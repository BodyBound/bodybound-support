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
    """Post-process AI-generated stencil to ensure quality.
    
    This function:
    1. Boosts line weight if lines are too thin
    2. Cleans up stray pixels/artifacts
    3. Ensures consistent line darkness
    4. Removes noise while preserving detail
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
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        
        # === STEP 1: Analyze current line darkness ===
        # Find dark pixels (lines)
        dark_mask = gray < 128
        if np.sum(dark_mask) > 0:
            avg_line_darkness = np.mean(gray[dark_mask])
            logger.info(f"[PostProcess] Average line darkness: {avg_line_darkness:.1f}")
        else:
            avg_line_darkness = 128
        
        # === STEP 2: Boost line weight if too thin/light ===
        # If lines are too light (gray instead of black), make them darker
        if avg_line_darkness > 60:  # Lines should be closer to 0 (black)
            logger.info("[PostProcess] Boosting line darkness...")
            # Increase contrast to make lines darker
            # Apply a curve that makes darks darker while keeping whites white
            lut = np.zeros(256, dtype=np.uint8)
            for i in range(256):
                if i < 180:  # Dark to mid tones - make darker
                    lut[i] = max(0, int(i * 0.7))
                else:  # Keep whites white
                    lut[i] = i
            gray = cv2.LUT(gray, lut)
        
        # === STEP 3: Clean up artifacts ===
        # Remove small isolated pixels (noise)
        # Use morphological opening to remove small white noise in black areas
        kernel_small = np.ones((2, 2), np.uint8)
        
        # Invert for morphological operations (lines become white)
        inverted = 255 - gray
        
        # Remove small noise
        cleaned = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, kernel_small)
        
        # Slight dilation to ensure lines are bold enough
        kernel_dilate = np.ones((2, 2), np.uint8)
        # Only dilate if lines are thin
        line_pixels = np.sum(cleaned > 128)
        total_pixels = cleaned.shape[0] * cleaned.shape[1]
        line_ratio = line_pixels / total_pixels
        
        if line_ratio < 0.05:  # Less than 5% of image is lines - they're thin
            logger.info("[PostProcess] Lines appear thin, applying slight thickening...")
            cleaned = cv2.dilate(cleaned, kernel_dilate, iterations=1)
        
        # Invert back
        gray = 255 - cleaned
        
        # === STEP 4: Ensure pure black and white ===
        # Threshold to ensure crisp black/white output
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        
        # Convert back to 3-channel for consistency
        result = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        
        # Convert back to base64
        _, buffer = cv2.imencode('.png', result)
        result_base64 = base64.b64encode(buffer).decode('utf-8')
        
        logger.info("[PostProcess] Stencil post-processing complete")
        
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
    import google.generativeai as genai
    
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
        
        # Configure Gemini
        genai.configure(api_key=AI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash-image')
        
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

        # Call Gemini for enhancement
        image_bytes = base64.b64decode(base64_data)
        
        response = model.generate_content([
            enhancement_prompt,
            {"mime_type": "image/png", "data": image_bytes}
        ])
        
        # Extract the enhanced image
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    enhanced_base64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                    mime_type = part.inline_data.mime_type or 'image/png'
                    
                    # Verify the enhanced image
                    enhanced_img = Image.open(BytesIO(part.inline_data.data))
                    new_width, new_height = enhanced_img.size
                    logger.info(f"[AIEnhance] Enhanced resolution: {new_width}x{new_height}")
                    
                    return f"data:{mime_type};base64,{enhanced_base64}"
        
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

# API Routes
@api_router.get("/")
async def root():
    return {"message": "Tattoo Stencil API", "version": "1.0"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "tattoo-stencil-api"}

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
    """Generate stencil with Google Gemini 2.5 Flash Image (Nano Banana) - FAST model"""
    import google.generativeai as genai
    
    # Configure with user's Google API key
    genai.configure(api_key=AI_API_KEY)
    
    # Use Gemini 2.5 Flash Image (Nano Banana) - much faster than gemini-3-pro-image-preview
    # This model is optimized for fast, high-quality image generation
    model = genai.GenerativeModel('gemini-2.5-flash-image')
    
    # Decode the base64 image
    if ',' in image_data:
        image_data = image_data.split(',')[1]
    
    image_bytes = base64.b64decode(image_data)
    
    # Generate with the fast model
    response = model.generate_content([
        prompt,
        {"mime_type": "image/png", "data": image_bytes}
    ])
    
    # Extract the generated image
    if response.candidates and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                # Got image data
                image_base64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                mime_type = part.inline_data.mime_type or 'image/png'
                return image_base64, mime_type
    
    raise Exception("Gemini did not return any images")

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
        line_color = color_map.get(request.line_color, "black")
        
        # Determine shading level - if regenerate_style is set, use that specific style
        if request.regenerate_style:
            # Map regenerate_style to shading_level
            style_to_shading = {
                "light": "minimal",
                "medium": "light", 
                "heavy": "moderate"
            }
            shading_level = style_to_shading.get(request.regenerate_style.lower(), "light")
            logger.info(f"Regenerating single style: {request.regenerate_style} (shading: {shading_level})")
        else:
            # Use shading_detail from request
            shading_level = "minimal" if request.shading_detail < 20 else "light" if request.shading_detail < 40 else "moderate" if request.shading_detail < 60 else "heavy"
        
        fill_level = "none" if request.solid_fill < 15 else "minimal" if request.solid_fill < 40 else "moderate"
        
        # Create the prompt - THERMAFAX COMPATIBLE STENCIL
        prompt = f"""PROFESSIONAL TATTOO STENCIL - THERMAFAX MACHINE COMPATIBLE

You are creating a tattoo stencil that MUST work with a Thermafax thermal transfer machine.

🚨 CRITICAL THERMAFAX REQUIREMENTS:
- ONLY pure BLACK lines on pure WHITE background
- ZERO gradients, ZERO soft shading, ZERO gray tones
- Every mark must be a DISTINCT BLACK LINE
- NO airbrushed effects, NO blending, NO tonal variations
- If it's not a clean black line, DON'T include it

⚠️ WHAT WILL FAIL ON THERMAFAX (DO NOT DO):
- ❌ Soft shading or gradients (will blur/smear)
- ❌ Gray tones or semi-transparent areas (won't transfer)
- ❌ Blended edges or feathered lines (will blob together)
- ❌ Stippling that's too dense (becomes solid blob)
- ❌ Any "drawing-like" or "artistic" shading

✅ WHAT WORKS ON THERMAFAX (DO THIS):
- ✅ Clean, crisp black lines
- ✅ Hatching (parallel lines) for shadow indication
- ✅ Cross-hatching (crossed lines) for darker areas
- ✅ Clear spacing between all lines
- ✅ Pure white space between line work

🖼️ ALIGNMENT (CRITICAL):
- Output MUST be EXACT SAME dimensions as input
- Subject position MUST match EXACTLY
- DO NOT crop, zoom, or shift the composition

🎨 DETAIL LEVEL: {shading_level.upper()}

{
'''LOW FIDELITY - CLEAN OUTLINES / THE BONES:
- PURE LINE ART - NO shading, NO gradients, NO gray tones
- Only CLEAN BLACK LINES on WHITE background
- Single-weight outline strokes tracing every contour
- Hair: Simple outline of the overall shape, major strand groupings
- Face: Clean contour lines only - no internal detail shading
- Background elements: Simple outlines only
- Think: Basic line tracing that will transfer PERFECTLY on Thermafax
- MUST BE: Pure black lines, pure white space - NOTHING in between''' if shading_level == "minimal" else

'''MID-RANGE - FORM & SHAPE / MUSCLE & MEAT:
- CLEAN BLACK LINES - NO soft shading, NO gradients, NO gray
- Add MORE LINES to show form (not shading darkness)
- Use HATCHING (parallel lines) to indicate shadow areas:
  * Lines should be SEPARATE and DISTINCT - not blended
  * Spacing between hatch lines indicates shadow depth
- Hair: More individual strand lines showing flow direction
- Face: Contour lines + sparse hatching for depth
- ALL shading must be LINES, not tonal gradients
- Thermafax-ready: Every mark is a clean black line''' if shading_level == "light" else

'''HIGH DEF - FULL SHADING / FULLY SATURATED:
- MAXIMUM LINE DENSITY - still NO soft shading or gradients
- Heavy use of HATCHING and CROSS-HATCHING (line patterns only):
  * Single direction hatching (///) for lighter shadows
  * Cross-hatching (XXX) for darker areas
  * Denser line spacing = darker area, NOT gray fill
- Hair: Many individual strand lines with full flow detail
- Face: Rich linework showing all contours and forms
- Background: Complete detail with line-based texture
- CRITICAL: Even "full shading" means MORE LINES, not gray tones
- Must transfer cleanly on Thermafax - all marks are distinct lines
- Think: Detailed engraving style - dense linework, zero gradients'''
}

📋 FINAL CHECKLIST:
□ Are ALL details captured? (hair, jewelry, background, textures)
□ Are lines FINE and DELICATE (not thick/bold)?
□ Is the composition IDENTICAL to reference? (no cropping/shifting)
□ Is contrast HIGH? (pure black on pure white)
□ Would this capture the FULL richness of the reference image?
□ Does it look like professional Stencil AI output?

Generate the stencil now with FINE LINES and COMPLETE DETAIL CAPTURE."""

        
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
        
        # CRITICAL: Resize the generated stencil to match the original image dimensions
        # This ensures perfect alignment in the edit mode overlay
        try:
            # Get original image dimensions from the input
            original_img_data = base64.b64decode(image_data)
            original_img = Image.open(BytesIO(original_img_data))
            original_width, original_height = original_img.size
            logger.info(f"Original image dimensions: {original_width}x{original_height}")
            
            # Decode the generated stencil
            stencil_img_data = base64.b64decode(image_base64)
            stencil_img = Image.open(BytesIO(stencil_img_data))
            stencil_width, stencil_height = stencil_img.size
            logger.info(f"Generated stencil dimensions: {stencil_width}x{stencil_height}")
            
            # Resize stencil to match original if dimensions differ
            if stencil_width != original_width or stencil_height != original_height:
                logger.info(f"Resizing stencil from {stencil_width}x{stencil_height} to {original_width}x{original_height}")
                stencil_img = stencil_img.resize((original_width, original_height), Image.Resampling.LANCZOS)
                
                # Convert back to base64
                buffer = BytesIO()
                stencil_img.save(buffer, format='PNG')
                image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                mime_type = 'image/png'
                logger.info("Stencil resized successfully for alignment")
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
        
        # Determine shading level
        if shading_detail <= 10:
            shading_level = "minimal"
        elif shading_detail <= 35:
            shading_level = "light"
        else:
            shading_level = "moderate"
        
        # Create the detailed prompt - THERMAFAX COMPATIBLE STENCIL
        prompt = f"""PROFESSIONAL TATTOO STENCIL - THERMAFAX MACHINE COMPATIBLE

You are creating a tattoo stencil that MUST work with a Thermafax thermal transfer machine.

🚨 CRITICAL THERMAFAX REQUIREMENTS:
- ONLY pure BLACK lines on pure WHITE background
- ZERO gradients, ZERO soft shading, ZERO gray tones
- Every mark must be a DISTINCT BLACK LINE
- NO airbrushed effects, NO blending, NO tonal variations
- If it's not a clean black line, DON'T include it

⚠️ WHAT WILL FAIL ON THERMAFAX (DO NOT DO):
- ❌ Soft shading or gradients (will blur/smear)
- ❌ Gray tones or semi-transparent areas (won't transfer)
- ❌ Blended edges or feathered lines (will blob together)
- ❌ Stippling that's too dense (becomes solid blob)
- ❌ Any "drawing-like" or "artistic" shading

✅ WHAT WORKS ON THERMAFAX (DO THIS):
- ✅ Clean, crisp black lines
- ✅ Hatching (parallel lines) for shadow indication
- ✅ Cross-hatching (crossed lines) for darker areas
- ✅ Clear spacing between all lines
- ✅ Pure white space between line work

🖼️ ALIGNMENT (CRITICAL):
- Output MUST be EXACT SAME dimensions as input
- Subject position MUST match EXACTLY
- DO NOT crop, zoom, or shift the composition

🎨 DETAIL LEVEL: {shading_level.upper()}

{
'''LOW FIDELITY - CLEAN OUTLINES / THE BONES:
- PURE LINE ART - NO shading, NO gradients, NO gray tones
- Only CLEAN BLACK LINES on WHITE background
- Single-weight outline strokes tracing every contour
- Hair: Simple outline of the overall shape, major strand groupings
- Face: Clean contour lines only - no internal detail shading
- Background elements: Simple outlines only
- Think: Basic line tracing that will transfer PERFECTLY on Thermafax
- MUST BE: Pure black lines, pure white space - NOTHING in between''' if shading_level == "minimal" else

'''MID-RANGE - FORM & SHAPE / MUSCLE & MEAT:
- CLEAN BLACK LINES - NO soft shading, NO gradients, NO gray
- Add MORE LINES to show form (not shading darkness)
- Use HATCHING (parallel lines) to indicate shadow areas:
  * Lines should be SEPARATE and DISTINCT - not blended
  * Spacing between hatch lines indicates shadow depth
- Hair: More individual strand lines showing flow direction
- Face: Contour lines + sparse hatching for depth
- ALL shading must be LINES, not tonal gradients
- Thermafax-ready: Every mark is a clean black line''' if shading_level == "light" else

'''HIGH DEF - FULL SHADING / FULLY SATURATED:
- MAXIMUM LINE DENSITY - still NO soft shading or gradients
- Heavy use of HATCHING and CROSS-HATCHING (line patterns only):
  * Single direction hatching (///) for lighter shadows
  * Cross-hatching (XXX) for darker areas
  * Denser line spacing = darker area, NOT gray fill
- Hair: Many individual strand lines with full flow detail
- Face: Rich linework showing all contours and forms
- Background: Complete detail with line-based texture
- CRITICAL: Even "full shading" means MORE LINES, not gray tones
- Must transfer cleanly on Thermafax - all marks are distinct lines
- Think: Detailed engraving style - dense linework, zero gradients'''
}

📋 FINAL CHECKLIST:
□ Are ALL details captured? (hair, jewelry, background, textures)
□ Are lines FINE and DELICATE (not thick/bold)?
□ Is the composition IDENTICAL to reference? (no cropping/shifting)
□ Is contrast HIGH? (pure black on pure white)
□ Would this capture the FULL richness of the reference image?
□ Does it look like professional Stencil AI output?

Generate the stencil now with FINE LINES and COMPLETE DETAIL CAPTURE."""

        # Generate using Gemini
        result_base64, mime_type = await generate_with_gemini(image_data, prompt)
        
        if result_base64:
            # Resize to match original dimensions
            try:
                original_img_data = base64.b64decode(image_data)
                original_img = Image.open(BytesIO(original_img_data))
                original_width, original_height = original_img.size
                
                stencil_img_data = base64.b64decode(result_base64)
                stencil_img = Image.open(BytesIO(stencil_img_data))
                
                if stencil_img.size != (original_width, original_height):
                    stencil_img = stencil_img.resize((original_width, original_height), Image.Resampling.LANCZOS)
                    buffer = BytesIO()
                    stencil_img.save(buffer, format='PNG')
                    result_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    mime_type = 'image/png'
            except Exception as resize_err:
                logger.warning(f"[AsyncJob {job.job_id}] Resize warning: {resize_err}")
            
            job.result[style] = f"data:{mime_type};base64,{result_base64}"
            logger.info(f"[AsyncJob {job.job_id}] {style} version completed")
            return True
        else:
            logger.error(f"[AsyncJob {job.job_id}] {style} version failed - no result")
            return False
            
    except Exception as e:
        logger.error(f"[AsyncJob {job.job_id}] {style} version error: {str(e)}")
        return False

async def process_stencil_job(job_id: str):
    """Background task to process all 3 stencil versions"""
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
                enhanced = await enhance_photo_with_ai(job.image_base64)
                job.enhanced_image = enhanced
                logger.info(f"[AsyncJob {job_id}] AI enhancement complete")
            except Exception as e:
                logger.warning(f"[AsyncJob {job_id}] AI enhancement failed, using basic: {str(e)}")
                job.enhanced_image = enhance_photo_basic(job.image_base64)
        else:
            # Use basic enhancement only
            job.enhanced_image = enhance_photo_basic(job.image_base64)
        
        job.status = "processing"
        logger.info(f"[AsyncJob {job_id}] Starting stencil generation...")
        
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
