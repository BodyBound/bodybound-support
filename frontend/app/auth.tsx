/**
 * OAuth Callback Route — /auth
 *
 * Popup flow (primary — web preview):
 *   1. openAuthSessionAsync() in AuthScreen opens this page in a popup
 *   2. WebBrowser.maybeCompleteAuthSession() (called below at module level) detects
 *      the popup context, sends the current URL back to the parent window, and closes
 *   3. The parent window's openAuthSessionAsync resolves with the URL containing
 *      #session_id=xxx, and AuthScreen.tsx handles the token exchange
 *
 * Full-page redirect flow (fallback):
 *   If the OAuth opens the current tab instead of a popup (some browsers/settings),
 *   window.opener is null and we do the full token exchange here.
 *
 * Native (iOS):
 *   Deep links are handled by expo-linking — this page never loads on native.
 */

import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet, Image } from 'react-native';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { storeToken } from '../utils/tokenStore';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

// MUST be at module top-level — signals the parent window in popup OAuth flow
// and closes the popup. In full-page-redirect flow this is a no-op.
WebBrowser.maybeCompleteAuthSession();

export default function AuthCallback() {
  const [status, setStatus] = useState<'loading' | 'error'>('loading');
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    if (typeof window === 'undefined') return;

    // Popup flow: maybeCompleteAuthSession() above already handled it.
    // The popup will close on its own — nothing else needed.
    if (window.opener) return;

    // Full-page redirect flow: browser opened this URL in the current tab.
    // Do the full token exchange and redirect to the main app.
    handleFullPageRedirect();
  }, []);

  const handleFullPageRedirect = async () => {
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
      await storeToken(data.session_token);
      router.replace('/');
    } catch (err: any) {
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
  bg: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, width: '100%', height: '100%' },
  overlay: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.75)' },
  content: { flex: 1, justifyContent: 'center', alignItems: 'center', gap: 16 },
  label: { color: '#FFFFFF', fontSize: 16, fontWeight: '600', textAlign: 'center', paddingHorizontal: 32 },
  sub: { color: 'rgba(255,255,255,0.4)', fontSize: 13 },
  errorIcon: { color: '#C9A227', fontSize: 40, fontWeight: '800' },
});
