import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Alert,
  Image,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as AppleAuthentication from 'expo-apple-authentication';
import * as SecureStore from 'expo-secure-store';
import * as Application from 'expo-application';
import * as WebBrowser from 'expo-web-browser';
import { makeRedirectUri } from 'expo-auth-session';
import { User } from '../types';
import { storeToken } from '../../utils/tokenStore';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

// Get unique device identifier for anti-abuse tracking
const getDeviceId = async (): Promise<string | null> => {
  try {
    if (Platform.OS === 'ios') {
      // iOS: Use identifierForVendor (persists across app reinstalls for same vendor)
      return await Application.getIosIdForVendorAsync();
    } else if (Platform.OS === 'android') {
      // Android: Use Android ID
      return Application.getAndroidId();
    } else {
      // Web: Generate and persist a unique ID in localStorage
      if (typeof window !== 'undefined' && window.localStorage) {
        let webId = window.localStorage.getItem('bodybound_device_id');
        if (!webId) {
          webId = `web_${Date.now()}_${Math.random().toString(36).substring(2, 15)}`;
          window.localStorage.setItem('bodybound_device_id', webId);
        }
        return webId;
      }
    }
    return null;
  } catch (e) {
    console.log('[DeviceID] Error getting device ID:', e);
    return null;
  }
};

interface AuthScreenProps {
  onAuthSuccess: (user: User, token: string) => void;
}

export function AuthScreen({ onAuthSuccess }: AuthScreenProps) {
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [deviceId, setDeviceId] = useState<string | null>(null);

  // Get device ID on mount
  useEffect(() => {
    getDeviceId().then(setDeviceId);
  }, []);

  const handleAppleSignIn = async () => {
    setLoading(true);
    try {
      const credential = await AppleAuthentication.signInAsync({
        requestedScopes: [
          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
          AppleAuthentication.AppleAuthenticationScope.EMAIL,
        ],
      });

      // Send Apple credential to backend with device_id
      const response = await fetch(`${API_URL}/api/auth/apple`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identity_token: credential.identityToken,
          user_id: credential.user,
          email: credential.email,
          full_name: credential.fullName
            ? `${credential.fullName.givenName || ''} ${credential.fullName.familyName || ''}`.trim()
            : null,
          device_id: deviceId,
        }),
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Apple Sign-In failed');
      }

      const data = await response.json();
      await storeToken(data.session_token);
      onAuthSuccess(data.user, data.session_token);
    } catch (err: any) {
      if (err.code === 'ERR_REQUEST_CANCELED') return; // User cancelled
      Alert.alert('Sign In Failed', err.message || 'Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSignIn = async () => {
    // Google Sign-In via Emergent Auth OAuth flow
    setGoogleLoading(true);
    try {
      const { openAuthSessionAsync } = await import('expo-web-browser');
      const { makeRedirectUri } = await import('expo-auth-session');
      const { Platform } = await import('react-native');

      // On web: use the actual browser URL so maybeCompleteAuthSession() URL check passes.
      // On native: use the app deep-link scheme.
      const redirectUri =
        Platform.OS === 'web'
          ? (typeof window !== 'undefined'
              ? `${window.location.origin}/auth`
              : makeRedirectUri({ path: 'auth' }))
          : makeRedirectUri({ scheme: 'body-bound-stencil', path: 'auth' });

      const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUri)}`;

      const result = await openAuthSessionAsync(authUrl, redirectUri);

      if (result.type === 'success' && result.url) {
        // Extract session_id from URL fragment
        const url = result.url;
        const fragment = url.includes('#') ? url.split('#')[1] : '';
        const params = new URLSearchParams(fragment);
        const sessionId = params.get('session_id');

        if (!sessionId) throw new Error('No session ID received');

        // Exchange session_id for user data via backend with device_id
        const response = await fetch(`${API_URL}/api/auth/google-session`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            session_id: sessionId,
            device_id: deviceId,
          }),
        });

        if (!response.ok) {
          const err = await response.json();
          throw new Error(err.detail || 'Google Sign-In failed');
        }

        const data = await response.json();
        await storeToken(data.session_token);
        onAuthSuccess(data.user, data.session_token);
      }
    } catch (err: any) {
      if (err.message !== 'The user closed the authentication session.') {
        Alert.alert('Sign In Failed', err.message || 'Please try again.');
      }
    } finally {
      setGoogleLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      {/* Background */}
      <Image
        source={require('../../assets/images/splash-background.png')}
        style={styles.backgroundImage}
        resizeMode="cover"
      />
      <View style={styles.overlay} />

      <SafeAreaView style={styles.safeArea}>
        {/* Header */}
        <View style={styles.header}>
          <Image
            source={require('../../assets/images/logo.png')}
            style={styles.logo}
            resizeMode="contain"
          />
          <Text style={styles.title}>BODY BOUND</Text>
          <Text style={styles.subtitle}>Stencil Generator</Text>
        </View>

        {/* Auth Card */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Sign In</Text>
          <Text style={styles.cardSubtitle}>
            Create an account to track your credits and subscription
          </Text>

          {/* Apple Sign-In */}
          {Platform.OS === 'ios' && (
            <AppleAuthentication.AppleAuthenticationButton
              buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
              buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.WHITE}
              cornerRadius={4}
              style={styles.appleButton}
              onPress={handleAppleSignIn}
            />
          )}

          {loading && (
            <ActivityIndicator color="#C9A227" style={{ marginTop: 12 }} />
          )}

          {/* Divider */}
          <View style={styles.divider}>
            <View style={styles.dividerLine} />
            <Text style={styles.dividerText}>or</Text>
            <View style={styles.dividerLine} />
          </View>

          {/* Google Sign-In */}
          <TouchableOpacity
            testID="google-signin-btn"
            style={styles.googleButton}
            onPress={handleGoogleSignIn}
            disabled={googleLoading}
          >
            {googleLoading ? (
              <ActivityIndicator color="#000" size="small" />
            ) : (
              <Text style={styles.googleButtonText}>Continue with Google</Text>
            )}
          </TouchableOpacity>

          {/* Legal */}
          <Text style={styles.legal}>
            By continuing, you agree to our Terms of Service and Privacy Policy.
          </Text>
        </View>
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
    backgroundColor: 'rgba(0,0,0,0.7)',
  },
  safeArea: { flex: 1, paddingHorizontal: 24 },
  header: { flex: 1, justifyContent: 'center', alignItems: 'center', gap: 8 },
  logo: { width: 80, height: 80, marginBottom: 8 },
  title: {
    fontSize: 28, fontWeight: '800', color: '#C9A227',
    letterSpacing: 3,
  },
  subtitle: {
    fontSize: 14, color: 'rgba(255,255,255,0.7)',
    letterSpacing: 2, textTransform: 'uppercase',
  },
  card: {
    backgroundColor: 'rgba(15,15,15,0.95)',
    borderWidth: 1, borderColor: '#2A2A2A',
    borderRadius: 8,
    padding: 28,
    marginBottom: 40,
    gap: 16,
  },
  cardTitle: {
    fontSize: 22, fontWeight: '700', color: '#FFFFFF',
    textAlign: 'center',
  },
  cardSubtitle: {
    fontSize: 14, color: 'rgba(255,255,255,0.5)',
    textAlign: 'center', lineHeight: 20,
  },
  appleButton: { height: 52, width: '100%' },
  divider: {
    flexDirection: 'row', alignItems: 'center', gap: 12,
  },
  dividerLine: {
    flex: 1, height: 1, backgroundColor: '#2A2A2A',
  },
  dividerText: { color: '#666', fontSize: 13 },
  googleButton: {
    backgroundColor: '#FFFFFF',
    height: 52, borderRadius: 4,
    justifyContent: 'center', alignItems: 'center',
  },
  googleButtonText: {
    color: '#000000', fontSize: 16, fontWeight: '600',
  },
  legal: {
    fontSize: 11, color: 'rgba(255,255,255,0.3)',
    textAlign: 'center', lineHeight: 16,
  },
});
