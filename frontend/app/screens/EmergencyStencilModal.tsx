import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { Feather } from '@expo/vector-icons';
import * as SecureStore from 'expo-secure-store';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface EmergencyStencilModalProps {
  visible: boolean;
  onClaim: () => void;
  onDismiss: () => void;
}

export function EmergencyStencilModal({
  visible,
  onClaim,
  onDismiss,
}: EmergencyStencilModalProps) {
  const [claiming, setClaiming] = useState(false);

  const handleClaim = async () => {
    if (claiming) return;
    setClaiming(true);
    try {
      const token = await SecureStore.getItemAsync('session_token');
      const resp = await fetch(`${API_URL}/api/credits/emergency-stencil`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
      });
      if (!resp.ok) {
        const errText = await resp.text();
        let msg = 'Emergency stencil unavailable.';
        try {
          const err = JSON.parse(errText);
          msg = err.detail || msg;
        } catch (_) {}
        Alert.alert('Unavailable', msg);
        setClaiming(false);
        return;
      }
      // Success — parent refreshes credits and returns user to generation flow
      onClaim();
    } catch (e: any) {
      console.error('[EmergencyStencil] claim failed', e);
      Alert.alert('Unable to Continue', 'Please try again.');
    } finally {
      setClaiming(false);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onDismiss}
    >
      <View style={styles.overlay}>
        <View style={styles.card}>
          <View style={styles.iconCircle}>
            <Feather name="life-buoy" size={28} color="#C9A227" />
          </View>

          <Text style={styles.headline}>Need one more?</Text>
          <Text style={styles.body}>
            Use your monthly emergency stencil to finish your piece.
          </Text>

          {/* Primary — Use Emergency Stencil */}
          <TouchableOpacity
            onPress={handleClaim}
            disabled={claiming}
            style={[styles.primaryBtn, claiming && { opacity: 0.6 }]}
            data-testid="emergency-use-btn"
            activeOpacity={0.85}
          >
            {claiming ? (
              <ActivityIndicator color="#000" />
            ) : (
              <Text style={styles.primaryBtnText}>Use Emergency Stencil</Text>
            )}
          </TouchableOpacity>

          {/* Secondary — Maybe later */}
          <TouchableOpacity
            onPress={onDismiss}
            style={styles.secondaryBtn}
            data-testid="emergency-later-btn"
            activeOpacity={0.85}
          >
            <Text style={styles.secondaryBtnText}>Maybe later</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  card: {
    backgroundColor: '#12121f',
    borderRadius: 20,
    padding: 28,
    width: '100%',
    maxWidth: 380,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#C9A227',
  },
  iconCircle: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: 'rgba(201,162,39,0.12)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  headline: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '800',
    textAlign: 'center',
    marginBottom: 8,
  },
  body: {
    color: '#999',
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 22,
  },
  primaryBtn: {
    backgroundColor: '#C9A227',
    borderRadius: 12,
    paddingVertical: 14,
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryBtnText: {
    color: '#000',
    fontWeight: '800',
    fontSize: 16,
    letterSpacing: 0.3,
  },
  secondaryBtn: {
    paddingVertical: 14,
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 4,
  },
  secondaryBtnText: {
    color: '#888',
    fontSize: 14,
    fontWeight: '600',
  },
});
