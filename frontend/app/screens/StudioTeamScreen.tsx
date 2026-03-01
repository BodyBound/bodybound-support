import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  Alert,
  TextInput,
  Share,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { StudioTeam, StudioTeamMember, StudioInvite } from '../types';

const API_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface StudioTeamScreenProps {
  sessionToken: string;
  userTier: string | null;
  onBack: () => void;
  onTeamUpdated?: () => void;
}

export function StudioTeamScreen({ 
  sessionToken, 
  userTier, 
  onBack,
  onTeamUpdated 
}: StudioTeamScreenProps) {
  const [team, setTeam] = useState<StudioTeam | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviting, setInviting] = useState(false);
  const [pendingInvite, setPendingInvite] = useState<StudioInvite | null>(null);
  const [creatingTeam, setCreatingTeam] = useState(false);
  const [removingMember, setRemovingMember] = useState<string | null>(null);
  const [leavingTeam, setLeavingTeam] = useState(false);

  const isAdmin = userTier === 'the-shop';
  const isMember = userTier === 'the-shop-member';

  const fetchTeam = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/studio/team`, {
        headers: { 'Authorization': `Bearer ${sessionToken}` },
      });
      
      if (response.ok) {
        const data = await response.json();
        setTeam(data);
      } else if (response.status === 404) {
        // User not part of a team yet
        setTeam(null);
      }
    } catch (err) {
      console.error('[StudioTeam] Error fetching team:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [sessionToken]);

  useEffect(() => {
    fetchTeam();
  }, [fetchTeam]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    fetchTeam();
  }, [fetchTeam]);

  const handleCreateTeam = async () => {
    setCreatingTeam(true);
    try {
      const response = await fetch(`${API_URL}/api/studio/create`, {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${sessionToken}`,
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        Alert.alert('Team Created!', `Your studio team is ready with ${data.shared_credits} shared credits.`);
        fetchTeam();
        onTeamUpdated?.();
      } else {
        const err = await response.json();
        Alert.alert('Error', err.detail || 'Failed to create team');
      }
    } catch (err) {
      Alert.alert('Error', 'Network error. Please try again.');
    } finally {
      setCreatingTeam(false);
    }
  };

  const handleInviteMember = async () => {
    if (!inviteEmail.trim()) {
      Alert.alert('Email Required', 'Please enter the email address of the person you want to invite.');
      return;
    }

    setInviting(true);
    try {
      const response = await fetch(`${API_URL}/api/studio/invite`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${sessionToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email: inviteEmail.trim() }),
      });

      if (response.ok) {
        const data: StudioInvite = await response.json();
        setPendingInvite(data);
        setInviteEmail('');
      } else {
        const err = await response.json();
        Alert.alert('Error', err.detail || 'Failed to create invite');
      }
    } catch (err) {
      Alert.alert('Error', 'Network error. Please try again.');
    } finally {
      setInviting(false);
    }
  };

  const handleShareInvite = async () => {
    if (!pendingInvite) return;
    
    try {
      await Share.share({
        message: `You've been invited to join my Body Bound studio team!\n\nUse this invite code: ${pendingInvite.invite_code}\n\nDownload Body Bound and enter this code in Settings > Join Team to start creating stencils together.`,
        title: 'Join My Studio Team',
      });
    } catch (err) {
      console.error('[StudioTeam] Share error:', err);
    }
  };

  const handleRemoveMember = async (memberId: string, memberName: string | null) => {
    Alert.alert(
      'Remove Member',
      `Are you sure you want to remove ${memberName || 'this member'} from your team?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: async () => {
            setRemovingMember(memberId);
            try {
              const response = await fetch(`${API_URL}/api/studio/member/${memberId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${sessionToken}` },
              });

              if (response.ok) {
                Alert.alert('Member Removed', 'The member has been removed from your team.');
                fetchTeam();
                onTeamUpdated?.();
              } else {
                const err = await response.json();
                Alert.alert('Error', err.detail || 'Failed to remove member');
              }
            } catch (err) {
              Alert.alert('Error', 'Network error. Please try again.');
            } finally {
              setRemovingMember(null);
            }
          },
        },
      ]
    );
  };

  const handleLeaveTeam = async () => {
    Alert.alert(
      'Leave Team',
      'Are you sure you want to leave this studio team? You will lose access to the shared credits.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Leave',
          style: 'destructive',
          onPress: async () => {
            setLeavingTeam(true);
            try {
              const response = await fetch(`${API_URL}/api/studio/leave`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${sessionToken}` },
              });

              if (response.ok) {
                Alert.alert('Left Team', 'You have left the studio team.');
                onBack();
                onTeamUpdated?.();
              } else {
                const err = await response.json();
                Alert.alert('Error', err.detail || 'Failed to leave team');
              }
            } catch (err) {
              Alert.alert('Error', 'Network error. Please try again.');
            } finally {
              setLeavingTeam(false);
            }
          },
        },
      ]
    );
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <SafeAreaView style={styles.safeArea}>
          <View style={styles.header}>
            <TouchableOpacity onPress={onBack} style={styles.backBtn}>
              <Ionicons name="arrow-back" size={24} color="#FFF" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Studio Team</Text>
            <View style={{ width: 40 }} />
          </View>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#C9A227" />
          </View>
        </SafeAreaView>
      </View>
    );
  }

  // No team yet - show create team option (for The Shop subscribers)
  if (!team && isAdmin) {
    return (
      <View style={styles.container}>
        <SafeAreaView style={styles.safeArea}>
          <View style={styles.header}>
            <TouchableOpacity onPress={onBack} style={styles.backBtn}>
              <Ionicons name="arrow-back" size={24} color="#FFF" />
            </TouchableOpacity>
            <Text style={styles.headerTitle}>Studio Team</Text>
            <View style={{ width: 40 }} />
          </View>
          
          <ScrollView contentContainerStyle={styles.content}>
            <View style={styles.emptyState}>
              <Ionicons name="people-outline" size={80} color="#C9A227" />
              <Text style={styles.emptyTitle}>Create Your Studio Team</Text>
              <Text style={styles.emptyDescription}>
                With The Shop subscription, you can invite up to 5 team members to share 1,500 credits per month.
              </Text>
              
              <TouchableOpacity
                style={styles.createBtn}
                onPress={handleCreateTeam}
                disabled={creatingTeam}
              >
                {creatingTeam ? (
                  <ActivityIndicator color="#000" />
                ) : (
                  <>
                    <Ionicons name="add-circle" size={24} color="#000" />
                    <Text style={styles.createBtnText}>Create Team</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </ScrollView>
        </SafeAreaView>
      </View>
    );
  }

  // Team exists - show team management
  return (
    <View style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.header}>
          <TouchableOpacity onPress={onBack} style={styles.backBtn}>
            <Ionicons name="arrow-back" size={24} color="#FFF" />
          </TouchableOpacity>
          <Text style={styles.headerTitle}>Studio Team</Text>
          <View style={{ width: 40 }} />
        </View>

        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#C9A227" />
          }
        >
          {/* Credits Card */}
          <View style={styles.creditsCard}>
            <Text style={styles.creditsLabel}>Shared Credits</Text>
            <Text style={styles.creditsValue}>{team?.shared_credits ?? 0}</Text>
            <Text style={styles.creditsSubtext}>
              {team?.members.length ?? 0} of {team?.max_members ?? 5} team members
            </Text>
          </View>

          {/* Invite Section (Admin only) */}
          {isAdmin && team && team.members.length < (team.max_members || 5) && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Invite Team Member</Text>
              
              {pendingInvite ? (
                <View style={styles.inviteCodeCard}>
                  <Text style={styles.inviteCodeLabel}>Invite Code for {pendingInvite.email}</Text>
                  <Text style={styles.inviteCode}>{pendingInvite.invite_code}</Text>
                  <Text style={styles.inviteExpiry}>
                    Expires: {new Date(pendingInvite.expires_at).toLocaleDateString()}
                  </Text>
                  <TouchableOpacity style={styles.shareBtn} onPress={handleShareInvite}>
                    <Ionicons name="share-outline" size={20} color="#000" />
                    <Text style={styles.shareBtnText}>Share Invite</Text>
                  </TouchableOpacity>
                  <TouchableOpacity 
                    style={styles.newInviteBtn} 
                    onPress={() => setPendingInvite(null)}
                  >
                    <Text style={styles.newInviteBtnText}>Create Another Invite</Text>
                  </TouchableOpacity>
                </View>
              ) : (
                <View style={styles.inviteForm}>
                  <TextInput
                    style={styles.emailInput}
                    placeholder="Enter email address"
                    placeholderTextColor="#666"
                    value={inviteEmail}
                    onChangeText={setInviteEmail}
                    keyboardType="email-address"
                    autoCapitalize="none"
                  />
                  <TouchableOpacity
                    style={styles.inviteBtn}
                    onPress={handleInviteMember}
                    disabled={inviting}
                  >
                    {inviting ? (
                      <ActivityIndicator color="#000" size="small" />
                    ) : (
                      <Text style={styles.inviteBtnText}>Generate Invite</Text>
                    )}
                  </TouchableOpacity>
                </View>
              )}
            </View>
          )}

          {/* Team Members */}
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Team Members</Text>
            
            {team?.members.map((member) => (
              <View key={member.user_id} style={styles.memberCard}>
                <View style={styles.memberInfo}>
                  <View style={styles.memberAvatar}>
                    <Ionicons 
                      name={member.role === 'admin' ? 'shield' : 'person'} 
                      size={24} 
                      color="#C9A227" 
                    />
                  </View>
                  <View style={styles.memberDetails}>
                    <Text style={styles.memberName}>
                      {member.name || member.email || 'Team Member'}
                    </Text>
                    <Text style={styles.memberRole}>
                      {member.role === 'admin' ? 'Admin (Owner)' : 'Member'}
                    </Text>
                  </View>
                </View>
                
                {/* Remove button (admin only, can't remove self) */}
                {isAdmin && member.role !== 'admin' && (
                  <TouchableOpacity
                    style={styles.removeBtn}
                    onPress={() => handleRemoveMember(member.user_id, member.name)}
                    disabled={removingMember === member.user_id}
                  >
                    {removingMember === member.user_id ? (
                      <ActivityIndicator color="#FF4444" size="small" />
                    ) : (
                      <Ionicons name="close-circle" size={24} color="#FF4444" />
                    )}
                  </TouchableOpacity>
                )}
              </View>
            ))}
          </View>

          {/* Leave Team (Members only) */}
          {isMember && (
            <TouchableOpacity
              style={styles.leaveBtn}
              onPress={handleLeaveTeam}
              disabled={leavingTeam}
            >
              {leavingTeam ? (
                <ActivityIndicator color="#FF4444" />
              ) : (
                <>
                  <Ionicons name="exit-outline" size={20} color="#FF4444" />
                  <Text style={styles.leaveBtnText}>Leave Team</Text>
                </>
              )}
            </TouchableOpacity>
          )}
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#000',
  },
  safeArea: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(201,162,39,0.2)',
  },
  backBtn: {
    width: 40,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#FFF',
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  content: {
    padding: 20,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: 60,
  },
  emptyTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: '#FFF',
    marginTop: 20,
    marginBottom: 12,
  },
  emptyDescription: {
    fontSize: 16,
    color: '#999',
    textAlign: 'center',
    lineHeight: 24,
    paddingHorizontal: 20,
    marginBottom: 30,
  },
  createBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#C9A227',
    paddingHorizontal: 30,
    paddingVertical: 16,
    borderRadius: 12,
    gap: 10,
  },
  createBtnText: {
    fontSize: 18,
    fontWeight: '600',
    color: '#000',
  },
  creditsCard: {
    backgroundColor: 'rgba(201,162,39,0.15)',
    borderRadius: 16,
    padding: 24,
    alignItems: 'center',
    marginBottom: 24,
    borderWidth: 1,
    borderColor: 'rgba(201,162,39,0.3)',
  },
  creditsLabel: {
    fontSize: 14,
    color: '#999',
    marginBottom: 8,
  },
  creditsValue: {
    fontSize: 48,
    fontWeight: '700',
    color: '#C9A227',
  },
  creditsSubtext: {
    fontSize: 14,
    color: '#666',
    marginTop: 8,
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFF',
    marginBottom: 16,
  },
  inviteForm: {
    gap: 12,
  },
  emailInput: {
    backgroundColor: 'rgba(255,255,255,0.1)',
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
    color: '#FFF',
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.2)',
  },
  inviteBtn: {
    backgroundColor: '#C9A227',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
  },
  inviteBtnText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#000',
  },
  inviteCodeCard: {
    backgroundColor: 'rgba(201,162,39,0.1)',
    borderRadius: 12,
    padding: 20,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(201,162,39,0.3)',
  },
  inviteCodeLabel: {
    fontSize: 14,
    color: '#999',
    marginBottom: 8,
  },
  inviteCode: {
    fontSize: 20,
    fontWeight: '700',
    color: '#C9A227',
    letterSpacing: 1,
    marginBottom: 8,
  },
  inviteExpiry: {
    fontSize: 12,
    color: '#666',
    marginBottom: 16,
  },
  shareBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#C9A227',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
    gap: 8,
  },
  shareBtnText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#000',
  },
  newInviteBtn: {
    marginTop: 12,
    padding: 8,
  },
  newInviteBtnText: {
    fontSize: 14,
    color: '#C9A227',
  },
  memberCard: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 12,
    padding: 16,
    marginBottom: 10,
  },
  memberInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  memberAvatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: 'rgba(201,162,39,0.2)',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  memberDetails: {
    flex: 1,
  },
  memberName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FFF',
    marginBottom: 4,
  },
  memberRole: {
    fontSize: 13,
    color: '#999',
  },
  removeBtn: {
    padding: 8,
  },
  leaveBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: '#FF4444',
    borderRadius: 10,
    paddingVertical: 14,
    gap: 8,
    marginTop: 20,
  },
  leaveBtnText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#FF4444',
  },
});
