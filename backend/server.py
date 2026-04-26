from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Request
from fastapi.responses import Response, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime
import cv2
import numpy as np
import base64
from io import BytesIO
from PIL import Image
import asyncio
import struct
import zlib

# For AI-powered stencil generation
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
# Backup: OpenAI image generation
from emergentintegrations.llm.openai.image_generation import OpenAIImageGeneration

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Get AI API keys
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY', '')
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')

# Primary: Google API key, Backup: Emergent key for OpenAI
AI_API_KEY = GOOGLE_API_KEY if GOOGLE_API_KEY else EMERGENT_LLM_KEY

if not AI_API_KEY and not EMERGENT_LLM_KEY:
    logger_temp = logging.getLogger(__name__)
    logger_temp.error("No AI API key configured! Please set GOOGLE_API_KEY or EMERGENT_LLM_KEY")

# Track API key failures for admin visibility
async def log_key_failure(key_name: str, error_msg: str, fallback_used: str):
    """Log API key failures to MongoDB so the admin can monitor key health"""
    try:
        from datetime import datetime, timezone
        await db.api_key_alerts.insert_one({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "failed_key": key_name,
            "error": error_msg,
            "fallback_used": fallback_used,
            "resolved": fallback_used != "none"
        })
        logger_temp = logging.getLogger(__name__)
        logger_temp.warning(f"[KEY ALERT] {key_name} failed: {error_msg}. Fallback: {fallback_used}")
    except Exception:
        pass  # Don't let logging failures break the app

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# In-memory job storage for async stencil generation
# In production, this could be Redis or MongoDB for persistence across restarts
stencil_jobs = {}

# Stencil cache for faster regeneration of same images
# Key: hash of image + settings, Value: generated stencil results
stencil_cache = {}
CACHE_MAX_SIZE = 50  # Maximum number of cached stencils

import hashlib

def get_cache_key(image_base64: str, style: str) -> str:
    """Generate a cache key from image content and style"""
    # Use first 1000 chars of base64 + style for faster hashing
    # This is sufficient to uniquely identify most images
    image_sample = image_base64[:1000] if len(image_base64) > 1000 else image_base64
    content = f"{image_sample}_{style}"
    return hashlib.md5(content.encode()).hexdigest()

def cache_stencil(cache_key: str, stencil_base64: str, near_black_fraction: Optional[float] = None):
    """Cache a generated stencil along with its near_black_fraction so a
    cache hit returns the same shape of response a fresh generation does."""
    global stencil_cache
    # Evict oldest if cache is full
    if len(stencil_cache) >= CACHE_MAX_SIZE:
        # Remove oldest entry (first key)
        oldest_key = next(iter(stencil_cache))
        del stencil_cache[oldest_key]
    stencil_cache[cache_key] = {
        'stencil': stencil_base64,
        'near_black_fraction': near_black_fraction,
        'timestamp': datetime.utcnow()
    }
    logger.info(f"[Cache] Cached stencil, total cached: {len(stencil_cache)}")

def get_cached_stencil(cache_key: str) -> Optional[dict]:
    """Retrieve a cached stencil entry if available. Returns the full dict
    (with 'stencil' and 'near_black_fraction') so callers can echo the
    near_black_fraction on cache hits."""
    if cache_key in stencil_cache:
        logger.info(f"[Cache] Cache HIT - returning cached stencil")
        return stencil_cache[cache_key]
    return None

class StencilJob:
    def __init__(self, job_id: str, image_base64: str, settings: dict, auto_enhance: bool = True, single_style: str = None):
        self.job_id = job_id
        self.image_base64 = image_base64
        self.settings = settings
        self.auto_enhance = auto_enhance  # Whether to use AI enhancement
        self.single_style = single_style  # If set, only generate this style
        self.status = "pending"  # pending, enhancing, processing, completed, failed
        self.progress = 0  # 0-100
        self.current_style = None  # light, medium, heavy
        self.enhanced_image = None  # Store enhanced image for all stencil generations
        self.result = {
            "light": None,
            "medium": None,
            "heavy": None
        }
        self.error = None
        self.created_at = datetime.utcnow()
        self.completed_at = None

# Define Models
class StencilSettings(BaseModel):
    clarity: float = Field(default=50.0, ge=0, le=100)  # Controls edge detection threshold
    line_weight: float = Field(default=50.0, ge=0, le=100)  # Controls line thickness
    noise_reduction: float = Field(default=50.0, ge=0, le=100)  # Controls blur/smoothing
    invert: bool = Field(default=True)  # Invert colors (white lines on black vs black lines on white)

class ProcessImageRequest(BaseModel):
    image_base64: str
    settings: StencilSettings = Field(default_factory=StencilSettings)

class ProcessImageResponse(BaseModel):
    stencil_base64: str
    processing_time_ms: float

class SavedStencil(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_image: str  # base64
    stencil_image: str  # base64
    stencil_thumbnail: Optional[str] = None  # base64 thumbnail for gallery view
    settings: StencilSettings
    created_at: datetime = Field(default_factory=datetime.utcnow)
    name: Optional[str] = None

class StencilListItem(BaseModel):
    """Lightweight model for gallery list view - no full images"""
    id: str
    stencil_thumbnail: Optional[str] = None
    created_at: datetime
    name: Optional[str] = None

class SaveStencilRequest(BaseModel):
    original_image: str
    stencil_image: str
    settings: StencilSettings
    name: Optional[str] = None

def base64_to_cv2(base64_string: str) -> np.ndarray:
    """Convert base64 image to OpenCV format"""
    # Remove data URL prefix if present
    if ',' in base64_string:
        base64_string = base64_string.split(',')[1]
    
    img_data = base64.b64decode(base64_string)
    img_array = np.frombuffer(img_data, np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    return img

def cv2_to_base64(img: np.ndarray) -> str:
    """Convert OpenCV image to base64"""
    _, buffer = cv2.imencode('.png', img)
    base64_string = base64.b64encode(buffer).decode('utf-8')
    return f"data:image/png;base64,{base64_string}"

# ============================================
# PROFESSIONAL STENCIL PIPELINE
from PIL import Image as PILImage


def apply_line_weight_control(binary: np.ndarray, weight: int = 0) -> np.ndarray:
    """
    Apply morphological dilation/erosion to control line thickness.
    
    Args:
        binary: Binary image (black lines on white)
        weight: -5 to +5 (-5 = thinnest, 0 = original, +5 = thickest)
    
    Returns:
        Binary image with adjusted line weight
    """
    if weight == 0:
        return binary
    
    # Convert to grayscale if needed
    if len(binary.shape) == 3:
        gray = cv2.cvtColor(binary, cv2.COLOR_BGR2GRAY)
    else:
        gray = binary
    
    # Create kernel based on weight magnitude
    kernel_size = abs(weight) + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    
    if weight > 0:
        # Positive weight = thicker lines (dilate the black)
        inverted = cv2.bitwise_not(gray)
        dilated = cv2.dilate(inverted, kernel, iterations=1)
        result = cv2.bitwise_not(dilated)
        logger.info(f"[LineWeight] Thickening lines: +{weight}")
    else:
        # Negative weight = thinner lines (erode the black)
        inverted = cv2.bitwise_not(gray)
        eroded = cv2.erode(inverted, kernel, iterations=1)
        result = cv2.bitwise_not(eroded)
        logger.info(f"[LineWeight] Thinning lines: {weight}")
    
    # Ensure binary
    _, result = cv2.threshold(result, 127, 255, cv2.THRESH_BINARY)
    
    return cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)


# ============================================
# IMAGE QUALITY VALIDATOR
# ============================================

class ImageQualityResult(BaseModel):
    """Result of image quality validation"""
    is_valid: bool = True
    warnings: List[str] = []
    errors: List[str] = []
    blur_score: float = 0.0
    brightness_score: float = 0.0
    resolution: tuple = (0, 0)
    suggestions: List[str] = []

def validate_image_quality(base64_string: str) -> ImageQualityResult:
    """Validate image quality before AI processing.
    
    Checks for:
    - Blur (using Laplacian variance)
    - Brightness/exposure issues
    - Resolution requirements
    - Overall quality score
    
    Returns warnings and suggestions to help users get better results.
    """
    result = ImageQualityResult()
    
    try:
        # Decode image
        if ',' in base64_string:
            base64_data = base64_string.split(',')[1]
        else:
            base64_data = base64_string
        
        img_data = base64.b64decode(base64_data)
        img = Image.open(BytesIO(img_data))
        
        # Convert to OpenCV format
        img_cv = cv2.cvtColor(np.array(img.convert('RGB')), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        
        height, width = img_cv.shape[:2]
        result.resolution = (width, height)
        
        # === CHECK 1: Resolution ===
        min_dimension = 500
        if width < min_dimension or height < min_dimension:
            result.warnings.append(f"Low resolution ({width}x{height})")
            result.suggestions.append("Use a higher resolution image (at least 500x500) for better stencil detail")
        
        max_dimension = 4000
        if width > max_dimension or height > max_dimension:
            result.warnings.append(f"Very high resolution ({width}x{height}) - will be resized")
        
        # === CHECK 2: Blur Detection ===
        # Laplacian variance - higher = sharper, lower = blurrier
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        result.blur_score = laplacian_var
        
        blur_threshold_bad = 50  # Very blurry
        blur_threshold_warn = 100  # Somewhat blurry
        
        if laplacian_var < blur_threshold_bad:
            result.warnings.append("Image appears very blurry")
            result.suggestions.append("Use a sharper, more focused image for cleaner stencil lines")
        elif laplacian_var < blur_threshold_warn:
            result.warnings.append("Image appears slightly blurry")
            result.suggestions.append("A sharper image would produce better results")
        
        # === CHECK 3: Brightness/Exposure ===
        mean_brightness = np.mean(gray)
        result.brightness_score = mean_brightness
        
        if mean_brightness < 40:
            result.warnings.append("Image appears too dark")
            result.suggestions.append("Use a brighter image or one with better lighting")
        elif mean_brightness > 220:
            result.warnings.append("Image appears overexposed")
            result.suggestions.append("Use an image with less harsh lighting")
        
        # === CHECK 4: Contrast ===
        std_dev = np.std(gray)
        if std_dev < 30:
            result.warnings.append("Image has low contrast")
            result.suggestions.append("An image with more contrast will produce clearer stencil lines")
        
        # Determine overall validity
        # We don't block processing, just warn - let users decide
        result.is_valid = True  # Always allow processing, just with warnings
        
        logger.info(f"[QualityCheck] Resolution: {width}x{height}, Blur: {laplacian_var:.1f}, Brightness: {mean_brightness:.1f}, Contrast: {std_dev:.1f}")
        
        if result.warnings:
            logger.info(f"[QualityCheck] Warnings: {result.warnings}")
        
    except Exception as e:
        logger.error(f"[QualityCheck] Error validating image: {str(e)}")
        result.is_valid = True  # Don't block on validation errors
        
    return result

# ============================================
# EXIF ORIENTATION FIX
# ============================================

def fix_exif_orientation(base64_string: str) -> str:
    """Fix image orientation based on EXIF data.
    
    Many phone cameras store rotation in EXIF metadata rather than
    actually rotating the image. This can cause alignment issues.
    This function reads EXIF and rotates the image correctly.
    """
    try:
        # Decode image
        if ',' in base64_string:
            prefix = base64_string.split(',')[0] + ','
            base64_data = base64_string.split(',')[1]
        else:
            prefix = "data:image/jpeg;base64,"
            base64_data = base64_string
        
        img_data = base64.b64decode(base64_data)
        img = Image.open(BytesIO(img_data))
        
        # Check for EXIF orientation
        try:
            from PIL.ExifTags import TAGS
            exif = img._getexif()
            if exif:
                for tag_id, value in exif.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag == 'Orientation':
                        logger.info(f"[EXIF] Found orientation tag: {value}")
                        
                        # Apply rotation based on orientation value
                        if value == 2:
                            img = img.transpose(Image.FLIP_LEFT_RIGHT)
                        elif value == 3:
                            img = img.rotate(180)
                        elif value == 4:
                            img = img.transpose(Image.FLIP_TOP_BOTTOM)
                        elif value == 5:
                            img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(270)
                        elif value == 6:
                            img = img.rotate(270, expand=True)
                        elif value == 7:
                            img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(90)
                        elif value == 8:
                            img = img.rotate(90, expand=True)
                        
                        # Convert back to base64
                        buffer = BytesIO()
                        # Determine format
                        fmt = 'JPEG' if 'jpeg' in prefix.lower() or 'jpg' in prefix.lower() else 'PNG'
                        img.save(buffer, format=fmt, quality=95)
                        fixed_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                        
                        logger.info(f"[EXIF] Applied orientation fix for value {value}")
                        return f"{prefix}{fixed_base64}"
                        
        except (AttributeError, KeyError, TypeError) as e:
            # No EXIF data or no orientation tag - that's fine
            pass
        
        return base64_string  # Return original if no fix needed
        
    except Exception as e:
        logger.error(f"[EXIF] Error fixing orientation: {str(e)}")
        return base64_string  # Return original on error

# ============================================
# STENCIL POST-PROCESSING
# ============================================

def post_process_stencil(base64_string: str) -> tuple[str, float]:
    """Post-process AI-generated stencil to create a TRANSPARENT PNG.

    Value-preserving pipeline — NO thresholding, NO flattening.

    Returns:
        (data_url, near_black_fraction)
        - data_url: PNG data URL with alpha-matted transparent background
        - near_black_fraction: fraction of pixels darker than 40/255 in the raw
          model output (before alpha matting). Callers can surface this to
          clients as a signal that the model may have violated the zero-fill
          rule. Typical clean outputs: 3-5%. >5% indicates possible fills.
    """
    try:
        logger.info("[PostProcess] Starting stencil post-processing (value-preserving)...")

        # Decode image
        if ',' in base64_string:
            base64_data = base64_string.split(',')[1]
        else:
            base64_data = base64_string

        img_data = base64.b64decode(base64_data)
        img = Image.open(BytesIO(img_data))

        # Grayscale (preserves full 0–255 line-value range)
        gray = np.asarray(img.convert('L'))  # shape: (H, W), dtype uint8
        h, w = gray.shape
        logger.info(f"[PostProcess] Grayscale preserved (shape={h}x{w})")

        # Diagnostic: measure large solid-dark regions in the AI output. If the
        # model violated the zero-fill rule, this number is the evidence.
        # We count pixels darker than 40/255 (near-black) as a fraction of image.
        dark_fraction = float((gray < 40).sum()) / float(h * w)
        if dark_fraction > 0.05:
            logger.warning(
                f"[PostProcess] FILL VIOLATION SUSPECTED: {dark_fraction*100:.1f}% of "
                f"pixels are near-black (>5% threshold). Model output may contain solid fills."
            )
        else:
            logger.info(f"[PostProcess] Fill check passed (near-black pixels: {dark_fraction*100:.2f}%)")

        # Background removal via inverted-alpha:
        #   pure white (255)  -> alpha 0   (transparent)
        #   near-white (250)  -> alpha 5   (nearly transparent)
        #   mid-gray (128)    -> alpha 127 (semi-transparent)
        #   pure black (0)    -> alpha 255 (solid)
        alpha = 255 - gray

        # RGB = black everywhere. With the alpha matte above, this produces
        # anti-aliased black line work whose softness matches the model output.
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[..., 3] = alpha  # R, G, B stay 0; A carries the line intensity

        logger.info("[PostProcess] Transparent PNG composed — line values preserved, no threshold applied")

        result_img = Image.fromarray(rgba, 'RGBA')
        buffer = BytesIO()
        result_img.save(buffer, format='PNG')
        result_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        logger.info("[PostProcess] Stencil post-processing complete")
        return f"data:image/png;base64,{result_base64}", dark_fraction

    except Exception as e:
        logger.error(f"[PostProcess] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return base64_string, 0.0  # Return original on error

def generate_thumbnail(base64_string: str, max_size: int = 150) -> str:
    """Generate a thumbnail from a base64 image for gallery preview
    
    Args:
        base64_string: The original base64 encoded image
        max_size: Maximum dimension (width or height) of the thumbnail
        
    Returns:
        Base64 encoded thumbnail image
    """
    try:
        # Remove data URL prefix if present
        if ',' in base64_string:
            base64_data = base64_string.split(',')[1]
        else:
            base64_data = base64_string
        
        # Decode the image
        img_data = base64.b64decode(base64_data)
        img = Image.open(BytesIO(img_data))
        
        # Calculate thumbnail size maintaining aspect ratio
        width, height = img.size
        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))
        
        # Resize image with high quality
        thumbnail = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Convert back to base64
        buffer = BytesIO()
        thumbnail.save(buffer, format='PNG', optimize=True)
        thumbnail_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return f"data:image/png;base64,{thumbnail_base64}"
    except Exception as e:
        logger.error(f"Error generating thumbnail: {str(e)}")
        return ""  # Return empty string if thumbnail generation fails

def resize_image_if_needed(base64_string: str, max_dimension: int = 2000, max_file_size_mb: float = 4.0) -> str:
    """Resize image if it's too large to prevent AI processing failures
    
    Args:
        base64_string: The original base64 encoded image
        max_dimension: Maximum width or height in pixels (default 2000)
        max_file_size_mb: Maximum file size in MB (default 4MB)
        
    Returns:
        Base64 encoded image (resized if necessary, original if within limits)
    """
    try:
        # Remove data URL prefix if present
        prefix = ""
        if ',' in base64_string:
            prefix_parts = base64_string.split(',')
            prefix = prefix_parts[0] + ","
            base64_data = prefix_parts[1]
        else:
            base64_data = base64_string
        
        # Check file size
        img_data = base64.b64decode(base64_data)
        file_size_mb = len(img_data) / (1024 * 1024)
        
        # Open image to check dimensions
        img = Image.open(BytesIO(img_data))
        width, height = img.size
        
        # Determine if resizing is needed
        needs_resize = False
        if width > max_dimension or height > max_dimension:
            needs_resize = True
            logger.info(f"Image dimensions ({width}x{height}) exceed max ({max_dimension}), will resize")
        if file_size_mb > max_file_size_mb:
            needs_resize = True
            logger.info(f"Image size ({file_size_mb:.2f}MB) exceeds max ({max_file_size_mb}MB), will resize")
        
        if not needs_resize:
            return base64_string  # Return original if no resize needed
        
        # Calculate new dimensions maintaining aspect ratio
        if width > height:
            if width > max_dimension:
                new_width = max_dimension
                new_height = int(height * (max_dimension / width))
            else:
                new_width = width
                new_height = height
        else:
            if height > max_dimension:
                new_height = max_dimension
                new_width = int(width * (max_dimension / height))
            else:
                new_width = width
                new_height = height
        
        # Convert to RGB if necessary (for JPEG compatibility)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # Resize image with high quality
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Save with compression - start with quality 85 and reduce if needed
        quality = 85
        buffer = BytesIO()
        resized.save(buffer, format='JPEG', quality=quality, optimize=True)
        
        # If still too large, reduce quality further
        while buffer.tell() / (1024 * 1024) > max_file_size_mb and quality > 50:
            quality -= 10
            buffer = BytesIO()
            resized.save(buffer, format='JPEG', quality=quality, optimize=True)
        
        resized_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        logger.info(f"Image resized from {width}x{height} ({file_size_mb:.2f}MB) to {new_width}x{new_height} ({buffer.tell()/(1024*1024):.2f}MB)")
        
        return f"data:image/jpeg;base64,{resized_base64}"
        
    except Exception as e:
        logger.error(f"Error resizing image: {str(e)}")
        return base64_string  # Return original if resize fails


def picsart_style_preprocess(base64_string: str) -> str:
    """PicsArt-style image preprocessing for optimal stencil generation.
    
    This applies three filters inspired by PicsArt:
    1. CLEAN filter - Edge-preserving noise reduction (bilateral filter)
    2. BLACK & WHITE HIGH CONTRAST - Dramatic B&W with S-curve contrast
    3. SHARPEN at 100% fade - Strong unsharp mask for crisp details
    
    These filters prepare the image for cleaner, more defined stencil output.
    
    Args:
        base64_string: The original base64 encoded image
        
    Returns:
        Base64 encoded preprocessed image (still in color for AI processing)
    """
    try:
        logger.info("[PicsArt-Preprocess] Starting PicsArt-style preprocessing...")
        
        # Remove data URL prefix if present
        if ',' in base64_string:
            prefix_parts = base64_string.split(',')
            base64_data = prefix_parts[1]
        else:
            base64_data = base64_string
        
        # Decode the image
        img_data = base64.b64decode(base64_data)
        img = Image.open(BytesIO(img_data))
        
        # Convert to RGB if necessary
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Convert to OpenCV format (BGR)
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        logger.info(f"[PicsArt-Preprocess] Image size: {img_cv.shape[1]}x{img_cv.shape[0]}")
        
        # ============================================================
        # STEP 1: CLEAN FILTER (Edge-preserving noise reduction)
        # Mimics PicsArt's "Clean" tool in Adjust menu
        # Uses bilateral filter which smooths while preserving edges
        # ============================================================
        logger.info("[PicsArt-Preprocess] Applying CLEAN filter (bilateral denoising)...")
        
        # Bilateral filter: preserves edges while reducing noise
        # d=9: diameter of pixel neighborhood
        # sigmaColor=75: filter sigma in color space (larger = more colors mixed)
        # sigmaSpace=75: filter sigma in coordinate space (larger = farther pixels influence)
        img_clean = cv2.bilateralFilter(img_cv, d=9, sigmaColor=75, sigmaSpace=75)
        
        # Additional pass with fastNlMeansDenoisingColored for extra cleaning
        # This removes fine grain/noise while keeping edges sharp
        try:
            # Ensure image is uint8 and contiguous for OpenCV
            img_clean_uint8 = np.ascontiguousarray(img_clean, dtype=np.uint8)
            img_clean = cv2.fastNlMeansDenoisingColored(img_clean_uint8, None, h=8, hForColorComponents=8, 
                                                         templateWindowSize=7, searchWindowSize=21)
        except Exception as denoise_error:
            logger.warning(f"[PicsArt-Preprocess] fastNlMeansDenoisingColored failed, skipping: {denoise_error}")
            # Continue with bilateral filter result only
        
        logger.info("[PicsArt-Preprocess] CLEAN filter applied")
        
        # ============================================================
        # STEP 2: BLACK & WHITE HIGH CONTRAST
        # Mimics PicsArt's "B&W HDR" filter effect
        # Converts to grayscale with enhanced contrast via S-curve
        # ============================================================
        logger.info("[PicsArt-Preprocess] Applying B&W HIGH CONTRAST filter...")
        
        # Convert to grayscale using luminance-preserving formula
        gray = cv2.cvtColor(img_clean, cv2.COLOR_BGR2GRAY)
        
        # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        # This mimics HDR-like local contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(gray)
        
        # Apply S-curve for dramatic high contrast (like PicsArt B&W HDR)
        # S-curve: darks get darker, lights get lighter, midtones shift
        def apply_s_curve(img, strength=1.5):
            """Apply S-curve contrast enhancement"""
            # Normalize to 0-1
            normalized = img.astype(np.float32) / 255.0
            # S-curve formula: shifts midtones, crushes blacks, lifts whites
            # Using sigmoid-like curve with adjustable strength
            midpoint = 0.5
            curved = 1 / (1 + np.exp(-strength * 10 * (normalized - midpoint)))
            # Scale back to 0-255
            return np.clip(curved * 255, 0, 255).astype(np.uint8)
        
        gray_contrast = apply_s_curve(gray_clahe, strength=1.2)
        
        # Additional contrast boost - stretch histogram
        # This ensures full dynamic range usage
        min_val, max_val = np.percentile(gray_contrast, [2, 98])
        gray_stretched = np.clip((gray_contrast - min_val) * 255 / (max_val - min_val), 0, 255).astype(np.uint8)
        
        # Convert back to BGR for next processing step
        img_bw_contrast = cv2.cvtColor(gray_stretched, cv2.COLOR_GRAY2BGR)
        
        logger.info("[PicsArt-Preprocess] B&W HIGH CONTRAST filter applied")
        
        # ============================================================
        # STEP 3: SHARPEN at 100% FADE
        # Mimics PicsArt's Sharpen tool at maximum intensity
        # Uses unsharp mask technique for professional sharpening
        # ============================================================
        logger.info("[PicsArt-Preprocess] Applying SHARPEN at 100% fade...")
        
        # Method 1: Kernel-based sharpening (strong)
        # This kernel emphasizes the center pixel while subtracting neighbors
        sharpen_kernel = np.array([[0, -1, 0],
                                   [-1, 5, -1],
                                   [0, -1, 0]], dtype=np.float32)
        img_sharp1 = cv2.filter2D(img_bw_contrast, -1, sharpen_kernel)
        
        # Method 2: Unsharp mask at 100% (full strength blend)
        # Subtract blurred version from original to enhance edges
        gaussian = cv2.GaussianBlur(img_sharp1, (0, 0), sigma=2.0)
        # At 100% fade: amount = 1.5 original - 0.5 blurred (strong unsharp mask)
        img_sharp2 = cv2.addWeighted(img_sharp1, 1.5, gaussian, -0.5, 0)
        
        # Method 3: One more pass with Laplacian edge enhancement
        # This adds extra edge definition for tattoo stencils
        laplacian = cv2.Laplacian(cv2.cvtColor(img_sharp2, cv2.COLOR_BGR2GRAY), cv2.CV_64F)
        laplacian = np.uint8(np.clip(np.absolute(laplacian), 0, 255))
        laplacian_3ch = cv2.cvtColor(laplacian, cv2.COLOR_GRAY2BGR)
        
        # Blend edges with sharpened image
        img_final = cv2.addWeighted(img_sharp2, 1.0, laplacian_3ch, 0.15, 0)
        
        logger.info("[PicsArt-Preprocess] SHARPEN at 100% applied")
        
        # Final clip to valid range
        img_final = np.clip(img_final, 0, 255).astype(np.uint8)
        
        # Convert back to PIL and encode as base64
        img_final_rgb = cv2.cvtColor(img_final, cv2.COLOR_BGR2RGB)
        result_img = Image.fromarray(img_final_rgb)
        
        buffer = BytesIO()
        result_img.save(buffer, format='JPEG', quality=95, optimize=True)
        preprocessed_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        logger.info("[PicsArt-Preprocess] Preprocessing complete - image optimized for stencil generation")
        
        return f"data:image/jpeg;base64,{preprocessed_base64}"
        
    except Exception as e:
        logger.error(f"[PicsArt-Preprocess] Error in preprocessing: {str(e)}")
        import traceback
        traceback.print_exc()
        return base64_string  # Return original if preprocessing fails


def enhance_photo_basic(base64_string: str) -> str:
    """Basic photo enhancement using OpenCV (no AI, fast).
    
    This preprocessing step helps capture finer details by:
    1. Boosting contrast to make edges more defined
    2. Applying sharpening to bring out fine details
    3. Using CLAHE for adaptive local contrast enhancement
    4. Subtle edge enhancement to make contours more visible
    
    Args:
        base64_string: The original base64 encoded image
        
    Returns:
        Base64 encoded enhanced image
    """
    try:
        logger.info("[PhotoEnhance] Starting basic photo enhancement...")
        
        # Remove data URL prefix if present
        prefix = ""
        if ',' in base64_string:
            prefix_parts = base64_string.split(',')
            prefix = prefix_parts[0] + ","
            base64_data = prefix_parts[1]
        else:
            base64_data = base64_string
        
        # Decode the image
        img_data = base64.b64decode(base64_data)
        img = Image.open(BytesIO(img_data))
        
        # Convert to RGB if necessary
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Convert to OpenCV format (BGR)
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        original_shape = img_cv.shape
        logger.info(f"[PhotoEnhance] Original image: {original_shape[1]}x{original_shape[0]}")
        
        # === STEP 1: CONTRAST ENHANCEMENT ===
        lab = cv2.cvtColor(img_cv, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        l_enhanced = clahe.apply(l_channel)
        lab_enhanced = cv2.merge([l_enhanced, a_channel, b_channel])
        img_contrast = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
        
        # === STEP 2: SHARPENING (Unsharp Mask) ===
        gaussian = cv2.GaussianBlur(img_contrast, (0, 0), 2.0)
        sharpening_amount = 0.7
        img_sharp = cv2.addWeighted(img_contrast, 1 + sharpening_amount, gaussian, -sharpening_amount, 0)
        
        # === STEP 3: SUBTLE EDGE ENHANCEMENT ===
        gray = cv2.cvtColor(img_sharp, cv2.COLOR_BGR2GRAY)
        edges = cv2.Laplacian(gray, cv2.CV_64F)
        edges = np.uint8(np.absolute(edges))
        edges_3channel = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        edge_boost = 0.08
        img_edge_enhanced = cv2.addWeighted(img_sharp, 1.0, edges_3channel, edge_boost, 0)
        
        # === STEP 4: FINAL CONTRAST BOOST ===
        alpha = 1.15
        beta = -10
        img_final = cv2.convertScaleAbs(img_edge_enhanced, alpha=alpha, beta=beta)
        img_final = np.clip(img_final, 0, 255).astype(np.uint8)
        
        # Convert back to PIL and then to base64
        img_final_rgb = cv2.cvtColor(img_final, cv2.COLOR_BGR2RGB)
        result_img = Image.fromarray(img_final_rgb)
        
        buffer = BytesIO()
        result_img.save(buffer, format='JPEG', quality=95, optimize=True)
        enhanced_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        logger.info(f"[PhotoEnhance] Basic enhancement complete")
        
        return f"data:image/jpeg;base64,{enhanced_base64}"
        
    except Exception as e:
        logger.error(f"[PhotoEnhance] Error in basic enhancement: {str(e)}")
        import traceback
        traceback.print_exc()
        return base64_string


async def enhance_photo_with_ai(base64_string: str) -> str:
    """AI-powered photo enhancement using Gemini for upscaling and quality improvement.
    
    This uses Gemini to:
    1. Upscale low-resolution images
    2. Sharpen and enhance details
    3. Improve overall image quality for better stencil generation
    
    Args:
        base64_string: The original base64 encoded image
        
    Returns:
        Base64 encoded AI-enhanced image
    """
    from google import genai
    from google.genai import types
    
    try:
        logger.info("[AIEnhance] Starting AI-powered photo enhancement...")
        
        # Remove data URL prefix if present
        if ',' in base64_string:
            base64_data = base64_string.split(',')[1]
        else:
            base64_data = base64_string
        
        # Decode to check resolution
        img_data = base64.b64decode(base64_data)
        img = Image.open(BytesIO(img_data))
        width, height = img.size
        logger.info(f"[AIEnhance] Original resolution: {width}x{height}")
        
        # Configure Gemini with new SDK - try keys in order
        keys_to_try = []
        if GOOGLE_API_KEY:
            keys_to_try.append(("Google API Key", GOOGLE_API_KEY))
        if EMERGENT_LLM_KEY:
            keys_to_try.append(("Emergent LLM Key", EMERGENT_LLM_KEY))
        
        if not keys_to_try:
            logger.warning("[AIEnhance] No API keys available, falling back to basic enhancement")
            return enhance_photo_basic(base64_string)
        
        # Create enhancement prompt based on image issues
        needs_upscale = width < 1500 or height < 1500
        
        enhancement_prompt = """PHOTO ENHANCEMENT FOR TATTOO STENCIL CREATION

You are enhancing a photo that will be converted into a professional tattoo stencil.

ENHANCEMENT GOALS:
1. SHARPEN all details - especially fine features like hair strands, facial features, jewelry, and texture
2. ENHANCE CONTRAST to make edges and contours more defined
3. REDUCE NOISE while preserving important details
4. IMPROVE CLARITY so the AI stencil generator can trace clean lines"""
        
        if needs_upscale:
            enhancement_prompt += f"""
5. UPSCALE the image to approximately 2000 pixels on the longest edge (current: {width}x{height})
   - Maintain aspect ratio
   - Add realistic detail during upscaling, not just interpolation
   - Make sure small details become clearer, not blurry"""
        
        enhancement_prompt += """

IMPORTANT:
- Keep the subject EXACTLY as it is - do NOT change pose, expression, or composition
- Do NOT add, remove, or modify any elements in the photo
- Do NOT apply artistic filters or style changes
- Just enhance the QUALITY of the existing photo
- Output should be a high-quality photo, NOT a stencil or drawing

Output the enhanced photo now."""

        # Call Gemini for enhancement using new SDK - try each key
        image_bytes = base64.b64decode(base64_data)
        
        for key_name, api_key in keys_to_try:
            try:
                logger.info(f"[AIEnhance] Trying {key_name}...")
                client = genai.Client(api_key=api_key)
                
                response = client.models.generate_content(
                    model='gemini-2.5-flash-image',
                    contents=[
                        enhancement_prompt,
                        types.Part.from_bytes(data=image_bytes, mime_type="image/png")
                    ],
                    config=types.GenerateContentConfig(
                        response_modalities=['IMAGE', 'TEXT']
                    )
                )
                
                # Extract the enhanced image
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            enhanced_base64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                            mime_type = part.inline_data.mime_type or 'image/png'
                            
                            # Verify the enhanced image
                            enhanced_img = Image.open(BytesIO(part.inline_data.data))
                            new_width, new_height = enhanced_img.size
                            logger.info(f"[AIEnhance] Enhanced resolution: {new_width}x{new_height} (using {key_name})")
                            
                            return f"data:{mime_type};base64,{enhanced_base64}"
                
                logger.warning(f"[AIEnhance] {key_name} returned no image, trying next key...")
            except Exception as key_err:
                logger.warning(f"[AIEnhance] {key_name} failed: {str(key_err)}, trying next key...")
                continue
        
        logger.warning("[AIEnhance] Gemini did not return enhanced image, falling back to basic enhancement")
        return enhance_photo_basic(base64_string)
        
    except Exception as e:
        logger.error(f"[AIEnhance] Error in AI enhancement: {str(e)}")
        import traceback
        traceback.print_exc()
        # Fall back to basic enhancement
        logger.info("[AIEnhance] Falling back to basic enhancement")
        return enhance_photo_basic(base64_string)


def enhance_photo_for_ai(base64_string: str) -> str:
    """Wrapper that uses basic enhancement (sync version for backward compatibility).
    
    For AI enhancement, use enhance_photo_with_ai() directly.
    """
    return enhance_photo_basic(base64_string)

def process_image_to_stencil(img: np.ndarray, settings: StencilSettings) -> np.ndarray:
    """Process image to create tattoo stencil using advanced edge detection
    
    This creates clean, detailed line drawings similar to professional stencil apps.
    Uses multiple techniques combined for best results.
    """
    
    height, width = img.shape[:2]
    
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # === STEP 1: Noise Reduction (controlled by setting) ===
    # Lower noise_reduction = more detail preserved
    # Higher noise_reduction = cleaner, simpler output
    noise_level = settings.noise_reduction / 100
    
    # Light bilateral filter to preserve edges while reducing noise
    d = int(5 + noise_level * 4)  # 5-9 diameter
    sigma_color = int(50 + noise_level * 50)  # 50-100
    sigma_space = int(50 + noise_level * 50)  # 50-100
    denoised = cv2.bilateralFilter(gray, d=d, sigmaColor=sigma_color, sigmaSpace=sigma_space)
    
    # === STEP 2: Enhance Contrast for Better Edge Detection ===
    # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    
    # === STEP 3: Multi-scale Edge Detection ===
    # Clarity controls edge sensitivity (lower = more edges/detail)
    clarity_factor = settings.clarity / 100
    
    # Canny edge detection with adaptive thresholds
    # Lower thresholds = more edges captured
    median_val = np.median(enhanced)
    lower = int(max(10, (1 - clarity_factor) * median_val * 0.5))
    upper = int(min(255, (1 + clarity_factor * 0.5) * median_val))
    
    edges_canny = cv2.Canny(enhanced, lower, upper)
    
    # === STEP 4: Adaptive Thresholding for Additional Details ===
    # This captures details that Canny might miss
    block_size = int(11 + (1 - clarity_factor) * 10)  # 11-21
    if block_size % 2 == 0:
        block_size += 1
    
    # Adaptive threshold captures local variations
    adaptive = cv2.adaptiveThreshold(
        enhanced, 255, 
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY_INV,
        block_size, 
        int(2 + clarity_factor * 3)  # C constant: 2-5
    )
    
    # === STEP 5: Combine Edge Methods ===
    # Merge Canny edges with adaptive threshold result
    # More detail at lower clarity
    if clarity_factor < 0.5:
        # More detail mode - use more adaptive threshold
        combined = cv2.bitwise_or(edges_canny, adaptive)
    else:
        # Cleaner mode - primarily use Canny
        # Dilate Canny slightly to connect broken edges
        kernel_connect = np.ones((2, 2), np.uint8)
        edges_connected = cv2.dilate(edges_canny, kernel_connect, iterations=1)
        combined = edges_connected
    
    # === STEP 6: Clean Up Small Noise ===
    # Remove very small isolated pixels
    kernel_clean = np.ones((2, 2), np.uint8)
    cleaned = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel_clean)
    
    # === STEP 7: Apply Line Weight ===
    line_weight_factor = settings.line_weight / 100
    
    if line_weight_factor > 0.1:
        # Dilate to thicken lines
        kernel_size = max(1, int(1 + line_weight_factor * 3))
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        final_edges = cv2.dilate(cleaned, kernel, iterations=1)
    else:
        final_edges = cleaned
    
    # === STEP 8: Create Final Output ===
    if settings.invert:
        # White background, black lines (typical stencil look)
        stencil = 255 - final_edges
    else:
        # Black background, white lines
        stencil = final_edges
    
    # Convert to 3 channel for consistent output
    stencil_rgb = cv2.cvtColor(stencil, cv2.COLOR_GRAY2BGR)
    
    return stencil_rgb

def remove_background(img: np.ndarray, method: str = "auto") -> np.ndarray:
    """Remove background from image while preserving the main subject"""
    
    height, width = img.shape[:2]
    
    if method == "grabcut":
        # GrabCut algorithm with better initialization
        mask = np.zeros((height, width), np.uint8)
        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)
        
        # Use a smaller margin to keep more of the subject
        margin_x = int(width * 0.02)
        margin_y = int(height * 0.02)
        rect = (margin_x, margin_y, width - 2*margin_x, height - 2*margin_y)
        
        # Apply GrabCut with more iterations for better accuracy
        cv2.grabCut(img, mask, rect, bgd_model, fgd_model, 8, cv2.GC_INIT_WITH_RECT)
        
        # Create mask where sure/probable foreground is 1
        mask2 = np.where((mask == 2) | (mask == 0), 0, 1).astype('uint8')
        
        # Dilate the mask slightly to avoid cutting into the subject
        kernel = np.ones((3, 3), np.uint8)
        mask2 = cv2.dilate(mask2, kernel, iterations=2)
        
    elif method == "threshold":
        # Simple threshold-based removal - good for light/white backgrounds
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Check if background is light (white/light gray)
        corners = [gray[0:10, 0:10], gray[0:10, -10:], gray[-10:, 0:10], gray[-10:, -10:]]
        avg_corner = np.mean([np.mean(c) for c in corners])
        
        if avg_corner > 200:  # Light background
            _, mask2 = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
        else:  # Dark background
            _, mask2 = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
        
        mask2 = mask2 // 255
        
        # Clean up the mask
        kernel = np.ones((5, 5), np.uint8)
        mask2 = cv2.morphologyEx(mask2, cv2.MORPH_CLOSE, kernel)
        mask2 = cv2.morphologyEx(mask2, cv2.MORPH_OPEN, kernel)
        
    else:  # "auto" - use GrabCut with smart initialization
        # Convert to different color spaces for better segmentation
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Detect edges to help identify subject boundaries
        edges = cv2.Canny(gray, 50, 150)
        kernel = np.ones((5, 5), np.uint8)
        edges_dilated = cv2.dilate(edges, kernel, iterations=2)
        
        # Use GrabCut with the center region as probable foreground
        mask = np.zeros((height, width), np.uint8)
        
        # Mark center region as probable foreground
        center_margin_x = int(width * 0.15)
        center_margin_y = int(height * 0.15)
        mask[center_margin_y:height-center_margin_y, center_margin_x:width-center_margin_x] = cv2.GC_PR_FGD
        
        # Mark edges near center as definite foreground
        center_mask = np.zeros((height, width), np.uint8)
        center_mask[center_margin_y:height-center_margin_y, center_margin_x:width-center_margin_x] = 255
        edges_in_center = cv2.bitwise_and(edges_dilated, center_mask)
        mask[edges_in_center > 0] = cv2.GC_FGD
        
        # Mark corners as probable background
        corner_size = int(min(width, height) * 0.1)
        mask[0:corner_size, 0:corner_size] = cv2.GC_PR_BGD
        mask[0:corner_size, width-corner_size:] = cv2.GC_PR_BGD
        mask[height-corner_size:, 0:corner_size] = cv2.GC_PR_BGD
        mask[height-corner_size:, width-corner_size:] = cv2.GC_PR_BGD
        
        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)
        
        # Run GrabCut with mask initialization
        try:
            cv2.grabCut(img, mask, None, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_MASK)
        except:
            # Fallback to rect-based if mask init fails
            margin = int(min(height, width) * 0.02)
            rect = (margin, margin, width - 2*margin, height - 2*margin)
            mask = np.zeros((height, width), np.uint8)
            cv2.grabCut(img, mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)
        
        # Create final mask - keep both definite and probable foreground
        mask2 = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype('uint8')
        
        # Dilate slightly to avoid cutting into subject
        kernel = np.ones((3, 3), np.uint8)
        mask2 = cv2.dilate(mask2, kernel, iterations=1)
        
        # Fill holes in the mask
        mask2 = cv2.morphologyEx(mask2, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    
    # Create output with transparent background (BGRA)
    result = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    result[:, :, 3] = mask2 * 255
    
    return result

def cv2_to_base64_png(img: np.ndarray) -> str:
    """Convert OpenCV image to base64 PNG (supports transparency)"""
    _, buffer = cv2.imencode('.png', img)
    base64_string = base64.b64encode(buffer).decode('utf-8')
    return f"data:image/png;base64,{base64_string}"


def adjust_stencil_line_weight(base64_string: str, adjustment: int) -> str:
    """Adjust the line weight of a stencil using morphological operations.
    
    This is a POST-AI-GENERATION adjustment that thins or thickens lines
    without changing the AI prompts or generation process.
    
    The stencil format is: BLACK lines on TRANSPARENT background.
    - Alpha channel: 255 where lines are, 0 where transparent
    - RGB channels: Black (0,0,0) where lines are
    
    Args:
        base64_string: The stencil image (transparent PNG with black lines)
        adjustment: Line weight adjustment from -5 (thinner) to +5 (thicker)
                   0 = no change, negative = erode (thin), positive = dilate (thick)
        
    Returns:
        Base64 encoded adjusted stencil PNG
    """
    try:
        logger.info(f"[LineWeight] Adjusting line weight by {adjustment}")
        
        if adjustment == 0:
            return base64_string  # No change needed
        
        # Remove data URL prefix if present
        if ',' in base64_string:
            base64_data = base64_string.split(',')[1]
        else:
            base64_data = base64_string
        
        # Decode the image
        img_data = base64.b64decode(base64_data)
        img_array = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_UNCHANGED)
        
        if img is None:
            logger.error("[LineWeight] Failed to decode image")
            return base64_string
        
        logger.info(f"[LineWeight] Image shape: {img.shape}")
        
        # Check if image has alpha channel (transparent PNG)
        has_alpha = len(img.shape) == 3 and img.shape[2] == 4
        
        if has_alpha:
            # Extract the alpha channel - this is where the lines are defined
            # Alpha = 255 means opaque (line), Alpha = 0 means transparent (background)
            alpha = img[:, :, 3].copy()
            
            # Create morphological kernel - circular for smoother results
            kernel_size = abs(adjustment)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size * 2 + 1, kernel_size * 2 + 1))
            
            if adjustment > 0:
                # Positive = dilate the alpha = thicker lines
                alpha_adjusted = cv2.dilate(alpha, kernel, iterations=1)
                logger.info(f"[LineWeight] Applied dilation (thicker) with kernel size {kernel_size * 2 + 1}")
            else:
                # Negative = erode the alpha = thinner lines
                alpha_adjusted = cv2.erode(alpha, kernel, iterations=1)
                logger.info(f"[LineWeight] Applied erosion (thinner) with kernel size {kernel_size * 2 + 1}")
            
            # Create result image - keep original BGR, update alpha
            # Lines should remain BLACK, just the alpha (coverage) changes
            result = img.copy()
            result[:, :, 3] = alpha_adjusted
            
            # Ensure RGB stays black where there are lines
            # Only apply black color where alpha > 0
            result[:, :, 0] = np.where(alpha_adjusted > 0, 0, 0).astype(np.uint8)  # B
            result[:, :, 1] = np.where(alpha_adjusted > 0, 0, 0).astype(np.uint8)  # G
            result[:, :, 2] = np.where(alpha_adjusted > 0, 0, 0).astype(np.uint8)  # R
            
        else:
            # No alpha channel - need to create transparent PNG from grayscale/RGB
            if len(img.shape) == 2:
                gray = img
            else:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Assume dark pixels are lines, light pixels are background
            # Threshold to get line mask
            _, line_mask = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)
            
            kernel_size = abs(adjustment)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size * 2 + 1, kernel_size * 2 + 1))
            
            if adjustment > 0:
                line_mask = cv2.dilate(line_mask, kernel, iterations=1)
            else:
                line_mask = cv2.erode(line_mask, kernel, iterations=1)
            
            # Create BGRA with black lines and transparency
            result = np.zeros((gray.shape[0], gray.shape[1], 4), dtype=np.uint8)
            result[:, :, 3] = line_mask  # Alpha from line mask
            # RGB stays 0 (black) where lines are
        
        # Encode as PNG
        _, buffer = cv2.imencode('.png', result)
        adjusted_base64 = base64.b64encode(buffer).decode('utf-8')
        
        logger.info("[LineWeight] Line weight adjustment complete")
        return f"data:image/png;base64,{adjusted_base64}"
        
    except Exception as e:
        logger.error(f"[LineWeight] Error adjusting line weight: {str(e)}")
        import traceback
        traceback.print_exc()
        return base64_string


class AdjustLineWeightRequest(BaseModel):
    image_base64: str = Field(..., description="Base64 encoded stencil image")
    adjustment: int = Field(..., ge=-5, le=5, description="Line weight adjustment: -5 (thinnest) to +5 (thickest)")


class AdjustLineWeightResponse(BaseModel):
    adjusted_image: str = Field(..., description="Base64 encoded adjusted stencil")
    adjustment_applied: int = Field(..., description="The adjustment value that was applied")


# API Routes
@api_router.post("/adjust-line-weight", response_model=AdjustLineWeightResponse)
async def adjust_line_weight_endpoint(request: AdjustLineWeightRequest):
    """Adjust the line weight of a generated stencil.
    
    This is a post-processing operation that thins or thickens the stencil lines
    using morphological operations. It does not affect AI generation.
    
    - Negative values (-5 to -1): Thin the lines (erosion)
    - Zero (0): No change
    - Positive values (1 to 5): Thicken the lines (dilation)
    """
    try:
        adjusted = adjust_stencil_line_weight(request.image_base64, request.adjustment)
        return AdjustLineWeightResponse(
            adjusted_image=adjusted,
            adjustment_applied=request.adjustment
        )
    except Exception as e:
        logger.error(f"[API] Line weight adjustment error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/")
async def root():
    return {"message": "Tattoo Stencil API", "version": "1.0"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "tattoo-stencil-api"}

@api_router.get("/admin/user-lookup")
async def admin_user_lookup(email: str = None, user_id: str = None):
    """Admin endpoint to look up a user's account and subscription status"""
    if not email and not user_id:
        raise HTTPException(status_code=400, detail="Provide email or user_id")
    
    query = {}
    if email:
        query['email'] = {'$regex': email, '$options': 'i'}
    if user_id:
        query['user_id'] = user_id
    
    user = await db.users.find_one(query, {'_id': 0})
    if not user:
        return {"found": False, "message": "No user found with that email/id"}
    
    uid = user.get('user_id', '')
    sub = await db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    
    # Check for unmatched webhooks that might belong to this user
    unmatched = await db.unmatched_webhooks.find(
        {'reconciled': False}, {'_id': 0}
    ).to_list(50)
    
    return {
        "found": True,
        "user": user,
        "subscription": sub,
        "unmatched_webhooks_count": len(unmatched)
    }

@api_router.post("/admin/fix-subscription")
async def admin_fix_subscription(request: Request):
    """Admin endpoint to manually activate a customer's subscription"""
    body = await request.json()
    email = body.get('email', '')
    product_id = body.get('product_id', '')
    
    if not email or not product_id:
        raise HTTPException(status_code=400, detail="Provide email and product_id")
    
    tier_info = PRODUCT_CREDIT_MAP.get(product_id)
    if not tier_info:
        raise HTTPException(status_code=400, detail=f"Invalid product_id. Valid: {list(PRODUCT_CREDIT_MAP.keys())}")
    
    user = await db.users.find_one({'email': {'$regex': email, '$options': 'i'}}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    uid = user['user_id']
    
    await db.subscriptions.update_one(
        {'user_id': uid},
        {'$set': {
            'tier': tier_info['tier'],
            'available_credits': tier_info['credits'],
            'is_trial': False,
            'last_event': 'ADMIN_FIX',
            'synced_from': 'admin_manual',
            'renewal_date': (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        }},
        upsert=True
    )
    
    updated = await db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    return {
        "status": "fixed",
        "user_email": email,
        "user_id": uid,
        "subscription": updated
    }

@api_router.get("/diagnostics")
async def diagnostics(request: Request):
    """Diagnostic endpoint - returns HTML dashboard or JSON based on Accept header"""
    import importlib
    from starlette.responses import HTMLResponse
    
    results = {}
    
    # Check API keys
    results["google_api_key_set"] = bool(GOOGLE_API_KEY)
    results["google_api_key_prefix"] = GOOGLE_API_KEY[:8] + "..." if GOOGLE_API_KEY else "NOT SET"
    results["emergent_llm_key_set"] = bool(EMERGENT_LLM_KEY)
    results["ai_api_key_set"] = bool(AI_API_KEY)
    
    # Check library versions
    try:
        import emergentintegrations
        results["emergentintegrations_version"] = getattr(emergentintegrations, '__version__', 'unknown')
    except ImportError:
        results["emergentintegrations_version"] = "NOT INSTALLED"
    
    try:
        import litellm
        results["litellm_version"] = getattr(litellm, '__version__', getattr(litellm, 'version', 'unknown'))
    except ImportError:
        results["litellm_version"] = "NOT INSTALLED"
    
    try:
        import google.generativeai
        results["google_generativeai_version"] = getattr(google.generativeai, '__version__', 'unknown')
    except ImportError:
        results["google_generativeai_version"] = "NOT INSTALLED"
    
    # Quick Gemini API test
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        api_key = GOOGLE_API_KEY or EMERGENT_LLM_KEY
        chat = LlmChat(api_key=api_key, session_id="diag-test", system_message="Reply with 'OK'")
        chat.with_model("gemini", "gemini-3-pro-image-preview").with_params(modalities=["text"])
        msg = UserMessage(text="Say OK")
        response = await chat.send_message(msg)
        results["gemini_api_test"] = "PASS" if response else "FAIL"
    except Exception as e:
        error_str = str(e)
        if "expired" in error_str.lower() or "invalid" in error_str.lower():
            results["gemini_api_test"] = "FAIL - Key expired or invalid"
        else:
            results["gemini_api_test"] = f"FAIL - {error_str[:100]}"
    
    # Recent key failure alerts (last 10)
    try:
        alerts = await db.api_key_alerts.find(
            {}, {"_id": 0}
        ).sort("timestamp", -1).limit(10).to_list(10)
        results["recent_key_alerts"] = alerts
        results["total_key_failures"] = await db.api_key_alerts.count_documents({})
    except Exception:
        results["recent_key_alerts"] = []
        results["total_key_failures"] = 0
    
    # If browser request, return nice HTML page
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        google_status = "Working" if results["gemini_api_test"] == "PASS" else "NOT Working"
        google_color = "#22c55e" if google_status == "Working" else "#ef4444"
        google_icon = "&#10004;" if google_status == "Working" else "&#10008;"
        
        emergent_status = "Available" if results["emergent_llm_key_set"] else "Not Set"
        emergent_color = "#22c55e" if results["emergent_llm_key_set"] else "#ef4444"
        
        alerts_html = ""
        if results["recent_key_alerts"]:
            for alert in results["recent_key_alerts"]:
                ts = alert.get("timestamp", "Unknown time")
                if "T" in str(ts):
                    ts = str(ts).replace("T", " ").split(".")[0] + " UTC"
                failed = alert.get("failed_key", "Unknown")
                fallback = alert.get("fallback_used", "none")
                resolved = alert.get("resolved", False)
                resolved_text = "Yes - Backup key used" if resolved else "No - Generation failed"
                resolved_color = "#22c55e" if resolved else "#ef4444"
                
                alerts_html += f"""
                <div style="background:#1a1a2e;border-radius:12px;padding:16px;margin-bottom:12px;border-left:4px solid {resolved_color};">
                    <div style="color:#999;font-size:13px;margin-bottom:6px;">{ts}</div>
                    <div style="color:#fff;font-size:15px;margin-bottom:4px;"><strong>{failed}</strong> failed</div>
                    <div style="color:{resolved_color};font-size:14px;">Recovered: {resolved_text}</div>
                </div>"""
        else:
            alerts_html = '<div style="color:#999;text-align:center;padding:20px;">No key failures recorded. Everything is running smoothly!</div>'
        
        html = f"""<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BODY BOUND - System Health</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0a0a0f; color:#fff; font-family:-apple-system,BlinkMacSystemFont,sans-serif; padding:20px; }}
  .header {{ text-align:center; margin-bottom:30px; padding:20px 0; }}
  .header h1 {{ color:#c4a44a; font-size:24px; letter-spacing:2px; }}
  .header p {{ color:#888; font-size:14px; margin-top:6px; }}
  .card {{ background:#12121f; border-radius:16px; padding:24px; margin-bottom:20px; }}
  .card h2 {{ color:#c4a44a; font-size:16px; letter-spacing:1px; margin-bottom:16px; text-transform:uppercase; }}
  .status-row {{ display:flex; justify-content:space-between; align-items:center; padding:12px 0; border-bottom:1px solid #1a1a2e; }}
  .status-row:last-child {{ border-bottom:none; }}
  .status-label {{ color:#999; font-size:14px; }}
  .status-value {{ font-size:15px; font-weight:600; }}
  .badge {{ display:inline-block; padding:4px 12px; border-radius:20px; font-size:13px; font-weight:600; }}
  .badge-green {{ background:#22c55e22; color:#22c55e; }}
  .badge-red {{ background:#ef444422; color:#ef4444; }}
  .badge-yellow {{ background:#eab30822; color:#eab308; }}
  .big-status {{ text-align:center; padding:20px; }}
  .big-status .icon {{ font-size:48px; margin-bottom:10px; }}
  .big-status .text {{ font-size:18px; font-weight:600; }}
  .footer {{ text-align:center; color:#555; font-size:12px; margin-top:30px; padding:20px; }}
</style>
</head><body>
<div class="header">
  <h1>BODY BOUND</h1>
  <p>System Health Dashboard</p>
</div>

<div class="card">
  <h2>API Key Status</h2>
  <div class="big-status">
    <div class="icon" style="color:{google_color};">{google_icon}</div>
    <div class="text" style="color:{google_color};">Google API Key: {google_status}</div>
  </div>
  <div class="status-row">
    <span class="status-label">Google Key</span>
    <span class="badge {"badge-green" if results["google_api_key_set"] else "badge-red"}">{results["google_api_key_prefix"]}</span>
  </div>
  <div class="status-row">
    <span class="status-label">Backup Key (Emergent)</span>
    <span class="badge {"badge-green" if results["emergent_llm_key_set"] else "badge-red"}">{emergent_status}</span>
  </div>
  <div class="status-row">
    <span class="status-label">Stencil Generation Test</span>
    <span class="badge {"badge-green" if results["gemini_api_test"] == "PASS" else "badge-red"}">{results["gemini_api_test"]}</span>
  </div>
</div>

<div class="card">
  <h2>Key Failure History</h2>
  <div class="status-row">
    <span class="status-label">Total failures recorded</span>
    <span class="badge {"badge-green" if results["total_key_failures"] == 0 else "badge-yellow"}">{results["total_key_failures"]}</span>
  </div>
  <div style="margin-top:16px;">
    {alerts_html}
  </div>
</div>

<div class="footer">
  Refresh this page anytime to check your system health.<br>
  If Google Key shows "NOT Working", the backup Emergent key is keeping your app running.
</div>
</body></html>"""
        return HTMLResponse(content=html)
    
    return results

@api_router.get("/admin/all-users")
async def admin_all_users():
    """List all users with their subscription status"""
    users = await db.users.find({}, {'_id': 0}).to_list(500)
    results = []
    for u in users:
        uid = u.get('user_id', '')
        sub = await db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
        results.append({
            "email": u.get('email', 'no email'),
            "name": u.get('name', 'no name'),
            "user_id": uid,
            "tier": sub.get('tier') if sub else None,
            "credits": sub.get('available_credits', 0) if sub else 0,
            "is_trial": sub.get('is_trial', False) if sub else False,
            "last_event": sub.get('last_event', 'none') if sub else 'none',
            "created_at": u.get('created_at', '')
        })
    return {"total": len(results), "users": results}

@api_router.post("/process", response_model=ProcessImageResponse)
async def process_image(request: ProcessImageRequest):
    """Process an image to create a tattoo stencil"""
    try:
        import time
        start_time = time.time()
        
        # Auto-resize image if too large to prevent processing issues
        resized_image = resize_image_if_needed(request.image_base64, max_dimension=2000, max_file_size_mb=4.0)
        
        # Convert base64 to OpenCV image
        img = base64_to_cv2(resized_image)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image data")
        
        # Process the image
        stencil = process_image_to_stencil(img, request.settings)
        
        # Convert back to base64
        stencil_base64 = cv2_to_base64(stencil)
        
        processing_time = (time.time() - start_time) * 1000
        
        return ProcessImageResponse(
            stencil_base64=stencil_base64,
            processing_time_ms=round(processing_time, 2)
        )
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")

# Fast Stencil Generation - All 3 versions using OpenCV edge detection
class FastStencilRequest(BaseModel):
    image_base64: str

class FastStencilResponse(BaseModel):
    light: str  # Clean outlines only
    medium: str  # Outlines + some detail/contour
    heavy: str  # Full detail with texture
    processing_time_ms: float

@api_router.post("/fast-stencil", response_model=FastStencilResponse)
async def generate_fast_stencil(request: FastStencilRequest):
    """Generate all 3 stencil versions instantly using OpenCV edge detection.
    
    This is MUCH faster than AI generation (milliseconds vs minutes).
    Uses professional edge detection algorithms for accurate tracing.
    """
    try:
        import time
        start_time = time.time()
        
        logger.info("[FastStencil] Starting fast edge detection...")
        
        # Auto-resize image if too large
        resized_image = resize_image_if_needed(request.image_base64, max_dimension=2000, max_file_size_mb=4.0)
        
        # Convert base64 to OpenCV image
        img = base64_to_cv2(resized_image)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image data")
        
        # Generate LIGHT version - Clean outlines, minimal detail
        light_settings = StencilSettings(
            clarity=70.0,        # Higher = less edges, cleaner
            noise_reduction=60.0, # Higher = smoother
            line_weight=40.0,    # Thinner lines
            invert=True
        )
        light_stencil = process_image_to_stencil(img, light_settings)
        light_base64 = cv2_to_base64(light_stencil)
        
        # Generate MEDIUM version - Outlines + contour details
        medium_settings = StencilSettings(
            clarity=50.0,        # Balanced
            noise_reduction=40.0, # Some smoothing
            line_weight=50.0,    # Medium lines
            invert=True
        )
        medium_stencil = process_image_to_stencil(img, medium_settings)
        medium_base64 = cv2_to_base64(medium_stencil)
        
        # Generate HEAVY version - Full detail with texture
        heavy_settings = StencilSettings(
            clarity=30.0,        # Lower = more edges, more detail
            noise_reduction=20.0, # Less smoothing = more texture
            line_weight=60.0,    # Thicker lines
            invert=True
        )
        heavy_stencil = process_image_to_stencil(img, heavy_settings)
        heavy_base64 = cv2_to_base64(heavy_stencil)
        
        processing_time = (time.time() - start_time) * 1000
        logger.info(f"[FastStencil] Generated all 3 versions in {processing_time:.0f}ms")
        
        return FastStencilResponse(
            light=light_base64,
            medium=medium_base64,
            heavy=heavy_base64,
            processing_time_ms=round(processing_time, 2)
        )
        
    except Exception as e:
        logger.error(f"[FastStencil] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating stencils: {str(e)}")

class RemoveBackgroundRequest(BaseModel):
    image_base64: str
    method: str = Field(default="auto")  # "auto", "grabcut", or "threshold"

class RemoveBackgroundResponse(BaseModel):
    image_base64: str
    processing_time_ms: float

@api_router.post("/remove-background", response_model=RemoveBackgroundResponse)
async def remove_background_endpoint(request: RemoveBackgroundRequest):
    """Remove background from an image"""
    try:
        import time
        start_time = time.time()
        
        # Convert base64 to OpenCV image
        img = base64_to_cv2(request.image_base64)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image data")
        
        # Remove background
        result = remove_background(img, request.method)
        
        # Convert back to base64 (PNG to preserve transparency)
        result_base64 = cv2_to_base64_png(result)
        
        processing_time = (time.time() - start_time) * 1000
        
        return RemoveBackgroundResponse(
            image_base64=result_base64,
            processing_time_ms=round(processing_time, 2)
        )
    except Exception as e:
        logger.error(f"Error removing background: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error removing background: {str(e)}")

# ============================================
# IMAGE QUALITY VALIDATION ENDPOINT
# ============================================

class ValidateImageRequest(BaseModel):
    image_base64: str

class ValidateImageResponse(BaseModel):
    is_valid: bool
    warnings: List[str]
    suggestions: List[str]
    blur_score: float
    brightness_score: float
    resolution_width: int
    resolution_height: int

@api_router.post("/validate-image", response_model=ValidateImageResponse)
async def validate_image_endpoint(request: ValidateImageRequest):
    """Validate image quality before stencil generation.
    
    Returns warnings and suggestions to help users get the best stencil results.
    This is optional - the AI generation will still work, but results may vary.
    """
    try:
        # Fix EXIF orientation first
        oriented_image = fix_exif_orientation(request.image_base64)
        
        # Validate quality
        result = validate_image_quality(oriented_image)
        
        return ValidateImageResponse(
            is_valid=result.is_valid,
            warnings=result.warnings,
            suggestions=result.suggestions,
            blur_score=round(result.blur_score, 2),
            brightness_score=round(result.brightness_score, 2),
            resolution_width=result.resolution[0],
            resolution_height=result.resolution[1]
        )
    except Exception as e:
        logger.error(f"Error validating image: {str(e)}")
        # Return valid with no warnings on error - don't block user
        return ValidateImageResponse(
            is_valid=True,
            warnings=[],
            suggestions=[],
            blur_score=0,
            brightness_score=0,
            resolution_width=0,
            resolution_height=0
        )

# Image Enhancement Endpoint
class EnhanceImageRequest(BaseModel):
    image_base64: str
    use_ai: bool = Field(default=True)  # Use AI enhancement (slower but better) or basic (fast)

class EnhanceImageResponse(BaseModel):
    enhanced_base64: str
    original_resolution: tuple
    enhanced_resolution: tuple
    enhancement_type: str  # "ai" or "basic"
    processing_time_ms: float

@api_router.post("/enhance-image", response_model=EnhanceImageResponse)
async def enhance_image_endpoint(request: EnhanceImageRequest):
    """Enhance an image for better stencil generation.
    
    Uses AI (Gemini) to upscale and enhance low-quality images, or falls back
    to basic OpenCV enhancement for faster processing.
    
    - AI Enhancement: Upscales, sharpens, improves contrast (~3-8 seconds)
    - Basic Enhancement: Sharpens and improves contrast only (~0.5 seconds)
    """
    import time
    start_time = time.time()
    
    try:
        # Get original resolution
        if ',' in request.image_base64:
            base64_data = request.image_base64.split(',')[1]
        else:
            base64_data = request.image_base64
        
        img_data = base64.b64decode(base64_data)
        original_img = Image.open(BytesIO(img_data))
        original_resolution = original_img.size
        
        logger.info(f"[EnhanceImage] Original resolution: {original_resolution}")
        
        if request.use_ai:
            # Use AI enhancement (includes upscaling)
            logger.info("[EnhanceImage] Using AI enhancement...")
            enhanced_base64 = await enhance_photo_with_ai(request.image_base64)
            enhancement_type = "ai"
        else:
            # Use basic enhancement (fast, no upscaling)
            logger.info("[EnhanceImage] Using basic enhancement...")
            enhanced_base64 = enhance_photo_basic(request.image_base64)
            enhancement_type = "basic"
        
        # Get enhanced resolution
        if ',' in enhanced_base64:
            enhanced_data = enhanced_base64.split(',')[1]
        else:
            enhanced_data = enhanced_base64
        
        enhanced_img_data = base64.b64decode(enhanced_data)
        enhanced_img = Image.open(BytesIO(enhanced_img_data))
        enhanced_resolution = enhanced_img.size
        
        processing_time = (time.time() - start_time) * 1000
        
        logger.info(f"[EnhanceImage] Enhanced: {original_resolution} -> {enhanced_resolution} in {processing_time:.0f}ms ({enhancement_type})")
        
        return EnhanceImageResponse(
            enhanced_base64=enhanced_base64,
            original_resolution=original_resolution,
            enhanced_resolution=enhanced_resolution,
            enhancement_type=enhancement_type,
            processing_time_ms=round(processing_time, 2)
        )
        
    except Exception as e:
        logger.error(f"[EnhanceImage] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error enhancing image: {str(e)}")


# ---------------------------------------------------------------------------
# BLUEPRINT HEAVY+ — production standard for every stencil we ship.
# Single source of truth for both /api/ai-stencil and /api/process_stencil_job.
# Line-only. Zero fills. Four-tier weight hierarchy (Primary / Secondary /
# Tertiary / Dotted). Detail is toned down vs. the previous Heavy so the
# artist receives readable structure, not noise.
# ---------------------------------------------------------------------------
def build_blueprint_prompt(line_color: str, detail_level: str) -> str:
    """Build the stencil-generation prompt.

    Light ("minimal") uses a completely separate, standalone "clean line
    drawing" brief — it deliberately does NOT inherit the Blueprint Heavy+
    framing, four-tier hierarchy, or DOTTED guides. This is the only way
    to force a visibly cleaner output than Medium/Heavy.

    Medium ("moderate") and Heavy ("detailed") share the Blueprint Heavy+
    base prompt with their own detail blocks.

    Args:
        line_color: rendered line color (e.g. "purple/violet", "black").
        detail_level: one of "minimal", "moderate", "detailed".
    """
    # LIGHT: Feb 16 2026 prompt — photo-to-line-art tracing brief.
    # Standalone; does NOT inherit Blueprint Heavy+ framing. The user
    # preferred this minimal style over later iterations.
    if detail_level == "minimal":
        return f"""IMPORTANT: Convert THIS EXACT input image to a line art stencil. DO NOT create a different image.

ABSOLUTE RULES - VIOLATION IS FAILURE:
1. The output MUST show the EXACT SAME subject as the input
2. The output MUST have the EXACT SAME composition as the input
3. The output MUST have the EXACT SAME pose/position as the input
4. If input shows a face, output must show THAT SAME face in SAME position
5. If input shows an object, output must show THAT SAME object in SAME position
6. DO NOT create your own version or interpretation
7. DO NOT draw a "similar" subject - draw THIS subject

TASK: Photo-to-line-art conversion (NOT creative generation)
- Input: The photo I'm providing
- Output: A line drawing of EXACTLY what's in that photo
- Think of this as TRACING, not drawing from imagination

TECHNICAL SPECS:
- Use {line_color} colored lines on pure white background
- NO gradients, NO soft shading, NO gray tones
- All shading via line techniques only (cross-hatch, dots, parallel lines)

SHADING AMOUNT: MINIMAL
- Outlines only, minimal internal detail

BLACK FILLS: NONE
- None - lines only

VERIFY: Before outputting, check that your stencil matches the input image exactly."""

    detail_blocks = {
        "minimal": (
            "LIGHT — clean, sparse outline.\n"
            "- PRIMARY contours only: outer silhouette + the few major structural boundaries that define the subject's identity.\n"
            "- NO internal texture. NO hair strands. NO fur detail. NO fabric weave.\n"
            "- NO dotted marks anywhere — not on the face, not on the body, not anywhere. Zero dots.\n"
            "- NO plane-change indication, NO under-eye contour, NO cheek contour, NO jaw shading hint, NO nose-to-cheek transition line. The face has only its primary feature outlines (eye outline, nose outline, lip outline, brow line) and nothing else.\n"
            "- Facial features present but drawn with the absolute minimum line count needed to recognize them.\n"
            "- The stencil must feel noticeably SPARSE. If you are debating whether to add a line, LEAVE IT OUT.\n"
            "- Target visual impression: a confident outline drawing. Clean. Readable at a glance. Obviously less detail than Medium. An artist looking at this should think 'just the bones, I'll add everything else myself.'"
        ),
        "moderate": (
            "MEDIUM — balanced form + shape.\n"
            "- PRIMARY contours + SECONDARY internal structure (facial features, major hair mass groupings, fold lines, feature boundaries).\n"
            "- A MODERATE pass of TERTIARY directional lines: hair direction, fabric folds, major structural creases.\n"
            "- NO DOTTED guides at this level.\n"
            "- Texture is present but restrained. Clearly MORE detail than Light, clearly LESS than Heavy.\n"
            "- Target visual impression: balanced — form and shape are readable, but the image is not crowded."
        ),
        "detailed": (
            "HEAVY — full detail, maximum information density.\n"
            "- ALL four line tiers engaged: PRIMARY + SECONDARY + FULL TERTIARY + DOTTED facial guides.\n"
            "- Individual hair strands, fur texture, depth lines, micro-structure, every small surface mark visible in the reference.\n"
            "- Dotted guides on facial plane changes (cheek to jaw, brow to socket, nose to cheek, under-eye, lip volumes).\n"
            "- Hair follows directional flow — not random scatter — and at this level, every notable strand is shown.\n"
            "- Target visual impression: VISIBLY DENSER than Medium at a glance. A tattoo artist should have every structural cue they need.\n"
            "- Cap: density must not collapse into clutter. Every mark still describes a real structural feature in the reference — no invented texture, no shading fills, no crosshatching."
        ),
    }
    detail_text = detail_blocks.get(detail_level, detail_blocks["moderate"])

    return f"""BLUEPRINT HEAVY+ — Tattoo Stencil (production standard).
You are producing a line-only BLUEPRINT that a human tattoo artist will use as a guide. You are NOT rendering the final tattoo. You are NOT interpreting shading. You do NOT decide where shading goes — the artist decides that on skin.

OUTPUT FORMAT:
- {line_color} lines on a pure white background.
- 100% linework. Lines describe STRUCTURE, not shading.
- Every dark region in the reference is represented by a CONTOUR, never by a fill.

ZERO-FILL RULE (hard constraint — if any fill appears, the output is incorrect):
- No solid black anywhere.
- No gray shading anywhere.
- No filled regions of any kind — not eyes, not pupils, not hair shadows, not face paint, not background, not anywhere.
- The background is pure white even if the reference background is dark. Do not invert. Do not reproduce the reference background as a dark shape.
- Face paint, makeup, scars, skull-paint patterns, tattoos are drawn as OUTLINES in their exact reference positions — never as filled shapes.
- Do not use crosshatching, stippling, gradients, or any mark pattern intended to simulate tone.
- Dotted/dashed marks are permitted ONLY as the DOTTED tier defined below (facial guides, form transitions, light-placement hints). They are never used to simulate tonal fills.
- Do not introduce any new solid black region that is not directly derived from a solid-black region already present in the reference photo. When in doubt, use line work instead.

LINE WEIGHT HIERARCHY — four visibly distinct tiers. Lines MUST NOT be uniform weight. Foreground elements must read stronger than background elements:
- PRIMARY (bold): outer contours, silhouette, foreground elements, major structural boundaries (head/body outline, jawline, crown/antlers outer edge).
- SECONDARY (medium): internal structure, facial features (eyes, brows, nose, lips), major forms, key folds and creases, feature boundaries, major hair-mass groupings.
- TERTIARY (fine): texture, hair flow, fur direction, secondary detail, small surface marks, minor wrinkles.
- DOTTED (light): facial guides for the artist — cheeks, jawline, brow ridges, nose bridge, under eyes, lip volumes. Also used for transitions of form and light-placement hints on the face. Dotted marks stay at clean, readable dot size. They are line work, not fills. (Engaged at Heavy+ only — see DETAIL LEVEL below.)
The four tiers MUST be visibly separated. A tattoo artist must be able to tell foreground from background, and structure from texture, at a glance.

FINE-LINE REFINEMENTS (extremely important for readable tattoo transfer — applies at every detail level):
- Use the THINNEST possible fine line weight for ALL facial features: eyebrows, eyelids, eyelashes, iris, pupil, nose bridge, nostrils, lip edges, lip creases. These are small, tightly-spaced areas and thicker lines will bleed together and hide the true form when applied to skin — the goal is to reveal the form, not bury it under thick outlines.
- Use the THINNEST possible fine line weight for ALL interior hair texture / flow lines — noticeably finer than the hair silhouette. Hair strands packed close together must remain clearly individual and not merge into each other.
- PRIMARY silhouette / outer body outline may be slightly heavier (thin-to-medium) but still never thick or bold.
- EYELASHES must be drawn as individual fine hair strokes with the thinnest possible line weight — never a thick continuous band or heavy shadow along the lash line. Each lash is a delicate separate hair.
- PUPIL: hollow circle outline only — never filled black, never solid.
- IRIS: hollow outline only — never filled or shaded solid.
- Eyebrows, nostrils, and eye liner areas: drawn as outlines only — never filled dark regions, regardless of how dark they appear in the reference.
- This refinement controls STROKE THICKNESS only — it does not reduce the COUNT of marks called for by the detail level. Keep the structural detail; just draw thinner in these specific areas.

DETAIL LEVEL — {detail_level.upper()}:
- {detail_text}

READABILITY (thermofax transfer):
- The stencil must read clearly at real stencil print size.
- Do not cluster overlapping micro-lines in small areas.
- Avoid clutter and unnecessary micro-detail. Every mark has a reason.
- Continuous lines must be clean and confident, never broken, pixelated, or noisy.

STRUCTURAL FIDELITY:
- Replicate only what is visibly present in the reference. Do not invent, add, extend, complete, or clean up.
- Exactly ONE subject in the frame, in the EXACT same pose, orientation, facing direction, gaze, framing, and crop as the reference. Do not duplicate, mirror, tile, rotate, flip, re-center, re-crop, or re-pose.
- Preserve identity exactly: face shape, hair style (braided/loose/etc.), adornments (crowns, antlers, jewelry), facial markings. These are drawn as line work — never replaced, cleaned up, or swapped.
- Do not re-interpret the subject when adding detail. Every added line describes a feature that is already there.

CONSISTENCY REQUIREMENT:
- The same reference image should produce consistent structure and predictable line placement across runs.
- Do not freely reinterpret the reference. Trace the structure that is actually present.
- Minimise variation between runs: same reference → same structural decisions.

Style: Line-only Blueprint Heavy+ stencil suitable for thermofax transfer paper."""



# AI-Powered Stencil Generation
class AIStencilRequest(BaseModel):
    image_base64: str
    style: str = Field(default="tattoo")  # "tattoo", "clean", "detailed"
    line_color: str = Field(default="purple")  # "purple", "blue", "black"
    shading_detail: int = Field(default=50, ge=0, le=100)  # 0-100: how much cross-hatching
    solid_fill: int = Field(default=30, ge=0, le=100)  # 0-100: how much solid black fill
    regenerate_style: Optional[str] = Field(default=None)  # "light", "medium", "heavy" - if set, only regenerate this style
    extra_preamble: Optional[str] = Field(default=None)  # DEMO / experimental: image-specific rules prepended to the prompt (used by pre-scan demo)
    temperature: Optional[float] = Field(default=0.0, ge=0.0, le=2.0)  # Blueprint Heavy+ consistency default. Near-deterministic sampling. Overridable per-request.

class AIStencilResponse(BaseModel):
    stencil_base64: str
    processing_time_ms: float
    regenerated_style: Optional[str] = None  # Which style was regenerated (if single style request)
    near_black_fraction: Optional[float] = None  # 0..1 — fraction of raw-output pixels darker than 40/255. >0.05 indicates possible zero-fill violation.
    
async def generate_with_gemini(image_data: str, prompt: str, temperature: Optional[float] = None) -> tuple[str, str]:
    """Generate stencil with Gemini using emergentintegrations LlmChat
    
    Uses gemini-3-pro-image-preview model which produces better quality stencils.
    Tries GOOGLE_API_KEY first, auto-falls back to EMERGENT_LLM_KEY if it fails.
    If temperature is provided, it is forwarded via with_params for variance control.
    """
    # Decode the base64 image if needed
    if ',' in image_data:
        image_data = image_data.split(',')[1]
    
    # Build ordered list of keys to try
    keys_to_try = []
    if GOOGLE_API_KEY:
        keys_to_try.append(("Google API Key", GOOGLE_API_KEY))
    if EMERGENT_LLM_KEY:
        keys_to_try.append(("Emergent LLM Key", EMERGENT_LLM_KEY))
    
    if not keys_to_try:
        raise Exception("No API key configured for Gemini")
    
    last_error = None
    for key_name, api_key in keys_to_try:
        try:
            logger.info(f"[Gemini] Attempting stencil generation with {key_name}...")
            chat = LlmChat(
                api_key=api_key, 
                session_id=f"stencil-{uuid.uuid4()}", 
                system_message="You are a professional tattoo stencil translator. You accurately convert reference images into clean stencil linework without interpretation or modification."
            )
            chat.with_model("gemini", "gemini-3-pro-image-preview").with_params(modalities=["image", "text"])
            if temperature is not None:
                chat.with_params(temperature=temperature)
            
            # Send the image with prompt
            msg = UserMessage(
                text=prompt,
                file_contents=[ImageContent(image_data)]
            )
            
            text_response, images = await chat.send_message_multimodal_response(msg)
            
            if not images or len(images) == 0:
                raise Exception("Gemini did not return any images")
            
            # Get the generated image
            generated_image = images[0]
            image_base64 = generated_image['data']
            mime_type = generated_image.get('mime_type', 'image/png')
            
            logger.info(f"[Gemini] Successfully generated with {key_name}")
            return image_base64, mime_type
            
        except Exception as e:
            last_error = e
            logger.warning(f"[Gemini] {key_name} failed: {str(e)}")
            # Log key failure to DB for admin visibility
            next_key = keys_to_try[keys_to_try.index((key_name, api_key)) + 1][0] if keys_to_try.index((key_name, api_key)) + 1 < len(keys_to_try) else "none"
            await log_key_failure(key_name, str(e), next_key)
            # Continue to next key
            continue
    
    # All keys failed
    raise Exception(f"All API keys failed. Last error: {str(last_error)}")

async def generate_with_openai(prompt: str) -> tuple[str, str]:
    """Fallback: Generate stencil with OpenAI gpt-image-1"""
    image_gen = OpenAIImageGeneration(api_key=EMERGENT_LLM_KEY)
    
    # OpenAI prompt (text-only, describes the desired stencil)
    openai_prompt = f"""Create a professional tattoo stencil line drawing.

{prompt}

Style: Clean black line art on pure white background. No colors, no shading - just black outlines suitable for tattoo transfer paper."""
    
    images = await image_gen.generate_images(
        prompt=openai_prompt,
        model="gpt-image-1",
        number_of_images=1
    )
    
    if not images or len(images) == 0:
        raise Exception("OpenAI did not return any images")
    
    # Convert bytes to base64
    image_base64 = base64.b64encode(images[0]).decode('utf-8')
    return image_base64, 'image/png'


# ============================================
# LINE WEIGHT ADJUSTMENT ENDPOINT
# ============================================

class LineWeightRequest(BaseModel):
    stencil_base64: str  # Existing stencil to adjust
    line_weight: int  # -5 to +5

class LineWeightResponse(BaseModel):
    stencil_base64: str
    line_weight: int
    processing_time_ms: float

@api_router.post("/adjust-line-weight", response_model=LineWeightResponse)
async def adjust_line_weight(request: LineWeightRequest):
    """Adjust line weight on an existing stencil in real-time.
    
    This is a fast operation (~50ms) that applies morphological
    dilation/erosion to thicken or thin the lines.
    
    Parameters:
    - stencil_base64: The existing stencil image
    - line_weight: -5 (thinnest) to +5 (thickest), 0 = original
    """
    import time
    start_time = time.time()
    
    try:
        # Decode stencil
        img = base64_to_cv2(request.stencil_base64)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid stencil data")
        
        # Convert to grayscale if needed
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        
        # Apply line weight adjustment
        adjusted = apply_line_weight_control(gray, request.line_weight)
        
        # Ensure binary
        _, adjusted = cv2.threshold(adjusted, 127, 255, cv2.THRESH_BINARY)
        
        # Convert back to BGR
        adjusted_bgr = cv2.cvtColor(adjusted, cv2.COLOR_GRAY2BGR)
        
        # Convert to base64
        result_base64 = cv2_to_base64(adjusted_bgr)
        
        processing_time = (time.time() - start_time) * 1000
        logger.info(f"[LineWeight] Adjusted to {request.line_weight} in {processing_time:.1f}ms")
        
        return LineWeightResponse(
            stencil_base64=result_base64,
            line_weight=request.line_weight,
            processing_time_ms=processing_time
        )
        
    except Exception as e:
        logger.error(f"[LineWeight] Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Line weight adjustment failed: {str(e)}")


@api_router.post("/ai-stencil", response_model=AIStencilResponse)
async def generate_ai_stencil(request: AIStencilRequest, http_request: Request):
    """Generate a professional tattoo stencil using AI with fallback providers
    
    If regenerate_style is specified (light/medium/heavy), only that style is generated.
    Otherwise, this endpoint is called 3 times by the frontend for all styles.
    
    ENHANCED PIPELINE:
    1. EXIF orientation fix (phone photos)
    2. Image quality validation (warnings for blur/darkness)
    3. Auto-resize if too large
    4. Photo enhancement (contrast, sharpening)
    5. Cache check (instant return if same image processed before)
    6. AI generation
    7. Post-processing (boost lines, clean artifacts)
    8. Cache storage for future requests
    """
    try:
        import time
        start_time = time.time()
        
        if not EMERGENT_LLM_KEY and not AI_API_KEY:
            raise HTTPException(status_code=500, detail="AI API key not configured. Please check your internet connection and try again.")
        
        # ---- Soft server-side credit gate (defence-in-depth) ----
        # Frontend calls /api/credits/deduct before this endpoint. If the
        # request also carries an auth token, we re-check credits here so an
        # authenticated caller cannot bypass the credit system by skipping
        # deduct. Unauthenticated legacy callers still work (we log them).
        auth_header = http_request.headers.get('authorization')
        if auth_header:
            try:
                current_user = await get_current_user(auth_header)
                credits_state = await get_user_credits(current_user['user_id'])
                available = int(credits_state.get('available_credits', 0))
                is_emergency = bool(credits_state.get('emergency_available', False))
                if available <= 0 and not is_emergency:
                    logger.info(
                        f"[CreditGate] Blocked generation for {current_user.get('email')} "
                        f"— available_credits=0"
                    )
                    raise HTTPException(
                        status_code=402,
                        detail="No credits available. Please upgrade or wait for your next cycle.",
                    )
            except HTTPException:
                raise
            except Exception as gate_err:
                # Never break the generation if the gate itself fails — it is
                # a secondary safety net, not the primary enforcement.
                logger.warning(f"[CreditGate] Soft check failed, allowing request: {gate_err}")
        else:
            logger.warning("[CreditGate] /api/ai-stencil called without auth token (legacy path) — credit gate skipped")
        # Determine the style for caching
        cache_style = request.regenerate_style or f"shading_{request.shading_detail}"
        
        # === STEP 1: Check cache first for instant results ===
        # IMPORTANT: when this call is an explicit regeneration (regenerate_style
        # is set), we SKIP the cache entirely so the user gets a genuinely new
        # result each time they reroll. The cache only helps first-time generation
        # where a user might upload the same photo twice in a session.
        cache_key = get_cache_key(request.image_base64, cache_style)
        cached_result = get_cached_stencil(cache_key) if not request.regenerate_style else None
        if cached_result:
            logger.info(f"[AI-Stencil] Cache HIT - returning cached result in {(time.time() - start_time) * 1000:.0f}ms")
            cached_nbf = cached_result.get('near_black_fraction')
            return AIStencilResponse(
                stencil_base64=cached_result['stencil'],
                processing_time_ms=round((time.time() - start_time) * 1000, 2),
                regenerated_style=request.regenerate_style,
                near_black_fraction=round(cached_nbf, 4) if cached_nbf is not None else None,
            )
        
        # === STEP 2: Fix EXIF orientation (phone photos often have wrong rotation) ===
        oriented_image = fix_exif_orientation(request.image_base64)
        
        # === STEP 3: Validate image quality (log warnings, don't block) ===
        quality_result = validate_image_quality(oriented_image)
        if quality_result.warnings:
            logger.info(f"[AI-Stencil] Quality warnings: {quality_result.warnings}")
            # Future: could return warnings to frontend to show user
        
        # === STEP 4: Auto-resize image if too large to prevent AI failures ===
        resized_image = resize_image_if_needed(oriented_image, max_dimension=2000, max_file_size_mb=4.0)
        
        # === STEP 5: AUTOMATIC PHOTO ENHANCEMENT for better AI stencil results ===
        # This boosts contrast, sharpens details, and enhances edges so the AI
        # can better capture fine details like hair, jewelry, subtle facial features
        enhanced_image = enhance_photo_for_ai(resized_image)
        
        # Extract base64 data (remove data URL prefix if present)
        image_data = enhanced_image
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        # Define line color based on request
        color_map = {
            "purple": "purple/violet",
            "blue": "blue/indigo", 
            "black": "black"
        }
        line_color = color_map.get(request.line_color, "purple/violet")
        
        # Determine detail level based on style
        if request.regenerate_style:
            style_to_detail = {
                "light": "minimal",
                "medium": "moderate", 
                "heavy": "detailed"
            }
            detail_level = style_to_detail.get(request.regenerate_style.lower(), "moderate")
            logger.info(f"Regenerating single style: {request.regenerate_style} (detail: {detail_level})")
        else:
            detail_level = "minimal" if request.shading_detail < 30 else "moderate" if request.shading_detail < 60 else "detailed"
        
        # Blueprint Mode — line-only stencil for a human artist
        prompt = build_blueprint_prompt(line_color, detail_level)

        image_base64 = None
        mime_type = 'image/png'
        # === EXPERIMENTAL: inject image-specific pre-scan rules if provided ===
        # This supports the pre-scan demo/feature: an optional preamble string
        # is prepended to the main prompt so rules derived from a prior Gemini
        # classification pass on this exact image take priority over generic rules.
        if request.extra_preamble:
            prompt = request.extra_preamble.strip() + "\n\n" + prompt
            logger.info(f"[AI-Stencil] extra_preamble injected ({len(request.extra_preamble)} chars)")

        provider_used = "google"
        last_error = None
        
        # Use Google Gemini (can see and trace reference images)
        # Heavy mode is denser → needs longer wall-clock budget + one retry.
        # Other modes keep the 120 s budget and no retry.
        is_heavy = (detail_level == "detailed") or (
            (request.regenerate_style or "").lower() == "heavy"
        )
        gen_timeout = 180.0 if is_heavy else 120.0
        max_attempts = 2 if is_heavy else 1

        # OpenAI gpt-image-1 is text-to-image only and CANNOT trace reference photos
        if EMERGENT_LLM_KEY or AI_API_KEY:
            for attempt in range(1, max_attempts + 1):
                try:
                    logger.info(
                        f"Attempting stencil generation with Google Gemini "
                        f"(attempt {attempt}/{max_attempts}, timeout={gen_timeout}s, heavy={is_heavy})..."
                    )
                    image_base64, mime_type = await asyncio.wait_for(
                        generate_with_gemini(image_data, prompt, temperature=request.temperature),
                        timeout=gen_timeout,
                    )
                    provider_used = "google"
                    logger.info("Successfully generated with Google Gemini")
                    break
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Google Gemini timed out after {gen_timeout}s (attempt {attempt}/{max_attempts})"
                    )
                    if attempt < max_attempts:
                        continue  # heavy mode: one retry
                    raise HTTPException(
                        status_code=504,
                        detail="AI generation is taking longer than expected. Please try again shortly.",
                    )
                except Exception as e:
                    logger.error(f"Google Gemini failed: {e}")
                    # Non-timeout errors: do NOT retry heavy — most are auth/quota/invalid key.
                    raise HTTPException(
                        status_code=503,
                        detail=f"AI service error: {str(e)}. Please try again.",
                    )
        
        if not image_base64:
            raise HTTPException(
                status_code=503, 
                detail="Unable to generate stencil. AI services may be experiencing issues. Please check your internet connection and try again."
            )
        
        # CRITICAL: Resize stencil to match ORIGINAL input image dimensions
        # Use the user's ORIGINAL image (before enhancement/resize) for accurate overlay
        try:
            # Get dimensions from the ORIGINAL request image, not enhanced
            original_b64 = request.image_base64
            if ',' in original_b64:
                original_b64 = original_b64.split(',')[1]
            original_img_data = base64.b64decode(original_b64)
            original_img = Image.open(BytesIO(original_img_data))
            original_width, original_height = original_img.size
            logger.info(f"Original input dimensions: {original_width}x{original_height}")
            
            # Decode the generated stencil
            stencil_img_data = base64.b64decode(image_base64)
            stencil_img = Image.open(BytesIO(stencil_img_data))
            stencil_width, stencil_height = stencil_img.size
            logger.info(f"AI stencil dimensions: {stencil_width}x{stencil_height}")
            
            # Resize to match original if different
            if stencil_width != original_width or stencil_height != original_height:
                logger.info(f"Resizing stencil from {stencil_width}x{stencil_height} to {original_width}x{original_height}")
                # Direct resize - LANCZOS preserves quality
                stencil_img = stencil_img.resize((original_width, original_height), Image.Resampling.LANCZOS)
                
                # Convert back to base64
                buffer = BytesIO()
                stencil_img.save(buffer, format='PNG')
                image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                mime_type = 'image/png'
                logger.info("Stencil resized to match original dimensions")
        except Exception as resize_error:
            logger.warning(f"Could not resize stencil (non-critical): {resize_error}")
            # Continue with original stencil if resize fails
        
        # Format as data URL
        stencil_base64 = f"data:{mime_type};base64,{image_base64}"
        
        # === STEP 7: POST-PROCESS STENCIL ===
        # Boost line weight, clean artifacts, ensure consistent quality
        stencil_base64, near_black_fraction = post_process_stencil(stencil_base64)
        
        # === STEP 8: CACHE THE RESULT for future instant retrieval ===
        cache_stencil(cache_key, stencil_base64, near_black_fraction)
        
        processing_time = (time.time() - start_time) * 1000
        
        logger.info(f"AI stencil generated in {processing_time:.2f}ms using {provider_used}")
        
        return AIStencilResponse(
            stencil_base64=stencil_base64,
            processing_time_ms=round(processing_time, 2),
            provider=provider_used,
            regenerated_style=request.regenerate_style,
            near_black_fraction=round(near_black_fraction, 4),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating AI stencil: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error generating stencil. Please check your internet connection and try again. If the problem persists, AI services may be temporarily unavailable."
        )

# ============================================
# ASYNC STENCIL GENERATION (Polling Architecture)
# ============================================
# This avoids gateway timeouts by:
# 1. Starting generation in background, returning job ID immediately
# 2. Frontend polls status endpoint until complete
# 3. Each poll request is quick (< 1 second), avoiding timeouts

class AsyncStencilRequest(BaseModel):
    image_base64: str
    line_color: str = "black"
    auto_enhance: bool = True  # Auto-enhance image before processing (AI upscaling)
    single_style: Optional[str] = None  # If set, only generate this style (light, medium, or heavy)

class AsyncStencilStartResponse(BaseModel):
    job_id: str
    status: str
    message: str

class AsyncStencilStatusResponse(BaseModel):
    job_id: str
    status: str  # pending, processing, completed, failed
    progress: int  # 0-100
    current_style: Optional[str]  # Which style is being generated
    result: Optional[dict]  # Contains light, medium, heavy when complete
    error: Optional[str]

async def generate_single_stencil_for_job(job: StencilJob, style: str, shading_detail: int, solid_fill: int):
    """Generate a single stencil style for an async job"""
    try:
        job.current_style = style
        logger.info(f"[AsyncJob {job.job_id}] Generating {style} version...")
        
        # Use the enhanced image if available, otherwise use original
        if job.enhanced_image:
            image_data = job.enhanced_image
            logger.info(f"[AsyncJob {job.job_id}] Using AI-enhanced image")
        else:
            raw_image = job.image_base64
            image_data = enhance_photo_basic(raw_image)  # Use basic enhancement as fallback
        
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        # Determine detail level
        if shading_detail <= 10:
            detail_level = "minimal"
        elif shading_detail <= 35:
            detail_level = "moderate"
        else:
            detail_level = "detailed"
        
        # Blueprint Mode — line-only stencil for a human artist (async job path)
        prompt = build_blueprint_prompt("purple/violet", detail_level)

        # Generate using Gemini (Blueprint Heavy+ consistency default)
        result_base64, mime_type = await generate_with_gemini(image_data, prompt, temperature=0.0)
        
        if result_base64:
            # Resize stencil to match ORIGINAL input dimensions for proper overlay
            try:
                # Get original image dimensions from job (user's original input)
                original_b64 = job.image_base64
                if ',' in original_b64:
                    original_b64 = original_b64.split(',')[1]
                original_img_data = base64.b64decode(original_b64)
                original_img = Image.open(BytesIO(original_img_data))
                original_width, original_height = original_img.size
                
                stencil_img_data = base64.b64decode(result_base64)
                stencil_img = Image.open(BytesIO(stencil_img_data))
                stencil_width, stencil_height = stencil_img.size
                
                logger.info(f"[AsyncJob {job.job_id}] Original: {original_width}x{original_height}, Stencil: {stencil_width}x{stencil_height}")
                
                if stencil_img.size != (original_width, original_height):
                    # Direct resize to match original - preserves quality
                    stencil_img = stencil_img.resize((original_width, original_height), Image.Resampling.LANCZOS)
                    buffer = BytesIO()
                    stencil_img.save(buffer, format='PNG')
                    result_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    mime_type = 'image/png'
                    logger.info(f"[AsyncJob {job.job_id}] Stencil resized to {original_width}x{original_height}")
            except Exception as resize_err:
                logger.warning(f"[AsyncJob {job.job_id}] Resize warning: {resize_err}")
            
            # Apply post-processing to ensure clean B&W output
            stencil_with_prefix = f"data:{mime_type};base64,{result_base64}"
            processed_stencil, _fill_frac = post_process_stencil(stencil_with_prefix)
            
            job.result[style] = processed_stencil
            logger.info(f"[AsyncJob {job.job_id}] {style} version completed")
            return True
        else:
            logger.error(f"[AsyncJob {job.job_id}] {style} version failed - no result")
            return False
            
    except Exception as e:
        logger.error(f"[AsyncJob {job.job_id}] {style} version error: {str(e)}")
        import traceback
        traceback.print_exc()
        # Store the actual error so it propagates to the client
        job.error = f"{style} generation error: {str(e)}"
        return False

async def process_stencil_job(job_id: str):
    """Background task to process stencil versions (all 3 or single style)"""
    job = stencil_jobs.get(job_id)
    if not job:
        logger.error(f"[AsyncJob {job_id}] Job not found")
        return
    
    try:
        # Step 0: AI Enhancement (if enabled)
        if job.auto_enhance:
            job.status = "enhancing"
            job.current_style = "enhancing"
            job.progress = 5
            logger.info(f"[AsyncJob {job_id}] Starting AI image enhancement...")
            
            try:
                # Skip PicsArt preprocessing - directly use AI enhancement
                # (PicsArt filters causing OpenCV errors on some images)
                enhanced = await enhance_photo_with_ai(job.image_base64)
                job.enhanced_image = enhanced
                logger.info(f"[AsyncJob {job_id}] AI enhancement complete")
            except Exception as e:
                logger.warning(f"[AsyncJob {job_id}] Enhancement pipeline failed, using basic: {str(e)}")
                # Fallback to basic enhancement without preprocessing
                job.enhanced_image = enhance_photo_basic(job.image_base64)
        else:
            # Use basic enhancement only
            job.enhanced_image = enhance_photo_basic(job.image_base64)
        
        job.status = "processing"
        logger.info(f"[AsyncJob {job_id}] Starting stencil generation...")
        
        # Check if we're generating a single style or all styles
        if job.single_style:
            # Generate only the requested style
            style = job.single_style
            job.progress = 20
            
            if style == "light":
                success = await generate_single_stencil_for_job(job, "light", 5, 0)
            elif style == "medium":
                success = await generate_single_stencil_for_job(job, "medium", 30, 0)
            elif style == "heavy":
                success = await generate_single_stencil_for_job(job, "heavy", 50, 30)
            else:
                logger.error(f"[AsyncJob {job_id}] Unknown style: {style}")
                job.status = "failed"
                job.error = f"Unknown style: {style}"
                return
            
            job.progress = 100
            
            if job.result[style]:
                job.status = "completed"
                logger.info(f"[AsyncJob {job_id}] Single style '{style}' completed successfully")
            else:
                job.status = "failed"
                job.error = f"Failed to generate {style} stencil"
                logger.error(f"[AsyncJob {job_id}] Single style '{style}' failed")
        else:
            # Generate all 3 versions
            # Generate Light version (progress 10-33%)
            job.progress = 10
            success = await generate_single_stencil_for_job(job, "light", 5, 0)
            job.progress = 33
            
            # Small delay between generations
            await asyncio.sleep(0.5)
            
            # Generate Medium version (progress 33-66%)
            job.progress = 40
            success = await generate_single_stencil_for_job(job, "medium", 30, 0)
            job.progress = 66
            
            # Small delay between generations
            await asyncio.sleep(0.5)
            
            # Generate Heavy version (progress 66-100%)
            job.progress = 75
            success = await generate_single_stencil_for_job(job, "heavy", 50, 30)
            job.progress = 100
            
            # Check if at least one version succeeded
            if job.result["light"] or job.result["medium"] or job.result["heavy"]:
                job.status = "completed"
                logger.info(f"[AsyncJob {job_id}] All versions completed successfully")
            else:
                job.status = "failed"
                job.error = "Failed to generate any stencil versions"
                logger.error(f"[AsyncJob {job_id}] All versions failed")
        
        job.completed_at = datetime.utcnow()
        job.current_style = None
        
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.completed_at = datetime.utcnow()
        logger.error(f"[AsyncJob {job_id}] Job failed with error: {str(e)}")

@api_router.post("/ai-stencil-async", response_model=AsyncStencilStartResponse)
async def start_async_stencil(request: AsyncStencilRequest):
    """Start async stencil generation - returns immediately with job ID.
    
    Use GET /api/ai-stencil-status/{job_id} to poll for results.
    This avoids gateway timeouts by not waiting for generation to complete.
    
    Set auto_enhance=true (default) to use AI upscaling/enhancement before stencil generation.
    Set single_style to 'light', 'medium', or 'heavy' to only generate that style.
    """
    try:
        # Create job
        job_id = str(uuid.uuid4())
        job = StencilJob(
            job_id=job_id,
            image_base64=request.image_base64,
            settings={"line_color": request.line_color},
            auto_enhance=request.auto_enhance,
            single_style=request.single_style
        )
        stencil_jobs[job_id] = job
        
        enhance_msg = "with AI enhancement" if request.auto_enhance else "without AI enhancement"
        style_msg = f" (single style: {request.single_style})" if request.single_style else " (all styles)"
        logger.info(f"[AsyncJob {job_id}] Job created {enhance_msg}{style_msg}, starting background processing...")
        
        # Start background task (don't await it)
        asyncio.create_task(process_stencil_job(job_id))
        
        return AsyncStencilStartResponse(
            job_id=job_id,
            status="pending",
            message="Stencil generation started. Poll /api/ai-stencil-status/{job_id} for results."
        )
        
    except Exception as e:
        logger.error(f"Error starting async stencil job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error starting generation: {str(e)}")

@api_router.get("/ai-stencil-status/{job_id}", response_model=AsyncStencilStatusResponse)
async def get_stencil_status(job_id: str):
    """Check status of async stencil generation job.
    
    Poll this endpoint every 2-3 seconds until status is 'completed' or 'failed'.
    """
    job = stencil_jobs.get(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return AsyncStencilStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        current_style=job.current_style,
        result=job.result if job.status == "completed" else None,
        error=job.error
    )

@api_router.delete("/ai-stencil-job/{job_id}")
async def delete_stencil_job(job_id: str):
    """Delete a completed job to free memory"""
    if job_id in stencil_jobs:
        del stencil_jobs[job_id]
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Job not found")

@api_router.post("/stencils", response_model=SavedStencil)
async def save_stencil(request: SaveStencilRequest):
    """Save a stencil to the database with auto-generated thumbnail"""
    try:
        # Generate thumbnail from stencil image for gallery preview
        thumbnail = generate_thumbnail(request.stencil_image, max_size=150)
        
        stencil = SavedStencil(
            original_image=request.original_image,
            stencil_image=request.stencil_image,
            stencil_thumbnail=thumbnail,
            settings=request.settings,
            name=request.name
        )
        await db.stencils.insert_one(stencil.dict())
        logger.info(f"Stencil saved with thumbnail (size: {len(thumbnail)} bytes)")
        return stencil
    except Exception as e:
        logger.error(f"Error saving stencil: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error saving stencil: {str(e)}")

@api_router.get("/stencils/list", response_model=List[StencilListItem])
async def get_stencils_list():
    """Get lightweight list of stencils for gallery view (thumbnails only, no full images)"""
    try:
        # Only fetch fields needed for gallery display
        projection = {
            "id": 1,
            "stencil_thumbnail": 1,
            "stencil_image": 1,  # Fallback if no thumbnail
            "created_at": 1,
            "name": 1,
            "_id": 0
        }
        stencils = await db.stencils.find({}, projection).sort("created_at", -1).to_list(100)
        
        result = []
        for stencil in stencils:
            # Use thumbnail if available, otherwise generate one from full image
            thumbnail = stencil.get("stencil_thumbnail")
            if not thumbnail and stencil.get("stencil_image"):
                thumbnail = generate_thumbnail(stencil["stencil_image"], max_size=150)
            
            result.append(StencilListItem(
                id=stencil["id"],
                stencil_thumbnail=thumbnail,
                created_at=stencil["created_at"],
                name=stencil.get("name")
            ))
        
        return result
    except Exception as e:
        logger.error(f"Error fetching stencils list: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching stencils list: {str(e)}")

@api_router.get("/stencils", response_model=List[SavedStencil])
async def get_stencils():
    """Get all saved stencils with full images (use /stencils/list for gallery view)"""
    try:
        stencils = await db.stencils.find().sort("created_at", -1).to_list(100)
        return [SavedStencil(**stencil) for stencil in stencils]
    except Exception as e:
        logger.error(f"Error fetching stencils: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching stencils: {str(e)}")

@api_router.get("/stencils/{stencil_id}", response_model=SavedStencil)
async def get_stencil(stencil_id: str):
    """Get a specific stencil by ID"""
    try:
        stencil = await db.stencils.find_one({"id": stencil_id})
        if not stencil:
            raise HTTPException(status_code=404, detail="Stencil not found")
        return SavedStencil(**stencil)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching stencil: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching stencil: {str(e)}")

@api_router.delete("/stencils/{stencil_id}")
async def delete_stencil(stencil_id: str):
    """Delete a stencil"""
    try:
        result = await db.stencils.delete_one({"id": stencil_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Stencil not found")
        return {"message": "Stencil deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting stencil: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting stencil: {str(e)}")

# Make Stencil Transparent - converts white background to transparent for Procreate layers
class MakeTransparentRequest(BaseModel):
    image_base64: str  # base64 encoded stencil image
    target_width: Optional[int] = None  # Optional: resize to match reference dimensions
    target_height: Optional[int] = None  # Optional: resize to match reference dimensions

class MakeTransparentResponse(BaseModel):
    image_base64: str  # base64 encoded PNG with transparent background
    width: int
    height: int

@api_router.post("/make-transparent", response_model=MakeTransparentResponse)
async def make_transparent(request: MakeTransparentRequest):
    """Convert stencil to clean black linework on transparent background.
    
    This creates a PNG with:
    - Pure black lines (RGB 0,0,0) with alpha based on original darkness
    - Complete transparency for white/light areas (no halo effect)
    - Perfect for layering over a reference photo in Procreate
    
    The key innovation: We use luminance to calculate alpha, then force
    all visible pixels to pure black. This eliminates gray "halos" around lines.
    """
    try:
        import time
        start_time = time.time()
        
        logger.info("[MakeTransparent] Starting transparency conversion...")
        
        # Decode the stencil image
        stencil_data = request.image_base64
        if not stencil_data or len(stencil_data) < 100:
            raise ValueError(f"Invalid image data: too short ({len(stencil_data) if stencil_data else 0} chars)")
        
        if ',' in stencil_data:
            stencil_data = stencil_data.split(',')[1]
        
        # Validate base64 data length
        if len(stencil_data) < 100:
            raise ValueError(f"Invalid base64 data after prefix removal: too short ({len(stencil_data)} chars)")
        
        # Add padding if needed for base64
        padding_needed = len(stencil_data) % 4
        if padding_needed:
            stencil_data += '=' * (4 - padding_needed)
        
        stencil_bytes = base64.b64decode(stencil_data)
        stencil_img = Image.open(BytesIO(stencil_bytes))
        
        original_size = stencil_img.size
        logger.info(f"[MakeTransparent] Original stencil size: {original_size}")
        
        # Resize to match target dimensions if specified
        if request.target_width and request.target_height:
            target_size = (request.target_width, request.target_height)
            if stencil_img.size != target_size:
                stencil_img = stencil_img.resize(target_size, Image.Resampling.LANCZOS)
                logger.info(f"[MakeTransparent] Resized to: {target_size}")
        
        # Convert to RGB first (in case it's RGBA or palette mode)
        if stencil_img.mode != 'RGB':
            # Convert palette or RGBA to RGB
            stencil_img = stencil_img.convert('RGB')
        
        # Convert to numpy array for pixel manipulation
        rgb_array = np.array(stencil_img, dtype=np.float32)
        
        # Calculate luminance (perceived brightness) for each pixel
        # Using standard luminance formula: 0.299*R + 0.587*G + 0.114*B
        luminance = (
            0.299 * rgb_array[:,:,0] + 
            0.587 * rgb_array[:,:,1] + 
            0.114 * rgb_array[:,:,2]
        )
        
        # Invert luminance to get alpha: dark pixels = high alpha, light pixels = low alpha
        # luminance 0 (black) -> alpha 255 (fully opaque)
        # luminance 255 (white) -> alpha 0 (fully transparent)
        alpha = 255.0 - luminance
        
        # Apply a threshold to eliminate near-white pixels completely
        # This removes any faint gray "halos" around lines
        # Pixels with luminance > 230 become fully transparent
        alpha[luminance > 230] = 0
        
        # Boost the alpha for darker pixels to make lines crisper
        # This creates sharper line edges
        alpha = np.clip(alpha * 1.3, 0, 255)
        
        # Create output RGBA array
        # All visible pixels will be PURE BLACK with varying alpha
        height, width = rgb_array.shape[:2]
        result_array = np.zeros((height, width, 4), dtype=np.uint8)
        
        # Set RGB to pure black (0, 0, 0) for all pixels
        result_array[:,:,0] = 0  # R = 0
        result_array[:,:,1] = 0  # G = 0
        result_array[:,:,2] = 0  # B = 0
        
        # Set alpha from our calculated values
        result_array[:,:,3] = alpha.astype(np.uint8)
        
        # Create final image
        result_img = Image.fromarray(result_array, mode='RGBA')
        
        # Convert to base64 PNG
        buffer = BytesIO()
        result_img.save(buffer, format='PNG', optimize=True)
        result_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        width, height = result_img.size
        
        processing_time = (time.time() - start_time) * 1000
        logger.info(f"[MakeTransparent] Converted in {processing_time:.2f}ms, output size: {width}x{height}")
        
        return MakeTransparentResponse(
            image_base64=f"data:image/png;base64,{result_base64}",
            width=width,
            height=height
        )
        
    except Exception as e:
        logger.error(f"[MakeTransparent] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error creating transparent image: {str(e)}")


# Preview endpoints for edge detection samples
from fastapi.responses import FileResponse, HTMLResponse
from fastapi import Request as FastAPIRequest

# ============================================
# AUTH & USER MANAGEMENT
# ============================================
import jwt
import httpx
from datetime import timezone, timedelta

JWT_SECRET = os.environ.get('JWT_SECRET', 'body-bound-stencil-generator-jwt-secret-key-2026-secure')

# ---- Pydantic Models ----
class AppleAuthRequest(BaseModel):
    identity_token: str
    user_id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    device_id: Optional[str] = None  # Device ID for anti-abuse
    referral_code: Optional[str] = None  # Referral code from deep link

class GoogleSessionRequest(BaseModel):
    session_id: str
    device_id: Optional[str] = None  # Device ID for anti-abuse
    referral_code: Optional[str] = None  # Referral code from deep link

class UserCreditsResponse(BaseModel):
    available_credits: int
    tier: Optional[str] = None
    is_trial: bool = False
    trial_expires_at: Optional[str] = None  # ISO timestamp when trial expires
    trial_days_remaining: Optional[int] = None  # Days remaining in trial
    renewal_date: Optional[str] = None
    revenuecat_customer_id: Optional[str] = None

# ---- Trial Constants ----
TRIAL_DURATION_DAYS = 3
TRIAL_CREDITS = 10  # Credits during Apple trial (all tiers)
REFERRALS_NEEDED_FOR_REWARD = 2  # Verified referrals needed for 1 free month
VERIFICATION_DAYS = 14  # Days a referred user must stay subscribed

# ---- JWT Helpers ----
def create_session_token(user_id: str) -> str:
    payload = {
        'user_id': user_id,
        'exp': datetime.now(timezone.utc) + timedelta(days=7),
        'iat': datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

async def get_current_user(auth_header: Optional[str]):
    if not auth_header or not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Missing authorization')
    token = auth_header[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        user_id = payload.get('user_id')
        user = await db.users.find_one({'user_id': user_id}, {'_id': 0})
        if not user:
            raise HTTPException(status_code=401, detail='User not found')
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail='Token expired')
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail='Invalid token')

async def get_user_credits(user_id: str) -> dict:
    # Phase 2 referral redemption: auto-activate queued referral months and
    # auto-expire finished ones. This is idempotent and safe on every call.
    try:
        await maybe_redeem_referral_month(user_id)
    except Exception as e:
        logger.error(f'[Referral Redeem] Failed for {user_id}: {e}')

    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    if not sub:
        return {
            'available_credits': 0, 'tier': None, 'is_trial': False,
            'trial_expires_at': None, 'trial_days_remaining': None,
            'renewal_date': None, 'revenuecat_customer_id': None,
            'is_studio_team': False, 'studio_team_id': None
        }
    
    # Check if user is part of a studio team
    studio_team_id = sub.get('studio_team_id')
    is_studio_team = False
    available_credits = sub.get('available_credits', 0)
    
    if studio_team_id:
        # Get credits from studio team shared pool
        team = await db.studio_teams.find_one({'team_id': studio_team_id}, {'_id': 0})
        if team:
            available_credits = team.get('shared_credits', 0)
            is_studio_team = True
    
    # Calculate trial expiration info
    is_trial = sub.get('is_trial', False)
    trial_expires_at = sub.get('trial_expires_at')
    trial_days_remaining = None
    
    if is_trial and trial_expires_at:
        try:
            expires_dt = datetime.fromisoformat(trial_expires_at.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            if expires_dt <= now:
                # Trial has expired - set credits to 0
                available_credits = 0
                trial_days_remaining = 0
                # Update DB to reflect expired trial
                await db.subscriptions.update_one(
                    {'user_id': user_id},
                    {'$set': {'available_credits': 0, 'tier': 'trial_expired'}}
                )
                logger.info(f'[Trial] User {user_id} trial expired')
            else:
                delta = expires_dt - now
                trial_days_remaining = max(0, delta.days + (1 if delta.seconds > 0 else 0))
        except Exception as e:
            logger.error(f'[Trial] Error parsing trial_expires_at: {e}')
    
    # Tier -> total monthly credits mapping
    TIER_CREDITS_MAP = {'walk-in': 125, 'booked-out': 500, 'the-shop': 1500, 'the-shop-member': 1500, 'referral_premium': 125}
    tier = sub.get('tier')
    total_monthly_credits = TIER_CREDITS_MAP.get(tier, 0)
    # Rollover policy: balance cap = 2× monthly allowance
    monthly_allowance = sub.get('monthly_allowance', total_monthly_credits)
    max_balance_cap = sub.get('max_balance_cap', monthly_allowance * BALANCE_CAP_MULTIPLIER if monthly_allowance else 0)
    last_refill_at = sub.get('last_refill_at')
    # Emergency-stencil one-time monthly flag
    current_month_key = datetime.now(timezone.utc).strftime('%Y-%m')
    emergency_stencil_available = sub.get('emergency_stencil_month') != current_month_key

    # Walk-In behavioral upsell — suggest Booked Out BEFORE hitting zero.
    # Trigger: tier=walk-in AND credits_consumed_this_cycle >= 40 AND
    # available_credits <= 10 AND not already dismissed/shown this cycle.
    # No time-based/velocity logic. Banner state is tied to last_refill_at so
    # it resets naturally each billing cycle.
    credits_consumed_this_cycle = int(sub.get('credits_consumed_this_cycle', 0) or 0)
    upsell_cycle_key = sub.get('last_refill_at')
    upsell_already_dismissed = sub.get('upsell_dismissed_for_cycle') == upsell_cycle_key
    show_walkin_upsell = (
        tier == 'walk-in'
        and not is_trial
        and credits_consumed_this_cycle >= 40
        and available_credits <= 10
        and not upsell_already_dismissed
    )

    # Referral premium override state (Phase 2 redemption)
    rewards_doc = await db.referral_rewards.find_one({'user_id': user_id}, {'_id': 0})
    referral_premium_until = None
    is_referral_premium_active = False
    earned_free_months = 0
    if rewards_doc:
        earned_free_months = rewards_doc.get('free_months_available', 0) or 0
        rpu = rewards_doc.get('referral_premium_until')
        if rpu:
            try:
                rpu_dt = datetime.fromisoformat(rpu.replace('Z', '+00:00'))
                if rpu_dt > datetime.now(timezone.utc):
                    referral_premium_until = rpu
                    is_referral_premium_active = True
            except Exception:
                pass

    return {
        'available_credits': available_credits,
        'total_monthly_credits': total_monthly_credits,
        'monthly_allowance': monthly_allowance,
        'max_balance_cap': max_balance_cap,
        'last_refill_at': last_refill_at,
        'tier': tier,
        'is_trial': is_trial,
        'trial_expires_at': trial_expires_at,
        'trial_days_remaining': trial_days_remaining,
        'renewal_date': sub.get('renewal_date'),
        'revenuecat_customer_id': sub.get('revenuecat_customer_id'),
        'is_studio_team': is_studio_team,
        'studio_team_id': studio_team_id,
        'needs_subscription': tier in (None, 'trial_expired', 'expired'),
        'is_referral_premium_active': is_referral_premium_active,
        'referral_premium_until': referral_premium_until,
        'earned_free_months': earned_free_months,
        'emergency_stencil_available': emergency_stencil_available,
        'show_walkin_upsell': show_walkin_upsell,
    }

# ---- Apple Sign-In ----
APPLE_KEYS_URL = 'https://appleid.apple.com/auth/keys'

async def check_trial_abuse(email: Optional[str], device_id: Optional[str], provider: str, provider_id: str) -> tuple[bool, str]:
    """Check if this email/device combination has already used a trial.
    
    Anti-abuse strategy:
    1. Check by email (prevents same email getting multiple trials)
    2. Check by device_id (prevents same device getting trials with different emails)
    3. Check by provider_id (prevents same account getting trials)
    
    Returns: (is_abuse, reason)
    """
    # Check by email
    if email:
        email_abuse = await db.subscriptions.find_one({
            'anti_abuse_email': email.lower(),
            'is_trial': True
        })
        if email_abuse:
            logger.info(f'[AntiAbuse] Email {email} already used trial')
            return True, 'email_used'
    
    # Check by device_id
    if device_id:
        device_abuse = await db.subscriptions.find_one({
            'anti_abuse_device_id': device_id,
            'is_trial': True
        })
        if device_abuse:
            logger.info(f'[AntiAbuse] Device {device_id[:8]}... already used trial')
            return True, 'device_used'
    
    # Check by provider_id (legacy check)
    provider_key = f'{provider}:{provider_id}'
    provider_abuse = await db.subscriptions.find_one({
        'anti_abuse_provider': provider_key,
        'is_trial': True
    })
    if provider_abuse:
        logger.info(f'[AntiAbuse] Provider {provider_key} already used trial')
        return True, 'provider_used'
    
    return False, ''

async def create_initial_subscription(user_id: str, email: Optional[str], device_id: Optional[str], provider: str, provider_id: str) -> dict:
    """Create an initial subscription record for a new user.
    
    If TEMP_BYPASS_ENABLED=true, grants paywall_bypass tier with 10 credits
    so new users can try the app while subscription loading is unstable.
    Otherwise, no credits — user must subscribe via Apple/RevenueCat.

    Paywall-QA escape hatch (PAYWALL_NO_BYPASS_EMAILS): a comma-separated
    allowlist of lowercased emails for which the bypass is NEVER applied,
    even when TEMP_BYPASS_ENABLED=true. Use this to run clean paid-user
    tests for specific QA accounts without disturbing the global bypass
    behavior for everyone else.
    """
    now = datetime.now(timezone.utc)
    temp_bypass = os.environ.get('TEMP_BYPASS_ENABLED', '').lower() == 'true'

    # Per-email escape hatch for paywall validation runs. Skip bypass for
    # any email in the allowlist so the account lands with tier=None,
    # credits=0, and must go through the real Apple/RC purchase path.
    no_bypass_emails_raw = os.environ.get('PAYWALL_NO_BYPASS_EMAILS', '') or ''
    no_bypass_emails = {
        e.strip().lower()
        for e in no_bypass_emails_raw.split(',')
        if e.strip()
    }
    email_lc = email.lower() if email else None
    email_is_blocked_from_bypass = bool(email_lc and email_lc in no_bypass_emails)

    if temp_bypass and not email_is_blocked_from_bypass:
        tier = 'paywall_bypass'
        credits = 10
        log_msg = f'[Subscription] New user {user_id} ({email_lc}) — temp bypass: 10 credits, tier=paywall_bypass'
    else:
        tier = None
        credits = 0
        reason = (
            'paywall-QA blocklist hit'
            if email_is_blocked_from_bypass
            else 'TEMP_BYPASS_ENABLED off'
        )
        log_msg = (
            f'[Subscription] New user {user_id} ({email_lc}) — no trial, must subscribe via Apple '
            f'({reason})'
        )

    subscription = {
        'user_id': user_id,
        'tier': tier,
        'available_credits': credits,
        'is_trial': False,
        'trial_expires_at': None,
        'renewal_date': None,
        'revenuecat_customer_id': None,
        'anti_abuse_email': email.lower() if email else None,
        'anti_abuse_device_id': device_id,
        'anti_abuse_provider': f'{provider}:{provider_id}',
        'created_at': now.isoformat(),
    }
    logger.info(log_msg)
    
    await db.subscriptions.insert_one(subscription)
    return subscription

async def verify_apple_token(identity_token: str, user_id: str) -> dict:
    """Verify Apple identity token - falls back to trusting client in dev"""
    try:
        async with httpx.AsyncClient() as c:
            resp = await c.get(APPLE_KEYS_URL, timeout=5.0)
            apple_keys = resp.json()
        header = jwt.get_unverified_header(identity_token)
        kid = header.get('kid')
        from jwt.algorithms import RSAAlgorithm
        key = None
        for k in apple_keys.get('keys', []):
            if k.get('kid') == kid:
                key = RSAAlgorithm.from_jwk(k)
                break
        if not key:
            raise ValueError('Key not found')
        payload = jwt.decode(
            identity_token, key, algorithms=['RS256'],
            audience='com.bodybound.stencilgenerator',
        )
        return {'apple_user_id': payload.get('sub'), 'email': payload.get('email')}
    except Exception as e:
        logger.warning(f'[Auth] Apple token fallback: {e}')
        return {'apple_user_id': user_id, 'email': None}

@api_router.post("/auth/apple")
async def apple_sign_in(request: AppleAuthRequest):
    """Handle Apple Sign-In — new users get no free trial (Apple/RevenueCat manages trials)"""
    verified = await verify_apple_token(request.identity_token, request.user_id)
    apple_user_id = verified['apple_user_id']
    email = verified.get('email') or request.email

    existing = await db.users.find_one({'apple_user_id': apple_user_id}, {'_id': 0})
    if existing:
        user_id = existing['user_id']
        update = {'last_login': datetime.now(timezone.utc).isoformat()}
        if email and not existing.get('email'):
            update['email'] = email
        if request.full_name and not existing.get('name'):
            update['name'] = request.full_name
        # Update device_id if provided (for tracking)
        if request.device_id:
            update['device_id'] = request.device_id
        await db.users.update_one({'user_id': user_id}, {'$set': update})
        user = {**existing, **update}
    else:
        user_id = f'user_{uuid.uuid4().hex[:12]}'
        user = {
            'user_id': user_id, 'apple_user_id': apple_user_id, 'email': email,
            'name': request.full_name, 'picture': None,
            'device_id': request.device_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'last_login': datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one({**user})
        # Create initial subscription (no free credits — user must subscribe via Apple)
        await create_initial_subscription(
            user_id=user_id,
            email=email,
            device_id=request.device_id,
            provider='apple',
            provider_id=apple_user_id
        )
        # Attribute referral if code provided
        if request.referral_code:
            await attribute_referral(user_id, email, request.device_id, request.referral_code)

    return {'user': user, 'session_token': create_session_token(user_id)}

@api_router.post("/auth/google-session")
async def google_session_exchange(request: GoogleSessionRequest):
    """Exchange Emergent Auth session_id for user data — new users must subscribe via Apple"""
    try:
        async with httpx.AsyncClient() as c:
            resp = await c.get(
                'https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data',
                headers={'X-Session-ID': request.session_id},
                timeout=10.0,
            )
            if not resp.is_success:
                raise HTTPException(status_code=401, detail='Invalid Google session')
            google_data = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail='Auth service timeout')

    google_user_id = google_data.get('id')
    email = google_data.get('email')
    existing = await db.users.find_one(
        {'$or': [{'google_user_id': google_user_id}, {'email': email}]}, {'_id': 0}
    )
    if existing:
        user_id = existing['user_id']
        update = {
            'google_user_id': google_user_id,
            'last_login': datetime.now(timezone.utc).isoformat()
        }
        # Update device_id if provided
        if request.device_id:
            update['device_id'] = request.device_id
        await db.users.update_one({'user_id': user_id}, {'$set': update})
        user = {**existing, **update}
    else:
        user_id = f'user_{uuid.uuid4().hex[:12]}'
        user = {
            'user_id': user_id, 'google_user_id': google_user_id, 'apple_user_id': None,
            'email': email, 'name': google_data.get('name'), 'picture': google_data.get('picture'),
            'device_id': request.device_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'last_login': datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one({**user})
        # Create initial subscription (no free credits — user must subscribe via Apple)
        await create_initial_subscription(
            user_id=user_id,
            email=email,
            device_id=request.device_id,
            provider='google',
            provider_id=google_user_id
        )
        # Attribute referral if code provided
        if request.referral_code:
            await attribute_referral(user_id, email, request.device_id, request.referral_code)

    return {'user': user, 'session_token': create_session_token(user_id)}

@api_router.get("/auth/me")
async def get_me(request: FastAPIRequest):
    """Get current user info and credits"""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    credits = await get_user_credits(user['user_id'])
    return {'user': user, 'credits': credits}


# ── Early-access credit bridge ───────────────────────────────────────────────
# ONE-TIME 10-credit top-up for users currently in paywall_bypass mode who
# have hit 0 credits. Prevents dead-ends while subscription loading is
# stabilized, without opening a credit firehose for the entire user base.
#
# Guardrails (non-negotiable):
#   • ONLY applies to tier == 'paywall_bypass'. Real paid, referral-premium,
#     trial, expired, or tier=None users are never touched.
#   • ONLY fires when available_credits <= 0 AND received_temp_credits is
#     falsy. The flag is set atomically on the same update so re-invocations
#     no-op.
#   • Audit log entry is written to db.admin_actions with admin_email
#     'system:early-access-bridge' so ops can track every grant.
#
# Idempotency: the Mongo update uses a conditional filter on the flag, so
# concurrent calls from two tabs cannot double-grant.
EARLY_ACCESS_BRIDGE_CREDITS = 10
EARLY_ACCESS_BRIDGE_MESSAGE = (
    "Early Access Update\n\n"
    "We’re finalizing the credit and subscription system.\n\n"
    "To keep things running smoothly, we’ve added a complimentary set of "
    "credits to your account.\n\n"
    "This early-access phase is temporary while we lock in the full "
    "experience.\n\n"
    "Appreciate you being part of it."
)


@api_router.post("/credits/early-access-bridge")
async def early_access_credit_bridge(request: FastAPIRequest):
    """Idempotent, one-time 10-credit top-up for paywall_bypass users at 0."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    # Atomic eligibility check + grant + flag set. If any guardrail fails
    # (wrong tier, credits > 0, flag already true) the filter misses and we
    # return granted=false. This is the ONLY place that increments credits
    # under the 'early_access_bridge' source label.
    result = await db.subscriptions.find_one_and_update(
        {
            'user_id': user_id,
            'tier': 'paywall_bypass',
            'available_credits': {'$lte': 0},
            '$or': [
                {'received_temp_credits': {'$exists': False}},
                {'received_temp_credits': False},
                {'received_temp_credits': None},
            ],
        },
        {
            '$set': {
                'available_credits': EARLY_ACCESS_BRIDGE_CREDITS,
                'received_temp_credits': True,
                'received_temp_credits_at': datetime.now(timezone.utc).isoformat(),
                'received_temp_credits_source': 'early_access_bridge',
            },
        },
        return_document=ReturnDocument.AFTER,
    )

    if not result:
        # Not eligible — no state change. Silent no-op for the client.
        return {
            'granted': False,
            'reason': 'not_eligible',
            'message': None,
            'credits': None,
        }

    # Audit log so ops can track exactly who received the bridge.
    try:
        await log_admin_action(
            admin_email='system:early-access-bridge',
            action='early_access_credit_bridge',
            target_email=user.get('email', '') or '',
            details={
                'user_id': user_id,
                'tier': 'paywall_bypass',
                'credits_granted': EARLY_ACCESS_BRIDGE_CREDITS,
                'new_total': result.get('available_credits'),
            },
        )
    except Exception as audit_err:
        # Never let audit-log failure block the user. Log + continue.
        logger.error(f'[EarlyAccessBridge] audit log failed for {user_id}: {audit_err}')

    logger.info(
        f'[EarlyAccessBridge] Granted {EARLY_ACCESS_BRIDGE_CREDITS} credits to '
        f'user={user_id} email={user.get("email")}'
    )
    return {
        'granted': True,
        'reason': 'bypass_zero_credits_onetime',
        'message': EARLY_ACCESS_BRIDGE_MESSAGE,
        'credits': result.get('available_credits'),
    }

@api_router.post("/credits/deduct")
async def deduct_credit(request: FastAPIRequest):
    """Deduct 1 credit for stencil generation (atomic).
    
    For studio team members, deducts from the shared team pool instead of individual credits.

    Idempotency: clients SHOULD pass a unique `reroll_id` (any client-generated
    string — UUID v4 recommended) per intended deduction. Repeat requests with
    the same (user_id, reroll_id) within IDEMPOTENCY_TTL_SECONDS return the
    original response without a second deduction. This protects against rapid
    double-taps on the regenerate button (a real frontend race condition).
    """
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    # Optional idempotency key from body. Body is also OK to be empty.
    try:
        body = await request.json()
    except Exception:
        body = {}
    reroll_id = (body or {}).get('reroll_id')

    if reroll_id:
        # Atomic insert — fails (DuplicateKey) if this (user_id, reroll_id)
        # was already processed. We then return the cached response.
        idem_key = f"{user_id}:{reroll_id}"
        try:
            await db.credit_deduct_idempotency.insert_one({
                '_id': idem_key,
                'user_id': user_id,
                'reroll_id': reroll_id,
                'created_at': datetime.now(timezone.utc),
                'response': None,  # filled in below after successful deduct
            })
        except DuplicateKeyError:
            existing = await db.credit_deduct_idempotency.find_one(
                {'_id': idem_key}, {'_id': 0, 'response': 1}
            )
            if existing and existing.get('response'):
                logger.info(f"[CreditsDeduct] Idempotent replay for {idem_key} — returning cached response, no deduction")
                return existing['response']
            # Sentinel exists but response not yet written → first call still
            # in flight. Reject the duplicate so the client doesn't think it
            # got a free deduction.
            logger.warning(f"[CreditsDeduct] In-flight duplicate for {idem_key} — rejecting")
            raise HTTPException(status_code=409, detail='Duplicate deduction in progress')

    # Check if user is part of a studio team
    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    studio_team_id = sub.get('studio_team_id') if sub else None
    
    if studio_team_id:
        # User is part of a studio team - deduct from shared pool
        team_result = await db.studio_teams.find_one_and_update(
            {'team_id': studio_team_id, 'shared_credits': {'$gt': 0}},
            {'$inc': {'shared_credits': -1}},
            return_document=True,
            projection={'_id': 0}
        )
        if not team_result:
            if reroll_id:
                # Clear sentinel so a subsequent retry can proceed once credits are restored.
                await db.credit_deduct_idempotency.delete_one({'_id': f"{user_id}:{reroll_id}"})
            raise HTTPException(status_code=402, detail='Studio team has no credits remaining')
        response_payload = {
            'available_credits': team_result['shared_credits'],
            'tier': 'the-shop',
            'is_studio_team': True,
        }
        if reroll_id:
            await db.credit_deduct_idempotency.update_one(
                {'_id': f"{user_id}:{reroll_id}"},
                {'$set': {'response': response_payload}},
            )
        return response_payload

    # Regular individual credit deduction
    # Also increments `credits_consumed_this_cycle` — used by the Walk-In upsell
    # banner to decide when to soft-prompt an upgrade.
    result = await db.subscriptions.find_one_and_update(
        {'user_id': user_id, 'available_credits': {'$gt': 0}},
        {
            '$inc': {
                'available_credits': -1,
                'credits_consumed_this_cycle': 1,
            },
        },
        return_document=True,
        projection={'_id': 0}
    )
    if not result:
        if reroll_id:
            await db.credit_deduct_idempotency.delete_one({'_id': f"{user_id}:{reroll_id}"})
        raise HTTPException(status_code=402, detail='Insufficient credits')
    tier = result.get('tier', '')
    TIER_CREDITS_MAP = {'walk-in': 125, 'booked-out': 500, 'the-shop': 1500, 'the-shop-member': 1500, 'referral_premium': 125}
    response_payload = {
        'available_credits': result['available_credits'],
        'total_monthly_credits': TIER_CREDITS_MAP.get(tier, 0),
        'tier': tier,
    }
    if reroll_id:
        await db.credit_deduct_idempotency.update_one(
            {'_id': f"{user_id}:{reroll_id}"},
            {'$set': {'response': response_payload}},
        )
    return response_payload

# ---- Walk-In behavioral upsell tracking ----

async def _log_upsell_event(user_id: str, event: str, cycle_key: Optional[str]):
    """Log a Walk-In upsell event to a dedicated audit collection."""
    await db.upsell_events.insert_one({
        'user_id': user_id,
        'event': event,  # 'shown' | 'dismissed' | 'cta_tapped' | 'upgraded'
        'cycle_key': cycle_key,
        'created_at': datetime.now(timezone.utc).isoformat(),
    })


@api_router.post("/upsell/walk-in/shown")
async def upsell_walkin_shown(request: FastAPIRequest):
    """Mark the Walk-In upsell as shown for the current cycle."""
    user = await get_current_user(request.headers.get('authorization'))
    user_id = user['user_id']
    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0}) or {}
    cycle_key = sub.get('last_refill_at')
    if sub.get('upsell_shown_for_cycle') != cycle_key:
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {'upsell_shown_for_cycle': cycle_key}},
        )
        await _log_upsell_event(user_id, 'shown', cycle_key)
    return {'status': 'ok'}


@api_router.post("/upsell/walk-in/dismiss")
async def upsell_walkin_dismiss(request: FastAPIRequest):
    """Dismiss the Walk-In upsell for the current cycle (permanent until next refill)."""
    user = await get_current_user(request.headers.get('authorization'))
    user_id = user['user_id']
    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0}) or {}
    cycle_key = sub.get('last_refill_at')
    await db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': {'upsell_dismissed_for_cycle': cycle_key}},
    )
    await _log_upsell_event(user_id, 'dismissed', cycle_key)
    return {'status': 'ok'}


@api_router.post("/upsell/walk-in/cta-tapped")
async def upsell_walkin_cta_tapped(request: FastAPIRequest):
    """Track that the user tapped View Plans from the upsell banner."""
    user = await get_current_user(request.headers.get('authorization'))
    user_id = user['user_id']
    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0}) or {}
    await _log_upsell_event(user_id, 'cta_tapped', sub.get('last_refill_at'))
    return {'status': 'ok'}


# ---- Stencil Quality Ratings (thumbs up / down) ----

class StencilRatingRequest(BaseModel):
    style: str = Field(..., description="light | medium | heavy")
    rating: str = Field(..., description="up | down")
    stencil_hash: Optional[str] = Field(default=None, description="Optional hash/id of the stencil image for dedupe")
    prompt_version: Optional[str] = Field(default=None, description="Optional tag for which prompt produced this stencil")


@api_router.post("/stencil-rating")
async def submit_stencil_rating(payload: StencilRatingRequest, request: FastAPIRequest):
    """Submit a thumbs up/down rating for a generated stencil.

    Anonymous-friendly: if no auth header, `user_id` is stored as None. This is an
    intentionally low-friction feedback pipe — no PII, no comments, just signal.
    """
    if payload.style not in {"light", "medium", "heavy"}:
        raise HTTPException(status_code=400, detail="style must be light|medium|heavy")
    if payload.rating not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="rating must be up|down")

    user_id: Optional[str] = None
    auth = request.headers.get('authorization', '')
    token = auth.replace('Bearer ', '') if auth else ''
    if token:
        try:
            decoded = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            user_id = decoded.get('user_id')
        except Exception:
            user_id = None

    doc = {
        'user_id': user_id,
        'style': payload.style,
        'rating': payload.rating,
        'stencil_hash': payload.stencil_hash,
        'prompt_version': payload.prompt_version,
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    await db.stencil_ratings.insert_one(doc)
    logger.info(f"[StencilRating] user={user_id} style={payload.style} rating={payload.rating}")
    return {'status': 'ok'}


@api_router.get("/admin/stencil-ratings")
async def admin_stencil_ratings(request: FastAPIRequest):
    """Admin dashboard view: aggregated thumbs-up/down counts per style + recent ratings."""
    await verify_admin(request.headers.get('authorization'))

    # Aggregate counts per style × rating
    pipeline = [
        {'$group': {
            '_id': {'style': '$style', 'rating': '$rating'},
            'count': {'$sum': 1},
        }}
    ]
    agg_rows = [row async for row in db.stencil_ratings.aggregate(pipeline)]
    summary: dict = {
        'light': {'up': 0, 'down': 0},
        'medium': {'up': 0, 'down': 0},
        'heavy': {'up': 0, 'down': 0},
    }
    for row in agg_rows:
        style = row['_id'].get('style')
        rating = row['_id'].get('rating')
        if style in summary and rating in ('up', 'down'):
            summary[style][rating] = int(row['count'])

    total_up = sum(s['up'] for s in summary.values())
    total_down = sum(s['down'] for s in summary.values())
    total = total_up + total_down

    # Recent 50 ratings (no _id, latest first)
    recent_cursor = db.stencil_ratings.find({}, {'_id': 0}).sort('created_at', -1).limit(50)
    recent = [doc async for doc in recent_cursor]

    return {
        'summary': summary,
        'totals': {
            'up': total_up,
            'down': total_down,
            'total': total,
            'satisfaction_pct': round((total_up / total) * 100, 1) if total else None,
        },
        'recent': recent,
    }




@api_router.post("/credits/emergency-stencil")
async def claim_emergency_stencil(request: FastAPIRequest):
    """One-time monthly Emergency Stencil fallback.

    Rules:
    - User must have 0 credits.
    - Not more than one emergency stencil per calendar month (resets on the 1st UTC).
    - Grants exactly 1 credit.
    - Atomic via a conditional find_one_and_update — safe against double-tap.
    """
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    now = datetime.now(timezone.utc)
    current_month_key = now.strftime('%Y-%m')  # e.g. '2026-04'

    # Atomic claim: only succeeds if credits == 0 AND emergency hasn't been used this month.
    claimed = await db.subscriptions.find_one_and_update(
        {
            'user_id': user_id,
            'available_credits': 0,
            '$or': [
                {'emergency_stencil_month': {'$ne': current_month_key}},
                {'emergency_stencil_month': {'$exists': False}},
            ],
        },
        {
            '$set': {
                'emergency_stencil_month': current_month_key,
                'emergency_stencil_used_at': now.isoformat(),
            },
            '$inc': {'available_credits': 1},
        },
        return_document=True,
        projection={'_id': 0},
    )

    if not claimed:
        # Determine why: already used vs. has credits
        existing = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0}) or {}
        if existing.get('available_credits', 0) > 0:
            raise HTTPException(status_code=400, detail='You still have credits available.')
        if existing.get('emergency_stencil_month') == current_month_key:
            raise HTTPException(status_code=400, detail='Emergency stencil already used this month.')
        raise HTTPException(status_code=400, detail='Emergency stencil is not available.')

    logger.info(f'[EmergencyStencil] Granted to {user_id} (month={current_month_key})')
    return {
        'status': 'ok',
        'available_credits': claimed['available_credits'],
        'emergency_stencil_month': current_month_key,
    }



@api_router.delete("/account/delete")
async def delete_account(request: FastAPIRequest):
    """Delete user account and all data (App Store requirement)"""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    await db.users.delete_one({'user_id': user_id})
    await db.subscriptions.delete_many({'user_id': user_id})
    await db.stencils.delete_many({'user_id': user_id})
    # Also remove from any studio teams
    await db.studio_teams.update_many(
        {'members.user_id': user_id},
        {'$pull': {'members': {'user_id': user_id}}}
    )
    # Delete team if user was admin
    await db.studio_teams.delete_many({'admin_user_id': user_id})
    return {'message': 'Account deleted successfully'}

# ---- Studio Tier Team Management ----
# The Shop ($99/mo) allows up to 5 team members sharing 1500 credits

STUDIO_MAX_MEMBERS = 5
STUDIO_CREDITS = 1500

class StudioInviteRequest(BaseModel):
    email: str = Field(..., description="Email of user to invite")

class StudioInviteResponse(BaseModel):
    invite_code: str
    expires_at: str
    email: str

class StudioAcceptInviteRequest(BaseModel):
    invite_code: str

class StudioTeamMember(BaseModel):
    user_id: str
    email: Optional[str]
    name: Optional[str]
    role: str  # 'admin' or 'member'
    joined_at: str

class StudioTeamResponse(BaseModel):
    team_id: str
    admin_user_id: str
    members: List[StudioTeamMember]
    shared_credits: int
    max_members: int
    created_at: str

async def get_user_studio_team(user_id: str) -> Optional[dict]:
    """Get the studio team for a user (either as admin or member)."""
    # Check if user is admin
    team = await db.studio_teams.find_one({'admin_user_id': user_id}, {'_id': 0})
    if team:
        return team
    # Check if user is a member
    team = await db.studio_teams.find_one({'members.user_id': user_id}, {'_id': 0})
    return team

async def deduct_studio_credit(team_id: str) -> dict:
    """Atomically deduct 1 credit from studio team shared pool."""
    result = await db.studio_teams.find_one_and_update(
        {'team_id': team_id, 'shared_credits': {'$gt': 0}},
        {'$inc': {'shared_credits': -1}},
        return_document=True,
        projection={'_id': 0}
    )
    return result

@api_router.get("/studio/team")
async def get_studio_team(request: FastAPIRequest):
    """Get current user's studio team info."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    
    team = await get_user_studio_team(user['user_id'])
    if not team:
        raise HTTPException(status_code=404, detail='Not part of a studio team')
    
    # Enrich member info with names
    enriched_members = []
    for member in team.get('members', []):
        user_info = await db.users.find_one({'user_id': member['user_id']}, {'_id': 0})
        enriched_members.append({
            'user_id': member['user_id'],
            'email': user_info.get('email') if user_info else member.get('email'),
            'name': user_info.get('name') if user_info else None,
            'role': member.get('role', 'member'),
            'joined_at': member.get('joined_at', team.get('created_at')),
        })
    
    return {
        'team_id': team['team_id'],
        'admin_user_id': team['admin_user_id'],
        'members': enriched_members,
        'shared_credits': team.get('shared_credits', 0),
        'max_members': STUDIO_MAX_MEMBERS,
        'created_at': team.get('created_at'),
    }

@api_router.post("/studio/create")
async def create_studio_team(request: FastAPIRequest):
    """Create a new studio team (user must have 'the-shop' subscription)."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    
    # Verify user has The Shop subscription
    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    if not sub or sub.get('tier') != 'the-shop':
        raise HTTPException(status_code=403, detail='The Shop subscription required to create a studio team')
    
    # Check if user already has a team
    existing_team = await get_user_studio_team(user_id)
    if existing_team:
        raise HTTPException(status_code=400, detail='Already part of a studio team')
    
    now = datetime.now(timezone.utc).isoformat()
    team_id = f'studio_{uuid.uuid4().hex[:12]}'
    
    team = {
        'team_id': team_id,
        'admin_user_id': user_id,
        'members': [{
            'user_id': user_id,
            'email': user.get('email'),
            'role': 'admin',
            'joined_at': now,
        }],
        'shared_credits': STUDIO_CREDITS,
        'created_at': now,
        'pending_invites': [],
    }
    
    await db.studio_teams.insert_one(team)
    
    # Update subscription to link to team
    await db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': {'studio_team_id': team_id}}
    )
    
    logger.info(f'[Studio] Team {team_id} created by user {user_id}')
    
    return {
        'team_id': team_id,
        'shared_credits': STUDIO_CREDITS,
        'message': 'Studio team created successfully',
    }

@api_router.post("/studio/invite", response_model=StudioInviteResponse)
async def invite_to_studio(request: FastAPIRequest, invite_request: StudioInviteRequest):
    """Invite a user to join your studio team (admin only)."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    
    # Get team and verify admin
    team = await db.studio_teams.find_one({'admin_user_id': user_id}, {'_id': 0})
    if not team:
        raise HTTPException(status_code=403, detail='Only team admin can invite members')
    
    # Check member limit
    if len(team.get('members', [])) >= STUDIO_MAX_MEMBERS:
        raise HTTPException(status_code=400, detail=f'Team already has maximum {STUDIO_MAX_MEMBERS} members')
    
    # Check if email already a member
    invited_email = invite_request.email.lower()
    for member in team.get('members', []):
        member_user = await db.users.find_one({'user_id': member['user_id']}, {'_id': 0})
        if member_user and member_user.get('email', '').lower() == invited_email:
            raise HTTPException(status_code=400, detail='User is already a team member')
    
    # Generate invite code
    invite_code = f'inv_{uuid.uuid4().hex[:16]}'
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    
    # Store invite
    invite = {
        'code': invite_code,
        'email': invited_email,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'expires_at': expires_at,
    }
    
    await db.studio_teams.update_one(
        {'team_id': team['team_id']},
        {'$push': {'pending_invites': invite}}
    )
    
    logger.info(f'[Studio] Invite {invite_code} created for {invited_email} to team {team["team_id"]}')
    
    return StudioInviteResponse(
        invite_code=invite_code,
        expires_at=expires_at,
        email=invited_email,
    )

@api_router.post("/studio/accept-invite")
async def accept_studio_invite(request: FastAPIRequest, accept_request: StudioAcceptInviteRequest):
    """Accept a studio team invitation."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    user_email = (user.get('email') or '').lower()
    
    # Check if user already in a team
    existing_team = await get_user_studio_team(user_id)
    if existing_team:
        raise HTTPException(status_code=400, detail='Already part of a studio team')
    
    # Find team with this invite
    team = await db.studio_teams.find_one(
        {'pending_invites.code': accept_request.invite_code},
        {'_id': 0}
    )
    
    if not team:
        raise HTTPException(status_code=404, detail='Invalid invite code')
    
    # Find the specific invite
    invite = None
    for inv in team.get('pending_invites', []):
        if inv['code'] == accept_request.invite_code:
            invite = inv
            break
    
    if not invite:
        raise HTTPException(status_code=404, detail='Invite not found')
    
    # Check if expired
    expires_at = datetime.fromisoformat(invite['expires_at'].replace('Z', '+00:00'))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail='Invite has expired')
    
    # Verify email matches (optional but recommended)
    if user_email and invite['email'] and user_email != invite['email']:
        logger.warning(f'[Studio] Email mismatch: invite for {invite["email"]}, user has {user_email}')
        # Allow anyway for flexibility, but log it
    
    # Check member limit again
    if len(team.get('members', [])) >= STUDIO_MAX_MEMBERS:
        raise HTTPException(status_code=400, detail='Team is now full')
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Add user to team and remove invite
    await db.studio_teams.update_one(
        {'team_id': team['team_id']},
        {
            '$push': {'members': {
                'user_id': user_id,
                'email': user_email,
                'role': 'member',
                'joined_at': now,
            }},
            '$pull': {'pending_invites': {'code': accept_request.invite_code}},
        }
    )
    
    # Link user's subscription to team
    await db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': {'studio_team_id': team['team_id'], 'tier': 'the-shop-member'}}
    )
    
    logger.info(f'[Studio] User {user_id} joined team {team["team_id"]}')
    
    return {
        'message': 'Successfully joined studio team',
        'team_id': team['team_id'],
    }

@api_router.delete("/studio/member/{member_user_id}")
async def remove_studio_member(request: FastAPIRequest, member_user_id: str):
    """Remove a member from the studio team (admin only)."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    
    # Get team and verify admin
    team = await db.studio_teams.find_one({'admin_user_id': user_id}, {'_id': 0})
    if not team:
        raise HTTPException(status_code=403, detail='Only team admin can remove members')
    
    # Can't remove yourself as admin
    if member_user_id == user_id:
        raise HTTPException(status_code=400, detail='Admin cannot remove themselves. Transfer ownership first.')
    
    # Check if member exists in team
    member_found = False
    for member in team.get('members', []):
        if member['user_id'] == member_user_id:
            member_found = True
            break
    
    if not member_found:
        raise HTTPException(status_code=404, detail='Member not found in team')
    
    # Remove member
    await db.studio_teams.update_one(
        {'team_id': team['team_id']},
        {'$pull': {'members': {'user_id': member_user_id}}}
    )
    
    # Update removed member's subscription
    await db.subscriptions.update_one(
        {'user_id': member_user_id},
        {'$unset': {'studio_team_id': ''}, '$set': {'tier': None, 'available_credits': 0}}
    )
    
    logger.info(f'[Studio] User {member_user_id} removed from team {team["team_id"]} by admin {user_id}')
    
    return {'message': 'Member removed successfully'}

@api_router.post("/studio/leave")
async def leave_studio_team(request: FastAPIRequest):
    """Leave a studio team (non-admin members only)."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    
    # Get user's team
    team = await get_user_studio_team(user_id)
    if not team:
        raise HTTPException(status_code=404, detail='Not part of a studio team')
    
    # Admin cannot leave - must transfer or delete
    if team['admin_user_id'] == user_id:
        raise HTTPException(status_code=400, detail='Admin cannot leave. Transfer ownership or delete the team.')
    
    # Remove from team
    await db.studio_teams.update_one(
        {'team_id': team['team_id']},
        {'$pull': {'members': {'user_id': user_id}}}
    )
    
    # Update subscription
    await db.subscriptions.update_one(
        {'user_id': user_id},
        {'$unset': {'studio_team_id': ''}, '$set': {'tier': None, 'available_credits': 0}}
    )
    
    logger.info(f'[Studio] User {user_id} left team {team["team_id"]}')
    
    return {'message': 'Successfully left the studio team'}

# ---- RevenueCat Webhook ----
REVENUECAT_WEBHOOK_AUTH = os.environ.get('REVENUECAT_WEBHOOK_AUTH', '')
CRON_SECRET = os.environ.get('CRON_SECRET', '')
PRODUCT_CREDIT_MAP = {
    # App Store product identifiers registered in App Store Connect for this
    # project use short numeric codes — this is what Apple/StoreKit returns
    # in receipts and what RevenueCat sends through webhooks (event.product_id)
    # and through CustomerInfo.entitlements[x].productIdentifier. The names
    # below ("The Walk In", "Booked Out", "The Shop") correspond to these.
    '01': {'tier': 'walk-in', 'credits': 125},
    '02': {'tier': 'booked-out', 'credits': 500},
    '03': {'tier': 'the-shop', 'credits': 1500},
    # Legacy / RevenueCat package identifiers kept for backwards-compat in
    # case any older webhook re-delivery references them. Never remove these
    # without first confirming no in-flight subscriptions still carry them.
    'bodybound_1499_1m_3d': {'tier': 'walk-in', 'credits': 125},
    'bodybound_2999_1m_3d': {'tier': 'booked-out', 'credits': 500},
    'bodybound_9999_1m_3d': {'tier': 'the-shop', 'credits': 1500},
}


async def apply_paid_subscription_state(
    user_id: str,
    product_id: str,
    source: str,
    rc_customer_id: Optional[str] = None,
    is_apple_trial: bool = False,
) -> dict:
    """Single authoritative writer for paid subscription state.

    STRICT RULES (per product spec):
    - product_id is the ONLY source of truth for tier + credits.
    - No fallback to walk-in, no default 10 credits, no silent trial.
    - If product_id is unknown, DO NOT overwrite user state — log and raise.
    - Always sets is_trial = (is_apple_trial only). Never flips to trial silently.
    - Resets credits_consumed_this_cycle on every paid-state application.

    The `source` string is stamped into last_event for auditability:
    one of: 'INITIAL_PURCHASE' | 'RENEWAL' | 'FRONTEND_SYNC' | 'ADMIN' etc.

    Returns the updated subscription doc.
    """
    tier_info = PRODUCT_CREDIT_MAP.get(product_id)
    if not tier_info:
        logger.error(
            f'[PaidState] REFUSED to apply unknown product_id={product_id!r} '
            f'for user_id={user_id} source={source}. User state preserved.'
        )
        raise ValueError(f'Unknown product_id: {product_id}')

    tier = tier_info['tier']
    # Trial period gets the symbolic TRIAL_CREDITS cap; paid gets full allowance.
    credits = TRIAL_CREDITS if is_apple_trial else tier_info['credits']
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── Idempotent FRONTEND_SYNC guard ─────────────────────────────────
    # /api/subscription/sync fires on every app cold-start. If the user is
    # already on the same tier + trial state, we MUST NOT reset
    # available_credits or credits_consumed_this_cycle — that would refill
    # the user's bucket on every app launch. Genuine paid-state transitions
    # (webhook INITIAL_PURCHASE / RENEWAL, ADMIN, or a tier change via
    # FRONTEND_SYNC) still take the full apply path below.
    #
    # NOTE: We compare TIER, not product_id. PRODUCT_CREDIT_MAP exposes
    # multiple product_id aliases per tier (App Store short codes "01",
    # "02", "03" + legacy RC package ids "bodybound_..._1m_3d"). The iOS
    # frontend may send any of them depending on which path resolved the
    # active entitlement. Comparing product_id strings would falsely
    # invalidate the idempotency check and re-trigger the credit reset.
    existing_sub = await db.subscriptions.find_one(
        {'user_id': user_id}, {'_id': 0}
    ) or {}
    is_idempotent_resync = (
        source == 'FRONTEND_SYNC'
        and existing_sub.get('tier') == tier
        and bool(existing_sub.get('is_trial')) == bool(is_apple_trial)
    )
    logger.info(
        f'[PaidState] Resync-check user={user_id} source={source} '
        f'incoming_tier={tier} existing_tier={existing_sub.get("tier")} '
        f'incoming_product={product_id} existing_product={existing_sub.get("last_product_id")} '
        f'incoming_trial={bool(is_apple_trial)} existing_trial={bool(existing_sub.get("is_trial"))} '
        f'→ idempotent={is_idempotent_resync}'
    )
    if is_idempotent_resync:
        light_set = {
            'last_event': source,
            'last_applied_at': now_iso,
        }
        if rc_customer_id:
            light_set['revenuecat_customer_id'] = rc_customer_id
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': light_set},
        )
        logger.info(
            f'[PaidState] FRONTEND_SYNC no-op: user={user_id} product={product_id} '
            f'tier={tier} — credits preserved (already on same tier+product)'
        )
        return await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})

    next_renewal = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    set_doc = {
        'user_id': user_id,
        'tier': tier,
        'available_credits': credits,
        'is_trial': bool(is_apple_trial),
        'period_type': 'TRIAL' if is_apple_trial else 'NORMAL',
        'monthly_allowance': tier_info['credits'],
        'max_balance_cap': tier_info['credits'] * BALANCE_CAP_MULTIPLIER,
        'credits_consumed_this_cycle': 0,
        # New cycle → wipe per-cycle upsell flags so the Walk-In nudge can
        # re-trigger next cycle if criteria are still met.
        'upsell_shown_for_cycle': None,
        'upsell_dismissed_for_cycle': None,
        'trial_expires_at': None,
        'renewal_date': next_renewal,
        'last_event': source,
        'last_product_id': product_id,
        'last_applied_at': now_iso,
        'last_refill_at': f'paid:{now_iso}',
    }
    if rc_customer_id:
        set_doc['revenuecat_customer_id'] = rc_customer_id

    await db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': set_doc},
        upsert=True,
    )
    logger.info(
        f'[PaidState] Applied {source}: user={user_id} product={product_id} '
        f'→ tier={tier} credits={credits} trial={is_apple_trial}'
    )
    return await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})

# ── Promo Code System ──────────────────────────────────────────
@api_router.post("/promo/redeem")
async def redeem_promo_code(request: FastAPIRequest):
    """Redeem a promo code for a free subscription period"""
    auth = request.headers.get('authorization', '')
    token = auth.replace('Bearer ', '') if auth else ''
    user_id = None
    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            user_id = payload.get('user_id')
        except Exception:
            pass
    if not user_id:
        raise HTTPException(status_code=401, detail='Missing authorization')
    
    body = await request.json()
    code = body.get('code', '').strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail='Missing promo code')
    
    # Look up the promo code
    promo = await db.promo_codes.find_one({'code': code, 'active': True}, {'_id': 0})
    if not promo:
        raise HTTPException(status_code=400, detail='Invalid or expired promo code')
    
    # Check if user already redeemed this code
    existing = await db.promo_redemptions.find_one({'user_id': user_id, 'code': code})
    if existing:
        raise HTTPException(status_code=400, detail='You have already used this promo code')
    
    # Check if this code is email-restricted
    allowed_emails = promo.get('allowed_emails', [])
    if allowed_emails:
        user = await db.users.find_one({'user_id': user_id}, {'_id': 0, 'email': 1})
        user_email = (user.get('email', '') if user else '').lower()
        if user_email not in [e.lower() for e in allowed_emails]:
            raise HTTPException(status_code=403, detail='This promo code is not available for your account')
    
    # Check max total redemptions
    max_uses = promo.get('max_uses', 0)
    if max_uses > 0:
        total_used = await db.promo_redemptions.count_documents({'code': code})
        if total_used >= max_uses:
            raise HTTPException(status_code=400, detail='This promo code has reached its limit')
    
    # Apply the promo
    tier = promo.get('tier', 'walk-in')
    credits = promo.get('credits', 125)
    duration_days = promo.get('duration_days', 30)
    
    await db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': {
            'tier': tier,
            'available_credits': credits,
            'is_trial': False,
            'last_event': 'PROMO_REDEEM',
            'synced_from': f'promo:{code}',
            'renewal_date': (datetime.now(timezone.utc) + timedelta(days=duration_days)).isoformat()
        }},
        upsert=True
    )
    
    # Record redemption
    await db.promo_redemptions.insert_one({
        'user_id': user_id,
        'code': code,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })
    
    logger.info(f'[Promo] {user_id} redeemed {code} -> {tier} ({credits} credits, {duration_days} days)')
    
    return {
        'status': 'success',
        'message': f'Promo code applied! You have {credits} credits for {duration_days} days.',
        'tier': tier,
        'available_credits': credits,
        'needs_subscription': False
    }

@api_router.post("/admin/add-credits")
async def admin_add_credits(request: Request):
    """Admin endpoint to add bonus credits to a user"""
    body = await request.json()
    email = body.get('email', '')
    bonus = body.get('credits', 0)
    
    if not email or not bonus:
        raise HTTPException(status_code=400, detail="Provide email and credits")
    
    user = await db.users.find_one({'email': {'$regex': email, '$options': 'i'}}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    uid = user['user_id']
    result = await db.subscriptions.update_one(
        {'user_id': uid},
        {'$inc': {'available_credits': bonus}},
    )
    
    if result.matched_count == 0:
        # Create subscription if none exists
        await db.subscriptions.insert_one({
            'user_id': uid,
            'tier': 'trial',
            'available_credits': bonus,
            'is_trial': True,
            'last_event': 'LOYALTY_BONUS',
            'synced_from': 'admin_bonus'
        })
    
    updated = await db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    return {"status": "credits_added", "email": email, "bonus": bonus, "new_total": updated.get('available_credits', 0)}

@api_router.post("/admin/paywall-bypass")
async def admin_paywall_bypass(request: Request):
    """Temporary paywall bypass: grants 10 credits with a non-subscriber tier.
    Does NOT count as a real subscription for referrals, analytics, or credit refresh."""
    body = await request.json()
    email = body.get('email', '')
    if not email:
        raise HTTPException(status_code=400, detail="Provide email")

    user = await db.users.find_one({'email': {'$regex': email, '$options': 'i'}}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    uid = user['user_id']
    await db.subscriptions.update_one(
        {'user_id': uid},
        {'$set': {
            'tier': 'paywall_bypass',
            'available_credits': 10,
            'is_trial': False,
            'last_event': 'PAYWALL_BYPASS',
            'synced_from': 'admin_temp_bypass',
            'bypass_granted_at': datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True
    )
    logger.info(f"[Admin] Paywall bypass granted to {email} ({uid}) — 10 credits, tier=paywall_bypass")
    return {"status": "bypass_granted", "email": email, "credits": 10, "tier": "paywall_bypass"}

@api_router.get("/admin/webhook-debug")
async def admin_webhook_debug():
    """Inspect recent webhook activity for debugging RevenueCat sync issues."""
    unmatched = []
    async for doc in db.unmatched_webhooks.find({}, {'_id': 0}).sort('timestamp', -1).limit(20):
        unmatched.append(doc)
    
    # Check for any subscriptions with last_event from webhooks
    webhook_updated = []
    async for doc in db.subscriptions.find(
        {'last_event': {'$in': ['INITIAL_PURCHASE', 'RENEWAL', 'CANCELLATION', 'EXPIRATION', 'TRANSFER', 'TRANSFER_DEFAULT', 'TRANSFER_OUT']}},
        {'_id': 0}
    ).limit(20):
        webhook_updated.append(doc)
    
    # Count totals
    total_unmatched = await db.unmatched_webhooks.count_documents({})
    total_subs = await db.subscriptions.count_documents({})
    
    return {
        "total_unmatched_webhooks": total_unmatched,
        "total_subscriptions": total_subs,
        "recent_unmatched": unmatched,
        "webhook_updated_subscriptions": webhook_updated,
    }

@api_router.post("/admin/create-promo")
async def admin_create_promo(request: Request):
    """Admin endpoint to create a promo code"""
    body = await request.json()
    code = body.get('code', '').strip().upper()
    tier = body.get('tier', 'walk-in')
    credits = body.get('credits', 125)
    duration_days = body.get('duration_days', 30)
    allowed_emails = body.get('allowed_emails', [])
    max_uses = body.get('max_uses', 0)
    
    if not code:
        raise HTTPException(status_code=400, detail='Missing code')
    
    await db.promo_codes.update_one(
        {'code': code},
        {'$set': {
            'code': code,
            'tier': tier,
            'credits': credits,
            'duration_days': duration_days,
            'allowed_emails': [e.lower() for e in allowed_emails],
            'max_uses': max_uses,
            'active': True,
            'created_at': datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    
    return {'status': 'created', 'code': code, 'allowed_emails': len(allowed_emails), 'tier': tier, 'credits': credits}


# ---- Feedback System ----

@api_router.post("/feedback")
async def submit_feedback(request: FastAPIRequest):
    """Store user feedback (positive/negative, text, tags)."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    body = await request.json()
    sentiment = body.get('sentiment', '')  # 'positive' or 'negative'
    text = body.get('text', '')
    tags = body.get('tags', [])  # e.g. ['realism', 'speed', 'clean_lines']
    action_taken = body.get('action_taken', '')  # 'shared', 'feedback', 'review', 'skip'

    now = datetime.now(timezone.utc).isoformat()
    await db.user_feedback.insert_one({
        'user_id': user_id,
        'sentiment': sentiment,
        'text': text,
        'tags': tags,
        'action_taken': action_taken,
        'created_at': now,
    })

    # Record that user has given feedback (for frequency control)
    await db.feedback_status.update_one(
        {'user_id': user_id},
        {'$set': {
            'last_feedback_at': now,
            'has_submitted': True,
            'last_action': action_taken,
            'last_sentiment': sentiment,
        }},
        upsert=True,
    )

    logger.info(f'[Feedback] {user_id}: {sentiment} — action={action_taken}, tags={tags}')
    return {'status': 'ok'}


@api_router.get("/feedback/should-prompt")
async def should_prompt_feedback(request: FastAPIRequest):
    """Check if user should see the feedback prompt.
    Rules: 3+ successful generations, not already submitted, max once per session (client-side)."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    # Check if user already submitted feedback or review
    status = await db.feedback_status.find_one({'user_id': user_id}, {'_id': 0})
    if status and status.get('has_submitted'):
        last_action = status.get('last_action', '')
        # Stop prompting if user shared, left review, or gave feedback
        if last_action in ('shared', 'review', 'feedback'):
            return {'should_prompt': False, 'reason': 'already_completed'}

    # Check generation count (from subscriptions/usage)
    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    if not sub:
        return {'should_prompt': False, 'reason': 'no_subscription'}

    # Count stencil generations for this user
    gen_count = await db.generation_log.count_documents({'user_id': user_id})
    if gen_count < 3:
        return {'should_prompt': False, 'reason': 'insufficient_usage', 'generations': gen_count}

    return {'should_prompt': True, 'generations': gen_count}


@api_router.get("/admin/feedback-summary")
async def admin_feedback_summary():
    """Admin view of all feedback."""
    all_feedback = await db.user_feedback.find({}, {'_id': 0}).sort('created_at', -1).to_list(100)
    positive = sum(1 for f in all_feedback if f.get('sentiment') == 'positive')
    negative = sum(1 for f in all_feedback if f.get('sentiment') == 'negative')

    # Collect tags
    tag_counts: dict = {}
    for f in all_feedback:
        for tag in f.get('tags', []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return {
        'total': len(all_feedback),
        'positive': positive,
        'negative': negative,
        'top_tags': dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)),
        'recent': all_feedback[:20],
    }



@api_router.get("/admin/referral-analytics")
async def admin_referral_analytics():
    """Referral funnel analytics — overview of the entire referral system."""
    # Total referral codes generated
    total_codes = await db.referral_codes.count_documents({})

    # Referral funnel counts by status
    all_links = await db.referral_links.find({}, {'_id': 0, 'referrer_id': 1, 'status': 1, 'fraud_flag': 1}).to_list(None)
    total_referrals = len(all_links)
    status_counts = {}
    for link in all_links:
        s = link.get('status', 'unknown')
        status_counts[s] = status_counts.get(s, 0) + 1

    account_created = status_counts.get('account_created', 0)
    verification_pending = status_counts.get('verification_pending', 0)
    verified = status_counts.get('verified', 0)
    rejected = status_counts.get('rejected', 0)
    fraud_flagged = sum(1 for l in all_links if l.get('fraud_flag'))

    # Conversion rates
    subscribed_total = verification_pending + verified + rejected  # all who subscribed at some point
    signup_to_sub_rate = round(subscribed_total / total_referrals * 100, 1) if total_referrals > 0 else 0
    sub_to_verified_rate = round(verified / subscribed_total * 100, 1) if subscribed_total > 0 else 0
    overall_rate = round(verified / total_referrals * 100, 1) if total_referrals > 0 else 0

    # Rewards issued
    rewards = await db.referral_rewards.find({}, {'_id': 0}).to_list(None)
    total_rewards_earned = sum(r.get('rewards_earned', 0) for r in rewards)
    total_free_months_available = sum(r.get('free_months_available', 0) for r in rewards)

    # Top referrers (by verified count)
    referrer_counts = {}
    for link in all_links:
        rid = link.get('referrer_id', '')
        if rid not in referrer_counts:
            referrer_counts[rid] = {'total': 0, 'verified': 0}
        referrer_counts[rid]['total'] += 1
        if link.get('status') == 'verified':
            referrer_counts[rid]['verified'] += 1

    top_referrers_raw = sorted(referrer_counts.items(), key=lambda x: x[1]['verified'], reverse=True)[:10]
    top_referrers = []
    for user_id, counts in top_referrers_raw:
        if counts['total'] == 0:
            continue
        user = await db.users.find_one({'user_id': user_id}, {'_id': 0, 'email': 1, 'name': 1})
        top_referrers.append({
            'user_id': user_id,
            'email': user.get('email', '') if user else '',
            'name': user.get('name', '') if user else '',
            'total_referrals': counts['total'],
            'verified_referrals': counts['verified'],
        })

    return {
        'funnel': {
            'referral_codes_generated': total_codes,
            'total_referrals_created': total_referrals,
            'account_created': account_created,
            'subscribed_and_pending': verification_pending,
            'verified': verified,
            'rejected': rejected,
            'fraud_flagged': fraud_flagged,
        },
        'conversion_rates': {
            'signup_to_subscription': f'{signup_to_sub_rate}%',
            'subscription_to_verified': f'{sub_to_verified_rate}%',
            'overall_referral_to_verified': f'{overall_rate}%',
        },
        'rewards': {
            'total_free_months_earned': total_rewards_earned,
            'free_months_currently_available': total_free_months_available,
        },
        'top_referrers': top_referrers,
    }


@api_router.post("/webhooks/revenuecat")
async def revenuecat_webhook(request: FastAPIRequest):
    """Handle RevenueCat subscription lifecycle events.
    app_user_id = our backend user_id (set via Purchases.logIn(userId) in the app).
    """
    # Auth check - flexible to handle RevenueCat header quirks
    # If no webhook auth is configured, allow all requests through
    auth = request.headers.get('authorization', '')
    auth_token = auth.replace('Bearer ', '').strip()
    expected_token = REVENUECAT_WEBHOOK_AUTH.replace('Bearer ', '').strip() if REVENUECAT_WEBHOOK_AUTH else ''
    if expected_token and auth_token and auth_token != expected_token:
        logger.warning(f'[RevenueCat] Webhook auth mismatch. Got: "{auth[:30]}..."')
        raise HTTPException(status_code=401, detail='Unauthorized')
    # If no auth sent at all, still allow (RevenueCat may not be sending the header)
    if not auth:
        logger.info('[RevenueCat] Webhook received without auth header - allowing through')
    body = await request.json()
    event = body.get('event', {})
    event_type = event.get('type', '')

    # ── Event-ID Deduplication ─────────────────────────────────────────
    # RevenueCat retries webhooks on transient failures, and APIs can fan
    # out duplicate POSTs in rare cases. Without dedup, a replayed
    # INITIAL_PURCHASE / RENEWAL event re-runs apply_paid_subscription_state,
    # which legitimately resets credits_consumed_this_cycle to 0 for the new
    # cycle — same class of accidental "credit refill" we just patched on
    # FRONTEND_SYNC. Track each unique event.id and skip on replay.
    event_id = event.get('id', '') or body.get('id', '')
    if event_id:
        try:
            await db.revenuecat_webhook_events.insert_one({
                '_id': event_id,
                'event_type': event_type,
                'created_at': datetime.now(timezone.utc),
            })
        except DuplicateKeyError:
            logger.info(
                f'[RevenueCat] Duplicate webhook IGNORED — event_id={event_id} '
                f'event_type={event_type}'
            )
            return {'status': 'ok', 'duplicate': True, 'event_id': event_id}
    else:
        logger.warning(f'[RevenueCat] Webhook arrived without event.id — cannot dedup. type={event_type}')

    # app_user_id might be a RevenueCat anonymous UUID instead of our backend user_id
    # Check aliases first for a backend user_id match (format: user_XXXXXXXXXXXX)
    raw_user_id = event.get('app_user_id', '')
    aliases = event.get('aliases', [])
    product_id = event.get('product_id', '')
    
    # Try to find the backend user_id from aliases or app_user_id
    user_id = ''
    all_ids = [raw_user_id] + aliases
    
    # First: check if any ID matches our backend format (starts with 'user_')
    for candidate in all_ids:
        if candidate and candidate.startswith('user_'):
            user_id = candidate
            break
    
    # Second: if no backend-format ID found, search the database for any matching ID
    if not user_id:
        for candidate in all_ids:
            if not candidate:
                continue
            # Check if this RevenueCat ID is stored as revenuecat_customer_id on any user
            existing = await db.subscriptions.find_one({'revenuecat_customer_id': candidate}, {'_id': 0, 'user_id': 1})
            if existing:
                user_id = existing['user_id']
                break
            # Also check users collection
            existing_user = await db.users.find_one(
                {'$or': [{'revenuecat_customer_id': candidate}, {'user_id': candidate}]},
                {'_id': 0, 'user_id': 1}
            )
            if existing_user:
                user_id = existing_user['user_id']
                break
    
    # Third: if still no match, use the raw app_user_id and store it for later reconciliation
    if not user_id:
        user_id = raw_user_id
        logger.warning(f'[RevenueCat] Could not match user. raw_id={raw_user_id}, aliases={aliases}')
        # Store the unmatched webhook for later reconciliation
        await db.unmatched_webhooks.insert_one({
            'raw_user_id': raw_user_id,
            'aliases': aliases,
            'event_type': event_type,
            'product_id': product_id,
            'event_data': event,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'reconciled': False
        })
    
    logger.info(f'[RevenueCat] {event_type} | user_id={user_id} | raw_id={raw_user_id} | product={product_id}')

    # -------------------------------------------------------------
    # TRANSFER — informational / reconciliation only.
    # Per product spec: TRANSFER MUST NOT overwrite tier/credits/is_trial.
    # We ONLY update the revenuecat_customer_id mapping so subsequent
    # INITIAL_PURCHASE / RENEWAL webhooks can match the right backend user.
    # Paid state already applied by a frontend /api/subscription/sync or a
    # prior INITIAL_PURCHASE webhook MUST survive a TRANSFER event.
    # -------------------------------------------------------------
    if event_type == 'TRANSFER':
        transferred_to = event.get('transferred_to', [])
        transferred_from = event.get('transferred_from', [])
        logger.info(
            f'[RevenueCat:TRANSFER] IGNORED for state writes. '
            f'from={transferred_from} to={transferred_to} product={product_id}'
        )

        # Find the target user (our backend user_id) and, if present, store
        # the new RC customer id on their subscription doc so future webhooks
        # reconcile correctly. No tier/credits/trial mutations.
        # Resolution order for each candidate in transferred_to:
        #   1. it literally starts with 'user_' (standard backend id format)
        #   2. it matches a user_id in db.subscriptions (covers legacy ids
        #      like the demo_reviewer_account fixture)
        #   3. it matches a revenuecat_customer_id in db.subscriptions
        #      (covers RC anonymous ids we've already linked)
        target_user_id = ''
        for candidate in transferred_to:
            if not candidate:
                continue
            if candidate.startswith('user_'):
                target_user_id = candidate
                break
            sub_match = await db.subscriptions.find_one(
                {'$or': [{'user_id': candidate}, {'revenuecat_customer_id': candidate}]},
                {'_id': 0, 'user_id': 1},
            )
            if sub_match and sub_match.get('user_id'):
                target_user_id = sub_match['user_id']
                break
        if target_user_id:
            reconcile_set = {'last_transfer_at': datetime.now(timezone.utc).isoformat()}
            if raw_user_id:
                reconcile_set['revenuecat_customer_id'] = raw_user_id
            if transferred_from:
                reconcile_set['last_transfer_from'] = transferred_from[0]
            await db.subscriptions.update_one(
                {'user_id': target_user_id},
                {'$set': reconcile_set},
                upsert=False,  # never create a new doc from a TRANSFER
            )
        # Audit log so ops can inspect TRANSFERs without them mutating state
        await db.rc_transfer_log.insert_one({
            'target_user_id': target_user_id,
            'transferred_from': transferred_from,
            'transferred_to': transferred_to,
            'product_id': product_id,
            'raw_event': event,
            'received_at': datetime.now(timezone.utc).isoformat(),
        })
        return {'status': 'ok', 'handled_as': 'informational'}

    # -------------------------------------------------------------
    # Authoritative paid events — INITIAL_PURCHASE / RENEWAL.
    # Route through apply_paid_subscription_state so behavior is identical
    # to the frontend /api/subscription/sync path.
    # -------------------------------------------------------------
    if event_type in ('INITIAL_PURCHASE', 'RENEWAL') and user_id:
        if not product_id or product_id not in PRODUCT_CREDIT_MAP:
            logger.error(
                f'[RevenueCat:{event_type}] REFUSED: unknown product_id={product_id!r} '
                f'for user={user_id}. State preserved.'
            )
            return {'status': 'error', 'reason': 'unknown_product'}
        period_type = event.get('period_type', 'NORMAL')
        is_apple_trial = period_type == 'TRIAL'
        try:
            await apply_paid_subscription_state(
                user_id=user_id,
                product_id=product_id,
                source=event_type,
                rc_customer_id=raw_user_id or None,
                is_apple_trial=is_apple_trial,
            )
        except ValueError as e:
            return {'status': 'error', 'reason': str(e)}
        # Update referral ledger (paid only — not during Apple trial)
        if not is_apple_trial:
            await update_referral_on_subscription(user_id, event_type)
        return {'status': 'ok'}

    elif event_type in ('CANCELLATION', 'EXPIRATION') and user_id:
        # Keep remaining credits but mark tier as expired
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {'tier': 'expired', 'last_event': event_type}}
        )
        await update_referral_on_subscription(user_id, event_type)
    return {'status': 'ok'}


@api_router.post("/subscription/link-rc")
async def link_revenuecat_id(request: FastAPIRequest):
    """Store the RevenueCat originalAppUserId on the user's subscription record.
    This enables webhook matching when RC sends anonymous IDs."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    
    body = await request.json()
    rc_id = body.get('revenuecat_customer_id', '')
    if not rc_id:
        raise HTTPException(status_code=400, detail='Missing revenuecat_customer_id')
    
    await db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': {'revenuecat_customer_id': rc_id}},
        upsert=True
    )
    logger.info(f'[RC:Link] Stored RC ID {rc_id} for user {user_id}')
    return {'status': 'linked', 'revenuecat_customer_id': rc_id}

@api_router.post("/subscription/sync")
async def sync_subscription(request: FastAPIRequest):
    """Frontend-authoritative paid subscription application.

    Called by PaywallScreen's handlePurchase/handleRestore right after
    `Purchases.purchasePackage` / `Purchases.restorePurchases` confirms an
    active entitlement. This is the MAIN paid-state writer — it runs before
    the RC webhook arrives and is robust against webhook misclassification
    (TRANSFER vs INITIAL_PURCHASE).

    Rules (mirrors apply_paid_subscription_state):
    - product_id MUST be in PRODUCT_CREDIT_MAP — no fallbacks.
    - No default tier / default credits / silent trial.
    - is_trial is applied only when the frontend explicitly passes it from
      the active RC entitlement's periodType === 'TRIAL'.
    """
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    body = await request.json()
    product_id = body.get('product_id')
    is_trial = bool(body.get('is_trial', False))
    rc_customer_id = body.get('revenuecat_customer_id', '') or None
    # Manual restore (user tapped "Restore Purchases") is allowed to override
    # the admin-reset block. Passive auto-sync on app launch is not.
    manual_restore = bool(body.get('manual_restore', False))

    if not product_id:
        raise HTTPException(status_code=400, detail='Missing product_id')
    if product_id not in PRODUCT_CREDIT_MAP:
        logger.warning(f'[Sync] Unknown product_id: {product_id} for user {user_id}')
        raise HTTPException(
            status_code=400,
            detail=f'Unknown product_id: {product_id}. Valid: {list(PRODUCT_CREDIT_MAP.keys())}',
        )

    # Admin-reset guard: if this user was admin-reset and has not yet manually
    # opted back in, reject passive auto-sync. Otherwise every app launch would
    # silently re-apply the cached App Store entitlement and defeat the reset.
    existing_sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0, 'last_event': 1}) or {}
    if existing_sub.get('last_event') == 'ADMIN_RESET' and not manual_restore:
        logger.info(f'[Sync] BLOCKED — user {user_id} is admin-reset; passive auto-sync rejected')
        raise HTTPException(
            status_code=403,
            detail='Account was reset. Tap Restore Purchases on the paywall to restore your subscription.',
        )

    try:
        await apply_paid_subscription_state(
            user_id=user_id,
            product_id=product_id,
            source='FRONTEND_SYNC',
            rc_customer_id=rc_customer_id,
            is_apple_trial=is_trial,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    credits = await get_user_credits(user_id)
    logger.info(
        f'[Sync] Applied for user {user_id}: product={product_id} → '
        f'tier={credits.get("tier")} credits={credits.get("available_credits")} trial={is_trial}'
    )
    return credits
    logger.info(f'[Sync] User {user_id} synced to tier {tier_info["tier"]} with {credits_to_grant} credits ({"trial" if is_trial else "paid"}, product: {product_id})')
    
    # Update referral status if this user was referred and it's a paid subscription
    if not is_trial:
        await update_referral_on_subscription(user_id, 'INITIAL_PURCHASE')
    
    credits = await get_user_credits(user_id)
    return credits


# ---- Referral System v2 ----

REFERRAL_ACTIVE_TIERS = ['walk-in', 'booked-out', 'the-shop', 'the-shop-member']

# Referral premium override: "simple credit-based" Phase 2 redemption
# Each earned free month grants 30 days of premium entitlement + walk-in tier's
# credit refill, but only when the user's paid RC subscription is NOT active.
REFERRAL_PREMIUM_TIER = 'referral_premium'
REFERRAL_PREMIUM_CREDITS = 125  # Same as walk-in tier
REFERRAL_MONTH_DAYS = 30
# Tiers that indicate the user is NOT on an active paid subscription — referral
# months are safe to auto-activate for these states.
INACTIVE_TIERS = {None, '', 'expired', 'trial_expired', 'paywall_bypass', REFERRAL_PREMIUM_TIER}

# Tier -> monthly credit allowance. Balance caps at 2× the allowance.
MONTHLY_ALLOWANCE_MAP = {
    'walk-in': 125,
    'booked-out': 500,
    'the-shop': 1500,
    'the-shop-member': 1500,
    REFERRAL_PREMIUM_TIER: 125,
}

BALANCE_CAP_MULTIPLIER = 2  # max_balance = monthly_allowance × this


async def apply_monthly_refill(
    user_id: str,
    monthly_allowance: int,
    cycle_key: str,
    tier: Optional[str] = None,
    extra_set: Optional[dict] = None,
) -> dict:
    """Atomic rollover-aware monthly credit refill.

    Behavior:
    - Balance rolls over between cycles; refill ADDS monthly_allowance to
      whatever the user has left.
    - Balance is capped at `monthly_allowance × BALANCE_CAP_MULTIPLIER` (2× by
      default). If a refill would overshoot the cap, balance is truncated.
    - Refill is idempotent per (user_id, cycle_key) via `last_refill_at`:
      a second call with the same cycle_key is a no-op.
    - Safe against concurrent callers — uses a conditional atomic update.

    Returns: {
        'applied': bool — whether this call performed a refill,
        'previous_balance': int,
        'new_balance': int,
        'monthly_allowance': int,
        'max_balance_cap': int,
        'cycle_key': str,
    }
    """
    cap = monthly_allowance * BALANCE_CAP_MULTIPLIER

    # Step 1: Ensure subscription doc exists (idempotent). We use $setOnInsert so
    # repeated callers don't clobber existing state.
    await db.subscriptions.update_one(
        {'user_id': user_id},
        {
            '$setOnInsert': {
                'user_id': user_id,
                'available_credits': 0,
                'is_trial': False,
                'tier': tier,
            },
        },
        upsert=True,
    )

    # Step 2: Atomic claim. Only the FIRST concurrent caller gets past this
    # filter; everyone else sees last_refill_at == cycle_key and fails the $ne
    # check, returning None (no double-refill possible).
    claim_filter = {
        'user_id': user_id,
        '$or': [
            {'last_refill_at': {'$ne': cycle_key}},
            {'last_refill_at': {'$exists': False}},
        ],
    }
    set_doc = {
        'last_refill_at': cycle_key,
        'monthly_allowance': monthly_allowance,
        'max_balance_cap': cap,
        # New cycle → reset the usage counter and any per-cycle upsell state.
        'credits_consumed_this_cycle': 0,
        'upsell_shown_for_cycle': None,
        'upsell_dismissed_for_cycle': None,
    }
    if tier is not None:
        set_doc['tier'] = tier
    if extra_set:
        set_doc.update(extra_set)

    claimed_before = await db.subscriptions.find_one_and_update(
        claim_filter,
        {'$set': set_doc},
        return_document=False,  # return the doc as it was BEFORE the update
    )

    if claimed_before is None:
        # Either already refilled for this cycle OR lost the race to another caller
        existing = await db.subscriptions.find_one({'user_id': user_id}) or {}
        return {
            'applied': False,
            'previous_balance': existing.get('available_credits', 0),
            'new_balance': existing.get('available_credits', 0),
            'monthly_allowance': monthly_allowance,
            'max_balance_cap': cap,
            'cycle_key': cycle_key,
            'reason': 'already_refilled_for_cycle',
        }

    # We won the claim. Apply rollover + cap.
    previous_balance = int(claimed_before.get('available_credits', 0) or 0)
    new_balance = min(previous_balance + monthly_allowance, cap)

    if new_balance != previous_balance:
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {'available_credits': new_balance}},
        )

    return {
        'applied': True,
        'previous_balance': previous_balance,
        'new_balance': new_balance,
        'monthly_allowance': monthly_allowance,
        'max_balance_cap': cap,
        'cycle_key': cycle_key,
    }


async def maybe_redeem_referral_month(user_id: str) -> Optional[dict]:
    """Idempotent referral-month redemption.

    Called on every /auth/me hit, every cron pass, and every subscription event.
    Safe to call repeatedly AND concurrently; will NEVER double-grant credits.

    Behavior:
    1. If user has an active referral_premium_until in the future → no-op.
    2. Else if free_months_available > 0 AND user's paid sub is NOT active:
       atomically start a new 30-day period, decrement free_months_available,
       grant walk-in-equivalent credits (once), flip subscription tier to
       'referral_premium'.
    3. Else if referral_premium_until has expired and no more months queued:
       restore subscription tier to 'expired' (only if it was referral_premium).

    Concurrency is handled via an atomic find_one_and_update. Only the first
    concurrent caller passes the filter; the others see the updated doc and no-op.

    Returns the current reward doc (or None if no ledger exists).
    """
    rewards = await db.referral_rewards.find_one({'user_id': user_id})
    if not rewards:
        return None

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    until_str = rewards.get('referral_premium_until')
    is_active = False
    if until_str:
        try:
            until_dt = datetime.fromisoformat(until_str.replace('Z', '+00:00'))
            is_active = until_dt > now
        except Exception:
            is_active = False

    sub = await db.subscriptions.find_one({'user_id': user_id}) or {}
    sub_tier = sub.get('tier')
    sub_is_trial = sub.get('is_trial', False)
    paid_active = (sub_tier in REFERRAL_ACTIVE_TIERS) and not sub_is_trial

    # CASE 1: Already active → nothing to do
    if is_active:
        return rewards

    # CASE 2: Period expired and we were holding tier=referral_premium, reset it
    if until_str and not is_active and sub_tier == REFERRAL_PREMIUM_TIER:
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {'tier': 'expired', 'last_event': 'REFERRAL_MONTH_EXPIRED'}}
        )
        logger.info(f'[Referral Redeem] User {user_id} referral month expired, tier reset to expired')
        sub = await db.subscriptions.find_one({'user_id': user_id}) or {}
        sub_tier = sub.get('tier')
        paid_active = False

    # CASE 3: Try to atomically claim the next queued month
    available = rewards.get('free_months_available', 0) or 0
    if available <= 0:
        return rewards

    # Paid users bank their months — skip activation
    if paid_active:
        return rewards

    new_until = (now + timedelta(days=REFERRAL_MONTH_DAYS)).isoformat()
    redeemed_at = now_iso

    # Atomic claim: requires free_months_available > 0 AND
    # (referral_premium_until is null OR referral_premium_until < now_iso).
    # ISO8601 UTC strings sort lexicographically, so $lt on them is valid.
    claim_filter = {
        'user_id': user_id,
        'free_months_available': {'$gt': 0},
        '$or': [
            {'referral_premium_until': {'$in': [None, '']}},
            {'referral_premium_until': {'$exists': False}},
            {'referral_premium_until': {'$lt': now_iso}},
        ],
    }
    claim_update = {
        '$set': {
            'referral_premium_until': new_until,
            'last_referral_month_redeemed_at': redeemed_at,
            'referral_credits_granted_for': redeemed_at,
        },
        '$inc': {'free_months_available': -1},
    }

    # find_one_and_update is atomic — only ONE concurrent caller wins.
    claimed = await db.referral_rewards.find_one_and_update(
        claim_filter, claim_update, return_document=True
    )

    if not claimed:
        # Someone else claimed it first (or no months left) — nothing to do.
        return await db.referral_rewards.find_one({'user_id': user_id})

    # We won the race — apply rollover-aware refill (once).
    # cycle_key = redeemed_at so repeated calls with same activation don't re-refill.
    refill = await apply_monthly_refill(
        user_id=user_id,
        monthly_allowance=REFERRAL_PREMIUM_CREDITS,
        cycle_key=f'referral:{redeemed_at}',
        tier=REFERRAL_PREMIUM_TIER,
        extra_set={
            'is_trial': False,
            'referral_premium_until': new_until,
            'last_event': 'REFERRAL_MONTH_ACTIVATED',
            'updated_at': redeemed_at,
        },
    )
    logger.info(
        f'[Referral Redeem] Activated referral month for {user_id}: '
        f'balance {refill["previous_balance"]} → {refill["new_balance"]} '
        f'(cap {refill["max_balance_cap"]}), until {new_until}, '
        f'remaining queued={claimed.get("free_months_available", 0)}'
    )

    return claimed


async def attribute_referral(new_user_id: str, email: Optional[str], device_id: Optional[str], referral_code: Optional[str]):
    """Called during signup to attribute a new user to a referrer. First-touch only."""
    if not referral_code:
        return
    referral_code = referral_code.strip().upper()

    # Find the referral code owner
    code_doc = await db.referral_codes.find_one({'code': referral_code})
    if not code_doc:
        logger.warning(f'[Referral] Invalid code {referral_code} during signup for {new_user_id}')
        return

    referrer_id = code_doc['user_id']

    # Anti-abuse: self-referral
    if referrer_id == new_user_id:
        logger.warning(f'[Referral] Self-referral blocked: {new_user_id}')
        return

    # Anti-abuse: same email as referrer
    if email:
        referrer = await db.users.find_one({'user_id': referrer_id}, {'_id': 0, 'email': 1})
        if referrer and referrer.get('email') and referrer['email'].lower() == email.lower():
            logger.warning(f'[Referral] Same email as referrer blocked: {email}')
            return

    # Anti-abuse: same device as referrer
    if device_id:
        referrer = await db.users.find_one({'user_id': referrer_id}, {'_id': 0, 'device_id': 1})
        if referrer and referrer.get('device_id') and referrer['device_id'] == device_id:
            logger.warning(f'[Referral] Same device as referrer blocked: {device_id[:8]}...')
            return

    # Anti-abuse: user already attributed (first-touch lock)
    existing = await db.referral_links.find_one({'referred_user_id': new_user_id})
    if existing:
        logger.warning(f'[Referral] User {new_user_id} already attributed — first-touch lock')
        return

    # Anti-abuse: rapid referral detection (flag if referrer has >5 referrals in last hour)
    one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    recent_count = await db.referral_links.count_documents({
        'referrer_id': referrer_id,
        'created_at': {'$gte': one_hour_ago}
    })
    fraud_flag = recent_count >= 5

    now = datetime.now(timezone.utc).isoformat()
    await db.referral_links.insert_one({
        'referrer_id': referrer_id,
        'referred_user_id': new_user_id,
        'referral_code': referral_code,
        'status': 'account_created',
        'created_at': now,
        'account_created_at': now,
        'subscribed_at': None,
        'verification_due_at': None,
        'verified_at': None,
        'rejected_at': None,
        'rejection_reason': None,
        'referred_email': email,
        'referred_device_id': device_id,
        'reward_consumed': False,
        'fraud_flag': fraud_flag,
    })

    # Mark the new user as referred
    await db.users.update_one(
        {'user_id': new_user_id},
        {'$set': {'referred_by': referrer_id, 'referral_code_used': referral_code}}
    )

    if fraud_flag:
        logger.warning(f'[Referral] FRAUD FLAG: Referrer {referrer_id} has {recent_count} referrals in last hour')
    logger.info(f'[Referral] Attributed {new_user_id} to referrer {referrer_id} via code {referral_code}')


async def update_referral_on_subscription(user_id: str, event_type: str):
    """Called from webhook/sync when a referred user's subscription changes."""
    referral = await db.referral_links.find_one(
        {'referred_user_id': user_id, 'status': {'$in': ['account_created', 'subscribed', 'verification_pending']}}
    )
    if not referral:
        return

    now = datetime.now(timezone.utc)

    if event_type in ('INITIAL_PURCHASE', 'RENEWAL', 'FRONTEND_SYNC'):
        if referral['status'] == 'account_created':
            # Referred user just subscribed — start 14-day verification
            verification_due = (now + timedelta(days=VERIFICATION_DAYS)).isoformat()
            await db.referral_links.update_one(
                {'referred_user_id': user_id, 'status': 'account_created'},
                {'$set': {
                    'status': 'verification_pending',
                    'subscribed_at': now.isoformat(),
                    'verification_due_at': verification_due,
                }}
            )
            logger.info(f'[Referral] User {user_id} subscribed — verification pending until {verification_due}')

    elif event_type in ('CANCELLATION', 'EXPIRATION'):
        if referral['status'] in ('subscribed', 'verification_pending'):
            # Cancelled during verification period — reject
            await db.referral_links.update_one(
                {'referred_user_id': user_id, 'status': {'$in': ['subscribed', 'verification_pending']}},
                {'$set': {
                    'status': 'rejected',
                    'rejected_at': now.isoformat(),
                    'rejection_reason': f'{event_type.lower()}_during_verification',
                }}
            )
            logger.info(f'[Referral] Referral for {user_id} rejected — {event_type} during verification')


async def process_referral_verifications():
    """Check verification_pending referrals where 14 days have passed."""
    now = datetime.now(timezone.utc)
    pending = await db.referral_links.find({'status': 'verification_pending'}).to_list(None)

    verified_count = 0
    rejected_count = 0

    for ref in pending:
        # Check if 14 days have passed since subscription
        subscribed_at_str = ref.get('subscribed_at')
        if not subscribed_at_str:
            continue
        try:
            subscribed_at = datetime.fromisoformat(subscribed_at_str.replace('Z', '+00:00'))
        except Exception:
            continue

        if (now - subscribed_at).days < VERIFICATION_DAYS:
            continue  # Not yet due

        referred_user_id = ref['referred_user_id']
        sub = await db.subscriptions.find_one({'user_id': referred_user_id}, {'_id': 0})

        if sub and sub.get('tier') in REFERRAL_ACTIVE_TIERS and not sub.get('is_trial', False):
            # Still active and paid — verify
            await db.referral_links.update_one(
                {'referred_user_id': referred_user_id, 'status': 'verification_pending'},
                {'$set': {'status': 'verified', 'verified_at': now.isoformat()}}
            )
            verified_count += 1
            logger.info(f'[Referral] Verified referral for user {referred_user_id}')
            await check_and_issue_rewards(ref['referrer_id'])
        else:
            await db.referral_links.update_one(
                {'referred_user_id': referred_user_id, 'status': 'verification_pending'},
                {'$set': {
                    'status': 'rejected',
                    'rejected_at': now.isoformat(),
                    'rejection_reason': 'not_active_at_verification',
                }}
            )
            rejected_count += 1
            logger.info(f'[Referral] Rejected referral for user {referred_user_id} — not active')

    return {'verified': verified_count, 'rejected': rejected_count, 'checked': len(pending)}


async def check_and_issue_rewards(referrer_id: str):
    """Check if referrer has enough unconsumed verified referrals for a new reward."""
    unconsumed = await db.referral_links.find({
        'referrer_id': referrer_id,
        'status': 'verified',
        'reward_consumed': False,
    }).to_list(None)

    if len(unconsumed) < REFERRALS_NEEDED_FOR_REWARD:
        return

    rewards_to_issue = len(unconsumed) // REFERRALS_NEEDED_FOR_REWARD
    # Consume referrals in pairs
    consume_count = rewards_to_issue * REFERRALS_NEEDED_FOR_REWARD
    consumed_user_ids = [r['referred_user_id'] for r in unconsumed[:consume_count]]

    await db.referral_links.update_many(
        {'referrer_id': referrer_id, 'referred_user_id': {'$in': consumed_user_ids}, 'status': 'verified'},
        {'$set': {'reward_consumed': True}}
    )

    now = datetime.now(timezone.utc).isoformat()
    existing = await db.referral_rewards.find_one({'user_id': referrer_id})

    if existing:
        await db.referral_rewards.update_one(
            {'user_id': referrer_id},
            {'$inc': {
                'rewards_earned': rewards_to_issue,
                'free_months_available': rewards_to_issue,
            },
            '$set': {'last_reward_at': now}}
        )
    else:
        await db.referral_rewards.insert_one({
            'user_id': referrer_id,
            'rewards_earned': rewards_to_issue,
            'free_months_available': rewards_to_issue,
            'last_reward_at': now,
        })

    logger.info(f'[Referral] Issued {rewards_to_issue} free month(s) reward to referrer {referrer_id}')

    # Phase 2: try to auto-activate the first queued month immediately
    try:
        await maybe_redeem_referral_month(referrer_id)
    except Exception as e:
        logger.error(f'[Referral Redeem] Post-issue redemption failed for {referrer_id}: {e}')


@api_router.get("/referral/code")
async def get_referral_code(request: FastAPIRequest):
    """Get or generate the user's unique referral code and shareable link."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    existing = await db.referral_codes.find_one({'user_id': user_id}, {'_id': 0})
    if existing:
        code = existing['code']
    else:
        code = f'BB-{uuid.uuid4().hex[:6].upper()}'
        await db.referral_codes.insert_one({
            'user_id': user_id,
            'code': code,
            'created_at': datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f'[Referral] Generated code {code} for user {user_id}')

    # Build referral link using production URL
    base_url = os.environ.get('REFERRAL_BASE_URL', 'https://bodybound-subs.emergent.host')
    referral_link = f'{base_url}/api/ref/{code}'

    return {
        'referral_code': code,
        'referral_link': referral_link,
    }


@api_router.get("/referral/dashboard")
async def get_referral_dashboard(request: FastAPIRequest):
    """Full referral dashboard data for the logged-in user."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    # Get or create referral code
    code_doc = await db.referral_codes.find_one({'user_id': user_id}, {'_id': 0})
    if not code_doc:
        code = f'BB-{uuid.uuid4().hex[:6].upper()}'
        await db.referral_codes.insert_one({
            'user_id': user_id,
            'code': code,
            'created_at': datetime.now(timezone.utc).isoformat(),
        })
    else:
        code = code_doc['code']

    base_url = os.environ.get('REFERRAL_BASE_URL', 'https://bodybound-subs.emergent.host')
    referral_link = f'{base_url}/api/ref/{code}'

    # Get all referral links where this user is the referrer
    all_referrals = await db.referral_links.find(
        {'referrer_id': user_id}, {'_id': 0}
    ).sort('created_at', -1).to_list(None)

    verified = sum(1 for r in all_referrals if r['status'] == 'verified')
    pending = sum(1 for r in all_referrals if r['status'] in ('account_created', 'subscribed', 'verification_pending'))
    rejected = sum(1 for r in all_referrals if r['status'] == 'rejected')

    # Get reward ledger (and auto-redeem queued months if applicable)
    await maybe_redeem_referral_month(user_id)
    rewards = await db.referral_rewards.find_one({'user_id': user_id}, {'_id': 0})
    free_months_earned = rewards['rewards_earned'] if rewards else 0
    free_months_available = rewards['free_months_available'] if rewards else 0

    # Phase 2 redemption state
    referral_premium_until = rewards.get('referral_premium_until') if rewards else None
    is_referral_premium_active = False
    if referral_premium_until:
        try:
            until_dt = datetime.fromisoformat(referral_premium_until.replace('Z', '+00:00'))
            is_referral_premium_active = until_dt > datetime.now(timezone.utc)
        except Exception:
            is_referral_premium_active = False
    if not is_referral_premium_active:
        referral_premium_until = None

    # Does the user have a paid sub currently blocking auto-activation?
    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0}) or {}
    paid_active = (sub.get('tier') in REFERRAL_ACTIVE_TIERS) and not sub.get('is_trial', False)

    # Progress toward next reward: count unconsumed verified referrals
    unconsumed_verified = sum(1 for r in all_referrals if r['status'] == 'verified' and not r.get('reward_consumed', False))
    progress = unconsumed_verified % REFERRALS_NEEDED_FOR_REWARD

    # Referral activity list (simplified for frontend)
    referral_list = [
        {'status': r['status'], 'created_at': r['created_at']}
        for r in all_referrals
    ]

    return {
        'referral_code': code,
        'referral_link': referral_link,
        'verified_referrals': verified,
        'pending_referrals': pending,
        'rejected_referrals': rejected,
        'progress_toward_reward': progress,
        'referrals_needed': REFERRALS_NEEDED_FOR_REWARD,
        'free_months_earned': free_months_earned,
        'free_months_available': free_months_available,
        'earned_free_months': free_months_available,
        'is_referral_premium_active': is_referral_premium_active,
        'referral_premium_until': referral_premium_until,
        'blocked_by_paid_sub': paid_active and free_months_available > 0,
        'referrals': referral_list,
    }


@api_router.post("/referral/check-verifications")
async def check_verifications_endpoint(request: FastAPIRequest):
    """Cron endpoint: process pending referral verifications (14-day rule).
    Secured via X-Cron-Secret header."""
    if not CRON_SECRET:
        raise HTTPException(status_code=503, detail='Cron not configured')
    secret_header = request.headers.get('x-cron-secret', '')
    if secret_header != CRON_SECRET:
        raise HTTPException(status_code=401, detail='Unauthorized')

    result = await process_referral_verifications()
    logger.info(f'[Referral Cron] Verification check: {result}')
    return result


@api_router.get("/referral/popup-eligible")
async def referral_popup_eligible(request: FastAPIRequest):
    """Check if the user should see the referral popup.
    Rules: active paid subscriber, max once per 7 days if dismissed."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    # Must be an active paid subscriber
    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    if not sub or sub.get('tier') not in REFERRAL_ACTIVE_TIERS or sub.get('is_trial', False):
        return {'eligible': False, 'reason': 'not_paid_subscriber'}

    # Check last dismissal — cooldown varies by action
    dismissal = await db.referral_popup_dismissals.find_one(
        {'user_id': user_id}, {'_id': 0}
    )
    if dismissal:
        last_dismissed = dismissal.get('dismissed_at', '')
        last_action = dismissal.get('action', 'dismiss')
        # Cooldown: dismiss=7d, shared/invite/copy=30d
        cooldown_days = 30 if last_action in ('shared', 'invite', 'copy') else 7
        try:
            dismissed_dt = datetime.fromisoformat(last_dismissed.replace('Z', '+00:00'))
            if (datetime.now(timezone.utc) - dismissed_dt).days < cooldown_days:
                return {'eligible': False, 'reason': 'recently_dismissed'}
        except Exception:
            pass

    # If user already has verified referrals, suppress longer (60 days from last dismissal)
    has_verified = await db.referral_links.find_one(
        {'referrer_id': user_id, 'status': 'verified'}
    )
    if has_verified and dismissal:
        try:
            dismissed_dt = datetime.fromisoformat(dismissal.get('dismissed_at', '').replace('Z', '+00:00'))
            if (datetime.now(timezone.utc) - dismissed_dt).days < 60:
                return {'eligible': False, 'reason': 'active_referrer'}
        except Exception:
            pass

    return {'eligible': True}


@api_router.post("/referral/dismiss-popup")
async def dismiss_referral_popup(request: FastAPIRequest):
    """Record that the user dismissed or engaged with the referral popup.
    Actions: 'dismiss' (7-day cooldown), 'shared' (30-day cooldown)."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    action = body.get('action', 'dismiss')

    now = datetime.now(timezone.utc).isoformat()
    await db.referral_popup_dismissals.update_one(
        {'user_id': user_id},
        {'$set': {'dismissed_at': now, 'action': action}},
        upsert=True
    )
    return {'status': 'ok'}


@api_router.get("/ref/{code}")
async def referral_landing(code: str):
    """Landing page when someone clicks a referral link.
    Displays the app info and directs to App Store."""
    code = code.strip().upper()
    code_doc = await db.referral_codes.find_one({'code': code})
    valid = code_doc is not None
    app_store_url = "https://apps.apple.com/app/body-bound-stencil-generator/id6741930631"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BODY BOUND - Referral</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #0a0a0f; color: #fff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
        .card {{ max-width: 420px; text-align: center; }}
        .logo {{ font-size: 28px; font-weight: 800; color: #C9A227; letter-spacing: 3px; margin-bottom: 8px; }}
        .sub {{ color: #666; font-size: 13px; letter-spacing: 2px; margin-bottom: 32px; }}
        h1 {{ font-size: 22px; margin-bottom: 12px; line-height: 1.3; }}
        p {{ color: #999; font-size: 15px; line-height: 1.6; margin-bottom: 24px; }}
        .code-box {{ background: #12121f; border: 1px solid #C9A227; border-radius: 12px; padding: 16px; margin-bottom: 24px; }}
        .code-label {{ color: #666; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }}
        .code-value {{ color: #C9A227; font-size: 20px; font-weight: 700; letter-spacing: 2px; }}
        .dl-btn {{ display: inline-block; background: #C9A227; color: #000; padding: 16px 40px; border-radius: 12px; text-decoration: none; font-weight: 700; font-size: 16px; }}
        .dl-btn:hover {{ background: #d4b042; }}
        .note {{ color: #555; font-size: 12px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="logo">BODY BOUND</div>
        <div class="sub">STENCIL GENERATOR</div>
        {"<h1>You've been invited to try BODY BOUND</h1><p>A fellow tattoo artist thinks you'd love this AI-powered stencil generator. Download the app and enter the referral code when you sign up.</p>" if valid else "<h1>Invalid Referral Link</h1><p>This referral link is not valid. You can still download BODY BOUND below.</p>"}
        {"<div class='code-box'><div class='code-label'>Your Referral Code</div><div class='code-value'>" + code + "</div></div>" if valid else ""}
        <a href="{app_store_url}" class="dl-btn">Download on App Store</a>
        <p class="note">Enter the code above when you create your account.</p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@api_router.post("/tasks/refresh-credits")
async def tasks_refresh_credits(request: FastAPIRequest):
    """Monthly credit refresh endpoint.
    Triggered by an external scheduler (e.g. GitHub Actions).
    Secured via X-Cron-Secret header matching CRON_SECRET env var.
    """
    if not CRON_SECRET:
        raise HTTPException(status_code=503, detail='Cron not configured')
    secret_header = request.headers.get('x-cron-secret', '')
    if secret_header != CRON_SECRET:
        raise HTTPException(status_code=401, detail='Unauthorized')

    return await _do_credit_refresh()


async def _do_credit_refresh():
    """Shared credit refresh logic used by both cron endpoints.

    Applies rollover-aware monthly refill: adds tier allowance to existing
    balance, capped at 2× allowance. Idempotent via cycle_key = renewal_date.
    """
    now = datetime.now(timezone.utc)
    active_tiers = ['walk-in', 'booked-out', 'the-shop']

    subs = await db.subscriptions.find(
        {'tier': {'$in': active_tiers}, 'is_trial': False}
    ).to_list(None)

    refreshed = 0
    for sub in subs:
        renewal_str = sub.get('renewal_date')
        if not renewal_str:
            continue
        try:
            renewal_date = datetime.fromisoformat(renewal_str.replace('Z', '+00:00'))
        except Exception:
            continue
        if renewal_date <= now:
            tier = sub.get('tier', '')
            allowance = MONTHLY_ALLOWANCE_MAP.get(tier, 0)
            if not allowance:
                continue
            next_renewal = (renewal_date + timedelta(days=30)).isoformat()
            # cycle_key tied to this billing period — prevents duplicate refills
            cycle_key = f'sub:{renewal_str}'
            result = await apply_monthly_refill(
                user_id=sub['user_id'],
                monthly_allowance=allowance,
                cycle_key=cycle_key,
                tier=tier,
                extra_set={'renewal_date': next_renewal},
            )
            if result['applied']:
                refreshed += 1
                logger.info(
                    f'[Cron] Refreshed credits for user {sub["user_id"]}: '
                    f'{result["previous_balance"]} → {result["new_balance"]} '
                    f'(cap {result["max_balance_cap"]})'
                )

    logger.info(f'[Cron] Credit refresh complete: {refreshed}/{len(subs)} subscriptions refreshed')
    return {'refreshed': refreshed, 'checked': len(subs), 'timestamp': now.isoformat()}

# Reviewer demo account endpoint
@api_router.post("/auth/demo-login")
async def demo_login():
    """Create/get reviewer demo account with 100 credits"""
    demo_id = 'demo_reviewer_account'
    user = await db.users.find_one({'user_id': demo_id}, {'_id': 0})
    if not user:
        user = {
            'user_id': demo_id, 'email': 'reviewer@bodybound.app',
            'name': 'App Store Reviewer', 'apple_user_id': None,
            'google_user_id': None, 'picture': None,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'last_login': datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one({**user})
        await db.subscriptions.insert_one({
            'user_id': demo_id, 'tier': 'booked-out', 'available_credits': 100,
            'is_trial': False, 'renewal_date': None, 'revenuecat_customer_id': None,
            'anti_abuse_key': 'demo',
            'created_at': datetime.now(timezone.utc).isoformat(),
        })
    else:
        await db.users.update_one({'user_id': demo_id}, {'$set': {'last_login': datetime.now(timezone.utc).isoformat()}})
    return {'user': user, 'session_token': create_session_token(demo_id)}

# ============================================
# END AUTH & USER MANAGEMENT
# ============================================



@api_router.get("/preview-image/{method}")
async def get_preview_image(method: str):
    """Serve preview stencil images"""
    file_map = {
        "original": "/tmp/sample_portrait.jpg",
        "canny": "/tmp/stencil_method1_canny.png",
        "adaptive": "/tmp/stencil_method2_adaptive.png",
        "sketch": "/tmp/stencil_method3_sketch.png",
        "clean": "/tmp/stencil_method4_clean.png",
    }
    file_path = file_map.get(method)
    if file_path and os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Image not found")

@api_router.get("/stencil-preview")
async def stencil_preview_page():
    """Serve the preview HTML page"""
    html_path = "/app/backend/static/preview.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


@api_router.get("/prompt-preview")
async def prompt_preview_page():
    """Serve the new-prompt side-by-side preview HTML (temporary QA tool)."""
    html_path = "/app/backend/static/prompt_preview.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


@api_router.get("/prompt-preview-alt")
async def prompt_preview_alt_page():
    """Serve a second reference-photo preview (different subject — short hair, beard)."""
    html_path = "/app/backend/static/prompt_preview_alt.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


@api_router.get("/prompt-preview-prescan")
async def prompt_preview_prescan_page():
    html_path = "/app/backend/static/prompt_preview_prescan.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


@api_router.get("/blueprint-mode")
async def blueprint_mode_page():
    """Live preview of Blueprint Mode output for skull + lion references."""
    html_path = "/app/backend/static/blueprint_mode.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


@api_router.get("/blueprint-heavy")
async def blueprint_heavy_page():
    """Focused preview: Heavy-only with facial dotted shading guides."""
    html_path = "/app/backend/static/blueprint_heavy.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


@api_router.get("/tier-compare")
async def tier_compare_page():
    """Side-by-side: reference vs Light/Medium/Heavy stencils for visual QA
    of the standalone Light prompt vs the Blueprint Heavy+ Medium/Heavy."""
    html_path = "/app/backend/static/tier_compare.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


@api_router.get("/raw-vs-processed")
async def raw_vs_processed_page():
    """Side-by-side: raw AI output vs post-processed output."""
    html_path = "/app/backend/static/raw_vs_processed.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


class AIStencilDebugRequest(BaseModel):
    image_base64: str
    regenerate_style: Optional[str] = "heavy"
    temperature: Optional[float] = 0.0


@api_router.post("/ai-stencil-debug")
async def ai_stencil_debug(request: AIStencilDebugRequest):
    """Debug endpoint: return the raw AI output AND the post-processed output.

    Exists so the user can visually verify that post-processing is not altering
    line values. Skips cache and resize to keep the comparison honest.
    """
    style_to_detail = {"light": "minimal", "medium": "moderate", "heavy": "detailed"}
    detail_level = style_to_detail.get(request.regenerate_style or "heavy", "detailed")
    prompt = build_blueprint_prompt("black", detail_level)

    image_data = request.image_base64.split(",", 1)[1] if "," in request.image_base64 else request.image_base64

    raw_b64, mime = await generate_with_gemini(image_data, prompt, temperature=request.temperature)

    raw_data_url = f"data:{mime};base64,{raw_b64}"
    processed_data_url, near_black_fraction = post_process_stencil(raw_data_url)

    return {
        "raw_base64": raw_data_url,
        "processed_base64": processed_data_url,
        "prompt_length": len(prompt),
        "near_black_fraction": round(near_black_fraction, 4),
    }


@api_router.get("/prompt-preview-lion")
async def prompt_preview_lion_page():
    html_path = "/app/backend/static/prompt_preview_lion.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


@api_router.get("/prompt-preview-skull")
async def prompt_preview_skull_page():
    """Serve a third-reference preview (stylized skull-makeup photo)."""
    html_path = "/app/backend/static/prompt_preview_skull.html"
    if os.path.exists(html_path):
        with open(html_path, 'r') as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Preview page not found")


@api_router.get("/prompt-preview-asset/{filename}")
async def prompt_preview_asset(filename: str):
    """Serve the prompt-preview images. Whitelist only; no path traversal."""
    allowed = {
        'portrait.jpg', 'stencil_medium.png', 'stencil_heavy.png',
        'portrait2.jpg', 'stencil_medium_alt.png', 'stencil_heavy_alt.png',
        'portrait3.jpg', 'stencil_light_skull.png', 'stencil_medium_skull.png', 'stencil_heavy_skull.png',
        'portrait4.jpg', 'stencil_light_lion.png', 'stencil_medium_lion.png', 'stencil_heavy_lion.png',
        'prescan_skull_before.png', 'prescan_skull_after.png',
        'prescan_lion_before.png', 'prescan_lion_after.png',
        'prescan_skull_before_a.png', 'prescan_skull_before_b.png',
        'prescan_skull_after_a.png', 'prescan_skull_after_b.png',
        'prescan_lion_before_a.png', 'prescan_lion_before_b.png',
        'prescan_lion_after_a.png', 'prescan_lion_after_b.png',
        'blueprint_skull_light.png', 'blueprint_skull_heavy.png',
        'blueprint_lion_light.png', 'blueprint_lion_heavy.png',
        'rawvp_skull_raw.png', 'rawvp_skull_processed.png',
        'rawvp_lion_raw.png', 'rawvp_lion_processed.png',
        'tier_compare_light.png', 'tier_compare_medium.png', 'tier_compare_heavy.png',
    }
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Not found")
    file_path = f"/app/backend/static/{filename}"
    if os.path.exists(file_path):
        mime = 'image/png' if filename.endswith('.png') else 'image/jpeg'
        return FileResponse(file_path, media_type=mime)
    raise HTTPException(status_code=404, detail="File not found")

@api_router.get("/brand/{filename}")
async def brand_asset(filename: str):
    """Serve brand assets (logo, icons) for download during build credential setup."""
    # Whitelist to prevent path traversal
    allowed = {'logo.png', 'icon.png', 'adaptive-icon.png'}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="Not found")
    file_path = f"/app/backend/static/brand/{filename}"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type='image/png')
    raise HTTPException(status_code=404, detail="File not found")

FALLBACK_CREDITS = 15

@api_router.post("/auth/fallback-credits")
async def grant_fallback_credits(request: FastAPIRequest):
    """One-time fallback credits when paywall offerings fail to load."""
    auth = request.headers.get('authorization', '')
    token = auth.replace('Bearer ', '') if auth else ''
    user_id = None
    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            user_id = payload.get('user_id')
        except Exception:
            pass
    if not user_id:
        raise HTTPException(status_code=401, detail='Missing authorization')

    sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    if sub and sub.get('fallback_credits_granted'):
        raise HTTPException(status_code=400, detail='Fallback credits already granted')
    if sub and sub.get('available_credits', 0) > 0:
        raise HTTPException(status_code=400, detail='You already have credits')

    await db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': {
            'available_credits': FALLBACK_CREDITS,
            'tier': 'fallback_trial',
            'fallback_credits_granted': True,
        }},
        upsert=True
    )
    logger.info(f"[Fallback] Granted {FALLBACK_CREDITS} credits to {user_id}")
    return {"status": "granted", "credits": FALLBACK_CREDITS}

# ============================================
# ADMIN TOOL — Auth, Audit, Error Monitoring
# ============================================
import bcrypt

ADMIN_EMAIL = 'bodyboundstencil@yahoo.com'
ADMIN_PASSWORD_HASH = '$2b$12$OVZISVhwAYWw.Jlz.fs7Hu0Axbb6TS0dPMtxh7X1KM33H0Rh2JKvW'
ADMIN_LOGIN_ATTEMPTS = {}  # rate limiting: {ip: [timestamps]}
ADMIN_MAX_ATTEMPTS = 5
ADMIN_LOCKOUT_SECONDS = 300

def create_admin_token(email: str) -> str:
    payload = {
        'email': email,
        'role': 'admin',
        'exp': datetime.now(timezone.utc) + timedelta(hours=12),
        'iat': datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

async def verify_admin(auth_header: Optional[str]):
    if not auth_header or not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Missing admin authorization')
    token = auth_header[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        if payload.get('role') != 'admin':
            raise HTTPException(status_code=403, detail='Not an admin')
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail='Session expired — please log in again')
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail='Invalid session')

async def log_admin_action(admin_email: str, action: str, target_email: str, details: dict):
    await db.admin_actions.insert_one({
        'admin_email': admin_email,
        'action': action,
        'target_email': target_email,
        'details': details,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })

@api_router.post("/admin-auth/login")
async def admin_login(request: FastAPIRequest):
    body = await request.json()
    email = body.get('email', '').strip().lower()
    password = body.get('password', '')
    client_ip = request.client.host if request.client else 'unknown'

    # Rate limiting
    now = datetime.now(timezone.utc).timestamp()
    attempts = ADMIN_LOGIN_ATTEMPTS.get(client_ip, [])
    attempts = [t for t in attempts if now - t < ADMIN_LOCKOUT_SECONDS]
    if len(attempts) >= ADMIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail='Too many login attempts. Try again in 5 minutes.')
    
    if email != ADMIN_EMAIL.lower():
        attempts.append(now)
        ADMIN_LOGIN_ATTEMPTS[client_ip] = attempts
        raise HTTPException(status_code=401, detail='Invalid credentials')
    
    if not bcrypt.checkpw(password.encode(), ADMIN_PASSWORD_HASH.encode()):
        attempts.append(now)
        ADMIN_LOGIN_ATTEMPTS[client_ip] = attempts
        raise HTTPException(status_code=401, detail='Invalid credentials')
    
    ADMIN_LOGIN_ATTEMPTS.pop(client_ip, None)
    token = create_admin_token(email)
    logger.info(f'[Admin] Login success: {email} from {client_ip}')
    return {'token': token, 'email': email, 'expires_in': '12h'}

@api_router.get("/admin-auth/me")
async def admin_me(request: FastAPIRequest):
    admin = await verify_admin(request.headers.get('authorization'))
    return {'email': admin['email'], 'role': admin['role']}

@api_router.get("/admin-tool/dashboard")
async def admin_dashboard(request: FastAPIRequest):
    await verify_admin(request.headers.get('authorization'))
    
    total_users = await db.users.count_documents({})
    total_subs = await db.subscriptions.count_documents({})
    
    paid_tiers = ['walk-in', 'booked-out', 'the-shop', 'the-shop-member']
    paid_count = await db.subscriptions.count_documents({'tier': {'$in': paid_tiers}, 'is_trial': {'$ne': True}})
    bypass_count = await db.subscriptions.count_documents({'tier': 'paywall_bypass'})
    trial_count = await db.subscriptions.count_documents({'is_trial': True, 'tier': {'$in': paid_tiers}})
    
    # Revenue estimate
    revenue = 0
    async for sub in db.subscriptions.find({'tier': {'$in': paid_tiers}, 'is_trial': {'$ne': True}}, {'_id': 0, 'tier': 1}):
        prices = {'walk-in': 14.99, 'booked-out': 29.99, 'the-shop': 49.99, 'the-shop-member': 49.99}
        revenue += prices.get(sub.get('tier'), 0)
    
    # Recent key failures
    key_failures = await db.key_failures.count_documents({})
    recent_key_failures = []
    async for f in db.key_failures.find({}, {'_id': 0}).sort('timestamp', -1).limit(5):
        recent_key_failures.append(f)
    
    # Unmatched webhooks
    unmatched_count = await db.unmatched_webhooks.count_documents({})
    
    # API health
    api_health = 'healthy'
    if recent_key_failures:
        last_failure = recent_key_failures[0]
        if not last_failure.get('resolved'):
            api_health = 'degraded'
    
    return {
        'total_users': total_users,
        'paid_subscribers': paid_count,
        'active_trials': trial_count,
        'bypass_users': bypass_count,
        'monthly_revenue_gross': round(revenue, 2),
        'monthly_revenue_net_15': round(revenue * 0.85, 2),
        'api_health': api_health,
        'total_key_failures': key_failures,
        'unmatched_webhooks': unmatched_count,
        'recent_key_failures': recent_key_failures,
    }

@api_router.get("/admin-tool/errors/webhooks")
async def admin_errors_webhooks(request: FastAPIRequest):
    await verify_admin(request.headers.get('authorization'))
    errors = []
    async for doc in db.unmatched_webhooks.find({}, {'_id': 0}).sort('timestamp', -1).limit(50):
        errors.append(doc)
    return {'webhook_failures': errors, 'total': await db.unmatched_webhooks.count_documents({})}

@api_router.get("/admin-tool/errors/generation")
async def admin_errors_generation(request: FastAPIRequest):
    await verify_admin(request.headers.get('authorization'))
    errors = []
    async for doc in db.key_failures.find({}, {'_id': 0}).sort('timestamp', -1).limit(50):
        errors.append(doc)
    return {'generation_failures': errors, 'total': await db.key_failures.count_documents({})}

@api_router.get("/admin-tool/errors/sync")
async def admin_errors_sync(request: FastAPIRequest):
    await verify_admin(request.headers.get('authorization'))
    # Subscription sync failures: users with RC webhooks that didn't match
    sync_issues = []
    async for doc in db.unmatched_webhooks.find(
        {'event_type': {'$in': ['INITIAL_PURCHASE', 'RENEWAL', 'TRANSFER']}},
        {'_id': 0}
    ).sort('timestamp', -1).limit(50):
        sync_issues.append(doc)
    return {'sync_failures': sync_issues, 'total': len(sync_issues)}

@api_router.get("/admin-tool/user/{email}")
async def admin_user_detail(email: str, request: FastAPIRequest):
    await verify_admin(request.headers.get('authorization'))
    user = await db.users.find_one({'email': {'$regex': email, '$options': 'i'}}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    sub = await db.subscriptions.find_one({'user_id': user['user_id']}, {'_id': 0})
    actions = []
    async for a in db.admin_actions.find({'target_email': {'$regex': email, '$options': 'i'}}, {'_id': 0}).sort('timestamp', -1).limit(20):
        actions.append(a)
    return {'user': user, 'subscription': sub, 'admin_history': actions}

@api_router.post("/admin-tool/action/grant-credits")
async def admin_action_grant_credits(request: FastAPIRequest):
    admin = await verify_admin(request.headers.get('authorization'))
    body = await request.json()
    email = body.get('email', '')
    credits = body.get('credits', 0)
    # Use EXACT email match to prevent accidentally hitting the wrong
    # user when multiple emails share a prefix (e.g. bodyboundstencil
    # vs bodyboundstencilapp).
    user = await db.users.find_one({'email': email}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail=f'User not found (exact email match: "{email}")')
    await db.subscriptions.update_one({'user_id': user['user_id']}, {'$inc': {'available_credits': credits}}, upsert=True)
    updated = await db.subscriptions.find_one({'user_id': user['user_id']}, {'_id': 0})
    # Prevent going negative
    if updated.get('available_credits', 0) < 0:
        await db.subscriptions.update_one({'user_id': user['user_id']}, {'$set': {'available_credits': 0}})
        updated['available_credits'] = 0
    await log_admin_action(admin['email'], 'grant_credits', email, {'credits': credits, 'new_total': updated.get('available_credits', 0)})
    return {'status': 'ok', 'new_credits': updated.get('available_credits', 0)}

@api_router.post("/admin-tool/action/set-credits")
async def admin_action_set_credits(request: FastAPIRequest):
    """Set credits to an EXACT value (overwrites current balance)."""
    admin = await verify_admin(request.headers.get('authorization'))
    body = await request.json()
    email = body.get('email', '')
    credits = int(body.get('credits', 0))
    if credits < 0:
        raise HTTPException(status_code=400, detail='Credits cannot be negative')
    user = await db.users.find_one({'email': email}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail=f'User not found (exact email match: "{email}")')
    await db.subscriptions.update_one(
        {'user_id': user['user_id']},
        {'$set': {'available_credits': credits, 'last_event': 'ADMIN_SET_CREDITS'}},
        upsert=True,
    )
    await log_admin_action(admin['email'], 'set_credits', email, {'new_total': credits})
    return {'status': 'ok', 'new_credits': credits}


@api_router.post("/admin-tool/action/change-tier")
async def admin_action_change_tier(request: FastAPIRequest):
    admin = await verify_admin(request.headers.get('authorization'))
    body = await request.json()
    email = body.get('email', '')
    new_tier = body.get('tier', '')
    tier_credits = {'walk-in': 125, 'booked-out': 500, 'the-shop': 1500}
    user = await db.users.find_one({'email': {'$regex': email, '$options': 'i'}}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    update = {'tier': new_tier, 'last_event': 'ADMIN_TIER_CHANGE', 'is_trial': False}
    if new_tier in tier_credits:
        update['available_credits'] = tier_credits[new_tier]
    await db.subscriptions.update_one({'user_id': user['user_id']}, {'$set': update}, upsert=True)
    await log_admin_action(admin['email'], 'change_tier', email, {'new_tier': new_tier, 'credits_set': tier_credits.get(new_tier, 'unchanged')})
    return {'status': 'ok', 'tier': new_tier}

@api_router.post("/admin-tool/action/reset-account")
async def admin_action_reset_account(request: FastAPIRequest):
    admin = await verify_admin(request.headers.get('authorization'))
    body = await request.json()
    email = body.get('email', '')
    user = await db.users.find_one({'email': {'$regex': email, '$options': 'i'}}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    await db.subscriptions.update_one({'user_id': user['user_id']}, {'$set': {
        'tier': None, 'available_credits': 0, 'is_trial': False, 'fallback_credits_granted': False,
        'last_event': 'ADMIN_RESET',
        # Clear the RC identity link so stale anonymous/device entitlements
        # cannot auto-restore after the reset. The user's NEXT sign-in will
        # re-link via /api/subscription/link-rc using their authenticated email.
        'revenuecat_customer_id': None,
    }}, upsert=True)
    await log_admin_action(admin['email'], 'reset_account', email, {'set_to': 'expired/0'})
    return {'status': 'ok', 'tier': None, 'credits': 0}

@api_router.post("/admin-tool/action/paywall-bypass")
async def admin_action_bypass(request: FastAPIRequest):
    admin = await verify_admin(request.headers.get('authorization'))
    body = await request.json()
    email = body.get('email', '')
    user = await db.users.find_one({'email': {'$regex': email, '$options': 'i'}}, {'_id': 0})
    if not user:
        raise HTTPException(status_code=404, detail='User not found')
    await db.subscriptions.update_one({'user_id': user['user_id']}, {'$set': {
        'tier': 'paywall_bypass', 'available_credits': 10, 'is_trial': False,
        'last_event': 'ADMIN_BYPASS',
    }}, upsert=True)
    await log_admin_action(admin['email'], 'paywall_bypass', email, {'credits': 10, 'tier': 'paywall_bypass'})
    return {'status': 'ok', 'tier': 'paywall_bypass', 'credits': 10}

@api_router.get("/admin-tool/audit-log")
async def admin_audit_log(request: FastAPIRequest):
    await verify_admin(request.headers.get('authorization'))
    actions = []
    async for a in db.admin_actions.find({}, {'_id': 0}).sort('timestamp', -1).limit(100):
        actions.append(a)
    return {'actions': actions, 'total': await db.admin_actions.count_documents({})}

@api_router.get("/admin-tool/search")
async def admin_search_users(request: FastAPIRequest, q: str = ''):
    await verify_admin(request.headers.get('authorization'))
    if not q or len(q) < 2:
        raise HTTPException(status_code=400, detail='Search query too short')
    users = []
    async for u in db.users.find({'$or': [
        {'email': {'$regex': q, '$options': 'i'}},
        {'display_name': {'$regex': q, '$options': 'i'}},
        {'name': {'$regex': q, '$options': 'i'}},
    ]}, {'_id': 0}).limit(20):
        sub = await db.subscriptions.find_one({'user_id': u['user_id']}, {'_id': 0})
        users.append({**u, **(sub or {})})
    return {'results': users, 'count': len(users)}

@api_router.get("/admin-panel")
async def serve_admin_page():
    html_path = "/app/backend/static/admin.html"
    try:
        with open(html_path) as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Admin page not found")

# Root health check — nginx in production hits /health (no /api prefix)
@app.get("/health")
async def root_health_check():
    return {"status": "healthy", "service": "tattoo-stencil-api"}

# Include the router in the main app
app.include_router(api_router)


# Root-path health probe. Emergent's k8s liveness/readiness probe checks
# `/` — not `/api/health` — so an unhandled `/` would 404 and the pod
# would be marked unhealthy. Keep this returning 200 JSON so probes pass
# and Cloudflare keeps routing traffic to the pod.
@app.get("/")
async def root_health():
    return {"status": "healthy", "service": "tattoo-stencil-api"}

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_scheduler():
    """Start background cron scheduler for daily referral verification."""
    # Ensure unique index on subscriptions.user_id — required for safe
    # concurrent upserts during credit refills (rollover policy).
    try:
        await db.subscriptions.create_index('user_id', unique=True, background=True)
        logger.info('[Startup] Ensured unique index on subscriptions.user_id')
    except Exception as e:
        logger.warning(f'[Startup] Could not create unique index on subscriptions.user_id: {e}')

    # Idempotency for /api/credits/deduct — TTL=24h auto-expires old keys.
    # Doc shape: { _id: "<user_id>:<reroll_id>", created_at: <datetime>, response: <dict> }
    try:
        await db.credit_deduct_idempotency.create_index(
            'created_at', expireAfterSeconds=86400, background=True
        )
        logger.info('[Startup] Ensured TTL index on credit_deduct_idempotency.created_at (24h)')
    except Exception as e:
        logger.warning(f'[Startup] Could not create TTL index on credit_deduct_idempotency: {e}')

    # Idempotency for RevenueCat webhooks — TTL=30d. Prevents replays from
    # triggering INITIAL_PURCHASE / RENEWAL writes more than once per event.
    try:
        await db.revenuecat_webhook_events.create_index(
            'created_at', expireAfterSeconds=2592000, background=True
        )
        logger.info('[Startup] Ensured TTL index on revenuecat_webhook_events.created_at (30d)')
    except Exception as e:
        logger.warning(f'[Startup] Could not create TTL index on revenuecat_webhook_events: {e}')

    async def daily_referral_cron():
        """Runs every 24 hours: processes pending referral verifications."""
        while True:
            await asyncio.sleep(86400)  # 24 hours
            try:
                result = await process_referral_verifications()
                logger.info(f'[Cron Auto] Referral verification: verified={result["verified"]}, rejected={result["rejected"]}, checked={result["checked"]}')
            except Exception as e:
                logger.error(f'[Cron Auto] Referral verification failed: {e}')
    # Run initial check 60s after startup, then daily
    async def initial_check():
        await asyncio.sleep(60)
        try:
            result = await process_referral_verifications()
            logger.info(f'[Cron Auto] Initial referral verification: verified={result["verified"]}, rejected={result["rejected"]}, checked={result["checked"]}')
        except Exception as e:
            logger.error(f'[Cron Auto] Initial referral verification failed: {e}')
    asyncio.create_task(initial_check())
    asyncio.create_task(daily_referral_cron())
    logger.info('[Cron Auto] Referral verification scheduler started (runs daily)')

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
