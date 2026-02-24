#!/usr/bin/env python3
"""
Backend API Testing for Tattoo Stencil App
Tests all backend endpoints with real data
"""

import requests
import base64
import json
import time
from PIL import Image, ImageDraw
import io
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv('/app/frontend/.env')

# Get backend URL from environment
BACKEND_URL = os.getenv('EXPO_PUBLIC_BACKEND_URL', 'http://localhost:8001')
API_BASE = f"{BACKEND_URL}/api"

print(f"Testing backend at: {API_BASE}")

def create_test_image():
    """Create a simple test image with some patterns for edge detection"""
    # Create a 200x200 image with some geometric shapes
    img = Image.new('RGB', (200, 200), color='white')
    draw = ImageDraw.Draw(img)
    
    # Draw some shapes that will create good edges
    draw.rectangle([50, 50, 150, 150], outline='black', width=3)
    draw.ellipse([75, 75, 125, 125], outline='black', width=2)
    draw.line([0, 0, 200, 200], fill='black', width=2)
    draw.line([200, 0, 0, 200], fill='black', width=2)
    
    # Convert to base64
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG')
    img_data = buffer.getvalue()
    base64_string = base64.b64encode(img_data).decode('utf-8')
    return f"data:image/jpeg;base64,{base64_string}"

def test_health_check():
    """Test the health check endpoint"""
    print("\n=== Testing Health Check ===")
    try:
        response = requests.get(f"{API_BASE}/health", timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'healthy':
                print("✅ Health check PASSED")
                return True
            else:
                print("❌ Health check FAILED - Invalid response format")
                return False
        else:
            print(f"❌ Health check FAILED - Status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Health check FAILED - Error: {str(e)}")
        return False

def test_image_processing():
    """Test the image processing endpoint"""
    print("\n=== Testing Image Processing ===")
    try:
        # Create test image
        test_image_b64 = create_test_image()
        
        # Test data
        payload = {
            "image_base64": test_image_b64,
            "settings": {
                "clarity": 50,
                "line_weight": 50,
                "noise_reduction": 50,
                "invert": True
            }
        }
        
        print("Sending image processing request...")
        response = requests.post(
            f"{API_BASE}/process", 
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Processing time: {data.get('processing_time_ms', 'N/A')} ms")
            
            # Check if we got a stencil back
            if 'stencil_base64' in data and data['stencil_base64']:
                stencil_data = data['stencil_base64']
                if stencil_data.startswith('data:image/'):
                    print("✅ Image processing PASSED - Got valid stencil image")
                    return True, stencil_data
                else:
                    print("❌ Image processing FAILED - Invalid stencil format")
                    return False, None
            else:
                print("❌ Image processing FAILED - No stencil in response")
                return False, None
        else:
            print(f"❌ Image processing FAILED - Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False, None
            
    except Exception as e:
        print(f"❌ Image processing FAILED - Error: {str(e)}")
        return False, None

def test_save_stencil(original_image, stencil_image):
    """Test saving a stencil"""
    print("\n=== Testing Save Stencil ===")
    try:
        payload = {
            "original_image": original_image,
            "stencil_image": stencil_image,
            "settings": {
                "clarity": 50,
                "line_weight": 50,
                "noise_reduction": 50,
                "invert": True
            },
            "name": "Test Stencil Design"
        }
        
        response = requests.post(
            f"{API_BASE}/stencils",
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=15
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Saved stencil ID: {data.get('id', 'N/A')}")
            print(f"Stencil name: {data.get('name', 'N/A')}")
            
            if 'id' in data and data['id']:
                print("✅ Save stencil PASSED")
                return True, data['id']
            else:
                print("❌ Save stencil FAILED - No ID returned")
                return False, None
        else:
            print(f"❌ Save stencil FAILED - Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False, None
            
    except Exception as e:
        print(f"❌ Save stencil FAILED - Error: {str(e)}")
        return False, None

def test_get_stencils():
    """Test getting all stencils"""
    print("\n=== Testing Get Stencils ===")
    try:
        response = requests.get(f"{API_BASE}/stencils", timeout=10)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Number of stencils: {len(data)}")
            
            if isinstance(data, list):
                if len(data) > 0:
                    print(f"First stencil ID: {data[0].get('id', 'N/A')}")
                    print(f"First stencil name: {data[0].get('name', 'N/A')}")
                print("✅ Get stencils PASSED")
                return True, data
            else:
                print("❌ Get stencils FAILED - Response is not a list")
                return False, None
        else:
            print(f"❌ Get stencils FAILED - Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False, None
            
    except Exception as e:
        print(f"❌ Get stencils FAILED - Error: {str(e)}")
        return False, None

def test_ai_stencil():
    """Test the AI stencil generation endpoint"""
    print("\n=== Testing AI Stencil Generation ===")
    try:
        # Create test image
        test_image_b64 = create_test_image()
        
        # Test data with the expected parameters
        payload = {
            "image_base64": test_image_b64,
            "shading_detail": 50,
            "solid_fill": 30,
            "line_color": "black"
        }
        
        print("Sending AI stencil generation request...")
        response = requests.post(
            f"{API_BASE}/ai-stencil", 
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=60  # AI processing might take longer
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Processing time: {data.get('processing_time_ms', 'N/A')} ms")
            
            # Check if we got a stencil back
            if 'stencil_base64' in data and data['stencil_base64']:
                stencil_data = data['stencil_base64']
                if stencil_data.startswith('data:image/'):
                    print("✅ AI stencil generation PASSED - Got valid AI-generated stencil")
                    return True, stencil_data
                else:
                    print("❌ AI stencil generation FAILED - Invalid stencil format")
                    return False, None
            else:
                print("❌ AI stencil generation FAILED - No stencil in response")
                return False, None
        elif response.status_code == 500:
            print(f"❌ AI stencil generation FAILED - Server error: {response.text}")
            # Check if it's an API key or quota issue
            response_text = response.text.lower()
            if 'api key' in response_text or 'key not configured' in response_text:
                print("🔑 Issue: AI API key not configured or invalid")
            elif 'quota' in response_text or 'limit' in response_text or 'budget' in response_text:
                print("💰 Issue: API quota/budget exceeded")
            elif 'timeout' in response_text:
                print("⏱️ Issue: AI processing timeout")
            return False, None
        else:
            print(f"❌ AI stencil generation FAILED - Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False, None
            
    except Exception as e:
        print(f"❌ AI stencil generation FAILED - Error: {str(e)}")
        return False, None

def test_delete_stencil(stencil_id):
    """Test deleting a stencil"""
    print("\n=== Testing Delete Stencil ===")
    try:
        response = requests.delete(f"{API_BASE}/stencils/{stencil_id}", timeout=10)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Response: {data}")
            
            if 'message' in data and 'deleted' in data['message'].lower():
                print("✅ Delete stencil PASSED")
                return True
            else:
                print("❌ Delete stencil FAILED - Unexpected response format")
                return False
        elif response.status_code == 404:
            print("❌ Delete stencil FAILED - Stencil not found (404)")
            return False
        else:
            print(f"❌ Delete stencil FAILED - Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Delete stencil FAILED - Error: {str(e)}")
        return False

def create_stencil_test_image():
    """Create a test stencil image with black lines on white background"""
    img = Image.new('RGB', (100, 100), (255, 255, 255))  # White background
    
    draw = ImageDraw.Draw(img)
    # Draw some black lines to simulate a stencil
    draw.line([(10, 10), (90, 90)], fill=(0, 0, 0), width=3)
    draw.line([(90, 10), (10, 90)], fill=(0, 0, 0), width=3)
    draw.rectangle([30, 30, 70, 70], outline=(0, 0, 0), width=2)
    
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{img_base64}"

def test_psd_export():
    """Test the new PSD export endpoint for Procreate"""
    print("\n=== Testing PSD Export Endpoint ===")
    
    try:
        # Create test images
        print("Creating test images...")
        original_image = create_test_image()  # Use existing function for original
        stencil_image = create_stencil_test_image()  # Create stencil-specific image
        
        # Prepare request data
        request_data = {
            "original_image": original_image,
            "stencil_image": stencil_image
        }
        
        print(f"Sending POST request to {API_BASE}/export-psd...")
        start_time = time.time()
        
        response = requests.post(
            f"{API_BASE}/export-psd",
            json=request_data,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        processing_time = (time.time() - start_time) * 1000
        
        print(f"Response status: {response.status_code}")
        print(f"Response time: {processing_time:.2f}ms")
        print(f"Response headers: {dict(response.headers)}")
        
        # Check status code
        if response.status_code != 200:
            print(f"❌ PSD Export FAILED: Expected status 200, got {response.status_code}")
            print(f"Response text: {response.text}")
            return False
        
        # Check content type
        content_type = response.headers.get('content-type', '')
        if 'application/x-photoshop' not in content_type:
            print(f"❌ PSD Export FAILED: Expected content-type 'application/x-photoshop', got '{content_type}'")
            return False
        
        # Check content disposition (filename)
        content_disposition = response.headers.get('content-disposition', '')
        if 'attachment' not in content_disposition or '.psd' not in content_disposition:
            print(f"❌ PSD Export FAILED: Expected attachment with .psd filename, got '{content_disposition}'")
            return False
        
        # Check response body starts with PSD signature
        response_data = response.content
        if len(response_data) < 4:
            print(f"❌ PSD Export FAILED: Response too short ({len(response_data)} bytes)")
            return False
        
        psd_signature = response_data[:4]
        if psd_signature != b'8BPS':
            print(f"❌ PSD Export FAILED: Expected PSD signature '8BPS', got '{psd_signature}'")
            return False
        
        # Check file size is reasonable (should be > 1KB for a valid PSD)
        file_size = len(response_data)
        if file_size < 1024:
            print(f"❌ PSD Export FAILED: PSD file too small ({file_size} bytes), likely invalid")
            return False
        
        # Save the PSD file for manual verification (optional)
        psd_filename = f"/tmp/test_export_{int(time.time())}.psd"
        with open(psd_filename, 'wb') as f:
            f.write(response_data)
        
        print(f"✅ PSD Export PASSED: Working correctly")
        print(f"   - Status: 200 OK")
        print(f"   - Content-Type: {content_type}")
        print(f"   - File size: {file_size} bytes")
        print(f"   - PSD signature: {psd_signature}")
        print(f"   - Processing time: {processing_time:.2f}ms")
        print(f"   - Saved test file: {psd_filename}")
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ PSD Export FAILED: Network error - {str(e)}")
        return False
    except Exception as e:
        print(f"❌ PSD Export FAILED: Unexpected error - {str(e)}")
        return False

def test_psd_export_edge_cases():
    """Test PSD export with edge cases"""
    print("\n=== Testing PSD Export Edge Cases ===")
    
    # Test 1: Invalid base64 data
    print("\nTest 1: Invalid base64 data")
    try:
        request_data = {
            "original_image": "invalid_base64_data",
            "stencil_image": "also_invalid"
        }
        
        response = requests.post(
            f"{API_BASE}/export-psd",
            json=request_data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 500:
            print("✅ Correctly handles invalid base64 data with 500 error")
            return True
        else:
            print(f"⚠️  Unexpected response for invalid data: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"⚠️  Error testing invalid data: {str(e)}")
        return False

def create_test_stencil_for_transparency():
    """Create a test stencil image with black lines on white background for transparency testing"""
    img = Image.new('RGB', (100, 100), (255, 255, 255))  # White background
    draw = ImageDraw.Draw(img)
    
    # Draw a black square in the center
    draw.rectangle([25, 25, 75, 75], fill=(0, 0, 0))
    
    # Convert to base64
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    img_data = buffer.getvalue()
    base64_string = base64.b64encode(img_data).decode('utf-8')
    return f"data:image/png;base64,{base64_string}"

def analyze_transparency(base64_image):
    """Analyze the transparency of pixels in a base64 image"""
    import numpy as np
    
    # Remove data URL prefix
    if ',' in base64_image:
        base64_data = base64_image.split(',')[1]
    else:
        base64_data = base64_image
    
    # Decode image
    img_data = base64.b64decode(base64_data)
    img = Image.open(io.BytesIO(img_data))
    
    # Convert to RGBA if needed
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # Convert to numpy array
    img_array = np.array(img)
    
    # Count transparent vs opaque pixels
    transparent_pixels = np.sum(img_array[:,:,3] == 0)
    opaque_pixels = np.sum(img_array[:,:,3] == 255)
    total_pixels = img_array.shape[0] * img_array.shape[1]
    
    return {
        'width': img.size[0],
        'height': img.size[1],
        'total_pixels': total_pixels,
        'transparent_pixels': transparent_pixels,
        'opaque_pixels': opaque_pixels,
        'transparency_ratio': transparent_pixels / total_pixels if total_pixels > 0 else 0,
        'opacity_ratio': opaque_pixels / total_pixels if total_pixels > 0 else 0
    }

def test_make_transparent():
    """Test the new /api/make-transparent endpoint"""
    print("\n=== Testing Make Transparent Endpoint ===")
    
    try:
        # Create test stencil image (black square on white background)
        test_stencil = create_test_stencil_for_transparency()
        
        # Test basic functionality
        print("Test 1: Basic transparency conversion")
        payload = {
            "image_base64": test_stencil
        }
        
        start_time = time.time()
        response = requests.post(
            f"{API_BASE}/make-transparent",
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=15
        )
        processing_time = (time.time() - start_time) * 1000
        
        print(f"Status Code: {response.status_code}")
        print(f"Processing time: {processing_time:.2f}ms")
        
        if response.status_code != 200:
            print(f"❌ Make Transparent FAILED: Expected 200, got {response.status_code}")
            print(f"Response: {response.text}")
            return False
        
        result = response.json()
        
        # Verify response structure
        required_keys = ['image_base64', 'width', 'height']
        for key in required_keys:
            if key not in result:
                print(f"❌ Make Transparent FAILED: Missing key '{key}' in response")
                return False
        
        # Verify dimensions
        if result['width'] != 100 or result['height'] != 100:
            print(f"❌ Make Transparent FAILED: Expected 100x100, got {result['width']}x{result['height']}")
            return False
        
        # Analyze transparency
        transparency_info = analyze_transparency(result['image_base64'])
        print(f"Transparency analysis: {transparency_info}")
        
        # Verify that we have both transparent and opaque pixels
        if transparency_info['transparent_pixels'] == 0:
            print("❌ Make Transparent FAILED: No transparent pixels found - white background should be transparent")
            return False
        
        if transparency_info['opaque_pixels'] == 0:
            print("❌ Make Transparent FAILED: No opaque pixels found - black square should be opaque")
            return False
        
        # The white background should be majority transparent
        if transparency_info['transparency_ratio'] < 0.5:  # At least 50% should be transparent
            print(f"❌ Make Transparent FAILED: Only {transparency_info['transparency_ratio']:.2%} transparent, expected >50%")
            return False
        
        print("✅ Basic transparency conversion PASSED")
        
        # Test 2: With resizing
        print("\nTest 2: Transparency with resizing")
        payload_resize = {
            "image_base64": test_stencil,
            "target_width": 200,
            "target_height": 200
        }
        
        response_resize = requests.post(
            f"{API_BASE}/make-transparent",
            json=payload_resize,
            headers={'Content-Type': 'application/json'},
            timeout=15
        )
        
        if response_resize.status_code != 200:
            print(f"❌ Make Transparent with resize FAILED: Status {response_resize.status_code}")
            return False
        
        result_resize = response_resize.json()
        
        if result_resize['width'] != 200 or result_resize['height'] != 200:
            print(f"❌ Make Transparent resize FAILED: Expected 200x200, got {result_resize['width']}x{result_resize['height']}")
            return False
        
        print("✅ Transparency with resizing PASSED")
        
        # Test 3: Error handling
        print("\nTest 3: Error handling for invalid base64")
        payload_invalid = {
            "image_base64": "invalid_base64_data"
        }
        
        response_invalid = requests.post(
            f"{API_BASE}/make-transparent",
            json=payload_invalid,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response_invalid.status_code == 200:
            print("❌ Make Transparent error handling FAILED: Should reject invalid base64")
            return False
        
        print("✅ Error handling PASSED")
        
        print("✅ Make Transparent endpoint PASSED all tests")
        return True
        
    except Exception as e:
        print(f"❌ Make Transparent FAILED: Error - {str(e)}")
        return False

def main():
    """Run all backend tests"""
    print("🧪 Starting Tattoo Stencil Backend API Tests")
    print("=" * 50)
    
    results = {}
    
    # Test 1: Health Check
    results['health'] = test_health_check()
    
    # Test 2: Image Processing
    process_success, stencil_image = test_image_processing()
    results['process'] = process_success
    
    # Test 3: AI Stencil Generation
    ai_success, ai_stencil_image = test_ai_stencil()
    results['ai_stencil'] = ai_success
    
    # Test 4: Make Transparent (NEW TEST - Primary focus as requested)
    results['make_transparent'] = test_make_transparent()
    
    # Test 5: PSD Export 
    results['psd_export'] = test_psd_export()
    
    # Test 6: PSD Export Edge Cases
    results['psd_edge_cases'] = test_psd_export_edge_cases()
    
    # Test 7: Save Stencil (only if processing worked)
    if process_success and stencil_image:
        original_image = create_test_image()
        save_success, stencil_id = test_save_stencil(original_image, stencil_image)
        results['save'] = save_success
    else:
        print("\n⚠️  Skipping save test - image processing failed")
        results['save'] = False
        stencil_id = None
    
    # Test 8: Get Stencils
    get_success, stencils_data = test_get_stencils()
    results['get'] = get_success
    
    # Test 9: Delete Stencil (only if we have an ID)
    if stencil_id:
        results['delete'] = test_delete_stencil(stencil_id)
    else:
        print("\n⚠️  Skipping delete test - no stencil ID available")
        results['delete'] = False
    
    # Summary
    print("\n" + "=" * 50)
    print("🏁 TEST SUMMARY")
    print("=" * 50)
    
    total_tests = len(results)
    passed_tests = sum(1 for result in results.values() if result)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name.upper()}: {status}")
    
    print(f"\nOverall: {passed_tests}/{total_tests} tests passed")
    
    # Special focus on Make Transparent endpoint since that's the current focus
    if results.get('make_transparent'):
        print("\n🎯 PRIMARY FOCUS: Make Transparent endpoint is WORKING correctly!")
    else:
        print("\n⚠️  PRIMARY FOCUS: Make Transparent endpoint has ISSUES!")
    
    if passed_tests == total_tests:
        print("🎉 All tests PASSED!")
        return True
    else:
        print("⚠️  Some tests FAILED!")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)