# BODY BOUND Stencil Generator - PRD

## Product Overview
iOS app (Expo/React Native + FastAPI backend + MongoDB) that generates tattoo stencils from photos using AI. Designed for tattoo artists.

## Core Tech Stack
- **Frontend**: React Native (Expo SDK 54), TypeScript, expo-router
- **Backend**: FastAPI (Python), MongoDB
- **AI**: Gemini gemini-3-pro-image-preview (stencil gen), gemini-2.5-flash-image (enhancement)
- **Auth**: Apple Sign-In (primary), Google OAuth via Emergent Auth (fallback)
- **Subscriptions**: RevenueCat SDK (react-native-purchases v9.10.5)

## Subscription Tiers
| Tier | Price | Credits/Month |
|------|-------|---------------|
| Walk-In | $14.99/mo | 125 |
| Booked Out | $29.99/mo | 500 |
| The Shop | $99.00/mo | 1,500 shared |

## Key Systems

### Referral System v2 (Ledger Only)
- 2 verified paid referrals = 1 free month (tracked, not redeemed yet)
- Status flow: account_created → verification_pending → verified → rejected
- 14-day verification, first-touch attribution, anti-abuse
- Popup cooldowns: Dismiss=7d, Share/Copy=30d, Has verified referral=60d

### Low-Credit Notification & Upgrade System
- Persistent `X / Total` credit display in header (gold/yellow/red)
- Threshold modals at 25%, 10%, 0% — each fires once per billing cycle
- Low-credit modal includes both "Upgrade Plan" and "Invite Artists" CTAs
- 0-credit modal blocks generation (no dismiss)

### Growth Messaging System
- **Referral Banner**: Persistent, dismissible (7d cooldown), paid users only. "Invite 2 artists → get 1 free month"
- **Milestone Modal**: After 3rd gen, then every 10th. "That took you minutes." → Invite Artists
- **Flex Messages**: Inline, auto-fading. At 10/25/50 credits used. Value reinforcement copy.
- **Priority**: Low credit modal > Milestone modal > Banner > Flex message. Only one prompt at a time.

### Auth Token Persistence Fix
- Token only deleted on 401 (not 5xx/network errors)
- Retry once with 2s delay on network failure
- Prevents sign-out after iOS app backgrounding

## Key API Endpoints
- `POST /api/ai-stencil-async` — AI stencil generation
- `POST /api/subscription/sync` — Sync RevenueCat subscription
- `POST /api/webhooks/revenuecat` — RevenueCat webhook
- `POST /api/credits/deduct` — Deduct 1 credit (returns total_monthly_credits)
- `GET /api/auth/me` — User info + credits (returns total_monthly_credits)
- `GET /api/referral/dashboard` — Full referral stats
- `POST /api/referral/dismiss-popup` — Record dismissal with action type
- `POST /api/referral/check-verifications` — Cron: 14-day verification
- `GET /api/ref/{code}` — Referral landing page

## Frontend Components
- `ReferralBanner.tsx` — Persistent banner in main working screen
- `MilestoneModal.tsx` — Value reinforcement modal after generation milestones
- `FlexMessage.tsx` — Inline auto-fading achievement message
- `LowCreditModal.tsx` — Threshold modal with upgrade + referral CTAs
- `ReferralPopup.tsx` — Original referral popup (still available)
- `ReferralDashboard.tsx` — Full referral stats screen

## Critical Rules
1. **BUNDLE ID**: `app.emergent.tattoostencils115373ef8`
2. **NO ios/ FOLDER**: Expo Managed Workflow only
3. **AI STENCILS**: gemini-3-pro-image-preview with Emergent key fallback
4. **NO .metro-cache in git**

## Known Issues
- TestFlight upload blocked (Mac VM disk full, waiting on Emergent support)
- Admin endpoints unauthenticated (P2)
