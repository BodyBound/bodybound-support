#!/usr/bin/env python3
"""
Specific AI Stencil Endpoint Testing
Tests the AI stencil generation with different parameters and edge cases
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

print(f"Testing AI stencil endpoint at: {API_BASE}/ai-stencil")

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

def test_ai_stencil_with_params(shading_detail, solid_fill, line_color, test_name):
    """Test AI stencil with specific parameters"""
    print(f"\n=== {test_name} ===")
    try:
        test_image_b64 = create_test_image()
        
        payload = {
            "image_base64": test_image_b64,
            "shading_detail": shading_detail,
            "solid_fill": solid_fill,
            "line_color": line_color
        }
        
        print(f"Parameters: shading_detail={shading_detail}, solid_fill={solid_fill}, line_color={line_color}")
        
        response = requests.post(
            f"{API_BASE}/ai-stencil", 
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=60
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Processing time: {data.get('processing_time_ms', 'N/A')} ms")
            
            if 'stencil_base64' in data and data['stencil_base64']:
                stencil_data = data['stencil_base64']
                if stencil_data.startswith('data:image/'):
                    print(f"✅ {test_name} PASSED")
                    return True
                else:
                    print(f"❌ {test_name} FAILED - Invalid stencil format")
                    return False
            else:
                print(f"❌ {test_name} FAILED - No stencil in response")
                return False
        else:
            print(f"❌ {test_name} FAILED - Status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ {test_name} FAILED - Error: {str(e)}")
        return False

def test_ai_stencil_edge_cases():
    """Test edge cases and error handling"""
    print("\n=== Testing Edge Cases ===")
    
    results = {}
    
    # Test 1: Invalid base64 image
    print("\n--- Test: Invalid base64 image ---")
    try:
        payload = {
            "image_base64": "invalid_base64_data",
            "shading_detail": 50,
            "solid_fill": 30,
            "line_color": "black"
        }
        
        response = requests.post(
            f"{API_BASE}/ai-stencil", 
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        if response.status_code == 400 or response.status_code == 500:
            print("✅ Invalid image handling PASSED - Correctly rejected invalid data")
            results['invalid_image'] = True
        else:
            print("❌ Invalid image handling FAILED - Should have rejected invalid data")
            results['invalid_image'] = False
            
    except Exception as e:
        print(f"❌ Invalid image test FAILED - Error: {str(e)}")
        results['invalid_image'] = False
    
    # Test 2: Missing required fields
    print("\n--- Test: Missing required fields ---")
    try:
        payload = {
            "shading_detail": 50,
            "solid_fill": 30,
            "line_color": "black"
            # Missing image_base64
        }
        
        response = requests.post(
            f"{API_BASE}/ai-stencil", 
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        if response.status_code == 422 or response.status_code == 400:
            print("✅ Missing field validation PASSED - Correctly rejected missing image")
            results['missing_field'] = True
        else:
            print("❌ Missing field validation FAILED - Should have rejected missing image")
            results['missing_field'] = False
            
    except Exception as e:
        print(f"❌ Missing field test FAILED - Error: {str(e)}")
        results['missing_field'] = False
    
    return results

def main():
    """Run AI stencil specific tests"""
    print("🧪 Starting AI Stencil Specific Tests")
    print("=" * 50)
    
    results = {}
    
    # Test different parameter combinations
    test_cases = [
        (0, 0, "black", "Minimal shading, no fill, black lines"),
        (100, 100, "purple", "Maximum shading, maximum fill, purple lines"),
        (50, 30, "blue", "Medium shading, low fill, blue lines"),
        (25, 75, "black", "Low shading, high fill, black lines")
    ]
    
    for shading, fill, color, name in test_cases:
        results[f"params_{shading}_{fill}_{color}"] = test_ai_stencil_with_params(shading, fill, color, name)
    
    # Test edge cases
    edge_results = test_ai_stencil_edge_cases()
    results.update(edge_results)
    
    # Summary
    print("\n" + "=" * 50)
    print("🏁 AI STENCIL TEST SUMMARY")
    print("=" * 50)
    
    total_tests = len(results)
    passed_tests = sum(1 for result in results.values() if result)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name.upper()}: {status}")
    
    print(f"\nOverall: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 All AI stencil tests PASSED!")
        return True
    else:
        print("⚠️  Some AI stencil tests FAILED!")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)