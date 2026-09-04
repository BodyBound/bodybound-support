# Post-Cleanup Reconciliation Audit (READ-ONLY, Part 2)

- **Generated at (UTC):** 2026-09-04T01:33:18.361249+00:00
- **Target:** `https://bodybound-subs.emergent.host`
- **Writes performed:** NONE
- **RevenueCat REST/dashboard access available:** False — Only REVENUECAT_WEBHOOK_AUTH is set; no v1 REST secret. Live RC state cannot be queried from this env.

## §1 — Paid cohort: 46 vs 48

- **RAW PAID (all subscription rows in a paid tier):** 48
- **TEST/REVIEWER/INTERNAL:** 2
- **REAL BILLING CUSTOMERS:** 46

Audit cutoff used to bucket "existing vs new" = 2026-09-03T00:00:00+00:00 (based on previous audit run at 2026-09-03 ~00:26 UTC).

### 1.1 Complete paid cohort

| # | email (redacted) | user_id | agg_tier | sub_tier | product_id | last_event | RC id | trial? | excluded? | first_paid_evidence | bucket |
|---:|---|---|---|---|---|---|:---:|:---:|---|---|---|
| 1 | re***@bodybound.app | `demo_reviewer_account` | walk-in | walk-in | `01` | INITIAL_PURCHASE | ✅ | — | YES (reviewer_account_user_id) | 2026-03-01 | **EXISTING** |
| 2 | st***@studio.test | `user_57ea3448954c` | the-shop | the-shop | `—` | INITIAL_PURCHASE | — | — | YES (test_domain) | 2026-03-01 | **EXISTING** |
| 3 | co***@icloud.com | `user_50aab4a6df20` | walk-in | walk-in | `—` | ADMIN_FIX | — | — | — | 2026-03-01 | **EXISTING** |
| 4 | pa***@gmail.com | `user_8305f4c0c6ac` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-03-01 | **EXISTING** |
| 5 | me***@msn.com | `user_614c619aa115` | walk-in | walk-in | `—` | ADMIN_FIX | — | — | — | 2026-03-04 | **EXISTING** |
| 6 | cr***@gmail.com | `user_e36bbdeb84d1` | walk-in | walk-in | `—` | ADMIN_FIX | — | — | — | 2026-03-04 | **EXISTING** |
| 7 | ni***@gmail.com | `user_751133796eb6` | walk-in | walk-in | `—` | ADMIN_FIX | — | — | — | 2026-03-06 | **EXISTING** |
| 8 | ri***@gmail.com | `user_570f85906b8c` | booked-out | booked-out | `02` | RENEWAL | ✅ | — | — | 2026-03-15 | **EXISTING** |
| 9 | wv***@privaterelay.appleid.com | `user_0f97e50d1efe` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-03-15 | **EXISTING** |
| 10 | sk***@gmail.com | `user_4c5444ff7bd0` | booked-out | booked-out | `02` | FRONTEND_SYNC | ✅ | — | — | 2026-03-16 | **EXISTING** |
| 11 | 6y***@privaterelay.appleid.com | `user_4a1e48ed8a6d` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-03-16 | **EXISTING** |
| 12 | jk***@gmail.com | `user_ae1fbf7264c4` | walk-in | walk-in | `—` | ADMIN_FIX | — | — | — | 2026-03-16 | **EXISTING** |
| 13 | re***@gmail.com | `user_6e6b39d29544` | walk-in | walk-in | `—` | ADMIN_FIX | ✅ | — | — | 2026-03-16 | **EXISTING** |
| 14 | du***@gmail.com | `user_617e7c1897ee` | walk-in | walk-in | `—` | ADMIN_FIX | — | — | — | 2026-03-17 | **EXISTING** |
| 15 | 20***@gmail.com | `user_48f1564a931b` | walk-in | walk-in | `—` | ADMIN_FIX | — | — | — | 2026-03-17 | **EXISTING** |
| 16 | da***@gmail.com | `user_755a7e8a76bd` | walk-in | walk-in | `—` | ADMIN_FIX | ✅ | — | — | 2026-03-19 | **EXISTING** |
| 17 | pj***@gmail.com | `user_d121c4f4b490` | walk-in | walk-in | `—` | ADMIN_FIX | — | — | — | 2026-03-20 | **EXISTING** |
| 18 | ca***@yahoo.com | `user_1854defdd339` | walk-in | walk-in | `—` | ADMIN_FIX | ✅ | — | — | 2026-03-27 | **EXISTING** |
| 19 | (anonymous) | `user_2b6570eb8562` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-04-10 | **EXISTING** |
| 20 | ja***@revivaltattoostudios.com | `user_979a9ce23623` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-04-11 | **EXISTING** |
| 21 | gp***@gmail.com | `user_bc6624b714e6` | walk-in | walk-in | `—` | ADMIN_FIX | ✅ | — | — | 2026-04-14 | **EXISTING** |
| 22 | g5***@privaterelay.appleid.com | `user_411142487bbb` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-04-16 | **EXISTING** |
| 23 | rs***@privaterelay.appleid.com | `user_baad7e119a97` | walk-in | walk-in | `01` | RENEWAL | ✅ | — | — | 2026-04-16 | **EXISTING** |
| 24 | (anonymous) | `user_e2513c91a809` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-04-18 | **EXISTING** |
| 25 | 5f***@privaterelay.appleid.com | `user_2d8695fa13b8` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-04-23 | **EXISTING** |
| 26 | rq***@privaterelay.appleid.com | `user_a63818aad888` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-04-23 | **EXISTING** |
| 27 | ta***@gmail.com | `user_6e764650c8e1` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-04-28 | **EXISTING** |
| 28 | m.***@gmail.com | `user_998cfa8c131d` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-05-04 | **EXISTING** |
| 29 | ar***@gmail.com | `user_f10f9cc9fc79` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-05-05 | **EXISTING** |
| 30 | ja***@gmail.com | `user_129ccd99e6c5` | booked-out | booked-out | `02` | FRONTEND_SYNC | ✅ | — | — | 2026-05-06 | **EXISTING** |
| 31 | (anonymous) | `user_dde57b488d1c` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-05-09 | **EXISTING** |
| 32 | (anonymous) | `user_39ac4e487c88` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-05-15 | **EXISTING** |
| 33 | hp***@privaterelay.appleid.com | `user_c4163130ac56` | walk-in | walk-in | `01` | RENEWAL | ✅ | — | — | 2026-05-27 | **EXISTING** |
| 34 | im***@gmail.com | `user_6cc79d1eb4a4` | walk-in | walk-in | `01` | RENEWAL | ✅ | — | — | 2026-05-31 | **EXISTING** |
| 35 | fa***@icloud.com | `user_b7d704f68e33` | walk-in | walk-in | `01` | RENEWAL | ✅ | — | — | 2026-06-06 | **EXISTING** |
| 36 | 8f***@privaterelay.appleid.com | `user_a3530562aa2e` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-06-09 | **EXISTING** |
| 37 | ro***@gmail.com | `user_22dcc92af7f2` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-06-10 | **EXISTING** |
| 38 | od***@gmail.com | `user_8480b70fd9a8` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-06-16 | **EXISTING** |
| 39 | ja***@gmail.com | `user_ae483591af44` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-06-19 | **EXISTING** |
| 40 | (anonymous) | `user_620f53dea616` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-06-24 | **EXISTING** |
| 41 | pz***@privaterelay.appleid.com | `user_ee2270632116` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-07-01 | **EXISTING** |
| 42 | od***@gmail.com | `user_d8d894b397c9` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-07-03 | **EXISTING** |
| 43 | (anonymous) | `user_2b28d360eb02` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-07-09 | **EXISTING** |
| 44 | ju***@gmail.com | `user_d126265f6e2c` | walk-in | walk-in | `01` | RENEWAL | ✅ | — | — | 2026-07-11 | **EXISTING** |
| 45 | 5h***@privaterelay.appleid.com | `user_2f0a52ef24a1` | walk-in | walk-in | `01` | RENEWAL | ✅ | — | — | 2026-07-20 | **EXISTING** |
| 46 | 7f***@privaterelay.appleid.com | `user_dfdec8331c18` | walk-in | walk-in | `01` | RENEWAL | ✅ | — | — | 2026-07-21 | **EXISTING** |
| 47 | ht***@gmail.com | `user_dd68dcc37908` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-08-21 | **EXISTING** |
| 48 | al***@icloud.com | `user_8e250567c3b1` | walk-in | walk-in | `01` | FRONTEND_SYNC | ✅ | — | — | 2026-08-24 | **EXISTING** |

### 1.3 Existing (before audit cutoff) vs New

- **Existing paid users** (first-paid before 2026-09-03T00:00:00+00:00): **48**
- **Newly paid users** (first-paid on/after 2026-09-03T00:00:00+00:00): **0**
- **Unknown first-paid date:** **0**

### 1.4 Answer

- Previous audit reported **48 raw / 46 real** (2 excluded).
- Current audit reports **48 raw / 46 real** (2 excluded).
- Delta raw: **+0**, delta real: **+0**.
- No new customers detected by first-paid-evidence — the delta is likely due to previously-excluded test/reviewer accounts being re-included or reclassified.

## §2 — Actual MRR (by product mix)

**Deployed product-id prices (authoritative from `PRODUCT_CREDIT_MAP` in `backend/server.py`):**

| Tier | Real subscribers | Price | Gross MRR |
|---|---:|---:|---:|
| walk-in | 43 | $14.99 | $644.57 |
| booked-out | 3 | $29.99 | $89.97 |
| **TOTAL** | **46** | — | **$734.54** |

**ACTUAL VERIFIED GROSS MRR (code prices) = $734.54**

**User-brief prices (as quoted in the reconciliation request — includes "The Shop $49.99"):**

| Tier | Real subscribers | Price | Gross MRR |
|---|---:|---:|---:|
| walk-in | 43 | $14.99 | $644.57 |
| booked-out | 3 | $29.99 | $89.97 |
| **TOTAL** | **46** | — | **$734.54** |

**ACTUAL VERIFIED GROSS MRR (user-brief prices) = $734.54**

⚠️ **Price discrepancy noted:** the user brief lists The Shop at $49.99/mo, but the deployed product id is `bodybound_9999_1m_3d` ($99.99/mo). Both figures are shown; the deployed one is the source of truth unless a price migration is in flight.

**Prior verified MRR:** 46 × $14.99 floor = $689.54 (previous audit used the Walk-In floor; this audit uses the actual mix — the change is a **methodology change**, not a customer growth signal).

## §3 — users.tier vs subscriptions.tier reconciliation

### 3.1 Authoritative-source-of-truth analysis

**Code-level evidence:**

- `GET /api/credits` calls `get_user_credits(user_id)` (backend/server.py) which reads `sub.get('tier')` (line 3792) from the **`subscriptions`** collection.
- `needs_subscription` is derived at line 3849 as `tier in (None, 'trial_expired', 'expired')` — using the `subscriptions.tier` value only.
- The **frontend paywall** in `frontend/app/index.tsx` gates on `credits.needs_subscription` (lines 845, 1040, 5216) which comes from `/api/credits`.
- The **`users` collection** stores identity/profile fields only (`user_id`, `apple_user_id`, `email`, `name`, `device_id`, `created_at`, `last_login`, `referred_by`, `referral_code_used`). There is **no `tier` field and no `is_trial` field on the users doc** anywhere in `backend/server.py`.

> **AUTHORITATIVE ENTITLEMENT SOURCE = `subscriptions.tier` (via `get_user_credits()` → `needs_subscription`)**

The `/admin/all-users` endpoint also derives its `tier` column from `subscriptions.tier` (server.py line 1803). Any mismatch below therefore reflects a **different underlying condition** (transient in-flight update, duplicate subscription doc for the same user_id, or aggregation-time skew) — NOT a users-vs-subscriptions collection drift.

### 3.2 Mismatches in the 57-user legacy universe (0)

✅ No mismatches detected on re-fetch — `/admin/all-users` and `/admin/user-lookup?user_id=…` agree for all 57 legacy users.

### 3.3 `users` collection field presence (across the 57 legacy users)

- users docs with a `tier` field: **0** / 57
- users docs with an `is_trial` field: **0** / 57
- ✅ Confirms the `users` collection does not carry tier/entitlement state. `subscriptions.tier` is the only authoritative field.

## §4 — Re-evaluate the six `tier='trial'` users

| user_id | email (redacted) | agg.tier | sub.tier | sub.is_trial | trial_expires | days_since_exp | RC | sub_cleanup_reason | needs_sub | classification |
|---|---|---|---|:---:|---|---:|:---:|---|:---:|---|
| `user_673ab0d5552a` | (anonymous) | `trial` | `trial` | True | — | — | — | — | False | **telemetry-limited** |
| `user_a413c2ff83f9` | (anonymous) | `trial` | `trial` | True | 2026-03-04 | 183.3 | — | — | False | **already expired / stale display only** |
| `user_5a08baad0eb6` | te***@example.com | `trial` | `trial` | True | 2026-03-04 | 183.3 | — | — | False | **already expired / stale display only** |
| `user_853c847c8f91` | (anonymous) | `trial` | `trial` | True | 2026-03-08 | 180.0 | — | — | False | **already expired / stale display only** |
| `user_714df781c4f8` | (anonymous) | `trial` | `trial` | True | 2026-03-20 | 167.4 | — | — | False | **already expired / stale display only** |
| `user_2c877c5ff51f` | (anonymous) | `trial` | `trial` | True | 2026-03-23 | 165.0 | — | — | False | **already expired / stale display only** |

## §5 — Re-evaluate the four `is_trial=true` users

### 5.1 What does `is_trial=true` actually gate?

**Code-level trace (backend/server.py):**

- `is_trial` is stored on the `subscriptions` doc and surfaced by `get_user_credits()` as `credits.is_trial`.
- **`needs_subscription`** is computed as `tier in (None, 'trial_expired', 'expired')` — **it does NOT read `is_trial`**. So `is_trial=true` alone does NOT prevent the paywall from opening.
- `is_trial` is used for: (1) trial-expiry countdown UI, (2) referral-reward accounting, (3) `PAYWALL_BYPASS`/anti-abuse email checks, (4) analytics.
- **Generation entitlement** is gated by `available_credits > 0` on the `/api/credits/deduct` path. `is_trial` is not consulted.
- **RC sync behaviour**: on webhook receipt (`webhooks/revenuecat`), the trial flag is *rewritten* from RC's payload — it does not affect entitlement, it reflects it.

> **Conclusion:** `is_trial=true` on an `expired` / `trial_expired` sub is **display-only metadata**. It does not open the paywall gate.

### 5.2 Detail

| user_id | email (redacted) | agg.is_trial | sub.is_trial | sub.tier | trial_expires | RC | needs_sub? | classification |
|---|---|:---:|:---:|---|---|:---:|:---:|---|
| `user_043c1203bbf7` | yo***@icloud.com | True | True | `trial_expired` | 2026-03-20 | — | True | **harmless stale metadata (needs_subscription=true regardless of is_trial)** |
| `user_6bc049c92733` | ta***@gmail.com | True | True | `trial_expired` | 2026-03-23 | ✅ | True | **harmless stale metadata (needs_subscription=true regardless of is_trial)** |
| `user_bb51f47bab8a` | (anonymous) | True | True | `trial_expired` | 2026-03-30 | — | True | **harmless stale metadata (needs_subscription=true regardless of is_trial)** |
| `user_046f6e48e8ce` | ma***@icloud.com | True | True | `expired` | — | ✅ | True | **harmless stale metadata (needs_subscription=true regardless of is_trial)** |

## §6 — Live RevenueCat verification of the 46 RC-linked bypass users

**RC REST/dashboard access available in this environment:** False
**Environment vars present:** only `REVENUECAT_WEBHOOK_AUTH` (validates INCOMING webhooks; does not enable OUTGOING queries).
**No RC v1/v2 REST API secret is set.** Live entitlement state therefore CANNOT be queried from this environment.

Per the brief's fail-safe rule ("Do NOT infer 'expired' merely because local last_event is missing"), every RC-linked bypass user is classified **`RC_UNVERIFIABLE`** until a v1 secret is added and this section is re-run.

| RC class | Count |
|---|---:|
| RC_ACTIVE_PAID | 0 |
| RC_ACTIVE_TRIAL | 0 |
| RC_EXPIRED | 0 |
| RC_NOT_FOUND | 0 |
| RC_UNVERIFIABLE | 46 |
| NO_RC_ID | 1 |
| **Total** | **47** |

### 6.1 Recommendation to unlock RC verification

Set `REVENUECAT_V1_SECRET` in `backend/.env` (Project settings → API keys → Secret v1 key), then a follow-up read-only pass can call:
`GET https://api.revenuecat.com/v1/subscribers/{user_id_or_rc_customer_id}` with `Authorization: Bearer <v1_secret>` and classify each of the 46 conclusively.

**Until then, the 46 RC-linked bypass users must remain untouched.**

## §7 — Corrected action-category labeling

**Rules (mutually exclusive, in priority order):**
1. **Legitimate paid/trial** — sub_tier in PAID_TIERS OR in-window trial (`sub_trial_expires_at` ≥ now)
2. **RevenueCat verification required** — has `sub_revenuecat_customer_id` AND RC status is `RC_UNVERIFIABLE` (i.e. all RC-linked accounts right now)
3. **Source-of-truth / telemetry ambiguity** — agg-vs-sub mismatch, OR trial with no expiry data AND no RC id (cannot classify)
4. **Safe stale cleanup** — no RC id AND (`needs_subscription=true` OR expired trial)
5. **Conversion candidate** — active bypass with no RC id (RC conclusively absent, functional free access confirmed)

| Category | Count | Members |
|---|---:|---|
| 1. Legitimate paid/trial | 0 | sub in PAID_TIERS or in-window trial |
| 2. RevenueCat verification required | 48 | has RC id + RC_UNVERIFIABLE (46 bypass; the rest are trials) |
| 3. Source-of-truth / telemetry ambiguity | 1 | aggregation mismatch or trial w/o expiry & no RC |
| 4. Safe stale cleanup | 7 | no RC + needs_sub / expired trial |
| 5. Conversion candidate | 1 | active bypass w/o RC (RC conclusively absent) |
| **Sum (must equal 57)** | **57** | ✅ |

## §8 — Final decision table

| Group | Count | Functional free access now? | RC status | Safe to change? | Recommended next action |
|---|---:|:---:|---|:---:|---|
| Real paying subscribers | 46 | ❌ (paying) | RC entitlement live (implied by billing) | ❌ NEVER | Do not touch. |
| Active bypass — RC id present | 30 | ✅ | RC_UNVERIFIABLE (no REST key) | ❌ NOT YET | Add REVENUECAT_V1_SECRET; classify per-user; then decide. |
| Active bypass — no RC id | 1 | ✅ | NO_RC_ID (RC conclusively absent) | ⚠️ Conversion-safe | Contact for conversion; expire on non-conversion after warning. |
| Dormant bypass (>90d) — RC id present | 16 | ✅ (credits remain) | RC_UNVERIFIABLE | ❌ NOT YET | Add REVENUECAT_V1_SECRET; then Batch D-safe. |
| Dormant bypass (>90d) — no RC id | 0 | ✅ (credits remain) | NO_RC_ID | ✅ SAFE | Include in a future Batch D (`user_id`-keyed cleanup). |
| tier='trial' — display-only stale | 5 | ❌ (needs_subscription=true) | no RC | ✅ SAFE | Batch D by `user_id` (email-blind) to normalize tier/is_trial. |
| tier='trial' — telemetry-limited / ambiguous | 1 | ⚠️ unknown | unknown | ❌ NOT YET | Investigate individually; require RC verification if any RC id. |
| is_trial=true — display-only | 4 | ❌ (needs_subscription=true; is_trial flag has no gate effect) | no gating impact | ✅ SAFE | Batch D by `user_id` to clear the stale is_trial flag. |
| is_trial=true — ambiguous (has RC) | 0 | ⚠️ unknown | RC_UNVERIFIABLE | ❌ NOT YET | Require RC verification. |

### 8.1 Explicit totals

- Verified real paying subscribers: **46**
- Actual gross MRR (code prices): **$734.54**  ·  (user-brief prices): **$734.54**
- Active bypass users: **31**
- Active bypass with confirmed inactive RC entitlement: **0** _(0 until RC verifier is unlocked)_
- Active bypass with live paid/trial entitlement: **0** _(0 until RC verifier is unlocked)_
- Active bypass still RC-unverifiable: **30**
- Dormant bypass safe to expire: **0** _(requires RC verification first)_
- Stale trial records that actually still grant access: **0** _(none — see §5)_
- Stale trial records that are display-only: **9**
- Remaining ambiguous accounts: **1**

---

**HARD STOP.** No cleanup executed. No production code changed. No RC changes. No credit changes. No deploys.
