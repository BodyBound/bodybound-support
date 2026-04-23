/**
 * QA-only local state reset helper.
 *
 * Why this file exists:
 * On iOS, `Delete App → Reinstall` does NOT clear app identity because both
 *   (a) our `session_token` lives in the iOS Keychain via expo-secure-store, and
 *   (b) RevenueCat's `appUserID` is also Keychain-persisted by default.
 * A reinstalled build therefore re-auths silently and replays the previous
 * RC entitlement cache — which renders "You're subscribed" on the paywall
 * even on a supposedly-fresh install.
 *
 * This helper gives QA a reliable way to force a true clean-launch state
 * without erasing the device. It is invoked from hidden 7-tap gestures on
 * both `SettingsScreen` (footer) and `PaywallScreen` (footer) so it's
 * reachable even when the user is trapped on the subscribed paywall.
 *
 * Safe in production: no backend mutation, no PII; `Purchases.logOut()` is
 * reversible on next real sign-in via `Purchases.logIn(user_id)`.
 */
import Purchases from 'react-native-purchases';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/** Every SecureStore key the app has ever written. Add new ones here. */
const SECURE_STORE_KEYS = ['session_token', 'pending_referral_code'] as const;

/**
 * Hard-reset every piece of locally persisted identity on the device.
 * - RevenueCat: `Purchases.logOut()` → new anonymous appUserID, discards cached entitlements.
 * - SecureStore: delete every known key.
 *
 * Never throws. Errors are logged but swallowed so the caller can always
 * proceed to sign the user out / force a relaunch.
 */
export async function performQaLocalReset(): Promise<void> {
  // 1. RevenueCat identity
  if (Platform.OS === 'ios' || Platform.OS === 'android') {
    try {
      await Purchases.logOut();
      console.log('[QAReset] Purchases.logOut() OK');
    } catch (e) {
      // RC throws if the current user is already anonymous — not fatal.
      console.log('[QAReset] Purchases.logOut() threw (harmless if anonymous):', e);
    }
  }

  // 2. Every SecureStore key
  for (const key of SECURE_STORE_KEYS) {
    try {
      await SecureStore.deleteItemAsync(key);
    } catch (_) {
      /* ignore */
    }
  }
  console.log('[QAReset] SecureStore keys wiped');
}

/**
 * Build a tap-counter that fires `onTrigger` after `requiredTaps` within
 * `windowMs`. Consumer calls `.tap()` in the onPress handler.
 *
 * Returns a plain object (not a hook) so it can live inside a component
 * via useRef without re-rendering on every tap.
 */
export function createTapCounter(options: {
  requiredTaps: number;
  windowMs: number;
  onTrigger: () => void;
}): { tap: () => void } {
  let count = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  return {
    tap: () => {
      count += 1;
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        count = 0;
      }, options.windowMs);
      if (count >= options.requiredTaps) {
        count = 0;
        if (timer) clearTimeout(timer);
        options.onTrigger();
      }
    },
  };
}
