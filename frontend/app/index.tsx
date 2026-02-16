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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as ImagePicker from 'expo-image-picker';
import Slider from '@react-native-community/slider';
import { Ionicons } from '@expo/vector-icons';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

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
  
  // Refs for debouncing
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  
  // Settings state
  const [settings, setSettings] = useState<StencilSettings>({
    clarity: 50,
    line_weight: 50,
    noise_reduction: 50,
    invert: true,
  });

  // Live update function with debouncing
  const processImageLive = useCallback(async (currentSettings: StencilSettings) => {
    if (!originalImage || !hasGeneratedOnce) return;

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
  }, [originalImage, hasGeneratedOnce]);

  // Debounced settings change handler
  const handleSettingsChange = useCallback((newSettings: StencilSettings) => {
    setSettings(newSettings);
    
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
    } catch (error) {
      console.error('Error processing image:', error);
      Alert.alert('Error', 'Failed to process image. Please try again.');
    } finally {
      setIsProcessing(false);
    }
  }, [originalImage, settings]);

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
    setSettings({
      clarity: 50,
      line_weight: 50,
      noise_reduction: 50,
      invert: true,
    });
  };

  const renderSlider = (
    label: string,
    value: number,
    onValueChange: (val: number) => void,
    icon: string
  ) => (
    <View style={styles.sliderContainer}>
      <View style={styles.sliderHeader}>
        <Ionicons name={icon as any} size={18} color="#8B5CF6" />
        <Text style={styles.sliderLabel}>{label}</Text>
        <Text style={styles.sliderValue}>{Math.round(value)}%</Text>
      </View>
      <Slider
        style={styles.slider}
        minimumValue={0}
        maximumValue={100}
        value={value}
        onValueChange={onValueChange}
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

              {/* Stencil Image */}
              {stencilImage && (
                <View style={styles.imageWrapper}>
                  <Text style={styles.imageLabel}>Stencil</Text>
                  <Image
                    source={{ uri: stencilImage }}
                    style={styles.previewImage}
                    resizeMode="contain"
                  />
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

        {/* Settings Controls */}
        {originalImage && (
          <View style={styles.settingsSection}>
            <Text style={styles.sectionTitle}>Stencil Settings</Text>

            {renderSlider(
              'Clarity',
              settings.clarity,
              (val) => setSettings(prev => ({ ...prev, clarity: val })),
              'contrast-outline'
            )}

            {renderSlider(
              'Line Weight',
              settings.line_weight,
              (val) => setSettings(prev => ({ ...prev, line_weight: val })),
              'pencil-outline'
            )}

            {renderSlider(
              'Noise Reduction',
              settings.noise_reduction,
              (val) => setSettings(prev => ({ ...prev, noise_reduction: val })),
              'sparkles-outline'
            )}

            {/* Invert Toggle */}
            <TouchableOpacity
              style={styles.invertToggle}
              onPress={() => setSettings(prev => ({ ...prev, invert: !prev.invert }))}
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

        {/* Action Buttons */}
        {originalImage && (
          <View style={styles.actionButtons}>
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
    marginBottom: 16,
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
});
