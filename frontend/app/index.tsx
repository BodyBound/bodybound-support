import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Pressable,
  ScrollView,
  Image,
  ActivityIndicator,
  Alert,
  Platform,
  KeyboardAvoidingView,
  TextInput,
  Modal,
  Dimensions,
  PanResponder,
  GestureResponderEvent,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as ImagePicker from 'expo-image-picker';
import * as ImageManipulator from 'expo-image-manipulator';
import * as MediaLibrary from 'expo-media-library';
import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import * as FileSystem from 'expo-file-system';
import Slider from '@react-native-community/slider';
import { Ionicons } from '@expo/vector-icons'; // Keep import for potential future use

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const { width: SCREEN_WIDTH, height: SCREEN_HEIGHT } = Dimensions.get('window');

interface StencilSettings {
  clarity: number;
  line_weight: number;
  noise_reduction: number;
  invert: boolean;
}

interface SavedStencil {
  id: string;
  original_image: string;
  stencil_image: string;
  settings: StencilSettings;
  created_at: string;
  name: string | null;
}

// Lightweight interface for gallery list (thumbnails only)
interface StencilListItem {
  id: string;
  stencil_thumbnail: string | null;
  created_at: string;
  name: string | null;
}

export default function Index() {
  const [originalImage, setOriginalImage] = useState<string | null>(null);
  const [stencilImage, setStencilImage] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isLiveUpdating, setIsLiveUpdating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [showGallery, setShowGallery] = useState(false);
  const [savedStencils, setSavedStencils] = useState<StencilListItem[]>([]);
  const [loadingGallery, setLoadingGallery] = useState(false);
  const [stencilName, setStencilName] = useState('');
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [hasGeneratedOnce, setHasGeneratedOnce] = useState(false);
  
  // Background removal state
  const [isRemovingBackground, setIsRemovingBackground] = useState(false);
  
  // AI Stencil states
  const [isGeneratingAI, setIsGeneratingAI] = useState(false);
  const [stencilMode, setStencilMode] = useState<'basic' | 'ai'>('ai'); // Default to AI mode
  const [lineColor, setLineColor] = useState<'purple' | 'blue' | 'black'>('purple');
  
  // Full-size preview state with zoom
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [previewShowingOriginal, setPreviewShowingOriginal] = useState(false);
  const [previewScale, setPreviewScale] = useState(1);
  const [previewPosition, setPreviewPosition] = useState({ x: 0, y: 0 });
  
  // Hold to compare - shows original when pressing down
  const [showingOriginal, setShowingOriginal] = useState(false);
  
  // Crop modal state
  const [showCropModal, setShowCropModal] = useState(false);
  const [cropImageSize, setCropImageSize] = useState({ width: 0, height: 0 });
  const [cropBox, setCropBox] = useState({ x: 50, y: 50, width: 200, height: 200 });
  const [activeCropHandle, setActiveCropHandle] = useState<string | null>(null);
  const [cropStartPos, setCropStartPos] = useState({ x: 0, y: 0 });
  const [cropStartBox, setCropStartBox] = useState({ x: 0, y: 0, width: 0, height: 0 });
  
  // Refs for debouncing
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  
  // Refs for crop tool state (to avoid stale closures in PanResponder)
  const cropBoxRef = useRef(cropBox);
  const activeCropHandleRef = useRef<string | null>(null);
  const cropStartBoxRef = useRef({ x: 0, y: 0, width: 0, height: 0 });
  
  // Keep refs in sync with state
  useEffect(() => {
    cropBoxRef.current = cropBox;
  }, [cropBox]);
  
  // Crop PanResponder for reliable touch handling
  const cropPanResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (evt) => {
        const { locationX, locationY } = evt.nativeEvent;
        const box = cropBoxRef.current;
        const margin = 45; // Larger hit area for corners
        
        let handle: string | null = null;
        
        // Check corners first (larger hit area)
        if (Math.abs(locationX - box.x) < margin && Math.abs(locationY - box.y) < margin) {
          handle = 'tl';
        } else if (Math.abs(locationX - (box.x + box.width)) < margin && Math.abs(locationY - box.y) < margin) {
          handle = 'tr';
        } else if (Math.abs(locationX - box.x) < margin && Math.abs(locationY - (box.y + box.height)) < margin) {
          handle = 'bl';
        } else if (Math.abs(locationX - (box.x + box.width)) < margin && Math.abs(locationY - (box.y + box.height)) < margin) {
          handle = 'br';
        } else if (locationX >= box.x && locationX <= box.x + box.width &&
                   locationY >= box.y && locationY <= box.y + box.height) {
          handle = 'move';
        }
        
        activeCropHandleRef.current = handle;
        cropStartBoxRef.current = { ...box };
        setActiveCropHandle(handle);
      },
      onPanResponderMove: (evt, gestureState) => {
        const handle = activeCropHandleRef.current;
        if (!handle) return;
        
        const startBox = cropStartBoxRef.current;
        const dx = gestureState.dx;
        const dy = gestureState.dy;
        const minSize = 60;
        const containerWidth = SCREEN_WIDTH - 40;
        const containerHeight = SCREEN_HEIGHT - 150; // More space for the crop area

        let newBox = { ...startBox };

        if (handle === 'move') {
          newBox = {
            ...startBox,
            x: Math.max(0, Math.min(containerWidth - startBox.width, startBox.x + dx)),
            y: Math.max(0, Math.min(containerHeight - startBox.height, startBox.y + dy)),
          };
        } else if (handle === 'br') {
          newBox = {
            ...startBox,
            width: Math.max(minSize, Math.min(containerWidth - startBox.x, startBox.width + dx)),
            height: Math.max(minSize, Math.min(containerHeight - startBox.y, startBox.height + dy)),
          };
        } else if (handle === 'bl') {
          const newWidth = Math.max(minSize, startBox.width - dx);
          const newX = startBox.x + startBox.width - newWidth;
          if (newX >= 0) {
            newBox = {
              ...startBox,
              x: newX,
              width: newWidth,
              height: Math.max(minSize, Math.min(containerHeight - startBox.y, startBox.height + dy)),
            };
          }
        } else if (handle === 'tr') {
          const newHeight = Math.max(minSize, startBox.height - dy);
          const newY = startBox.y + startBox.height - newHeight;
          if (newY >= 0) {
            newBox = {
              ...startBox,
              y: newY,
              width: Math.max(minSize, Math.min(containerWidth - startBox.x, startBox.width + dx)),
              height: newHeight,
            };
          }
        } else if (handle === 'tl') {
          const newWidth = Math.max(minSize, startBox.width - dx);
          const newHeight = Math.max(minSize, startBox.height - dy);
          const newX = startBox.x + startBox.width - newWidth;
          const newY = startBox.y + startBox.height - newHeight;
          if (newX >= 0 && newY >= 0) {
            newBox = {
              x: newX,
              y: newY,
              width: newWidth,
              height: newHeight,
            };
          }
        }
        
        setCropBox(newBox);
        cropBoxRef.current = newBox;
      },
      onPanResponderRelease: () => {
        activeCropHandleRef.current = null;
        setActiveCropHandle(null);
      },
    })
  ).current;
  
  // Settings state - defaults optimized for detailed stencils
  const [settings, setSettings] = useState<StencilSettings>({
    clarity: 30,  // Lower = more detail captured
    line_weight: 40,  // Medium line weight
    noise_reduction: 30,  // Lower = more detail preserved
    invert: true,
  });

  // Live update function with debouncing - ONLY for basic mode
  const processImageLive = useCallback(async (currentSettings: StencilSettings) => {
    // Only process in basic mode with live updates enabled
    if (!originalImage || !hasGeneratedOnce || stencilMode !== 'basic') return;

    // Cancel any pending request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    // Create new abort controller
    abortControllerRef.current = new AbortController();

    setIsLiveUpdating(true);
    try {
      const response = await fetch(`${API_URL}/api/process`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          image_base64: originalImage,
          settings: currentSettings,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error('Failed to process image');
      }

      const data = await response.json();
      setStencilImage(data.stencil_base64);
    } catch (error: any) {
      if (error.name !== 'AbortError') {
        console.error('Error processing image:', error);
      }
    } finally {
      setIsLiveUpdating(false);
    }
  }, [originalImage, hasGeneratedOnce, stencilMode]);

  // Debounced settings change handler - ONLY for basic mode
  const handleSettingsChange = useCallback((newSettings: StencilSettings) => {
    setSettings(newSettings);
    
    // Only trigger live update in basic mode
    if (stencilMode !== 'basic') return;
    // Only trigger live update if we've generated at least once
    if (hasGeneratedOnce && originalImage) {
      // Clear existing timer
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
      
      // Set new debounced timer (300ms delay)
      debounceTimerRef.current = setTimeout(() => {
        processImageLive(newSettings);
      }, 300);
    }
  }, [hasGeneratedOnce, originalImage, processImageLive]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const pickImage = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission Required', 'Please allow access to your photo library to select images.');
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      quality: 0.8,
      base64: true,
    });

    if (!result.canceled && result.assets[0].base64) {
      const base64Image = `data:image/jpeg;base64,${result.assets[0].base64}`;
      setOriginalImage(base64Image);
      setStencilImage(null);
    }
  };

  const takePhoto = async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission Required', 'Please allow access to your camera to take photos.');
      return;
    }

    const result = await ImagePicker.launchCameraAsync({
      allowsEditing: true,
      quality: 0.8,
      base64: true,
    });

    if (!result.canceled && result.assets[0].base64) {
      const base64Image = `data:image/jpeg;base64,${result.assets[0].base64}`;
      setOriginalImage(base64Image);
      setStencilImage(null);
    }
  };

  const processImage = useCallback(async () => {
    if (!originalImage) {
      Alert.alert('No Image', 'Please select an image first.');
      return;
    }

    setIsProcessing(true);
    try {
      const response = await fetch(`${API_URL}/api/process`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          image_base64: originalImage,
          settings: settings,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to process image');
      }

      const data = await response.json();
      setStencilImage(data.stencil_base64);
      setHasGeneratedOnce(true); // Enable live updates after first generation
    } catch (error) {
      console.error('Error processing image:', error);
      Alert.alert('Error', 'Failed to process image. Please try again.');
    } finally {
      setIsProcessing(false);
    }
  }, [originalImage, settings]);

  // AI-Powered Stencil Generation
  const generateAIStencil = async () => {
    if (!originalImage) {
      Alert.alert('No Image', 'Please select an image first.');
      return;
    }

    setIsGeneratingAI(true);
    try {
      const response = await fetch(`${API_URL}/api/ai-stencil`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          image_base64: originalImage,
          style: 'tattoo',
          line_color: lineColor,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Failed to generate AI stencil');
      }

      const data = await response.json();
      setStencilImage(data.stencil_base64);
      setHasGeneratedOnce(true);
    } catch (error: any) {
      console.error('Error generating AI stencil:', error);
      Alert.alert('Error', error.message || 'Failed to generate AI stencil. Please try again.');
    } finally {
      setIsGeneratingAI(false);
    }
  };

  // Remove background function
  const removeBackground = async () => {
    if (!originalImage) {
      Alert.alert('No Image', 'Please select an image first.');
      return;
    }

    setIsRemovingBackground(true);
    try {
      const response = await fetch(`${API_URL}/api/remove-background`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          image_base64: originalImage,
          method: 'auto',
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to remove background');
      }

      const data = await response.json();
      setOriginalImage(data.image_base64);
      setStencilImage(null);
      setHasGeneratedOnce(false);
      Alert.alert('Success', 'Background removed! Generate stencil to see the result.');
    } catch (error) {
      console.error('Error removing background:', error);
      Alert.alert('Error', 'Failed to remove background. Please try again.');
    } finally {
      setIsRemovingBackground(false);
    }
  };

  // Open the crop modal with the current image
  const openCropModal = () => {
    if (!originalImage) {
      Alert.alert('No Image', 'Please select an image first.');
      return;
    }

    // Get image dimensions to set up crop box
    Image.getSize(originalImage, (width, height) => {
      setCropImageSize({ width, height });
      
      // Calculate display dimensions - use same values as PanResponder
      const containerWidth = SCREEN_WIDTH - 40;
      const containerHeight = SCREEN_HEIGHT - 150;
      
      // Calculate how the image will be displayed (contain mode)
      const imageAspect = width / height;
      const containerAspect = containerWidth / containerHeight;
      
      let displayWidth, displayHeight, offsetX, offsetY;
      if (imageAspect > containerAspect) {
        // Image is wider - fit to width
        displayWidth = containerWidth;
        displayHeight = containerWidth / imageAspect;
        offsetX = 0;
        offsetY = (containerHeight - displayHeight) / 2;
      } else {
        // Image is taller - fit to height
        displayHeight = containerHeight;
        displayWidth = containerHeight * imageAspect;
        offsetX = (containerWidth - displayWidth) / 2;
        offsetY = 0;
      }
      
      // Set initial crop box to 80% of the displayed image area, centered
      const cropWidth = displayWidth * 0.8;
      const cropHeight = displayHeight * 0.8;
      const cropX = offsetX + (displayWidth - cropWidth) / 2;
      const cropY = offsetY + (displayHeight - cropHeight) / 2;
      
      setCropBox({
        x: cropX,
        y: cropY,
        width: cropWidth,
        height: cropHeight,
      });
      setShowCropModal(true);
    }, () => {
      // Fallback if can't get size
      const containerWidth = SCREEN_WIDTH - 40;
      const containerHeight = SCREEN_HEIGHT - 200;
      setCropImageSize({ width: 1000, height: 1000 });
      setCropBox({ 
        x: containerWidth * 0.1, 
        y: containerHeight * 0.1, 
        width: containerWidth * 0.8, 
        height: containerHeight * 0.8 
      });
      setShowCropModal(true);
    });
  };

  // Handle crop box touch events
  const handleCropTouchStart = (handle: string, event: GestureResponderEvent) => {
    const { locationX, locationY } = event.nativeEvent;
    setActiveCropHandle(handle);
    setCropStartPos({ x: locationX, y: locationY });
    setCropStartBox({ ...cropBox });
  };

  const handleCropTouchMove = (event: GestureResponderEvent) => {
    if (!activeCropHandle) return;
    
    const { locationX, locationY } = event.nativeEvent;
    const dx = locationX - cropStartPos.x;
    const dy = locationY - cropStartPos.y;
    const minSize = 60;
    const containerWidth = SCREEN_WIDTH - 40;
    const containerHeight = SCREEN_HEIGHT - 150; // Account for header and bottom info

    if (activeCropHandle === 'move') {
      const newX = Math.max(0, Math.min(containerWidth - cropStartBox.width, cropStartBox.x + dx));
      const newY = Math.max(0, Math.min(containerHeight - cropStartBox.height, cropStartBox.y + dy));
      setCropBox({
        ...cropStartBox,
        x: newX,
        y: newY,
      });
    } else if (activeCropHandle === 'br') {
      // Bottom-right corner
      const newWidth = Math.max(minSize, Math.min(containerWidth - cropStartBox.x, cropStartBox.width + dx));
      const newHeight = Math.max(minSize, Math.min(containerHeight - cropStartBox.y, cropStartBox.height + dy));
      setCropBox({
        ...cropStartBox,
        width: newWidth,
        height: newHeight,
      });
    } else if (activeCropHandle === 'bl') {
      // Bottom-left corner
      const newWidth = Math.max(minSize, cropStartBox.width - dx);
      const newX = cropStartBox.x + cropStartBox.width - newWidth;
      const newHeight = Math.max(minSize, Math.min(containerHeight - cropStartBox.y, cropStartBox.height + dy));
      if (newX >= 0) {
        setCropBox({
          ...cropStartBox,
          x: newX,
          width: newWidth,
          height: newHeight,
        });
      }
    } else if (activeCropHandle === 'tr') {
      // Top-right corner
      const newHeight = Math.max(minSize, cropStartBox.height - dy);
      const newY = cropStartBox.y + cropStartBox.height - newHeight;
      const newWidth = Math.max(minSize, Math.min(containerWidth - cropStartBox.x, cropStartBox.width + dx));
      if (newY >= 0) {
        setCropBox({
          ...cropStartBox,
          y: newY,
          width: newWidth,
          height: newHeight,
        });
      }
    } else if (activeCropHandle === 'tl') {
      // Top-left corner
      const newWidth = Math.max(minSize, cropStartBox.width - dx);
      const newHeight = Math.max(minSize, cropStartBox.height - dy);
      const newX = cropStartBox.x + cropStartBox.width - newWidth;
      const newY = cropStartBox.y + cropStartBox.height - newHeight;
      if (newX >= 0 && newY >= 0) {
        setCropBox({
          x: newX,
          y: newY,
          width: newWidth,
          height: newHeight,
        });
      }
    }
    
    // Update start position for continuous movement
    setCropStartPos({ x: locationX, y: locationY });
  };

  const handleCropTouchEnd = () => {
    setActiveCropHandle(null);
  };

  // Apply the crop
  const applyCrop = async () => {
    if (!originalImage) return;

    try {
      // Calculate display dimensions (same logic as openCropModal and PanResponder)
      const containerWidth = SCREEN_WIDTH - 40;
      const containerHeight = SCREEN_HEIGHT - 150;
      
      const imageAspect = cropImageSize.width / cropImageSize.height;
      const containerAspect = containerWidth / containerHeight;
      
      let displayWidth, displayHeight, offsetX, offsetY;
      if (imageAspect > containerAspect) {
        displayWidth = containerWidth;
        displayHeight = containerWidth / imageAspect;
        offsetX = 0;
        offsetY = (containerHeight - displayHeight) / 2;
      } else {
        displayHeight = containerHeight;
        displayWidth = containerHeight * imageAspect;
        offsetX = (containerWidth - displayWidth) / 2;
        offsetY = 0;
      }
      
      // Convert crop box from display coordinates to image coordinates
      // First, adjust for the offset (where the image starts in the container)
      const adjustedX = cropBox.x - offsetX;
      const adjustedY = cropBox.y - offsetY;
      
      // Scale factors from display to actual image
      const scaleX = cropImageSize.width / displayWidth;
      const scaleY = cropImageSize.height / displayHeight;
      
      const cropRegion = {
        originX: Math.round(Math.max(0, adjustedX * scaleX)),
        originY: Math.round(Math.max(0, adjustedY * scaleY)),
        width: Math.round(cropBox.width * scaleX),
        height: Math.round(cropBox.height * scaleY),
      };

      // Ensure crop region is within bounds
      cropRegion.originX = Math.max(0, Math.min(cropRegion.originX, cropImageSize.width - 10));
      cropRegion.originY = Math.max(0, Math.min(cropRegion.originY, cropImageSize.height - 10));
      cropRegion.width = Math.max(10, Math.min(cropRegion.width, cropImageSize.width - cropRegion.originX));
      cropRegion.height = Math.max(10, Math.min(cropRegion.height, cropImageSize.height - cropRegion.originY));

      const result = await ImageManipulator.manipulateAsync(
        originalImage,
        [{ crop: cropRegion }],
        { compress: 0.8, format: ImageManipulator.SaveFormat.PNG, base64: true }
      );

      if (result.base64) {
        setOriginalImage(`data:image/png;base64,${result.base64}`);
        setStencilImage(null);
        setHasGeneratedOnce(false);
        setShowCropModal(false);
        Alert.alert('Success', 'Image cropped successfully!');
      }
    } catch (error) {
      console.error('Error applying crop:', error);
      Alert.alert('Error', 'Failed to crop image. Please try again.');
    }
  };

  const saveStencil = async () => {
    if (!originalImage || !stencilImage) {
      Alert.alert('Error', 'Please process an image first.');
      return;
    }

    setIsSaving(true);
    try {
      const response = await fetch(`${API_URL}/api/stencils`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          original_image: originalImage,
          stencil_image: stencilImage,
          settings: settings,
          name: stencilName || null,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to save stencil');
      }

      Alert.alert('Success', 'Stencil saved successfully!');
      setShowSaveModal(false);
      setStencilName('');
    } catch (error) {
      console.error('Error saving stencil:', error);
      Alert.alert('Error', 'Failed to save stencil. Please try again.');
    } finally {
      setIsSaving(false);
    }
  };

  // Save stencil to device photo library
  const saveToDevice = async () => {
    if (!stencilImage) {
      Alert.alert('Error', 'No stencil to save.');
      return;
    }

    try {
      // Request permission
      const { status } = await MediaLibrary.requestPermissionsAsync();
      if (status !== 'granted') {
        Alert.alert('Permission Required', 'Please allow access to save images to your device.');
        return;
      }

      // Extract base64 data
      const base64Data = stencilImage.includes(',') ? stencilImage.split(',')[1] : stencilImage;
      
      // Create a temporary file
      const filename = `stencil_${Date.now()}.png`;
      const fileUri = `${FileSystem.cacheDirectory}${filename}`;
      
      await FileSystem.writeAsStringAsync(fileUri, base64Data, {
        encoding: FileSystem.EncodingType.Base64,
      });

      // Save to media library
      const asset = await MediaLibrary.createAssetAsync(fileUri);
      await MediaLibrary.createAlbumAsync('Tattoo Stencils', asset, false);

      Alert.alert('Success', 'Stencil saved to your photo library!');
    } catch (error) {
      console.error('Error saving to device:', error);
      Alert.alert('Error', 'Failed to save to device. Please try again.');
    }
  };

  // Print stencil
  const printStencil = async () => {
    if (!stencilImage) {
      Alert.alert('Error', 'No stencil to print.');
      return;
    }

    try {
      const html = `
        <html>
          <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
              body {
                margin: 0;
                padding: 20px;
                display: flex;
                justify-content: center;
                align-items: center;
              }
              img {
                max-width: 100%;
                height: auto;
              }
              @page {
                size: auto;
                margin: 10mm;
              }
            </style>
          </head>
          <body>
            <img src="${stencilImage}" />
          </body>
        </html>
      `;

      await Print.printAsync({ html });
    } catch (error) {
      console.error('Error printing:', error);
      Alert.alert('Error', 'Failed to print. Please try again.');
    }
  };

  // Share stencil
  const shareStencil = async () => {
    if (!stencilImage) {
      Alert.alert('Error', 'No stencil to share.');
      return;
    }

    try {
      // Check if sharing is available
      const isAvailable = await Sharing.isAvailableAsync();
      if (!isAvailable) {
        Alert.alert('Error', 'Sharing is not available on this device.');
        return;
      }

      // Extract base64 data
      const base64Data = stencilImage.includes(',') ? stencilImage.split(',')[1] : stencilImage;
      
      // Create a temporary file
      const filename = `stencil_${Date.now()}.png`;
      const fileUri = `${FileSystem.cacheDirectory}${filename}`;
      
      await FileSystem.writeAsStringAsync(fileUri, base64Data, {
        encoding: FileSystem.EncodingType.Base64,
      });

      await Sharing.shareAsync(fileUri, {
        mimeType: 'image/png',
        dialogTitle: 'Share Tattoo Stencil',
      });
    } catch (error) {
      console.error('Error sharing:', error);
      Alert.alert('Error', 'Failed to share. Please try again.');
    }
  };

  const loadGallery = async () => {
    setLoadingGallery(true);
    try {
      const response = await fetch(`${API_URL}/api/stencils`);
      if (!response.ok) {
        throw new Error('Failed to load gallery');
      }
      const data = await response.json();
      setSavedStencils(data);
    } catch (error) {
      console.error('Error loading gallery:', error);
      Alert.alert('Error', 'Failed to load saved stencils.');
    } finally {
      setLoadingGallery(false);
    }
  };

  const deleteStencil = async (id: string) => {
    Alert.alert(
      'Delete Stencil',
      'Are you sure you want to delete this stencil?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              const response = await fetch(`${API_URL}/api/stencils/${id}`, {
                method: 'DELETE',
              });
              if (response.ok) {
                setSavedStencils(prev => prev.filter(s => s.id !== id));
              }
            } catch (error) {
              console.error('Error deleting stencil:', error);
            }
          },
        },
      ]
    );
  };

  const loadStencilFromGallery = (stencil: SavedStencil) => {
    setOriginalImage(stencil.original_image);
    setStencilImage(stencil.stencil_image);
    setSettings(stencil.settings);
    setShowGallery(false);
  };

  const resetAll = () => {
    setOriginalImage(null);
    setStencilImage(null);
    setHasGeneratedOnce(false);
    setSettings({
      clarity: 30,
      line_weight: 40,
      noise_reduction: 30,
      invert: true,
    });
  };

  const getSliderIcon = (key: string) => {
    switch (key) {
      case 'clarity': return '🔆';
      case 'line_weight': return '✏️';
      case 'noise_reduction': return '✨';
      default: return '⚙️';
    }
  };

  const renderSlider = (
    label: string,
    value: number,
    settingKey: keyof StencilSettings,
    icon: string
  ) => (
    <View style={styles.sliderContainer}>
      <View style={styles.sliderHeader}>
        <Text style={styles.sliderIcon}>{getSliderIcon(settingKey as string)}</Text>
        <Text style={styles.sliderLabel}>{label}</Text>
        <View style={styles.sliderValueContainer}>
          {isLiveUpdating && <ActivityIndicator size="small" color="#8B5CF6" style={styles.miniLoader} />}
          <Text style={styles.sliderValue}>{Math.round(value)}%</Text>
        </View>
      </View>
      <Slider
        style={styles.slider}
        minimumValue={0}
        maximumValue={100}
        value={value}
        onValueChange={(val) => setSettings(prev => ({ ...prev, [settingKey]: val }))}
        onSlidingComplete={(val) => handleSettingsChange({ ...settings, [settingKey]: val })}
        minimumTrackTintColor="#8B5CF6"
        maximumTrackTintColor="#374151"
        thumbTintColor="#8B5CF6"
      />
    </View>
  );

  // Gallery Modal
  const renderGalleryModal = () => (
    <Modal
      visible={showGallery}
      animationType="slide"
      transparent={false}
      onRequestClose={() => setShowGallery(false)}
    >
      <SafeAreaView style={styles.galleryContainer}>
        <View style={styles.galleryHeader}>
          <Text style={styles.galleryTitle}>Saved Stencils</Text>
          <TouchableOpacity
            onPress={() => setShowGallery(false)}
            style={styles.closeButton}
          >
            <Text style={styles.closeIcon}>✕</Text>
          </TouchableOpacity>
        </View>

        {loadingGallery ? (
          <ActivityIndicator size="large" color="#8B5CF6" style={styles.loader} />
        ) : savedStencils.length === 0 ? (
          <View style={styles.emptyGallery}>
            <Text style={styles.emptyIcon}>🖼️</Text>
            <Text style={styles.emptyText}>No saved stencils yet</Text>
          </View>
        ) : (
          <ScrollView style={styles.galleryScroll}>
            {savedStencils.map((stencil) => (
              <TouchableOpacity
                key={stencil.id}
                style={styles.galleryItem}
                onPress={() => loadStencilFromGallery(stencil)}
              >
                <Image
                  source={{ uri: stencil.stencil_image }}
                  style={styles.galleryImage}
                  resizeMode="contain"
                />
                <View style={styles.galleryItemInfo}>
                  <Text style={styles.galleryItemName}>
                    {stencil.name || 'Untitled'}
                  </Text>
                  <Text style={styles.galleryItemDate}>
                    {new Date(stencil.created_at).toLocaleDateString()}
                  </Text>
                </View>
                <TouchableOpacity
                  onPress={() => deleteStencil(stencil.id)}
                  style={styles.deleteButton}
                >
                  <Text style={styles.deleteIcon}>🗑️</Text>
                </TouchableOpacity>
              </TouchableOpacity>
            ))}
          </ScrollView>
        )}
      </SafeAreaView>
    </Modal>
  );

  // Save Modal
  const renderSaveModal = () => (
    <Modal
      visible={showSaveModal}
      animationType="fade"
      transparent={true}
      onRequestClose={() => setShowSaveModal(false)}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.saveModalOverlay}
      >
        <View style={styles.saveModalContent}>
          <Text style={styles.saveModalTitle}>Save Stencil</Text>
          <TextInput
            style={styles.saveModalInput}
            placeholder="Enter a name (optional)"
            placeholderTextColor="#6B7280"
            value={stencilName}
            onChangeText={setStencilName}
          />
          <View style={styles.saveModalButtons}>
            <TouchableOpacity
              style={styles.saveModalCancel}
              onPress={() => {
                setShowSaveModal(false);
                setStencilName('');
              }}
            >
              <Text style={styles.saveModalCancelText}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.saveModalSave}
              onPress={saveStencil}
              disabled={isSaving}
            >
              {isSaving ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Text style={styles.saveModalSaveText}>Save</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );

  return (
    <SafeAreaView style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Image 
            source={require('../assets/images/logo.png')} 
            style={styles.headerLogo}
            resizeMode="contain"
          />
          <View style={styles.headerTitleContainer}>
            <Text style={styles.headerTitle}>BODY BOUND</Text>
            <Text style={styles.headerSubtitle}>Stencil Generator</Text>
          </View>
        </View>
        <TouchableOpacity
          style={styles.galleryButton}
          onPress={() => {
            loadGallery();
            setShowGallery(true);
          }}
        >
          <Text style={styles.iconText}>📁</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {/* Image Preview Area - Stencil overlays Original with hold-to-compare */}
        <View style={styles.previewSection}>
          {!originalImage ? (
            <View style={styles.placeholderContainer}>
              <Text style={styles.placeholderIcon}>🖼️</Text>
              <Text style={styles.placeholderText}>Select or capture a photo</Text>
            </View>
          ) : (
            <View style={styles.imagesContainer}>
              {/* Main Image Display - Shows Stencil, hold to see Original */}
              <View style={styles.imageWrapper}>
                <View style={styles.imageLabelRow}>
                  <Text style={styles.imageLabel}>
                    {stencilImage ? (showingOriginal ? 'Original' : 'Stencil') : 'Original'}
                  </Text>
                  {stencilImage && (
                    <View style={styles.holdHintContainer}>
                      <Text style={styles.holdHintIcon}>👆</Text>
                      <Text style={styles.holdHintText}>Tap Compare button</Text>
                    </View>
                  )}
                </View>
                
                {/* Image display */}
                <Image
                  source={{ uri: stencilImage && !showingOriginal ? stencilImage : originalImage }}
                  style={styles.previewImage}
                  resizeMode="contain"
                />
                
                {/* Compare toggle button - shows when stencil exists */}
                {stencilImage && (
                  <TouchableOpacity
                    style={[styles.compareButton, showingOriginal && styles.compareButtonActive]}
                    onPress={() => setShowingOriginal(!showingOriginal)}
                  >
                    <Text style={styles.compareIconText}>{showingOriginal ? "👁️" : "👁️‍🗨️"}</Text>
                    <Text style={[styles.compareButtonText, showingOriginal && styles.compareButtonTextActive]}>
                      {showingOriginal ? "Showing Original" : "Compare"}
                    </Text>
                  </TouchableOpacity>
                )}

                {/* Export buttons below main image when stencil exists */}
                {stencilImage && (
                  <View style={styles.exportButtons}>
                    <TouchableOpacity 
                      style={styles.exportButton} 
                      onPress={() => setShowPreviewModal(true)}
                    >
                      <Text style={styles.exportIconText}>🔍</Text>
                      <Text style={styles.exportButtonText}>Full View</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.exportButton} onPress={saveToDevice}>
                      <Text style={[styles.exportIconText, { color: '#10B981' }]}>💾</Text>
                      <Text style={styles.exportButtonText}>Save</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.exportButton} onPress={printStencil}>
                      <Text style={[styles.exportIconText, { color: '#3B82F6' }]}>🖨️</Text>
                      <Text style={styles.exportButtonText}>Print</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.exportButton} onPress={shareStencil}>
                      <Text style={[styles.exportIconText, { color: '#F59E0B' }]}>📤</Text>
                      <Text style={styles.exportButtonText}>Share</Text>
                    </TouchableOpacity>
                  </View>
                )}
              </View>
            </View>
          )}
        </View>

        {/* Image Source Buttons */}
        <View style={styles.sourceButtons}>
          <TouchableOpacity style={styles.sourceButton} onPress={pickImage}>
            <Text style={styles.buttonIcon}>🖼️</Text>
            <Text style={styles.sourceButtonText}>Gallery</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.sourceButton} onPress={takePhoto}>
            <Text style={styles.buttonIcon}>📷</Text>
            <Text style={styles.sourceButtonText}>Camera</Text>
          </TouchableOpacity>
          {originalImage && (
            <TouchableOpacity style={styles.resetButton} onPress={resetAll}>
              <Text style={styles.buttonIcon}>🔄</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* Edit Tools - Crop and Remove Background */}
        {originalImage && (
          <View style={styles.editToolsSection}>
            <Text style={styles.editToolsTitle}>Edit Tools</Text>
            <View style={styles.editToolsRow}>
              <TouchableOpacity 
                style={styles.editToolButton} 
                onPress={openCropModal}
              >
                <Text style={styles.toolIcon}>✂️</Text>
                <Text style={styles.editToolButtonText}>Crop</Text>
              </TouchableOpacity>
              <TouchableOpacity 
                style={[styles.editToolButton, isRemovingBackground && styles.buttonDisabled]} 
                onPress={removeBackground}
                disabled={isRemovingBackground}
              >
                {isRemovingBackground ? (
                  <ActivityIndicator size="small" color="#8B5CF6" />
                ) : (
                  <Text style={styles.toolIcon}>🎭</Text>
                )}
                <Text style={styles.editToolButtonText}>
                  {isRemovingBackground ? 'Removing...' : 'Remove BG'}
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* Settings Controls - Only show for Basic Edge mode */}
        {originalImage && stencilMode === 'basic' && (
          <View style={styles.settingsSection}>
            <View style={styles.sectionTitleRow}>
              <Text style={styles.sectionTitle}>Stencil Settings</Text>
              {hasGeneratedOnce && (
                <Text style={styles.liveUpdateHint}>Live updates enabled</Text>
              )}
            </View>

            {renderSlider(
              'Clarity',
              settings.clarity,
              'clarity',
              'contrast-outline'
            )}

            {renderSlider(
              'Line Weight',
              settings.line_weight,
              'line_weight',
              'pencil-outline'
            )}

            {renderSlider(
              'Noise Reduction',
              settings.noise_reduction,
              'noise_reduction',
              'sparkles-outline'
            )}

            {/* Invert Toggle */}
            <TouchableOpacity
              style={styles.invertToggle}
              onPress={() => {
                const newSettings = { ...settings, invert: !settings.invert };
                setSettings(newSettings);
                if (hasGeneratedOnce) {
                  handleSettingsChange(newSettings);
                }
              }}
            >
              <View style={styles.invertToggleLeft}>
                <Text style={styles.invertIcon}>🎨</Text>
                <Text style={styles.invertToggleLabel}>Invert Colors</Text>
              </View>
              <View style={[
                styles.toggleSwitch,
                settings.invert && styles.toggleSwitchActive
              ]}>
                <View style={[
                  styles.toggleKnob,
                  settings.invert && styles.toggleKnobActive
                ]} />
              </View>
            </TouchableOpacity>
          </View>
        )}

        {/* Generation Mode Selection and AI Options */}
        {originalImage && (
          <View style={styles.modeSection}>
            <Text style={styles.modeSectionTitle}>Generation Mode</Text>
            
            {/* Mode Toggle */}
            <View style={styles.modeToggle}>
              <TouchableOpacity
                style={[styles.modeButton, stencilMode === 'ai' && styles.modeButtonActive]}
                onPress={() => {
                  setStencilMode('ai');
                  setHasGeneratedOnce(false); // Reset to prevent basic mode auto-updates
                }}
              >
                <Text style={styles.modeIcon}>✨</Text>
                <Text style={[styles.modeButtonText, stencilMode === 'ai' && styles.modeButtonTextActive]}>
                  AI Stencil
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modeButton, stencilMode === 'basic' && styles.modeButtonActive]}
                onPress={() => {
                  setStencilMode('basic');
                  setHasGeneratedOnce(false); // Reset when switching modes
                }}
              >
                <Text style={styles.modeIcon}>⚙️</Text>
                <Text style={[styles.modeButtonText, stencilMode === 'basic' && styles.modeButtonTextActive]}>
                  Basic Edge
                </Text>
              </TouchableOpacity>
            </View>

            {/* Line Color Selection (AI Mode Only) */}
            {stencilMode === 'ai' && (
              <View style={styles.colorSection}>
                <Text style={styles.colorSectionTitle}>Stencil Line Color</Text>
                <View style={styles.colorOptions}>
                  {(['purple', 'blue', 'black'] as const).map((color) => (
                    <TouchableOpacity
                      key={color}
                      style={[
                        styles.colorOption,
                        lineColor === color && styles.colorOptionActive,
                        { borderColor: color === 'purple' ? '#8B5CF6' : color === 'blue' ? '#3B82F6' : '#000' }
                      ]}
                      onPress={() => setLineColor(color)}
                    >
                      <View style={[
                        styles.colorDot,
                        { backgroundColor: color === 'purple' ? '#8B5CF6' : color === 'blue' ? '#3B82F6' : '#000' }
                      ]} />
                      <Text style={styles.colorOptionText}>{color.charAt(0).toUpperCase() + color.slice(1)}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </View>
            )}
          </View>
        )}

        {/* Action Buttons */}
        {originalImage && (
          <View style={styles.actionButtons}>
            {stencilMode === 'ai' ? (
              <Pressable
                style={({ pressed }) => [
                  styles.aiButton,
                  isGeneratingAI && styles.buttonDisabled,
                  pressed && !isGeneratingAI && styles.buttonPressed
                ]}
                onPress={generateAIStencil}
                disabled={isGeneratingAI}
                hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
              >
                {isGeneratingAI ? (
                  <>
                    <ActivityIndicator size="small" color="#fff" />
                    <Text style={styles.aiButtonText}>Creating Stencil...</Text>
                  </>
                ) : (
                  <>
                    <Text style={styles.generateIcon}>✨</Text>
                    <Text style={styles.aiButtonText}>Generate AI Stencil</Text>
                  </>
                )}
              </Pressable>
            ) : (
              <Pressable
                style={({ pressed }) => [
                  styles.processButton,
                  isProcessing && styles.buttonDisabled,
                  pressed && !isProcessing && styles.buttonPressed
                ]}
                onPress={processImage}
                disabled={isProcessing}
                hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
              >
                {isProcessing ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <>
                    <Text style={styles.generateIcon}>⚡</Text>
                    <Text style={styles.processButtonText}>Generate Stencil</Text>
                  </>
                )}
              </Pressable>
            )}

            {stencilImage && (
              <TouchableOpacity
                style={styles.saveButton}
                onPress={() => setShowSaveModal(true)}
              >
                <Text style={styles.saveIcon}>💾</Text>
                <Text style={styles.saveButtonText}>Save</Text>
              </TouchableOpacity>
            )}
          </View>
        )}

        <View style={styles.bottomSpacer} />
      </ScrollView>

      {renderGalleryModal()}
      {renderSaveModal()}
      
      {/* Crop Modal with Visual Drag Corners */}
      <Modal
        visible={showCropModal}
        animationType="slide"
        transparent={false}
        onRequestClose={() => setShowCropModal(false)}
      >
        <SafeAreaView style={styles.cropModalContainer}>
          <View style={styles.cropModalHeader}>
            <TouchableOpacity onPress={() => setShowCropModal(false)} style={styles.cropHeaderButton}>
              <Text style={styles.cropCancelText}>✕</Text>
            </TouchableOpacity>
            <Text style={styles.cropModalTitle}>Crop Image</Text>
            <TouchableOpacity onPress={applyCrop} style={styles.cropHeaderButton}>
              <Text style={styles.cropApplyText}>✓ Apply</Text>
            </TouchableOpacity>
          </View>

          {/* Crop Area with Draggable Box */}
          <View 
            style={styles.cropAreaContainer}
            {...cropPanResponder.panHandlers}
          >
            {/* Full Image */}
            {originalImage && (
              <Image
                source={{ uri: originalImage }}
                style={styles.cropFullImage}
                resizeMode="contain"
              />
            )}
            
            {/* Dark overlay outside crop area */}
            <View style={[styles.cropDarkOverlay, { top: 0, left: 0, right: 0, height: cropBox.y }]} pointerEvents="none" />
            <View style={[styles.cropDarkOverlay, { top: cropBox.y, left: 0, width: cropBox.x, height: cropBox.height }]} pointerEvents="none" />
            <View style={[styles.cropDarkOverlay, { top: cropBox.y, left: cropBox.x + cropBox.width, right: 0, height: cropBox.height }]} pointerEvents="none" />
            <View style={[styles.cropDarkOverlay, { top: cropBox.y + cropBox.height, left: 0, right: 0, bottom: 0 }]} pointerEvents="none" />
            
            {/* Crop Box Border */}
            <View style={[styles.cropBoxBorder, {
              left: cropBox.x,
              top: cropBox.y,
              width: cropBox.width,
              height: cropBox.height,
            }]} pointerEvents="none">
              {/* Grid lines */}
              <View style={[styles.cropGridLineH, { top: '33%' }]} />
              <View style={[styles.cropGridLineH, { top: '66%' }]} />
              <View style={[styles.cropGridLineV, { left: '33%' }]} />
              <View style={[styles.cropGridLineV, { left: '66%' }]} />
            </View>
            
            {/* Corner Handles - larger touch targets */}
            <View style={[styles.cropCornerHandle, { left: cropBox.x - 15, top: cropBox.y - 15 }]} pointerEvents="none" />
            <View style={[styles.cropCornerHandle, { left: cropBox.x + cropBox.width - 15, top: cropBox.y - 15 }]} pointerEvents="none" />
            <View style={[styles.cropCornerHandle, { left: cropBox.x - 15, top: cropBox.y + cropBox.height - 15 }]} pointerEvents="none" />
            <View style={[styles.cropCornerHandle, { left: cropBox.x + cropBox.width - 15, top: cropBox.y + cropBox.height - 15 }]} pointerEvents="none" />
          </View>

          <View style={styles.cropBottomInfo}>
            <Text style={styles.cropInstructionsText}>Drag corners to resize • Drag inside to move</Text>
          </View>
        </SafeAreaView>
      </Modal>
      
      {/* Full-Size Preview Modal with Zoom and Compare */}
      <Modal
        visible={showPreviewModal}
        animationType="fade"
        transparent={true}
        onRequestClose={() => {
          setShowPreviewModal(false);
          setPreviewShowingOriginal(false);
          setPreviewScale(1);
        }}
      >
        <View style={styles.previewModalContainer}>
          <TouchableOpacity 
            style={styles.previewModalClose}
            onPress={() => {
              setShowPreviewModal(false);
              setPreviewShowingOriginal(false);
              setPreviewScale(1);
            }}
          >
            <Text style={styles.modalCloseIcon}>✕</Text>
          </TouchableOpacity>
          
          {/* Zoom controls */}
          <View style={styles.zoomControls}>
            <TouchableOpacity 
              style={styles.zoomButton}
              onPress={() => setPreviewScale(Math.max(0.5, previewScale - 0.5))}
            >
              <Text style={styles.zoomButtonText}>−</Text>
            </TouchableOpacity>
            <Text style={styles.zoomText}>{Math.round(previewScale * 100)}%</Text>
            <TouchableOpacity 
              style={styles.zoomButton}
              onPress={() => setPreviewScale(Math.min(3, previewScale + 0.5))}
            >
              <Text style={styles.zoomButtonText}>+</Text>
            </TouchableOpacity>
          </View>
          
          {/* Image display */}
          <ScrollView 
            style={styles.previewScrollView}
            contentContainerStyle={styles.previewScrollContent}
            maximumZoomScale={3}
            minimumZoomScale={0.5}
            showsHorizontalScrollIndicator={false}
            showsVerticalScrollIndicator={false}
          >
            {(stencilImage || originalImage) && (
              <Image
                source={{ uri: previewShowingOriginal ? originalImage! : stencilImage! }}
                style={[styles.previewModalImage, { transform: [{ scale: previewScale }] }]}
                resizeMode="contain"
              />
            )}
          </ScrollView>
          
          {/* Compare toggle button */}
          <TouchableOpacity
            style={[styles.previewCompareButton, previewShowingOriginal && styles.previewCompareButtonActive]}
            onPress={() => setPreviewShowingOriginal(!previewShowingOriginal)}
          >
            <Text style={styles.previewCompareIcon}>{previewShowingOriginal ? '👁️' : '👁️‍🗨️'}</Text>
            <Text style={[styles.previewCompareButtonText, previewShowingOriginal && styles.previewCompareButtonTextActive]}>
              {previewShowingOriginal ? 'Showing Original' : 'Compare with Original'}
            </Text>
          </TouchableOpacity>
          
          <View style={styles.previewModalActions}>
            <TouchableOpacity style={styles.previewActionButton} onPress={saveToDevice}>
              <Text style={styles.previewActionIcon}>💾</Text>
              <Text style={styles.previewActionText}>Save</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.previewActionButton} onPress={printStencil}>
              <Text style={styles.previewActionIcon}>🖨️</Text>
              <Text style={styles.previewActionText}>Print</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.previewActionButton} onPress={shareStencil}>
              <Text style={styles.previewActionIcon}>📤</Text>
              <Text style={styles.previewActionText}>Share</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0F0F0F',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1F1F1F',
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  headerLogo: {
    width: 40,
    height: 40,
    borderRadius: 8,
  },
  headerTitleContainer: {
    flexDirection: 'column',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: '#fff',
    letterSpacing: 1,
  },
  headerSubtitle: {
    fontSize: 11,
    fontWeight: '500',
    color: '#8B5CF6',
    letterSpacing: 0.5,
  },
  galleryButton: {
    padding: 8,
  },
  iconText: {
    fontSize: 22,
  },
  placeholderIcon: {
    fontSize: 48,
  },
  holdHintIcon: {
    fontSize: 12,
    marginRight: 4,
  },
  compareIconText: {
    fontSize: 16,
    marginRight: 4,
  },
  exportIconText: {
    fontSize: 18,
  },
  closeIcon: {
    fontSize: 24,
    color: '#fff',
    fontWeight: '300',
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 12,
  },
  deleteIcon: {
    fontSize: 20,
  },
  invertIcon: {
    fontSize: 16,
    marginRight: 4,
  },
  modeIcon: {
    fontSize: 16,
    marginRight: 4,
  },
  generateIcon: {
    fontSize: 20,
    marginRight: 6,
  },
  saveIcon: {
    fontSize: 18,
    marginRight: 6,
  },
  sliderIcon: {
    fontSize: 16,
    marginRight: 8,
  },
  modalCloseIcon: {
    fontSize: 28,
    color: '#fff',
    fontWeight: '300',
    backgroundColor: 'rgba(0,0,0,0.5)',
    width: 36,
    height: 36,
    borderRadius: 18,
    textAlign: 'center',
    lineHeight: 36,
  },
  zoomButtonText: {
    fontSize: 24,
    color: '#fff',
    fontWeight: '300',
  },
  previewCompareIcon: {
    fontSize: 18,
    marginRight: 6,
  },
  previewActionIcon: {
    fontSize: 22,
    marginBottom: 4,
  },
  content: {
    flex: 1,
    paddingHorizontal: 20,
  },
  previewSection: {
    marginTop: 20,
    minHeight: 200,
  },
  placeholderContainer: {
    height: 200,
    backgroundColor: '#1A1A1A',
    borderRadius: 16,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: '#2D2D2D',
    borderStyle: 'dashed',
  },
  placeholderText: {
    color: '#6B7280',
    fontSize: 16,
    marginTop: 12,
  },
  imagesContainer: {
    gap: 16,
  },
  imageWrapper: {
    backgroundColor: '#1A1A1A',
    borderRadius: 16,
    padding: 12,
  },
  imageLabelRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  imageLabel: {
    color: '#9CA3AF',
    fontSize: 14,
    fontWeight: '600',
  },
  holdHintContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(139, 92, 246, 0.15)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    gap: 4,
  },
  holdHintText: {
    color: '#8B5CF6',
    fontSize: 11,
    fontWeight: '500',
  },
  stencilLabelRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  updatingBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(139, 92, 246, 0.2)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  updatingText: {
    color: '#8B5CF6',
    fontSize: 12,
    fontWeight: '500',
    marginLeft: 6,
  },
  stencilImageContainer: {
    position: 'relative',
  },
  imageUpdating: {
    opacity: 0.6,
  },
  previewImage: {
    width: '100%',
    height: 250,
    borderRadius: 12,
    backgroundColor: '#0F0F0F',
  },
  sourceButtons: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 20,
  },
  sourceButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#374151',
    paddingVertical: 14,
    borderRadius: 12,
    gap: 8,
  },
  sourceButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  buttonIcon: {
    fontSize: 20,
  },
  toolIcon: {
    fontSize: 18,
  },
  resetButton: {
    backgroundColor: '#374151',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  settingsSection: {
    marginTop: 24,
    backgroundColor: '#1A1A1A',
    borderRadius: 16,
    padding: 16,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#fff',
  },
  sectionTitleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  liveUpdateHint: {
    fontSize: 12,
    color: '#10B981',
    fontWeight: '500',
  },
  sliderContainer: {
    marginBottom: 20,
  },
  sliderHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  sliderLabel: {
    color: '#D1D5DB',
    fontSize: 15,
    fontWeight: '500',
    marginLeft: 8,
    flex: 1,
  },
  sliderValueContainer: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  miniLoader: {
    marginRight: 6,
  },
  sliderValue: {
    color: '#8B5CF6',
    fontSize: 14,
    fontWeight: '600',
  },
  slider: {
    width: '100%',
    height: 40,
  },
  invertToggle: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
  },
  invertToggleLeft: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  invertToggleLabel: {
    color: '#D1D5DB',
    fontSize: 15,
    fontWeight: '500',
    marginLeft: 8,
  },
  toggleSwitch: {
    width: 50,
    height: 28,
    backgroundColor: '#374151',
    borderRadius: 14,
    padding: 3,
  },
  toggleSwitchActive: {
    backgroundColor: '#8B5CF6',
  },
  toggleKnob: {
    width: 22,
    height: 22,
    backgroundColor: '#fff',
    borderRadius: 11,
  },
  toggleKnobActive: {
    marginLeft: 'auto',
  },
  actionButtons: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 24,
  },
  processButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#8B5CF6',
    paddingVertical: 16,
    borderRadius: 12,
    gap: 8,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.98 }],
  },
  processButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  saveButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1A1A1A',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#8B5CF6',
    gap: 8,
  },
  saveButtonText: {
    color: '#8B5CF6',
    fontSize: 16,
    fontWeight: '700',
  },
  bottomSpacer: {
    height: 40,
  },
  // Gallery Modal Styles
  galleryContainer: {
    flex: 1,
    backgroundColor: '#0F0F0F',
  },
  galleryHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#1F1F1F',
  },
  galleryTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: '#fff',
  },
  closeButton: {
    padding: 4,
  },
  galleryScroll: {
    flex: 1,
    paddingHorizontal: 20,
    paddingTop: 16,
  },
  galleryItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  galleryImage: {
    width: 80,
    height: 80,
    borderRadius: 8,
    backgroundColor: '#0F0F0F',
  },
  galleryItemInfo: {
    flex: 1,
    marginLeft: 12,
  },
  galleryItemName: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  galleryItemDate: {
    color: '#6B7280',
    fontSize: 13,
    marginTop: 4,
  },
  deleteButton: {
    padding: 8,
  },
  emptyGallery: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyText: {
    color: '#6B7280',
    fontSize: 16,
    marginTop: 12,
  },
  loader: {
    flex: 1,
    justifyContent: 'center',
  },
  // Save Modal Styles
  saveModalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 20,
  },
  saveModalContent: {
    width: '100%',
    backgroundColor: '#1A1A1A',
    borderRadius: 16,
    padding: 24,
  },
  saveModalTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#fff',
    marginBottom: 16,
    textAlign: 'center',
  },
  saveModalInput: {
    backgroundColor: '#0F0F0F',
    borderRadius: 12,
    padding: 16,
    color: '#fff',
    fontSize: 16,
    borderWidth: 1,
    borderColor: '#2D2D2D',
  },
  saveModalButtons: {
    flexDirection: 'row',
    marginTop: 20,
    gap: 12,
  },
  saveModalCancel: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#374151',
    alignItems: 'center',
  },
  saveModalCancelText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  saveModalSave: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#8B5CF6',
    alignItems: 'center',
  },
  saveModalSaveText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  // Edit Tools Styles
  editToolsSection: {
    marginTop: 16,
    backgroundColor: '#1A1A1A',
    borderRadius: 16,
    padding: 16,
  },
  editToolsTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#9CA3AF',
    marginBottom: 12,
  },
  editToolsRow: {
    flexDirection: 'row',
    gap: 12,
  },
  editToolButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#0F0F0F',
    paddingVertical: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#2D2D2D',
    gap: 8,
  },
  editToolButtonText: {
    color: '#8B5CF6',
    fontSize: 14,
    fontWeight: '600',
  },
  // Crop Modal Styles
  cropModalContainer: {
    flex: 1,
    backgroundColor: '#0F0F0F',
  },
  cropModalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#1F1F1F',
  },
  cropModalTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#fff',
  },
  cropHeaderButton: {
    padding: 8,
  },
  cropApplyText: {
    color: '#10B981',
    fontSize: 16,
    fontWeight: '600',
  },
  cropCancelText: {
    color: '#fff',
    fontSize: 24,
    fontWeight: '400',
  },
  // Visual Crop Styles
  cropAreaContainer: {
    flex: 1,
    margin: 20,
    position: 'relative',
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
    overflow: 'hidden',
  },
  cropFullImage: {
    width: '100%',
    height: '100%',
  },
  cropDarkOverlay: {
    position: 'absolute',
    backgroundColor: 'rgba(0, 0, 0, 0.6)',
  },
  cropBoxBorder: {
    position: 'absolute',
    borderWidth: 2,
    borderColor: '#8B5CF6',
    backgroundColor: 'transparent',
  },
  cropGridLineH: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: 1,
    backgroundColor: 'rgba(255, 255, 255, 0.3)',
  },
  cropGridLineV: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    width: 1,
    backgroundColor: 'rgba(255, 255, 255, 0.3)',
  },
  cropCornerHandle: {
    position: 'absolute',
    width: 24,
    height: 24,
    backgroundColor: '#8B5CF6',
    borderRadius: 12,
    borderWidth: 3,
    borderColor: '#fff',
  },
  cropCornerTL: {},
  cropCornerTR: {},
  cropCornerBL: {},
  cropCornerBR: {},
  cropBottomInfo: {
    padding: 16,
    alignItems: 'center',
    backgroundColor: '#1A1A1A',
  },
  cropInstructionsText: {
    color: '#9CA3AF',
    fontSize: 14,
    textAlign: 'center',
  },
  cropBackgroundImage: {
    width: '100%',
    height: '100%',
  },
  cropOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },
  cropDarkArea: {
    position: 'absolute',
    backgroundColor: 'rgba(0, 0, 0, 0.6)',
  },
  cropBox: {
    position: 'absolute',
    borderWidth: 2,
    borderColor: '#8B5CF6',
    backgroundColor: 'transparent',
  },
  cropGridLine: {
    position: 'absolute',
    backgroundColor: 'rgba(255, 255, 255, 0.3)',
  },
  cropGridLineHorizontal: {
    left: 0,
    right: 0,
    height: 1,
  },
  cropGridLineVertical: {
    top: 0,
    bottom: 0,
    width: 1,
  },
  cropHandle: {
    position: 'absolute',
    width: 24,
    height: 24,
    backgroundColor: '#8B5CF6',
    borderRadius: 12,
    borderWidth: 3,
    borderColor: '#fff',
  },
  cropHandleTopLeft: {},
  cropHandleTopRight: {},
  cropHandleBottomLeft: {},
  cropHandleBottomRight: {},
  cropBottomBar: {
    padding: 16,
    alignItems: 'center',
    backgroundColor: '#1A1A1A',
  },
  cropInstructions: {
    color: '#9CA3AF',
    fontSize: 14,
  },
  // Legacy crop styles (keep for compatibility)
  cropPreviewContainer: {
    flex: 1,
    padding: 20,
    justifyContent: 'center',
    alignItems: 'center',
  },
  cropPreviewImage: {
    width: '100%',
    height: '100%',
    maxHeight: 300,
    borderRadius: 12,
  },
  cropControls: {
    padding: 20,
    backgroundColor: '#1A1A1A',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
  },
  cropControlsTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fff',
    marginBottom: 16,
  },
  cropSliderRow: {
    marginBottom: 16,
  },
  cropSliderLabel: {
    color: '#9CA3AF',
    fontSize: 14,
    marginBottom: 8,
  },
  cropSlider: {
    width: '100%',
    height: 40,
  },
  cropInfoRow: {
    alignItems: 'center',
    marginTop: 8,
  },
  cropInfoText: {
    color: '#6B7280',
    fontSize: 12,
  },
  // Mode Selection Styles
  modeSection: {
    marginTop: 20,
    backgroundColor: '#1A1A1A',
    borderRadius: 16,
    padding: 16,
  },
  modeSectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#fff',
    marginBottom: 12,
  },
  modeToggle: {
    flexDirection: 'row',
    gap: 12,
  },
  modeButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: '#8B5CF6',
    backgroundColor: 'transparent',
    gap: 8,
  },
  modeButtonActive: {
    backgroundColor: '#8B5CF6',
  },
  modeButtonText: {
    color: '#8B5CF6',
    fontSize: 14,
    fontWeight: '600',
  },
  modeButtonTextActive: {
    color: '#fff',
  },
  // Color Selection Styles
  colorSection: {
    marginTop: 16,
  },
  colorSectionTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: '#9CA3AF',
    marginBottom: 10,
  },
  colorOptions: {
    flexDirection: 'row',
    gap: 10,
  },
  colorOption: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    borderRadius: 8,
    borderWidth: 2,
    backgroundColor: '#0F0F0F',
    gap: 6,
  },
  colorOptionActive: {
    backgroundColor: 'rgba(139, 92, 246, 0.15)',
  },
  colorDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
  },
  colorOptionText: {
    color: '#D1D5DB',
    fontSize: 12,
    fontWeight: '500',
  },
  // AI Button Styles
  aiButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#7C3AED',
    paddingVertical: 16,
    borderRadius: 12,
    gap: 8,
  },
  aiButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  // Export buttons
  exportButtons: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#2D2D2D',
  },
  exportButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: 12,
    gap: 6,
  },
  exportButtonText: {
    color: '#9CA3AF',
    fontSize: 13,
    fontWeight: '500',
  },
  // Expand button
  expandButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  expandButtonText: {
    color: '#8B5CF6',
    fontSize: 12,
    fontWeight: '500',
  },
  // Updating overlay
  updatingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: 12,
    flexDirection: 'row',
    gap: 8,
  },
  // Full-size preview modal
  previewModalContainer: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.95)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  previewModalClose: {
    position: 'absolute',
    top: 50,
    right: 20,
    zIndex: 10,
  },
  previewModalImage: {
    width: SCREEN_WIDTH - 40,
    height: SCREEN_HEIGHT * 0.5,
    borderRadius: 12,
  },
  previewModalActions: {
    flexDirection: 'row',
    marginTop: 20,
    gap: 30,
  },
  previewActionButton: {
    alignItems: 'center',
    gap: 6,
  },
  previewActionText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '500',
  },
  // Zoom controls
  zoomControls: {
    flexDirection: 'row',
    alignItems: 'center',
    position: 'absolute',
    top: 50,
    left: 20,
    zIndex: 10,
    backgroundColor: 'rgba(0,0,0,0.5)',
    borderRadius: 20,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  zoomButton: {
    padding: 8,
  },
  zoomText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
    minWidth: 50,
    textAlign: 'center',
  },
  previewScrollView: {
    flex: 1,
    width: '100%',
  },
  previewScrollContent: {
    flexGrow: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  previewCompareHint: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(139, 92, 246, 0.2)',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    marginBottom: 10,
    gap: 8,
  },
  previewCompareText: {
    color: '#8B5CF6',
    fontSize: 13,
    fontWeight: '500',
  },
  // Preview compare button
  previewCompareButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'transparent',
    borderWidth: 2,
    borderColor: '#8B5CF6',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 25,
    marginBottom: 15,
    gap: 8,
  },
  previewCompareButtonActive: {
    backgroundColor: '#8B5CF6',
  },
  previewCompareButtonText: {
    color: '#8B5CF6',
    fontSize: 14,
    fontWeight: '600',
  },
  previewCompareButtonTextActive: {
    color: '#fff',
  },
  // Compare button for main view
  compareButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'transparent',
    borderWidth: 2,
    borderColor: '#8B5CF6',
    paddingVertical: 10,
    borderRadius: 10,
    marginTop: 10,
    gap: 8,
  },
  compareButtonActive: {
    backgroundColor: '#8B5CF6',
  },
  compareButtonText: {
    color: '#8B5CF6',
    fontSize: 14,
    fontWeight: '600',
  },
  compareButtonTextActive: {
    color: '#fff',
  },
  // Crop modal styles
  cropPreviewArea: {
    flex: 1,
    margin: 20,
    position: 'relative',
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
    overflow: 'hidden',
  },
  cropIndicator: {
    position: 'absolute',
    borderWidth: 2,
    borderColor: '#8B5CF6',
    backgroundColor: 'transparent',
  },
  cropSliders: {
    padding: 20,
    backgroundColor: '#1A1A1A',
  },
  cropImageArea: {
    flex: 1,
    margin: 20,
    position: 'relative',
  },
  cropDarkOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
  },
  cropInstructionsText: {
    color: '#9CA3AF',
    fontSize: 14,
    textAlign: 'center',
  },
});
