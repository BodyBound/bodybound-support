import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  Share,
  Clipboard,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';
import { Feather } from '@expo/vector-icons';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface ReferralDashboardProps {
  onClose: () => void;
}

interface ReferralData {
  referral_code: string;
  referral_link: string;
  verified_referrals: number;
  pending_referrals: number;
  rejected_referrals: number;
  progress_toward_reward: number;
  referrals_needed: number;
  free_months_earned: number;
  free_months_available: number;
  earned_free_months?: number;
  is_referral_premium_active?: boolean;
  referral_premium_until?: string | null;
  blocked_by_paid_sub?: boolean;
  referrals: Array<{
    status: string;
    created_at: string;
  }>;
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  clicked: { label: 'Clicked Link', color: '#666' },
  account_created: { label: 'Signed Up', color: '#C9A227' },
  subscribed: { label: 'Subscribed', color: '#2196F3' },
  verification_pending: { label: 'Verifying (14 days)', color: '#FF9800' },
  verified: { label: 'Verified', color: '#4CAF50' },
  rejected: { label: 'Did not qualify', color: '#ef4444' },
};

export function ReferralDashboard({ onClose }: ReferralDashboardProps) {
  const [data, setData] = useState<ReferralData | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const token = await SecureStore.getItemAsync('session_token');
      if (!token) return;
      const resp = await fetch(`${API_URL}/api/referral/dashboard`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) {
        setData(await resp.json());
      }
    } catch (_) {} finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleCopyLink = () => {
    if (!data) return;
    Clipboard.setString(data.referral_link);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleShare = async () => {
    if (!data) return;
    try {
      await Share.share({
        message: `Stop wasting hours hand-drawing realism stencils. I use BODY BOUND and it's a game changer. Try it free: ${data.referral_link}`,
      });
    } catch (_) {}
  };

  const handleSendReminder = async () => {
    if (!data) return;
    try {
      await Share.share({
        message: `Hey — just checking in! Keep using BODY BOUND for a full 14 days and I'll earn a free month. Link if you need it again: ${data.referral_link}`,
      });
    } catch (_) {}
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator color="#C9A227" size="large" style={{ marginTop: 100 }} />
      </SafeAreaView>
    );
  }

  if (!data) {
    return (
      <SafeAreaView style={styles.container}>
        <Text style={styles.errorText}>Could not load referral data.</Text>
        <TouchableOpacity onPress={onClose} style={styles.closeBtn}>
          <Feather name="x" size={24} color="#fff" />
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  const progress = data.progress_toward_reward;
  const needed = data.referrals_needed;
  const progressPercent = (progress / needed) * 100;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={onClose} style={styles.closeBtn} data-testid="referral-close-btn">
            <Feather name="arrow-left" size={24} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.title}>Refer & Earn</Text>
          <View style={{ width: 40 }} />
        </View>

        {/* Hero */}
        <View style={styles.heroCard}>
          <Text style={styles.heroTitle}>Earn Free Months</Text>
          <Text style={styles.heroSubtitle}>
            Invite 2 artists who become verified paid subscribers and get 1 free month of BODY BOUND.
          </Text>
        </View>

        {/* Progress */}
        <View style={styles.progressCard}>
          <Text style={styles.progressLabel}>Progress to next free month</Text>
          <View style={styles.progressBarBg}>
            <View style={[styles.progressBarFill, { width: `${progressPercent}%` }]} />
          </View>
          <Text style={styles.progressText}>
            {progress} of {needed} verified referrals
          </Text>
          {data.is_referral_premium_active && data.referral_premium_until && (
            <View style={styles.activeBadge} data-testid="referral-active-banner">
              <Feather name="zap" size={16} color="#000" />
              <Text style={styles.activeBadgeText}>
                1 free month active until {new Date(data.referral_premium_until).toLocaleDateString()}
              </Text>
            </View>
          )}
          {data.free_months_available > 0 && !data.is_referral_premium_active && !data.blocked_by_paid_sub && (
            <View style={styles.rewardBadge} data-testid="referral-months-available">
              <Feather name="gift" size={16} color="#000" />
              <Text style={styles.rewardBadgeText}>
                {data.free_months_available} free month{data.free_months_available > 1 ? 's' : ''} available!
              </Text>
            </View>
          )}
          {data.is_referral_premium_active && data.free_months_available > 0 && (
            <Text style={styles.queuedText} data-testid="referral-queued-text">
              Your next earned month will activate automatically when this one ends.
            </Text>
          )}
          {data.blocked_by_paid_sub && data.free_months_available > 0 && (
            <Text style={styles.queuedText} data-testid="referral-banked-text">
              {data.free_months_available} free month{data.free_months_available > 1 ? 's' : ''} banked — will activate when your paid subscription ends.
            </Text>
          )}
          {data.free_months_available === 0 && !data.is_referral_premium_active && (
            <Text style={[styles.progressText, { color: '#666', fontSize: 13, marginTop: 8, fontWeight: '400' }]}>
              Keep inviting to earn more free months.
            </Text>
          )}
        </View>

        {/* Stats */}
        <View style={styles.statsRow}>
          <View style={styles.statBox}>
            <Text style={styles.statNum}>{data.verified_referrals}</Text>
            <Text style={styles.statLabel}>Verified</Text>
          </View>
          <View style={styles.statBox}>
            <Text style={styles.statNum}>{data.pending_referrals}</Text>
            <Text style={styles.statLabel}>Pending</Text>
          </View>
          <View style={styles.statBox}>
            <Text style={styles.statNum}>{data.free_months_earned}</Text>
            <Text style={styles.statLabel}>Months Earned</Text>
          </View>
        </View>

        {/* Send Reminder button (only if there are pending referrals) */}
        {data.pending_referrals > 0 && (
          <TouchableOpacity
            onPress={handleSendReminder}
            style={styles.reminderBtn}
            data-testid="send-reminder-btn"
          >
            <Feather name="bell" size={16} color="#C9A227" />
            <Text style={styles.reminderBtnText}>
              Nudge pending referrals
            </Text>
          </TouchableOpacity>
        )}

        {/* Share Section */}
        <View style={styles.shareCard}>
          <Text style={styles.shareLabel}>Your Referral Link</Text>
          <View style={styles.linkRow}>
            <Text style={styles.linkText} numberOfLines={1}>{data.referral_link}</Text>
            <TouchableOpacity onPress={handleCopyLink} style={styles.copyBtn} data-testid="copy-referral-link">
              <Feather name={copied ? 'check' : 'copy'} size={18} color={copied ? '#4CAF50' : '#C9A227'} />
            </TouchableOpacity>
          </View>
          <TouchableOpacity onPress={handleShare} style={styles.shareBtn} data-testid="share-referral-btn">
            <Feather name="share" size={18} color="#000" />
            <Text style={styles.shareBtnText}>Invite Artists</Text>
          </TouchableOpacity>
          <Text style={styles.codeText}>Or share code: {data.referral_code}</Text>
        </View>

        {/* Referral History */}
        {data.referrals.length > 0 && (
          <View style={styles.historyCard}>
            <Text style={styles.historyTitle}>Referral Activity</Text>
            {data.referrals.map((ref, i) => {
              const info = STATUS_LABELS[ref.status] || { label: ref.status, color: '#666' };
              return (
                <View key={i} style={styles.historyRow}>
                  <View style={[styles.statusDot, { backgroundColor: info.color }]} />
                  <Text style={styles.historyLabel}>{info.label}</Text>
                  <Text style={styles.historyDate}>
                    {ref.created_at ? new Date(ref.created_at).toLocaleDateString() : ''}
                  </Text>
                </View>
              );
            })}
          </View>
        )}

        {/* How It Works */}
        <View style={styles.howCard}>
          <Text style={styles.howTitle}>How It Works</Text>
          <View style={styles.howStep}>
            <View style={styles.stepNum}><Text style={styles.stepNumText}>1</Text></View>
            <Text style={styles.stepText}>Share your link with fellow tattoo artists</Text>
          </View>
          <View style={styles.howStep}>
            <View style={styles.stepNum}><Text style={styles.stepNumText}>2</Text></View>
            <Text style={styles.stepText}>They sign up and subscribe to a paid plan</Text>
          </View>
          <View style={styles.howStep}>
            <View style={styles.stepNum}><Text style={styles.stepNumText}>3</Text></View>
            <Text style={styles.stepText}>After 14 days active, the referral is verified</Text>
          </View>
          <View style={styles.howStep}>
            <View style={styles.stepNum}><Text style={styles.stepNumText}>4</Text></View>
            <Text style={styles.stepText}>Every 2 verified referrals = 1 free month</Text>
          </View>
        </View>

        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0f' },
  scroll: { padding: 20 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 },
  closeBtn: { width: 40, height: 40, justifyContent: 'center', alignItems: 'center' },
  title: { color: '#C9A227', fontSize: 20, fontWeight: '700', letterSpacing: 1 },
  errorText: { color: '#999', textAlign: 'center', marginTop: 100, fontSize: 16 },
  heroCard: { backgroundColor: '#12121f', borderRadius: 16, padding: 24, marginBottom: 16, borderLeftWidth: 3, borderLeftColor: '#C9A227' },
  heroTitle: { color: '#fff', fontSize: 22, fontWeight: '700', marginBottom: 8 },
  heroSubtitle: { color: '#999', fontSize: 14, lineHeight: 20 },
  progressCard: { backgroundColor: '#12121f', borderRadius: 16, padding: 20, marginBottom: 16 },
  progressLabel: { color: '#999', fontSize: 13, marginBottom: 10, textTransform: 'uppercase', letterSpacing: 1 },
  progressBarBg: { height: 8, backgroundColor: '#1a1a2e', borderRadius: 4, overflow: 'hidden', marginBottom: 8 },
  progressBarFill: { height: '100%', backgroundColor: '#C9A227', borderRadius: 4 },
  progressText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  rewardBadge: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#C9A227', borderRadius: 20, paddingHorizontal: 14, paddingVertical: 8, marginTop: 12, alignSelf: 'flex-start', gap: 6 },
  rewardBadgeText: { color: '#000', fontWeight: '700', fontSize: 13 },
  activeBadge: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#4CAF50', borderRadius: 20, paddingHorizontal: 14, paddingVertical: 8, marginTop: 12, alignSelf: 'flex-start', gap: 6 },
  activeBadgeText: { color: '#000', fontWeight: '700', fontSize: 13 },
  queuedText: { color: '#C9A227', fontSize: 12, marginTop: 10, fontStyle: 'italic', lineHeight: 17 },
  reminderBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#12121f', borderWidth: 1, borderColor: '#C9A227', borderRadius: 10, paddingVertical: 12, marginBottom: 16, gap: 8 },
  reminderBtnText: { color: '#C9A227', fontSize: 14, fontWeight: '600' },
  statsRow: { flexDirection: 'row', gap: 10, marginBottom: 16 },
  statBox: { flex: 1, backgroundColor: '#12121f', borderRadius: 12, padding: 16, alignItems: 'center' },
  statNum: { color: '#C9A227', fontSize: 24, fontWeight: '700' },
  statLabel: { color: '#666', fontSize: 11, marginTop: 4, textTransform: 'uppercase' },
  shareCard: { backgroundColor: '#12121f', borderRadius: 16, padding: 20, marginBottom: 16 },
  shareLabel: { color: '#999', fontSize: 13, marginBottom: 10, textTransform: 'uppercase', letterSpacing: 1 },
  linkRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#1a1a2e', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, marginBottom: 14, gap: 8 },
  linkText: { flex: 1, color: '#C9A227', fontSize: 13 },
  copyBtn: { padding: 4 },
  shareBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', backgroundColor: '#C9A227', borderRadius: 10, paddingVertical: 14, gap: 8, marginBottom: 10 },
  shareBtnText: { color: '#000', fontWeight: '700', fontSize: 16 },
  codeText: { color: '#666', fontSize: 12, textAlign: 'center' },
  historyCard: { backgroundColor: '#12121f', borderRadius: 16, padding: 20, marginBottom: 16 },
  historyTitle: { color: '#fff', fontSize: 16, fontWeight: '600', marginBottom: 14 },
  historyRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#1a1a2e', gap: 10 },
  statusDot: { width: 8, height: 8, borderRadius: 4 },
  historyLabel: { flex: 1, color: '#ccc', fontSize: 14 },
  historyDate: { color: '#666', fontSize: 12 },
  howCard: { backgroundColor: '#12121f', borderRadius: 16, padding: 20, marginBottom: 16 },
  howTitle: { color: '#fff', fontSize: 16, fontWeight: '600', marginBottom: 14 },
  howStep: { flexDirection: 'row', alignItems: 'center', marginBottom: 12, gap: 12 },
  stepNum: { width: 28, height: 28, borderRadius: 14, backgroundColor: '#C9A227', justifyContent: 'center', alignItems: 'center' },
  stepNumText: { color: '#000', fontWeight: '700', fontSize: 13 },
  stepText: { flex: 1, color: '#999', fontSize: 14, lineHeight: 20 },
});
