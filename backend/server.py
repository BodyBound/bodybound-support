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
    def __init__(self, job_id: str, image_base64: str, settings: dict):
        self.job_id = job_id
        self.image_base64 = image_base64
        self.settings = settings
        self.status = "pending"  # pending, processing, completed, failed
        self.progress = 0  # 0-100
        self.current_style = None  # light, medium, heavy
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

def enhance_photo_for_ai(base64_string: str) -> str:
    """Automatically enhance photo before AI processing for better stencil results.
    
    This preprocessing step helps the AI capture finer details by:
    1. Boosting contrast to make edges more defined
    2. Applying sharpening to bring out fine details (hair, jewelry, subtle features)
    3. Using CLAHE for adaptive local contrast enhancement
    4. Subtle edge enhancement to make contours more visible
    
    Args:
        base64_string: The original base64 encoded image
        
    Returns:
        Base64 encoded enhanced image ready for AI processing
    """
    try:
        logger.info("[PhotoEnhance] Starting automatic photo enhancement...")
        
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
        # Convert to LAB color space for better contrast manipulation
        lab = cv2.cvtColor(img_cv, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        
        # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) to L channel
        # This enhances local contrast without over-amplifying noise
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        l_enhanced = clahe.apply(l_channel)
        
        # Merge back and convert to BGR
        lab_enhanced = cv2.merge([l_enhanced, a_channel, b_channel])
        img_contrast = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
        
        # === STEP 2: SHARPENING (Unsharp Mask) ===
        # This brings out fine details like hair strands, jewelry, facial features
        gaussian = cv2.GaussianBlur(img_contrast, (0, 0), 2.0)
        # Unsharp mask: original + (original - blurred) * amount
        sharpening_amount = 0.7  # Moderate sharpening
        img_sharp = cv2.addWeighted(img_contrast, 1 + sharpening_amount, gaussian, -sharpening_amount, 0)
        
        # === STEP 3: SUBTLE EDGE ENHANCEMENT ===
        # Enhance edges slightly to help AI detect contours better
        # Using a subtle Laplacian edge enhancement
        gray = cv2.cvtColor(img_sharp, cv2.COLOR_BGR2GRAY)
        edges = cv2.Laplacian(gray, cv2.CV_64F)
        edges = np.uint8(np.absolute(edges))
        
        # Create a subtle edge overlay (very light - just to boost existing edges)
        edges_3channel = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        edge_boost = 0.08  # Very subtle - we don't want visible halos
        img_edge_enhanced = cv2.addWeighted(img_sharp, 1.0, edges_3channel, edge_boost, 0)
        
        # === STEP 4: FINAL CONTRAST BOOST ===
        # Slight additional contrast to make darks darker, lights lighter
        # This helps the AI distinguish features more clearly
        alpha = 1.15  # Contrast boost (1.0 = no change)
        beta = -10    # Brightness adjustment (negative = slightly darker midtones)
        img_final = cv2.convertScaleAbs(img_edge_enhanced, alpha=alpha, beta=beta)
        
        # Ensure we don't clip too much - keep details in highlights and shadows
        img_final = np.clip(img_final, 0, 255).astype(np.uint8)
        
        # Convert back to PIL and then to base64
        img_final_rgb = cv2.cvtColor(img_final, cv2.COLOR_BGR2RGB)
        result_img = Image.fromarray(img_final_rgb)
        
        # Save as high-quality JPEG
        buffer = BytesIO()
        result_img.save(buffer, format='JPEG', quality=95, optimize=True)
        enhanced_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        logger.info(f"[PhotoEnhance] Enhancement complete - contrast boosted, sharpened, edges enhanced")
        
        return f"data:image/jpeg;base64,{enhanced_base64}"
        
    except Exception as e:
        logger.error(f"[PhotoEnhance] Error enhancing photo: {str(e)}")
        import traceback
        traceback.print_exc()
        # Return original if enhancement fails
        return base64_string

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
    """
    try:
        import time
        start_time = time.time()
        
        if not EMERGENT_LLM_KEY and not AI_API_KEY:
            raise HTTPException(status_code=500, detail="AI API key not configured. Please check your internet connection and try again.")
        
        # Auto-resize image if too large to prevent AI failures
        resized_image = resize_image_if_needed(request.image_base64, max_dimension=2000, max_file_size_mb=4.0)
        
        # AUTOMATIC PHOTO ENHANCEMENT for better AI stencil results
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
        
        # Create the prompt for EXACT tracing - PROFESSIONAL TATTOO STENCILS
        # This is for real tattoo artists - precision is critical
        prompt = f"""PROFESSIONAL TATTOO STENCIL - EXACT STYLE REPLICATION

You are creating a tattoo stencil for professional tattoo artists. Your output MUST match this EXACT style:

🎨 MASTER STYLE REFERENCE (FOLLOW THIS EXACTLY):
- THICK, BOLD BLACK OUTLINES for all primary contours (face shape, jawline, nose profile, lips, hair outline, accessories)
- MEDIUM WEIGHT LINES for secondary features (ear structure, eye details, eyebrows)
- DASHED/DOTTED LINES for shading guides and form indication
- HIGH CONTRAST black lines on pure white - NO gray, NO faint lines
- Lines should be CONFIDENT and BOLD - not sketchy or light

🚨🚨🚨 CRITICAL: PIXEL-PERFECT ALIGNMENT 🚨🚨🚨
This stencil will be OVERLAID on the reference photo. ZERO misalignment allowed.

ALIGNMENT RULES (MANDATORY - READ CAREFULLY):
1. DO NOT shift subject left, right, up, or down - EXACT same position
2. DO NOT zoom in or zoom out - EXACT same scale  
3. DO NOT add margins or borders - edge-to-edge matching
4. The LEFT EYE center must be at EXACTLY the same (x,y) coordinates
5. The RIGHT EYE center must be at EXACTLY the same (x,y) coordinates
6. The NOSE TIP must be at EXACTLY the same (x,y) coordinates
7. The CHIN must be at EXACTLY the same (x,y) coordinates
8. The TOP OF HEAD must be the same distance from top edge
9. TRACE OVER the photo - do not redraw from memory or interpretation

⚠️ CANVAS & DIMENSIONS:
- Output MUST be the EXACT SAME pixel dimensions as input
- FILL the entire canvas - subject in SAME position
- If input has negative space, preserve it EXACTLY

📐 LINE WEIGHT SPECIFICATIONS:
- THICKEST LINES (3-4pt equivalent): Face outline, jawline, main hair outline, nose bridge/profile, lip outline, major accessory outlines
- MEDIUM LINES (2pt equivalent): Eye outlines, ear details, eyebrow shapes, secondary hair strands, jewelry
- THIN LINES (1pt equivalent): Dashed contour lines, shading guides, texture details

STEP 1: TRACE THE EXACT POSITIONS
Before drawing, mentally note:
- Exact distance from top edge to top of head
- Exact distance from bottom edge to chin
- Exact horizontal position of each eye
- Exact spacing on left and right sides
YOUR STENCIL MUST MATCH THESE EXACTLY.

STEP 2: DRAW WITH BOLD, CONFIDENT LINES
- Use THICK, DARK strokes - not light or sketchy
- Lines should be suitable for thermal transfer paper
- Every line should be clearly visible and professional

STEP 3: APPLY DETAIL LEVEL - {shading_level.upper()}

{
'''LIGHT VERSION - BOLD OUTLINES ONLY:
- THICK bold outlines for face shape, jawline, profile
- THICK bold outlines for hair silhouette and major strands
- THICK bold outlines for all accessories (feathers, jewelry, headwear)
- Clean defined eyes with bold eyeliner-style outlines
- Bold eyebrow shapes
- NO internal shading lines
- NO dots or dashes inside the face
- Just clean, bold outlines that define every shape
- Think: Bold coloring book style with STRONG line weight''' if shading_level == "minimal" else

'''MEDIUM VERSION - BOLD OUTLINES + DASHED SHADING GUIDES:
- Same THICK bold outlines as Light version for all shapes
- ADD DASHED LINES (- - - -) to indicate shadow placement:
  * Dashed contour under cheekbones following the bone structure
  * Dashed line under the nose indicating shadow
  * Dashed lines around eye sockets showing depth
  * Dashed lines on lips showing volume (horizontal dashes on lower lip)
- ADD DOTTED LINES (....) for subtle form indicators
- Hair should have internal line detail showing flow direction
- Feathers should have internal vein lines
- The dashed lines guide where the tattoo artist should shade
- This is the IDEAL balance of outline and shading reference''' if shading_level == "light" else

'''HEAVY VERSION - BOLD OUTLINES + DASHED LINES + CROSSHATCHING:
- Same THICK bold outlines as Light version
- Same DASHED shading guides as Medium version
- ADD CROSSHATCHING in the darkest shadow areas:
  * Fine diagonal parallel lines (///) under cheekbones
  * Crosshatch pattern in deep shadows (under nose, eye sockets)
  * Denser hatching = darker shadow, lighter hatching = softer shadow
- Add more texture detail in hair with parallel flow lines
- Add more detail in feathers with fine barb lines
- Keep crosshatching CONTROLLED and PROFESSIONAL
- The extra detail helps artist see exact shading intensity needed'''
}

FINAL CHECKS BEFORE OUTPUT:
- Are lines BOLD and THICK enough? (not light or sketchy)
- Is alignment PERFECT with reference? (overlay test would match)
- Is contrast HIGH? (pure black on pure white)
- Does it look like a PROFESSIONAL tattoo stencil?
- Would this transfer cleanly to skin?

Generate the stencil now. BOLD LINES + PERFECT ALIGNMENT are mandatory."""

        
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
        
        # Get image data and enhance it for better AI results
        raw_image = job.image_base64
        enhanced_image = enhance_photo_for_ai(raw_image)
        
        image_data = enhanced_image
        if ',' in image_data:
            image_data = image_data.split(',')[1]
        
        # Determine shading level
        if shading_detail <= 10:
            shading_level = "minimal"
        elif shading_detail <= 35:
            shading_level = "light"
        else:
            shading_level = "moderate"
        
        # Create the detailed prompt (same as synchronous version)
        prompt = f"""PROFESSIONAL TATTOO STENCIL - EXACT STYLE REPLICATION

You are creating a tattoo stencil for professional tattoo artists. Your output MUST match this EXACT style:

🎨 MASTER STYLE REFERENCE (FOLLOW THIS EXACTLY):
- THICK, BOLD BLACK OUTLINES for all primary contours (face shape, jawline, nose profile, lips, hair outline, accessories)
- MEDIUM WEIGHT LINES for secondary features (ear structure, eye details, eyebrows)
- DASHED/DOTTED LINES for shading guides and form indication
- HIGH CONTRAST black lines on pure white - NO gray, NO faint lines
- Lines should be CONFIDENT and BOLD - not sketchy or light

🚨🚨🚨 CRITICAL: PIXEL-PERFECT ALIGNMENT 🚨🚨🚨
This stencil will be OVERLAID on the reference photo. ZERO misalignment allowed.

ALIGNMENT RULES (MANDATORY - READ CAREFULLY):
1. DO NOT shift subject left, right, up, or down - EXACT same position
2. DO NOT zoom in or zoom out - EXACT same scale  
3. DO NOT add margins or borders - edge-to-edge matching
4. The LEFT EYE center must be at EXACTLY the same (x,y) coordinates
5. The RIGHT EYE center must be at EXACTLY the same (x,y) coordinates
6. The NOSE TIP must be at EXACTLY the same (x,y) coordinates
7. The CHIN must be at EXACTLY the same (x,y) coordinates
8. The TOP OF HEAD must be the same distance from top edge
9. TRACE OVER the photo - do not redraw from memory or interpretation

⚠️ CANVAS & DIMENSIONS:
- Output MUST be the EXACT SAME pixel dimensions as input
- FILL the entire canvas - subject in SAME position
- If input has negative space, preserve it EXACTLY

📐 LINE WEIGHT SPECIFICATIONS:
- THICKEST LINES (3-4pt equivalent): Face outline, jawline, main hair outline, nose bridge/profile, lip outline, major accessory outlines
- MEDIUM LINES (2pt equivalent): Eye outlines, ear details, eyebrow shapes, secondary hair strands, jewelry
- THIN LINES (1pt equivalent): Dashed contour lines, shading guides, texture details

STEP 1: TRACE THE EXACT POSITIONS
Before drawing, mentally note:
- Exact distance from top edge to top of head
- Exact distance from bottom edge to chin
- Exact horizontal position of each eye
- Exact spacing on left and right sides
YOUR STENCIL MUST MATCH THESE EXACTLY.

STEP 2: DRAW WITH BOLD, CONFIDENT LINES
- Use THICK, DARK strokes - not light or sketchy
- Lines should be suitable for thermal transfer paper
- Every line should be clearly visible and professional

STEP 3: APPLY DETAIL LEVEL - {shading_level.upper()}

{
'''LIGHT VERSION - BOLD OUTLINES ONLY:
- THICK bold outlines for face shape, jawline, profile
- THICK bold outlines for hair silhouette and major strands
- THICK bold outlines for all accessories (feathers, jewelry, headwear)
- Clean defined eyes with bold eyeliner-style outlines
- Bold eyebrow shapes
- NO internal shading lines
- NO dots or dashes inside the face
- Just clean, bold outlines that define every shape
- Think: Bold coloring book style with STRONG line weight''' if shading_level == "minimal" else

'''MEDIUM VERSION - BOLD OUTLINES + DASHED SHADING GUIDES:
- Same THICK bold outlines as Light version for all shapes
- ADD DASHED LINES (- - - -) to indicate shadow placement:
  * Dashed contour under cheekbones following the bone structure
  * Dashed line under the nose indicating shadow
  * Dashed lines around eye sockets showing depth
  * Dashed lines on lips showing volume (horizontal dashes on lower lip)
- ADD DOTTED LINES (....) for subtle form indicators
- Hair should have internal line detail showing flow direction
- Feathers should have internal vein lines
- The dashed lines guide where the tattoo artist should shade
- This is the IDEAL balance of outline and shading reference''' if shading_level == "light" else

'''HEAVY VERSION - BOLD OUTLINES + DASHED LINES + CROSSHATCHING:
- Same THICK bold outlines as Light version
- Same DASHED shading guides as Medium version
- ADD CROSSHATCHING in the darkest shadow areas:
  * Fine diagonal parallel lines (///) under cheekbones
  * Crosshatch pattern in deep shadows (under nose, eye sockets)
  * Denser hatching = darker shadow, lighter hatching = softer shadow
- Add more texture detail in hair with parallel flow lines
- Add more detail in feathers with fine barb lines
- Keep crosshatching CONTROLLED and PROFESSIONAL
- The extra detail helps artist see exact shading intensity needed'''
}

FINAL CHECKS BEFORE OUTPUT:
- Are lines BOLD and THICK enough? (not light or sketchy)
- Is alignment PERFECT with reference? (overlay test would match)
- Is contrast HIGH? (pure black on pure white)
- Does it look like a PROFESSIONAL tattoo stencil?
- Would this transfer cleanly to skin?

Generate the stencil now. BOLD LINES + PERFECT ALIGNMENT are mandatory."""

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
        job.status = "processing"
        logger.info(f"[AsyncJob {job_id}] Starting background generation...")
        
        # Generate Light version (progress 0-33%)
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
    """
    try:
        # Create job
        job_id = str(uuid.uuid4())
        job = StencilJob(
            job_id=job_id,
            image_base64=request.image_base64,
            settings={"line_color": request.line_color}
        )
        stencil_jobs[job_id] = job
        
        logger.info(f"[AsyncJob {job_id}] Job created, starting background processing...")
        
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
