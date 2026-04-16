import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
  TextInput,
  Share,
  Alert,
  Platform,
} from 'react-native';
import { Feather } from '@expo/vector-icons';
import * as StoreReview from 'expo-store-review';
import * as SecureStore from 'expo-secure-store';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type FlowStep = 'initial' | 'positive' | 'negative' | 'feedback_text' | 'done';

interface FeedbackFlowProps {
  visible: boolean;
  stencilImageUri?: string | null;
  onDismiss: () => void;
  onComplete: () => void;
}

const NEGATIVE_TAGS = [
  { id: 'too_messy', label: 'Too messy' },
  { id: 'missing_details', label: 'Missing details' },
  { id: 'not_accurate', label: 'Not accurate' },
  { id: 'hard_to_use', label: 'Hard to use' },
  { id: 'other', label: 'Other' },
];

export function FeedbackFlow({ visible, stencilImageUri, onDismiss, onComplete }: FeedbackFlowProps) {
  const [step, setStep] = useState<FlowStep>('initial');
  const [feedbackText, setFeedbackText] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [caption, setCaption] = useState(
    'Used Body Bound to build this stencil. Made the process way faster and cleaner.'
  );

  const submitFeedback = async (sentiment: string, action: string, text?: string, tags?: string[]) => {
    try {
      const token = await SecureStore.getItemAsync('session_token');
      if (!token) return;
      await fetch(`${API_URL}/api/feedback`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ sentiment, action_taken: action, text: text || '', tags: tags || [] }),
      });
    } catch (_) {}
  };

  const handlePositive = () => {
    setStep('positive');
  };

  const handleNegative = () => {
    setStep('negative');
  };

  const handleShare = async () => {
    try {
      const shareOptions: any = { message: caption };
      if (stencilImageUri && Platform.OS !== 'web') {
        shareOptions.url = stencilImageUri;
      }
      await Share.share(shareOptions);
      await submitFeedback('positive', 'shared');
      onComplete();
    } catch (_) {
      // User cancelled share
    }
  };

  const handleReview = async () => {
    await submitFeedback('positive', 'review');
    try {
      if (await StoreReview.hasAction()) {
        await StoreReview.requestReview();
      }
    } catch (_) {}
    onComplete();
  };

  const handleFeedbackSubmit = async () => {
    setStep('positive');
  };

  const handlePositiveFeedback = () => {
    setStep('feedback_text');
  };

  const handleSubmitText = async () => {
    const sentiment = step === 'feedback_text' ? 'positive' : 'negative';
    await submitFeedback(sentiment, 'feedback', feedbackText, []);
    onComplete();
  };

  const handleNegativeSubmit = async () => {
    const showTextInput = selectedTags.includes('other');
    await submitFeedback('negative', 'feedback', feedbackText, selectedTags);
    onComplete();
  };

  const handleSkip = async () => {
    await submitFeedback(step === 'negative' ? 'negative' : 'positive', 'skip');
    onDismiss();
  };

  const toggleTag = (tagId: string) => {
    setSelectedTags(prev =>
      prev.includes(tagId) ? prev.filter(t => t !== tagId) : [...prev, tagId]
    );
  };

  const resetAndClose = () => {
    setStep('initial');
    setFeedbackText('');
    setSelectedTags([]);
    onDismiss();
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={resetAndClose}>
      <View style={styles.overlay}>
        <View style={styles.card}>
          {/* Close */}
          <TouchableOpacity onPress={resetAndClose} style={styles.closeBtn} data-testid="feedback-close">
            <Feather name="x" size={20} color="#666" />
          </TouchableOpacity>

          {/* Step: Initial — "Did this save you time?" */}
          {step === 'initial' && (
            <>
              <Text style={styles.headline}>Did this save you time?</Text>
              <View style={styles.buttonRow}>
                <TouchableOpacity
                  style={[styles.thumbBtn, styles.thumbUp]}
                  onPress={handlePositive}
                  data-testid="feedback-yes"
                >
                  <Feather name="thumbs-up" size={22} color="#16A34A" />
                  <Text style={[styles.thumbText, { color: '#16A34A' }]}>Yes</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.thumbBtn, styles.thumbDown]}
                  onPress={handleNegative}
                  data-testid="feedback-no"
                >
                  <Feather name="thumbs-down" size={22} color="#ef4444" />
                  <Text style={[styles.thumbText, { color: '#ef4444' }]}>Not really</Text>
                </TouchableOpacity>
              </View>
            </>
          )}

          {/* Step: Positive — follow-up options */}
          {step === 'positive' && (
            <>
              <Text style={styles.headline}>Glad it helped</Text>
              <Text style={styles.body}>
                Want to share your result or leave quick feedback?{'\n'}Helps other artists see real-world use.
              </Text>

              <TouchableOpacity style={styles.optionBtn} onPress={handleShare} data-testid="feedback-share">
                <Feather name="share" size={18} color="#C9A227" />
                <Text style={styles.optionText}>Share result</Text>
              </TouchableOpacity>

              <TouchableOpacity style={styles.optionBtn} onPress={handlePositiveFeedback} data-testid="feedback-text">
                <Feather name="message-circle" size={18} color="#C9A227" />
                <Text style={styles.optionText}>Leave feedback</Text>
              </TouchableOpacity>

              <TouchableOpacity style={styles.optionBtn} onPress={handleReview} data-testid="feedback-review">
                <Feather name="star" size={18} color="#C9A227" />
                <Text style={styles.optionText}>Leave App Store review</Text>
              </TouchableOpacity>

              <TouchableOpacity style={styles.skipBtn} onPress={handleSkip} data-testid="feedback-skip">
                <Text style={styles.skipText}>Skip</Text>
              </TouchableOpacity>
            </>
          )}

          {/* Step: Feedback text (positive) */}
          {step === 'feedback_text' && (
            <>
              <Text style={styles.headline}>What helped the most?</Text>
              <TextInput
                style={styles.textInput}
                placeholder="Speed, clean lines, workflow..."
                placeholderTextColor="#555"
                value={feedbackText}
                onChangeText={setFeedbackText}
                multiline
                maxLength={280}
                data-testid="feedback-input"
              />
              <TouchableOpacity
                style={[styles.submitBtn, !feedbackText.trim() && { opacity: 0.4 }]}
                onPress={handleSubmitText}
                disabled={!feedbackText.trim()}
                data-testid="feedback-submit"
              >
                <Text style={styles.submitBtnText}>Submit</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.skipBtn} onPress={handleSkip}>
                <Text style={styles.skipText}>Skip</Text>
              </TouchableOpacity>
            </>
          )}

          {/* Step: Negative — quick-select tags */}
          {step === 'negative' && (
            <>
              <Text style={styles.headline}>What could be better?</Text>
              <View style={styles.tagGrid}>
                {NEGATIVE_TAGS.map(tag => (
                  <TouchableOpacity
                    key={tag.id}
                    style={[styles.tagBtn, selectedTags.includes(tag.id) && styles.tagBtnSelected]}
                    onPress={() => toggleTag(tag.id)}
                    data-testid={`feedback-tag-${tag.id}`}
                  >
                    <Text style={[styles.tagText, selectedTags.includes(tag.id) && styles.tagTextSelected]}>
                      {tag.label}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
              {selectedTags.includes('other') && (
                <TextInput
                  style={[styles.textInput, { marginTop: 10 }]}
                  placeholder="Tell us more..."
                  placeholderTextColor="#555"
                  value={feedbackText}
                  onChangeText={setFeedbackText}
                  multiline
                  maxLength={280}
                />
              )}
              <TouchableOpacity
                style={[styles.submitBtn, selectedTags.length === 0 && { opacity: 0.4 }]}
                onPress={handleNegativeSubmit}
                disabled={selectedTags.length === 0}
                data-testid="feedback-negative-submit"
              >
                <Text style={styles.submitBtnText}>Submit</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.skipBtn} onPress={handleSkip}>
                <Text style={styles.skipText}>Skip</Text>
              </TouchableOpacity>
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.65)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  card: {
    backgroundColor: '#12121f',
    borderRadius: 20,
    padding: 24,
    width: '100%',
    maxWidth: 380,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#1e1e35',
  },
  closeBtn: {
    position: 'absolute',
    top: 14,
    right: 14,
    width: 32,
    height: 32,
    justifyContent: 'center',
    alignItems: 'center',
  },
  headline: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '800',
    textAlign: 'center',
    marginTop: 12,
    marginBottom: 8,
  },
  body: {
    color: '#999',
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 20,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 16,
  },
  thumbBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 14,
    paddingHorizontal: 28,
    borderRadius: 12,
    borderWidth: 1,
  },
  thumbUp: {
    borderColor: 'rgba(22,163,74,0.3)',
    backgroundColor: 'rgba(22,163,74,0.08)',
  },
  thumbDown: {
    borderColor: 'rgba(239,68,68,0.3)',
    backgroundColor: 'rgba(239,68,68,0.08)',
  },
  thumbText: {
    fontSize: 16,
    fontWeight: '700',
  },
  optionBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    width: '100%',
    paddingVertical: 13,
    paddingHorizontal: 16,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'rgba(201,162,39,0.2)',
    backgroundColor: 'rgba(201,162,39,0.06)',
    marginBottom: 8,
  },
  optionText: {
    color: '#ddd',
    fontSize: 15,
    fontWeight: '600',
  },
  skipBtn: {
    paddingVertical: 10,
    marginTop: 4,
  },
  skipText: {
    color: '#555',
    fontSize: 14,
  },
  textInput: {
    width: '100%',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    borderRadius: 10,
    padding: 14,
    color: '#fff',
    fontSize: 15,
    minHeight: 80,
    textAlignVertical: 'top',
    marginBottom: 12,
  },
  submitBtn: {
    backgroundColor: '#C9A227',
    borderRadius: 12,
    paddingVertical: 14,
    width: '100%',
    alignItems: 'center',
  },
  submitBtnText: {
    color: '#000',
    fontWeight: '700',
    fontSize: 16,
  },
  tagGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 12,
    marginTop: 8,
    justifyContent: 'center',
  },
  tagBtn: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.04)',
  },
  tagBtnSelected: {
    borderColor: '#C9A227',
    backgroundColor: 'rgba(201,162,39,0.15)',
  },
  tagText: {
    color: '#999',
    fontSize: 13,
    fontWeight: '600',
  },
  tagTextSelected: {
    color: '#C9A227',
  },
});
