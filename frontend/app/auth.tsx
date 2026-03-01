/**
 * OAuth Callback Route — /auth
 *
 * On web, after Google Sign-In, the Emergent Auth server redirects back to
 * https://<preview>.emergentagent.com/auth#session_id=<id>
 *
 * This page:
 *  1. Reads session_id from the URL hash
 *  2. Exchanges it with the backend for a JWT session token
 *  3. Stores the token via SecureStore (falls back to localStorage on web)
 *  4. Redirects to the main app at /
 *
 * On native (iOS), deep links are handled by expo-linking — this page is never loaded.
 */

import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet, Image } from 'react-native';
import { router } from 'expo-router';
import * as SecureStore from 'expo-secure-store';
import { storeToken } from './utils/tokenStore';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

export default function AuthCallback() {
  const [status, setStatus] = useState<'loading' | 'error'>('loading');
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    handleCallback();
  }, []);

  const handleCallback = async () => {
    if (typeof window === 'undefined') {
      // Native — should not land here, redirect to root
      router.replace('/');
      return;
    }

    // Read session_id from the URL hash (#session_id=xxx)
    const hash = window.location.hash.replace('#', '');
    const params = new URLSearchParams(hash);
    const sessionId = params.get('session_id');

    if (!sessionId) {
      setErrorMsg('No session ID found. Please try signing in again.');
      setStatus('error');
      setTimeout(() => router.replace('/'), 3000);
      return;
    }

    try {
      const response = await fetch(`${API_URL}/api/auth/google-session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || `Server error ${response.status}`);
      }

      const data = await response.json();
      // Store token — SecureStore uses localStorage on web
      await SecureStore.setItemAsync('session_token', data.session_token);

      // Redirect to main app — index.tsx will pick up the stored token
      router.replace('/');
    } catch (err: any) {
      console.error('[Auth callback]', err);
      setErrorMsg(err.message || 'Sign in failed. Redirecting…');
      setStatus('error');
      setTimeout(() => router.replace('/'), 3000);
    }
  };

  return (
    <View style={styles.container}>
      <Image
        source={require('../assets/images/splash-background.png')}
        style={styles.bg}
        resizeMode="cover"
      />
      <View style={styles.overlay} />

      <View style={styles.content}>
        {status === 'loading' ? (
          <>
            <ActivityIndicator size="large" color="#C9A227" />
            <Text style={styles.label}>Completing sign in…</Text>
          </>
        ) : (
          <>
            <Text style={styles.errorIcon}>!</Text>
            <Text style={styles.label}>{errorMsg}</Text>
            <Text style={styles.sub}>Redirecting you back…</Text>
          </>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0A0A0A' },
  bg: {
    position: 'absolute',
    top: 0, left: 0, right: 0, bottom: 0,
    width: '100%', height: '100%',
  },
  overlay: {
    position: 'absolute',
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.75)',
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    gap: 16,
  },
  label: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
    textAlign: 'center',
    paddingHorizontal: 32,
  },
  sub: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 13,
  },
  errorIcon: {
    color: '#C9A227',
    fontSize: 40,
    fontWeight: '800',
  },
});
