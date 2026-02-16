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
    
    # Test 3: Save Stencil (only if processing worked)
    if process_success and stencil_image:
        original_image = create_test_image()
        save_success, stencil_id = test_save_stencil(original_image, stencil_image)
        results['save'] = save_success
    else:
        print("\n⚠️  Skipping save test - image processing failed")
        results['save'] = False
        stencil_id = None
    
    # Test 4: Get Stencils
    get_success, stencils_data = test_get_stencils()
    results['get'] = get_success
    
    # Test 5: Delete Stencil (only if we have an ID)
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
    
    if passed_tests == total_tests:
        print("🎉 All tests PASSED!")
        return True
    else:
        print("⚠️  Some tests FAILED!")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)