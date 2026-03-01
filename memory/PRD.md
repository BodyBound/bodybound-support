# BODY BOUND Stencil Generator - PRD

## Product Overview
An iOS app (Expo/React Native + FastAPI backend) that generates tattoo stencils from photos using AI. Designed for tattoo artists.

## Core Tech Stack
- **Frontend**: React Native (Expo SDK 54), TypeScript, expo-router
- **Backend**: FastAPI (Python), MongoDB
- **AI**: Gemini gemini-3-pro-image-preview for stencil generation
- **Auth**: Apple Sign-In (primary), Google OAuth via Emergent Auth (fallback)
- **Subscriptions**: RevenueCat SDK (react-native-purchases v9.10.5)
- **Storage**: MongoDB (tattoo_stencil DB)

## Subscription Tiers
| Tier | Price | Credits/Month | Notes |
|------|-------|---------------|-------|
| Free Trial | Free (3 days) | 10 starter credits | Auto-expires after 3 days |
| The Walk-In | $14.99/mo | 125 | Individual plan |
| Booked Out | $29.99/mo | 500 | Individual plan |
| The Shop | $99.00/mo | 1,500 shared | Team plan (up to 5 members) |

## Code Architecture
```
/app
├── backend/
│   ├── server.py          # FastAPI (~3644 lines) - monolithic but working
│   ├── requirements.txt
│   └── tests/
│       ├── test_auth_credits.py      # 26 tests
│       └── test_iter4_credits_studio.py  # 28 tests (new)
├── frontend/
│   ├── assets/
│   │   └── images/        # logo, splash-background, etc.
│   ├── app/
│   │   ├── index.tsx      # Main app (~3933 lines)
│   │   ├── types.ts       # Shared TypeScript interfaces
│   │   ├── auth.tsx       # OAuth callback route for web
│   │   ├── styles/
│   │   │   └── mainStyles.ts   # All styles
│   │   ├── components/
│   │   │   └── WelcomeScreen.tsx  # Welcome/splash screen
│   │   └── screens/
│   │       ├── AuthScreen.tsx      # Apple + Google Sign-In with device_id
│   │       ├── PaywallScreen.tsx   # RevenueCat subscription paywall
│   │       └── SettingsScreen.tsx  # Credits, subscription mgmt, account
│   ├── utils/
│   │   └── tokenStore.ts  # Web/native compatible token storage
│   ├── app.json
│   ├── .env               # EXPO_PUBLIC_BACKEND_URL
│   └── package.json
└── memory/
    └── PRD.md
```

## Key API Endpoints

### Auth & User
- `POST /api/auth/apple` - Apple Sign-In (with device_id for anti-abuse)
- `POST /api/auth/google-session` - Google Sign-In via Emergent Auth (with device_id)
- `GET /api/auth/me` - Get current user + credits (Bearer auth)
- `POST /api/auth/demo-login` - Reviewer demo account (100 credits)
- `DELETE /api/account/delete` - Delete user account (App Store req)

### Credits
- `POST /api/credits/deduct` - Atomically deduct 1 credit (handles studio teams)

### Studio Team Management (NEW)
- `GET /api/studio/team` - Get team info (credits, members, etc.)
- `POST /api/studio/create` - Create team (requires 'the-shop' subscription)
- `POST /api/studio/invite` - Invite member by email (admin only)
- `POST /api/studio/accept-invite` - Accept team invitation
- `DELETE /api/studio/member/{user_id}` - Remove member (admin only)
- `POST /api/studio/leave` - Leave team (non-admin members)

### Stencil Generation
- `POST /api/ai-stencil-async` - Generate stencil async
- `GET /api/ai-stencil-status/{job_id}` - Check job status
- `POST /api/adjust-line-weight` - Thin/thicken stencil lines
- `GET/POST /api/stencils` - Stencil gallery CRUD

### Webhooks & Cron
- `POST /api/webhooks/revenuecat` - RevenueCat subscription events
- `POST /api/tasks/refresh-credits` - Monthly credit refresh (GitHub Actions)

## MongoDB Collections
- **users**: user_id, apple_user_id, google_user_id, email, name, picture, device_id, created_at, last_login
- **subscriptions**: user_id, tier, available_credits, is_trial, trial_start_date, trial_expires_at, renewal_date, revenuecat_customer_id, anti_abuse_email, anti_abuse_device_id, anti_abuse_provider, studio_team_id
- **studio_teams**: team_id, admin_user_id, members[], shared_credits, pending_invites[], created_at
- **stencils**: id, user_id, original_image, stencil_image, settings, created_at, name

## What's Been Implemented

### 2026-03 - Credit Management & Auth System (Phase 0-2)
1. **Monolith Refactor**: `index.tsx` 6661 → 3933 lines
2. **Backend Auth**: Apple Sign-In + Google OAuth, JWT sessions (7-day expiry)
3. **Credit System**: Atomic credit deduction, trial credits (10), blocking at 0
4. **RevenueCat**: SDK configured, PaywallScreen with tier selection, webhook handler
5. **App Store Requirements**: Delete Account, demo reviewer account, store review prompt

### 2026-03 - Free Trial Logic + Anti-Abuse (Phase 3) ✅ NEW
6. **3-Day Trial**: New users get 10 credits that expire after 3 days
7. **Trial Expiration**: `trial_expires_at` and `trial_days_remaining` fields in API
8. **Anti-Abuse (Device ID + Email)**:
   - Email tracking: Same email can only get trial once
   - Device ID tracking: Same device can only get trial once
   - Provider ID tracking: Same Apple/Google account can only get trial once
9. **Device ID Collection**: Frontend uses `expo-application` to get device identifier
   - iOS: `Application.getIosIdForVendorAsync()`
   - Android: `Application.getAndroidId()`
   - Web: UUID generated and stored in localStorage

### 2026-03 - Studio Team Management UI (Phase 3) ✅ NEW
11. **StudioTeamScreen.tsx**: Full frontend UI for team management
    - View shared credits and member count
    - Create team (for The Shop subscribers)
    - Invite members by email (generates shareable invite code)
    - View team members list with roles (admin/member)
    - Remove members (admin only)
    - Leave team (members only)
12. **Settings Integration**: "Manage Studio Team" button appears only for The Shop tier

## Known Issues / Pending Work

### P0 - Active
- RevenueCat products need to be configured in App Store Connect
- RevenueCat webhook URL needs to be configured in RevenueCat Dashboard

### P1 - Upcoming
- Backend server.py refactoring (split into routes/, services/, models/)
- Studio team admin transfer functionality
- Real Apple identity token verification with proper bundle ID

### P2 - Backlog
- Crop tool inaccuracy and delay fix
- Offline/no-connection handling

## Testing Status
- **Backend Tests**: 28/28 passing (test_iter4_credits_studio.py)
- **Test Coverage**: Free trial, anti-abuse, studio team full flow
- **Test Report**: /app/test_reports/iteration_4.json

## Environment Variables
### Backend (.env)
- `MONGO_URL` - MongoDB connection string
- `DB_NAME` - Database name (tattoo_stencil)
- `GOOGLE_API_KEY` - Gemini API key
- `JWT_SECRET` - JWT signing secret
- `CRON_SECRET` - For monthly credit refresh endpoint
- `REVENUECAT_WEBHOOK_AUTH` - RevenueCat webhook auth token (optional)

### Frontend (.env)
- `EXPO_PUBLIC_BACKEND_URL` - Backend URL

## RevenueCat Configuration
- API Key: `appl_test_IuokLnnASfsuVHgijvsTOFfQAiI` (iOS)
- Products (to configure in App Store Connect):
  - `bodybound_1499_1m_3d` → The Walk-In $14.99/mo
  - `bodybound_2999_1m_3d` → Booked Out $29.99/mo
  - `bodybound_9999_1m_3d` → The Shop $99.00/mo
