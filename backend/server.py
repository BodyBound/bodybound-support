from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
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

def cache_stencil(cache_key: str, stencil_base64: str):
    """Cache a generated stencil"""
    global stencil_cache
    # Evict oldest if cache is full
    if len(stencil_cache) >= CACHE_MAX_SIZE:
        # Remove oldest entry (first key)
        oldest_key = next(iter(stencil_cache))
        del stencil_cache[oldest_key]
    stencil_cache[cache_key] = {
        'stencil': stencil_base64,
        'timestamp': datetime.utcnow()
    }
    logger.info(f"[Cache] Cached stencil, total cached: {len(stencil_cache)}")

def get_cached_stencil(cache_key: str) -> Optional[str]:
    """Retrieve a cached stencil if available"""
    if cache_key in stencil_cache:
        logger.info(f"[Cache] Cache HIT - returning cached stencil")
        return stencil_cache[cache_key]['stencil']
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

def post_process_stencil(base64_string: str) -> str:
    """Post-process AI-generated stencil to create a TRANSPARENT PNG.
    
    This function:
    1. Removes ANY color - converts to pure grayscale
    2. Forces TRUE BINARY output - only black and transparent pixels
    3. White background becomes TRANSPARENT
    4. Black linework remains solid
    """
    try:
        logger.info("[PostProcess] Starting stencil post-processing...")
        
        # Decode image
        if ',' in base64_string:
            prefix = base64_string.split(',')[0] + ','
            base64_data = base64_string.split(',')[1]
        else:
            prefix = "data:image/png;base64,"
            base64_data = base64_string
        
        img_data = base64.b64decode(base64_data)
        img = Image.open(BytesIO(img_data))
        
        # Convert to OpenCV format
        img_cv = cv2.cvtColor(np.array(img.convert('RGB')), cv2.COLOR_RGB2BGR)
        
        # === STEP 1: Force grayscale to remove any color ===
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        logger.info("[PostProcess] Converted to grayscale (removed any color)")
        
        # === STEP 2: Apply adaptive threshold for better line preservation ===
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        logger.info("[PostProcess] Applied Otsu's adaptive threshold")
        
        # === STEP 3: Ensure lines are solid black, background is white ===
        white_pixels = np.sum(binary == 255)
        black_pixels = np.sum(binary == 0)
        if black_pixels > white_pixels:
            binary = 255 - binary
            logger.info("[PostProcess] Inverted to ensure white background")
        
        # === STEP 4: Create transparent PNG - white becomes transparent ===
        # Create RGBA image (4 channels: R, G, B, Alpha)
        height, width = binary.shape
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        
        # Black pixels (linework) = solid black with full opacity
        # White pixels (background) = transparent
        black_mask = binary == 0
        white_mask = binary == 255
        
        # Set black linework (R=0, G=0, B=0, A=255)
        rgba[black_mask] = [0, 0, 0, 255]
        
        # Set white background as transparent (R=255, G=255, B=255, A=0)
        rgba[white_mask] = [255, 255, 255, 0]
        
        logger.info("[PostProcess] Created transparent PNG - white background removed")
        
        # Convert to PIL Image and save as PNG with alpha
        result_img = Image.fromarray(rgba, 'RGBA')
        
        # Save to buffer
        buffer = BytesIO()
        result_img.save(buffer, format='PNG')
        result_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        logger.info("[PostProcess] Stencil post-processing complete - transparent PNG output")
        
        return f"data:image/png;base64,{result_base64}"
        
    except Exception as e:
        logger.error(f"[PostProcess] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return base64_string  # Return original on error

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

@api_router.get("/diagnostics")
async def diagnostics():
    """Diagnostic endpoint to check API key status and library versions on production"""
    import importlib
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
        results["gemini_api_test"] = "PASS" if response else "FAIL - empty response"
    except Exception as e:
        results["gemini_api_test"] = f"FAIL: {str(e)}"
    
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
    
    return results

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

# AI-Powered Stencil Generation
class AIStencilRequest(BaseModel):
    image_base64: str
    style: str = Field(default="tattoo")  # "tattoo", "clean", "detailed"
    line_color: str = Field(default="purple")  # "purple", "blue", "black"
    shading_detail: int = Field(default=50, ge=0, le=100)  # 0-100: how much cross-hatching
    solid_fill: int = Field(default=30, ge=0, le=100)  # 0-100: how much solid black fill
    regenerate_style: Optional[str] = Field(default=None)  # "light", "medium", "heavy" - if set, only regenerate this style

class AIStencilResponse(BaseModel):
    stencil_base64: str
    processing_time_ms: float
    regenerated_style: Optional[str] = None  # Which style was regenerated (if single style request)
    
async def generate_with_gemini(image_data: str, prompt: str) -> tuple[str, str]:
    """Generate stencil with Gemini using emergentintegrations LlmChat
    
    Uses gemini-3-pro-image-preview model which produces better quality stencils.
    Tries GOOGLE_API_KEY first, auto-falls back to EMERGENT_LLM_KEY if it fails.
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
                system_message="You are an expert tattoo stencil artist. You create clean, professional tattoo stencils from reference images."
            )
            chat.with_model("gemini", "gemini-3-pro-image-preview").with_params(modalities=["image", "text"])
            
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
async def generate_ai_stencil(request: AIStencilRequest):
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
        
        # Determine the style for caching
        cache_style = request.regenerate_style or f"shading_{request.shading_detail}"
        
        # === STEP 1: Check cache first for instant results ===
        cache_key = get_cache_key(request.image_base64, cache_style)
        cached_result = get_cached_stencil(cache_key)
        if cached_result:
            logger.info(f"[AI-Stencil] Cache HIT - returning cached result in {(time.time() - start_time) * 1000:.0f}ms")
            return AIStencilResponse(
                stencil_base64=cached_result,
                processing_time_ms=round((time.time() - start_time) * 1000, 2),
                regenerated_style=request.regenerate_style
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
        
        # Create the prompt - Original Feb 16 style that produced excellent stencils
        prompt = f"""Transform this image into a professional tattoo stencil drawing.

CRITICAL REQUIREMENTS:
1. Create clean, smooth, continuous lines - NO noise or scattered marks
2. Use {line_color} colored lines on a pure white background
3. Draw like a skilled tattoo artist would hand-draw a stencil:
   - Main outline contours with solid, confident lines
   - Inner detail lines for important features
   - Use dotted or dashed lines to indicate shading/contour areas where the tattoo artist would add shading
4. Simplify the image - remove unnecessary details, keep only the essential form
5. Lines should be bold enough to transfer clearly to skin
6. The output should look like a professional tattoo stencil/blueprint
7. NO grayscale shading - only line work
8. Ensure all lines are connected and flowing, not broken or pixelated

DETAIL LEVEL: {detail_level.upper()}
{
"- Minimal detail: Just essential outlines, very clean and simple" if detail_level == "minimal" else
"- Moderate detail: Outlines plus key interior details and contour guides" if detail_level == "moderate" else
"- Maximum detail: Full detail with hatching, all contours, and shading guides"
}

Style: Professional tattoo stencil suitable for thermal transfer paper"""

        
        image_base64 = None
        mime_type = 'image/png'
        provider_used = "google"
        last_error = None
        
        # Use Google Gemini (can see and trace reference images)
        # OpenAI gpt-image-1 is text-to-image only and CANNOT trace reference photos
        if EMERGENT_LLM_KEY or AI_API_KEY:
            try:
                logger.info("Attempting stencil generation with Google Gemini...")
                image_base64, mime_type = await asyncio.wait_for(
                    generate_with_gemini(image_data, prompt),
                    timeout=120.0  # 120 second timeout - image generation takes time
                )
                provider_used = "google"
                logger.info("Successfully generated with Google Gemini")
            except asyncio.TimeoutError:
                last_error = "Google Gemini timed out after 120 seconds"
                logger.error(f"Google Gemini timed out")
                raise HTTPException(
                    status_code=503, 
                    detail="AI generation is taking longer than expected. Please try again - the servers may be busy."
                )
            except Exception as e:
                last_error = str(e)
                logger.error(f"Google Gemini failed: {e}")
                raise HTTPException(
                    status_code=503, 
                    detail=f"AI service error: {str(e)}. Please try again."
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
        stencil_base64 = post_process_stencil(stencil_base64)
        
        # === STEP 8: CACHE THE RESULT for future instant retrieval ===
        cache_stencil(cache_key, stencil_base64)
        
        processing_time = (time.time() - start_time) * 1000
        
        logger.info(f"AI stencil generated in {processing_time:.2f}ms using {provider_used}")
        
        return AIStencilResponse(
            stencil_base64=stencil_base64,
            processing_time_ms=round(processing_time, 2),
            provider=provider_used,
            regenerated_style=request.regenerate_style
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
        
        # Create the prompt - Original Feb 16 style that produced excellent stencils
        prompt = f"""Transform this image into a professional tattoo stencil drawing.

CRITICAL REQUIREMENTS:
1. Create clean, smooth, continuous lines - NO noise or scattered marks
2. Use purple/violet colored lines on a pure white background
3. Draw like a skilled tattoo artist would hand-draw a stencil:
   - Main outline contours with solid, confident lines
   - Inner detail lines for important features
   - Use dotted or dashed lines to indicate shading/contour areas where the tattoo artist would add shading
4. Simplify the image - remove unnecessary details, keep only the essential form
5. Lines should be bold enough to transfer clearly to skin
6. The output should look like a professional tattoo stencil/blueprint
7. NO grayscale shading - only line work
8. Ensure all lines are connected and flowing, not broken or pixelated

DETAIL LEVEL: {detail_level.upper()}
{
"- Minimal detail: Just essential outlines, very clean and simple" if detail_level == "minimal" else
"- Moderate detail: Outlines plus key interior details and contour guides" if detail_level == "moderate" else
"- Maximum detail: Full detail with hatching, all contours, and shading guides"
}

Style: Professional tattoo stencil suitable for thermal transfer paper"""

        # Generate using Gemini
        result_base64, mime_type = await generate_with_gemini(image_data, prompt)
        
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
            processed_stencil = post_process_stencil(stencil_with_prefix)
            
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

class GoogleSessionRequest(BaseModel):
    session_id: str
    device_id: Optional[str] = None  # Device ID for anti-abuse

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
REFERRAL_BONUS_CREDITS = 20  # Credits awarded to both referrer and friend

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
    
    return {
        'available_credits': available_credits,
        'tier': sub.get('tier'),
        'is_trial': is_trial,
        'trial_expires_at': trial_expires_at,
        'trial_days_remaining': trial_days_remaining,
        'renewal_date': sub.get('renewal_date'),
        'revenuecat_customer_id': sub.get('revenuecat_customer_id'),
        'is_studio_team': is_studio_team,
        'studio_team_id': studio_team_id,
        'needs_subscription': sub.get('tier') in (None, 'trial_expired', 'expired'),
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
    
    No free credits are granted — the user must subscribe via Apple/RevenueCat
    to start their 3-day free trial (managed by Apple, not our backend).
    """
    now = datetime.now(timezone.utc)
    subscription = {
        'user_id': user_id,
        'tier': None,
        'available_credits': 0,
        'is_trial': False,
        'trial_expires_at': None,
        'renewal_date': None,
        'revenuecat_customer_id': None,
        'anti_abuse_email': email.lower() if email else None,
        'anti_abuse_device_id': device_id,
        'anti_abuse_provider': f'{provider}:{provider_id}',
        'created_at': now.isoformat(),
    }
    logger.info(f'[Subscription] New user {user_id} — no trial, must subscribe via Apple')
    
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

    return {'user': user, 'session_token': create_session_token(user_id)}

@api_router.get("/auth/me")
async def get_me(request: FastAPIRequest):
    """Get current user info and credits"""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    credits = await get_user_credits(user['user_id'])
    return {'user': user, 'credits': credits}

@api_router.post("/credits/deduct")
async def deduct_credit(request: FastAPIRequest):
    """Deduct 1 credit for stencil generation (atomic).
    
    For studio team members, deducts from the shared team pool instead of individual credits.
    """
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    
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
            raise HTTPException(status_code=402, detail='Studio team has no credits remaining')
        return {
            'available_credits': team_result['shared_credits'],
            'tier': 'the-shop',
            'is_studio_team': True,
        }
    
    # Regular individual credit deduction
    result = await db.subscriptions.find_one_and_update(
        {'user_id': user_id, 'available_credits': {'$gt': 0}},
        {'$inc': {'available_credits': -1}},
        return_document=True,
        projection={'_id': 0}
    )
    if not result:
        raise HTTPException(status_code=402, detail='Insufficient credits')
    return {'available_credits': result['available_credits'], 'tier': result.get('tier')}

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
    'bodybound_1499_1m_3d': {'tier': 'walk-in', 'credits': 125},
    'bodybound_2999_1m_3d': {'tier': 'booked-out', 'credits': 500},
    'bodybound_9999_1m_3d': {'tier': 'the-shop', 'credits': 1500},
}

@api_router.post("/webhooks/revenuecat")
async def revenuecat_webhook(request: FastAPIRequest):
    """Handle RevenueCat subscription lifecycle events.
    app_user_id = our backend user_id (set via Purchases.logIn(userId) in the app).
    """
    auth = request.headers.get('authorization', '')
    if REVENUECAT_WEBHOOK_AUTH and auth != f'Bearer {REVENUECAT_WEBHOOK_AUTH}':
        raise HTTPException(status_code=401, detail='Unauthorized')
    body = await request.json()
    event = body.get('event', {})
    event_type = event.get('type', '')
    # app_user_id is our backend user_id (we call Purchases.logIn(userId) in the app)
    user_id = event.get('app_user_id', '')
    product_id = event.get('product_id', '')
    logger.info(f'[RevenueCat] {event_type} | user_id={user_id} | product={product_id}')
    tier_info = PRODUCT_CREDIT_MAP.get(product_id, {})
    if event_type in ('INITIAL_PURCHASE', 'RENEWAL') and tier_info and user_id:
        # Detect Apple trial vs paid subscription
        period_type = event.get('period_type', 'NORMAL')
        is_apple_trial = period_type == 'TRIAL'
        credits_to_grant = TRIAL_CREDITS if is_apple_trial else tier_info['credits']
        next_renewal = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {
                'tier': tier_info['tier'],
                'available_credits': credits_to_grant,
                'is_trial': is_apple_trial,
                'renewal_date': next_renewal,
                'last_event': event_type,
                'period_type': period_type,
            }},
            upsert=True
        )
        logger.info(f'[RevenueCat] Granted {credits_to_grant} credits ({"trial" if is_apple_trial else "paid"}) to {user_id}')
    elif event_type in ('CANCELLATION', 'EXPIRATION') and user_id:
        # Keep remaining credits but mark tier as expired
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {'tier': 'expired', 'last_event': event_type}}
        )
    return {'status': 'ok'}


@api_router.post("/subscription/sync")
async def sync_subscription(request: FastAPIRequest):
    """Sync subscription status from RevenueCat entitlement data sent by the frontend.
    
    Called after a successful purchase or on app startup when the frontend detects
    active RevenueCat entitlements that don't match the backend subscription state.
    This acts as a fallback when the RevenueCat webhook doesn't fire.
    """
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    
    body = await request.json()
    product_id = body.get('product_id')
    is_trial = body.get('is_trial', False)  # Frontend passes trial status from RevenueCat
    
    if not product_id:
        raise HTTPException(status_code=400, detail='Missing product_id')
    
    tier_info = PRODUCT_CREDIT_MAP.get(product_id)
    if not tier_info:
        logger.warning(f'[Sync] Unknown product_id: {product_id} for user {user_id}')
        raise HTTPException(status_code=400, detail='Unknown product')
    
    # Cap credits during Apple trial
    credits_to_grant = TRIAL_CREDITS if is_trial else tier_info['credits']
    
    # Check current subscription to avoid overwriting if already correct
    existing_sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    if existing_sub and existing_sub.get('tier') == tier_info['tier'] and existing_sub.get('is_trial', False) == is_trial:
        # Already synced — return current credits
        logger.info(f'[Sync] User {user_id} already on tier {tier_info["tier"]}, skipping')
        credits = await get_user_credits(user_id)
        return credits
    
    next_renewal = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': {
            'tier': tier_info['tier'],
            'available_credits': credits_to_grant,
            'is_trial': is_trial,
            'trial_expires_at': None,
            'renewal_date': next_renewal,
            'synced_from': 'frontend',
            'last_event': 'FRONTEND_SYNC',
        }},
        upsert=True
    )
    logger.info(f'[Sync] User {user_id} synced to tier {tier_info["tier"]} with {credits_to_grant} credits ({"trial" if is_trial else "paid"}, product: {product_id})')
    
    credits = await get_user_credits(user_id)
    return credits


# ---- Refer-a-Friend ----

@api_router.get("/referral/code")
async def get_referral_code(request: FastAPIRequest):
    """Get or generate the user's unique referral code."""
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    
    # Check if user already has a referral code
    existing = await db.referrals.find_one({'referrer_user_id': user_id, 'type': 'code'}, {'_id': 0})
    if existing:
        stats = await db.referrals.count_documents({'referrer_user_id': user_id, 'type': 'redemption', 'status': 'completed'})
        return {
            'referral_code': existing['referral_code'],
            'total_referrals': stats,
            'credits_earned': stats * REFERRAL_BONUS_CREDITS,
        }
    
    # Generate a unique code: BB-XXXXXX
    code = f'BB-{uuid.uuid4().hex[:6].upper()}'
    await db.referrals.insert_one({
        'type': 'code',
        'referral_code': code,
        'referrer_user_id': user_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
    })
    logger.info(f'[Referral] Generated code {code} for user {user_id}')
    return {
        'referral_code': code,
        'total_referrals': 0,
        'credits_earned': 0,
    }


@api_router.post("/referral/redeem")
async def redeem_referral_code(request: FastAPIRequest):
    """Redeem a referral code. Awards 20 credits to both the referrer and the redeemer.
    
    Rules:
    - User must have an active subscription (not trial, not expired)
    - Cannot redeem your own code
    - Can only redeem one referral code ever
    """
    auth_header = request.headers.get('authorization')
    user = await get_current_user(auth_header)
    user_id = user['user_id']
    
    body = await request.json()
    code = body.get('referral_code', '').strip().upper()
    
    if not code:
        raise HTTPException(status_code=400, detail='Missing referral_code')
    
    # Find the referral code
    code_doc = await db.referrals.find_one({'type': 'code', 'referral_code': code}, {'_id': 0})
    if not code_doc:
        raise HTTPException(status_code=404, detail='Invalid referral code')
    
    referrer_user_id = code_doc['referrer_user_id']
    
    # Can't redeem your own code
    if referrer_user_id == user_id:
        raise HTTPException(status_code=400, detail='Cannot redeem your own referral code')
    
    # Check if user already redeemed a code
    already_redeemed = await db.referrals.find_one({
        'type': 'redemption', 'redeemer_user_id': user_id, 'status': 'completed'
    })
    if already_redeemed:
        raise HTTPException(status_code=400, detail='You have already redeemed a referral code')
    
    # Check redeemer has an active subscription
    redeemer_sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    active_tiers = ['walk-in', 'booked-out', 'the-shop', 'the-shop-member']
    if not redeemer_sub or redeemer_sub.get('tier') not in active_tiers:
        raise HTTPException(status_code=400, detail='You need an active subscription to redeem a referral code')
    
    # Check referrer has an active subscription
    referrer_sub = await db.subscriptions.find_one({'user_id': referrer_user_id}, {'_id': 0})
    if not referrer_sub or referrer_sub.get('tier') not in active_tiers:
        raise HTTPException(status_code=400, detail='Referrer does not have an active subscription')
    
    # Award credits to both parties
    # Referrer: add credits (check if team member for shared pool)
    referrer_team_id = referrer_sub.get('studio_team_id')
    if referrer_team_id:
        await db.studio_teams.update_one(
            {'team_id': referrer_team_id},
            {'$inc': {'shared_credits': REFERRAL_BONUS_CREDITS}}
        )
    else:
        await db.subscriptions.update_one(
            {'user_id': referrer_user_id},
            {'$inc': {'available_credits': REFERRAL_BONUS_CREDITS}}
        )
    
    # Redeemer: add credits (check if team member for shared pool)
    redeemer_team_id = redeemer_sub.get('studio_team_id')
    if redeemer_team_id:
        await db.studio_teams.update_one(
            {'team_id': redeemer_team_id},
            {'$inc': {'shared_credits': REFERRAL_BONUS_CREDITS}}
        )
    else:
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$inc': {'available_credits': REFERRAL_BONUS_CREDITS}}
        )
    
    # Record the redemption
    await db.referrals.insert_one({
        'type': 'redemption',
        'referral_code': code,
        'referrer_user_id': referrer_user_id,
        'redeemer_user_id': user_id,
        'credits_awarded': REFERRAL_BONUS_CREDITS,
        'status': 'completed',
        'created_at': datetime.now(timezone.utc).isoformat(),
    })
    
    logger.info(f'[Referral] {user_id} redeemed code {code} from {referrer_user_id} — {REFERRAL_BONUS_CREDITS} credits each')
    
    credits = await get_user_credits(user_id)
    return {
        'message': f'Referral applied! You and your friend both received {REFERRAL_BONUS_CREDITS} bonus credits.',
        'credits': credits,
    }


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
    """Shared credit refresh logic used by both cron endpoints."""
    now = datetime.now(timezone.utc)
    active_tiers = ['walk-in', 'booked-out', 'the-shop']
    tier_credits = {'walk-in': 125, 'booked-out': 500, 'the-shop': 1500}

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
            credits = tier_credits.get(sub.get('tier', ''), 0)
            if credits:
                next_renewal = (renewal_date + timedelta(days=30)).isoformat()
                await db.subscriptions.update_one(
                    {'user_id': sub['user_id']},
                    {'$set': {'available_credits': credits, 'renewal_date': next_renewal}}
                )
                refreshed += 1
                logger.info(f'[Cron] Refreshed credits for user {sub["user_id"]}: {credits} credits')

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

# Root health check — nginx in production hits /health (no /api prefix)
@app.get("/health")
async def root_health_check():
    return {"status": "healthy", "service": "tattoo-stencil-api"}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
