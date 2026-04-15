# BODY BOUND Stencil Generator - PRD

## Product Overview
iOS app (Expo/React Native + FastAPI backend + MongoDB) that generates tattoo stencils from photos using AI. Designed for tattoo artists.

## Core Tech Stack
- **Frontend**: React Native (Expo SDK 54), TypeScript, expo-router
- **Backend**: FastAPI (Python), MongoDB
- **AI**: Gemini gemini-3-pro-image-preview (stencil gen), gemini-2.5-flash-image (enhancement)
- **Auth**: Apple Sign-In (primary), Google OAuth via Emergent Auth (fallback)
- **Subscriptions**: RevenueCat SDK (react-native-purchases v9.10.5)
- **Storage**: MongoDB Atlas (production), local MongoDB (preview)

## Subscription Tiers
| Tier | Price | Credits/Month | Trial Credits |
|------|-------|---------------|---------------|
| Walk-In | $14.99/mo | 125 | 10 |
| Booked Out | $29.99/mo | 500 | 10 |
| The Shop | $99.00/mo | 1,500 shared | 10 |

## Key API Endpoints
- `POST /api/ai-stencil-async` — AI stencil generation
- `POST /api/subscription/sync` — Sync RevenueCat subscription
- `POST /api/webhooks/revenuecat` — RevenueCat webhook (unauthenticated currently)
- `POST /api/promo/redeem` — Redeem promo codes
- `GET /api/diagnostics` — Visual health dashboard
- `POST /api/credits/deduct` — Deduct 1 credit (returns total_monthly_credits)
- `GET /api/auth/me` — User info + credits (returns total_monthly_credits)
- Admin endpoints: user-lookup, fix-subscription, add-credits, all-users, create-promo

### Referral System v2 Endpoints
- `GET /api/referral/code` — Get/generate user's referral code + link
- `GET /api/referral/dashboard` — Full referral stats, progress, history
- `GET /api/referral/popup-eligible` — Check popup eligibility (action-based cooldowns)
- `POST /api/referral/dismiss-popup` — Record dismissal with action type
- `POST /api/referral/check-verifications` — Cron: process 14-day verifications
- `GET /api/ref/{code}` — Landing page for referral links

## Referral System v2
- **Core rule**: 2 verified paid referrals = 1 free month (ledger only, Phase 1)
- **Status flow**: account_created → verification_pending → verified → rejected
- **14-day verification**: Referred user must stay subscribed for 14 days
- **Attribution**: First-touch, locked at signup, cannot be changed
- **Anti-abuse**: Self-referral blocked, same email/device blocked, rapid referral fraud flagging
- **Popup cooldowns**: Dismiss=7d, Share/Copy=30d, Has verified referral=60d
- **Phase 2 (NOT IMPLEMENTED)**: Reward redemption requires compliance strategy doc first

## Low-Credit Notification System
- **Persistent credit display**: Shows `X / Total` in header, always visible
- **Color coding**: Normal=gold, 25%=yellow (#F59E0B), 10%=red (#ef4444)
- **Threshold modals**: 25% (low), 10% (critical), 0% (empty/no dismiss)
- **Once per cycle**: Each threshold triggers only once per billing cycle
- **Reset on renewal**: Thresholds clear when credits increase (new billing cycle)
- **Backend**: `total_monthly_credits` returned in /auth/me and /credits/deduct responses

## Auth Token Fix
- Token only deleted on **401** (definitive auth rejection)
- Network errors and 5xx responses: token preserved, retry once after 2s delay
- Prevents sign-out after app backgrounding/memory reclaim

## AI Key Fallback System
- Primary: User's GOOGLE_API_KEY → Backup: EMERGENT_LLM_KEY
- Auto-fallback on auth/quota failures

## Critical Rules
1. **BUNDLE ID IS SACRED**: `app.emergent.tattoostencils115373ef8`
2. **NO ios/ FOLDER**: Keep Managed Workflow
3. **AI STENCILS**: gemini-3-pro-image-preview with key fallback
4. **NO .metro-cache in git**

## Known Issues
- App Store Connect / TestFlight Upload blocked (Mac VM disk full, waiting on Emergent support)
- Admin endpoints are unauthenticated (P2 security fix)
