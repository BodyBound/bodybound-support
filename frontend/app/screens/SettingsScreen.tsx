import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  Alert,
  ActivityIndicator,
  Image,
  Share,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Purchases from 'react-native-purchases';
import * as SecureStore from 'expo-secure-store';
import Constants from 'expo-constants';
import { performQaLocalReset, createTapCounter } from '../utils/qaReset';
import { User, UserCredits } from '../types';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const TIER_LABELS: Record<string, string> = {
  trial: 'Free Trial',
  trial_expired: 'Trial Expired',
  'walk-in': 'The Walk-In',
  'booked-out': 'Booked Out',
  'the-shop': 'The Shop',
  'the-shop-member': 'The Shop (Team)',
};

interface SettingsScreenProps {
  user: User | null;
  credits: UserCredits | null;
  onSignOut: () => void;
  onClose: () => void;
  onManageSubscription: () => void;
  onManageTeam?: () => void;
  onOpenReferralDashboard?: () => void;
}

export function SettingsScreen({
  user,
  credits,
  onSignOut,
  onClose,
  onManageSubscription,
  onManageTeam,
  onOpenReferralDashboard,
}: SettingsScreenProps) {
  const [deletingAccount, setDeletingAccount] = useState(false);
  const [restoringPurchases, setRestoringPurchases] = useState(false);
  const [referralCode, setReferralCode] = useState<string | null>(null);
  const [referralLink, setReferralLink] = useState<string | null>(null);
  const [loadingReferral, setLoadingReferral] = useState(false);

  // --- QA-ONLY hidden reset gesture ---
  // See /app/frontend/app/utils/qaReset.ts for the rationale. The same
  // gesture is wired into PaywallScreen so QA can reach the reset even when
  // they're trapped on "You're subscribed" and can't reach Settings.
  const [qaResetting, setQaResetting] = useState(false);
  const qaTapperRef = useRef(
    createTapCounter({
      requiredTaps: 7,
      windowMs: 3000,
      onTrigger: () => {
        Alert.alert(
          'QA Reset',
          'This wipes the locally stored session token AND the RevenueCat identity on this device.\n\nThe app will return to its fresh-install welcome screen. Use this only for subscription QA.',
          [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Reset Local State', style: 'destructive', onPress: runQaReset },
          ],
        );
      },
    }),
  );

  const runQaReset = async () => {
    setQaResetting(true);
    try {
      await performQaLocalReset();
      Alert.alert(
        'Local state cleared',
        'You are now anonymous. Force-close the app and relaunch to complete the reset.',
        [{ text: 'OK', onPress: onSignOut }],
      );
    } catch (err: any) {
      Alert.alert('Reset failed', err?.message || 'Something went wrong. Try again.');
    } finally {
      setQaResetting(false);
    }
  };
  
  // Check if user has The Shop subscription (admin or member)
  const isShopTier = credits?.tier === 'the-shop' || credits?.tier === 'the-shop-member';
  const activeTiers = ['walk-in', 'booked-out', 'the-shop', 'the-shop-member'];
  const hasActiveSubscription = credits?.tier ? activeTiers.includes(credits.tier) : false;

  useEffect(() => {
    if (hasActiveSubscription) {
      fetchReferralCode();
    }
  }, [hasActiveSubscription]);

  const fetchReferralCode = async () => {
    setLoadingReferral(true);
    try {
      const token = await SecureStore.getItemAsync('session_token');
      if (!token) return;
      const resp = await fetch(`${API_URL}/api/referral/code`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (resp.ok) {
        const data = await resp.json();
        setReferralCode(data.referral_code);
        setReferralLink(data.referral_link);
      }
    } catch (_) {} finally {
      setLoadingReferral(false);
    }
  };

  const handleShareReferral = async () => {
    if (!referralLink) return;
    try {
      await Share.share({
        message: `Stop wasting hours hand-drawing realism stencils. I use BODY BOUND and it's a game changer. Try it free: ${referralLink}`,
      });
    } catch (_) {}
  };

  const handleRestorePurchases = async () => {
    setRestoringPurchases(true);
    try {
      const customerInfo = await Purchases.restorePurchases();
      if (typeof customerInfo.entitlements.active['BODY BOUND Stencil Generator Pro'] !== 'undefined') {
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

  // QA-only: nuke every piece of locally persisted auth/identity state so
  // the next app launch behaves exactly like a fresh install on a virgin
  // device — without requiring the user to Erase All Content.
  const handleQaResetTap = () => {
    if (qaResetting) return;
    qaTapCountRef.current += 1;
    // Reset the counter if taps slow down (must hit 7 within ~3 s)
    if (qaTapTimerRef.current) clearTimeout(qaTapTimerRef.current);
    qaTapTimerRef.current = setTimeout(() => {
      qaTapCountRef.current = 0;
    }, 3000);
    if (qaTapCountRef.current < 7) return;

    // Fired on the 7th tap. Reset counter so repeating the gesture works.
    qaTapCountRef.current = 0;
    if (qaTapTimerRef.current) clearTimeout(qaTapTimerRef.current);

    Alert.alert(
      'QA Reset',
      'This wipes the locally stored session token AND the RevenueCat identity on this device.\n\nThe app will return to its fresh-install welcome screen. Use this only for subscription QA.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset Local State',
          style: 'destructive',
          onPress: performQaReset,
        },
      ],
    );
  };

  const performQaReset = async () => {
    setQaResetting(true);
    try {
      // 1. RevenueCat: generates a new anonymous appUserID on-device and
      //    discards any entitlements cached for the previous identity.
      //    Safe on production accounts too — logOut is always reversible
      //    by calling logIn() again with the real user_id.
      if (Platform.OS === 'ios' || Platform.OS === 'android') {
        try {
          await Purchases.logOut();
          console.log('[QAReset] Purchases.logOut() complete');
        } catch (e) {
          // RC throws if the current user is already anonymous — not fatal.
          console.log('[QAReset] Purchases.logOut() threw (expected if anonymous):', e);
        }
      }

      // 2. Delete every SecureStore key we've ever written. These are the
      //    only two; documented here so a future audit can spot drift.
      try { await SecureStore.deleteItemAsync('session_token'); } catch (_) {}
      try { await SecureStore.deleteItemAsync('pending_referral_code'); } catch (_) {}
      console.log('[QAReset] SecureStore keys deleted');

      // 3. Hand control back to index.tsx which will re-evaluate auth on
      //    mount and route the user to WelcomeScreen (same as fresh install).
      Alert.alert(
        'Local state cleared',
        'You are now anonymous. Force-close the app and relaunch to complete the reset.',
        [{ text: 'OK', onPress: onSignOut }],
      );
    } catch (err: any) {
      Alert.alert('Reset failed', err?.message || 'Something went wrong. Try again.');
    } finally {
      setQaResetting(false);
    }
  };

  const appVersion = Constants.expoConfig?.version || '—';
  const buildNumber =
    (Platform.OS === 'ios' && (Constants.expoConfig as any)?.ios?.buildNumber) ||
    (Platform.OS === 'android' && (Constants.expoConfig as any)?.android?.versionCode) ||
    '';
  const versionLabel = buildNumber
    ? `BODY BOUND · v${appVersion} (${buildNumber})`
    : `BODY BOUND · v${appVersion}`;

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

            {/* Manage Team button - only for The Shop subscribers */}
            {isShopTier && onManageTeam && (
              <TouchableOpacity
                testID="manage-team-btn"
                style={[styles.actionBtn, styles.teamBtn]}
                onPress={onManageTeam}
              >
                <Text style={[styles.actionBtnText, { color: '#C9A227' }]}>
                  Manage Studio Team
                </Text>
              </TouchableOpacity>
            )}

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

          {/* Refer & Earn — only for active subscribers */}
          {hasActiveSubscription && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>REFER & EARN</Text>
              <View style={styles.referralCard}>
                {loadingReferral ? (
                  <ActivityIndicator color="#C9A227" size="small" />
                ) : referralCode ? (
                  <>
                    <Text style={styles.referralCodeLabel}>Your referral code</Text>
                    <Text testID="referral-code-display" style={styles.referralCodeText}>{referralCode}</Text>
                    <Text style={styles.referralReward}>
                      Invite 2 artists who become verified subscribers and earn 1 free month
                    </Text>
                    <TouchableOpacity
                      testID="share-referral-btn"
                      style={styles.referralShareBtn}
                      onPress={handleShareReferral}
                    >
                      <Text style={styles.referralShareBtnText}>Invite Artists</Text>
                    </TouchableOpacity>
                    {onOpenReferralDashboard && (
                      <TouchableOpacity
                        testID="open-referral-dashboard-btn"
                        style={[styles.referralShareBtn, { backgroundColor: 'transparent', borderWidth: 1, borderColor: '#C9A227', marginTop: 8 }]}
                        onPress={onOpenReferralDashboard}
                      >
                        <Text style={[styles.referralShareBtnText, { color: '#C9A227' }]}>View Referral Dashboard</Text>
                      </TouchableOpacity>
                    )}
                  </>
                ) : (
                  <Text style={styles.referralCodeLabel}>Unable to load referral code</Text>
                )}
              </View>
            </View>
          )}

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

          {/* Account Management — subtle links */}
          <View style={styles.section}>
            <TouchableOpacity
              testID="manage-subscription-btn"
              style={styles.subtleLink}
              onPress={onManageSubscription}
            >
              <Text style={styles.subtleLinkText}>Change Plan</Text>
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

          {/* Hidden QA reset — 7 taps on the version string */}
          <TouchableOpacity
            testID="qa-reset-version-tap"
            activeOpacity={1}
            onPress={() => { if (!qaResetting) qaTapperRef.current.tap(); }}
            style={styles.qaVersionTapTarget}
            accessible={false}
          >
            {qaResetting ? (
              <ActivityIndicator color="rgba(255,255,255,0.2)" size="small" />
            ) : (
              <Text style={styles.qaVersionText}>{versionLabel}</Text>
            )}
          </TouchableOpacity>
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
  teamBtn: {
    backgroundColor: 'rgba(201,162,39,0.1)',
    borderColor: 'rgba(201,162,39,0.3)',
  },
  deleteBtn: {
    backgroundColor: 'rgba(255,68,68,0.1)',
    borderWidth: 1, borderColor: '#FF4444',
    borderRadius: 6, padding: 14,
    alignItems: 'center',
  },
  deleteBtnText: { color: '#FF4444', fontSize: 15, fontWeight: '600' },
  deleteWarning: { color: 'rgba(255,68,68,0.5)', fontSize: 12, textAlign: 'center' },
  subtleLink: {
    paddingVertical: 8,
    alignItems: 'center',
  },
  subtleLinkText: {
    color: 'rgba(255,255,255,0.3)',
    fontSize: 13,
    textDecorationLine: 'underline',
  },
  referralCard: {
    backgroundColor: '#141414',
    borderWidth: 1,
    borderColor: '#2A2A2A',
    borderRadius: 8,
    padding: 18,
    alignItems: 'center',
    gap: 8,
  },
  referralCodeLabel: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 13,
  },
  referralCodeText: {
    color: '#C9A227',
    fontSize: 24,
    fontWeight: '800',
    letterSpacing: 3,
  },
  referralReward: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 12,
    textAlign: 'center',
    lineHeight: 18,
  },
  referralShareBtn: {
    backgroundColor: '#C9A227',
    paddingHorizontal: 28,
    paddingVertical: 10,
    borderRadius: 20,
    marginTop: 4,
  },
  referralShareBtnText: {
    color: '#000',
    fontWeight: '700',
    fontSize: 14,
  },
  // Hidden QA reset tap target — footer visibly legible so build/version is
  // verifiable at a glance; reset still requires 7 taps in 3 s to trigger.
  qaVersionTapTarget: {
    paddingVertical: 32,
    paddingHorizontal: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  qaVersionText: {
    color: 'rgba(255,255,255,0.55)',
    fontSize: 12,
    letterSpacing: 1,
    fontWeight: '600',
  },
});
