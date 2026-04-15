import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
} from 'react-native';
import { Feather } from '@expo/vector-icons';

interface ReferralBannerProps {
  onPress: () => void;
  onDismiss: () => void;
}

export function ReferralBanner({ onPress, onDismiss }: ReferralBannerProps) {
  return (
    <TouchableOpacity
      style={styles.banner}
      onPress={onPress}
      activeOpacity={0.85}
      data-testid="referral-banner"
    >
      <View style={styles.iconWrap}>
        <Feather name="gift" size={16} color="#C9A227" />
      </View>
      <View style={styles.textWrap}>
        <Text style={styles.primary}>Invite 2 artists → get 1 free month</Text>
        <Text style={styles.secondary}>Built for tattooers. Share the workflow.</Text>
      </View>
      <TouchableOpacity
        onPress={(e) => { e.stopPropagation(); onDismiss(); }}
        style={styles.closeBtn}
        hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
        data-testid="referral-banner-dismiss"
      >
        <Feather name="x" size={14} color="#555" />
      </TouchableOpacity>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(201,162,39,0.08)',
    borderWidth: 1,
    borderColor: 'rgba(201,162,39,0.2)',
    borderRadius: 10,
    paddingVertical: 10,
    paddingLeft: 12,
    paddingRight: 8,
    marginHorizontal: 16,
    marginBottom: 8,
    gap: 10,
  },
  iconWrap: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: 'rgba(201,162,39,0.12)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  textWrap: {
    flex: 1,
  },
  primary: {
    color: '#C9A227',
    fontSize: 13,
    fontWeight: '700',
  },
  secondary: {
    color: '#666',
    fontSize: 11,
    marginTop: 1,
  },
  closeBtn: {
    width: 24,
    height: 24,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
