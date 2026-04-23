import React, { useState, useEffect, useRef } from 'react';
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
import Purchases, { PurchasesPackage, CustomerInfo } from 'react-native-purchases';
import * as SecureStore from 'expo-secure-store';
import Constants from 'expo-constants';
import { performQaLocalReset, createTapCounter } from '../utils/qaReset';

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
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [selectedPackage, setSelectedPackage] = useState<PurchasesPackage | null>(null);
  const [referralCode, setReferralCode] = useState('');
  const [referralApplied, setReferralApplied] = useState(false);
  const [applyingPromo, setApplyingPromo] = useState(false);
  const [offeringsError, setOfferingsError] = useState(false);
  const [grantingFallback, setGrantingFallback] = useState(false);
  // Subscriber state: if user already has an active entitlement, we hide the
  // purchase flow and show "You're subscribed" / Manage Subscription.
  const [isActiveSubscriber, setIsActiveSubscriber] = useState(false);
  // Trial eligibility from RC (Apple decides this based on subscription group
  // history). We assume eligible until RC tells us otherwise.
  const [trialEligible, setTrialEligible] = useState(true);

  // Divergence toast — a non-blocking, auto-dismissing banner that appears
  // when RevenueCat reports an ACTIVE product different from the one the
  // user tapped. Typically triggered by:
  //   • Apple sandbox accounts that already have an active subscription
  //   • PRODUCT_CHANGE transitions
  //   • Pre-existing entitlements from other app installs
  // The console.warn at the divergence site is kept for debugging; this
  // toast is purely for user clarity.
  const [divergenceToast, setDivergenceToast] = useState<string | null>(null);
  const divergenceShownRef = useRef(false); // once-per-purchase guard

  // --- QA-ONLY hidden reset gesture ---
  // Mirrors the one in SettingsScreen. Critical here because the paywall
  // auto-shows "You're subscribed" on launch when RC has a cached entitlement
  // for the persisted appUserID, leaving QA with no path to Settings. This
  // 7-tap gesture on the muted version footer is reachable from BOTH the
  // subscribed and unsubscribed states.
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
        [{ text: 'OK', onPress: () => onSignOut && onSignOut() }],
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

  // Map a raw RC product identifier back to the human tier label. If the
  // id is unknown we fall back to the generic message from the spec.
  const tierLabelForProduct = (productId: string): string | null => {
    switch (productId) {
      case 'bodybound_1499_1m_3d': return 'Walk-In';
      case 'bodybound_2999_1m_3d': return 'Booked Out';
      case 'bodybound_9999_1m_3d': return 'The Shop';
      default: return null;
    }
  };

  // Auto-dismiss the divergence toast. 2.8 s per spec (2–3 seconds).
  useEffect(() => {
    if (!divergenceToast) return;
    const t = setTimeout(() => setDivergenceToast(null), 2800);
    return () => clearTimeout(t);
  }, [divergenceToast]);

  // Package identifiers as configured in RevenueCat dashboard
  const PACKAGE_IDS = ['walk_in', 'booked_out', 'the_shop'];
  // The entitlement name configured in RevenueCat dashboard
  const ENTITLEMENT_ID = 'BODY BOUND Stencil Generator Pro';

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
    console.log('[RC:Paywall] Loading offerings...');

    try {
      const allOfferings = await Purchases.getOfferings();
      const offering = allOfferings.current;

      console.log('[RC:Paywall] Current offering:', offering?.identifier || 'NONE');
      console.log('[RC:Paywall] All offering keys:', JSON.stringify(Object.keys(allOfferings.all || {})));

      if (!offering) {
        console.error('[RC:Paywall] No current offering returned');
        setOfferingsError(true);
        setLoading(false);
        return;
      }

      const available = offering.availablePackages || [];
      console.log('[RC:Paywall] availablePackages count:', available.length);
      for (const pkg of available) {
        console.log('[RC:Paywall]   package:', pkg.identifier, '→ product:', pkg.product.identifier, '→ price:', pkg.product.priceString);
      }

      // Map packages by identifier
      const walkIn = available.find(p => p.identifier === 'walk_in');
      const bookedOut = available.find(p => p.identifier === 'booked_out');
      const theShop = available.find(p => p.identifier === 'the_shop');

      console.log('[RC:Paywall] walk_in:', walkIn ? walkIn.product.identifier : 'NOT FOUND');
      console.log('[RC:Paywall] booked_out:', bookedOut ? bookedOut.product.identifier : 'NOT FOUND');
      console.log('[RC:Paywall] the_shop:', theShop ? theShop.product.identifier : 'NOT FOUND');

      const packages = [walkIn, bookedOut, theShop].filter(Boolean) as PurchasesPackage[];

      if (packages.length > 0) {
        setOfferings(packages);
        // Do NOT pre-select — spec requires explicit user selection to enable CTA.
        console.log('[RC:Paywall] SUCCESS — Loaded', packages.length, 'packages');

        // Check subscriber + trial eligibility from RevenueCat
        try {
          const customerInfo = await Purchases.getCustomerInfo();
          const active = !!customerInfo.entitlements.active[ENTITLEMENT_ID];
          setIsActiveSubscriber(active);
          if (!active) {
            const productIds = packages.map(p => p.product.identifier);
            const eligibility = await Purchases.checkTrialOrIntroductoryPriceEligibility(productIds);
            // Status: 0=unknown, 1=ineligible, 2=eligible, 3=no_intro_offer_exists
            const anyEligible = Object.values(eligibility).some((e: any) => e.status === 2);
            setTrialEligible(anyEligible);
          }
        } catch (e) {
          console.warn('[RC:Paywall] Could not check subscription/trial state:', e);
        }
      } else {
        console.error('[RC:Paywall] No matching packages found (expected: walk_in, booked_out, the_shop)');
        setOfferingsError(true);
      }
    } catch (err: any) {
      console.error('[RC:Paywall] getOfferings() FAILED:', err.message);
      setOfferingsError(true);
    }

    setLoading(false);
  };

  const logEntitlements = (customerInfo: CustomerInfo, context: string) => {
    const activeKeys = Object.keys(customerInfo.entitlements.active || {});
    const allKeys = Object.keys(customerInfo.entitlements.all || {});
    console.log(`[RC:${context}] Active entitlement keys:`, JSON.stringify(activeKeys));
    console.log(`[RC:${context}] All entitlement keys:`, JSON.stringify(allKeys));
    console.log(`[RC:${context}] Active subscriptions:`, JSON.stringify(customerInfo.activeSubscriptions));
    console.log(`[RC:${context}] Expected entitlement "${ENTITLEMENT_ID}" present:`, activeKeys.includes(ENTITLEMENT_ID));
  };

  const handlePurchase = async () => {
    if (Platform.OS === 'web') {
      Alert.alert('iOS Only', 'Subscriptions are available in the iOS App Store.');
      return;
    }
    if (!selectedPackage) {
      Alert.alert('No Plan Selected', 'Please select a subscription plan to continue.');
      return;
    }

    setPurchasing(true);
    // Reset once-per-purchase divergence guard so this attempt can surface
    // a toast if Apple/RC returns a mismatched product. Previous attempts'
    // toasts do not carry over.
    divergenceShownRef.current = false;
    setDivergenceToast(null);
    try {
      console.log('[RC:Purchase] Purchasing package:', selectedPackage.identifier, '→ product:', selectedPackage.product.identifier);
      const { customerInfo } = await Purchases.purchasePackage(selectedPackage);

      logEntitlements(customerInfo, 'Purchase');

      if (typeof customerInfo.entitlements.active[ENTITLEMENT_ID] !== 'undefined') {
        if (referralCode.trim()) {
          try {
            await SecureStore.setItemAsync('pending_referral_code', referralCode.trim().toUpperCase());
          } catch (_) {}
        }

        // CRITICAL: Tell our backend exactly what product is ACTIVE on the
        // customer's account after this purchase settles, regardless of how
        // RC's webhook classifies the event (INITIAL_PURCHASE vs TRANSFER vs
        // PRODUCT_CHANGE).
        //
        // Source of truth is `activeEntitlement.productIdentifier`, NOT
        // `selectedPackage.product.identifier`. In sandbox, and whenever an
        // account already has an active subscription from prior testing,
        // Apple's StoreKit can report success while leaving the existing
        // product in place — `customerInfo` will reflect the OLD product,
        // not the one the user just tapped. If we sync with the tapped
        // product here, the RC webhook later overwrites it with the real
        // product, which is exactly the "selected Walk-In, got 500 credits"
        // bug we hit in sandbox on multiple test accounts.
        try {
          const token = await SecureStore.getItemAsync('session_token');
          const activeEntitlement = customerInfo.entitlements.active[ENTITLEMENT_ID];
          const isTrial = activeEntitlement?.periodType === 'TRIAL';
          const activeProductId = activeEntitlement?.productIdentifier || '';
          const tappedProductId = selectedPackage.product.identifier;

          // Only sync if RC gave us a real product id. If it didn't, bail —
          // letting the RC webhook establish the state is safer than guessing
          // from the user's tap.
          if (!activeProductId) {
            console.error('[RC:Purchase] activeEntitlement.productIdentifier was empty; skipping sync and leaving state to the RC webhook. tapped=', tappedProductId);
          } else {
            if (activeProductId !== tappedProductId) {
              // Non-fatal divergence: Apple granted a different plan than the
              // one tapped. This is expected for PRODUCT_CHANGE flows but also
              // happens in sandbox when a prior subscription is still active.
              console.warn('[RC:Purchase] DIVERGENCE — tapped', tappedProductId, 'but Apple reports active product', activeProductId, '. Syncing the ACTIVE product.');
              // Non-blocking user-facing toast. Show ONCE per purchase; don't
              // show on normal matching purchases. Covered by the ref guard.
              if (!divergenceShownRef.current) {
                divergenceShownRef.current = true;
                const tierName = tierLabelForProduct(activeProductId);
                setDivergenceToast(
                  tierName
                    ? `You're already subscribed to ${tierName} — loading your current plan.`
                    : "You're already subscribed to a different plan — loading your current plan.",
                );
              }
            }
            const syncResp = await fetch(`${API_URL}/api/subscription/sync`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
              body: JSON.stringify({
                product_id: activeProductId,
                is_trial: isTrial,
                revenuecat_customer_id: customerInfo.originalAppUserId || '',
              }),
            });
            if (!syncResp.ok) {
              const errTxt = await syncResp.text();
              console.error('[RC:Purchase] Backend sync failed:', syncResp.status, errTxt);
            } else {
              console.log('[RC:Purchase] Backend sync OK for ACTIVE product:', activeProductId, '(tapped was', tappedProductId + ')');
            }
          }
        } catch (syncErr) {
          console.error('[RC:Purchase] Backend sync exception:', syncErr);
        }

        if (divergenceShownRef.current) {
          // Divergence flow: skip the blocking 'Welcome!' alert (confusing
          // when the plan the user ended up with differs from the one they
          // tapped). Keep the paywall mounted just long enough for the
          // non-blocking toast to remain visible, then dismiss.
          setTimeout(() => onPurchaseSuccess(), 2800);
        } else {
          Alert.alert('Welcome!', 'Your subscription is now active. Enjoy your credits!');
          onPurchaseSuccess();
        }
      } else {
        const activeKeys = Object.keys(customerInfo.entitlements.active || {});
        console.error('[RC:Purchase] ENTITLEMENT MISMATCH — expected:', ENTITLEMENT_ID, 'got:', JSON.stringify(activeKeys));
        Alert.alert(
          'Subscription Activated',
          `Your purchase was processed but we're verifying it. Please tap "Restore Purchases" or restart the app.\n\nDebug: entitlements=[${activeKeys.join(', ')}]`,
          [{ text: 'OK' }]
        );
        onPurchaseSuccess();
      }
    } catch (err: any) {
      if (!err.userCancelled) {
        console.error('[RC:Purchase] FAILED:', err.message, err.code);
        Alert.alert('Purchase Failed', err.message || 'Please try again.');
      } else {
        console.log('[RC:Purchase] User cancelled');
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
      console.log('[RC:Restore] Starting restore...');
      const customerInfo: CustomerInfo = await Purchases.restorePurchases();
      logEntitlements(customerInfo, 'Restore');

      if (typeof customerInfo.entitlements.active[ENTITLEMENT_ID] !== 'undefined') {
        // Sync restored entitlement to backend. Find the active product ID
        // from the customerInfo to tell the backend what was restored.
        try {
          const activeEntitlement = customerInfo.entitlements.active[ENTITLEMENT_ID];
          const productId = activeEntitlement?.productIdentifier;
          const isTrial = activeEntitlement?.periodType === 'TRIAL';
          if (productId) {
            const token = await SecureStore.getItemAsync('session_token');
            const syncResp = await fetch(`${API_URL}/api/subscription/sync`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
              body: JSON.stringify({
                product_id: productId,
                is_trial: isTrial,
                revenuecat_customer_id: customerInfo.originalAppUserId || '',
              }),
            });
            if (!syncResp.ok) {
              const errTxt = await syncResp.text();
              console.error('[RC:Restore] Backend sync failed:', syncResp.status, errTxt);
            } else {
              console.log('[RC:Restore] Backend sync OK for product:', productId);
            }
          } else {
            console.warn('[RC:Restore] No productIdentifier in active entitlement — skipping sync');
          }
        } catch (syncErr) {
          console.error('[RC:Restore] Backend sync exception:', syncErr);
        }

        Alert.alert('Restored!', 'Subscription restored.');
        onPurchaseSuccess();
      } else {
        const activeKeys = Object.keys(customerInfo.entitlements.active || {});
        if (activeKeys.length > 0) {
          console.error('[RC:Restore] ENTITLEMENT MISMATCH — has entitlements but not expected one');
          Alert.alert(
            'Subscription Found',
            `We found an active subscription but couldn't match it. Please contact support.\n\nDebug: entitlements=[${activeKeys.join(', ')}]`
          );
        } else {
          Alert.alert('No Subscription', 'No active subscription found.');
        }
      }
    } catch (err: any) {
      console.error('[RC:Restore] FAILED:', err.message);
      Alert.alert('Restore Failed', 'Unable to restore. Try again.');
    } finally {
      setRestoring(false);
    }
  };

  const isWeb = Platform.OS === 'web';
  // Selected tier label (e.g. "Walk-In", "Booked Out", "The Shop")
  // Look up by IDENTIFIER, not by array index — same class of bug as the
  // card selection. TIER_INFO keys (walk_in / booked_out / the_shop) match
  // the RC package identifiers exactly by design.
  const selectedTierLabel = (() => {
    if (!selectedPackage) return '';
    const tier = (TIER_INFO as any)[selectedPackage.identifier];
    // Strip leading "The " to keep CTA tight: "The Walk-In" -> "Walk-In"
    return tier ? tier.label.replace(/^The /, '') : '';
  })();

  const ctaText = (() => {
    if (isWeb) return 'Subscribe in iOS App Store';
    if (purchasing) return 'Processing…';
    if (!selectedPackage) return 'Select a Plan';
    return `Confirm ${selectedTierLabel} Subscription`;
  })();
  const ctaDisabled = purchasing || (!isWeb && !selectedPackage);

  return (
    <View style={styles.container}>
      {/* Background image — same as WelcomeScreen */}
      <Image
        source={require('../../assets/images/splash-background.png')}
        style={styles.backgroundImage}
        resizeMode="cover"
      />
      <View style={styles.overlay} />

      {/* Non-blocking divergence toast — surfaces when Apple/RC returned a
          different active plan than the one the user tapped. Auto-dismisses
          in ~2.8s; shown only once per purchase; suppressed entirely when
          the tapped and active products match. */}
      {divergenceToast && (
        <View style={styles.divergenceToast} pointerEvents="none" testID="paywall-divergence-toast">
          <Text style={styles.divergenceToastText}>{divergenceToast}</Text>
        </View>
      )}

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
              Precision stencil generation. Built for tattooers.
            </Text>
            {trialEligible && !isActiveSubscriber && (
              <View style={styles.trialBadge}>
                <Text style={styles.trialBadgeText}>3-Day Free Trial</Text>
              </View>
            )}
          </View>

          {/* Plans */}
          {loading ? (
            <ActivityIndicator color="#C9A227" size="large" style={{ marginVertical: 40 }} />
          ) : (
            <View style={styles.plans}>
              {Object.entries(TIER_INFO).map(([key, tier]) => {
                // CRITICAL: look up the package by IDENTIFIER, never by array
                // index. Index-based lookup breaks silently whenever RC's
                // offering returns packages in a different order or drops one,
                // causing the Walk-In card to select Booked Out etc.
                const pkg = offerings.find(p => p.identifier === key);
                const isSelected = selectedPackage?.identifier === pkg?.identifier;

                return (
                  <TouchableOpacity
                    key={key}
                    testID={`plan-${key}-btn`}
                    style={[styles.planCard, isSelected && styles.planCardSelected, !pkg && { opacity: 0.4 }]}
                    onPress={() => {
                      if (!pkg) {
                        console.warn('[RC:Paywall] Tapped card for', key, 'but no matching package in offerings');
                        return;
                      }
                      console.log('[RC:Paywall] Selected package:', pkg.identifier, '→ product:', pkg.product.identifier);
                      setSelectedPackage(pkg);
                    }}
                    disabled={!pkg}
                    activeOpacity={0.85}
                  >
                    {tier.popular && (
                      <View style={styles.popularBadge}>
                        <Text style={styles.popularText}>STUDIO STANDARD</Text>
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

          {/* Sandbox / Offerings error message */}
          {offeringsError && !isWeb && (
            <View style={{ backgroundColor: 'rgba(239,68,68,0.1)', borderRadius: 12, padding: 16, marginBottom: 16, borderWidth: 1, borderColor: 'rgba(239,68,68,0.2)' }}>
              <Text style={{ color: '#ef4444', fontSize: 14, fontWeight: '700', marginBottom: 6 }}>Unable to load subscription plans</Text>
              <Text style={{ color: '#999', fontSize: 13, lineHeight: 18, marginBottom: 12 }}>
                We're currently experiencing a temporary issue with subscriptions. Please enjoy some free credits while we fix this.
              </Text>
              <TouchableOpacity
                style={{ backgroundColor: '#ef4444', borderRadius: 8, paddingVertical: 10, alignItems: 'center', marginBottom: 10 }}
                onPress={() => {
                  setOfferingsError(false);
                  setLoading(true);
                  loadOfferings();
                }}
              >
                <Text style={{ color: '#fff', fontWeight: '700', fontSize: 14 }}>Retry Loading Plans</Text>
              </TouchableOpacity>
              <TouchableOpacity
                testID="fallback-credits-btn"
                style={{ backgroundColor: '#C9A227', borderRadius: 8, paddingVertical: 10, alignItems: 'center' }}
                onPress={async () => {
                  setGrantingFallback(true);
                  try {
                    const token = await SecureStore.getItemAsync('session_token');
                    const res = await fetch(`${API_URL}/api/auth/fallback-credits`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                    });
                    const data = await res.json();
                    if (res.ok) {
                      Alert.alert('Free Credits Granted!', `You've received ${data.credits} free credits to try the app. Enjoy!`);
                      onPurchaseSuccess();
                    } else {
                      Alert.alert('Unavailable', data.detail || 'Could not grant free credits.');
                    }
                  } catch (err) {
                    Alert.alert('Error', 'Something went wrong. Please try again.');
                  } finally {
                    setGrantingFallback(false);
                  }
                }}
                disabled={grantingFallback}
              >
                {grantingFallback ? (
                  <ActivityIndicator color="#000" size="small" />
                ) : (
                  <Text style={{ color: '#000', fontWeight: '700', fontSize: 14 }}>Get Free Credits Instead</Text>
                )}
              </TouchableOpacity>
            </View>
          )}

          {/* CTA — single source of purchase action */}
          {isActiveSubscriber ? (
            <>
              <View style={[styles.subscribeBtn, { backgroundColor: 'rgba(76,175,80,0.15)', borderWidth: 1, borderColor: '#4CAF50' }]}>
                <Text style={[styles.subscribeBtnText, { color: '#4CAF50' }]}>You're subscribed</Text>
              </View>
              <TouchableOpacity
                testID="manage-subscription-btn"
                style={[styles.restoreBtn, { borderColor: '#C9A227', borderWidth: 1, borderRadius: 12, paddingVertical: 14, marginBottom: 8 }]}
                onPress={async () => {
                  try {
                    if (Platform.OS === 'ios') {
                      Linking.openURL('https://apps.apple.com/account/subscriptions');
                    } else {
                      Linking.openURL('https://play.google.com/store/account/subscriptions');
                    }
                  } catch (_) {}
                }}
              >
                <Text style={[styles.restoreBtnText, { color: '#C9A227', fontWeight: '700' }]}>Manage Subscription</Text>
              </TouchableOpacity>
            </>
          ) : (
            <TouchableOpacity
              testID="subscribe-btn"
              style={[styles.subscribeBtn, ctaDisabled && styles.subscribeBtnDisabled]}
              onPress={handlePurchase}
              disabled={ctaDisabled}
            >
              {purchasing ? (
                <ActivityIndicator color="#000" />
              ) : (
                <Text style={styles.subscribeBtnText}>{ctaText}</Text>
              )}
            </TouchableOpacity>
          )}

          {/* Restore — secondary outlined button, clearly tappable, NOT a text link */}
          <TouchableOpacity
            testID="restore-purchases-btn"
            style={styles.restoreBtn}
            onPress={handleRestore}
            disabled={restoring}
            activeOpacity={0.8}
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
          <Text style={styles.restoreHelperText}>Already subscribed? Restore your existing plan.</Text>

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

          {/* Hidden QA reset — 7 taps on the version string.
              Reachable even when user is trapped on "You're subscribed".
              Indistinguishable from a standard footer version label. */}
          <TouchableOpacity
            testID="paywall-qa-reset-version-tap"
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
  restoreBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    borderWidth: 1.5,
    borderColor: '#C9A227',
    borderRadius: 12,
    backgroundColor: 'rgba(201,162,39,0.08)',
    marginTop: 10,
    marginBottom: 6,
  },
  restoreBtnText: { color: '#C9A227', fontSize: 15, fontWeight: '700' },
  restoreHelperText: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 12,
    textAlign: 'center',
    marginBottom: 16,
  },
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
  // Non-blocking divergence toast. Top-center, gold-ringed, same dark
  // luxury aesthetic as the rest of the app. pointerEvents='none' on the
  // containing view ensures it never intercepts taps on the paywall.
  divergenceToast: {
    position: 'absolute',
    top: Platform.OS === 'ios' ? 60 : 40,
    left: 16,
    right: 16,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    backgroundColor: 'rgba(15,15,15,0.94)',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(201,162,39,0.55)',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 100,
    // Subtle gold glow for visibility without interrupting the flow.
    shadowColor: '#C9A227',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 8,
    elevation: 6,
  },
  divergenceToastText: {
    color: '#E7E2D4',
    fontSize: 13.5,
    lineHeight: 19,
    textAlign: 'center',
    letterSpacing: 0.2,
    fontWeight: '500',
  },
  // Hidden QA reset tap target — deliberately indistinguishable from a
  // normal footer version label. 7 taps within 3 s triggers the reset.
  qaVersionTapTarget: {
    paddingVertical: 28,
    paddingHorizontal: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  qaVersionText: {
    color: 'rgba(255,255,255,0.18)',
    fontSize: 11,
    letterSpacing: 1,
  },
});
