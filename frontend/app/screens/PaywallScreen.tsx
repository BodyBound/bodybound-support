import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  Alert,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Purchases, { PurchasesPackage, CustomerInfo } from 'react-native-purchases';

const TIER_INFO = {
  hobbyist: {
    label: 'Hobbyist',
    price: '$14.99/mo',
    credits: 125,
    description: 'Perfect for individual tattoo artists',
    features: ['125 credits/month', 'All stencil styles', 'Edit mode', 'HD export'],
    color: '#C9A227',
  },
  pro: {
    label: 'Pro',
    price: '$29.99/mo',
    credits: 500,
    description: 'For active studios and professionals',
    features: ['500 credits/month', 'All Hobbyist features', 'Priority processing', 'Batch export'],
    color: '#E8D5A3',
    popular: true,
  },
  studio: {
    label: 'Studio',
    price: '$99.00/mo',
    credits: 1500,
    description: 'Shared credits for teams up to 5',
    features: ['1,500 shared credits', 'Up to 5 team members', 'Admin dashboard', 'All Pro features'],
    color: '#FFFFFF',
  },
};

interface PaywallScreenProps {
  onPurchaseSuccess: () => void;
  onDismiss?: () => void;
}

export function PaywallScreen({ onPurchaseSuccess, onDismiss }: PaywallScreenProps) {
  const [offerings, setOfferings] = useState<PurchasesPackage[]>([]);
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [selectedPackage, setSelectedPackage] = useState<PurchasesPackage | null>(null);

  useEffect(() => {
    loadOfferings();
  }, []);

  const loadOfferings = async () => {
    // RevenueCat SDK is not available on web - skip and use static plans
    if (Platform.OS === 'web') {
      setLoading(false);
      return;
    }
    try {
      const offerings = await Purchases.getOfferings();
      if (offerings.current?.availablePackages.length) {
        setOfferings(offerings.current.availablePackages);
        setSelectedPackage(offerings.current.availablePackages[1] || offerings.current.availablePackages[0]);
      }
    } catch (err) {
      console.error('Failed to load offerings:', err);
    } finally {
      setLoading(false);
    }
  };

  const handlePurchase = async () => {
    if (Platform.OS === 'web') {
      Alert.alert('iOS Only', 'Subscriptions are available in the iOS App Store. Download Body Bound on your iPhone or iPad to subscribe.');
      return;
    }
    if (!selectedPackage) {
      Alert.alert('No Plan Selected', 'Please select a subscription plan to continue.');
      return;
    }
    setPurchasing(true);
    try {
      const { customerInfo } = await Purchases.purchasePackage(selectedPackage);
      if (typeof customerInfo.entitlements.active['premium'] !== 'undefined') {
        Alert.alert('Welcome!', 'Your subscription is now active. Enjoy your credits!');
        onPurchaseSuccess();
      }
    } catch (err: any) {
      if (!err.userCancelled) {
        Alert.alert('Purchase Failed', err.message || 'Please try again.');
      }
    } finally {
      setPurchasing(false);
    }
  };

  const handleRestore = async () => {
    if (Platform.OS === 'web') {
      Alert.alert('iOS Only', 'Restore Purchases is available on the iOS app.');
      return;
    }
    setRestoring(true);
    try {
      const customerInfo: CustomerInfo = await Purchases.restorePurchases();
      if (typeof customerInfo.entitlements.active['premium'] !== 'undefined') {
        Alert.alert('Restored!', 'Your previous purchase has been restored.');
        onPurchaseSuccess();
      } else {
        Alert.alert('No Purchase Found', 'No previous subscription was found for your account.');
      }
    } catch (err: any) {
      Alert.alert('Restore Failed', err.message || 'Please try again.');
    } finally {
      setRestoring(false);
    }
  };

  const isWeb = Platform.OS === 'web';
  const ctaText = isWeb ? 'Subscribe in iOS App Store' : 'Start Free Trial';
  const ctaSubtext = isWeb ? 'Download Body Bound on iPhone or iPad' : '3 days free, then cancel anytime';
  const ctaDisabled = purchasing || (!isWeb && !selectedPackage);

  return (
    <View style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.scroll}>
          {/* Header */}
          {onDismiss && (
            <TouchableOpacity style={styles.closeBtn} onPress={onDismiss} testID="paywall-close-btn">
              <Text style={styles.closeBtnText}>✕</Text>
            </TouchableOpacity>
          )}

          <View style={styles.header}>
            <Text style={styles.headline}>Professional Tattoo Stencils</Text>
            <Text style={styles.subheadline}>
              Unlimited creativity. Precise results.{'\n'}Built for tattooers, by tattooers.
            </Text>
            <View style={styles.trialBadge}>
              <Text style={styles.trialBadgeText}>3-Day FREE Trial</Text>
            </View>
          </View>

          {/* Plans */}
          {loading ? (
            <ActivityIndicator color="#C9A227" size="large" style={{ marginVertical: 40 }} />
          ) : (
            <View style={styles.plans}>
              {Object.entries(TIER_INFO).map(([key, tier]) => {
                const pkg = offerings.find(p =>
                  p.product?.identifier?.toLowerCase().includes(key)
                );
                const isSelected = selectedPackage?.identifier === pkg?.identifier;

                return (
                  <TouchableOpacity
                    key={key}
                    testID={`plan-${key}-btn`}
                    style={[styles.planCard, isSelected && styles.planCardSelected]}
                    onPress={() => pkg && setSelectedPackage(pkg)}
                    activeOpacity={0.85}
                  >
                    {tier.popular && (
                      <View style={styles.popularBadge}>
                        <Text style={styles.popularText}>MOST POPULAR</Text>
                      </View>
                    )}
                    <View style={styles.planHeader}>
                      <Text style={[styles.planName, { color: tier.color }]}>{tier.label}</Text>
                      <Text style={styles.planPrice}>
                        {pkg ? pkg.product.priceString : tier.price}
                      </Text>
                    </View>
                    <Text style={styles.planDescription}>{tier.description}</Text>
                    <View style={styles.planCredits}>
                      <Text style={[styles.creditsNumber, { color: tier.color }]}>{tier.credits}</Text>
                      <Text style={styles.creditsLabel}> credits/month</Text>
                    </View>
                    {tier.features.map((f, i) => (
                      <Text key={i} style={styles.feature}>• {f}</Text>
                    ))}
                  </TouchableOpacity>
                );
              })}
            </View>
          )}

          {/* Trial Info */}
          <View style={styles.trialInfo}>
            <Text style={styles.trialInfoText}>
              All plans include a 3-day free trial with 10 starter credits.{'\n'}
              Cancel anytime before trial ends. Full credits unlock after first payment.
            </Text>
          </View>

          {/* CTA */}
          <TouchableOpacity
            testID="subscribe-btn"
            style={[styles.subscribeBtn, ctaDisabled && styles.subscribeBtnDisabled]}
            onPress={handlePurchase}
            disabled={ctaDisabled}
          >
            {purchasing ? (
              <ActivityIndicator color="#000" />
            ) : (
              <>
                <Text style={styles.subscribeBtnText}>{ctaText}</Text>
                <Text style={styles.subscribeBtnSubtext}>{ctaSubtext}</Text>
              </>
            )}
          </TouchableOpacity>

          {/* Restore */}
          <TouchableOpacity
            testID="restore-purchases-btn"
            style={styles.restoreBtn}
            onPress={handleRestore}
            disabled={restoring}
          >
            {restoring ? (
              <ActivityIndicator color="#666" size="small" />
            ) : (
              <Text style={styles.restoreBtnText}>Restore Purchases</Text>
            )}
          </TouchableOpacity>

          {/* Legal */}
          <Text style={styles.legal}>
            Payment charged to Apple ID. Subscription auto-renews monthly.{'\n'}
            Cancel anytime in Settings &gt; Apple ID &gt; Subscriptions.{'\n'}
            Terms of Service  •  Privacy Policy
          </Text>
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0A0A0A' },
  safeArea: { flex: 1 },
  scroll: { paddingHorizontal: 20, paddingBottom: 40 },
  closeBtn: {
    alignSelf: 'flex-end',
    padding: 12,
    marginTop: 8,
  },
  closeBtnText: { color: '#666', fontSize: 18 },
  header: { alignItems: 'center', paddingVertical: 24, gap: 12 },
  headline: {
    fontSize: 26, fontWeight: '800', color: '#FFFFFF',
    textAlign: 'center', letterSpacing: 0.5,
  },
  subheadline: {
    fontSize: 15, color: 'rgba(255,255,255,0.6)',
    textAlign: 'center', lineHeight: 22,
  },
  trialBadge: {
    backgroundColor: '#C9A227',
    paddingHorizontal: 18, paddingVertical: 6,
    borderRadius: 20,
  },
  trialBadgeText: { color: '#000', fontWeight: '700', fontSize: 13 },
  plans: { gap: 14, marginBottom: 20 },
  planCard: {
    backgroundColor: '#141414',
    borderWidth: 1, borderColor: '#2A2A2A',
    borderRadius: 8, padding: 18,
    gap: 6,
  },
  planCardSelected: {
    borderColor: '#C9A227',
    backgroundColor: '#1A1500',
  },
  popularBadge: {
    backgroundColor: '#C9A227',
    alignSelf: 'flex-start',
    paddingHorizontal: 10, paddingVertical: 3,
    borderRadius: 4, marginBottom: 4,
  },
  popularText: { color: '#000', fontSize: 10, fontWeight: '700' },
  planHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  planName: { fontSize: 18, fontWeight: '700' },
  planPrice: { fontSize: 16, fontWeight: '600', color: '#FFFFFF' },
  planDescription: { color: 'rgba(255,255,255,0.5)', fontSize: 13 },
  planCredits: { flexDirection: 'row', alignItems: 'baseline', marginTop: 4 },
  creditsNumber: { fontSize: 24, fontWeight: '800' },
  creditsLabel: { color: 'rgba(255,255,255,0.5)', fontSize: 14 },
  feature: { color: 'rgba(255,255,255,0.7)', fontSize: 13 },
  trialInfo: {
    backgroundColor: '#141414',
    borderRadius: 8, padding: 16,
    marginBottom: 20,
  },
  trialInfoText: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 13, textAlign: 'center', lineHeight: 20,
  },
  subscribeBtn: {
    backgroundColor: '#C9A227',
    borderRadius: 6, paddingVertical: 18,
    alignItems: 'center', gap: 4,
    marginBottom: 16,
  },
  subscribeBtnDisabled: { opacity: 0.5 },
  subscribeBtnText: { color: '#000', fontSize: 17, fontWeight: '800' },
  subscribeBtnSubtext: { color: 'rgba(0,0,0,0.6)', fontSize: 12 },
  restoreBtn: { alignItems: 'center', paddingVertical: 12, marginBottom: 16 },
  restoreBtnText: { color: '#666', fontSize: 14 },
  legal: {
    color: 'rgba(255,255,255,0.25)',
    fontSize: 11, textAlign: 'center', lineHeight: 17,
  },
});
