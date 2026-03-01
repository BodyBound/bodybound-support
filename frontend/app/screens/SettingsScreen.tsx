import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Alert,
  ActivityIndicator,
  Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Purchases from 'react-native-purchases';
import * as SecureStore from 'expo-secure-store';
import { User, UserCredits } from '../types';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const TIER_LABELS: Record<string, string> = {
  trial: 'Free Trial',
  'walk-in': 'The Walk-In',
  'booked-out': 'Booked Out',
  'the-shop': 'The Shop',
};

interface SettingsScreenProps {
  user: User | null;
  credits: UserCredits | null;
  onSignOut: () => void;
  onClose: () => void;
  onManageSubscription: () => void;
}

export function SettingsScreen({
  user,
  credits,
  onSignOut,
  onClose,
  onManageSubscription,
}: SettingsScreenProps) {
  const [deletingAccount, setDeletingAccount] = useState(false);
  const [restoringPurchases, setRestoringPurchases] = useState(false);

  const handleRestorePurchases = async () => {
    setRestoringPurchases(true);
    try {
      const customerInfo = await Purchases.restorePurchases();
      if (typeof customerInfo.entitlements.active['premium'] !== 'undefined') {
        Alert.alert('Restored!', 'Your previous subscription has been restored.');
      } else {
        Alert.alert(
          'No Purchase Found',
          'No active subscription was found for your account. If you believe this is an error, please contact support.'
        );
      }
    } catch (err: any) {
      Alert.alert('Restore Failed', err.message || 'Please try again.');
    } finally {
      setRestoringPurchases(false);
    }
  };

  const handleDeleteAccount = () => {
    Alert.alert(
      'Delete Account',
      'This will permanently delete your account and all associated data. This cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: confirmDeleteAccount,
        },
      ]
    );
  };

  const confirmDeleteAccount = async () => {
    setDeletingAccount(true);
    try {
      const token = await SecureStore.getItemAsync('session_token');
      const response = await fetch(`${API_URL}/api/account/delete`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      if (response.ok) {
        await SecureStore.deleteItemAsync('session_token');
        Alert.alert('Account Deleted', 'Your account has been deleted successfully.');
        onSignOut();
      } else {
        const err = await response.json();
        throw new Error(err.detail || 'Failed to delete account');
      }
    } catch (err: any) {
      Alert.alert('Error', err.message || 'Failed to delete account. Please try again.');
    } finally {
      setDeletingAccount(false);
    }
  };

  const handleSignOut = async () => {
    await SecureStore.deleteItemAsync('session_token');
    onSignOut();
  };

  const tierLabel = credits?.tier ? TIER_LABELS[credits.tier] || credits.tier : 'No Subscription';
  const renewalDate = credits?.renewal_date
    ? new Date(credits.renewal_date).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
    : null;

  return (
    <View style={styles.container}>
      {/* Background image — same as WelcomeScreen */}
      <Image
        source={require('../../assets/images/splash-background.png')}
        style={styles.backgroundImage}
        resizeMode="cover"
      />
      <View style={styles.overlay} />

      <SafeAreaView style={styles.safeArea}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Settings</Text>
          <TouchableOpacity testID="settings-close-btn" onPress={onClose} style={styles.closeBtn}>
            <Text style={styles.closeBtnText}>✕</Text>
          </TouchableOpacity>
        </View>

        <ScrollView showsVerticalScrollIndicator={false}>
          {/* Account Info */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>ACCOUNT</Text>
            {user && (
              <>
                <View style={styles.row}>
                  <Text style={styles.rowLabel}>Name</Text>
                  <Text style={styles.rowValue}>{user.name || 'Not set'}</Text>
                </View>
                <View style={styles.row}>
                  <Text style={styles.rowLabel}>Email</Text>
                  <Text style={styles.rowValue}>{user.email || 'Not set'}</Text>
                </View>
              </>
            )}
          </View>

          {/* Credits & Subscription */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>SUBSCRIPTION</Text>
            <View style={styles.creditsCard}>
              <View style={styles.creditsRow}>
                <Text style={styles.creditsLabel}>Credits Remaining</Text>
                <Text style={styles.creditsValue} testID="credits-display">
                  {credits?.available_credits ?? 0}
                </Text>
              </View>
              <View style={styles.creditsDivider} />
              <View style={styles.creditsRow}>
                <Text style={styles.creditsLabel}>Plan</Text>
                <Text style={[styles.creditsValue, { color: '#C9A227' }]}>{tierLabel}</Text>
              </View>
              {renewalDate && (
                <View style={styles.creditsRow}>
                  <Text style={styles.creditsLabel}>Renews</Text>
                  <Text style={styles.creditsValue}>{renewalDate}</Text>
                </View>
              )}
              {credits?.is_trial && (
                <View style={styles.trialBanner}>
                  <Text style={styles.trialBannerText}>
                    {credits.trial_days_remaining !== undefined && credits.trial_days_remaining !== null
                      ? credits.trial_days_remaining > 0
                        ? `Free Trial • ${credits.trial_days_remaining} day${credits.trial_days_remaining === 1 ? '' : 's'} remaining`
                        : 'Free Trial Expired'
                      : 'Free Trial Active'}
                  </Text>
                </View>
              )}
              {credits?.tier === 'trial_expired' && (
                <View style={[styles.trialBanner, { borderColor: '#FF4444', backgroundColor: 'rgba(255,68,68,0.1)' }]}>
                  <Text style={[styles.trialBannerText, { color: '#FF4444' }]}>
                    Trial Expired • Subscribe to continue
                  </Text>
                </View>
              )}
            </View>

            <TouchableOpacity
              testID="manage-subscription-btn"
              style={styles.actionBtn}
              onPress={onManageSubscription}
            >
              <Text style={styles.actionBtnText}>Manage Subscription</Text>
            </TouchableOpacity>

            <TouchableOpacity
              testID="restore-purchases-btn"
              style={styles.actionBtn}
              onPress={handleRestorePurchases}
              disabled={restoringPurchases}
            >
              {restoringPurchases ? (
                <ActivityIndicator color="#C9A227" size="small" />
              ) : (
                <Text style={styles.actionBtnText}>Restore Purchases</Text>
              )}
            </TouchableOpacity>
          </View>

          {/* Sign Out */}
          <View style={styles.section}>
            <TouchableOpacity
              testID="sign-out-btn"
              style={styles.actionBtn}
              onPress={handleSignOut}
            >
              <Text style={styles.actionBtnText}>Sign Out</Text>
            </TouchableOpacity>
          </View>

          {/* Danger Zone */}
          <View style={[styles.section, styles.dangerSection]}>
            <Text style={[styles.sectionTitle, { color: '#FF4444' }]}>DANGER ZONE</Text>
            <TouchableOpacity
              testID="delete-account-btn"
              style={styles.deleteBtn}
              onPress={handleDeleteAccount}
              disabled={deletingAccount}
            >
              {deletingAccount ? (
                <ActivityIndicator color="#FF4444" size="small" />
              ) : (
                <Text style={styles.deleteBtnText}>Delete Account</Text>
              )}
            </TouchableOpacity>
            <Text style={styles.deleteWarning}>
              This permanently deletes your account and all data.
            </Text>
          </View>
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0A0A0A' },
  backgroundImage: {
    position: 'absolute',
    top: 0, left: 0, right: 0, bottom: 0,
    width: '100%', height: '100%',
  },
  overlay: {
    position: 'absolute',
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.72)',
  },
  safeArea: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#1A1A1A',
  },
  headerTitle: { fontSize: 18, fontWeight: '700', color: '#C9A227', letterSpacing: 1 },
  closeBtn: { padding: 8 },
  closeBtnText: { color: '#666', fontSize: 18 },
  section: {
    paddingHorizontal: 20,
    paddingVertical: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#1A1A1A',
    gap: 12,
  },
  dangerSection: { borderBottomWidth: 0 },
  sectionTitle: {
    fontSize: 11, fontWeight: '700', color: '#666',
    letterSpacing: 1.5, marginBottom: 4,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 4,
  },
  rowLabel: { color: 'rgba(255,255,255,0.5)', fontSize: 15 },
  rowValue: { color: '#FFFFFF', fontSize: 15, fontWeight: '500' },
  creditsCard: {
    backgroundColor: '#141414',
    borderWidth: 1, borderColor: '#2A2A2A',
    borderRadius: 8, padding: 16, gap: 10,
  },
  creditsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  creditsLabel: { color: 'rgba(255,255,255,0.5)', fontSize: 14 },
  creditsValue: { color: '#FFFFFF', fontSize: 20, fontWeight: '700' },
  creditsDivider: { height: 1, backgroundColor: '#2A2A2A' },
  trialBanner: {
    backgroundColor: '#2D1F00',
    borderWidth: 1, borderColor: '#C9A227',
    borderRadius: 4, padding: 8,
    alignItems: 'center',
  },
  trialBannerText: { color: '#C9A227', fontSize: 13, fontWeight: '600' },
  actionBtn: {
    backgroundColor: '#141414',
    borderWidth: 1, borderColor: '#2A2A2A',
    borderRadius: 6, padding: 14,
    alignItems: 'center',
  },
  actionBtnText: { color: '#C9A227', fontSize: 15, fontWeight: '600' },
  deleteBtn: {
    backgroundColor: 'rgba(255,68,68,0.1)',
    borderWidth: 1, borderColor: '#FF4444',
    borderRadius: 6, padding: 14,
    alignItems: 'center',
  },
  deleteBtnText: { color: '#FF4444', fontSize: 15, fontWeight: '600' },
  deleteWarning: { color: 'rgba(255,68,68,0.5)', fontSize: 12, textAlign: 'center' },
});
