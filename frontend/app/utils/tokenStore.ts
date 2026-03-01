/**
 * tokenStore.ts
 *
 * Cross-platform session token storage.
 * - Native (iOS/Android): expo-secure-store (encrypted)
 * - Web preview: localStorage (expo-secure-store is a stub on web)
 */

import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const NATIVE_KEY = 'session_token';
const WEB_KEY = 'bb_session_token';

export const storeToken = async (token: string): Promise<void> => {
  if (Platform.OS === 'web') {
    if (typeof window !== 'undefined') localStorage.setItem(WEB_KEY, token);
  } else {
    await SecureStore.setItemAsync(NATIVE_KEY, token);
  }
};

export const getToken = async (): Promise<string | null> => {
  if (Platform.OS === 'web') {
    if (typeof window !== 'undefined') return localStorage.getItem(WEB_KEY);
    return null;
  }
  return SecureStore.getItemAsync(NATIVE_KEY);
};

export const deleteToken = async (): Promise<void> => {
  if (Platform.OS === 'web') {
    if (typeof window !== 'undefined') localStorage.removeItem(WEB_KEY);
  } else {
    await SecureStore.deleteItemAsync(NATIVE_KEY);
  }
};
