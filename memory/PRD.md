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
- **CRITICAL: Cache-Key Collision Causing Cross-Reference Image Output (Apr 29 2026)** 🔴🔴🔴
  - **Bug:** A user reported the AI returning a stencil from an UNRELATED reference photo. Two separate failures + a wrong-image return in one session.
  - **Root cause:** `get_cache_key(image_base64, style)` hashed only the **first 1000 base64 characters** of the image with MD5. JPEG/PNG headers, EXIF, and quantization tables on phone photos are similar enough that two unrelated photos can collide on this prefix. When that happened, the cache returned user A's stencil for user B's unrelated reference photo. The async job path (UUID-keyed) was clean — collision was 100% in the cache.
  - **Fix:** `hash_image()` now SHA-256s the FULL base64 payload (data-URL prefix stripped). `get_cache_key()` is `sha256(image_hash + "_" + style)`. Collision is mathematically impossible.
  - **Audit logging added (3 structured log lines per request):** `[AI-Stencil:REQ id=...]` on receipt, `[AI-Stencil:CACHE_HIT id=...]` on cache return, `[AI-Stencil:RESP id=...]` on fresh generation. Each line includes correlation_id, user_id, request image_sha (16-char), cache_key, response image_sha, and provider/latency. Any future "wrong image" report can be cross-referenced against these to forensically prove the input/output correlation.
  - **Tests:** `tests/test_cache_key_collision.py` — 4/4 pass:
    - Two images with shared 1000-char prefix → distinct cache keys (the exact bug)
    - Same image, same style → identical cache key (cache still works)
    - Same image, different styles → 3 distinct keys (style isolation)
    - `data:image/png;base64,` prefix stripped before hashing (client-format-tolerant)
  - **Total regression suite:** 15/15 pass.

- **Critical Bug Fix: Subscription Upgrade (Walk-In → Booked-Out) Not Applying (Apr 27 2026)** 🔴
  - **Bug:** Marilynn (real Apple ID purchase) upgraded Walk-In → Booked-Out via Apple Settings → Subscriptions. App stayed on Walk-In/125 credits even after sign-out/sign-in.
  - **Root cause #1 — Webhook handler:** `/api/webhooks/revenuecat` only branched on `event_type in ('INITIAL_PURCHASE', 'RENEWAL')`. `PRODUCT_CHANGE` (upgrade/downgrade) and `UNCANCELLATION` events fell through to a no-op `return {'status':'ok'}` — no state update.
  - **Root cause #2 — Frontend:** `syncRevenueCatWithBackend` was only called on cold-start. If the user upgraded in iOS Settings while app was backgrounded, foregrounding back didn't re-sync.
  - **Fix #1 (backend):** `event_type in ('INITIAL_PURCHASE', 'RENEWAL', 'PRODUCT_CHANGE', 'UNCANCELLATION')` now all route through `apply_paid_subscription_state`. Logged `[RevenueCat:PRODUCT_CHANGE] APPLIED ...`. Unknown product_ids still refuse with `{'reason':'unknown_product'}` and preserve existing state.
  - **Fix #2 (frontend):** Added `AppState.addEventListener('change')` in `index.tsx`. On `active` transition, calls `syncRevenueCatWithBackend(token)` if a session token exists. Throttled to once per 10s to protect against rapid bg/fg toggling.
  - **Note on idempotency:** The earlier FRONTEND_SYNC idempotency fix (compare TIER not product_id) correctly allows tier changes through — confirmed in regression tests. Walk-in → booked-out fires the apply path even via FRONTEND_SYNC.
  - **Verified live (3/3):** PRODUCT_CHANGE walk-in→booked-out → 500 credits / consumed=0 / last_event=PRODUCT_CHANGE; unknown product refused with state preserved; UNCANCELLATION fully restores.

- **Tier-Segmented Analytics (Apr 26 2026 — late evening)** ✅
  - Extracted `_aggregate_stencil_sessions(sessions)` as a pure helper.
  - `GET /api/admin/stencil-analytics` now returns a `by_tier` slice with three buckets: `walk-in`, `booked-out`, `shop`. The `shop` bucket folds `the-shop` + `the-shop-member` together (studio members exhibit the same paid-tier behavior as Shop owners). Each bucket has the same shape as the top-level (`total_sessions`, `per_style`, `totals`).
  - Verified live with a 5-session multi-tier smoke test — bucketing, fold-in, and per-bucket math all correct. Test data even reveals the hypothesized pattern: Walk-In sticks with Light at 0 rerolls, Booked-Out switches to Heavy at 2 rerolls, Shop tolerates 5 rerolls on Heavy.

- **Observability + Analytics Layer (Apr 26 2026 — late afternoon)** ✅
  - **Unmatched RC webhook rolling buffer.** `db.unmatched_webhooks` now caps itself at 100 entries — after every insert, the oldest beyond the cap are pruned. Lightweight observability without admin-UI overhead.
  - **Stencil usage analytics.** New collection `db.stencil_sessions`, one doc per photo-flow session with: `styles_generated`, `reroll_counts` per style, `style_switches`, `final_style`, `saved`, `exported`, `user_tier`.
    - Public ingest: `POST /api/analytics/session-event` accepts `{session_id, event, style?, user_tier?}` where event ∈ `{generate, reroll, style_switch, save, export}`. Anonymous-friendly, fire-and-forget.
    - Admin aggregation: `GET /api/admin/stencil-analytics?days=30` returns per-style metrics (generated, final_style_count, final_style_pct, avg_rerolls_when_final, switched_away_pct, save_rate_when_final_pct) + totals (saves, exports, save_rate_pct, avg_style_switches).
  - **Frontend instrumentation** (`recordSessionEvent` helper in `lib/stencilApi.ts`): hooks at 5 sites in `index.tsx` — `generate` + `style_switch` in `generateSingleStyle`, `reroll` in `regenerateSingleStyle`, `save` in the gallery save handler, `export` in `shareStencil`. Session id refreshed on first style of each new photo flow. All non-blocking, never throws.
  - **Verified live (4-session smoke test):** math correct on all dimensions — final-style %, switched-away %, avg rerolls, save/export rates, avg switches. Test script: `backend/tests/manual_analytics_aggregation_curl.py`.

- **Hot Fix: Credit Reset Returned + Edit-Mode Erase Doesn't Save (Apr 26 2026 — late evening)** 🔴🔴
  - **Credit reset bug RECURRED post-deploy.** Bryan reported credits refilling to 125 on TestFlight update again.
  - **Root cause:** `PRODUCT_CREDIT_MAP` exposes multiple `product_id` aliases for each tier (`'01'` App Store short-code + `'bodybound_1499_1m_3d'` legacy RC package id, both → walk-in). The earlier idempotency check compared `existing_sub.last_product_id == incoming product_id` — when the iOS RC client sent one alias and the DB had the other, the check returned False and fell through to the full credit-reset path.
  - **Fix:** Drop product_id from the idempotency comparison; compare TIER + trial state only. Same tier + same trial state = idempotent regardless of which product_id alias the client sends. Added a structured `[PaidState] Resync-check` log line so this kind of mismatch is debuggable from production logs.
  - **Regression test:** `test_frontend_sync_idempotent_across_product_id_aliases` — seeds DB with `bodybound_1499_1m_3d`, sync arrives with `'01'`, asserts credits preserved.
  - All 6 sync idempotency tests pass.

  - **Edit-mode erase doesn't persist** (separate frontend bug):
    - **Root cause:** `saveEditedStencil` had an early-return guard `if (drawingPaths.length === 0 && dotMarks.length === 0) return` — when a user opened edit mode with prior edits and erased all of them, drawingPaths was empty so the guard fired and the function did nothing. Main screen kept showing the old captured edits.
    - **Fix:** Empty canvas + `isEditedStencil = true` now means "user erased all edits" — restore the original AI base stencil (`stencilVersions[selectedVersion]` or `originalAIStencil`) to the main screen, clear `isEditedStencil`. Empty canvas with no prior edits is still a no-op close.
    - **Test:** Code-review verified; needs TestFlight build for end-to-end validation.

- **P2 Reroll Idempotency + P3 RC Webhook Dedup (Apr 26 2026)** ✅
  - **P2 — Reroll Idempotency.** `/api/credits/deduct` now accepts an optional `reroll_id` body field. Duplicate calls with the same `(user_id, reroll_id)` within 24h return the cached response without re-deducting; concurrent in-flight duplicates get HTTP 409. Backed by `db.credit_deduct_idempotency` collection with TTL=24h. Frontend `regenerateSingleStyle` and `generateSingleStyle` each generate a per-intent UUID and pass it through `deductCredit(API_URL, token, rerollId)`. Protects against rapid double-tap on the regenerate button.
  - **P3 — RevenueCat Webhook event.id dedup.** Webhook handler now stores each unique `event.id` in `db.revenuecat_webhook_events` (TTL=30d). Replays return `{status: 'ok', duplicate: true, event_id: ...}` without re-applying paid state. This closes the same class of vulnerability as the FRONTEND_SYNC fix — webhook replays of `INITIAL_PURCHASE` / `RENEWAL` would otherwise reset `credits_consumed_this_cycle` to 0 mid-cycle.
  - **Verification:** 5/5 end-to-end curl tests pass against running backend (`/app/backend/tests/manual_idempotency_dedup_curl.py`):
    - P2: same reroll_id → one deduction
    - P2: distinct reroll_ids → each charges
    - P2: no reroll_id → backwards-compat (charges every time)
    - P3: CANCELLATION replay → returns duplicate=True
    - P3: RENEWAL replay → does NOT reset credits

- **Critical Bug Fix: FRONTEND_SYNC Credit Reset on App Cold-Start (Apr 26 2026)** 🔴
  - **Bug:** Every iOS app cold-start (and TestFlight update) reset users' `available_credits` to the tier base (Walk-In → 125, Booked-Out → 500, The Shop → 1500) and zeroed their `credits_consumed_this_cycle`. Users got their entire monthly allotment refilled on every app launch.
  - **Root cause:** `/api/subscription/sync` calls `apply_paid_subscription_state(source='FRONTEND_SYNC')`, which unconditionally wrote `available_credits = tier_info['credits']` and `credits_consumed_this_cycle = 0`. Same writer is used by webhook events (`INITIAL_PURCHASE` / `RENEWAL`) where that reset IS correct.
  - **Fix:** Added an idempotent-resync guard at the top of `apply_paid_subscription_state`. When `source == 'FRONTEND_SYNC'` AND existing sub already has the same `tier` + `last_product_id` + `is_trial`, only `last_event`, `last_applied_at`, and `revenuecat_customer_id` are updated — credits and consumed counter are preserved. Genuine state transitions (tier upgrade via FRONTEND_SYNC, all webhook events, ADMIN paths) take the full apply path unchanged.
  - **Regression suite:** `tests/test_sync_idempotency.py` — 5/5 pass:
    - `test_frontend_sync_preserves_credits_when_tier_unchanged` (the exact bug)
    - `test_frontend_sync_resets_credits_on_tier_change` (genuine upgrade still works)
    - `test_initial_purchase_still_resets_credits` (webhook unchanged)
    - `test_renewal_still_resets_credits` (webhook unchanged)
    - `test_frontend_sync_resets_credits_when_trial_state_flips` (trial→paid transition)
  - **User impact:** Users who lost balance to this bug need a manual admin credit grant on production once they report a number. Fix prevents future occurrences.

- **Pre-Deploy Polish Batch (Apr 25 2026)** — shipped together:
  - **Edits-applied badge** — gold "✏️ EDITS APPLIED" pill, top-right of main preview. Visible only when `isEditedStencil` is true and user isn't holding Compare. Auto-clears when a fresh AI stencil replaces the edited one.
  - **Auto-retry on generation failures** — 4 Alert dialogs (`Regeneration Failed`, `Generation Failed` (start), `Generation Issue`, `Connection Issue`, `Generation Failed` (poll)) replaced OK-only with `Cancel` + `Try Again`. Try Again reinvokes the correct generator (`generateSingleStyle(style)` or `regenerateSingleStyle(style)`). Credit deduct only happens on success, so retry is safe from double-charge.
  - **Cache-hit `near_black_fraction` fix** — `cache_stencil(key, b64, nbf)` now persists near_black_fraction alongside bytes; cache hits echo the value back instead of `null`. Verified via curl: call 1 (miss, 23.1s) and call 2 (hit, 0.0s) both returned `near_black=0.0184`.

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
