from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File
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

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

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
    settings: StencilSettings
    created_at: datetime = Field(default_factory=datetime.utcnow)
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

def process_image_to_stencil(img: np.ndarray, settings: StencilSettings) -> np.ndarray:
    """Process image to create tattoo stencil using edge detection"""
    
    # Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Map settings to actual values
    # Noise reduction: higher = more blur (less noise)
    blur_kernel = int(3 + (settings.noise_reduction / 100) * 8)
    if blur_kernel % 2 == 0:
        blur_kernel += 1  # Must be odd
    
    # Apply bilateral filter for noise reduction while preserving edges
    denoised = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)
    
    # Apply Gaussian blur based on noise reduction setting
    blurred = cv2.GaussianBlur(denoised, (blur_kernel, blur_kernel), 0)
    
    # Clarity affects edge detection thresholds
    # Lower clarity = more edges, Higher clarity = fewer, cleaner edges
    low_threshold = int(30 + (settings.clarity / 100) * 70)
    high_threshold = int(low_threshold * 2.5)
    
    # Apply Canny edge detection
    edges = cv2.Canny(blurred, low_threshold, high_threshold)
    
    # Line weight affects dilation (thickening of lines)
    line_kernel_size = max(1, int(1 + (settings.line_weight / 100) * 4))
    if line_kernel_size > 1:
        kernel = np.ones((line_kernel_size, line_kernel_size), np.uint8)
        edges = cv2.dilate(edges, kernel, iterations=1)
    
    # Create output image (white background with black lines for tattoo stencil)
    if settings.invert:
        # White background, black lines (typical stencil look)
        stencil = 255 - edges
    else:
        # Black background, white lines
        stencil = edges
    
    # Convert to 3 channel for consistent output
    stencil_rgb = cv2.cvtColor(stencil, cv2.COLOR_GRAY2BGR)
    
    return stencil_rgb

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
        
        # Convert base64 to OpenCV image
        img = base64_to_cv2(request.image_base64)
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

@api_router.post("/stencils", response_model=SavedStencil)
async def save_stencil(request: SaveStencilRequest):
    """Save a stencil to the database"""
    try:
        stencil = SavedStencil(
            original_image=request.original_image,
            stencil_image=request.stencil_image,
            settings=request.settings,
            name=request.name
        )
        await db.stencils.insert_one(stencil.dict())
        return stencil
    except Exception as e:
        logger.error(f"Error saving stencil: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error saving stencil: {str(e)}")

@api_router.get("/stencils", response_model=List[SavedStencil])
async def get_stencils():
    """Get all saved stencils"""
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
