import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  Image,
  StyleSheet,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

interface WelcomeScreenProps {
  onGetStarted: () => void;
}

export function WelcomeScreen({ onGetStarted }: WelcomeScreenProps) {
  return (
    <View style={styles.welcomeContainer}>
      {/* Full-screen Background Image */}
      <Image
        source={require('../../assets/images/splash-background.png')}
        style={styles.welcomeBackgroundImage}
        resizeMode="cover"
      />

      {/* Dark Gradient Overlay for text readability */}
      <View style={styles.welcomeOverlay} pointerEvents="none" />

      {/* Content Container */}
      <SafeAreaView style={styles.welcomeContentOverlay}>
        {/* Top Section - Tagline + Disclaimer + Button */}
        <View style={styles.welcomeTopSection}>
          <Text style={styles.welcomeTaglineTop}>
            Made for Tattooers,{'\n'}By Tattooers
          </Text>

          {/* Disclaimer right under tagline */}
          <View style={styles.disclaimerUnderTagline}>
            <Text style={styles.disclaimerTextLegible}>
              WiFi required  •  AI-powered  •  Servers may occasionally be
              unavailable  •  Results may vary
            </Text>
          </View>

          {/* Get Started Button - right after disclaimer */}
          <TouchableOpacity
            testID="welcome-get-started-btn"
            style={styles.welcomeButtonTop}
            onPress={onGetStarted}
            activeOpacity={0.9}
          >
            <Text style={styles.welcomeButtonTextNew}>Let's Get Started</Text>
            <Text style={styles.welcomeButtonArrowNew}>→</Text>
          </TouchableOpacity>
        </View>

        {/* Middle Spacer - Let the artwork show */}
        <View style={styles.welcomeMiddleSpacer} />

        {/* Bottom - Just version */}
        <View style={styles.welcomeBottomVersion}>
          <Text style={styles.welcomeVersionNew}>v2.2.0</Text>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  welcomeContainer: {
    flex: 1,
    backgroundColor: '#0A0A0A',
  },
  welcomeBackgroundImage: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    height: '100%',
  },
  welcomeOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.45)',
  },
  welcomeContentOverlay: {
    flex: 1,
    paddingHorizontal: 28,
    paddingTop: 20,
    paddingBottom: 24,
  },
  welcomeTopSection: {
    marginTop: '15%',
    alignItems: 'flex-start',
  },
  welcomeTaglineTop: {
    fontSize: 36,
    fontWeight: '800',
    color: '#FFFFFF',
    letterSpacing: 0.5,
    lineHeight: 44,
    marginBottom: 14,
    textShadowColor: 'rgba(0,0,0,0.8)',
    textShadowOffset: { width: 0, height: 2 },
    textShadowRadius: 8,
  },
  disclaimerUnderTagline: {
    marginBottom: 24,
  },
  disclaimerTextLegible: {
    color: 'rgba(255,255,255,0.75)',
    fontSize: 12,
    fontStyle: 'italic',
    lineHeight: 18,
  },
  welcomeButtonTop: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#C9A227',
    paddingHorizontal: 28,
    paddingVertical: 16,
    borderRadius: 4,
    gap: 8,
  },
  welcomeButtonTextNew: {
    color: '#000000',
    fontSize: 17,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  welcomeButtonArrowNew: {
    color: '#000000',
    fontSize: 18,
    fontWeight: '700',
  },
  welcomeMiddleSpacer: {
    flex: 1,
  },
  welcomeBottomVersion: {
    alignItems: 'center',
  },
  welcomeVersionNew: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: 12,
    letterSpacing: 1,
  },
});

export default WelcomeScreen;
