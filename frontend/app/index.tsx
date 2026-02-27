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
import { Image as ExpoImage } from 'expo-image';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as ImagePicker from 'expo-image-picker';
import * as ImageManipulator from 'expo-image-manipulator';
import * as Print from 'expo-print';
import * as MediaLibrary from 'expo-media-library';
import * as FileSystem from 'expo-file-system/legacy';
import * as StoreReview from 'expo-store-review';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Share as RNShare } from 'react-native';
import Slider from '@react-native-community/slider';
import { Ionicons } from '@expo/vector-icons';
import Svg, { Path, Circle } from 'react-native-svg';
import { Gesture, GestureDetector, GestureHandlerRootView, PointerType } from 'react-native-gesture-handler';
import Animated, { useSharedValue, useAnimatedStyle, runOnJS, useDerivedValue, withSpring } from 'react-native-reanimated';
import { captureRef } from 'react-native-view-shot';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

// Onboarding tutorial slides
const ONBOARDING_SLIDES = [
  {
    id: 1,
    icon: '🎨',
    title: 'Welcome to BODY BOUND',
    subtitle: 'Professional Stencil Generator',
    description: 'Transform any photo into a precise tattoo stencil in seconds. Let\'s walk you through how it works.',
    buttonText: 'Get Started',
  },
  {
    id: 2,
    icon: '📷',
    title: 'Step 1: Choose Your Photo',
    subtitle: 'Select or Capture',
    description: 'Tap the camera icon to select a photo from your gallery or take a new one. For best results, use clear, well-lit images.',
    buttonText: 'Next',
  },
  {
    id: 3,
    icon: '✨',
    title: 'Step 2: Generate Stencils',
    subtitle: 'Three Detail Levels',
    description: 'LIGHT - Simple clean outlines\nMEDIUM - Outlines + dotted guide lines\nHEAVY - Full detail with contours\n\nTap GENERATE to create all three!',
    buttonText: 'Next',
  },
  {
    id: 4,
    icon: '✏️',
    title: 'Step 3: Edit & Export',
    subtitle: 'iPad Pro Features',
    description: '• Apple Pencil to draw/refine\n• Two fingers to zoom & pan\n• Double-tap to undo\n• Tap Save to export to Photos',
    buttonText: 'Start Creating!',
  },
];
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
  // Layer System: Store reference photo separately so it persists through edit sessions
  const [referencePhotoLayer, setReferencePhotoLayer] = useState<string | null>(null);
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
  
  // Onboarding tutorial state
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [onboardingSlide, setOnboardingSlide] = useState(0);
  const [hasSeenOnboarding, setHasSeenOnboarding] = useState(true); // Default true until we check
  
  // Background removal state
  const [isRemovingBackground, setIsRemovingBackground] = useState(false);
  
  // Handmade Stencil states
  const [isGeneratingAI, setIsGeneratingAI] = useState(false);
  // Simplified: Only Handmade Stencil mode with black lines
  const lineColor = 'black'; // Fixed to black
  
  // Auto-enhance image before generation (AI upscaling)
  const [autoEnhance, setAutoEnhance] = useState(true);
  
  // Line weight control (-5 to +5)
  const [lineWeight, setLineWeight] = useState(0);
  
  // 3-Version Stencil Generation
  const [stencilVersions, setStencilVersions] = useState<{
    light: string | null;
    medium: string | null;
    heavy: string | null;
  }>({ light: null, medium: null, heavy: null });
  const [selectedVersion, setSelectedVersion] = useState<'light' | 'medium' | 'heavy'>('medium');
  const [isGeneratingVersions, setIsGeneratingVersions] = useState(false);
  const [generationProgress, setGenerationProgress] = useState(0); // 0, 1, 2, 3 for progress
  const [regeneratingStyle, setRegeneratingStyle] = useState<string | null>(null); // Which single style is being regenerated
  const [isExportingPSD, setIsExportingPSD] = useState(false); // Loading state for saving both images
  
  // Dot marks for pencil taps (for better sensitivity)
  const [dotMarks, setDotMarks] = useState<{x: number, y: number, size: number}[]>([]);
  
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
  
  // Image Quality Validation state
  const [imageQualityWarnings, setImageQualityWarnings] = useState<string[]>([]);
  const [imageQualitySuggestions, setImageQualitySuggestions] = useState<string[]>([]);
  const [isValidatingImage, setIsValidatingImage] = useState(false);
  const [showQualityWarning, setShowQualityWarning] = useState(false);
  
  // Edit Mode state - Overlay + Apple Pencil Drawing
  const [showEditModal, setShowEditModal] = useState(false);
  const [editOpacity, setEditOpacity] = useState(0.5); // Stencil opacity over original
  const [drawingPaths, setDrawingPaths] = useState<string[]>([]); // SVG path strings
  const [currentPath, setCurrentPath] = useState<string>(''); // Current drawing path
  const [currentPoints, setCurrentPoints] = useState<{x: number, y: number}[]>([]); // Points for smooth curve
  const [brushSize, setBrushSize] = useState(3); // Brush size in pixels
  const [isEraser, setIsEraser] = useState(false); // Eraser mode
  const [enableFingerPainting, setEnableFingerPainting] = useState(false); // Like Procreate: OFF = pencil only
  const [editedStencil, setEditedStencil] = useState<string | null>(null); // Saved edited version
  const [originalAIStencil, setOriginalAIStencil] = useState<string | null>(null); // Original AI stencil (for revert)
  const persistentReferencePhotoRef = useRef<string | null>(null); // NEVER changes once set - for edit mode (using ref for reliability)
  const [isCapturingForExport, setIsCapturingForExport] = useState(false); // Hide original when saving
  const [showEditHint, setShowEditHint] = useState(true); // Show double-tap hint on first entry
  const [editModeStencilImage, setEditModeStencilImage] = useState<string | null>(null); // Frozen stencil for edit mode
  const [editModeOriginalImage, setEditModeOriginalImage] = useState<string | null>(null); // Frozen original for edit mode
  const editCanvasRef = useRef<View>(null); // Ref for capturing the canvas
  const lastTapTimeRef = useRef<number>(0); // For double-tap detection
  
  // Shared values for Reanimated (for smooth gesture handling)
  const scale = useSharedValue(1);
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);
  const rotation = useSharedValue(0); // Canvas rotation in radians
  const savedScale = useSharedValue(1);
  const savedTranslateX = useSharedValue(0);
  const savedTranslateY = useSharedValue(0);
  const savedRotation = useSharedValue(0);
  
  // Shared values for INSTANT touch feedback (no JS bridge delay)
  const touchX = useSharedValue(-1000);
  const touchY = useSharedValue(-1000);
  const isDrawingActive = useSharedValue(false);
  
  // Refs for drawing state (to avoid stale closures in gestures)
  const currentPointsRef = useRef<{x: number, y: number}[]>([]);
  const isDrawingRef = useRef(false);
  const enableFingerPaintingRef = useRef(false);
  const currentScaleRef = useRef(1);
  const currentTranslateXRef = useRef(0);
  const currentTranslateYRef = useRef(0);
  const currentRotationRef = useRef(0);
  
  // Keep ref in sync with state
  useEffect(() => {
    enableFingerPaintingRef.current = enableFingerPainting;
    console.log('[EditMode] enableFingerPainting changed to:', enableFingerPainting);
  }, [enableFingerPainting]);
  
  // Zoom and pan state for Edit mode (legacy - keeping for compatibility)
  const [editScale, setEditScale] = useState(1);
  const [editTranslateX, setEditTranslateX] = useState(0);
  const [editTranslateY, setEditTranslateY] = useState(0);
  const [lastPanX, setLastPanX] = useState(0);
  const [lastPanY, setLastPanY] = useState(0);
  const [lastDistance, setLastDistance] = useState(0);
  const [isPinching, setIsPinching] = useState(false);
  
  // Enhanced gesture refs for better two-finger detection
  const gestureStartTimeRef = useRef<number>(0);
  const isPinchingRef = useRef(false);
  const lastDistanceRef = useRef(0);
  const lastPanRef = useRef({ x: 0, y: 0 });
  const pendingDrawRef = useRef(false); // Track if we're waiting to see if second finger joins
  const drawStartTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const touchCountRef = useRef(0);
  
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

  // Check if user has seen onboarding tutorial
  useEffect(() => {
    const checkOnboarding = async () => {
      try {
        const seen = await AsyncStorage.getItem('hasSeenOnboarding');
        if (seen !== 'true') {
          setHasSeenOnboarding(false);
          setShowOnboarding(true);
        }
      } catch (error) {
        console.log('Error checking onboarding status:', error);
      }
    };
    checkOnboarding();
  }, []);

  // Complete onboarding
  const completeOnboarding = async () => {
    try {
      await AsyncStorage.setItem('hasSeenOnboarding', 'true');
      setHasSeenOnboarding(true);
      setShowOnboarding(false);
      setOnboardingSlide(0);
    } catch (error) {
      console.log('Error saving onboarding status:', error);
      setShowOnboarding(false);
    }
  };

  // Show onboarding again (from help button)
  const showOnboardingTutorial = () => {
    setOnboardingSlide(0);
    setShowOnboarding(true);
  };

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
      console.log('[SelectPhoto] Asset URI:', asset.uri);
      
      // Get the asset info with local URI
      const assetInfo = await MediaLibrary.getAssetInfoAsync(asset);
      console.log('[SelectPhoto] Asset info received, localUri:', assetInfo.localUri);
      
      const uriToUse = assetInfo.localUri || asset.uri;
      console.log('[SelectPhoto] Using URI:', uriToUse);
      
      // Use ImageManipulator to ensure consistent image handling across platforms
      // This handles HEIC conversion, proper encoding, and prevents iOS-specific issues
      console.log('[SelectPhoto] Processing image with ImageManipulator...');
      const manipulatedImage = await ImageManipulator.manipulateAsync(
        uriToUse,
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
        // Reset persistent reference for new photo
        persistentReferencePhotoRef.current = null;
        setOriginalAIStencil(null);
        setDrawingPaths([]);
        setDotMarks([]);
        // Validate the image quality
        validateImageQuality(base64Image);
      } else {
        console.error('[SelectPhoto] ImageManipulator did not return base64 data');
        // Fallback: Try using ImagePicker directly
        console.log('[SelectPhoto] Attempting fallback with ImagePicker...');
        const pickerResult = await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ['images'],
          allowsEditing: false,
          quality: 0.8,
          base64: true,
        });
        
        if (!pickerResult.canceled && pickerResult.assets[0].base64) {
          const base64Image = `data:image/jpeg;base64,${pickerResult.assets[0].base64}`;
          setOriginalImage(base64Image);
          setStencilImage(null);
          setStencilVersions({ light: null, medium: null, heavy: null });
          setHasGeneratedOnce(false);
          // Reset persistent reference for new photo
          persistentReferencePhotoRef.current = null;
          setOriginalAIStencil(null);
          setDrawingPaths([]);
          setDotMarks([]);
          validateImageQuality(base64Image);
        } else {
          Alert.alert('Error', 'Could not process the selected photo. Please try using the Gallery button instead.');
        }
      }
    } catch (error: any) {
      console.error('[SelectPhoto] Error selecting photo:', error);
      Alert.alert('Error', `Could not load the selected photo: ${error.message || 'Unknown error'}. Please try using the Gallery button instead.`);
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
      // Validate the image quality
      validateImageQuality(base64Image);
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
      // Validate the image quality
      validateImageQuality(base64Image);
    }
  };

  // Validate image quality before stencil generation
  const validateImageQuality = async (imageBase64: string) => {
    setIsValidatingImage(true);
    setImageQualityWarnings([]);
    setImageQualitySuggestions([]);
    setShowQualityWarning(false);
    
    try {
      console.log('[ValidateImage] Validating image quality...');
      const response = await fetch(`${API_URL}/api/validate-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_base64: imageBase64 }),
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log('[ValidateImage] Response:', JSON.stringify(data));
        
        if (data.warnings && data.warnings.length > 0) {
          setImageQualityWarnings(data.warnings);
          setImageQualitySuggestions(data.suggestions || []);
          setShowQualityWarning(true);
          console.log('[ValidateImage] Warnings:', data.warnings);
        }
      }
    } catch (error) {
      console.error('[ValidateImage] Error:', error);
      // Don't show error - validation is optional
    } finally {
      setIsValidatingImage(false);
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

  // Helper function to make API calls with timeout (no retry - keep it simple and fast)
  // AI stencil generation can take 60-180 seconds on busy servers, so we use a very long timeout
  const fetchWithTimeout = async (url: string, options: RequestInit, timeoutMs: number = 180000): Promise<Response> => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    
    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      return response;
    } catch (error: any) {
      clearTimeout(timeoutId);
      if (error.name === 'AbortError') {
        throw new Error('AI generation is taking longer than expected. Please try again - the servers may be busy.');
      }
      throw error;
    }
  };

  // Retry wrapper with exponential backoff for more reliable AI generation
  const fetchWithRetry = async (
    url: string, 
    options: RequestInit, 
    maxRetries: number = 3,
    baseDelay: number = 2000
  ): Promise<Response> => {
    let lastError: Error | null = null;
    
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        console.log(`[FetchRetry] Attempt ${attempt}/${maxRetries} for ${url}`);
        const response = await fetchWithTimeout(url, options);
        
        if (response.ok) {
          return response;
        }
        
        // If server error (5xx), retry
        if (response.status >= 500) {
          const errorText = await response.text();
          console.log(`[FetchRetry] Server error ${response.status}: ${errorText}`);
          lastError = new Error(`Server error: ${response.status}`);
          
          if (attempt < maxRetries) {
            const delay = baseDelay * Math.pow(2, attempt - 1); // Exponential backoff
            console.log(`[FetchRetry] Waiting ${delay}ms before retry...`);
            await new Promise(resolve => setTimeout(resolve, delay));
            continue;
          }
        }
        
        // For client errors (4xx), don't retry
        return response;
        
      } catch (error: any) {
        console.log(`[FetchRetry] Attempt ${attempt} failed:`, error.message);
        lastError = error;
        
        if (attempt < maxRetries) {
          const delay = baseDelay * Math.pow(2, attempt - 1);
          console.log(`[FetchRetry] Waiting ${delay}ms before retry...`);
          await new Promise(resolve => setTimeout(resolve, delay));
        }
      }
    }
    
    throw lastError || new Error('All retry attempts failed');
  };

  // AI-Powered Stencil Generation using Async/Polling Architecture
  // This avoids gateway timeouts by:
  // 1. Starting generation (returns immediately with job ID)
  // 2. Polling status endpoint until complete
  // Each poll is quick, so no timeout issues
  const generateAIStencil = async () => {
    if (!originalImage) {
      Alert.alert('No Image', 'Please select an image first.');
      return;
    }

    // Validate image data before sending
    console.log('[GenerateAI] Original image length:', originalImage.length);
    console.log('[GenerateAI] Image prefix:', originalImage.substring(0, 50));
    
    if (!originalImage.startsWith('data:image/')) {
      console.error('[GenerateAI] Invalid image format - missing data URI prefix');
      Alert.alert('Invalid Image', 'The selected image format is not valid. Please select a different photo.');
      return;
    }
    
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
    
    try {
      // Step 1: Start async generation - returns immediately with job ID
      console.log('[GenerateAI] Starting async generation...', autoEnhance ? 'with AI enhancement' : 'without enhancement');
      const startResponse = await fetch(`${API_URL}/api/ai-stencil-async`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: originalImage,
          line_color: lineColor,
          auto_enhance: autoEnhance,
        }),
      });
      
      if (!startResponse.ok) {
        const errorText = await startResponse.text();
        console.error('[GenerateAI] Failed to start job:', errorText);
        throw new Error('Failed to start stencil generation');
      }
      
      const startData = await startResponse.json();
      const jobId = startData.job_id;
      console.log('[GenerateAI] Job started:', jobId);
      
      // Step 2: Poll for status until complete
      let attempts = 0;
      const maxAttempts = 120; // 120 * 2.5s = 5 minutes max
      const pollInterval = 2500; // Poll every 2.5 seconds
      
      while (attempts < maxAttempts) {
        await new Promise(resolve => setTimeout(resolve, pollInterval));
        
        const statusResponse = await fetch(`${API_URL}/api/ai-stencil-status/${jobId}`);
        
        if (!statusResponse.ok) {
          console.error('[GenerateAI] Status check failed');
          attempts++;
          continue;
        }
        
        const statusData = await statusResponse.json();
        console.log(`[GenerateAI] Status: ${statusData.status}, Progress: ${statusData.progress}%, Current: ${statusData.current_style}`);
        
        // Update progress for UI
        if (statusData.progress <= 33) {
          setGenerationProgress(1); // Light
        } else if (statusData.progress <= 66) {
          setGenerationProgress(2); // Medium
        } else {
          setGenerationProgress(3); // Heavy
        }
        
        if (statusData.status === 'completed') {
          console.log('[GenerateAI] Generation completed!');
          
          const versions = {
            light: statusData.result?.light || null,
            medium: statusData.result?.medium || null,
            heavy: statusData.result?.heavy || null
          };
          
          setStencilVersions(versions);
          
          // Set default selection
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
          
          setHasGeneratedOnce(true);
          
          // Clean up job on server
          try {
            await fetch(`${API_URL}/api/ai-stencil-job/${jobId}`, { method: 'DELETE' });
          } catch (e) {
            // Non-critical, ignore
          }
          
          break;
        } else if (statusData.status === 'failed') {
          console.error('[GenerateAI] Job failed:', statusData.error);
          throw new Error(statusData.error || 'Generation failed');
        }
        
        attempts++;
      }
      
      if (attempts >= maxAttempts) {
        throw new Error('Generation timed out. Please try again.');
      }
      
    } catch (error: any) {
      console.error('Error generating stencil versions:', error);
      
      let errorMessage = 'Failed to generate stencils.';
      
      if (error.message?.includes('timed out') || error.message?.includes('timeout')) {
        errorMessage = 'Generation timed out. Please try again.';
      } else if (error.message?.includes('network') || error.message?.includes('Network')) {
        errorMessage = 'Network error. Please check your internet connection and try again.';
      } else if (error.message) {
        errorMessage = error.message;
      }
      
      Alert.alert(
        'Generation Issue',
        errorMessage,
        [{ text: 'OK' }]
      );
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

  // Regenerate a single style (Light, Medium, or Heavy) using AI
  const regenerateSingleStyle = async (style: 'light' | 'medium' | 'heavy') => {
    if (!originalImage || regeneratingStyle) return;
    
    try {
      setRegeneratingStyle(style);
      
      // Get base64 from original image
      let imageBase64 = originalImage;
      if (!imageBase64.startsWith('data:')) {
        const base64Data = await FileSystem.readAsStringAsync(imageBase64, {
          encoding: 'base64',
        });
        imageBase64 = `data:image/jpeg;base64,${base64Data}`;
      }
      
      const base64Part = imageBase64.includes(',') ? imageBase64.split(',')[1] : imageBase64;
      
      console.log(`[RegenerateSingle] Regenerating ${style} version...`);
      
      const response = await fetch(`${API_URL}/api/ai-stencil`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: imageBase64,
          style: 'tattoo',
          line_color: 'black',
          shading_detail: style === 'light' ? 5 : style === 'medium' ? 30 : 50,
          solid_fill: style === 'heavy' ? 30 : 0,
          regenerate_style: style,
        }),
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log(`[RegenerateSingle] ${style} version regenerated successfully`);
        
        // Update only this style in stencilVersions
        setStencilVersions(prev => ({
          ...prev,
          [style]: data.stencil_base64
        }));
        
        // Auto-select the regenerated style
        setSelectedVersion(style);
        setStencilImage(data.stencil_base64);
      } else {
        const errorText = await response.text();
        console.error(`[RegenerateSingle] ${style} version error:`, errorText);
        Alert.alert('Regeneration Failed', `Could not regenerate ${style} version. Please try again.`);
      }
    } catch (error: any) {
      console.error(`Error regenerating ${style} version:`, error);
      Alert.alert('Connection Issue', 'Failed to regenerate. Please check your internet connection.');
    } finally {
      setRegeneratingStyle(null);
    }
  };

  // Generate a single stencil style using original AI pipeline
  const generateSingleStyle = async (style: 'light' | 'medium' | 'heavy') => {
    if (!originalImage || isGeneratingAI || regeneratingStyle) return;
    
    // If this style already exists, just select it
    if (stencilVersions[style]) {
      selectVersion(style);
      return;
    }
    
    try {
      setRegeneratingStyle(style);
      setIsGeneratingAI(true);
      
      // Get base64 from original image
      let imageBase64 = originalImage;
      
      // Safety check - make sure we have an image
      if (!imageBase64) {
        console.error('[GenerateSingle] No original image available');
        Alert.alert('Error', 'No image selected. Please select an image first.');
        return;
      }
      
      console.log(`[GenerateSingle] Image source type: ${imageBase64.substring(0, 30)}...`);
      
      // If the image is not already base64 (e.g., file:// or ph:// URI), convert it
      if (!imageBase64.startsWith('data:')) {
        try {
          console.log(`[GenerateSingle] Converting image from URI to base64...`);
          const base64Data = await FileSystem.readAsStringAsync(imageBase64, {
            encoding: 'base64',
          });
          imageBase64 = `data:image/jpeg;base64,${base64Data}`;
          console.log(`[GenerateSingle] Converted to base64, length: ${imageBase64.length}`);
        } catch (readError: any) {
          console.error('[GenerateSingle] Failed to read image file:', readError);
          Alert.alert('Error', 'Could not read image. Please try selecting the photo again.');
          return;
        }
      }
      
      console.log(`[GenerateSingle] Generating ${style} version, image base64 length: ${imageBase64.length}`);
      
      // Use the original AI async endpoint
      const response = await fetch(`${API_URL}/api/ai-stencil-async`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: imageBase64,
          style: 'tattoo',
          line_color: 'black',
          auto_enhance: autoEnhance,
          single_style: style,
        }),
      });
      
      if (!response.ok) {
        const errorText = await response.text();
        console.error(`[GenerateSingle] Failed to start job. Status: ${response.status}, Error:`, errorText);
        Alert.alert('Generation Failed', `Could not start stencil generation. Status: ${response.status}`);
        return;
      }
      
      const { job_id: jobId } = await response.json();
      console.log(`[GenerateSingle] Job started:`, jobId);
      
      // Poll for completion
      let completed = false;
      while (!completed) {
        await new Promise(resolve => setTimeout(resolve, 1500));
        
        const statusResponse = await fetch(`${API_URL}/api/ai-stencil-status/${jobId}`);
        if (!statusResponse.ok) {
          console.error(`[GenerateSingle] Status check failed`);
          continue;
        }
        
        const statusData = await statusResponse.json();
        console.log(`[GenerateSingle] Status: ${statusData.status}, Progress: ${statusData.progress}%`);
        
        if (statusData.status === 'completed') {
          completed = true;
          console.log(`[GenerateSingle] Generation completed!`);
          
          const generatedStencil = statusData.result?.[style];
          if (generatedStencil) {
            setStencilVersions(prev => ({
              ...prev,
              [style]: generatedStencil
            }));
            setSelectedVersion(style);
            setStencilImage(generatedStencil);
            setHasGeneratedOnce(true);
            // Save the reference photo for edit mode layers
            if (originalImage) {
              setReferencePhotoLayer(originalImage);
              console.log('[GenerateSingle] Saved reference photo layer');
            }
          } else {
            console.error(`[GenerateSingle] No stencil in result for style ${style}`);
            Alert.alert('Generation Issue', 'Stencil was generated but not received properly.');
          }
          
          // Clean up job
          try {
            await fetch(`${API_URL}/api/ai-stencil-job/${jobId}`, { method: 'DELETE' });
          } catch (e) {
            console.log('Job cleanup failed (non-critical)');
          }
        } else if (statusData.status === 'failed') {
          completed = true;
          console.error(`[GenerateSingle] Job failed:`, statusData.error);
          Alert.alert('Generation Failed', statusData.error || 'Could not generate stencil.');
        }
      }
      
    } catch (error: any) {
      console.error(`Error generating ${style} version:`, error);
      Alert.alert('Connection Issue', 'Failed to generate. Please check your internet connection.');
    } finally {
      setRegeneratingStyle(null);
      setIsGeneratingAI(false);
    }
  };

  // Apply line weight adjustment to existing stencil (live update)
  const applyLineWeight = async (newWeight: number) => {
    if (!stencilImage || newWeight === lineWeight) return;
    
    setLineWeight(newWeight);
    
    // If weight is 0, restore original stencil
    if (newWeight === 0 && selectedVersion && stencilVersions[selectedVersion]) {
      setStencilImage(stencilVersions[selectedVersion]);
      return;
    }
    
    try {
      console.log(`[LineWeight] Applying weight: ${newWeight}`);
      
      // Use the original generated stencil as base, not the adjusted one
      const baseStencil = selectedVersion && stencilVersions[selectedVersion] 
        ? stencilVersions[selectedVersion] 
        : stencilImage;
      
      const response = await fetch(`${API_URL}/api/adjust-line-weight`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stencil_base64: baseStencil,
          line_weight: newWeight,
        }),
      });
      
      if (response.ok) {
        const data = await response.json();
        console.log(`[LineWeight] Adjusted in ${data.processing_time_ms}ms`);
        setStencilImage(data.stencil_base64);
      } else {
        console.error('[LineWeight] Failed to adjust');
      }
    } catch (error) {
      console.error('[LineWeight] Error:', error);
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

  // Unified Save Options - shows action sheet with all save options
  const showSaveOptions = () => {
    if (!stencilImage) {
      Alert.alert('Error', 'No stencil to save.');
      return;
    }

    Alert.alert(
      'Save Stencil',
      'Choose where to save your stencil',
      [
        {
          text: 'Save to App',
          onPress: () => setShowSaveModal(true),
        },
        {
          text: 'Save to Photos',
          onPress: () => saveToPhotoGallery(stencilImage, 'body_bound_stencil'),
        },
        {
          text: 'Save Stencil & Reference',
          onPress: () => saveStencilAndReference(),
        },
        {
          text: 'Cancel',
          style: 'cancel',
        },
      ],
      { cancelable: true }
    );
  };

  // Save both stencil (transparent PNG) and reference (JPEG) for Procreate import
  // Both images are saved at identical dimensions for perfect layer alignment
  const saveStencilAndReference = async () => {
    if (!stencilImage || !originalImage) {
      Alert.alert('Error', 'Both original photo and stencil are required.');
      return;
    }

    setIsExportingPSD(true); // Reuse this loading state
    
    try {
      console.log('[SaveBoth] Starting save process...');
      
      // Request MediaLibrary permissions
      const permissionResult = await MediaLibrary.requestPermissionsAsync();
      if (permissionResult.status !== 'granted') {
        Alert.alert(
          'Permission Required',
          'Please allow access to your photo library to save images. Go to Settings > Body Bound > Photos.',
          [{ text: 'OK' }]
        );
        setIsExportingPSD(false);
        return;
      }

      // Step 1: Get dimensions from original image to ensure both are the same size
      console.log('[SaveBoth] Processing original image...');
      const originalManipulated = await ImageManipulator.manipulateAsync(
        originalImage,
        [], // No transformations - keep original size
        { 
          format: ImageManipulator.SaveFormat.JPEG,
          compress: 0.9, // High quality JPEG
        }
      );
      
      // Get the dimensions of the processed original
      const getImageSize = (uri: string): Promise<{width: number, height: number}> => {
        return new Promise((resolve, reject) => {
          Image.getSize(uri, (width, height) => resolve({width, height}), reject);
        });
      };
      
      const originalSize = await getImageSize(originalManipulated.uri);
      console.log('[SaveBoth] Original dimensions:', originalSize.width, 'x', originalSize.height);

      // Step 2: Process stencil - resize to match original and convert white to transparent
      console.log('[SaveBoth] Processing stencil with transparency...');
      
      // First resize stencil to match original dimensions
      const stencilResized = await ImageManipulator.manipulateAsync(
        stencilImage,
        [{ resize: { width: originalSize.width, height: originalSize.height } }],
        { 
          format: ImageManipulator.SaveFormat.PNG,
          compress: 1, // Lossless for stencil
        }
      );
      
      console.log('[SaveBoth] Stencil resized to match original');

      // Step 3: Read the stencil image and make white pixels transparent
      // This is done by reading the image data and creating a new PNG with alpha channel
      const stencilBase64 = await FileSystem.readAsStringAsync(stencilResized.uri, {
        encoding: 'base64',
      });
      
      // Create transparent PNG by calling our backend helper
      // The backend will convert white/near-white pixels to transparent
      console.log('[SaveBoth] Converting stencil to transparent PNG...');
      
      const transparentResponse = await fetch(`${API_URL}/api/make-transparent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: `data:image/png;base64,${stencilBase64}`,
          target_width: originalSize.width,
          target_height: originalSize.height,
        }),
      });
      
      if (!transparentResponse.ok) {
        throw new Error('Failed to create transparent stencil');
      }
      
      const transparentData = await transparentResponse.json();
      const transparentStencilBase64 = transparentData.image_base64;
      
      // Step 4: Save the transparent stencil PNG
      console.log('[SaveBoth] Saving transparent stencil PNG...');
      
      // Write transparent stencil to file
      const stencilFilename = `stencil_${Date.now()}.png`;
      const stencilFileUri = `${FileSystem.cacheDirectory}${stencilFilename}`;
      
      // Remove data URL prefix if present
      const stencilPngBase64 = transparentStencilBase64.includes(',') 
        ? transparentStencilBase64.split(',')[1] 
        : transparentStencilBase64;
      
      await FileSystem.writeAsStringAsync(stencilFileUri, stencilPngBase64, {
        encoding: 'base64',
      });
      
      // Save stencil to gallery
      const stencilAsset = await MediaLibrary.createAssetAsync(stencilFileUri);
      console.log('[SaveBoth] Stencil saved:', stencilAsset.filename);
      
      // Step 5: Save the reference JPEG
      console.log('[SaveBoth] Saving reference JPEG...');
      const referenceAsset = await MediaLibrary.createAssetAsync(originalManipulated.uri);
      console.log('[SaveBoth] Reference saved:', referenceAsset.filename);
      
      // Try to add both to album
      try {
        const albumName = 'Body Bound Stencils';
        let album = await MediaLibrary.getAlbumAsync(albumName);
        
        if (album === null) {
          await MediaLibrary.createAlbumAsync(albumName, stencilAsset, false);
          album = await MediaLibrary.getAlbumAsync(albumName);
        }
        
        if (album) {
          await MediaLibrary.addAssetsToAlbumAsync([referenceAsset], album, false);
        }
        console.log('[SaveBoth] Both images added to album');
      } catch (albumError) {
        console.log('[SaveBoth] Album operation failed (non-critical):', albumError);
      }

      setIsExportingPSD(false);
      
      Alert.alert(
        'Saved! ✓',
        'Both images saved to your photo gallery:\n\n• Stencil (PNG with transparent background)\n• Reference Photo (JPEG)\n\nOpen Procreate and import both as separate layers. They\'ll align perfectly!',
        [{ text: 'Got it!' }]
      );
      
    } catch (error: any) {
      console.error('[SaveBoth] Error:', error);
      setIsExportingPSD(false);
      Alert.alert(
        'Save Failed', 
        `Could not save images: ${error.message || 'Unknown error'}. Please try again.`
      );
    }
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
    console.log('[EditMode] ========== OPENING EDIT MODE ==========');
    console.log('[EditMode] originalImage exists:', !!originalImage);
    console.log('[EditMode] persistentReferencePhotoRef.current exists:', !!persistentReferencePhotoRef.current);
    console.log('[EditMode] stencilImage exists:', !!stencilImage);
    
    // Store the original AI stencil if not already stored (for revert functionality)
    if (!originalAIStencil && stencilImage) {
      setOriginalAIStencil(stencilImage);
    }
    
    // Store the reference photo in ref ONCE - never overwrite it
    // Using ref instead of state to avoid async timing issues
    if (!persistentReferencePhotoRef.current && originalImage) {
      persistentReferencePhotoRef.current = originalImage;
      console.log('[EditMode] SAVED reference photo to ref (first time)');
    } else if (persistentReferencePhotoRef.current) {
      console.log('[EditMode] USING existing reference from ref (subsequent time)');
    }
    
    // Use the ref value (which persists across renders)
    const referenceToUse = persistentReferencePhotoRef.current || originalImage;
    
    console.log('[EditMode] referenceToUse exists:', !!referenceToUse);
    console.log('[EditMode] referenceToUse length:', referenceToUse ? referenceToUse.length : 0);
    
    // Freeze the images for edit mode
    setEditModeStencilImage(stencilImage);
    setEditModeOriginalImage(referenceToUse);
    
    // Don't reset drawings - preserve them for continued editing
    setCurrentPath('');
    setEditOpacity(0.5);
    setBrushSize(3);
    setIsEraser(false);
    setShowEditHint(true);
    // Reset canvas transforms
    scale.value = 1;
    translateX.value = 0;
    translateY.value = 0;
    rotation.value = 0;
    setShowEditModal(true);
    console.log('[EditMode] ========== EDIT MODE OPENED ==========');
  };

  // Revert to original AI stencil (removes all edits)
  const revertToOriginal = () => {
    Alert.alert(
      'Revert to Original',
      'This will remove all your drawings and restore the original AI stencil. Continue?',
      [
        { text: 'Cancel', style: 'cancel' },
        { 
          text: 'Revert', 
          style: 'destructive',
          onPress: () => {
            if (originalAIStencil) {
              setStencilImage(originalAIStencil);
              setDrawingPaths([]);
              setEditedStencil(null);
            }
          }
        }
      ]
    );
  };

  // Helper: Create smooth bezier curve from points
  // Procreate-style StreamLine smoothing parameters - REDUCED for faster response
  const streamLineAmount = 0.2; // 0 = no smoothing, 1 = max smoothing (was 0.5, now more responsive)
  const stabilizationFactor = 0.15; // Motion filtering strength (was 0.3, now faster)
  
  // Refs for StreamLine smoothing (like Procreate's monoline brush)
  const smoothedPointRef = useRef<{x: number, y: number} | null>(null);
  const velocityRef = useRef<{x: number, y: number}>({x: 0, y: 0});
  const lastRawPointRef = useRef<{x: number, y: number} | null>(null);
  
  // Apply StreamLine smoothing - exponential moving average like Procreate
  const applyStreamLine = (rawX: number, rawY: number): {x: number, y: number} => {
    if (!smoothedPointRef.current) {
      smoothedPointRef.current = {x: rawX, y: rawY};
      lastRawPointRef.current = {x: rawX, y: rawY};
      return {x: rawX, y: rawY};
    }
    
    // Calculate velocity for motion filtering
    if (lastRawPointRef.current) {
      const dx = rawX - lastRawPointRef.current.x;
      const dy = rawY - lastRawPointRef.current.y;
      velocityRef.current = {
        x: velocityRef.current.x * stabilizationFactor + dx * (1 - stabilizationFactor),
        y: velocityRef.current.y * stabilizationFactor + dy * (1 - stabilizationFactor)
      };
    }
    lastRawPointRef.current = {x: rawX, y: rawY};
    
    // StreamLine smoothing - exponential moving average
    // Higher streamLineAmount = more smoothing (catches up slower)
    const smoothingFactor = 1 - streamLineAmount;
    smoothedPointRef.current = {
      x: smoothedPointRef.current.x + (rawX - smoothedPointRef.current.x) * smoothingFactor,
      y: smoothedPointRef.current.y + (rawY - smoothedPointRef.current.y) * smoothingFactor
    };
    
    return smoothedPointRef.current;
  };
  
  // Reset smoothing state when starting a new stroke
  const resetStreamLine = () => {
    smoothedPointRef.current = null;
    velocityRef.current = {x: 0, y: 0};
    lastRawPointRef.current = null;
  };

  const createSmoothPath = (points: {x: number, y: number}[]): string => {
    if (points.length < 2) return '';
    if (points.length === 2) {
      return `M${points[0].x},${points[0].y} L${points[1].x},${points[1].y}`;
    }
    
    let path = `M${points[0].x},${points[0].y}`;
    
    // Use Catmull-Rom to cubic Bezier conversion for ultra-smooth strokes
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[Math.max(0, i - 1)];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[Math.min(points.length - 1, i + 2)];
      
      // Catmull-Rom to Bezier control points (tension = 0.5 for smooth curves)
      const tension = 0.5;
      const cp1x = p1.x + (p2.x - p0.x) * tension / 3;
      const cp1y = p1.y + (p2.y - p0.y) * tension / 3;
      const cp2x = p2.x - (p3.x - p1.x) * tension / 3;
      const cp2y = p2.y - (p3.y - p1.y) * tension / 3;
      
      path += ` C${cp1x},${cp1y} ${cp2x},${cp2y} ${p2.x},${p2.y}`;
    }
    
    return path;
  };

  // Helper functions for gesture callbacks (must be regular functions to use with runOnJS)
  const startDrawing = (screenX: number, screenY: number, currentScale: number, currentTX: number, currentTY: number, currentRotation: number) => {
    // Convert screen coordinates to canvas coordinates (accounting for scale, translation, AND rotation)
    const { width, height } = Dimensions.get('window');
    const centerX = width / 2;
    const centerY = height / 2;
    
    // Step 1: Remove translation
    let x = screenX - centerX - currentTX;
    let y = screenY - centerY - currentTY;
    
    // Step 2: Remove scale
    x = x / currentScale;
    y = y / currentScale;
    
    // Step 3: Remove rotation (rotate by negative angle around origin)
    const cos = Math.cos(-currentRotation);
    const sin = Math.sin(-currentRotation);
    const rotatedX = x * cos - y * sin;
    const rotatedY = x * sin + y * cos;
    
    // Step 4: Add back center offset
    const rawX = rotatedX + centerX;
    const rawY = rotatedY + centerY;
    
    // Reset StreamLine smoothing for new stroke
    resetStreamLine();
    
    // Apply StreamLine to first point
    const smoothed = applyStreamLine(rawX, rawY);
    
    // Store current transform for continue drawing
    currentScaleRef.current = currentScale;
    currentTranslateXRef.current = currentTX;
    currentTranslateYRef.current = currentTY;
    
    // INSTANT - no delays, start drawing immediately
    currentPointsRef.current = [{ x: smoothed.x, y: smoothed.y }];
    isDrawingRef.current = true;
    setCurrentPoints([{ x: smoothed.x, y: smoothed.y }]);
    setCurrentPath(`M${smoothed.x},${smoothed.y}`);
  };

  const continueDrawing = (screenX: number, screenY: number, currentScale: number, currentTX: number, currentTY: number, currentRotation: number) => {
    if (!isDrawingRef.current) return;
    
    // Convert screen coordinates to canvas coordinates (accounting for scale, translation, AND rotation)
    const { width, height } = Dimensions.get('window');
    const centerX = width / 2;
    const centerY = height / 2;
    
    // Step 1: Remove translation
    let x = screenX - centerX - currentTX;
    let y = screenY - centerY - currentTY;
    
    // Step 2: Remove scale
    x = x / currentScale;
    y = y / currentScale;
    
    // Step 3: Remove rotation (rotate by negative angle around origin)
    const cos = Math.cos(-currentRotation);
    const sin = Math.sin(-currentRotation);
    const rotatedX = x * cos - y * sin;
    const rotatedY = x * sin + y * cos;
    
    // Step 4: Add back center offset
    const rawX = rotatedX + centerX;
    const rawY = rotatedY + centerY;
    
    // Apply StreamLine smoothing for silky smooth lines
    const smoothed = applyStreamLine(rawX, rawY);
    
    // Only add point if it moved enough (reduces redundant points)
    const lastPoint = currentPointsRef.current[currentPointsRef.current.length - 1];
    const dist = Math.sqrt(Math.pow(smoothed.x - lastPoint.x, 2) + Math.pow(smoothed.y - lastPoint.y, 2));
    
    if (dist > 1) { // Minimum 1px movement
      const newPoints = [...currentPointsRef.current, { x: smoothed.x, y: smoothed.y }];
      currentPointsRef.current = newPoints;
      setCurrentPoints(newPoints);
      const smoothPath = createSmoothPath(newPoints);
      setCurrentPath(smoothPath);
    }
  };

  const endDrawing = () => {
    if (!isDrawingRef.current) return;
    isDrawingRef.current = false;
    
    // If we only have 1 point, it's a tap - create a dot
    if (currentPointsRef.current.length === 1) {
      const point = currentPointsRef.current[0];
      // Add a small dot at the tap location
      setDotMarks(prev => [...prev, { x: point.x, y: point.y, size: brushSize }]);
      console.log('[Drawing] Single tap - created dot at:', point.x, point.y);
    } else if (currentPointsRef.current.length > 1) {
      const smoothPath = createSmoothPath(currentPointsRef.current);
      if (isEraser) {
        setDrawingPaths(prev => [...prev, `ERASER:${smoothPath}`]);
      } else {
        setDrawingPaths(prev => [...prev, smoothPath]);
      }
    }
    currentPointsRef.current = [];
    setCurrentPath('');
    setCurrentPoints([]);
  };

  const undoLastPath = () => {
    // Undo dots first if there are any, otherwise undo paths
    if (dotMarks.length > 0) {
      setDotMarks(prev => prev.slice(0, -1));
    } else {
      setDrawingPaths(prev => prev.slice(0, -1));
    }
  };

  // PROCREATE-STYLE BEHAVIOR:
  // - Apple Pencil (stylus) = ALWAYS draws
  // - Single finger = PANS (navigation) by default, unless "Finger Drawing" is ON
  // - Two fingers = Zoom + Pan (navigation)
  // - enableFingerPainting toggle: when ON, finger also draws like Procreate's option
  
  // Single-finger gesture with proper pencil vs finger detection
  // Uses pointerType to differentiate between stylus (pencil) and touch (finger)
  // OPTIMIZED: Uses worklets to minimize runOnJS calls
  const drawGesture = Gesture.Pan()
    .minPointers(1)
    .maxPointers(1)
    .minDistance(0) // CRITICAL: 0 = instant response
    .activeOffsetX(0)
    .activeOffsetY(0)
    .hitSlop({ left: 0, right: 0, top: 0, bottom: 0 })
    .shouldCancelWhenOutside(false)
    .onBegin((event) => {
      const isPencil = event.pointerType === PointerType.STYLUS;
      const shouldDraw = isPencil || enableFingerPaintingRef.current;
      
      if (shouldDraw) {
        // INSTANT feedback on UI thread
        isDrawingActive.value = true;
        touchX.value = event.x;
        touchY.value = event.y;
      }
    })
    .onStart((event) => {
      const isPencil = event.pointerType === PointerType.STYLUS;
      const shouldDraw = isPencil || enableFingerPaintingRef.current;
      
      if (shouldDraw) {
        runOnJS(startDrawing)(event.x, event.y, scale.value, translateX.value, translateY.value, rotation.value);
      } else {
        savedTranslateX.value = translateX.value;
        savedTranslateY.value = translateY.value;
      }
    })
    .onUpdate((event) => {
      const isPencil = event.pointerType === PointerType.STYLUS;
      const shouldDraw = isPencil || enableFingerPaintingRef.current;
      
      if (shouldDraw) {
        // Update touch position on UI thread
        touchX.value = event.x;
        touchY.value = event.y;
        // Update path on JS thread
        runOnJS(continueDrawing)(event.x, event.y, scale.value, translateX.value, translateY.value, rotation.value);
      } else {
        translateX.value = savedTranslateX.value + event.translationX;
        translateY.value = savedTranslateY.value + event.translationY;
      }
    })
    .onEnd((event) => {
      const isPencil = event.pointerType === PointerType.STYLUS;
      const shouldDraw = isPencil || enableFingerPaintingRef.current;
      
      if (shouldDraw) {
        isDrawingActive.value = false;
        touchX.value = -1000;
        touchY.value = -1000;
        runOnJS(endDrawing)();
      }
    })
    .onFinalize(() => {
      isDrawingActive.value = false;
      touchX.value = -1000;
      touchY.value = -1000;
    });

  // PINCH gesture for zooming (always works with 2 fingers)
  const pinchGesture = Gesture.Pinch()
    .onStart(() => {
      savedScale.value = scale.value;
    })
    .onUpdate((event) => {
      // Procreate-style: nearly 1:1 zoom response
      scale.value = Math.min(Math.max(savedScale.value * event.scale, 0.1), 10);
    });

  // ROTATION gesture for rotating canvas with two fingers
  const rotationGesture = Gesture.Rotation()
    .onStart(() => {
      savedRotation.value = rotation.value;
    })
    .onUpdate((event) => {
      // Smooth rotation - follows finger rotation
      rotation.value = savedRotation.value + event.rotation;
    });

  // Two-finger PAN for moving while zooming
  const twoFingerPan = Gesture.Pan()
    .minPointers(2)
    .maxPointers(2)
    .onStart(() => {
      savedTranslateX.value = translateX.value;
      savedTranslateY.value = translateY.value;
    })
    .onUpdate((event) => {
      translateX.value = savedTranslateX.value + event.translationX;
      translateY.value = savedTranslateY.value + event.translationY;
    });

  // Double-tap to undo
  const doubleTapGesture = Gesture.Tap()
    .numberOfTaps(2)
    .onEnd(() => {
      runOnJS(undoLastPath)();
    });

  // Combine all gestures - pinch, rotation, and two-finger pan run simultaneously
  const combinedGesture = Gesture.Simultaneous(
    pinchGesture,
    rotationGesture,
    twoFingerPan
  );

  // Race between single-finger draw and the combined two-finger gestures
  // Also include double-tap for undo
  const allGestures = Gesture.Race(
    combinedGesture,
    Gesture.Exclusive(doubleTapGesture, drawGesture)
  );

  // Animated style for the canvas transform
  const animatedCanvasStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: translateX.value },
      { translateY: translateY.value },
      { scale: scale.value },
      { rotate: `${rotation.value}rad` }
    ]
  }));

  // Animated style for instant touch cursor (renders on UI thread - no delay!)
  const animatedCursorStyle = useAnimatedStyle(() => ({
    position: 'absolute',
    left: touchX.value - brushSize / 2,
    top: touchY.value - brushSize / 2,
    width: brushSize,
    height: brushSize,
    borderRadius: brushSize / 2,
    backgroundColor: isEraser ? 'white' : 'black',
    opacity: isDrawingActive.value ? 1 : 0,
    pointerEvents: 'none' as const,
  }));

  // Calculate distance between two touch points (for pinch zoom) - legacy
  const getDistance = (touches: any[]): number => {
    if (touches.length < 2) return 0;
    const dx = touches[0].pageX - touches[1].pageX;
    const dy = touches[0].pageY - touches[1].pageY;
    return Math.sqrt(dx * dx + dy * dy);
  };

  // Legacy touch handlers - kept for fallback but won't be used with GestureDetector
  // Handle touch start - iPad: ONLY Apple Pencil draws, finger does zoom/pan/undo
  const handleDrawStart = (event: GestureResponderEvent) => {
    const touches = event.nativeEvent.touches;
    const touchCount = touches ? touches.length : 1;
    const nativeEvent = event.nativeEvent as any;
    
    // Clear any pending draw timeout
    if (drawStartTimeoutRef.current) {
      clearTimeout(drawStartTimeoutRef.current);
      drawStartTimeoutRef.current = null;
    }
    
    // Track touch count
    touchCountRef.current = touchCount;
    gestureStartTimeRef.current = Date.now();
    
    // Two or more fingers = immediately enter zoom/pan mode
    if (touchCount >= 2) {
      isPinchingRef.current = true;
      setIsPinching(true);
      pendingDrawRef.current = false;
      if (touches) {
        const dist = getDistance(Array.from(touches));
        lastDistanceRef.current = dist;
        setLastDistance(dist);
        const midX = (touches[0].pageX + touches[1].pageX) / 2;
        const midY = (touches[0].pageY + touches[1].pageY) / 2;
        lastPanRef.current = { x: midX, y: midY };
        setLastPanX(midX);
        setLastPanY(midY);
      }
      setCurrentPath('');
      setCurrentPoints([]);
      return;
    }
    
    const { locationX, locationY, pageX, pageY } = event.nativeEvent;
    const now = Date.now();
    
    // Check if this is Apple Pencil - need to check multiple sources
    // React Native's responder system may expose touchType differently
    const touch = touches && touches.length > 0 ? touches[0] : null;
    const touchFromArray = touch as any;
    
    // Check touchType from multiple possible locations
    const touchTypeFromEvent = nativeEvent.touchType;
    const touchTypeFromTouch = touchFromArray?.touchType;
    const touchTypeFromType = touchFromArray?.type;
    
    // Apple Pencil specific properties - these are ONLY available for stylus input
    const hasForce = nativeEvent.force !== undefined && nativeEvent.force > 0;
    const hasAltitude = nativeEvent.altitudeAngle !== undefined;
    const hasAzimuth = nativeEvent.azimuthAngle !== undefined;
    
    // Determine if Apple Pencil based on all available signals
    // Also check the pointer events flag which is more reliable on native iOS
    const pointerWasPencil = (global as any).__lastPointerWasPencil === true;
    
    const isApplePencil = 
      pointerWasPencil ||
      touchTypeFromEvent === 'stylus' || 
      touchTypeFromEvent === 'pencil' ||
      touchTypeFromTouch === 'stylus' ||
      touchTypeFromTouch === 'pencil' ||
      touchTypeFromType === 'stylus' ||
      // Apple Pencil has altitude angle - fingers do not
      (hasAltitude && hasForce) ||
      // Check for azimuth angle (tilt detection) - only stylus has this
      hasAzimuth;
    
    // Extensive debug logging to diagnose the issue
    console.log('[EditMode] Touch Debug:', JSON.stringify({
      touchTypeFromEvent,
      touchTypeFromTouch,
      touchTypeFromType,
      force: nativeEvent.force,
      altitudeAngle: nativeEvent.altitudeAngle,
      azimuthAngle: nativeEvent.azimuthAngle,
      isApplePencil,
      enableFingerPainting: enableFingerPaintingRef.current,
      touchCount
    }));
    
    // Double-tap detection for undo (within 300ms) - works for any touch
    if (now - lastTapTimeRef.current < 300) {
      setDrawingPaths(prev => prev.slice(0, -1));
      lastTapTimeRef.current = 0;
      pendingDrawRef.current = false;
      return;
    }
    lastTapTimeRef.current = now;
    
    // Hide hint after 5 seconds
    if (showEditHint) {
      setTimeout(() => setShowEditHint(false), 5000);
    }
    
    // Store position for potential pan
    lastPanRef.current = { x: pageX, y: pageY };
    setLastPanX(pageX);
    setLastPanY(pageY);
    
    // Drawing logic: Finger painting enabled OR automatic pencil detection
    const shouldDraw = enableFingerPaintingRef.current || isApplePencil;
    
    console.log('[EditMode] shouldDraw:', shouldDraw, 'enableFingerPainting:', enableFingerPaintingRef.current, 'isApplePencil:', isApplePencil);
    
    if (shouldDraw) {
      console.log('[EditMode] ✏️ DRAWING - Starting at:', locationX, locationY, enableFingerPaintingRef.current ? '(finger painting)' : '(pencil detected)');
      setCurrentPoints([{ x: locationX, y: locationY }]);
      setCurrentPath(`M${locationX},${locationY}`);
      pendingDrawRef.current = false;
    } else {
      // For finger touch - do not draw
      console.log('[EditMode] 👆 FINGER - will pan');
      pendingDrawRef.current = false;
    }
  };

  // Handle touch move - iPad: ONLY Apple Pencil draws
  const handleDrawMove = (event: GestureResponderEvent) => {
    const touches = event.nativeEvent.touches;
    const touchCount = touches ? touches.length : 1;
    const nativeEvent = event.nativeEvent as any;
    
    // Update touch count
    touchCountRef.current = touchCount;
    
    // Two or more fingers = zoom and pan simultaneously
    // PROCREATE-LEVEL RESPONSIVENESS: Detect second finger IMMEDIATELY
    if (touchCount >= 2 && touches) {
      // Cancel any drawing in progress - second finger joined
      if (currentPoints.length > 0) {
        setCurrentPath('');
        setCurrentPoints([]);
      }
      pendingDrawRef.current = false;
      
      // Transition to pinch mode INSTANTLY
      if (!isPinchingRef.current) {
        isPinchingRef.current = true;
        setIsPinching(true);
        const dist = getDistance(Array.from(touches));
        lastDistanceRef.current = dist;
        setLastDistance(dist);
        const midX = (touches[0].pageX + touches[1].pageX) / 2;
        const midY = (touches[0].pageY + touches[1].pageY) / 2;
        lastPanRef.current = { x: midX, y: midY };
        setLastPanX(midX);
        setLastPanY(midY);
        return;
      }
      
      // PROCREATE-STYLE ZOOM: Nearly 1:1 response, minimal damping
      const newDistance = getDistance(Array.from(touches));
      if (lastDistanceRef.current > 0) {
        const scaleFactor = newDistance / lastDistanceRef.current;
        // 0.95 = almost 1:1 like Procreate (was 0.7)
        const dampedScale = 1 + (scaleFactor - 1) * 0.95;
        const newScale = Math.min(Math.max(editScale * dampedScale, 0.1), 10);
        setEditScale(newScale);
      }
      lastDistanceRef.current = newDistance;
      setLastDistance(newDistance);
      
      // PROCREATE-STYLE PAN: Direct 1:1 movement
      const midX = (touches[0].pageX + touches[1].pageX) / 2;
      const midY = (touches[0].pageY + touches[1].pageY) / 2;
      const deltaX = midX - lastPanRef.current.x;
      const deltaY = midY - lastPanRef.current.y;
      setEditTranslateX(prev => prev + deltaX);
      setEditTranslateY(prev => prev + deltaY);
      lastPanRef.current = { x: midX, y: midY };
      setLastPanX(midX);
      setLastPanY(midY);
      return;
    }
    
    // Reset pinching state when back to single touch
    if (isPinchingRef.current && touchCount === 1) {
      isPinchingRef.current = false;
      setIsPinching(false);
      lastDistanceRef.current = 0;
      setLastDistance(0);
      // Re-establish pan position for single finger
      const { pageX, pageY } = event.nativeEvent;
      lastPanRef.current = { x: pageX, y: pageY };
      setLastPanX(pageX);
      setLastPanY(pageY);
      return;
    }
    
    const { locationX, locationY, pageX, pageY } = event.nativeEvent;
    
    // Check if this is Apple Pencil - use same comprehensive detection as start
    const touch = touches && touches.length > 0 ? touches[0] : null;
    const touchFromArray = touch as any;
    
    const touchTypeFromEvent = nativeEvent.touchType;
    const touchTypeFromTouch = touchFromArray?.touchType;
    const touchTypeFromType = touchFromArray?.type;
    
    const hasForce = nativeEvent.force !== undefined && nativeEvent.force > 0;
    const hasAltitude = nativeEvent.altitudeAngle !== undefined;
    const hasAzimuth = nativeEvent.azimuthAngle !== undefined;
    
    // Check pointer events flag for reliable pencil detection
    const pointerWasPencil = (global as any).__lastPointerWasPencil === true;
    
    const isApplePencil = 
      pointerWasPencil ||
      touchTypeFromEvent === 'stylus' || 
      touchTypeFromEvent === 'pencil' ||
      touchTypeFromTouch === 'stylus' ||
      touchTypeFromTouch === 'pencil' ||
      touchTypeFromType === 'stylus' ||
      (hasAltitude && hasForce) ||
      hasAzimuth;
    
    // Drawing logic: Finger painting enabled OR automatic pencil detection
    const shouldDraw = enableFingerPaintingRef.current || isApplePencil;
    
    if (shouldDraw && currentPoints.length > 0) {
      // Continue drawing
      const newPoints = [...currentPoints, { x: locationX, y: locationY }];
      setCurrentPoints(newPoints);
      const smoothPath = createSmoothPath(newPoints);
      setCurrentPath(smoothPath);
    } else if (!shouldDraw && !isPinchingRef.current) {
      // Single finger - pan the canvas (when not in draw mode)
      const deltaX = pageX - lastPanRef.current.x;
      const deltaY = pageY - lastPanRef.current.y;
      setEditTranslateX(prev => prev + deltaX);
      setEditTranslateY(prev => prev + deltaY);
      lastPanRef.current = { x: pageX, y: pageY };
      setLastPanX(pageX);
      setLastPanY(pageY);
    }
  };

  // Handle touch end for drawing
  const handleDrawEnd = () => {
    // Clear any pending timeout
    if (drawStartTimeoutRef.current) {
      clearTimeout(drawStartTimeoutRef.current);
      drawStartTimeoutRef.current = null;
    }
    
    isPinchingRef.current = false;
    setIsPinching(false);
    lastDistanceRef.current = 0;
    setLastDistance(0);
    pendingDrawRef.current = false;
    touchCountRef.current = 0;
    
    if (currentPath && currentPoints.length > 1) {
      // Create final smooth path
      const smoothPath = createSmoothPath(currentPoints);
      
      if (isEraser) {
        setDrawingPaths(prev => [...prev, `ERASER:${smoothPath}`]);
      } else {
        setDrawingPaths(prev => [...prev, smoothPath]);
      }
    }
    setCurrentPath('');
    setCurrentPoints([]);
  };

  // Reset zoom to default
  const resetZoom = () => {
    setEditScale(1);
    setEditTranslateX(0);
    setEditTranslateY(0);
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

  // Save edited stencil - captures stencil + drawings and shows on main screen (no auto-save to gallery)
  const saveEditedStencil = async () => {
    // If no drawings AND no dots, just close
    if (drawingPaths.length === 0 && dotMarks.length === 0) {
      setShowEditModal(false);
      return;
    }

    // If ref not available, just close with message
    if (!editCanvasRef.current) {
      console.log('[SaveEdit] Canvas ref not available, closing modal');
      setShowEditModal(false);
      return;
    }

    try {
      console.log('[SaveEdit] Starting capture...');
      
      // Reset canvas transforms before capture (so we get the full image, not zoomed/rotated view)
      scale.value = 1;
      translateX.value = 0;
      translateY.value = 0;
      rotation.value = 0;
      
      // Set capture mode - hides original photo, shows stencil at full opacity
      setIsCapturingForExport(true);
      
      // Longer delay to let transforms and UI update
      await new Promise(resolve => setTimeout(resolve, 300));
      
      // Capture the canvas as an image (stencil + drawings on white bg)
      const uri = await captureRef(editCanvasRef, {
        format: 'png',
        quality: 1,
        result: 'base64',
      });
      
      console.log('[SaveEdit] Capture successful, uri length:', uri?.length);
      
      // Reset capture mode
      setIsCapturingForExport(false);
      
      if (uri) {
        // Set the edited image as the main stencil (shown on main screen)
        const editedImage = `data:image/png;base64,${uri}`;
        setEditedStencil(editedImage);
        setStencilImage(editedImage);
        console.log('[SaveEdit] Stencil updated with edits');
      }
      
      // Close modal
      setShowEditModal(false);
    } catch (error: any) {
      console.error('[SaveEdit] Error capturing:', error);
      setIsCapturingForExport(false);
      
      // Still close the modal even if capture fails - don't leave user stuck
      setShowEditModal(false);
      
      // Notify user that edits couldn't be saved but they can try Share in edit mode
      Alert.alert(
        'Note', 
        'Could not apply edits to preview. You can still save your work using "Save to Photos" in Edit mode.',
        [{ text: 'OK' }]
      );
    }
  };

  // Save edited stencil to gallery - captures stencil + drawings at full opacity (no original photo)
  const saveEditedToGallery = async () => {
    if (!editCanvasRef.current) {
      Alert.alert('Error', 'Could not capture the edited image.');
      return;
    }

    try {
      // Set capture mode - hides original photo, shows stencil at full opacity
      setIsCapturingForExport(true);
      
      // Small delay to let the UI update
      await new Promise(resolve => setTimeout(resolve, 150));
      
      // Capture the canvas as an image (now only shows stencil + drawings on white bg)
      const uri = await captureRef(editCanvasRef, {
        format: 'png',
        quality: 1,
        result: 'base64',
      });
      
      // Reset capture mode
      setIsCapturingForExport(false);
      
      await saveToPhotoGallery(`data:image/png;base64,${uri}`, 'body_bound_edited_stencil');
    } catch (error: any) {
      setIsCapturingForExport(false);
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
    setImageQualityWarnings([]);
    setImageQualitySuggestions([]);
    setShowQualityWarning(false);
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
        onSlidingComplete={(val) => setSettings(prev => ({ ...prev, [settingKey]: val }))}
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
        
        {/* Disclaimer */}
        <View style={styles.disclaimerContainer}>
          <Text style={styles.disclaimerTitle}>Please Note</Text>
          <Text style={styles.disclaimerText}>
            • WiFi connection required to generate stencils{'\n'}
            • This app uses AI services for stencil generation{'\n'}
            • AI servers may occasionally be unavailable{'\n'}
            • Results may sometimes vary — if you notice any inconsistencies, simply tap "Generate" again
          </Text>
        </View>
        
        {/* Footer Note */}
        <Text style={styles.welcomeFooter}>
          for tattoo artists • developed by a tattoo artist
        </Text>
        
        {/* Version Number */}
        <Text style={styles.welcomeVersion}>v2.2.0</Text>
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
        <View style={styles.headerRight}>
          {/* Action icons - always visible */}
          <TouchableOpacity
            style={styles.headerIconButton}
            onPress={() => setShowPreviewModal(true)}
          >
            <Text style={styles.headerIconText}>🔍</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.headerIconButton}
            onPress={printStencil}
          >
            <Text style={styles.headerIconText}>🖨️</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.headerIconButton}
            onPress={showSaveOptions}
          >
            <Text style={styles.headerIconText}>💾</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.helpButton}
            onPress={showOnboardingTutorial}
          >
            <Text style={styles.helpButtonText}>?</Text>
          </TouchableOpacity>
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
                          <ExpoImage
                            source={{ uri: asset.uri }}
                            style={styles.photoGridImage}
                            contentFit="cover"
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
                  {/* Crop Image button - top right of image area */}
                  <TouchableOpacity
                    style={styles.cropTopButton}
                    onPress={openCropModal}
                  >
                    <Text style={styles.cropTopIcon}>✂️</Text>
                    <Text style={styles.cropTopText}>Crop Image</Text>
                  </TouchableOpacity>
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

                {/* Revert button - only show if user has edited the stencil */}
                {editedStencil && originalAIStencil && (
                  <TouchableOpacity style={styles.revertButton} onPress={revertToOriginal}>
                    <Text style={styles.revertButtonIcon}>↩️</Text>
                    <Text style={styles.revertButtonText}>Revert to Original AI Stencil</Text>
                  </TouchableOpacity>
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
          {stencilImage && (
            <TouchableOpacity style={[styles.sourceButton, styles.editSourceButton]} onPress={openEditMode}>
              <Text style={styles.buttonIcon}>✏️</Text>
              <Text style={styles.sourceButtonText}>Edit</Text>
            </TouchableOpacity>
          )}
          {originalImage && (
            <TouchableOpacity style={styles.resetButton} onPress={resetAll}>
              <Text style={styles.buttonIcon}>🔄</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* Image Quality Warning Banner */}
        {showQualityWarning && imageQualityWarnings.length > 0 && (
          <View style={styles.qualityWarningBanner}>
            <View style={styles.qualityWarningHeader}>
              <Text style={styles.qualityWarningIcon}>⚠️</Text>
              <Text style={styles.qualityWarningTitle}>Image Quality Notice</Text>
              <TouchableOpacity 
                style={styles.qualityWarningClose}
                onPress={() => setShowQualityWarning(false)}
              >
                <Text style={styles.qualityWarningCloseText}>✕</Text>
              </TouchableOpacity>
            </View>
            {imageQualityWarnings.map((warning, index) => (
              <Text key={index} style={styles.qualityWarningText}>• {warning}</Text>
            ))}
            {imageQualitySuggestions.length > 0 && (
              <View style={styles.qualitySuggestionsContainer}>
                <Text style={styles.qualitySuggestionsTitle}>💡 Tips:</Text>
                {imageQualitySuggestions.map((suggestion, index) => (
                  <Text key={index} style={styles.qualitySuggestionText}>• {suggestion}</Text>
                ))}
              </View>
            )}
          </View>
        )}

        {/* Custom Button Style Selector - Always visible when image loaded */}
        {originalImage && (
          <View style={styles.stencilStyleSection}>
            {/* Custom Button Images Row - Tap to generate that style */}
            <View style={styles.styleButtonsRow}>
              {/* LOW FIDELITY Button */}
              <TouchableOpacity
                style={[
                  styles.styleButtonWrapper,
                  selectedVersion === 'light' && stencilVersions.light && styles.styleButtonSelected,
                  (isGeneratingAI || regeneratingStyle) && styles.styleButtonDisabled
                ]}
                onPress={() => generateSingleStyle('light')}
                disabled={isGeneratingAI || !!regeneratingStyle}
                activeOpacity={0.8}
              >
                <Image 
                  source={{ uri: 'https://customer-assets.emergentagent.com/job_7aab69d1-18d7-492c-bf0e-47aa8d7232af/artifacts/6gntycn7_1000040955.jpg' }}
                  style={styles.styleButtonImage}
                  resizeMode="contain"
                />
                {regeneratingStyle === 'light' && (
                  <View style={styles.styleGeneratingOverlay}>
                    <ActivityIndicator size="small" color="#C9A227" />
                  </View>
                )}
                {stencilVersions.light && !regeneratingStyle && (
                  <TouchableOpacity
                    style={styles.styleRegenButton}
                    onPress={(e) => {
                      e.stopPropagation();
                      regenerateSingleStyle('light');
                    }}
                    disabled={!!regeneratingStyle}
                  >
                    <Ionicons name="refresh" size={14} color="#C9A227" />
                  </TouchableOpacity>
                )}
              </TouchableOpacity>
              
              {/* MID-RANGE Button */}
              <TouchableOpacity
                style={[
                  styles.styleButtonWrapper,
                  selectedVersion === 'medium' && stencilVersions.medium && styles.styleButtonSelected,
                  (isGeneratingAI || regeneratingStyle) && styles.styleButtonDisabled
                ]}
                onPress={() => generateSingleStyle('medium')}
                disabled={isGeneratingAI || !!regeneratingStyle}
                activeOpacity={0.8}
              >
                <Image 
                  source={{ uri: 'https://customer-assets.emergentagent.com/job_7aab69d1-18d7-492c-bf0e-47aa8d7232af/artifacts/s7totdho_1000040953.jpg' }}
                  style={styles.styleButtonImage}
                  resizeMode="contain"
                />
                {regeneratingStyle === 'medium' && (
                  <View style={styles.styleGeneratingOverlay}>
                    <ActivityIndicator size="small" color="#C9A227" />
                  </View>
                )}
                {stencilVersions.medium && !regeneratingStyle && (
                  <TouchableOpacity
                    style={styles.styleRegenButton}
                    onPress={(e) => {
                      e.stopPropagation();
                      regenerateSingleStyle('medium');
                    }}
                    disabled={!!regeneratingStyle}
                  >
                    <Ionicons name="refresh" size={14} color="#C9A227" />
                  </TouchableOpacity>
                )}
              </TouchableOpacity>
              
              {/* HIGH DEF Button */}
              <TouchableOpacity
                style={[
                  styles.styleButtonWrapper,
                  selectedVersion === 'heavy' && stencilVersions.heavy && styles.styleButtonSelected,
                  (isGeneratingAI || regeneratingStyle) && styles.styleButtonDisabled
                ]}
                onPress={() => generateSingleStyle('heavy')}
                disabled={isGeneratingAI || !!regeneratingStyle}
                activeOpacity={0.8}
              >
                <Image 
                  source={{ uri: 'https://customer-assets.emergentagent.com/job_7aab69d1-18d7-492c-bf0e-47aa8d7232af/artifacts/3dplx323_1000040952.jpg' }}
                  style={styles.styleButtonImage}
                  resizeMode="contain"
                />
                {regeneratingStyle === 'heavy' && (
                  <View style={styles.styleGeneratingOverlay}>
                    <ActivityIndicator size="small" color="#C9A227" />
                  </View>
                )}
                {stencilVersions.heavy && !regeneratingStyle && (
                  <TouchableOpacity
                    style={styles.styleRegenButton}
                    onPress={(e) => {
                      e.stopPropagation();
                      regenerateSingleStyle('heavy');
                    }}
                    disabled={!!regeneratingStyle}
                  >
                    <Ionicons name="refresh" size={14} color="#C9A227" />
                  </TouchableOpacity>
                )}
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* Generation Progress - Compact */}
        {isGeneratingVersions && (
          <View style={styles.compactProgressSection}>
            <Text style={styles.compactProgressText}>
              Generating {generationProgress}/3: {generationProgress === 1 ? 'Low Fidelity' : generationProgress === 2 ? 'Mid-Range' : generationProgress === 3 ? 'High Def' : '...'}
            </Text>
            <View style={styles.compactProgressDots}>
              <View style={[styles.compactDot, generationProgress >= 1 && styles.compactDotComplete]} />
              <View style={[styles.compactDot, generationProgress >= 2 && styles.compactDotComplete]} />
              <View style={[styles.compactDot, generationProgress >= 3 && styles.compactDotComplete]} />
            </View>
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
            <TouchableOpacity style={styles.previewActionButton} onPress={saveStencilAndReference}>
              <Text style={styles.previewActionIcon}>📤</Text>
              <Text style={styles.previewActionText}>Procreate</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* Edit Mode Modal - Full Screen Procreate-Style Editor */}
      <Modal
        visible={showEditModal}
        animationType="fade"
        transparent={false}
        statusBarTranslucent={true}
        onRequestClose={() => setShowEditModal(false)}
      >
        <GestureHandlerRootView style={styles.procreateContainer}>
          {/* Full Screen Canvas with proper gesture detection */}
          <GestureDetector gesture={allGestures}>
            <Animated.View 
              ref={editCanvasRef as any}
              style={styles.procreateCanvas}
            >
              <Animated.View style={[
                styles.procreateCanvasInner,
                animatedCanvasStyle
              ]}>
              
              {/* WHITE BACKGROUND - Only shown during capture for clean export */}
              {isCapturingForExport && (
                <View style={[styles.procreateBackgroundImage, { backgroundColor: '#FFFFFF' }]} />
              )}
              
              {/* WHITE BACKGROUND for reference photo layer */}
              {!isCapturingForExport && (
                <View style={[styles.procreateBackgroundImage, { backgroundColor: '#FFFFFF' }]} />
              )}
              
              {/* Original image as background - opacity controlled by slider */}
              {/* Hidden during capture - only the stencil and drawings are exported */}
              {editModeOriginalImage && !isCapturingForExport && (
                <Image
                  source={{ uri: editModeOriginalImage }}
                  style={[styles.procreateBackgroundImage, { opacity: editOpacity }]}
                  resizeMode="contain"
                />
              )}
              
              {/* Stencil overlay - TRANSPARENT PNG with just black linework */}
              {/* Always at FULL OPACITY so linework is always visible */}
              {editModeStencilImage && (
                <Image
                  source={{ uri: editModeStencilImage }}
                  style={styles.procreateStencilImage}
                  resizeMode="contain"
                />
              )}
              
              {/* SVG Drawing Layer */}
              <Svg style={styles.procreateDrawingLayer}>
                {/* Render saved dot marks */}
                {dotMarks.map((dot, index) => (
                  <Circle
                    key={`dot-${index}`}
                    cx={dot.x}
                    cy={dot.y}
                    r={dot.size / 2}
                    fill="#000000"
                  />
                ))}
                {/* Render drawing paths */}
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
                      opacity={isEraserPath && !isCapturingForExport ? 0.7 : 1}
                      strokeDasharray={isEraserPath && !isCapturingForExport ? '5,3' : undefined}
                    />
                  );
                })}
                {currentPath && (
                  <Path
                    d={currentPath}
                    stroke={isEraser ? '#FFFFFF' : '#000000'}
                    strokeWidth={isEraser ? brushSize * 3 : brushSize}
                    fill="none"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    opacity={isEraser && !isCapturingForExport ? 0.7 : 1}
                    strokeDasharray={isEraser && !isCapturingForExport ? '5,3' : undefined}
                  />
                )}
              </Svg>
              </Animated.View>
            </Animated.View>
          </GestureDetector>

          {/* Left Side - Vertical Brush Size Slider */}
          <View style={styles.procreateLeftBar}>
            <View style={styles.procreateBrushSliderContainer}>
              <Text style={styles.procreateBrushLabel}>Size</Text>
              <View style={styles.procreateBrushSliderWrapper}>
                <Slider
                  style={[styles.procreateBrushSlider, { transform: [{ rotate: '-90deg' }] }]}
                  minimumValue={1}
                  maximumValue={20}
                  step={1}
                  value={brushSize}
                  onValueChange={(val) => setBrushSize(val)}
                  minimumTrackTintColor="#C9A227"
                  maximumTrackTintColor="#555"
                  thumbTintColor="#C9A227"
                  vertical={true}
                />
              </View>
              <Text style={styles.procreateBrushValue}>{Math.round(brushSize)}</Text>
            </View>
            
            {/* Opacity Slider - Controls REFERENCE PHOTO opacity */}
            <View style={styles.procreateBrushSliderContainer}>
              <Text style={styles.procreateBrushLabel}>Ref</Text>
              <View style={styles.procreateBrushSliderWrapper}>
                <Slider
                  style={[styles.procreateBrushSlider, { transform: [{ rotate: '-90deg' }] }]}
                  minimumValue={0}
                  maximumValue={100}
                  step={1}
                  value={editOpacity * 100}
                  onValueChange={(val) => setEditOpacity(val / 100)}
                  minimumTrackTintColor="#C9A227"
                  maximumTrackTintColor="#555"
                  thumbTintColor="#C9A227"
                  vertical={true}
                />
              </View>
              <Text style={styles.procreateBrushValue}>{Math.round(editOpacity * 100)}%</Text>
            </View>
          </View>

          {/* Top Bar - Done/Cancel */}
          <View style={styles.procreateTopBar} pointerEvents="box-none">
            <TouchableOpacity 
              style={styles.procreateTopButton}
              onPress={() => setShowEditModal(false)}
            >
              <Text style={styles.procreateTopButtonText}>✕</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={[styles.procreateTopButton, styles.procreateTopButtonDone]}
              onPress={saveEditedStencil}
            >
              <Text style={styles.procreateTopButtonTextDone}>Done</Text>
            </TouchableOpacity>
          </View>

          {/* Right Side - Tools */}
          <View style={styles.procreateRightBar} pointerEvents="box-none">
            <TouchableOpacity 
              style={[styles.procreateToolButton, !isEraser && styles.procreateToolActive]}
              onPress={() => setIsEraser(false)}
            >
              <Text style={styles.procreateToolIcon}>✏️</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={[styles.procreateToolButton, isEraser && styles.procreateToolActive]}
              onPress={() => setIsEraser(true)}
            >
              <Text style={styles.procreateToolIcon}>🧹</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={styles.procreateToolButton}
              onPress={() => setDrawingPaths(prev => prev.slice(0, -1))}
            >
              <Text style={styles.procreateToolIcon}>↩️</Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={styles.procreateToolButton}
              onPress={resetZoom}
            >
              <Text style={styles.procreateToolIcon}>⟲</Text>
            </TouchableOpacity>
          </View>

          {/* Bottom - Controls */}
          <View style={styles.procreateBottomBar} pointerEvents="box-none">
            {/* Enable Finger Drawing Toggle - Like Procreate */}
            <TouchableOpacity 
              style={[
                styles.procreateDrawModeButton,
                enableFingerPainting && styles.procreateDrawModeButtonActive
              ]}
              onPress={() => setEnableFingerPainting(!enableFingerPainting)}
            >
              <Text style={styles.procreateDrawModeIcon}>{enableFingerPainting ? '🖐️' : '✏️'}</Text>
              <Text style={[
                styles.procreateDrawModeText,
                enableFingerPainting && styles.procreateDrawModeTextActive
              ]}>
                {enableFingerPainting ? 'FINGER DRAWS' : 'PENCIL ONLY'}
              </Text>
            </TouchableOpacity>
            
            <TouchableOpacity 
              style={styles.procreateSaveButton}
              onPress={saveEditedToGallery}
            >
              <Text style={styles.procreateSaveIcon}>📤</Text>
              <Text style={styles.procreateSaveText}>Save to Photos</Text>
            </TouchableOpacity>
          </View>

          {/* Hint at top - Clear instructions */}
          <View style={styles.procreateTopHintBar} pointerEvents="box-none">
            <Text style={styles.procreateHintText}>
              {enableFingerPainting 
                ? '✏️ Apple Pencil: draw • 👆 Finger: draw • 🤏 Two fingers: zoom/pan'
                : '✏️ Apple Pencil: draw • 👆 Finger: pan • 🤏 Two fingers: zoom • Double-tap: undo'
              }
            </Text>
          </View>
          
          {/* Instant Touch Cursor - Animated on UI thread for zero delay */}
          <Animated.View style={animatedCursorStyle} pointerEvents="none" />
        </GestureHandlerRootView>
      </Modal>

      {/* Onboarding Tutorial Modal */}
      <Modal
        visible={showOnboarding}
        animationType="fade"
        transparent={true}
        statusBarTranslucent={true}
        onRequestClose={() => {}}
      >
        <View style={styles.onboardingOverlay}>
          <View style={styles.onboardingCard}>
            {/* Slide Content */}
            <View style={styles.onboardingContent}>
              <Text style={styles.onboardingIcon}>
                {ONBOARDING_SLIDES[onboardingSlide]?.icon}
              </Text>
              <Text style={styles.onboardingTitle}>
                {ONBOARDING_SLIDES[onboardingSlide]?.title}
              </Text>
              <Text style={styles.onboardingSubtitle}>
                {ONBOARDING_SLIDES[onboardingSlide]?.subtitle}
              </Text>
              <Text style={styles.onboardingDescription}>
                {ONBOARDING_SLIDES[onboardingSlide]?.description}
              </Text>
            </View>

            {/* Progress Dots */}
            <View style={styles.onboardingDots}>
              {ONBOARDING_SLIDES.map((_, index) => (
                <View
                  key={index}
                  style={[
                    styles.onboardingDot,
                    index === onboardingSlide && styles.onboardingDotActive
                  ]}
                />
              ))}
            </View>

            {/* Navigation Buttons */}
            <View style={styles.onboardingButtons}>
              {onboardingSlide > 0 && (
                <TouchableOpacity
                  style={styles.onboardingBackButton}
                  onPress={() => setOnboardingSlide(prev => prev - 1)}
                >
                  <Text style={styles.onboardingBackText}>Back</Text>
                </TouchableOpacity>
              )}
              
              <TouchableOpacity
                style={styles.onboardingNextButton}
                onPress={() => {
                  if (onboardingSlide < ONBOARDING_SLIDES.length - 1) {
                    setOnboardingSlide(prev => prev + 1);
                  } else {
                    completeOnboarding();
                  }
                }}
              >
                <Text style={styles.onboardingNextText}>
                  {ONBOARDING_SLIDES[onboardingSlide]?.buttonText}
                </Text>
              </TouchableOpacity>
            </View>

            {/* Skip Button */}
            {onboardingSlide < ONBOARDING_SLIDES.length - 1 && (
              <TouchableOpacity
                style={styles.onboardingSkip}
                onPress={completeOnboarding}
              >
                <Text style={styles.onboardingSkipText}>Skip Tutorial</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      </Modal>

      {/* Save Both Loading Overlay */}
      {isExportingPSD && (
        <View style={styles.exportLoadingOverlay}>
          <View style={styles.exportLoadingCard}>
            <ActivityIndicator size="large" color="#C9A227" />
            <Text style={styles.exportLoadingTitle}>Saving Images</Text>
            <Text style={styles.exportLoadingText}>
              Preparing stencil and reference for Procreate...
            </Text>
          </View>
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  // LUXURY DARK THEME - Brass Filigree & Black Leather
  container: {
    flex: 1,
    backgroundColor: '#0A0A0A',
  },
  // Image Quality Warning Banner Styles
  qualityWarningBanner: {
    backgroundColor: '#2D1F00',
    borderWidth: 1,
    borderColor: '#C9A227',
    borderRadius: 12,
    marginHorizontal: 16,
    marginTop: 12,
    padding: 14,
  },
  qualityWarningHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  qualityWarningIcon: {
    fontSize: 18,
    marginRight: 8,
  },
  qualityWarningTitle: {
    fontSize: 14,
    fontWeight: '700',
    color: '#C9A227',
    flex: 1,
  },
  qualityWarningClose: {
    padding: 4,
  },
  qualityWarningCloseText: {
    color: '#8B7355',
    fontSize: 16,
    fontWeight: '600',
  },
  qualityWarningText: {
    color: '#E5C76B',
    fontSize: 13,
    marginBottom: 4,
    marginLeft: 26,
  },
  qualitySuggestionsContainer: {
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#3D2D10',
  },
  qualitySuggestionsTitle: {
    color: '#C9A227',
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 4,
  },
  qualitySuggestionText: {
    color: '#9CA3AF',
    fontSize: 12,
    marginLeft: 20,
    marginBottom: 2,
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
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
  },
  headerIconButton: {
    width: 24,
    height: 24,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(26,26,26,0.8)',
    borderRadius: 4,
    borderWidth: 1,
    borderColor: '#444',
  },
  headerIconText: {
    fontSize: 11,
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
  helpButton: {
    width: 26,
    height: 26,
    borderRadius: 13,
    borderWidth: 1,
    borderColor: '#C9A227',
    justifyContent: 'center',
    alignItems: 'center',
  },
  helpButtonText: {
    color: '#C9A227',
    fontSize: 14,
    fontWeight: '700',
  },
  galleryButton: {
    padding: 5,
    borderWidth: 1,
    borderColor: '#C9A227',
    borderRadius: 6,
  },
  iconText: {
    fontSize: 16,
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
    height: 650,
    borderRadius: 12,
    backgroundColor: '#FFFFFF',
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
  editSourceButton: {
    backgroundColor: '#2A2018',
    borderColor: '#C9A227',
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
  // Auto-Enhance Toggle Styles
  autoEnhanceContainer: {
    marginTop: 10,
    marginHorizontal: 0,
  },
  autoEnhanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#1A1A1A',
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#333',
  },
  autoEnhanceLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  autoEnhanceIcon: {
    fontSize: 18,
    marginRight: 10,
  },
  autoEnhanceTextContainer: {
    flex: 1,
  },
  autoEnhanceLabel: {
    color: '#E5E5E5',
    fontSize: 14,
    fontWeight: '600',
  },
  autoEnhanceDescription: {
    color: '#888',
    fontSize: 11,
    marginTop: 2,
  },
  autoEnhanceToggle: {
    width: 46,
    height: 26,
    borderRadius: 13,
    backgroundColor: '#333',
    padding: 2,
    justifyContent: 'center',
  },
  autoEnhanceToggleOn: {
    backgroundColor: '#C9A227',
  },
  autoEnhanceToggleKnob: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: '#888',
  },
  autoEnhanceToggleKnobOn: {
    backgroundColor: '#FFF',
    alignSelf: 'flex-end',
  },
  methodToggle: {
    flexDirection: 'row',
    backgroundColor: '#333',
    borderRadius: 8,
    padding: 2,
  },
  methodToggleText: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    fontSize: 12,
    fontWeight: '600',
    color: '#888',
    borderRadius: 6,
  },
  methodToggleActive: {
    color: '#0A0A0A',
    backgroundColor: '#C9A227',
  },
  cvInfoRow: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: '#222',
  },
  cvInfoText: {
    color: '#888',
    fontSize: 11,
    textAlign: 'center',
  },
  sliderRow: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: '#222',
  },
  sliderHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  sliderLabel: {
    color: '#FFF',
    fontSize: 14,
    fontWeight: '600',
  },
  sliderValue: {
    color: '#C9A227',
    fontSize: 14,
    fontWeight: '700',
    minWidth: 30,
    textAlign: 'right',
  },
  sliderTrack: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    backgroundColor: '#333',
    borderRadius: 10,
    padding: 8,
  },
  sliderDot: {
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: '#555',
    borderWidth: 2,
    borderColor: '#444',
  },
  sliderDotActive: {
    backgroundColor: '#C9A227',
    borderColor: '#E0B82E',
  },
  sliderLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 6,
  },
  sliderMinMax: {
    color: '#888',
    fontSize: 11,
  },
  lineWeightSection: {
    marginTop: 12,
    marginHorizontal: 8,
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderWidth: 2,
    borderColor: '#333',
  },
  compactVersionSection: {
    marginTop: 10,
  },
  // Custom Button Style Selection - Dark Charcoal with Brass Labels
  stencilStyleSection: {
    marginTop: 12,
    paddingHorizontal: 16,
    backgroundColor: '#1A1A1A',
    borderRadius: 12,
    paddingVertical: 12,
    marginHorizontal: 12,
    // 3D bezel effect
    borderWidth: 2,
    borderColor: '#333',
    borderTopColor: '#444',
    borderLeftColor: '#444',
    borderBottomColor: '#111',
    borderRightColor: '#111',
  },
  styleLabelRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 12,
  },
  styleBrassLabel: {
    color: '#C9A227',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
    fontFamily: Platform.OS === 'ios' ? 'Helvetica Neue' : 'sans-serif',
    textShadowColor: 'rgba(201, 162, 39, 0.3)',
    textShadowOffset: { width: 0, height: 1 },
    textShadowRadius: 2,
    flex: 1,
    textAlign: 'center',
  },
  styleButtonsRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    gap: 12,
  },
  styleButtonWrapper: {
    width: 80,
    height: 100,
    borderRadius: 8,
    overflow: 'hidden',
    // Default brass 3D bezel border
    borderWidth: 2,
    borderColor: '#8B7320',
    borderTopColor: '#A68B26',
    borderLeftColor: '#A68B26',
    borderBottomColor: '#5C4D16',
    borderRightColor: '#5C4D16',
  },
  styleButtonSelected: {
    // Brighter brass when selected
    borderWidth: 3,
    borderColor: '#C9A227',
    borderTopColor: '#E0B82E',
    borderLeftColor: '#E0B82E',
    borderBottomColor: '#9A7B1E',
    borderRightColor: '#9A7B1E',
  },
  styleButtonDisabled: {
    opacity: 0.5,
  },
  styleButtonImage: {
    width: '100%',
    height: '100%',
    backgroundColor: '#0A0A0A',
  },
  styleRegenButton: {
    position: 'absolute',
    top: 4,
    right: 4,
    backgroundColor: 'rgba(26,26,26,0.9)',
    borderRadius: 10,
    width: 20,
    height: 20,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#333',
  },
  styleGeneratingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  cropTopButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(26,26,26,0.9)',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: '#444',
  },
  cropTopIcon: {
    fontSize: 14,
    marginRight: 5,
  },
  cropTopText: {
    color: '#C9A227',
    fontSize: 12,
    fontWeight: '600',
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
  regenButton: {
    position: 'absolute',
    top: -5,
    right: -5,
    backgroundColor: '#333',
    borderRadius: 10,
    width: 20,
    height: 20,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#C9A227',
  },
  regenButtonText: {
    fontSize: 10,
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
    paddingTop: 50,
    paddingBottom: 16,
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
  // Revert to original button
  revertButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 10,
    paddingVertical: 8,
    gap: 6,
  },
  revertButtonIcon: {
    fontSize: 14,
  },
  revertButtonText: {
    color: '#EF4444',
    fontSize: 12,
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
    marginTop: 12,
    fontFamily: 'monospace',
  },
  disclaimerContainer: {
    backgroundColor: 'rgba(201, 162, 39, 0.08)',
    borderRadius: 12,
    padding: 16,
    marginBottom: 20,
    marginHorizontal: 10,
    borderWidth: 1,
    borderColor: 'rgba(201, 162, 39, 0.2)',
  },
  disclaimerTitle: {
    fontSize: 11,
    fontWeight: '700',
    color: '#C9A227',
    textAlign: 'center',
    marginBottom: 8,
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  disclaimerText: {
    fontSize: 11,
    color: '#8B7355',
    lineHeight: 18,
    textAlign: 'left',
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
  // Minimal Share Row Styles (compact)
  minimalShareRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 16,
    gap: 8,
  },
  minimalShareButton: {
    padding: 8,
  },
  minimalShareIcon: {
    fontSize: 18,
  },
  minimalShareDivider: {
    color: '#444',
    fontSize: 14,
  },
  minimalShareText: {
    color: '#666',
    fontSize: 12,
    marginLeft: 4,
  },
  // Share & Review Section Styles (legacy - keeping for reference)
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
    paddingTop: 50,
    paddingBottom: 12,
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
    overflow: 'hidden',
  },
  editCanvasInner: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    height: '100%',
  },
  zoomIndicator: {
    position: 'absolute',
    top: 60,
    right: 16,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.7)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
    zIndex: 100,
    gap: 8,
  },
  zoomIndicatorText: {
    color: '#C9A227',
    fontSize: 14,
    fontWeight: '600',
  },
  resetZoomButton: {
    backgroundColor: '#C9A227',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  resetZoomText: {
    color: '#0A0A0A',
    fontSize: 12,
    fontWeight: '600',
  },
  editHintWrapper: {
    position: 'absolute',
    top: 70,
    left: 0,
    right: 0,
    alignItems: 'center',
    zIndex: 100,
  },
  editHintContainer: {
    backgroundColor: 'rgba(0, 0, 0, 0.9)',
    paddingHorizontal: 18,
    paddingVertical: 12,
    borderRadius: 25,
    borderWidth: 2,
    borderColor: '#C9A227',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.5,
    shadowRadius: 5,
    elevation: 5,
  },
  editHintText: {
    color: '#C9A227',
    fontSize: 15,
    fontWeight: '700',
    textAlign: 'center',
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
  // Mode Toggle - Draw vs Navigate
  modeToggleRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    marginBottom: 12,
    gap: 12,
  },
  modeToggleButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 25,
    backgroundColor: '#1A1A1A',
    borderWidth: 2,
    borderColor: '#333',
    gap: 8,
  },
  modeToggleActive: {
    backgroundColor: '#C9A227',
    borderColor: '#C9A227',
  },
  modeToggleIcon: {
    fontSize: 16,
  },
  modeToggleText: {
    color: '#9CA3AF',
    fontSize: 14,
    fontWeight: '600',
  },
  modeToggleTextActive: {
    color: '#0A0A0A',
  },
  resetZoomInlineButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 25,
    backgroundColor: '#8B7355',
    gap: 6,
  },
  resetZoomInlineText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
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
  // Procreate-Style Full Screen Editor
  procreateContainer: {
    flex: 1,
    backgroundColor: '#1A1A1A',
  },
  procreateCanvas: {
    flex: 1,
    backgroundColor: '#2A2A2A',
  },
  procreateCanvasInner: {
    flex: 1,
    position: 'relative',
  },
  procreateBackgroundImage: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    height: '100%',
  },
  procreateStencilImage: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    height: '100%',
  },
  procreateDrawingLayer: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    height: '100%',
  },
  procreateLeftBar: {
    position: 'absolute',
    left: 12,
    top: '15%',
    bottom: '25%',
    width: 50,
    justifyContent: 'center',
    alignItems: 'center',
    gap: 30,
  },
  procreateBrushSliderContainer: {
    alignItems: 'center',
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    borderRadius: 25,
    paddingVertical: 12,
    paddingHorizontal: 8,
    width: 50,
    height: 180,
  },
  procreateBrushLabel: {
    color: '#888',
    fontSize: 9,
    fontWeight: '600',
    marginBottom: 8,
  },
  procreateBrushSliderWrapper: {
    flex: 1,
    width: 150,
    justifyContent: 'center',
    alignItems: 'center',
  },
  procreateBrushSlider: {
    width: '100%',
    height: 40,
  },
  procreateBrushValue: {
    color: '#C9A227',
    fontSize: 11,
    fontWeight: '700',
    marginTop: 8,
  },
  procreateTopBar: {
    position: 'absolute',
    top: 50,
    left: 16,
    right: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  procreateTopButton: {
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    paddingVertical: 10,
    paddingHorizontal: 18,
    borderRadius: 20,
  },
  procreateTopButtonText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: '600',
  },
  procreateTopButtonDone: {
    backgroundColor: '#C9A227',
  },
  procreateTopButtonTextDone: {
    color: '#0A0A0A',
    fontSize: 16,
    fontWeight: '700',
  },
  procreateRightBar: {
    position: 'absolute',
    right: 12,
    top: '30%',
    gap: 12,
  },
  procreateToolButton: {
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    width: 50,
    height: 50,
    borderRadius: 25,
    justifyContent: 'center',
    alignItems: 'center',
  },
  procreateToolActive: {
    backgroundColor: '#C9A227',
  },
  procreateToolIcon: {
    fontSize: 22,
  },
  procreateBottomBar: {
    position: 'absolute',
    bottom: 40,
    left: 16,
    right: 16,
    alignItems: 'center',
  },
  procreateSaveButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    paddingVertical: 12,
    paddingHorizontal: 24,
    borderRadius: 25,
    borderWidth: 2,
    borderColor: '#C9A227',
    gap: 10,
  },
  procreateSaveIcon: {
    fontSize: 18,
  },
  procreateSaveText: {
    color: '#C9A227',
    fontSize: 15,
    fontWeight: '600',
  },
  procreateDrawModeButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 25,
    borderWidth: 2,
    borderColor: '#666',
    gap: 8,
  },
  procreateDrawModeButtonActive: {
    borderColor: '#4CAF50',
    backgroundColor: 'rgba(76, 175, 80, 0.2)',
  },
  procreateDrawModeIcon: {
    fontSize: 18,
  },
  procreateDrawModeText: {
    color: '#999',
    fontSize: 14,
    fontWeight: '700',
  },
  procreateDrawModeTextActive: {
    color: '#4CAF50',
  },
  procreateHint: {
    position: 'absolute',
    top: 110,
    left: 16,
    right: 16,
    alignItems: 'center',
  },
  procreateHintText: {
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    color: '#C9A227',
    fontSize: 11,
    fontWeight: '600',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 15,
    overflow: 'hidden',
    textAlign: 'center',
  },
  procreateTopHintBar: {
    position: 'absolute',
    top: 100,
    left: 16,
    right: 16,
    alignItems: 'center',
    gap: 10,
  },
  modeToggleContainer: {
    flexDirection: 'row',
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
    borderRadius: 25,
    padding: 4,
    gap: 4,
  },
  modeToggleBtn: {
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 20,
  },
  modeToggleBtnActive: {
    backgroundColor: '#C9A227',
  },
  modeToggleBtnText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  // Onboarding Tutorial Styles
  onboardingOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.9)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  onboardingCard: {
    backgroundColor: '#1A1A1A',
    borderRadius: 24,
    padding: 32,
    maxWidth: 400,
    width: '100%',
    borderWidth: 2,
    borderColor: '#C9A227',
    shadowColor: '#C9A227',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.3,
    shadowRadius: 20,
    elevation: 10,
  },
  onboardingContent: {
    alignItems: 'center',
    marginBottom: 24,
  },
  onboardingIcon: {
    fontSize: 64,
    marginBottom: 16,
  },
  onboardingTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: '#C9A227',
    textAlign: 'center',
    marginBottom: 8,
  },
  onboardingSubtitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#999',
    textAlign: 'center',
    marginBottom: 16,
  },
  onboardingDescription: {
    fontSize: 15,
    color: '#CCCCCC',
    textAlign: 'center',
    lineHeight: 24,
  },
  onboardingDots: {
    flexDirection: 'row',
    justifyContent: 'center',
    marginBottom: 24,
    gap: 8,
  },
  onboardingDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#333',
  },
  onboardingDotActive: {
    backgroundColor: '#C9A227',
    width: 24,
  },
  onboardingButtons: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 16,
    marginBottom: 16,
  },
  onboardingBackButton: {
    paddingVertical: 14,
    paddingHorizontal: 28,
    borderRadius: 25,
    borderWidth: 2,
    borderColor: '#666',
  },
  onboardingBackText: {
    color: '#999',
    fontSize: 16,
    fontWeight: '600',
  },
  onboardingNextButton: {
    backgroundColor: '#C9A227',
    paddingVertical: 14,
    paddingHorizontal: 32,
    borderRadius: 25,
  },
  onboardingNextText: {
    color: '#000',
    fontSize: 16,
    fontWeight: '700',
  },
  onboardingSkip: {
    alignItems: 'center',
  },
  onboardingSkipText: {
    color: '#666',
    fontSize: 14,
    textDecorationLine: 'underline',
  },
  // PSD Export Loading Overlay
  exportLoadingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 1000,
  },
  exportLoadingCard: {
    backgroundColor: '#1A1A1A',
    borderRadius: 16,
    padding: 32,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#C9A227',
    shadowColor: '#C9A227',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.3,
    shadowRadius: 10,
  },
  exportLoadingTitle: {
    color: '#C9A227',
    fontSize: 18,
    fontWeight: '600',
    marginTop: 16,
    marginBottom: 8,
  },
  exportLoadingText: {
    color: '#888',
    fontSize: 14,
    textAlign: 'center',
  },
});
