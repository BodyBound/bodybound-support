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
    """Try to generate stencil with Google Gemini"""
    chat = LlmChat(
        api_key=AI_API_KEY, 
        session_id=f"stencil-{uuid.uuid4()}", 
        system_message="You are an expert tattoo stencil artist. You create clean, professional tattoo stencils from reference images."
    )
    chat.with_model("gemini", "gemini-3-pro-image-preview").with_params(modalities=["image", "text"])
    
    msg = UserMessage(
        text=prompt,
        file_contents=[ImageContent(image_data)]
    )
    
    text_response, images = await chat.send_message_multimodal_response(msg)
    
    if not images or len(images) == 0:
        raise Exception("Gemini did not return any images")
    
    generated_image = images[0]
    
    if isinstance(generated_image, dict):
        image_base64 = generated_image.get('data') or generated_image.get('b64_json') or generated_image.get('base64')
        mime_type = generated_image.get('mime_type', 'image/png')
    elif isinstance(generated_image, str):
        image_base64 = generated_image
        mime_type = 'image/png'
    else:
        raise Exception(f"Unexpected image format: {type(generated_image)}")
    
    if not image_base64:
        raise Exception("Gemini returned empty image data")
    
    return image_base64, mime_type

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
        
        # Extract base64 data (remove data URL prefix if present)
        image_data = resized_image
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
        prompt = f"""PROFESSIONAL TATTOO STENCIL TRACE

You are creating a tattoo stencil for professional tattoo artists. PRECISION IS CRITICAL.

⚠️ CRITICAL - IMAGE ORIENTATION:
- If the reference photo is VERTICAL (portrait), output MUST be VERTICAL
- If the reference photo is HORIZONTAL (landscape), output MUST be HORIZONTAL
- NEVER rotate or change the orientation of the image
- The output dimensions should match the input dimensions

STEP 1: ANALYZE THE REFERENCE PHOTO
Look at every detail in the attached image:
- Face shape, jawline, cheekbones
- Eye shape, position, and spacing
- Nose shape and angle
- Lip shape and expression
- Hair outline and flow
- ANY unique features: horns, makeup, tattoos, accessories, piercings, jewelry
- Pose and angle of the subject
- IMAGE ORIENTATION (vertical or horizontal)

STEP 2: TRACE WITH EXACT PRECISION
Create a line drawing that traces the reference EXACTLY:
- Same proportions - if the nose is long, draw it long
- Same positions - if eyes are wide-set, draw them wide-set  
- Same angle - if face is turned 3/4, draw it at 3/4
- SAME ORIENTATION - vertical stays vertical, horizontal stays horizontal
- ALL unique elements MUST appear in the stencil exactly as shown

STEP 3: OUTPUT SPECIFICATIONS
- Pure white background (#FFFFFF)
- Black lines only (#000000)
- NO color, NO gray, NO fills, NO gradients
- Clean confident strokes suitable for thermal transfer paper
- MAINTAIN ORIGINAL IMAGE ORIENTATION

STEP 4: APPLY DETAIL LEVEL - {shading_level.upper()}

{
'''LIGHT VERSION:
- SIMPLE CLEAN OUTLINES ONLY
- Trace the outer edge of every shape (face, hair, features, accessories)
- Clean single-weight lines defining each form
- NO internal shading lines
- NO dots or dashes
- NO texture marks
- Think: A clean coloring book outline that captures the exact likeness''' if shading_level == "minimal" else

'''MEDIUM VERSION:
- SIMPLE OUTLINES + DOTTED REFERENCE LINES
- Start with the same clean outlines as Light version
- ADD dotted lines (......) or dashed lines (------) to show:
  * Where shadows fall (under cheekbones, under nose, around eye sockets)
  * Contour lines showing the 3D form of the face
  * Guide marks for shading placement
- These dotted lines help the tattoo artist know where to shade
- Keep dots/dashes subtle - they are REFERENCE guides, not heavy marks''' if shading_level == "light" else

'''HEAVY VERSION:
- SIMPLE OUTLINES + CONTOUR LINES + EXTRA DETAIL
- Start with the same clean outlines as Light version
- ADD solid contour lines (not just dots) showing form and depth
- ADD extra detail lines for:
  * Hair texture and flow direction
  * Clothing folds or fabric texture
  * Skin contours and muscle definition
- More line work than Medium, but still clean and purposeful
- Every line should serve the tattoo artist's needs'''
}

FINAL VERIFICATION:
✓ Would a tattoo artist recognize THIS EXACT PERSON from the stencil?
✓ Are the proportions IDENTICAL to the reference photo?
✓ Are ALL unique features (horns, makeup, jewelry, etc.) accurately traced?
✓ Is the detail level correct for {shading_level.upper()}?
✓ Is it purely black lines on white - no colors or gray?

Generate the stencil now. This is for professional use - precision matters."""

        
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

# PSD Export for Procreate - Layered file with original + stencil
class ExportPSDRequest(BaseModel):
    original_image: str  # base64 encoded original photo
    stencil_image: str   # base64 encoded stencil (transparent bg)

@api_router.post("/export-psd")
async def export_psd(request: ExportPSDRequest):
    """Generate a layered PSD file with original photo and stencil on separate layers.
    
    The PSD file will have:
    - Layer 1 (bottom): Original reference photo
    - Layer 2 (top): Stencil with transparent background
    
    This allows tattoo artists to easily align stencils in Procreate.
    """
    try:
        import time
        start_time = time.time()
        
        logger.info("[ExportPSD] Starting PSD generation...")
        
        # Decode the original image
        original_data = request.original_image
        if ',' in original_data:
            original_data = original_data.split(',')[1]
        original_bytes = base64.b64decode(original_data)
        original_img = Image.open(BytesIO(original_bytes))
        
        # Decode the stencil image
        stencil_data = request.stencil_image
        if ',' in stencil_data:
            stencil_data = stencil_data.split(',')[1]
        stencil_bytes = base64.b64decode(stencil_data)
        stencil_img = Image.open(BytesIO(stencil_bytes))
        
        logger.info(f"[ExportPSD] Original size: {original_img.size}, Stencil size: {stencil_img.size}")
        
        # Ensure both images are the same size - resize stencil to match original
        if stencil_img.size != original_img.size:
            stencil_img = stencil_img.resize(original_img.size, Image.Resampling.LANCZOS)
            logger.info(f"[ExportPSD] Resized stencil to: {stencil_img.size}")
        
        # Convert original to RGBA if needed
        if original_img.mode != 'RGBA':
            original_img = original_img.convert('RGBA')
        
        # Convert stencil to RGBA with transparent background
        # The stencil should have white background -> transparent, black lines stay
        if stencil_img.mode != 'RGBA':
            stencil_img = stencil_img.convert('RGBA')
        
        # Make white/near-white pixels transparent in stencil
        stencil_data_array = np.array(stencil_img)
        # Check if pixel is white or near-white (R>240, G>240, B>240)
        white_mask = (stencil_data_array[:,:,0] > 240) & (stencil_data_array[:,:,1] > 240) & (stencil_data_array[:,:,2] > 240)
        stencil_data_array[white_mask, 3] = 0  # Set alpha to 0 for white pixels
        stencil_img = Image.fromarray(stencil_data_array)
        
        logger.info("[ExportPSD] Images prepared, creating PSD...")
        
        # Create PSD file using psd-tools
        # psd-tools can create PSD files from scratch
        try:
            from psd_tools import PSDImage
            from psd_tools.api.layers import PixelLayer
            from psd_tools.constants import ColorMode, Compression
            
            # psd-tools approach: compose layers
            width, height = original_img.size
            
            # Create a composite image (what the PSD looks like when flattened)
            composite = Image.alpha_composite(original_img, stencil_img)
            
            # Unfortunately, psd-tools primarily reads PSD files and has limited write support
            # We'll use a manual PSD builder approach instead
            raise ImportError("Using manual PSD builder for better layer support")
            
        except ImportError:
            # Manual PSD file creation - this is more reliable for our use case
            logger.info("[ExportPSD] Using manual PSD builder...")
            
            psd_buffer = BytesIO()
            width, height = original_img.size
            
            # PSD File Format:
            # 1. Header
            # 2. Color Mode Data
            # 3. Image Resources
            # 4. Layer and Mask Information
            # 5. Image Data (composite)
            
            # Convert images to raw RGBA data
            original_rgba = original_img.tobytes()
            stencil_rgba = stencil_img.tobytes()
            composite = Image.alpha_composite(original_img, stencil_img)
            composite_rgba = composite.tobytes()
            
            def write_psd_string(s):
                """Write a Pascal string (length-prefixed)"""
                encoded = s.encode('utf-8')
                # Pad to even length
                padded_len = len(encoded) + 1  # +1 for length byte
                if padded_len % 2 != 0:
                    return bytes([len(encoded)]) + encoded + b'\x00'
                return bytes([len(encoded)]) + encoded
            
            def compress_channel(data, width, height):
                """RLE compress a single channel"""
                # For simplicity, use raw compression (mode 0)
                return data
            
            # ===== 1. FILE HEADER =====
            psd_buffer.write(b'8BPS')  # Signature
            psd_buffer.write(struct.pack('>H', 1))  # Version
            psd_buffer.write(b'\x00' * 6)  # Reserved
            psd_buffer.write(struct.pack('>H', 4))  # Channels (RGBA)
            psd_buffer.write(struct.pack('>I', height))  # Height
            psd_buffer.write(struct.pack('>I', width))  # Width
            psd_buffer.write(struct.pack('>H', 8))  # Depth (8 bits)
            psd_buffer.write(struct.pack('>H', 3))  # Color mode (3 = RGB)
            
            # ===== 2. COLOR MODE DATA =====
            psd_buffer.write(struct.pack('>I', 0))  # Length = 0 for RGB
            
            # ===== 3. IMAGE RESOURCES =====
            psd_buffer.write(struct.pack('>I', 0))  # Length = 0 (no resources)
            
            # ===== 4. LAYER AND MASK INFORMATION =====
            layer_section = BytesIO()
            
            # Layer info structure
            layer_info = BytesIO()
            
            # Layer count (negative for merged result with alpha)
            layer_info.write(struct.pack('>h', 2))  # 2 layers
            
            def write_layer_record(buf, name, img_data, width, height, is_bottom=False):
                """Write a layer record"""
                # Layer bounds (top, left, bottom, right)
                buf.write(struct.pack('>i', 0))  # top
                buf.write(struct.pack('>i', 0))  # left
                buf.write(struct.pack('>i', height))  # bottom
                buf.write(struct.pack('>i', width))  # right
                
                # Number of channels
                buf.write(struct.pack('>H', 4))  # RGBA = 4 channels
                
                # Channel info for each channel
                # Channel ID: -1=transparency, 0=red, 1=green, 2=blue
                channel_data_len = width * height + 2  # +2 for compression type
                buf.write(struct.pack('>h', -1))  # Alpha channel
                buf.write(struct.pack('>I', channel_data_len))
                buf.write(struct.pack('>h', 0))   # Red
                buf.write(struct.pack('>I', channel_data_len))
                buf.write(struct.pack('>h', 1))   # Green
                buf.write(struct.pack('>I', channel_data_len))
                buf.write(struct.pack('>h', 2))   # Blue
                buf.write(struct.pack('>I', channel_data_len))
                
                # Blend mode signature
                buf.write(b'8BIM')
                buf.write(b'norm')  # Normal blend mode
                
                # Opacity (0-255)
                buf.write(struct.pack('B', 255))
                
                # Clipping
                buf.write(struct.pack('B', 0))
                
                # Flags
                buf.write(struct.pack('B', 8))  # 8 = visible
                
                # Filler
                buf.write(b'\x00')
                
                # Extra data length
                extra_data = BytesIO()
                
                # Layer mask data (empty)
                extra_data.write(struct.pack('>I', 0))
                
                # Layer blending ranges (empty)
                extra_data.write(struct.pack('>I', 0))
                
                # Layer name (Pascal string, padded to 4 bytes)
                name_bytes = name.encode('utf-8')
                name_len = len(name_bytes)
                padded_name = bytes([name_len]) + name_bytes
                while len(padded_name) % 4 != 0:
                    padded_name += b'\x00'
                extra_data.write(padded_name)
                
                extra_data_bytes = extra_data.getvalue()
                buf.write(struct.pack('>I', len(extra_data_bytes)))
                buf.write(extra_data_bytes)
            
            # Write layer records
            write_layer_record(layer_info, "Original Photo", original_rgba, width, height, is_bottom=True)
            write_layer_record(layer_info, "Stencil", stencil_rgba, width, height, is_bottom=False)
            
            # Write channel image data for each layer
            def write_channel_data(buf, img_data, width, height):
                """Write raw channel data for a layer"""
                # Split into channels (RGBA order in the bytes)
                pixels = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width, 4))
                
                for channel_idx in [3, 0, 1, 2]:  # Alpha, R, G, B order in PSD
                    # Compression type: 0 = Raw
                    buf.write(struct.pack('>H', 0))
                    # Write raw channel data
                    channel = pixels[:, :, channel_idx].tobytes()
                    buf.write(channel)
            
            write_channel_data(layer_info, original_rgba, width, height)
            write_channel_data(layer_info, stencil_rgba, width, height)
            
            # Write layer info to layer section
            layer_info_bytes = layer_info.getvalue()
            # Round up to even
            if len(layer_info_bytes) % 2 != 0:
                layer_info_bytes += b'\x00'
            
            layer_section.write(struct.pack('>I', len(layer_info_bytes)))
            layer_section.write(layer_info_bytes)
            
            # Global layer mask info (empty)
            layer_section.write(struct.pack('>I', 0))
            
            # Write layer section to main buffer
            layer_section_bytes = layer_section.getvalue()
            psd_buffer.write(struct.pack('>I', len(layer_section_bytes)))
            psd_buffer.write(layer_section_bytes)
            
            # ===== 5. IMAGE DATA (Composite) =====
            # Compression type: 0 = Raw
            psd_buffer.write(struct.pack('>H', 0))
            
            # Write composite image channels (R, G, B, A)
            comp_pixels = np.frombuffer(composite_rgba, dtype=np.uint8).reshape((height, width, 4))
            for channel_idx in [0, 1, 2, 3]:  # R, G, B, A
                channel = comp_pixels[:, :, channel_idx].tobytes()
                psd_buffer.write(channel)
            
            logger.info("[ExportPSD] PSD file built successfully")
        
        processing_time = (time.time() - start_time) * 1000
        logger.info(f"[ExportPSD] Generated PSD in {processing_time:.2f}ms")
        
        # Return the PSD file
        psd_buffer.seek(0)
        
        return StreamingResponse(
            psd_buffer,
            media_type="application/x-photoshop",
            headers={
                "Content-Disposition": f"attachment; filename=body_bound_stencil_{int(time.time())}.psd"
            }
        )
        
    except Exception as e:
        logger.error(f"[ExportPSD] Error generating PSD: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating PSD file: {str(e)}")


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
