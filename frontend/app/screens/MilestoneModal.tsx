import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Modal,
} from 'react-native';
import { Feather } from '@expo/vector-icons';

interface MilestoneModalProps {
  visible: boolean;
  onInvite: () => void;
  onDismiss: () => void;
}

export function MilestoneModal({ visible, onInvite, onDismiss }: MilestoneModalProps) {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onDismiss}
    >
      <View style={styles.overlay}>
        <View style={styles.card}>
          <TouchableOpacity onPress={onDismiss} style={styles.closeBtn} data-testid="milestone-dismiss">
            <Feather name="x" size={20} color="#666" />
          </TouchableOpacity>

          <View style={styles.iconCircle}>
            <Feather name="zap" size={28} color="#C9A227" />
          </View>

          <Text style={styles.headline}>That took you minutes.</Text>
          <Text style={styles.body}>
            Most artists would spend hours building that stencil by hand.
          </Text>

          <TouchableOpacity onPress={onInvite} style={styles.primaryBtn} data-testid="milestone-invite-btn">
            <Feather name="users" size={18} color="#000" />
            <Text style={styles.primaryBtnText}>Invite Artists</Text>
          </TouchableOpacity>

          <TouchableOpacity onPress={onDismiss} style={styles.laterBtn} data-testid="milestone-not-now">
            <Text style={styles.laterText}>Not Now</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.65)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  card: {
    backgroundColor: '#12121f',
    borderRadius: 20,
    padding: 28,
    width: '100%',
    maxWidth: 360,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#1e1e35',
  },
  closeBtn: {
    position: 'absolute',
    top: 14,
    right: 14,
    width: 32,
    height: 32,
    justifyContent: 'center',
    alignItems: 'center',
  },
  iconCircle: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: 'rgba(201, 162, 39, 0.12)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 18,
    marginTop: 8,
  },
  headline: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '800',
    textAlign: 'center',
    marginBottom: 8,
  },
  body: {
    color: '#999',
    fontSize: 14,
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 24,
  },
  primaryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#C9A227',
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 24,
    width: '100%',
    gap: 8,
  },
  primaryBtnText: {
    color: '#000',
    fontWeight: '700',
    fontSize: 16,
  },
  laterBtn: {
    paddingVertical: 12,
  },
  laterText: {
    color: '#555',
    fontSize: 14,
  },
});
