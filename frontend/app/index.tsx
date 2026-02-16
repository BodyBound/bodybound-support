import React, { useState, useCallback, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as ImagePicker from 'expo-image-picker';
import * as ImageManipulator from 'expo-image-manipulator';
import * as MediaLibrary from 'expo-media-library';
import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import * as FileSystem from 'expo-file-system';
import Slider from '@react-native-community/slider';
import { Ionicons } from '@expo/vector-icons';

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

interface CropRegion {
  originX: number;
  originY: number;
  width: number;
  height: number;
}

export default function Index() {
  const [originalImage, setOriginalImage] = useState<string | null>(null);
  const [stencilImage, setStencilImage] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isLiveUpdating, setIsLiveUpdating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [showGallery, setShowGallery] = useState(false);
  const [savedStencils, setSavedStencils] = useState<SavedStencil[]>([]);
  const [loadingGallery, setLoadingGallery] = useState(false);
  const [stencilName, setStencilName] = useState('');
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [hasGeneratedOnce, setHasGeneratedOnce] = useState(false);
  
  // New states for crop and background removal
  const [isRemovingBackground, setIsRemovingBackground] = useState(false);
  const [showCropModal, setShowCropModal] = useState(false);
  const [cropImage, setCropImage] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState({ width: 0, height: 0 });
  const [cropRegion, setCropRegion] = useState<CropRegion>({ originX: 0, originY: 0, width: 100, height: 100 });
  
  // AI Stencil states
  const [isGeneratingAI, setIsGeneratingAI] = useState(false);
  const [stencilMode, setStencilMode] = useState<'basic' | 'ai'>('ai'); // Default to AI mode
  const [lineColor, setLineColor] = useState<'purple' | 'blue' | 'black'>('purple');
  
  // Full-size preview state
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  
  // Interactive crop states
  const [cropBoxPosition, setCropBoxPosition] = useState({ x: 20, y: 20 });
  const [cropBoxSize, setCropBoxSize] = useState({ width: 200, height: 200 });
  const [displayImageSize, setDisplayImageSize] = useState({ width: 0, height: 0 });
  
  // Refs for debouncing
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  
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

  // Open crop modal
  const openCropModal = async () => {
    if (!originalImage) {
      Alert.alert('No Image', 'Please select an image first.');
      return;
    }

    // Get image dimensions
    Image.getSize(originalImage, (width, height) => {
      setImageSize({ width, height });
      setCropRegion({
        originX: width * 0.1,
        originY: height * 0.1,
        width: width * 0.8,
        height: height * 0.8,
      });
      setCropImage(originalImage);
      setShowCropModal(true);
    }, (error) => {
      console.error('Error getting image size:', error);
      // Default size
      setImageSize({ width: 1000, height: 1000 });
      setCropRegion({ originX: 100, originY: 100, width: 800, height: 800 });
      setCropImage(originalImage);
      setShowCropModal(true);
    });
  };

  // Apply crop
  const applyCrop = async () => {
    if (!cropImage) return;

    try {
      // Extract base64 data
      const base64Data = cropImage.includes(',') ? cropImage.split(',')[1] : cropImage;
      
      const manipResult = await ImageManipulator.manipulateAsync(
        cropImage,
        [
          {
            crop: {
              originX: Math.max(0, Math.round(cropRegion.originX)),
              originY: Math.max(0, Math.round(cropRegion.originY)),
              width: Math.max(10, Math.round(cropRegion.width)),
              height: Math.max(10, Math.round(cropRegion.height)),
            },
          },
        ],
        { compress: 0.8, format: ImageManipulator.SaveFormat.PNG, base64: true }
      );

      if (manipResult.base64) {
        const croppedImage = `data:image/png;base64,${manipResult.base64}`;
        setOriginalImage(croppedImage);
        setStencilImage(null);
        setHasGeneratedOnce(false);
        setShowCropModal(false);
        Alert.alert('Success', 'Image cropped successfully!');
      }
    } catch (error) {
      console.error('Error cropping image:', error);
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

  const renderSlider = (
    label: string,
    value: number,
    settingKey: keyof StencilSettings,
    icon: string
  ) => (
    <View style={styles.sliderContainer}>
      <View style={styles.sliderHeader}>
        <Ionicons name={icon as any} size={18} color="#8B5CF6" />
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
            <Ionicons name="close" size={28} color="#fff" />
          </TouchableOpacity>
        </View>

        {loadingGallery ? (
          <ActivityIndicator size="large" color="#8B5CF6" style={styles.loader} />
        ) : savedStencils.length === 0 ? (
          <View style={styles.emptyGallery}>
            <Ionicons name="images-outline" size={64} color="#4B5563" />
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
                  <Ionicons name="trash-outline" size={22} color="#EF4444" />
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

  // Crop Modal - Simple crop with sliders
  const renderCropModal = () => (
    <Modal
      visible={showCropModal}
      animationType="slide"
      transparent={false}
      onRequestClose={() => setShowCropModal(false)}
    >
      <SafeAreaView style={styles.cropModalContainer}>
        <View style={styles.cropModalHeader}>
          <TouchableOpacity onPress={() => setShowCropModal(false)}>
            <Ionicons name="close" size={28} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.cropModalTitle}>Crop Image</Text>
          <TouchableOpacity onPress={applyCrop}>
            <Ionicons name="checkmark" size={28} color="#10B981" />
          </TouchableOpacity>
        </View>

        {cropImage && (
          <View style={styles.cropPreviewContainer}>
            <Image
              source={{ uri: cropImage }}
              style={styles.cropPreviewImage}
              resizeMode="contain"
            />
          </View>
        )}

        <View style={styles.cropControls}>
          <Text style={styles.cropControlsTitle}>Adjust Crop Region</Text>
          
          <View style={styles.cropSliderRow}>
            <Text style={styles.cropSliderLabel}>X Position</Text>
            <Slider
              style={styles.cropSlider}
              minimumValue={0}
              maximumValue={imageSize.width * 0.5}
              value={cropRegion.originX}
              onValueChange={(val) => setCropRegion(prev => ({ ...prev, originX: val }))}
              minimumTrackTintColor="#8B5CF6"
              maximumTrackTintColor="#374151"
              thumbTintColor="#8B5CF6"
            />
          </View>

          <View style={styles.cropSliderRow}>
            <Text style={styles.cropSliderLabel}>Y Position</Text>
            <Slider
              style={styles.cropSlider}
              minimumValue={0}
              maximumValue={imageSize.height * 0.5}
              value={cropRegion.originY}
              onValueChange={(val) => setCropRegion(prev => ({ ...prev, originY: val }))}
              minimumTrackTintColor="#8B5CF6"
              maximumTrackTintColor="#374151"
              thumbTintColor="#8B5CF6"
            />
          </View>

          <View style={styles.cropSliderRow}>
            <Text style={styles.cropSliderLabel}>Width</Text>
            <Slider
              style={styles.cropSlider}
              minimumValue={imageSize.width * 0.2}
              maximumValue={imageSize.width}
              value={cropRegion.width}
              onValueChange={(val) => setCropRegion(prev => ({ ...prev, width: val }))}
              minimumTrackTintColor="#8B5CF6"
              maximumTrackTintColor="#374151"
              thumbTintColor="#8B5CF6"
            />
          </View>

          <View style={styles.cropSliderRow}>
            <Text style={styles.cropSliderLabel}>Height</Text>
            <Slider
              style={styles.cropSlider}
              minimumValue={imageSize.height * 0.2}
              maximumValue={imageSize.height}
              value={cropRegion.height}
              onValueChange={(val) => setCropRegion(prev => ({ ...prev, height: val }))}
              minimumTrackTintColor="#8B5CF6"
              maximumTrackTintColor="#374151"
              thumbTintColor="#8B5CF6"
            />
          </View>

          <View style={styles.cropInfoRow}>
            <Text style={styles.cropInfoText}>
              Crop: {Math.round(cropRegion.originX)}, {Math.round(cropRegion.originY)} - {Math.round(cropRegion.width)}x{Math.round(cropRegion.height)}
            </Text>
          </View>
        </View>
      </SafeAreaView>
    </Modal>
  );

  return (
    <SafeAreaView style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Tattoo Stencil</Text>
        <TouchableOpacity
          style={styles.galleryButton}
          onPress={() => {
            loadGallery();
            setShowGallery(true);
          }}
        >
          <Ionicons name="folder-outline" size={24} color="#8B5CF6" />
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {/* Image Preview Area */}
        <View style={styles.previewSection}>
          {!originalImage ? (
            <View style={styles.placeholderContainer}>
              <Ionicons name="image-outline" size={64} color="#4B5563" />
              <Text style={styles.placeholderText}>Select or capture a photo</Text>
            </View>
          ) : (
            <View style={styles.imagesContainer}>
              {/* Original Image */}
              <View style={styles.imageWrapper}>
                <Text style={styles.imageLabel}>Original</Text>
                <Image
                  source={{ uri: originalImage }}
                  style={styles.previewImage}
                  resizeMode="contain"
                />
              </View>

              {/* Stencil Image - Clickable for full preview */}
              {stencilImage && (
                <View style={styles.imageWrapper}>
                  <View style={styles.stencilLabelRow}>
                    <Text style={styles.imageLabel}>Stencil</Text>
                    <TouchableOpacity 
                      onPress={() => setShowPreviewModal(true)}
                      style={styles.expandButton}
                    >
                      <Ionicons name="expand-outline" size={18} color="#8B5CF6" />
                      <Text style={styles.expandButtonText}>Full View</Text>
                    </TouchableOpacity>
                  </View>
                  <TouchableOpacity 
                    onPress={() => setShowPreviewModal(true)}
                    activeOpacity={0.8}
                  >
                    <View style={styles.stencilImageContainer}>
                      <Image
                        source={{ uri: stencilImage }}
                        style={[styles.previewImage, isLiveUpdating && styles.imageUpdating]}
                        resizeMode="contain"
                      />
                      {isLiveUpdating && (
                        <View style={styles.updatingOverlay}>
                          <ActivityIndicator size="small" color="#8B5CF6" />
                          <Text style={styles.updatingText}>Updating...</Text>
                        </View>
                      )}
                    </View>
                  </TouchableOpacity>
                  
                  {/* Export Action Buttons */}
                  <View style={styles.exportButtons}>
                    <TouchableOpacity style={styles.exportButton} onPress={saveToDevice}>
                      <Ionicons name="download-outline" size={20} color="#10B981" />
                      <Text style={styles.exportButtonText}>Save</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.exportButton} onPress={printStencil}>
                      <Ionicons name="print-outline" size={20} color="#3B82F6" />
                      <Text style={styles.exportButtonText}>Print</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.exportButton} onPress={shareStencil}>
                      <Ionicons name="share-outline" size={20} color="#F59E0B" />
                      <Text style={styles.exportButtonText}>Share</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              )}
            </View>
          )}
        </View>

        {/* Image Source Buttons */}
        <View style={styles.sourceButtons}>
          <TouchableOpacity style={styles.sourceButton} onPress={pickImage}>
            <Ionicons name="images" size={22} color="#fff" />
            <Text style={styles.sourceButtonText}>Gallery</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.sourceButton} onPress={takePhoto}>
            <Ionicons name="camera" size={22} color="#fff" />
            <Text style={styles.sourceButtonText}>Camera</Text>
          </TouchableOpacity>
          {originalImage && (
            <TouchableOpacity style={styles.resetButton} onPress={resetAll}>
              <Ionicons name="refresh" size={22} color="#EF4444" />
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
                <Ionicons name="crop-outline" size={22} color="#8B5CF6" />
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
                  <Ionicons name="cut-outline" size={22} color="#8B5CF6" />
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
                <Ionicons name="color-wand-outline" size={18} color="#8B5CF6" />
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
                <Ionicons name="sparkles" size={18} color={stencilMode === 'ai' ? '#fff' : '#8B5CF6'} />
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
                <Ionicons name="options" size={18} color={stencilMode === 'basic' ? '#fff' : '#8B5CF6'} />
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
              <TouchableOpacity
                style={[styles.aiButton, isGeneratingAI && styles.buttonDisabled]}
                onPress={generateAIStencil}
                disabled={isGeneratingAI}
              >
                {isGeneratingAI ? (
                  <>
                    <ActivityIndicator size="small" color="#fff" />
                    <Text style={styles.aiButtonText}>Creating Stencil...</Text>
                  </>
                ) : (
                  <>
                    <Ionicons name="sparkles" size={22} color="#fff" />
                    <Text style={styles.aiButtonText}>Generate AI Stencil</Text>
                  </>
                )}
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                style={[styles.processButton, isProcessing && styles.buttonDisabled]}
                onPress={processImage}
                disabled={isProcessing}
              >
                {isProcessing ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <>
                    <Ionicons name="flash" size={22} color="#fff" />
                    <Text style={styles.processButtonText}>Generate Stencil</Text>
                  </>
                )}
              </TouchableOpacity>
            )}

            {stencilImage && (
              <TouchableOpacity
                style={styles.saveButton}
                onPress={() => setShowSaveModal(true)}
              >
                <Ionicons name="save-outline" size={22} color="#8B5CF6" />
                <Text style={styles.saveButtonText}>Save</Text>
              </TouchableOpacity>
            )}
          </View>
        )}

        <View style={styles.bottomSpacer} />
      </ScrollView>

      {renderGalleryModal()}
      {renderSaveModal()}
      {renderCropModal()}
      
      {/* Full-Size Preview Modal */}
      <Modal
        visible={showPreviewModal}
        animationType="fade"
        transparent={true}
        onRequestClose={() => setShowPreviewModal(false)}
      >
        <View style={styles.previewModalContainer}>
          <TouchableOpacity 
            style={styles.previewModalClose}
            onPress={() => setShowPreviewModal(false)}
          >
            <Ionicons name="close-circle" size={36} color="#fff" />
          </TouchableOpacity>
          
          {stencilImage && (
            <Image
              source={{ uri: stencilImage }}
              style={styles.previewModalImage}
              resizeMode="contain"
            />
          )}
          
          <View style={styles.previewModalActions}>
            <TouchableOpacity style={styles.previewActionButton} onPress={saveToDevice}>
              <Ionicons name="download-outline" size={24} color="#10B981" />
              <Text style={styles.previewActionText}>Save to Device</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.previewActionButton} onPress={printStencil}>
              <Ionicons name="print-outline" size={24} color="#3B82F6" />
              <Text style={styles.previewActionText}>Print</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.previewActionButton} onPress={shareStencil}>
              <Ionicons name="share-outline" size={24} color="#F59E0B" />
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
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#1F1F1F',
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: '#fff',
  },
  galleryButton: {
    padding: 8,
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
  imageLabel: {
    color: '#9CA3AF',
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 8,
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
    height: SCREEN_HEIGHT * 0.6,
    borderRadius: 12,
  },
  previewModalActions: {
    flexDirection: 'row',
    marginTop: 30,
    gap: 20,
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
});
