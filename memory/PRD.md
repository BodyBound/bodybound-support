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
| Tier | Price | Credits/Month |
|------|-------|---------------|
| Free Trial | Free (3 days) | 10 starter credits |
| Hobbyist | $14.99/mo | 125 |
| Pro | $29.99/mo | 500 |
| Studio | $99.00/mo | 1,500 shared (up to 5 members) |

## Code Architecture
```
/app
├── backend/
│   ├── server.py          # FastAPI (~3075 lines) - monolithic but working
│   ├── requirements.txt
│   └── tests/
│       └── test_auth_credits.py  # 26 passing tests
├── frontend/
│   ├── assets/
│   │   └── images/        # logo, splash-background, etc.
│   ├── app/
│   │   ├── index.tsx      # Main app (~3933 lines, reduced from 6661)
│   │   ├── types.ts       # Shared TypeScript interfaces
│   │   ├── styles/
│   │   │   └── mainStyles.ts   # All styles (extracted from index.tsx)
│   │   ├── components/
│   │   │   └── WelcomeScreen.tsx  # Welcome/splash screen
│   │   └── screens/
│   │       ├── AuthScreen.tsx      # Apple + Google Sign-In
│   │       ├── PaywallScreen.tsx   # RevenueCat subscription paywall
│   │       └── SettingsScreen.tsx  # Credits, subscription mgmt, account
│   ├── app.json
│   ├── .env               # EXPO_PUBLIC_BACKEND_URL
│   └── package.json
└── memory/
    └── PRD.md
```

## Key API Endpoints
### Existing (Stencil Generation)
- `POST /api/ai-stencil-async` - Generate stencil async
- `GET /api/ai-stencil-status/{job_id}` - Check job status
- `POST /api/adjust-line-weight` - Thin/thicken stencil lines
- `GET/POST /api/stencils` - Stencil gallery CRUD

### Auth & Credits (Added 2026-03)
- `POST /api/auth/apple` - Apple Sign-In (verifies identity token)
- `POST /api/auth/google-session` - Google Sign-In via Emergent Auth
- `GET /api/auth/me` - Get current user + credits (Bearer auth)
- `POST /api/auth/demo-login` - Reviewer demo account (100 credits)
- `POST /api/credits/deduct` - Atomically deduct 1 credit
- `DELETE /api/account/delete` - Delete user account (App Store req)
- `POST /api/webhooks/revenuecat` - RevenueCat subscription events

## MongoDB Collections
- **users**: user_id, apple_user_id, google_user_id, email, name, picture, created_at, last_login
- **subscriptions**: user_id, tier, available_credits, is_trial, renewal_date, revenuecat_customer_id, anti_abuse_key
- **stencils**: id, user_id, original_image, stencil_image, settings, created_at, name
- **studio_teams**: (TBD - Studio tier multi-user support)

## What's Been Implemented

### 2026-03 - Credit Management & Auth System (Phase 0-2)
1. **Monolith Refactor**: `index.tsx` 6661 → 3933 lines
   - Extracted styles → `styles/mainStyles.ts`
   - Extracted WelcomeScreen → `components/WelcomeScreen.tsx`
   - Created `types.ts` for shared interfaces
   - Created new screens: AuthScreen, PaywallScreen, SettingsScreen
2. **Backend Auth**: Apple Sign-In + Google OAuth, JWT sessions (7-day expiry), user CRUD
3. **Credit System**: Atomic credit deduction, trial credits (10), blocking at 0, 402 response
4. **RevenueCat**: SDK configured, PaywallScreen with tier selection, webhook handler
5. **App Store Requirements**: Delete Account endpoint, demo reviewer account, store review prompt after 5 generations
6. **Security**: JWT secret >32 bytes, anti-abuse key for trial prevention
7. **Cleanup**: Removed debug alert, API_URL now from env var

### 2026-03 - RevenueCat Full Integration + Monthly Credit Refresh (Phase 2-3)
8. **Purchases.logIn(userId)**: Called after every successful auth (startup token restore + onAuthSuccess). Links user to RevenueCat so webhooks use our backend user_id as app_user_id.
9. **Webhook Fix**: Webhook now matches subscriptions via `user_id` (was `revenuecat_customer_id`). Handles INITIAL_PURCHASE, RENEWAL (grant credits), CANCELLATION, EXPIRATION (mark expired).
10. **Renewal Date**: Webhook sets renewal_date to 30 days from now (was incorrectly set to now).
11. **Monthly Credit Refresh Cron**: `POST /api/cron/refresh-credits` endpoint protected by `CRON_SECRET` env var. Finds all active paid subscriptions with overdue renewal_date, refreshes credits, advances renewal_date by 30 days.
12. **GitHub Actions Workflow**: `/.github/workflows/monthly-credit-refresh.yml` — runs on 1st of each month or on manual trigger. Requires GitHub Secrets: `BACKEND_URL` and `CRON_SECRET`.
13. **PaywallScreen Web Handling**: Skips `Purchases.getOfferings()` on web (no SDK), shows static prices, changes CTA to "Subscribe in iOS App Store" on web platform.
14. **Bug Fix**: Added `Platform` to imports in `mainStyles.ts` (critical — was causing app crash).
15. **WelcomeScreen**: Added default export to eliminate Expo Router warning.

### 2026-03 - Monthly Cron Endpoint + Push Notifications (Phase 3 cont.)
16. **New endpoint** `POST /api/tasks/refresh-credits` — secured by `X-Cron-Secret` header. Reads `CRON_SECRET` env var.
17. **Shared `_do_credit_refresh()`** — extracted logic; both cron endpoints call the same function.
18. **GitHub Actions workflow** at `.github/workflows/monthly_refresh.yml` — runs 1st of each month 00:00 UTC or on manual trigger. Uses `X-Cron-Secret: ${{ secrets.CRON_SECRET }}`.
19. **Low-credit push notification** — `expo-notifications` + `expo-device` installed. `setupNotifications()` requests permission on first login. `sendLowCreditsNotification()` fires local notification when credits drop below 10 (once per session, resets when credits recover).
20. **expo-auth-session pinned to `~7.0.10`** — fixes SSR crash from accidental upgrade to 55.x (incompatible with expo@54).

## Known Issues / Pending Work

### P0 - Active
- RevenueCat products need to be configured in App Store Connect (IDs: bodybound_1499_1m_3d, bodybound_2999_1m_3d, bodybound_9999_1m_3d)
- RevenueCat webhook URL needs to be configured in RevenueCat Dashboard → pointing to `/api/webhooks/revenuecat`
- Studio tier team management (admin invite system, shared credits) not yet built

### P1 - Upcoming
- Backend server.py refactoring (split into routes/, services/, models/) — currently ~3129 lines
- Real Apple identity token verification with proper bundle ID
- RevenueCat webhook auth token setup (REVENUECAT_WEBHOOK_AUTH env var)

### P2 - Backlog
- Crop tool inaccuracy and delay fix
- Offline/no-connection handling
- textShadow/boxShadow deprecation warnings in React Native Web

## GitHub Actions Setup (Monthly Credit Refresh)
Workflow file: `/.github/workflows/monthly-credit-refresh.yml`
Required GitHub Secrets:
- `BACKEND_URL` = your production backend URL
- `CRON_SECRET` = `bb-cron-2026-refresh-c7f3a1` (set in backend/.env)

## Environment Variables
### Backend (.env)
- `MONGO_URL` - MongoDB connection string
- `DB_NAME` - Database name (tattoo_stencil)
- `GOOGLE_API_KEY` - Gemini API key
- `JWT_SECRET` - JWT signing secret (optional, has default)
- `REVENUECAT_WEBHOOK_AUTH` - RevenueCat webhook auth token (optional)

### Frontend (.env)
- `EXPO_PUBLIC_BACKEND_URL` - Backend URL (production stable URL)
- `EXPO_TUNNEL_SUBDOMAIN` - Expo tunnel subdomain

## RevenueCat Configuration
- API Key: `appl_test_IuokLnnASfsuVHgijvsTOFfQAiI` (iOS)
- Entitlement: `premium`
- Products (to configure in App Store Connect):
  - `bodybound_1499_1m_3d` → Hobbyist $14.99/mo
  - `bodybound_2999_1m_3d` → Pro $29.99/mo
  - `bodybound_9999_1m_3d` → Studio $99.00/mo

## Testing
- Backend tests: `/app/backend/tests/test_auth_credits.py` - 26 tests, 100% passing
- Test command: `cd /app/backend && python -m pytest tests/ -v`
- Demo reviewer account: `POST /api/auth/demo-login`
