import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
} from 'react-native';
import { Feather } from '@expo/vector-icons';

type ThresholdLevel = 'low' | 'critical' | 'empty';

interface LowCreditModalProps {
  visible: boolean;
  level: ThresholdLevel;
  creditsRemaining: number;
  totalCredits: number;
  onUpgrade: () => void;
  onDismiss?: () => void;
}

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
    body: 'Upgrade your plan to continue generating stencils instantly.',
    icon: 'x-circle',
    color: '#ef4444',
  },
};

export function LowCreditModal({
  visible,
  level,
  creditsRemaining,
  totalCredits,
  onUpgrade,
  onDismiss,
}: LowCreditModalProps) {
  const content = CONTENT[level];
  const canDismiss = level !== 'empty';

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={canDismiss ? onDismiss : undefined}
    >
      <View style={styles.overlay}>
        <View style={[styles.card, { borderColor: content.color }]}>
          {/* Close button — not shown when empty */}
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

          {/* Upgrade button */}
          <TouchableOpacity
            onPress={onUpgrade}
            style={[styles.upgradeBtn, { backgroundColor: content.color }]}
            data-testid="low-credit-upgrade-btn"
          >
            <Feather name="arrow-up-circle" size={18} color="#fff" />
            <Text style={styles.upgradeBtnText}>
              {level === 'empty' ? 'Upgrade Now' : 'Upgrade Plan'}
            </Text>
          </TouchableOpacity>

          {/* Dismiss — only for low/critical */}
          {canDismiss && onDismiss && (
            <TouchableOpacity
              onPress={onDismiss}
              style={styles.dismissBtn}
              data-testid="low-credit-dismiss-text"
            >
              <Text style={styles.dismissText}>Dismiss</Text>
            </TouchableOpacity>
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
  dismissBtn: {
    paddingVertical: 12,
  },
  dismissText: {
    color: '#555',
    fontSize: 14,
  },
});
