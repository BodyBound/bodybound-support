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
import * as Print from 'expo-print';
import * as MediaLibrary from 'expo-media-library';
import * as FileSystem from 'expo-file-system';
import * as StoreReview from 'expo-store-review';
import { Share as RNShare } from 'react-native';
import Slider from '@react-native-community/slider';
import { Ionicons } from '@expo/vector-icons';
import Svg, { Path } from 'react-native-svg';
import { captureRef } from 'react-native-view-shot';

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
  // Welcome screen state - shows every time app opens
  const [showWelcome, setShowWelcome] = useState(true);
  
  const [originalImage, setOriginalImage] = useState<string | null>(null);
  const [stencilImage, setStencilImage] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isLiveUpdating, setIsLiveUpdating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isSavingToDevice, setIsSavingToDevice] = useState(false);
  const [showGallery, setShowGallery] = useState(false);
  const [savedStencils, setSavedStencils] = useState<StencilListItem[]>([]);
  const [loadingGallery, setLoadingGallery] = useState(false);
  const [stencilName, setStencilName] = useState('');
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [hasGeneratedOnce, setHasGeneratedOnce] = useState(false);
  
  // Background removal state
  const [isRemovingBackground, setIsRemovingBackground] = useState(false);
  
  // Handmade Stencil states
  const [isGeneratingAI, setIsGeneratingAI] = useState(false);
  // Simplified: Only Handmade Stencil mode with black lines
  const lineColor = 'black'; // Fixed to black
  
  // 3-Version Stencil Generation
  const [stencilVersions, setStencilVersions] = useState<{
    light: string | null;
    medium: string | null;
    heavy: string | null;
  }>({ light: null, medium: null, heavy: null });
  const [selectedVersion, setSelectedVersion] = useState<'light' | 'medium' | 'heavy'>('medium');
  const [isGeneratingVersions, setIsGeneratingVersions] = useState(false);
  const [generationProgress, setGenerationProgress] = useState(0); // 0, 1, 2, 3 for progress
  
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
  
  // Photo library grid state (Instagram-style selector)
  const [photoLibrary, setPhotoLibrary] = useState<MediaLibrary.Asset[]>([]);
  const [loadingPhotos, setLoadingPhotos] = useState(false);
  const [hasPhotoPermission, setHasPhotoPermission] = useState(false);
  const [photoLibraryEndCursor, setPhotoLibraryEndCursor] = useState<string | undefined>(undefined);
  const [hasMorePhotos, setHasMorePhotos] = useState(true);
  
  // Edit Mode state - Overlay + Apple Pencil Drawing
  const [showEditModal, setShowEditModal] = useState(false);
  const [editOpacity, setEditOpacity] = useState(0.5); // Stencil opacity over original
  const [drawingPaths, setDrawingPaths] = useState<string[]>([]); // SVG path strings
  const [currentPath, setCurrentPath] = useState<string>(''); // Current drawing path
  const [brushSize, setBrushSize] = useState(3); // Brush size in pixels
  const [isEraser, setIsEraser] = useState(false); // Eraser mode
  const [editedStencil, setEditedStencil] = useState<string | null>(null); // Saved edited version
  const editCanvasRef = useRef<View>(null); // Ref for capturing the canvas
  
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
  
  // Settings state - defaults optimized for detailed stencils (kept for potential future use)
  const [settings, setSettings] = useState<StencilSettings>({
    clarity: 30,  // Lower = more detail captured
    line_weight: 40,  // Medium line weight
    noise_reduction: 30,  // Lower = more detail preserved
    invert: true,
  });

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

  // Load photo library on mount (after welcome screen)
  useEffect(() => {
    if (!showWelcome) {
      loadPhotoLibrary();
    }
  }, [showWelcome]);

  // Function to load photos from device library
  const loadPhotoLibrary = async (loadMore = false) => {
    if (loadingPhotos) return;
    if (loadMore && !hasMorePhotos) return;

    setLoadingPhotos(true);
    try {
      const { status } = await MediaLibrary.requestPermissionsAsync();
      if (status !== 'granted') {
        setHasPhotoPermission(false);
        Alert.alert('Permission Required', 'Please allow access to your photo library to browse photos.');
        return;
      }
      setHasPhotoPermission(true);

      const mediaResult = await MediaLibrary.getAssetsAsync({
        mediaType: 'photo',
        first: 50,
        after: loadMore ? photoLibraryEndCursor : undefined,
        sortBy: [MediaLibrary.SortBy.creationTime],
      });

      if (loadMore) {
        setPhotoLibrary(prev => [...prev, ...mediaResult.assets]);
      } else {
        setPhotoLibrary(mediaResult.assets);
      }
      
      setPhotoLibraryEndCursor(mediaResult.endCursor);
      setHasMorePhotos(mediaResult.hasNextPage);
    } catch (error) {
      console.error('Error loading photo library:', error);
    } finally {
      setLoadingPhotos(false);
    }
  };

  // Select a photo from the library grid
  const selectPhotoFromLibrary = async (asset: MediaLibrary.Asset) => {
    try {
      console.log('[SelectPhoto] Starting photo selection for asset:', asset.id);
      
      // Get the asset info with local URI
      const assetInfo = await MediaLibrary.getAssetInfoAsync(asset);
      console.log('[SelectPhoto] Asset info received, localUri exists:', !!assetInfo.localUri);
      
      if (assetInfo.localUri) {
        // Use ImageManipulator to ensure consistent image handling across platforms
        // This handles HEIC conversion, proper encoding, and prevents iOS-specific issues
        console.log('[SelectPhoto] Processing image with ImageManipulator...');
        const manipulatedImage = await ImageManipulator.manipulateAsync(
          assetInfo.localUri,
          [{ resize: { width: 1500 } }], // Resize for optimal AI processing
          { 
            compress: 0.85, 
            format: ImageManipulator.SaveFormat.JPEG, 
            base64: true 
          }
        );
        
        if (manipulatedImage.base64) {
          console.log('[SelectPhoto] Image processed successfully, base64 length:', manipulatedImage.base64.length);
          const base64Image = `data:image/jpeg;base64,${manipulatedImage.base64}`;
          setOriginalImage(base64Image);
          setStencilImage(null);
          setStencilVersions({ light: null, medium: null, heavy: null });
          setHasGeneratedOnce(false);
        } else {
          console.error('[SelectPhoto] ImageManipulator did not return base64 data');
          Alert.alert('Error', 'Could not process the selected photo. Please try another.');
        }
      } else {
        console.error('[SelectPhoto] No localUri available for asset');
        Alert.alert('Error', 'Could not access the selected photo. Please try another.');
      }
    } catch (error: any) {
      console.error('[SelectPhoto] Error selecting photo:', error);
      Alert.alert('Error', `Could not load the selected photo: ${error.message || 'Unknown error'}`);
    }
  };

  // Legacy pickImage function (fallback)
  const pickImage = async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission Required', 'Please allow access to your photo library to select images.');
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: false,
      quality: 0.8,
      base64: true,
    });

    if (!result.canceled && result.assets[0].base64) {
      const base64Image = `data:image/jpeg;base64,${result.assets[0].base64}`;
      setOriginalImage(base64Image);
      setStencilImage(null);
      setStencilVersions({ light: null, medium: null, heavy: null });
      setHasGeneratedOnce(false);
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

  // AI-Powered Stencil Generation - Generate 3 versions
  const generateAIStencil = async () => {
    if (!originalImage) {
      Alert.alert('No Image', 'Please select an image first.');
      return;
    }

    // Validate image data before sending - check for proper base64 format
    console.log('[GenerateAI] Original image length:', originalImage.length);
    console.log('[GenerateAI] Image prefix:', originalImage.substring(0, 50));
    
    // Validate the base64 data is properly formatted
    if (!originalImage.startsWith('data:image/')) {
      console.error('[GenerateAI] Invalid image format - missing data URI prefix');
      Alert.alert('Invalid Image', 'The selected image format is not valid. Please select a different photo.');
      return;
    }
    
    // Check that the base64 portion isn't too short (indicating corruption)
    const base64Part = originalImage.split(',')[1];
    if (!base64Part || base64Part.length < 1000) {
      console.error('[GenerateAI] Base64 data appears corrupted or too short:', base64Part?.length);
      Alert.alert('Image Error', 'The image data appears corrupted. Please select a different photo.');
      return;
    }

    setIsGeneratingAI(true);
    setIsGeneratingVersions(true);
    setGenerationProgress(0);
    setStencilVersions({ light: null, medium: null, heavy: null });
    
    const versions: { light: string | null; medium: string | null; heavy: string | null } = {
      light: null,
      medium: null,
      heavy: null
    };
    
    try {
      // Generate Light version - Clean lines only, no texture, no black
      setGenerationProgress(1);
      console.log('[GenerateAI] Starting Light version, sending base64 length:', base64Part.length);
      const lightResponse = await fetch(`${API_URL}/api/ai-stencil`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: originalImage,
          style: 'tattoo',
          line_color: lineColor,
          shading_detail: 5,
          solid_fill: 0,
        }),
      });
      console.log('[GenerateAI] Light response status:', lightResponse.status);
      if (lightResponse.ok) {
        const lightData = await lightResponse.json();
        versions.light = lightData.stencil_base64;
        setStencilVersions({ ...versions });
        console.log('[GenerateAI] Light version received, length:', lightData.stencil_base64?.length);
      } else {
        const errorText = await lightResponse.text();
        console.log('[GenerateAI] Light version error:', errorText);
      }

      // Generate Medium version - Clean lines + texture/contour, NO black fill
      setGenerationProgress(2);
      console.log('[GenerateAI] Starting Medium version...');
      const mediumResponse = await fetch(`${API_URL}/api/ai-stencil`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: originalImage,
          style: 'tattoo',
          line_color: lineColor,
          shading_detail: 30,
          solid_fill: 0,
        }),
      });
      console.log('[GenerateAI] Medium response status:', mediumResponse.status);
      if (mediumResponse.ok) {
        const mediumData = await mediumResponse.json();
        versions.medium = mediumData.stencil_base64;
        setStencilVersions({ ...versions });
        console.log('[GenerateAI] Medium version received, length:', mediumData.stencil_base64?.length);
      } else {
        const errorText = await mediumResponse.text();
        console.log('[GenerateAI] Medium version error:', errorText);
      }

      // Generate Heavy version - Texture AND solid black (moderate)
      setGenerationProgress(3);
      console.log('[GenerateAI] Starting Heavy version...');
      const heavyResponse = await fetch(`${API_URL}/api/ai-stencil`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: originalImage,
          style: 'tattoo',
          line_color: lineColor,
          shading_detail: 50,
          solid_fill: 30,
        }),
      });
      console.log('[GenerateAI] Heavy response status:', heavyResponse.status);
      if (heavyResponse.ok) {
        const heavyData = await heavyResponse.json();
        versions.heavy = heavyData.stencil_base64;
        setStencilVersions({ ...versions });
        console.log('[GenerateAI] Heavy version received, length:', heavyData.stencil_base64?.length);
      } else {
        const errorText = await heavyResponse.text();
        console.log('[GenerateAI] Heavy version error:', errorText);
      }

      // Set the medium version as default selected
      setSelectedVersion('medium');
      if (versions.medium) {
        setStencilImage(versions.medium);
      } else if (versions.light) {
        setStencilImage(versions.light);
        setSelectedVersion('light');
      } else if (versions.heavy) {
        setStencilImage(versions.heavy);
        setSelectedVersion('heavy');
      }
      
      // Show error if no versions generated
      if (!versions.light && !versions.medium && !versions.heavy) {
        Alert.alert('Generation Failed', 'Could not generate stencils. Please try again or use a different image.');
      }
      
      setHasGeneratedOnce(true);
    } catch (error: any) {
      console.error('Error generating stencil versions:', error);
      Alert.alert('Error', error.message || 'Failed to generate stencils. Please try again.');
    } finally {
      setIsGeneratingAI(false);
      setIsGeneratingVersions(false);
      setGenerationProgress(0);
    }
  };

  // Select a stencil version
  const selectVersion = (version: 'light' | 'medium' | 'heavy') => {
    setSelectedVersion(version);
    const selectedStencil = stencilVersions[version];
    if (selectedStencil) {
      setStencilImage(selectedStencil);
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

  // Save stencil to device photo gallery using MediaLibrary with proper PNG quality
  const saveToPhotoGallery = async (imageBase64: string, filename: string = 'stencil'): Promise<boolean> => {
    try {
      console.log('[SaveToGallery] Starting save process...');
      
      // Validate input
      if (!imageBase64) {
        console.log('[SaveToGallery] ERROR: imageBase64 is undefined or empty');
        Alert.alert('Error', 'No image data to save.');
        return false;
      }
      
      console.log('[SaveToGallery] Image data length:', imageBase64.length);
      
      // Request MediaLibrary permissions
      const permissionResult = await MediaLibrary.requestPermissionsAsync();
      console.log('[SaveToGallery] Permission result:', JSON.stringify(permissionResult));
      
      if (permissionResult.status !== 'granted') {
        console.log('[SaveToGallery] Permission denied');
        Alert.alert(
          'Permission Required',
          'Please allow access to your photo library to save stencils. Go to Settings > Body Bound > Photos.',
          [{ text: 'OK' }]
        );
        return false;
      }

      console.log('[SaveToGallery] Permission granted, processing image...');
      
      // Use ImageManipulator to convert base64 to a file URI
      // This is the most reliable method for Expo SDK 54
      const manipulatedImage = await ImageManipulator.manipulateAsync(
        imageBase64,
        [], // No transformations needed
        { 
          format: ImageManipulator.SaveFormat.PNG,
          compress: 1, // Full quality for stencils
        }
      );
      
      console.log('[SaveToGallery] Image manipulated, URI:', manipulatedImage.uri);

      // Save directly to photo gallery using MediaLibrary
      const asset = await MediaLibrary.createAssetAsync(manipulatedImage.uri);
      console.log('[SaveToGallery] Asset created:', asset.id, 'filename:', asset.filename);
      
      // Try to create/use album, but don't fail if it doesn't work
      try {
        const albumName = 'Body Bound Stencils';
        let album = await MediaLibrary.getAlbumAsync(albumName);
        
        if (album === null) {
          await MediaLibrary.createAlbumAsync(albumName, asset, false);
          console.log('[SaveToGallery] Album created');
        } else {
          await MediaLibrary.addAssetsToAlbumAsync([asset], album, false);
          console.log('[SaveToGallery] Added to existing album');
        }
      } catch (albumError) {
        console.log('[SaveToGallery] Album operation failed (non-critical):', albumError);
        // Album creation is optional, image is already saved to gallery
      }

      console.log('[SaveToGallery] SUCCESS!');
      Alert.alert('Saved!', 'Stencil saved to your photo gallery.');
      return true;
    } catch (error: any) {
      console.error('[SaveToGallery] ERROR:', error?.message || error);
      Alert.alert(
        'Save Failed', 
        `Could not save stencil: ${error?.message || 'Unknown error'}. Please check app permissions.`
      );
      return false;
    }
  };

  // Export current stencil to device
  const saveToDevice = async () => {
    if (!stencilImage) {
      Alert.alert('Error', 'No stencil to save.');
      return;
    }

    setIsSavingToDevice(true);
    await saveToPhotoGallery(stencilImage, 'body_bound_stencil');
    setIsSavingToDevice(false);
  };

  // Export saved stencil from gallery to device
  const [exportingStencilId, setExportingStencilId] = useState<string | null>(null);
  
  const exportStencilToDevice = async (stencilId: string) => {
    setExportingStencilId(stencilId);
    try {
      // Fetch full stencil data from API
      const response = await fetch(`${API_URL}/api/stencils/${stencilId}`);
      if (!response.ok) {
        throw new Error('Failed to load stencil');
      }
      const stencilData = await response.json();
      
      await saveToPhotoGallery(stencilData.stencil_image, stencilData.name || 'stencil');
    } catch (error) {
      console.error('Error exporting stencil:', error);
      Alert.alert('Error', 'Failed to load stencil data.');
    } finally {
      setExportingStencilId(null);
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

  // Share stencil - saves to gallery directly
  const shareStencil = async () => {
    if (!stencilImage) {
      Alert.alert('Error', 'No stencil to share.');
      return;
    }

    // Use the save to gallery function directly
    await saveToPhotoGallery(stencilImage, 'body_bound_stencil');
  };

  // Request App Store review
  const requestAppReview = async () => {
    try {
      const isAvailable = await StoreReview.isAvailableAsync();
      if (isAvailable) {
        await StoreReview.requestReview();
      } else {
        // Fallback: open App Store directly
        // Replace with your actual App Store URL once published
        Alert.alert(
          'Thank You! 🙏',
          'We appreciate your support! The review prompt will be available after you\'ve used the app a bit more.',
          [{ text: 'OK' }]
        );
      }
    } catch (error) {
      console.error('Error requesting review:', error);
    }
  };

  // Share app with friends
  const shareAppWithFriends = async () => {
    try {
      const result = await RNShare.share({
        message: 'Check out Body Bound Stencil Generator! Transform photos into tattoo stencils as good as handmade. 🎨✨',
        // Add your App Store URL here once published:
        // url: 'https://apps.apple.com/app/body-bound-stencil-generator/id6741930631',
      });
      
      if (result.action === RNShare.sharedAction) {
        console.log('App shared successfully');
      }
    } catch (error) {
      console.error('Error sharing app:', error);
    }
  };

  // ============ EDIT MODE FUNCTIONS ============
  
  // Open edit modal and reset drawing state
  const openEditMode = () => {
    setDrawingPaths([]);
    setCurrentPath('');
    setEditOpacity(0.5);
    setBrushSize(3);
    setIsEraser(false);
    setShowEditModal(true);
  };

  // Handle touch start for drawing
  const handleDrawStart = (event: GestureResponderEvent) => {
    const { locationX, locationY } = event.nativeEvent;
    setCurrentPath(`M${locationX},${locationY}`);
  };

  // Handle touch move for drawing
  const handleDrawMove = (event: GestureResponderEvent) => {
    const { locationX, locationY } = event.nativeEvent;
    if (currentPath) {
      setCurrentPath(prev => `${prev} L${locationX},${locationY}`);
    }
  };

  // Handle touch end for drawing
  const handleDrawEnd = () => {
    if (currentPath) {
      if (isEraser) {
        // For eraser, we'll mark the path with a special prefix
        setDrawingPaths(prev => [...prev, `ERASER:${currentPath}`]);
      } else {
        setDrawingPaths(prev => [...prev, currentPath]);
      }
      setCurrentPath('');
    }
  };

  // Undo last drawing stroke
  const undoLastStroke = () => {
    setDrawingPaths(prev => prev.slice(0, -1));
  };

  // Clear all drawings
  const clearAllDrawings = () => {
    Alert.alert(
      'Clear All Drawings',
      'Are you sure you want to remove all your drawings?',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Clear', style: 'destructive', onPress: () => setDrawingPaths([]) }
      ]
    );
  };

  // Save the edited stencil
  const saveEditedStencil = async () => {
    if (!editCanvasRef.current) {
      Alert.alert('Error', 'Could not capture the edited image.');
      return;
    }

    try {
      // Capture the canvas as an image
      const uri = await captureRef(editCanvasRef, {
        format: 'png',
        quality: 1,
        result: 'base64',
      });
      
      const editedImage = `data:image/png;base64,${uri}`;
      setEditedStencil(editedImage);
      setStencilImage(editedImage);
      setShowEditModal(false);
      
      Alert.alert('Success', 'Your edited stencil has been saved!');
    } catch (error: any) {
      console.error('Error saving edited stencil:', error);
      Alert.alert('Error', 'Failed to save the edited stencil. Please try again.');
    }
  };

  // Save edited stencil to gallery
  const saveEditedToGallery = async () => {
    if (!editCanvasRef.current) {
      Alert.alert('Error', 'Could not capture the edited image.');
      return;
    }

    try {
      // Capture the canvas as an image
      const uri = await captureRef(editCanvasRef, {
        format: 'png',
        quality: 1,
        result: 'base64',
      });
      
      await saveToPhotoGallery(`data:image/png;base64,${uri}`, 'body_bound_edited_stencil');
    } catch (error: any) {
      console.error('Error saving to gallery:', error);
      Alert.alert('Error', 'Failed to save to gallery. Please try again.');
    }
  };

  // ============ END EDIT MODE FUNCTIONS ============

  const loadGallery = async () => {
    setLoadingGallery(true);
    try {
      // Use the lightweight list endpoint for faster gallery loading
      const response = await fetch(`${API_URL}/api/stencils/list`);
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

  const loadStencilFromGallery = async (stencilItem: StencilListItem) => {
    // Fetch full stencil details when user selects from gallery
    try {
      const response = await fetch(`${API_URL}/api/stencils/${stencilItem.id}`);
      if (!response.ok) {
        throw new Error('Failed to load stencil');
      }
      const stencil = await response.json();
      setOriginalImage(stencil.original_image);
      setStencilImage(stencil.stencil_image);
      setSettings(stencil.settings);
      setShowGallery(false);
    } catch (error) {
      console.error('Error loading stencil:', error);
      Alert.alert('Error', 'Failed to load stencil.');
    }
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
          {isLiveUpdating && <ActivityIndicator size="small" color="#C9A227" style={styles.miniLoader} />}
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
        minimumTrackTintColor="#C9A227"
        maximumTrackTintColor="#3D3428"
        thumbTintColor="#C9A227"
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
          <ActivityIndicator size="large" color="#C9A227" style={styles.loader} />
        ) : savedStencils.length === 0 ? (
          <View style={styles.emptyGallery}>
            <Text style={styles.emptyIcon}>🖼️</Text>
            <Text style={styles.emptyText}>No saved stencils yet</Text>
          </View>
        ) : (
          <ScrollView style={styles.galleryScroll}>
            {savedStencils.map((stencil) => (
              <View key={stencil.id} style={styles.galleryItemContainer}>
                <TouchableOpacity
                  style={styles.galleryItem}
                  onPress={() => loadStencilFromGallery(stencil)}
                >
                  <Image
                    source={{ uri: stencil.stencil_thumbnail || '' }}
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
                    onPress={(e) => {
                      e.stopPropagation();
                      deleteStencil(stencil.id);
                    }}
                    style={styles.deleteButton}
                  >
                    <Text style={styles.deleteIcon}>🗑️</Text>
                  </TouchableOpacity>
                </TouchableOpacity>
              </View>
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

  // Welcome Screen Component
  const renderWelcomeScreen = () => (
    <SafeAreaView style={styles.welcomeContainer}>
      <View style={styles.welcomeContent}>
        {/* Logo */}
        <Image 
          source={require('../assets/images/logo.png')} 
          style={styles.welcomeLogo}
          resizeMode="contain"
        />
        
        {/* App Title */}
        <Text style={styles.welcomeTitle}>BODY BOUND</Text>
        <Text style={styles.welcomeSubtitle}>Stencil Generator</Text>
        
        {/* Tagline */}
        <Text style={styles.welcomeTagline}>
          Transform photos into{'\n'}tattoo stencils as good as handmade
        </Text>
        
        {/* Get Started Button */}
        <TouchableOpacity
          style={styles.welcomeButton}
          onPress={() => setShowWelcome(false)}
          activeOpacity={0.8}
        >
          <Text style={styles.welcomeButtonText}>Get Started</Text>
          <Text style={styles.welcomeButtonArrow}>→</Text>
        </TouchableOpacity>
        
        {/* Footer Note */}
        <Text style={styles.welcomeFooter}>
          for tattoo artists • developed by a tattoo artist
        </Text>
        
        {/* Version Number */}
        <Text style={styles.welcomeVersion}>v1.4.1</Text>
      </View>
    </SafeAreaView>
  );

  // Show welcome screen if active
  if (showWelcome) {
    return renderWelcomeScreen();
  }

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
            <>
              {/* Photo Library Grid - Instagram style */}
              <View style={styles.photoLibraryContainer}>
                <View style={styles.photoLibraryHeader}>
                  <Text style={styles.photoLibraryTitle}>Select a Photo</Text>
                  <TouchableOpacity style={styles.cameraButton} onPress={takePhoto}>
                    <Text style={styles.cameraButtonIcon}>📷</Text>
                    <Text style={styles.cameraButtonText}>Camera</Text>
                  </TouchableOpacity>
                </View>
                
                {loadingPhotos && photoLibrary.length === 0 ? (
                  <View style={styles.loadingPhotosContainer}>
                    <ActivityIndicator size="large" color="#C9A227" />
                    <Text style={styles.loadingPhotosText}>Loading photos...</Text>
                  </View>
                ) : !hasPhotoPermission && photoLibrary.length === 0 ? (
                  <View style={styles.noPhotosContainer}>
                    <Text style={styles.noPhotosIcon}>🔒</Text>
                    <Text style={styles.noPhotosText}>Photo access required</Text>
                    <TouchableOpacity style={styles.grantAccessButton} onPress={loadPhotoLibrary}>
                      <Text style={styles.grantAccessButtonText}>Grant Access</Text>
                    </TouchableOpacity>
                  </View>
                ) : (
                  <ScrollView 
                    horizontal={false}
                    showsVerticalScrollIndicator={false}
                    style={styles.photoGrid}
                    onScrollEndDrag={() => {
                      if (hasMorePhotos && !loadingPhotos) {
                        loadPhotoLibrary(true);
                      }
                    }}
                  >
                    <View style={styles.photoGridInner}>
                      {photoLibrary.map((asset, index) => (
                        <TouchableOpacity
                          key={asset.id}
                          style={styles.photoGridItem}
                          onPress={() => selectPhotoFromLibrary(asset)}
                          activeOpacity={0.7}
                        >
                          <Image
                            source={{ uri: asset.uri }}
                            style={styles.photoGridImage}
                            resizeMode="cover"
                          />
                        </TouchableOpacity>
                      ))}
                    </View>
                    {loadingPhotos && photoLibrary.length > 0 && (
                      <ActivityIndicator size="small" color="#C9A227" style={{ marginVertical: 10 }} />
                    )}
                    {hasMorePhotos && !loadingPhotos && (
                      <TouchableOpacity style={styles.loadMoreButton} onPress={() => loadPhotoLibrary(true)}>
                        <Text style={styles.loadMoreText}>Load More Photos</Text>
                      </TouchableOpacity>
                    )}
                  </ScrollView>
                )}
              </View>
            </>
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
                    <TouchableOpacity style={styles.exportButton} onPress={openEditMode}>
                      <Text style={[styles.exportIconText, { color: '#10B981' }]}>✏️</Text>
                      <Text style={styles.exportButtonText}>Edit</Text>
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

        {/* Compact Tools Row - Crop + Generate side by side */}
        {originalImage && (
          <View style={styles.compactToolsContainer}>
            {/* Crop Button - Compact */}
            <TouchableOpacity 
              style={styles.compactCropButton} 
              onPress={openCropModal}
            >
              <Text style={styles.compactToolIcon}>✂️</Text>
              <Text style={styles.compactToolText}>Crop</Text>
            </TouchableOpacity>

            {/* Generate Button - Takes most space */}
            <Pressable
              style={({ pressed }) => [
                styles.compactGenerateButton,
                isGeneratingAI && styles.buttonDisabled,
                pressed && !isGeneratingAI && styles.buttonPressed
              ]}
              onPress={generateAIStencil}
              disabled={isGeneratingAI}
            >
              {isGeneratingAI ? (
                <>
                  <ActivityIndicator size="small" color="#0A0A0A" />
                  <Text style={styles.compactGenerateText}>Creating...</Text>
                </>
              ) : (
                <>
                  <Text style={styles.compactGenerateIcon}>✨</Text>
                  <Text style={styles.compactGenerateText}>Generate Stencil</Text>
                </>
              )}
            </Pressable>
          </View>
        )}

        {/* Compact Version Selector - Only shows after generation */}
        {originalImage && (stencilVersions.light || stencilVersions.medium || stencilVersions.heavy) && (
          <View style={styles.compactVersionSection}>
            <View style={styles.compactVersionRow}>
              <TouchableOpacity
                style={[
                  styles.compactVersionButton,
                  selectedVersion === 'light' && styles.compactVersionSelected,
                  !stencilVersions.light && styles.compactVersionDisabled
                ]}
                onPress={() => stencilVersions.light && selectVersion('light')}
                disabled={!stencilVersions.light}
              >
                <Text style={styles.compactVersionEmoji}>✏️</Text>
                <Text style={[
                  styles.compactVersionText,
                  selectedVersion === 'light' && styles.compactVersionTextSelected
                ]}>Light</Text>
              </TouchableOpacity>
              
              <TouchableOpacity
                style={[
                  styles.compactVersionButton,
                  selectedVersion === 'medium' && styles.compactVersionSelected,
                  !stencilVersions.medium && styles.compactVersionDisabled
                ]}
                onPress={() => stencilVersions.medium && selectVersion('medium')}
                disabled={!stencilVersions.medium}
              >
                <Text style={styles.compactVersionEmoji}>🖊️</Text>
                <Text style={[
                  styles.compactVersionText,
                  selectedVersion === 'medium' && styles.compactVersionTextSelected
                ]}>Medium</Text>
              </TouchableOpacity>
              
              <TouchableOpacity
                style={[
                  styles.compactVersionButton,
                  selectedVersion === 'heavy' && styles.compactVersionSelected,
                  !stencilVersions.heavy && styles.compactVersionDisabled
                ]}
                onPress={() => stencilVersions.heavy && selectVersion('heavy')}
                disabled={!stencilVersions.heavy}
              >
                <Text style={styles.compactVersionEmoji}>🖋️</Text>
                <Text style={[
                  styles.compactVersionText,
                  selectedVersion === 'heavy' && styles.compactVersionTextSelected
                ]}>Heavy</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* Generation Progress - Compact */}
        {isGeneratingVersions && (
          <View style={styles.compactProgressSection}>
            <Text style={styles.compactProgressText}>
              Generating {generationProgress}/3: {generationProgress === 1 ? 'Light' : generationProgress === 2 ? 'Medium' : generationProgress === 3 ? 'Heavy' : '...'}
            </Text>
            <View style={styles.compactProgressDots}>
              <View style={[styles.compactDot, generationProgress >= 1 && styles.compactDotComplete]} />
              <View style={[styles.compactDot, generationProgress >= 2 && styles.compactDotComplete]} />
              <View style={[styles.compactDot, generationProgress >= 3 && styles.compactDotComplete]} />
            </View>
          </View>
        )}

        {/* Save Button - Only visible when stencil exists */}
        {originalImage && stencilImage && (
          <View style={styles.saveButtonsRow}>
            <TouchableOpacity
              style={styles.saveButton}
              onPress={() => setShowSaveModal(true)}
            >
              <Text style={styles.saveIcon}>💾</Text>
              <Text style={styles.saveButtonText}>Save</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Minimal Share Section - Just icons */}
        <View style={styles.minimalShareRow}>
          <TouchableOpacity style={styles.minimalShareButton} onPress={requestAppReview}>
            <Text style={styles.minimalShareIcon}>⭐</Text>
          </TouchableOpacity>
          <Text style={styles.minimalShareDivider}>|</Text>
          <TouchableOpacity style={styles.minimalShareButton} onPress={shareAppWithFriends}>
            <Text style={styles.minimalShareIcon}>🔗</Text>
          </TouchableOpacity>
          <Text style={styles.minimalShareText}>Rate & Share</Text>
        </View>

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

      {/* Edit Mode Modal - Overlay + Drawing */}
      <Modal
        visible={showEditModal}
        animationType="slide"
        transparent={false}
        onRequestClose={() => setShowEditModal(false)}
      >
        <SafeAreaView style={styles.editModalContainer}>
          {/* Header */}
          <View style={styles.editModalHeader}>
            <TouchableOpacity onPress={() => setShowEditModal(false)}>
              <Text style={styles.editModalCloseText}>Cancel</Text>
            </TouchableOpacity>
            <Text style={styles.editModalTitle}>Edit Stencil</Text>
            <TouchableOpacity onPress={saveEditedStencil}>
              <Text style={styles.editModalSaveText}>Done</Text>
            </TouchableOpacity>
          </View>

          {/* Drawing Canvas Area */}
          <View 
            ref={editCanvasRef}
            style={styles.editCanvasContainer}
            onStartShouldSetResponder={() => true}
            onMoveShouldSetResponder={() => true}
            onResponderGrant={handleDrawStart}
            onResponderMove={handleDrawMove}
            onResponderRelease={handleDrawEnd}
          >
            {/* Original image as background */}
            {originalImage && (
              <Image
                source={{ uri: originalImage }}
                style={styles.editBackgroundImage}
                resizeMode="contain"
              />
            )}
            
            {/* Stencil overlay with adjustable opacity */}
            {stencilImage && (
              <Image
                source={{ uri: stencilImage }}
                style={[styles.editStencilOverlay, { opacity: editOpacity }]}
                resizeMode="contain"
              />
            )}
            
            {/* SVG Drawing Layer */}
            <Svg style={styles.editDrawingLayer}>
              {/* Existing paths */}
              {drawingPaths.map((path, index) => {
                const isEraserPath = path.startsWith('ERASER:');
                const actualPath = isEraserPath ? path.replace('ERASER:', '') : path;
                return (
                  <Path
                    key={index}
                    d={actualPath}
                    stroke={isEraserPath ? '#FFFFFF' : '#000000'}
                    strokeWidth={isEraserPath ? brushSize * 3 : brushSize}
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                );
              })}
              {/* Current drawing path */}
              {currentPath && (
                <Path
                  d={currentPath}
                  stroke={isEraser ? '#FFFFFF' : '#000000'}
                  strokeWidth={isEraser ? brushSize * 3 : brushSize}
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              )}
            </Svg>
          </View>

          {/* Controls */}
          <View style={styles.editControlsContainer}>
            {/* Opacity Slider */}
            <View style={styles.editSliderRow}>
              <Text style={styles.editSliderLabel}>Stencil Opacity</Text>
              <Slider
                style={styles.editSlider}
                minimumValue={0}
                maximumValue={1}
                value={editOpacity}
                onValueChange={setEditOpacity}
                minimumTrackTintColor="#C9A227"
                maximumTrackTintColor="#333"
                thumbTintColor="#C9A227"
              />
              <Text style={styles.editSliderValue}>{Math.round(editOpacity * 100)}%</Text>
            </View>

            {/* Brush Size Slider */}
            <View style={styles.editSliderRow}>
              <Text style={styles.editSliderLabel}>Brush Size</Text>
              <Slider
                style={styles.editSlider}
                minimumValue={1}
                maximumValue={15}
                value={brushSize}
                onValueChange={setBrushSize}
                minimumTrackTintColor="#C9A227"
                maximumTrackTintColor="#333"
                thumbTintColor="#C9A227"
              />
              <Text style={styles.editSliderValue}>{Math.round(brushSize)}px</Text>
            </View>

            {/* Tool Buttons */}
            <View style={styles.editToolsRow}>
              <TouchableOpacity 
                style={[styles.editToolButton, !isEraser && styles.editToolButtonActive]}
                onPress={() => setIsEraser(false)}
              >
                <Text style={styles.editToolIcon}>✏️</Text>
                <Text style={[styles.editToolText, !isEraser && styles.editToolTextActive]}>Draw</Text>
              </TouchableOpacity>
              
              <TouchableOpacity 
                style={[styles.editToolButton, isEraser && styles.editToolButtonActive]}
                onPress={() => setIsEraser(true)}
              >
                <Text style={styles.editToolIcon}>🧹</Text>
                <Text style={[styles.editToolText, isEraser && styles.editToolTextActive]}>Eraser</Text>
              </TouchableOpacity>
              
              <TouchableOpacity 
                style={styles.editToolButton}
                onPress={undoLastStroke}
              >
                <Text style={styles.editToolIcon}>↩️</Text>
                <Text style={styles.editToolText}>Undo</Text>
              </TouchableOpacity>
              
              <TouchableOpacity 
                style={styles.editToolButton}
                onPress={clearAllDrawings}
              >
                <Text style={styles.editToolIcon}>🗑️</Text>
                <Text style={styles.editToolText}>Clear</Text>
              </TouchableOpacity>
            </View>

            {/* Save to Gallery Button */}
            <TouchableOpacity style={styles.editSaveToGalleryButton} onPress={saveEditedToGallery}>
              <Text style={styles.editSaveToGalleryIcon}>📤</Text>
              <Text style={styles.editSaveToGalleryText}>Save to Photos</Text>
            </TouchableOpacity>
          </View>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  // LUXURY DARK THEME - Brass Filigree & Black Leather
  container: {
    flex: 1,
    backgroundColor: '#0A0A0A',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderBottomWidth: 2,
    borderBottomColor: '#C9A227',
    backgroundColor: '#0D0D0D',
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  headerLogo: {
    width: 42,
    height: 42,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#C9A227',
  },
  headerTitleContainer: {
    flexDirection: 'column',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: '#C9A227',
    letterSpacing: 2,
  },
  headerSubtitle: {
    fontSize: 10,
    fontWeight: '600',
    color: '#8B7355',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  galleryButton: {
    padding: 8,
    borderWidth: 1,
    borderColor: '#C9A227',
    borderRadius: 8,
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
    color: '#C9A227',
    fontWeight: '300',
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 12,
  },
  deleteIcon: {
    fontSize: 16,
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
    color: '#C9A227',
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
    paddingHorizontal: 16,
  },
  previewSection: {
    marginTop: 12,
    flex: 1,
    minHeight: 300,
  },
  placeholderContainer: {
    flex: 1,
    minHeight: 350,
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
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
    flex: 1,
    gap: 12,
  },
  imageWrapper: {
    flex: 1,
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
    padding: 10,
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
    backgroundColor: 'rgba(201, 162, 39, 0.15)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    gap: 4,
  },
  holdHintText: {
    color: '#C9A227',
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
    backgroundColor: 'rgba(201, 162, 39, 0.2)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  updatingText: {
    color: '#C9A227',
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
    height: 500,
    borderRadius: 12,
    backgroundColor: '#0F0F0F',
  },
  sourceButtons: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 12,
  },
  sourceButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1A1510',
    paddingVertical: 10,
    borderRadius: 10,
    gap: 6,
    borderWidth: 1,
    borderColor: '#3D3428',
  },
  sourceButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  buttonIcon: {
    fontSize: 16,
  },
  toolIcon: {
    fontSize: 18,
  },
  resetButton: {
    backgroundColor: '#1A1510',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#3D3428',
  },
  settingsSection: {
    marginTop: 24,
    backgroundColor: '#1A1A1A',
    borderRadius: 16,
    padding: 16,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#C9A227',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  sectionTitleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  liveUpdateHint: {
    fontSize: 11,
    color: '#C9A227',
    fontWeight: '600',
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
    color: '#A89060',
    fontSize: 14,
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
    color: '#C9A227',
    fontSize: 14,
    fontWeight: '700',
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
    color: '#A89060',
    fontSize: 14,
    fontWeight: '500',
    marginLeft: 8,
  },
  toggleSwitch: {
    width: 50,
    height: 28,
    backgroundColor: '#1A1510',
    borderRadius: 14,
    padding: 3,
    borderWidth: 1,
    borderColor: '#3D3428',
  },
  toggleSwitchActive: {
    backgroundColor: '#C9A227',
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
    gap: 10,
    marginTop: 16,
  },
  actionButtonsContainer: {
    marginTop: 16,
  },
  generateButtonRow: {
    flexDirection: 'row',
    gap: 10,
  },
  saveButtonsRow: {
    flexDirection: 'row',
    gap: 10,
  },
  processButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1A1510',
    paddingVertical: 12,
    borderRadius: 10,
    gap: 6,
    borderWidth: 2,
    borderColor: '#C9A227',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.98 }],
  },
  processButtonText: {
    color: '#C9A227',
    fontSize: 15,
    fontWeight: '700',
  },
  saveButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1A1510',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#C9A227',
    gap: 8,
  },
  saveToDeviceButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#2D5A3D',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#4A9B5C',
    gap: 8,
  },
  saveToDeviceButtonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
  },
  saveButtonText: {
    color: '#C9A227',
    fontSize: 15,
    fontWeight: '700',
  },
  bottomSpacer: {
    height: 40,
  },
  // Gallery Modal Styles - Luxury Theme
  galleryContainer: {
    flex: 1,
    backgroundColor: '#0A0A0A',
  },
  galleryHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 2,
    borderBottomColor: '#C9A227',
    backgroundColor: '#0D0D0D',
  },
  galleryTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: '#C9A227',
    letterSpacing: 1,
  },
  closeButton: {
    padding: 4,
  },
  galleryScroll: {
    flex: 1,
    paddingHorizontal: 20,
    paddingTop: 16,
  },
  galleryItemContainer: {
    backgroundColor: '#0D0D0D',
    borderRadius: 12,
    marginBottom: 12,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: '#3D3428',
  },
  galleryItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
  },
  galleryImage: {
    width: 70,
    height: 70,
    borderRadius: 8,
    backgroundColor: '#1A1510',
    borderWidth: 1,
    borderColor: '#C9A227',
  },
  galleryItemInfo: {
    flex: 1,
    marginLeft: 12,
  },
  galleryItemName: {
    color: '#C9A227',
    fontSize: 14,
    fontWeight: '700',
  },
  galleryItemDate: {
    color: '#6B5D48',
    fontSize: 11,
    marginTop: 4,
  },
  deleteButton: {
    padding: 10,
    backgroundColor: '#5C1F1F',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#8B3A3A',
  },
  // Version Selector Styles - Luxury Theme
  versionSelectorSection: {
    backgroundColor: '#0D0D0D',
    borderRadius: 12,
    padding: 16,
    marginTop: 16,
    borderWidth: 1,
    borderColor: '#C9A227',
  },
  versionSelectorTitle: {
    color: '#C9A227',
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 4,
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  versionSelectorSubtitle: {
    color: '#8B7355',
    fontSize: 11,
    marginBottom: 12,
  },
  versionButtonsRow: {
    flexDirection: 'row',
    gap: 8,
  },
  versionButton: {
    flex: 1,
    backgroundColor: '#1A1510',
    borderRadius: 10,
    paddingVertical: 12,
    paddingHorizontal: 6,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#3D3428',
  },
  versionButtonSelected: {
    borderColor: '#C9A227',
    backgroundColor: '#1F1A12',
    borderWidth: 2,
  },
  versionButtonDisabled: {
    opacity: 0.4,
  },
  versionButtonEmoji: {
    fontSize: 18,
    marginBottom: 4,
  },
  versionButtonText: {
    color: '#A89060',
    fontSize: 12,
    fontWeight: '700',
  },
  versionButtonTextSelected: {
    color: '#C9A227',
  },
  versionButtonDesc: {
    color: '#6B5D48',
    fontSize: 9,
    marginTop: 2,
    textAlign: 'center',
  },
  // Generation Progress Styles
  generationProgressSection: {
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
    padding: 20,
    marginTop: 16,
    alignItems: 'center',
  },
  generationProgressTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 16,
  },
  progressDotsRow: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 12,
  },
  progressDot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: '#1A1510',
    borderWidth: 1,
    borderColor: '#3D3428',
  },
  progressDotComplete: {
    backgroundColor: '#C9A227',
  },
  generationProgressLabel: {
    color: '#9CA3AF',
    fontSize: 14,
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
    backgroundColor: '#1A1510',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#3D3428',
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
    backgroundColor: '#C9A227',
    alignItems: 'center',
  },
  saveModalSaveText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
  // NEW COMPACT UI STYLES
  compactToolsContainer: {
    flexDirection: 'row',
    marginTop: 12,
    gap: 10,
    alignItems: 'center',
  },
  compactCropButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1A1A1A',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 25,
    borderWidth: 1,
    borderColor: '#333',
    gap: 6,
  },
  compactToolIcon: {
    fontSize: 16,
  },
  compactToolText: {
    color: '#9CA3AF',
    fontSize: 13,
    fontWeight: '600',
  },
  compactGenerateButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#C9A227',
    paddingVertical: 14,
    borderRadius: 25,
    gap: 8,
  },
  compactGenerateIcon: {
    fontSize: 18,
  },
  compactGenerateText: {
    color: '#0A0A0A',
    fontSize: 15,
    fontWeight: '700',
  },
  compactVersionSection: {
    marginTop: 10,
  },
  compactVersionRow: {
    flexDirection: 'row',
    gap: 8,
  },
  compactVersionButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1A1A1A',
    paddingVertical: 10,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#333',
    gap: 4,
  },
  compactVersionSelected: {
    backgroundColor: '#C9A227',
    borderColor: '#C9A227',
  },
  compactVersionDisabled: {
    opacity: 0.4,
  },
  compactVersionEmoji: {
    fontSize: 14,
  },
  compactVersionText: {
    color: '#9CA3AF',
    fontSize: 12,
    fontWeight: '600',
  },
  compactVersionTextSelected: {
    color: '#0A0A0A',
  },
  compactProgressSection: {
    marginTop: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
  },
  compactProgressText: {
    color: '#C9A227',
    fontSize: 13,
    fontWeight: '500',
  },
  compactProgressDots: {
    flexDirection: 'row',
    gap: 6,
  },
  compactDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#333',
  },
  compactDotComplete: {
    backgroundColor: '#C9A227',
  },
  // Edit Tools Styles (legacy - keeping for reference)
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
    color: '#C9A227',
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
    borderColor: '#C9A227',
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
    backgroundColor: '#C9A227',
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
    borderColor: '#C9A227',
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
    backgroundColor: '#C9A227',
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
    marginTop: 12,
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
    padding: 12,
  },
  modeSectionTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: '#fff',
    marginBottom: 8,
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
    borderColor: '#C9A227',
    backgroundColor: 'transparent',
    gap: 8,
  },
  modeButtonActive: {
    backgroundColor: '#C9A227',
  },
  modeButtonText: {
    color: '#C9A227',
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
    backgroundColor: 'rgba(201, 162, 39, 0.15)',
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
    backgroundColor: '#C9A227',
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
    color: '#C9A227',
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
    backgroundColor: 'rgba(201, 162, 39, 0.2)',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
    marginBottom: 10,
    gap: 8,
  },
  previewCompareText: {
    color: '#C9A227',
    fontSize: 13,
    fontWeight: '500',
  },
  // Preview compare button
  previewCompareButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'transparent',
    borderWidth: 2,
    borderColor: '#C9A227',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 25,
    marginBottom: 15,
    gap: 8,
  },
  previewCompareButtonActive: {
    backgroundColor: '#C9A227',
  },
  previewCompareButtonText: {
    color: '#C9A227',
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
    borderColor: '#C9A227',
    paddingVertical: 10,
    borderRadius: 10,
    marginTop: 10,
    gap: 8,
  },
  compareButtonActive: {
    backgroundColor: '#C9A227',
  },
  compareButtonText: {
    color: '#C9A227',
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
    borderColor: '#C9A227',
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
  // Welcome Screen Styles
  welcomeContainer: {
    flex: 1,
    backgroundColor: '#0A0A0A',
  },
  welcomeContent: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 30,
    paddingBottom: 40,
  },
  welcomeLogo: {
    width: 120,
    height: 120,
    borderRadius: 20,
    marginBottom: 24,
    borderWidth: 2,
    borderColor: '#C9A227',
  },
  welcomeTitle: {
    fontSize: 28,
    fontWeight: '900',
    color: '#C9A227',
    letterSpacing: 3,
    textAlign: 'center',
  },
  welcomeSubtitle: {
    fontSize: 14,
    fontWeight: '600',
    color: '#8B7355',
    letterSpacing: 2,
    marginTop: 4,
    marginBottom: 30,
    textTransform: 'uppercase',
  },
  welcomeTagline: {
    fontSize: 15,
    color: '#A89060',
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 40,
    paddingHorizontal: 10,
    fontStyle: 'italic',
  },
  welcomeButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#C9A227',
    paddingVertical: 16,
    paddingHorizontal: 50,
    borderRadius: 30,
    gap: 10,
    marginBottom: 30,
  },
  welcomeButtonText: {
    fontSize: 16,
    fontWeight: '800',
    color: '#0A0A0A',
    letterSpacing: 1,
  },
  welcomeButtonArrow: {
    fontSize: 18,
    color: '#0A0A0A',
    fontWeight: '300',
  },
  welcomeFooter: {
    fontSize: 11,
    color: '#6B5D48',
    textAlign: 'center',
    fontStyle: 'italic',
    letterSpacing: 0.5,
  },
  welcomeVersion: {
    fontSize: 10,
    color: '#4A4A4A',
    textAlign: 'center',
    marginTop: 20,
    fontFamily: 'monospace',
  },
  // Photo Library Grid Styles
  photoLibraryContainer: {
    flex: 1,
    minHeight: 400,
  },
  photoLibraryHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  photoLibraryTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#C9A227',
  },
  cameraButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1A1510',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#C9A227',
    gap: 6,
  },
  cameraButtonIcon: {
    fontSize: 16,
  },
  cameraButtonText: {
    color: '#C9A227',
    fontSize: 14,
    fontWeight: '600',
  },
  loadingPhotosContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    minHeight: 300,
  },
  loadingPhotosText: {
    color: '#9CA3AF',
    marginTop: 12,
    fontSize: 14,
  },
  noPhotosContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    minHeight: 300,
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
  },
  noPhotosIcon: {
    fontSize: 40,
    marginBottom: 12,
  },
  noPhotosText: {
    color: '#9CA3AF',
    fontSize: 16,
    marginBottom: 20,
  },
  grantAccessButton: {
    backgroundColor: '#C9A227',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 25,
  },
  grantAccessButtonText: {
    color: '#0A0A0A',
    fontSize: 14,
    fontWeight: '600',
  },
  photoGrid: {
    flex: 1,
  },
  photoGridInner: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
  },
  photoGridItem: {
    width: (SCREEN_WIDTH - 40 - 8) / 3,
    aspectRatio: 1,
    borderRadius: 4,
    overflow: 'hidden',
  },
  photoGridImage: {
    width: '100%',
    height: '100%',
  },
  loadMoreButton: {
    alignItems: 'center',
    paddingVertical: 16,
    marginTop: 8,
  },
  loadMoreText: {
    color: '#C9A227',
    fontSize: 14,
    fontWeight: '500',
  },
  // Share & Review Section Styles
  shareReviewSection: {
    marginTop: 30,
    backgroundColor: '#1A1510',
    borderRadius: 16,
    padding: 20,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(201, 162, 39, 0.3)',
  },
  shareReviewTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#C9A227',
    marginBottom: 6,
    textAlign: 'center',
  },
  shareReviewSubtitle: {
    fontSize: 14,
    color: '#9CA3AF',
    marginBottom: 16,
    textAlign: 'center',
  },
  shareReviewButtons: {
    flexDirection: 'row',
    gap: 12,
  },
  reviewButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#C9A227',
    paddingVertical: 12,
    borderRadius: 25,
    gap: 6,
  },
  reviewButtonIcon: {
    fontSize: 16,
  },
  reviewButtonText: {
    color: '#0A0A0A',
    fontSize: 14,
    fontWeight: '600',
  },
  shareAppButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'transparent',
    borderWidth: 2,
    borderColor: '#C9A227',
    paddingVertical: 12,
    borderRadius: 25,
    gap: 6,
  },
  shareAppButtonIcon: {
    fontSize: 16,
  },
  shareAppButtonText: {
    color: '#C9A227',
    fontSize: 14,
    fontWeight: '600',
  },
  
  // ========== EDIT MODE STYLES ==========
  editModalContainer: {
    flex: 1,
    backgroundColor: '#0A0A0A',
  },
  editModalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#C9A227',
    backgroundColor: '#0D0D0D',
  },
  editModalCloseText: {
    color: '#9CA3AF',
    fontSize: 16,
    fontWeight: '500',
  },
  editModalTitle: {
    color: '#C9A227',
    fontSize: 18,
    fontWeight: '700',
    letterSpacing: 1,
  },
  editModalSaveText: {
    color: '#C9A227',
    fontSize: 16,
    fontWeight: '700',
  },
  editCanvasContainer: {
    flex: 1,
    backgroundColor: '#1A1A1A',
    position: 'relative',
  },
  editBackgroundImage: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    height: '100%',
  },
  editStencilOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    height: '100%',
  },
  editDrawingLayer: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    height: '100%',
  },
  editControlsContainer: {
    backgroundColor: '#0D0D0D',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: '#333',
  },
  editSliderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  editSliderLabel: {
    color: '#E5E5E5',
    fontSize: 13,
    fontWeight: '500',
    width: 100,
  },
  editSlider: {
    flex: 1,
    height: 40,
  },
  editSliderValue: {
    color: '#C9A227',
    fontSize: 13,
    fontWeight: '600',
    width: 45,
    textAlign: 'right',
  },
  editToolsRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginTop: 8,
    marginBottom: 16,
  },
  editToolButton: {
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: '#1A1A1A',
    minWidth: 65,
  },
  editToolButtonActive: {
    backgroundColor: '#C9A227',
  },
  editToolIcon: {
    fontSize: 20,
    marginBottom: 4,
  },
  editToolText: {
    color: '#9CA3AF',
    fontSize: 11,
    fontWeight: '500',
  },
  editToolTextActive: {
    color: '#0A0A0A',
    fontWeight: '700',
  },
  editSaveToGalleryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#C9A227',
    paddingVertical: 14,
    borderRadius: 25,
    gap: 8,
  },
  editSaveToGalleryIcon: {
    fontSize: 18,
  },
  editSaveToGalleryText: {
    color: '#0A0A0A',
    fontSize: 16,
    fontWeight: '700',
  },
});
