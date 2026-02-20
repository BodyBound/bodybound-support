import cv2
import numpy as np
import base64
from io import BytesIO
from PIL import Image
import urllib.request

# Download a sample portrait image
print("Downloading sample image...")
url = "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=800"
urllib.request.urlretrieve(url, "/tmp/sample_portrait.jpg")

# Load the image
img = cv2.imread("/tmp/sample_portrait.jpg")
print(f"Image loaded: {img.shape}")

# Convert to grayscale
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

# ===== METHOD 1: Clean Canny Edge Detection =====
# Bilateral filter to smooth while keeping edges
smooth = cv2.bilateralFilter(gray, 9, 75, 75)

# Canny edge detection
edges_canny = cv2.Canny(smooth, 30, 100)

# Dilate slightly to make lines more visible
kernel = np.ones((2,2), np.uint8)
edges_canny = cv2.dilate(edges_canny, kernel, iterations=1)

# Invert for white background
canny_result = cv2.bitwise_not(edges_canny)

# ===== METHOD 2: Adaptive Threshold (pencil sketch look) =====
# More aggressive smoothing
smooth2 = cv2.bilateralFilter(gray, 9, 100, 100)

# Adaptive threshold
adaptive = cv2.adaptiveThreshold(smooth2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                  cv2.THRESH_BINARY, 11, 2)

# ===== METHOD 3: Pencil Sketch Style =====
# Invert the image
inv = 255 - gray
# Gaussian blur
blur = cv2.GaussianBlur(inv, (21, 21), 0)
# Blend
sketch = cv2.divide(gray, 255 - blur, scale=256)

# ===== METHOD 4: Combined Clean Approach =====
# Start with denoising
denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
# Light bilateral
bilateral = cv2.bilateralFilter(denoised, 5, 50, 50)
# Canny with tuned parameters
edges_clean = cv2.Canny(bilateral, 50, 150)
# Slight dilation
edges_clean = cv2.dilate(edges_clean, kernel, iterations=1)
# Invert
clean_result = cv2.bitwise_not(edges_clean)

# Save all results
cv2.imwrite("/tmp/stencil_method1_canny.png", canny_result)
cv2.imwrite("/tmp/stencil_method2_adaptive.png", adaptive)
cv2.imwrite("/tmp/stencil_method3_sketch.png", sketch)
cv2.imwrite("/tmp/stencil_method4_clean.png", clean_result)

print("Generated 4 stencil samples:")
print("1. /tmp/stencil_method1_canny.png - Canny edge detection")
print("2. /tmp/stencil_method2_adaptive.png - Adaptive threshold")
print("3. /tmp/stencil_method3_sketch.png - Pencil sketch style")
print("4. /tmp/stencil_method4_clean.png - Clean combined approach")
print("\nDone!")
