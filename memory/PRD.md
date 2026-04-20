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
- Daily auto-cron for verification processing

### Low-Credit Notification & Upgrade System
- Persistent `X / Total` credit display (gold/yellow/red)
- Threshold modals at 25%/10%/0% with upgrade + referral CTAs
- 0-credit blocks generation

### Growth Messaging System
- Referral Banner, Milestone Modal, Flex Messages, Low Credit + Referral combo
- Priority system: only one prompt at a time

### Feedback & Review System
- Triggers after save/export, 3+ generations, once per session
- "Did this save you time?" → thumbs up/down
- Positive path: Share (native share sheet), Leave feedback (text), App Store review
- Negative path: Quick tags (too messy, missing details, not accurate, hard to use, other)
- Frequency: stops after user shares/reviews/gives feedback
- Backend: `POST /api/feedback`, `GET /api/feedback/should-prompt`, `GET /api/admin/feedback-summary`
- Collections: `user_feedback`, `feedback_status`

### Credit Deduction
- All 3 generation paths deduct 1 credit on success: generateAIStencil, regenerateSingleStyle, generateSingleStyle
- Credit check (≤0 → upgrade modal) added to all paths
- No free retry logic exists yet — planned as future feature
- 5 color options in editor: Black, Red, Blue, Green, White
- Tint persists to main screen display
- Applied via React Native `tintColor` on transparent PNG

### Auth & Session
- Token only deleted on 401 (not 5xx/network errors), retry once on failure
- RevenueCat race condition fixed: PaywallScreen waits for `revenueCatReady`
- Paywall shows error + retry when offerings fail, sign-out link visible
- Disabled button now visually gray (not just dimmed)
- Fallback credits: If RevenueCat offerings fail, user can tap "Get Free Credits Instead" for 15 one-time credits (flag: `fallback_credits_granted` in DB)

## Critical Rules
1. **BUNDLE ID**: `app.emergent.tattoostencils115373ef8`
2. **NO ios/ FOLDER**: Expo Managed Workflow only
3. **AI STENCILS**: gemini-3-pro-image-preview with Emergent key fallback
4. **NO credit purchases**: Monetization = subscriptions + referral rewards only
5. **Existing user credits preserved**: Legacy/promo credits remain functional

## Recent Changes (Feb 2026)
- Per-style stencil history navigation arrows moved from below the stencil image to inline beneath each style button (Light / Medium / Heavy). Each button now owns its own `◀ n/N ▶` row, shown only when that style has >1 generation in session history. Tapping arrows also switches `selectedVersion` so users can jump back to any previously-paid style's variants for free. Tapping a previously-generated style button (no arrows) continues to re-select its latest without charging credits.
- New styles added in `mainStyles.ts`: `styleButtonColumn`, `styleHistoryRow`, `styleHistoryArrow`, `styleHistoryArrowText`, `styleHistoryCounter`.
- `styleButtonsRow` alignItems changed from `center` to `flex-start` to keep all 3 style buttons top-aligned when only one column shows its history row.

## Known Issues
- TestFlight sandbox can't load RevenueCat offerings (expected, production works)
- Admin endpoints unauthenticated (P2)
- EAS Deployment Pipeline overwriting Expo project ID (Blocked on Emergent Support)
