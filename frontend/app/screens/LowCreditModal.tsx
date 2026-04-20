import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
  Alert,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { Feather } from '@expo/vector-icons';
import Purchases from 'react-native-purchases';
import * as SecureStore from 'expo-secure-store';

type ThresholdLevel = 'low' | 'critical' | 'empty';

interface LowCreditModalProps {
  visible: boolean;
  level: ThresholdLevel;
  creditsRemaining: number;
  totalCredits: number;
  onUpgrade: () => void;
  onInviteArtists?: () => void;
  onDismiss?: () => void;
  onRestoreSuccess?: () => void;
}

const ENTITLEMENT_ID = 'BODY BOUND Stencil Generator Pro';
const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const CONTENT: Record<ThresholdLevel, { headline: string; body: string; icon: string; color: string }> = {
  low: {
    headline: "You're getting low on stencil generations",
    body: "Don't get stuck mid-design. Upgrade your plan for more monthly credits.",
    icon: 'alert-triangle',
    color: '#F59E0B',
  },
  critical: {
    headline: 'Almost out of stencil generations',
    body: "You're down to your last few. Upgrade now to keep working without interruptions.",
    icon: 'alert-circle',
    color: '#ef4444',
  },
  empty: {
    headline: "You're out of stencil generations",
    body: 'Continue generating instantly by upgrading your plan.',
    icon: 'zap-off',
    color: '#C9A227',
  },
};

export function LowCreditModal({
  visible,
  level,
  creditsRemaining,
  totalCredits,
  onUpgrade,
  onInviteArtists,
  onDismiss,
  onRestoreSuccess,
}: LowCreditModalProps) {
  const content = CONTENT[level];
  const canDismiss = level !== 'empty';
  const [restoring, setRestoring] = useState(false);

  const handleRestore = async () => {
    if (restoring) return;
    if (Platform.OS === 'web') {
      Alert.alert('iOS Only', 'Restore Subscription is available on the iOS app.');
      return;
    }
    setRestoring(true);
    try {
      const customerInfo = await Purchases.restorePurchases();
      const hasActive = typeof customerInfo.entitlements.active[ENTITLEMENT_ID] !== 'undefined';
      if (hasActive) {
        const active = customerInfo.entitlements.active[ENTITLEMENT_ID];
        const productId = active?.productIdentifier;
        const isTrial = active?.periodType === 'TRIAL';
        if (productId) {
          try {
            const token = await SecureStore.getItemAsync('session_token');
            await fetch(`${API_URL}/api/subscription/sync`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
              body: JSON.stringify({
                product_id: productId,
                is_trial: isTrial,
                revenuecat_customer_id: customerInfo.originalAppUserId || '',
              }),
            });
          } catch (syncErr) {
            console.error('[LowCreditModal:Restore] sync exception', syncErr);
          }
        }
        Alert.alert('Restored', 'Subscription restored.');
        if (onRestoreSuccess) onRestoreSuccess();
      } else {
        Alert.alert('No Subscription', 'No active subscription found.');
      }
    } catch (e: any) {
      console.error('[LowCreditModal:Restore] failed', e);
      Alert.alert('Restore Failed', 'Unable to restore. Try again.');
    } finally {
      setRestoring(false);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={canDismiss ? onDismiss : undefined}
    >
      <View style={styles.overlay}>
        <View style={[styles.card, { borderColor: content.color }]}>
          {/* Close button — not shown when empty (spec: no dead ends) */}
          {canDismiss && onDismiss && (
            <TouchableOpacity
              onPress={onDismiss}
              style={styles.closeBtn}
              data-testid="low-credit-dismiss"
            >
              <Feather name="x" size={20} color="#666" />
            </TouchableOpacity>
          )}

          {/* Icon */}
          <View style={[styles.iconCircle, { backgroundColor: `${content.color}18` }]}>
            <Feather name={content.icon as any} size={28} color={content.color} />
          </View>

          {/* Credit count */}
          <Text style={[styles.creditCount, { color: content.color }]}>
            {creditsRemaining} / {totalCredits}
          </Text>
          <Text style={styles.creditLabel}>credits remaining</Text>

          {/* Headline */}
          <Text style={styles.headline}>{content.headline}</Text>

          {/* Body */}
          <Text style={styles.body}>{content.body}</Text>

          {level === 'empty' ? (
            <>
              {/* PRIMARY — Continue Generating (gold, opens paywall) */}
              <TouchableOpacity
                onPress={onUpgrade}
                style={styles.primaryBtnEmpty}
                data-testid="empty-continue-generating-btn"
                activeOpacity={0.85}
              >
                <Text style={styles.primaryBtnEmptyText}>Continue Generating</Text>
              </TouchableOpacity>

              {/* SECONDARY — Restore Subscription (outlined) */}
              <TouchableOpacity
                onPress={handleRestore}
                style={styles.restoreBtn}
                disabled={restoring}
                data-testid="empty-restore-btn"
                activeOpacity={0.85}
              >
                {restoring ? (
                  <>
                    <ActivityIndicator color="#C9A227" size="small" style={{ marginRight: 8 }} />
                    <Text style={styles.restoreBtnText}>Checking subscription…</Text>
                  </>
                ) : (
                  <Text style={styles.restoreBtnText}>Restore Subscription</Text>
                )}
              </TouchableOpacity>

              {/* Helper text — small, ~60% opacity, not clickable */}
              <Text style={styles.helperText}>Already subscribed? Restore your purchase.</Text>
            </>
          ) : (
            <>
              {/* Low / Critical — keep existing Upgrade + Invite + Dismiss pattern */}
              <TouchableOpacity
                onPress={onUpgrade}
                style={[styles.upgradeBtn, { backgroundColor: content.color }]}
                data-testid="low-credit-upgrade-btn"
              >
                <Feather name="arrow-up-circle" size={18} color="#fff" />
                <Text style={styles.upgradeBtnText}>Upgrade Plan</Text>
              </TouchableOpacity>

              {onInviteArtists && (
                <TouchableOpacity
                  onPress={onInviteArtists}
                  style={styles.inviteBtn}
                  data-testid="low-credit-invite-btn"
                >
                  <Feather name="users" size={16} color="#C9A227" />
                  <Text style={styles.inviteBtnText}>Invite 2 Artists → Free Month</Text>
                </TouchableOpacity>
              )}

              {onDismiss && (
                <TouchableOpacity
                  onPress={onDismiss}
                  style={styles.dismissBtn}
                  data-testid="low-credit-dismiss-text"
                >
                  <Text style={styles.dismissText}>Dismiss</Text>
                </TouchableOpacity>
              )}
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
  iconCircle: {
    width: 56,
    height: 56,
    borderRadius: 28,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
    marginTop: 8,
  },
  creditCount: {
    fontSize: 28,
    fontWeight: '800',
    letterSpacing: 1,
  },
  creditLabel: {
    color: '#666',
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 16,
  },
  headline: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '700',
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 8,
  },
  body: {
    color: '#999',
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 24,
  },
  // Empty-state primary (gold)
  primaryBtnEmpty: {
    backgroundColor: '#C9A227',
    borderRadius: 12,
    paddingVertical: 14,
    width: '100%',
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryBtnEmptyText: {
    color: '#000',
    fontWeight: '800',
    fontSize: 16,
    letterSpacing: 0.3,
  },
  // Empty-state secondary (outlined)
  restoreBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.5,
    borderColor: '#C9A227',
    backgroundColor: 'rgba(201,162,39,0.08)',
    borderRadius: 12,
    paddingVertical: 12,
    width: '100%',
    marginTop: 10,
    marginBottom: 8,
  },
  restoreBtnText: {
    color: '#C9A227',
    fontWeight: '700',
    fontSize: 15,
  },
  helperText: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 12,
    textAlign: 'center',
    marginTop: 2,
  },
  // Low/Critical legacy styles
  upgradeBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 24,
    width: '100%',
    gap: 8,
  },
  upgradeBtnText: {
    color: '#fff',
    fontWeight: '700',
    fontSize: 16,
  },
  inviteBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(201,162,39,0.1)',
    borderWidth: 1,
    borderColor: '#C9A227',
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 24,
    width: '100%',
    gap: 8,
    marginTop: 8,
  },
  inviteBtnText: {
    color: '#C9A227',
    fontWeight: '600',
    fontSize: 14,
  },
  dismissBtn: {
    paddingVertical: 12,
  },
  dismissText: {
    color: '#555',
    fontSize: 14,
  },
});
