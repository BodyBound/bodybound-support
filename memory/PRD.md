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
- **Light Tier Standalone Prompt + Black Square Edit-Mode Fix (Apr 25 2026)** — two locked-in fixes:
  - **Light prompt rebuilt as standalone Feb-16-2026 photo-to-line-art tracing brief.** No longer inherits the Blueprint Heavy+ four-tier hierarchy / DOTTED tier / "tattoo stencil" framing. `build_blueprint_prompt("...", "minimal")` now returns the original Feb-16 brief with hardcoded `SHADING AMOUNT: MINIMAL` + `BLACK FILLS: NONE`. Medium and Heavy+ unchanged. User-approved against `/api/tier-compare`. Regression suite: `tests/test_prompt_tier_differentiation.py` (5/5 pass).
  - **Black-square-after-edit fix.** Root cause: edit canvas captures with an opaque white background; main screen applies `tintColor: '#000000'` to the new stencil and tints the entire white background black. Fix: track new state `isEditedStencil` (set true in `saveEditedStencil`, reset false at every fresh-stencil entry: `selectVersion`, history nav, `regenerateSingleStyle`, `generateSingleStyle`, line-weight adjust, `loadStencilFromGallery`, `revertToOriginal`, `processImage`). Main-screen `Image` now skips tintColor when `isEditedStencil` is true. Affects all 3 tiers (Light/Medium/Heavy) — bug was tier-agnostic.
  - **Live preview:** `GET /api/tier-compare`.

- **Blueprint Heavy+ — Production Standard (Apr 23 2026)** — locked in as the default generation behaviour for every stencil produced by `/api/ai-stencil` and `/api/process_stencil_job`. Replaces the previous Blueprint Mode pass.
  - Four-tier line-weight hierarchy: **PRIMARY** (bold outer contours, foreground) / **SECONDARY** (medium internal structure, facial features) / **TERTIARY** (fine texture, hair flow) / **DOTTED** (light facial guides + form transitions). `DOTTED` is now a first-class tier, not a Heavy-only exception.
  - `Lines MUST NOT be uniform weight` and `foreground reads stronger than background` are explicit rules.
  - Heavy block renamed **Heavy+**: preserve detail, reduce visual noise ~10–20%, hair follows directional flow (not random strands), texture is selective (not full-surface coverage), dotted facial guides retained, avoid clutter.
  - New `CONSISTENCY REQUIREMENT` section in the prompt — same reference → consistent structure → predictable line placement.
  - **Consistency default**: `temperature=0.0` is now the default on `/api/ai-stencil` (was `None`/provider default) and hardcoded in the async `process_stencil_job` path. Near-deterministic sampling by default; overridable per request.
  - All prior Fine-Line Refinements preserved (thinnest possible facial features, thinnest possible interior hair strands that don't merge, individual-stroke eyelashes, hollow pupils/irises).
  - Live preview: `GET /api/blueprint-heavy` (skull + lion Heavy+).

- **Blueprint Mode (Apr 23 2026)** — new default generation behaviour for every stencil produced by `/api/ai-stencil` and `/api/process_stencil_job`. Zero fills, line-only output, three-tier line-weight hierarchy (PRIMARY silhouette / SECONDARY features / TERTIARY texture), blueprint-purpose framing (guide for a human artist, no shading interpretation).
  - New single-source-of-truth helper `build_blueprint_prompt(line_color, detail_level)` in `backend/server.py`. Both generation endpoints now call it — no more duplicated 80-line prompt blocks drifting out of sync.
  - Removed from the base prompt: all fill logic, shadow interpretation, dotted-line shading guides, light-to-dark dotted transitions, lighting-density distribution rules, crosshatching.
  - Detail levels re-mapped to Blueprint tiers: Light = PRIMARY + SECONDARY only (cleanest outline), Medium = + reduced TERTIARY (key texture direction), Heavy = all three tiers fully expressed (line-only texture, never fills).
  - Opt-in request fields left available for future experimentation without touching core code: `temperature` (forwarded via `with_params` to Gemini through LiteLLM) and `extra_preamble` (prepended string). Default request shape unchanged.
  - Pre-scan experiment retired: variance test (2 images × 2 runs × 2 conditions at temperature=0) showed the prompt-prepended pre-scan block INCREASED output variance by 9% (skull) and 2.7% (lion). Decision: not wired into any production pipeline.
  - Live preview: `GET /api/blueprint-mode`. Variance preview: `GET /api/prompt-preview-prescan`.
  - Demo script: `backend/scripts/blueprint_mode_demo.py` generates Light + Heavy pairs for skull and lion at temperature=0 using the live endpoint.

- **QA-only local reset gesture (Apr 23 2026)** — shipped to `main`:
  - **Problem isolated during paywall validation**: `Delete App → Reinstall` does NOT produce a clean slate on iOS. Root causes: (1) `expo-secure-store` persists our `session_token` in iOS Keychain which survives uninstall by design, (2) RevenueCat's `appUserID` is also Keychain-persisted → `Purchases.getCustomerInfo()` replays cached entitlements attached to the previous identity, causing PaywallScreen to show "You're subscribed" on a supposedly-fresh install (triggered at `PaywallScreen.tsx:164-166`).
  - **Fix shipped** (`frontend/app/screens/SettingsScreen.tsx`): hidden 7-tap gesture on a version-number footer inside Settings → Danger Zone. 7 taps within 3 s → confirmation Alert → performs `Purchases.logOut()` + `SecureStore.deleteItemAsync('session_token')` + `SecureStore.deleteItemAsync('pending_referral_code')` + routes back through `onSignOut()`. Final Alert prompts user to force-quit and relaunch for a guaranteed fresh-install path.
  - **Production-safe**: footer renders as a muted `rgba(255,255,255,0.18)` version label — indistinguishable from a normal copyright line. No backend mutation, no PII exposure, `Purchases.logOut()` is reversible by next `Purchases.logIn(user_id)` call on real sign-in.
  - **Not a permanent fix for end-users**: this is a QA tool. A long-term solution would be "on first launch after fresh install, auto-wipe Keychain via a NSUserDefaults sentinel" — tracked as P2 backlog.

- **Reroll + Thumbs-Rating (Apr 23 2026)** — shipped to `main`, shared lib ready for `redesign/unified-editor`:
  - **Root-cause fix**: `/api/credits/deduct` individual-user branch was previously orphaned module-level code (only studio teams worked); restored inside the function. Plus `/api/ai-stencil` was returning the same cached image on every reroll — cache now skipped when `regenerate_style` is set.
  - **Reroll cost UX**: per-style inline label under each style button ("Free reroll" in green / "1 credit" in gold). First reroll per style stays free; every reroll after requires a native `Alert.alert` confirmation before the credit is spent. NO hard cap — unlimited rerolls as long as the user has credits.
  - **Thumbs up/down rating**: inline icons under each style button, toggleable, anonymous-friendly. `POST /api/stencil-rating`. Admin dashboard now shows "Stencil Quality (Thumbs)" card with satisfaction % + per-style breakdown.
  - **Shared lib**: `frontend/app/lib/stencilApi.ts` exports pure API wrappers (`regenerateStencil`, `deductCredit`, `submitStencilRating`, `isFreeRegen`, `regenCostLabel`) so both `main` and `redesign/unified-editor` reuse the same business logic. Integration notes: `/app/memory/REROLL_RATING_BRANCH_NOTES.md`.
  - **Tests**: new `test_reroll_and_rating.py` (6 cases) + `test_iter10_reroll_e2e.py` (4 e2e cases). 31/31 backend regression tests pass including end-to-end verification on the live preview URL.

- **AI Stencil Prompt — final tuning pass (Apr 23 2026)** — user-verified against `/api/prompt-preview` (long-hair female portrait) AND `/api/prompt-preview-alt` (short-hair male portrait) on production. Prompt generalises cleanly across subjects. Prompt in `backend/server.py` (both `/ai-stencil` and `process_stencil_job`) now enforces:
  - Strict FIDELITY: replicate only what's visibly present; no inventing / completing / cleaning up.
  - NO solid black fills anywhere. Pupils + irises are explicitly called out as hollow outlines only (this was the last regression the user flagged).
  - Eyelashes drawn as individual fine hair strokes — never a thick band.
  - LINE WEIGHT rule split: applies **only to continuous solid lines** (eyes/brows/lips/nose/hair flow/silhouette). Dotted/dashed shading guides keep full visible dot size, since thinning them made face-contour dots disappear.
  - Facial contour dotted shading (cheeks, jawline, brow ridges, nose bridge, under eyes, lip volumes) preserved at full density in Heavy.
  - Heavy hair dots now trace **light-to-dark transitions** (highlight-to-shadow boundaries) rather than just outlining highlight regions.
  - Moderate/Heavy intensity ordering corrected — Heavy is visibly denser than Moderate.
  - New one-off script `backend/scripts/generate_preview_stencils.py` regenerates the Medium + Heavy preview PNGs served by `/api/prompt-preview` using the live prompt — used for visual QA passes without needing a TestFlight build.
  - All 25 monetization/paywall regression tests still green after the prompt rewrite.

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
