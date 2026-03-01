// Shared TypeScript interfaces for BODY BOUND Stencil Generator

export interface StencilSettings {
  clarity: number;
  line_weight: number;
  noise_reduction: number;
  invert: boolean;
}

export interface SavedStencil {
  id: string;
  original_image: string;
  stencil_image: string;
  settings: StencilSettings;
  created_at: string;
  name: string | null;
}

// Lightweight interface for gallery list (thumbnails only)
export interface StencilListItem {
  id: string;
  stencil_thumbnail: string | null;
  created_at: string;
  name: string | null;
}

// User & Auth Types
export interface User {
  user_id: string;
  email: string | null;
  name: string | null;
  picture?: string | null;
  apple_user_id?: string | null;
  google_user_id?: string | null;
  created_at: string;
}

export interface AuthSession {
  user: User;
  session_token: string;
}

// Subscription & Credits
export type SubscriptionTier = 'trial' | 'trial_expired' | 'walk-in' | 'booked-out' | 'the-shop' | 'the-shop-member' | 'hobbyist' | 'pro' | 'studio' | null;

export interface UserCredits {
  available_credits: number;
  tier: SubscriptionTier;
  is_trial: boolean;
  trial_expires_at: string | null;
  trial_days_remaining: number | null;
  renewal_date: string | null;
  revenuecat_customer_id: string | null;
  is_studio_team?: boolean;
  studio_team_id?: string | null;
}

// Studio Team Types
export interface StudioTeamMember {
  user_id: string;
  email: string | null;
  name: string | null;
  role: 'admin' | 'member';
  joined_at: string;
}

export interface StudioTeam {
  team_id: string;
  admin_user_id: string;
  members: StudioTeamMember[];
  shared_credits: number;
  max_members: number;
  created_at: string;
}

export interface StudioInvite {
  invite_code: string;
  expires_at: string;
  email: string;
}
