import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
  Share,
} from 'react-native';
import { Feather } from '@expo/vector-icons';
import * as Clipboard from 'expo-clipboard';

interface ReferralPopupProps {
  visible: boolean;
  referralLink: string;
  referralCode: string;
  onInvite: () => void;
  onCopyLink: () => void;
  onDismiss: () => void;
}

export function ReferralPopup({
  visible,
  referralLink,
  referralCode,
  onInvite,
  onCopyLink,
  onDismiss,
}: ReferralPopupProps) {
  const handleShare = async () => {
    try {
      await Share.share({
        message: `Stop wasting hours hand-drawing realism stencils. I use BODY BOUND and it's a game changer. Try it free: ${referralLink}`,
      });
      onInvite();
    } catch (_) {}
  };

  const handleCopy = async () => {
    try {
      await Clipboard.setStringAsync(referralLink);
    } catch (_) {}
    onCopyLink();
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
          {/* Close button */}
          <TouchableOpacity
            onPress={onDismiss}
            style={styles.closeBtn}
            data-testid="referral-popup-dismiss"
          >
            <Feather name="x" size={20} color="#666" />
          </TouchableOpacity>

          {/* Icon */}
          <View style={styles.iconCircle}>
            <Feather name="users" size={28} color="#C9A227" />
          </View>

          {/* Headline */}
          <Text style={styles.headline}>
            Know tattooers still wasting hours building realism stencils by hand?
          </Text>

          {/* Body */}
          <Text style={styles.body}>
            Invite 2 artists who become verified subscribers and get 1 free month.
          </Text>

          {/* Invite Artists button */}
          <TouchableOpacity
            onPress={handleShare}
            style={styles.primaryBtn}
            data-testid="referral-popup-invite"
          >
            <Feather name="share" size={18} color="#000" />
            <Text style={styles.primaryBtnText}>Invite Artists</Text>
          </TouchableOpacity>

          {/* Copy Link button */}
          <TouchableOpacity
            onPress={handleCopy}
            style={styles.secondaryBtn}
            data-testid="referral-popup-copy"
          >
            <Feather name="copy" size={16} color="#C9A227" />
            <Text style={styles.secondaryBtnText}>Copy My Link</Text>
          </TouchableOpacity>

          {/* Maybe Later */}
          <TouchableOpacity
            onPress={onDismiss}
            style={styles.laterBtn}
            data-testid="referral-popup-later"
          >
            <Text style={styles.laterText}>Maybe Later</Text>
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
  iconCircle: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: 'rgba(201, 162, 39, 0.12)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 18,
    marginTop: 8,
  },
  headline: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '700',
    textAlign: 'center',
    lineHeight: 24,
    marginBottom: 10,
  },
  body: {
    color: '#999',
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 24,
  },
  primaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#C9A227',
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 24,
    width: '100%',
    gap: 8,
    marginBottom: 10,
  },
  primaryBtnText: {
    color: '#000',
    fontWeight: '700',
    fontSize: 16,
  },
  secondaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(201, 162, 39, 0.1)',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#C9A227',
    paddingVertical: 12,
    paddingHorizontal: 24,
    width: '100%',
    gap: 8,
    marginBottom: 10,
  },
  secondaryBtnText: {
    color: '#C9A227',
    fontWeight: '600',
    fontSize: 15,
  },
  laterBtn: {
    paddingVertical: 10,
  },
  laterText: {
    color: '#555',
    fontSize: 14,
  },
});
