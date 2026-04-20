import React, { useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Feather } from '@expo/vector-icons';
import * as SecureStore from 'expo-secure-store';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface WalkInUpsellBannerProps {
  visible: boolean;
  onViewPlans: () => void;
  onDismiss: () => void;
}

/**
 * Subtle inline banner for Walk-In users approaching their credit limit.
 * Trigger eligibility is computed on the backend (`show_walkin_upsell` in
 * /auth/me credits payload). This component does NOT compute eligibility.
 *
 * - Not a modal — shown as a lightweight card in the main screen.
 * - No aggressive copy, no warning colors, no usage stats.
 * - Dismissal is persistent for the rest of the billing cycle (server-side).
 */
export function WalkInUpsellBanner({ visible, onViewPlans, onDismiss }: WalkInUpsellBannerProps) {
  // Mark "shown" on first render so the backend knows this cycle received it
  useEffect(() => {
    if (!visible) return;
    (async () => {
      try {
        const token = await SecureStore.getItemAsync('session_token');
        await fetch(`${API_URL}/api/upsell/walk-in/shown`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`,
          },
        });
      } catch (_) {}
    })();
  }, [visible]);

  if (!visible) return null;

  const handleViewPlans = async () => {
    try {
      const token = await SecureStore.getItemAsync('session_token');
      fetch(`${API_URL}/api/upsell/walk-in/cta-tapped`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
      });
    } catch (_) {}
    onViewPlans();
  };

  const handleDismiss = async () => {
    try {
      const token = await SecureStore.getItemAsync('session_token');
      fetch(`${API_URL}/api/upsell/walk-in/dismiss`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
      });
    } catch (_) {}
    onDismiss();
  };

  return (
    <View style={styles.card} data-testid="walkin-upsell-banner">
      <View style={styles.textWrap}>
        <Text style={styles.message}>
          Running through credits fast? Booked Out gives you more room to work.
        </Text>
        <TouchableOpacity
          onPress={handleViewPlans}
          style={styles.cta}
          data-testid="walkin-upsell-cta"
          activeOpacity={0.8}
        >
          <Text style={styles.ctaText}>View Plans</Text>
        </TouchableOpacity>
      </View>
      <TouchableOpacity
        onPress={handleDismiss}
        style={styles.dismiss}
        hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
        data-testid="walkin-upsell-dismiss"
      >
        <Feather name="x" size={16} color="rgba(255,255,255,0.45)" />
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#12121f',
    borderWidth: 1,
    borderColor: 'rgba(201,162,39,0.35)',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginHorizontal: 16,
    marginTop: 10,
    marginBottom: 4,
    gap: 10,
  },
  textWrap: {
    flex: 1,
    flexDirection: 'column',
    gap: 8,
  },
  message: {
    color: 'rgba(255,255,255,0.85)',
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '500',
  },
  cta: {
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderColor: '#C9A227',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: 'rgba(201,162,39,0.06)',
  },
  ctaText: {
    color: '#C9A227',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  dismiss: {
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
