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

## Recent Changes (Feb-Apr 2026)
- **Subscription state rewrite (commit `9b852a22`, Apr 21 2026)** — single authoritative writer for paid state, eliminating the "Walk-In card purchased Booked Out" / TRANSFER-overwrites-paid-state regressions.
  - New helper `apply_paid_subscription_state(user_id, product_id, source, rc_customer_id, is_apple_trial)` in `backend/server.py` — the only place paid tier/credits are written. Raises `ValueError` on unknown product_id (no silent fallback).
  - New `PRODUCT_CREDIT_MAP`: strict `product_id → (tier, credits)` map. Three known products only.
  - Rewrote `/api/webhooks/revenuecat` TRANSFER branch to be **log-only** — updates only `revenuecat_customer_id` + `last_transfer_at` on the existing doc, never upserts, never mutates tier/credits/is_trial. Writes to `rc_transfer_log` audit collection.
  - TRANSFER target resolution order: `candidate.startswith('user_')` → `db.subscriptions.user_id` match → `db.subscriptions.revenuecat_customer_id` match (covers legacy ids like `demo_reviewer_account`).
  - INITIAL_PURCHASE / RENEWAL / FRONTEND_SYNC paths all flow through `apply_paid_subscription_state` — identical state shape regardless of origin.
  - New audit fields written every paid state application: `last_product_id`, `last_applied_at`, `last_refill_at`, `monthly_allowance`, `max_balance_cap`, `credits_consumed_this_cycle: 0`, plus cycle upsell flag reset (`upsell_shown_for_cycle`, `upsell_dismissed_for_cycle`).
  - **Frontend** `app/screens/PaywallScreen.tsx`: package lookup switched from array-index to `offerings.find(p => p.identifier === key)` so RC ordering changes can't crosswire cards. `handlePurchase` + `handleRestore` both POST `/api/subscription/sync` with the exact `product.identifier` before the RC webhook arrives.
  - Deploy-sanity pytest suite `tests/test_deploy_sanity_subscription_fields.py` (6 cases) — fails hard when any rewrite audit field is missing after `FRONTEND_SYNC` / `INITIAL_PURCHASE` / `RENEWAL`, and when TRANSFER fails to stamp `last_transfer_at` / mutates paid state. Run against any host: `DEPLOY_SANITY_API_URL=<host> pytest tests/test_deploy_sanity_subscription_fields.py`.
  - Verification script `/app/verify_subscription_rewrite.sh` — end-to-end synthetic TRANSFER / INITIAL_PURCHASE / RENEWAL flow against a live host with before/after state dump.
- **Credit Rollover Policy (monthly allowance × 2 cap)** — monthly refills now roll over month-to-month, capped at 2× the plan's monthly allowance.
  - New helper `apply_monthly_refill(user_id, allowance, cycle_key, tier, extra_set)` in `backend/server.py` — atomic, idempotent per cycle_key. Uses two-step "ensure exists + conditional claim" to handle race storms safely.
  - Unique index on `subscriptions.user_id` enforced at app startup (prevents duplicate docs under concurrent upserts).
  - New subscription doc fields: `monthly_allowance`, `max_balance_cap`, `last_refill_at`. Exposed to frontend via `/auth/me` credits payload.
  - `_do_credit_refresh` cron (paid subs) now uses rollover helper with `cycle_key = 'sub:<renewal_date>'`.
  - `maybe_redeem_referral_month` (referral months) now uses rollover helper with `cycle_key = 'referral:<redeemed_at>'`.
  - Tier→allowance map: walk-in 125, booked-out 500, the-shop 1500, the-shop-member 1500, referral_premium 125. Balance cap = allowance × 2.
  - Test suite `tests/test_credit_rollover.py` — 8/8 scenarios pass (rollover, partial rollover, cap-truncation, 50-way concurrent storm, booked-out tier, referral integration, fresh user, idempotency).
- **Phase 2 Referral Reward Redemption (simple credit-based premium override)** — earned free months now grant real usable premium access, not just a dashboard counter.
  - New helper `maybe_redeem_referral_month(user_id)` in `backend/server.py` — atomic, idempotent, race-safe.
  - New tier `referral_premium` (125 credits/month) registered in `TIER_CREDITS_MAP` and `MONTHLY_ALLOWANCE_MAP`.
  - Resolution order: active referral override > paid RC sub > free/expired.
  - Paid-active users bank their earned months — activation only starts after paid sub ends.
  - Redemption triggers: every `/auth/me`, every `/referral/dashboard`, immediately after a new reward is issued.
  - New dashboard fields: `is_referral_premium_active`, `referral_premium_until`, `earned_free_months`, `blocked_by_paid_sub`.
  - New ReferralDashboard UI states: green "1 free month active until [date]" badge, "Your next earned month will activate automatically" chain hint, "X months banked" paid-user hint.
  - Pytest suite `tests/test_referral_phase2_redemption.py` — 8/8 scenarios pass.
- **Send Reminder button** on ReferralDashboard — native share sheet with prewritten "14-day reminder" copy, shown only when `pending_referrals > 0`.
- Per-style stencil history navigation arrows moved from below the stencil image to inline beneath each style button (Light / Medium / Heavy). Each button owns its own `◀ n/N ▶` row; tapping arrows switches `selectedVersion`.
- New styles added in `mainStyles.ts`: `styleButtonColumn`, `styleHistoryRow`, `styleHistoryArrow`, `styleHistoryArrowText`, `styleHistoryCounter`.

## Known Issues
- TestFlight sandbox can't load RevenueCat offerings (expected, production works)
- Admin endpoints unauthenticated (P2)
- EAS Deployment Pipeline overwriting Expo project ID (Blocked on Emergent Support)
