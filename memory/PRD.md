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
| Tier | Price | Credits/Month | Notes |
|------|-------|---------------|-------|
| The Walk-In | $14.99/mo | 125 | Individual plan |
| Booked Out | $29.99/mo | 500 | Individual plan |
| The Shop | $99.00/mo | 1,500 shared | Team plan (up to 5 members) |

**Trial Model**: 3-day free trial managed by Apple/RevenueCat (not backend). Users get FULL tier credits during trial. No backend-granted starter credits.

## Code Architecture
```
/app
├── backend/
│   ├── server.py          # FastAPI (~3681 lines) - monolithic but working
│   ├── requirements.txt
│   └── tests/
│       ├── test_auth_credits.py
│       ├── test_iter4_credits_studio.py
│       ├── test_paywall_flow.py          # 7 tests (paywall-first flow)
│       └── test_paywall_flow_extended.py # 16 tests (extended coverage)
├── frontend/
│   ├── assets/
│   │   └── images/
│   ├── app/
│   │   ├── index.tsx      # Main app (~4232 lines)
│   │   ├── types.ts       # Shared TypeScript interfaces
│   │   ├── auth.tsx
│   │   ├── styles/
│   │   │   └── mainStyles.ts
│   │   ├── components/
│   │   │   └── WelcomeScreen.tsx
│   │   └── screens/
│   │       ├── AuthScreen.tsx
│   │       ├── PaywallScreen.tsx   # Supports required mode (non-dismissable)
│   │       ├── SettingsScreen.tsx  # "Change Plan" subtle link
│   │       └── StudioTeamScreen.tsx
│   ├── utils/
│   │   └── tokenStore.ts
│   ├── app.json
│   └── package.json
└── memory/
    ├── PRD.md
    └── test_credentials.md
```

## Key API Endpoints

### Auth & User
- `POST /api/auth/apple` - Apple Sign-In (new users get empty subscription, no free trial)
- `POST /api/auth/google-session` - Google Sign-In (new users get empty subscription)
- `GET /api/auth/me` - Get current user + credits (includes `needs_subscription` boolean)
- `POST /api/auth/demo-login` - Reviewer demo account (100 credits)
- `DELETE /api/account/delete` - Delete user account

### Subscription & Credits
- `POST /api/subscription/sync` - Sync RevenueCat entitlement to backend (fallback for missed webhooks)
- `POST /api/credits/deduct` - Atomically deduct 1 credit
- `POST /api/webhooks/revenuecat` - RevenueCat lifecycle events
- `POST /api/tasks/refresh-credits` - Monthly credit refresh (cron)

### Studio Team Management
- `GET /api/studio/team` - Get team info
- `POST /api/studio/create` - Create team (The Shop only)
- `POST /api/studio/invite` - Invite member
- `POST /api/studio/accept-invite` - Accept invitation
- `DELETE /api/studio/member/{user_id}` - Remove member
- `POST /api/studio/leave` - Leave team

### Stencil Generation
- `POST /api/ai-stencil-async` - Generate stencil async
- `GET /api/ai-stencil-status/{job_id}` - Check job status
- `POST /api/adjust-line-weight` - Adjust stencil lines
- `GET/POST /api/stencils` - Stencil gallery CRUD

## MongoDB Collections
- **users**: user_id, apple_user_id, google_user_id, email, name, device_id, created_at, last_login
- **subscriptions**: user_id, tier, available_credits, is_trial, renewal_date, revenuecat_customer_id, anti_abuse_*
- **studio_teams**: team_id, admin_user_id, members[], shared_credits, pending_invites[]
- **stencils**: id, user_id, original_image, stencil_image, settings, created_at, name

## What's Been Implemented

### 2026-03 — Paywall-First Subscription Flow Refactor ✅ NEW
1. **Removed backend-managed trials**: New users get empty subscription (tier=null, credits=0) instead of 3-day/10-credit trial
2. **Apple-managed trial**: 3-day free trial handled by Apple/RevenueCat, full credits during trial
3. **Paywall-first UX**: New users see non-dismissable PaywallScreen immediately after sign-in
4. **RevenueCat sync endpoint**: `POST /api/subscription/sync` — frontend-driven sync for missed webhook scenarios
5. **needs_subscription flag**: `/api/auth/me` response includes boolean indicating if user must subscribe
6. **Startup sync**: On app launch, frontend syncs RevenueCat entitlements with backend (fixes stale subscription data)
7. **Cancel button de-emphasized**: "Manage Subscription" renamed to "Change Plan" and styled as subtle text link below Sign Out
8. **PaywallScreen text updated**: Reflects Apple-managed trial (full access, cancel anytime)
9. **Grandfathering**: Existing trial users' subscriptions are untouched — they keep their current trial

### 2026-03 — Previous Work
- Credit Management & Auth System (Phase 0-2)
- Free Trial Logic + Anti-Abuse (Phase 3) — now superseded by Apple-managed trials
- Studio Team Management UI
- RevenueCat LIVE keys and package identifiers
- Paywall legal links (EULA, Privacy Policy)
- VerticalSlider state/closure bug fix
- Edited stencil distortion bug fix
- Deployment crash fix (lazy rembg, /health endpoint)
- API key security (.gitignore protection)

## Known Issues / Pending Work

### P0 - Active
- **Booked Out customer showing 10 credits**: Fix deployed (RevenueCat sync on startup), requires new App Store build to take effect
- **EAS Project ID conflict**: Blocked on Emergent platform support

### P1 - Upcoming
- Apple token `audience doesn't match` warnings in backend logs
- Backend server.py refactoring (split into routes/services/models)
- Frontend index.tsx refactoring (extract components/hooks)

### P2 - Backlog
- Re-enable push notifications for production
- Pre-warm rembg ONNX model on backend startup
- Studio team admin transfer functionality

## Testing Status
- **Paywall Flow Tests**: 23/23 passing (test_paywall_flow.py + test_paywall_flow_extended.py)
- **Test Report**: /app/test_reports/iteration_5.json
- **Coverage**: Sync endpoint, needs_subscription field, product mapping, webhook, cron

## Environment Variables
### Backend (.env)
- `MONGO_URL`, `DB_NAME`, `GOOGLE_API_KEY`, `JWT_SECRET`, `CRON_SECRET`, `REVENUECAT_WEBHOOK_AUTH`

### Frontend (.env)
- `EXPO_PUBLIC_BACKEND_URL`

## RevenueCat Configuration
- API Key (Live): `appl_dVqjUPRJXPXNpLZThAjtsqApiVU`
- Product IDs → Backend Tiers:
  - `bodybound_1499_1m_3d` → walk-in (125 credits)
  - `bodybound_2999_1m_3d` → booked-out (500 credits)
  - `bodybound_9999_1m_3d` → the-shop (1500 credits)
