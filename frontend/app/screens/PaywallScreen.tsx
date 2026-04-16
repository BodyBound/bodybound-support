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
  Image,
  Linking,
  TextInput,
} from 'react-native';

const APPLE_EULA_URL = 'https://www.apple.com/legal/internet-services/itunes/dev/stdeula/';
const PRIVACY_POLICY_URL = 'https://bodybound.github.io/bodybound-support/privacy';
import { SafeAreaView } from 'react-native-safe-area-context';
import Purchases, { PurchasesPackage, CustomerInfo, PurchasesStoreProduct } from 'react-native-purchases';
import * as SecureStore from 'expo-secure-store';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const TIER_INFO = {
  walk_in: {
    label: 'The Walk-In',
    price: '$14.99/mo',
    credits: 125,
    description: 'Perfect for individual tattoo artists',
    features: ['125 credits/month', 'All stencil styles', 'Edit mode', 'HD export'],
    color: '#C9A227',
  },
  booked_out: {
    label: 'Booked Out',
    price: '$29.99/mo',
    credits: 500,
    description: 'For active studios and professionals',
    features: ['500 credits/month', 'All The Walk-In features', 'Priority processing', 'Batch export'],
    color: '#E8D5A3',
    popular: true,
  },
  the_shop: {
    label: 'The Shop',
    price: '$99.00/mo',
    credits: 1500,
    description: 'Shared credits for teams up to 5',
    features: ['1,500 shared credits', 'Up to 5 team members', 'Admin dashboard', 'All Booked Out features'],
    color: '#FFFFFF',
  },
};

interface PaywallScreenProps {
  onPurchaseSuccess: () => void;
  onDismiss?: () => void;
  onSignOut?: () => void;
  required?: boolean;
  revenueCatReady?: boolean;
}

export function PaywallScreen({ onPurchaseSuccess, onDismiss, onSignOut, required = false, revenueCatReady = true }: PaywallScreenProps) {
  const [offerings, setOfferings] = useState<PurchasesPackage[]>([]);
  const [directProducts, setDirectProducts] = useState<PurchasesStoreProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [selectedPackage, setSelectedPackage] = useState<PurchasesPackage | null>(null);
  const [selectedProduct, setSelectedProduct] = useState<PurchasesStoreProduct | null>(null);
  const [referralCode, setReferralCode] = useState('');
  const [referralApplied, setReferralApplied] = useState(false);
  const [applyingPromo, setApplyingPromo] = useState(false);
  const [offeringsError, setOfferingsError] = useState(false);

  // Known App Store product IDs
  const PRODUCT_IDS = ['bodybound_1499_1m_3d', 'bodybound_2999_1m_3d', 'bodybound_9999_1m_3d'];

  useEffect(() => {
    if (revenueCatReady) {
      loadOfferings();
    }
  }, [revenueCatReady]);

  const loadOfferings = async () => {
    if (Platform.OS === 'web') {
      setLoading(false);
      return;
    }
    setOfferingsError(false);

    // Step 1: Try RevenueCat offerings (preferred)
    try {
      const allOfferings = await Purchases.getOfferings();
      const packages: PurchasesPackage[] = [];

      const walkInOffering = allOfferings.all['bodybound_1499_1m_3d'];
      const bookedOutOffering = allOfferings.all['bodybound_2999_1m_3d'];
      const theShopOffering = allOfferings.all['bodybound_9999_1m_3d'];

      if (walkInOffering?.monthly) packages.push(walkInOffering.monthly);
      if (bookedOutOffering?.monthly) packages.push(bookedOutOffering.monthly);
      if (theShopOffering?.monthly) packages.push(theShopOffering.monthly);

      if (packages.length > 0) {
        setOfferings(packages);
        setSelectedPackage(packages[1] || packages[0]);
        console.log(`[Paywall] Loaded ${packages.length} offerings from RevenueCat`);
        setLoading(false);
        return;
      }
      console.log('[Paywall] No offerings from RevenueCat, trying direct product fetch...');
    } catch (err) {
      console.log('[Paywall] Offerings failed, trying direct product fetch...', err);
    }

    // Step 2: Fallback — fetch products directly from Apple via RevenueCat SDK
    try {
      const products = await Purchases.getProducts(PRODUCT_IDS);
      if (products.length > 0) {
        setDirectProducts(products);
        setSelectedProduct(products[1] || products[0]);
        console.log(`[Paywall] Loaded ${products.length} products directly from Apple`);
        setLoading(false);
        return;
      }
      console.log('[Paywall] No products returned from direct fetch either');
    } catch (err2) {
      console.log('[Paywall] Direct product fetch also failed:', err2);
    }

    setOfferingsError(true);
    setLoading(false);
  };

  // Check if we have products loaded (either via offerings or direct)
  const hasProducts = offerings.length > 0 || directProducts.length > 0;
  const usingDirectProducts = offerings.length === 0 && directProducts.length > 0;

  const handlePurchase = async () => {
    if (Platform.OS === 'web') {
      Alert.alert('iOS Only', 'Subscriptions are available in the iOS App Store.');
      return;
    }

    setPurchasing(true);
    try {
      let customerInfo: CustomerInfo;

      if (selectedPackage && !usingDirectProducts) {
        // Purchase via RevenueCat package (preferred)
        const result = await Purchases.purchasePackage(selectedPackage);
        customerInfo = result.customerInfo;
      } else if (selectedProduct) {
        // Fallback: purchase product directly from Apple
        const result = await Purchases.purchaseStoreProduct(selectedProduct);
        customerInfo = result.customerInfo;
      } else {
        Alert.alert('No Plan Selected', 'Please select a subscription plan to continue.');
        setPurchasing(false);
        return;
      }

      if (typeof customerInfo.entitlements.active['BODY BOUND Stencil Generator Pro'] !== 'undefined') {
        if (referralCode.trim()) {
          try {
            await SecureStore.setItemAsync('pending_referral_code', referralCode.trim().toUpperCase());
          } catch (_) {}
        }
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
      if (typeof customerInfo.entitlements.active['BODY BOUND Stencil Generator Pro'] !== 'undefined') {
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
  const ctaDisabled = purchasing || (!isWeb && !selectedPackage && !selectedProduct);

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
        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.scroll}>
          {/* Header */}
          {onDismiss && !required && (
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
              {Object.entries(TIER_INFO).map(([key, tier], index) => {
                const pkg = offerings[index];
                const prod = directProducts[index];
                const isSelected = usingDirectProducts
                  ? selectedProduct?.identifier === prod?.identifier
                  : selectedPackage?.identifier === pkg?.identifier;

                return (
                  <TouchableOpacity
                    key={key}
                    testID={`plan-${key}-btn`}
                    style={[styles.planCard, isSelected && styles.planCardSelected]}
                    onPress={() => {
                      if (usingDirectProducts && prod) {
                        setSelectedProduct(prod);
                      } else if (pkg) {
                        setSelectedPackage(pkg);
                      }
                    }}
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
                        {pkg ? pkg.product.priceString : prod ? prod.priceString : tier.price}
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

          {/* Sandbox / Offerings error message */}
          {offeringsError && !isWeb && (
            <View style={{ backgroundColor: 'rgba(239,68,68,0.1)', borderRadius: 12, padding: 16, marginBottom: 16, borderWidth: 1, borderColor: 'rgba(239,68,68,0.2)' }}>
              <Text style={{ color: '#ef4444', fontSize: 14, fontWeight: '700', marginBottom: 6 }}>Unable to load subscription plans</Text>
              <Text style={{ color: '#999', fontSize: 13, lineHeight: 18, marginBottom: 12 }}>
                This can happen due to a temporary connection issue. Please try again.
              </Text>
              <TouchableOpacity
                style={{ backgroundColor: '#ef4444', borderRadius: 8, paddingVertical: 10, alignItems: 'center' }}
                onPress={() => {
                  setOfferingsError(false);
                  setLoading(true);
                  loadOfferings();
                }}
              >
                <Text style={{ color: '#fff', fontWeight: '700', fontSize: 14 }}>Retry Loading Plans</Text>
              </TouchableOpacity>
            </View>
          )}

          {/* Trial Info */}
          <View style={styles.trialInfo}>
            <Text style={styles.trialInfoText}>
              Start your 3-day free trial with full access to all credits.{'\n'}
              Cancel anytime before your trial ends — you won't be charged.
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

          {/* Sign Out — right under Restore so it's visible */}
          {onSignOut && (
            <TouchableOpacity
              testID="paywall-sign-out-btn"
              style={{ paddingVertical: 12, alignItems: 'center', marginBottom: 16 }}
              onPress={() => {
                Alert.alert(
                  'Sign Out',
                  'Sign out and switch to a different account?',
                  [
                    { text: 'Cancel', style: 'cancel' },
                    { text: 'Sign Out', style: 'destructive', onPress: onSignOut },
                  ]
                );
              }}
            >
              <Text style={{ color: '#999', fontSize: 14 }}>Wrong account? Sign out</Text>
            </TouchableOpacity>
          )}

          {/* Referral / Promo Code */}
          <View style={styles.referralSection}>
            <Text style={styles.referralLabel}>Have a referral or promo code?</Text>
            <View style={styles.referralInputRow}>
              <TextInput
                testID="referral-code-input"
                style={styles.referralInput}
                placeholder="Enter code"
                placeholderTextColor="rgba(255,255,255,0.25)"
                value={referralCode}
                onChangeText={setReferralCode}
                autoCapitalize="characters"
                maxLength={12}
                editable={!referralApplied}
              />
              {referralCode.trim().length > 0 && !referralApplied && !referralCode.trim().startsWith('BB-') && (
                <TouchableOpacity
                  testID="apply-promo-btn"
                  style={styles.applyPromoBtn}
                  onPress={async () => {
                    setApplyingPromo(true);
                    try {
                      const token = await SecureStore.getItemAsync('session_token');
                      const res = await fetch(`${API_URL}/api/promo/redeem`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                        body: JSON.stringify({ code: referralCode.trim() }),
                      });
                      const data = await res.json();
                      if (res.ok) {
                        Alert.alert('Promo Applied!', data.message || 'Your free credits have been activated.');
                        setReferralApplied(true);
                        onPurchaseSuccess();
                      } else {
                        Alert.alert('Invalid Code', data.detail || 'This promo code is not valid.');
                      }
                    } catch (err) {
                      Alert.alert('Error', 'Could not apply promo code. Please try again.');
                    } finally {
                      setApplyingPromo(false);
                    }
                  }}
                  disabled={applyingPromo}
                >
                  {applyingPromo ? (
                    <ActivityIndicator color="#000" size="small" />
                  ) : (
                    <Text style={styles.applyPromoBtnText}>Apply</Text>
                  )}
                </TouchableOpacity>
              )}
              {referralCode.trim().length > 0 && !referralApplied && referralCode.trim().startsWith('BB-') && (
                <Text style={styles.referralHint}>Applied after purchase</Text>
              )}
              {referralApplied && (
                <Text style={[styles.referralHint, { color: '#4CAF50' }]}>Applied</Text>
              )}
            </View>
            <Text style={styles.referralSubtext}>
              Referral codes (BB-) apply after purchase. Promo codes activate instantly.
            </Text>
          </View>

          {/* Legal */}
          <Text style={styles.legal}>
            Payment charged to Apple ID. Subscription auto-renews monthly.{'\n'}
            Cancel anytime in Settings &gt; Apple ID &gt; Subscriptions.
          </Text>
          <View style={styles.legalLinks}>
            <TouchableOpacity onPress={() => Linking.openURL(APPLE_EULA_URL)}>
              <Text style={styles.legalLink}>Terms of Service</Text>
            </TouchableOpacity>
            <Text style={styles.legalSeparator}> • </Text>
            <TouchableOpacity onPress={() => Linking.openURL(PRIVACY_POLICY_URL)}>
              <Text style={styles.legalLink}>Privacy Policy</Text>
            </TouchableOpacity>
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
    backgroundColor: 'rgba(0,0,0,0.65)',
  },
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
  subscribeBtnDisabled: { opacity: 0.35, backgroundColor: '#666' },
  subscribeBtnText: { color: '#000', fontSize: 17, fontWeight: '800' },
  subscribeBtnSubtext: { color: 'rgba(0,0,0,0.6)', fontSize: 12 },
  restoreBtn: { alignItems: 'center', paddingVertical: 12, marginBottom: 16 },
  restoreBtnText: { color: '#666', fontSize: 14 },
  referralSection: {
    marginBottom: 16,
    paddingHorizontal: 4,
  },
  referralLabel: {
    color: 'rgba(255,255,255,0.5)',
    fontSize: 13,
    marginBottom: 8,
  },
  referralInputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  referralInput: {
    flex: 1,
    backgroundColor: '#141414',
    borderWidth: 1,
    borderColor: '#2A2A2A',
    borderRadius: 6,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '600',
    letterSpacing: 1,
  },
  referralHint: {
    color: 'rgba(255,255,255,0.35)',
    fontSize: 12,
  },
  applyPromoBtn: {
    backgroundColor: '#C9A227',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 6,
  },
  applyPromoBtnText: {
    color: '#000',
    fontWeight: '700',
    fontSize: 14,
  },
  referralSubtext: {
    color: 'rgba(255,255,255,0.3)',
    fontSize: 11,
    marginTop: 6,
  },
  legal: {
    color: 'rgba(255,255,255,0.25)',
    fontSize: 11, textAlign: 'center', lineHeight: 17,
    marginBottom: 6,
  },
  legalLinks: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  legalLink: {
    color: 'rgba(255,255,255,0.45)',
    fontSize: 11,
    textDecorationLine: 'underline',
  },
  legalSeparator: {
    color: 'rgba(255,255,255,0.25)',
    fontSize: 11,
  },
});
