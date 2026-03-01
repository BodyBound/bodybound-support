/**
 * tokenStore.ts
 *
 * Cross-platform session token storage.
 * - Web: localStorage (expo-secure-store exports {} on web — it's a complete stub)
 * - Native (iOS/Android): expo-secure-store (encrypted keychain storage)
 *
 * Uses typeof window check (not Platform.OS) because Platform.OS can be
 * evaluated at SSR time before the browser environment is fully set up.
 */

import * as SecureStore from 'expo-secure-store';

const NATIVE_KEY = 'session_token';
const WEB_KEY = 'bb_session_token';

const isWebEnv = () =>
  typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';

export const storeToken = async (token: string): Promise<void> => {
  if (isWebEnv()) {
    window.localStorage.setItem(WEB_KEY, token);
    return;
  }
  await SecureStore.setItemAsync(NATIVE_KEY, token);
};

export const getToken = async (): Promise<string | null> => {
  if (isWebEnv()) {
    return window.localStorage.getItem(WEB_KEY);
  }
  return SecureStore.getItemAsync(NATIVE_KEY);
};

export const deleteToken = async (): Promise<void> => {
  if (isWebEnv()) {
    window.localStorage.removeItem(WEB_KEY);
    return;
  }
  await SecureStore.deleteItemAsync(NATIVE_KEY);
};
