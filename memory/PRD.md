# BODY BOUND Stencil Generator - PRD

## Product Overview
An iOS app (Expo/React Native + FastAPI backend + MongoDB) that generates tattoo stencils from photos using AI. Designed for tattoo artists.

## Core Tech Stack
- **Frontend**: React Native (Expo SDK 54), TypeScript, expo-router
- **Backend**: FastAPI (Python), MongoDB
- **AI**: Gemini gemini-3-pro-image-preview for stencil generation
- **Auth**: Apple Sign-In (primary), Google OAuth via Emergent Auth (fallback)
- **Subscriptions**: RevenueCat SDK (react-native-purchases v9.10.5)
- **Storage**: MongoDB (tattoo_stencil DB)

## Subscription Tiers (Apple-managed trials)
| Tier | Price | Credits/Month | Trial Credits |
|------|-------|---------------|---------------|
| The Walk-In | $14.99/mo | 125 | 10 |
| Booked Out | $29.99/mo | 500 | 10 |
| The Shop | $99.00/mo | 1,500 shared | 10 |

**Trial Model**: 3-day free trial managed by Apple/RevenueCat. Users get 10 credits during trial (regardless of tier). Full tier credits unlock after first payment.

## Refer-a-Friend
- Each subscriber gets a unique referral code (BB-XXXXXX format)
- When a new subscriber redeems a code: both parties get **20 bonus credits**
- One-time use per user (can't redeem twice)
- Can't redeem your own code
- Both parties must have active subscriptions
- Stats tracked per user (total referrals, credits earned)

## Code Architecture
```
/app
├── backend/
│   ├── server.py              # FastAPI (~3820 lines) - monolithic but working
│   ├── requirements.txt
│   └── tests/
│       ├── test_paywall_flow.py          # 7 tests
│       ├── test_paywall_flow_extended.py # 16 tests
│       └── test_trial_referral.py        # 26 tests (trial cap + referral)
├── frontend/
│   ├── app/
│   │   ├── index.tsx      # Main app (~4250 lines)
│   │   ├── types.ts       # Shared TypeScript interfaces
│   │   ├── screens/
│   │   │   ├── AuthScreen.tsx
│   │   │   ├── PaywallScreen.tsx   # Required mode + referral code input
│   │   │   ├── SettingsScreen.tsx  # Refer-a-Friend section + subtle Change Plan
│   │   │   └── StudioTeamScreen.tsx
│   └── package.json
└── memory/
    ├── PRD.md
    └── test_credentials.md
```

## Key API Endpoints

### Auth & User
- `POST /api/auth/apple` - Apple Sign-In (new users: empty subscription)
- `POST /api/auth/google-session` - Google Sign-In (new users: empty subscription)
- `GET /api/auth/me` - Get current user + credits (includes `needs_subscription`)
- `POST /api/auth/demo-login` - Reviewer demo account

### Subscription & Credits
- `POST /api/subscription/sync` - Sync RevenueCat entitlement to backend (supports `is_trial` flag)
- `POST /api/credits/deduct` - Atomically deduct 1 credit
- `POST /api/webhooks/revenuecat` - RevenueCat lifecycle events (detects `period_type: TRIAL`)
- `POST /api/tasks/refresh-credits` - Monthly credit refresh (cron)

### Referral System
- `GET /api/referral/code` - Get or generate user's referral code + stats
- `POST /api/referral/redeem` - Redeem a referral code (20 credits to both parties)

### Studio Team, Stencil Generation
- Team CRUD: `/api/studio/*`
- AI Stencil: `/api/ai-stencil-async`, `/api/ai-stencil-status/{job_id}`

## MongoDB Collections
- **users**: user_id, apple_user_id, google_user_id, email, name, device_id
- **subscriptions**: user_id, tier, available_credits, is_trial, renewal_date, period_type
- **referrals**: type (code/redemption), referral_code, referrer_user_id, redeemer_user_id, status
- **studio_teams**: team_id, admin_user_id, members[], shared_credits
- **stencils**: id, user_id, original_image, stencil_image, settings

## What's Been Implemented

### 2026-03 — Trial Credit Cap + Refer-a-Friend
1. **Trial credit cap**: 10 credits for ALL tiers during Apple trial (`TRIAL_CREDITS=10`)
2. **Webhook trial detection**: `period_type=TRIAL` in RevenueCat webhook → 10 credits; `NORMAL` → full credits
3. **Sync trial detection**: `is_trial=true` parameter in `/api/subscription/sync` → 10 credits
4. **Referral code generation**: `GET /api/referral/code` returns unique BB-XXXXXX code
5. **Referral redemption**: `POST /api/referral/redeem` awards 20 credits to both parties
6. **Referral UI on Paywall**: Input field for referral code during subscription
7. **Referral UI on Settings**: "Refer a Friend" section with code display, stats, and Share button

### 2026-03 — Paywall-First Subscription Flow
1. Removed backend-managed trials (no free 3-day/10-credit trial)
2. Apple-managed trial with trial credit cap
3. Paywall-first UX (non-dismissable for new users)
4. RevenueCat sync endpoint as webhook fallback
5. `needs_subscription` flag in `/api/auth/me`
6. Startup sync of RevenueCat entitlements
7. "Change Plan" as subtle link (de-emphasized cancel)

### Earlier Work
- Credit management, auth, anti-abuse, studio teams, stencil generation
- RevenueCat LIVE keys, legal links, slider/distortion fixes, API key security

## Known Issues / Pending
- **P0**: EAS Project ID conflict (blocked on Emergent support)
- **P1**: Apple token `audience doesn't match` warnings
- **P2**: Refactor server.py (~3820 lines) and index.tsx (~4250 lines)
- **P2**: Re-enable push notifications, pre-warm rembg model

## Testing Status
- **Total Tests**: 49/49 passing (7 + 16 + 26)
- **Test Reports**: /app/test_reports/iteration_5.json, iteration_6.json
- **Coverage**: Sync, trial cap, webhook, referral CRUD, needs_subscription, regression

## RevenueCat Configuration
- API Key (Live): `appl_dVqjUPRJXPXNpLZThAjtsqApiVU`
- Product IDs → Backend Tiers:
  - `bodybound_1499_1m_3d` → walk-in (125 credits, 10 trial)
  - `bodybound_2999_1m_3d` → booked-out (500 credits, 10 trial)
  - `bodybound_9999_1m_3d` → the-shop (1500 credits, 10 trial)
