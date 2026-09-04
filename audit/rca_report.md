# Root Cause Audit — Why 5 Expired Trials Remained `tier='trial'` (READ-ONLY)

**Generated:** 2026-09-04 · **Target:** production data (read-only) · **Writes:** NONE

---

## 1. Full expiration control-flow trace

The natural-expiration mutation lives in `get_user_credits()` at `backend/server.py:3736-3855`. Order of operations:

```
async def get_user_credits(user_id: str) -> dict:
  L3740  await maybe_redeem_referral_month(user_id)   # side-effect only, wrapped in try/except
  L3744  sub = await db.subscriptions.find_one({'user_id': user_id})   # SINGLE FETCH
  L3745  if not sub:
           return {'available_credits': 0, 'tier': None, 'is_trial': False, ...}  # EARLY RETURN 1
  L3754  studio_team_id = sub.get('studio_team_id')                              # not our path
  L3766  is_trial = sub.get('is_trial', False)
  L3767  trial_expires_at = sub.get('trial_expires_at')
  L3770  if is_trial and trial_expires_at:                    # <── GATE
  L3771     try:
  L3772        expires_dt = fromisoformat(...)
  L3773        now = datetime.now(timezone.utc)
  L3774        if expires_dt <= now:                          # <── EXPIRED
  L3776           available_credits = 0                       # local var
  L3777           trial_days_remaining = 0
  L3779           await db.subscriptions.update_one(
                    {'user_id': user_id},
                    {'$set': {'available_credits': 0, 'tier': 'trial_expired'}}
                  )
  L3783           logger.info(...)
  L3787     except Exception as e:
  L3788        logger.error(...)                             # <── swallowed
  L3792  tier = sub.get('tier')                              # <── reads STALE in-memory tier
  L3849  'needs_subscription': tier in (None, 'trial_expired', 'expired')
```

### Exact conditions for the expiration branch to execute

**All of the following must hold:**

1. `subscriptions` doc exists for `user_id` (else early return).
2. `sub.is_trial == True` (non-truthy short-circuits at L3770).
3. `sub.trial_expires_at` is present.
4. `sub.trial_expires_at` parses as ISO-8601 (else caught by exception → logged, not raised).
5. `expires_dt <= now`.
6. **`get_user_credits(user_id)` is actually called** (no scheduler wakes it up).

### Ways an expired `tier='trial'` record can avoid reaching L3779

| # | Path | Applies to the 5 Batch D users? |
|---:|---|:---:|
| 1 | `get_user_credits()` never called for this `user_id` — account inactive after signup | **YES** ← this is what happened |
| 2 | `sub.is_trial == False` (flag was cleared out-of-band while `tier='trial'` remained) | No (`is_trial=True` on all 5) |
| 3 | `sub.trial_expires_at is None` (missing) | No (all 5 have valid ISO expiry) |
| 4 | `trial_expires_at` unparseable → caught + logged | No |
| 5 | Studio-team branch short-circuits before L3770 | No (studio_team_id=null) |
| 6 | `db.subscriptions.update_one` fails silently | No (Motor raises on failure, would be caught in caller) |
| 7 | Time-based background sweep expires them proactively | **N/A — no such sweep exists** |

**Bottom line:** the expiration branch is **lazy**. It only runs when a caller invokes `get_user_credits(user_id)`. No cron, no scheduler, no wake-up-on-timer path exists in the codebase.

## 2. Callers of `get_user_credits()` — the "self-heal" surface

### 2.1 Backend routes

| line | route/function | auth | invoked by |
|---:|---|---|---|
| 4095 | `GET /api/auth/me` | JWT required | frontend app-launch + every `refreshCredits()` (7 sites in `index.tsx`) |
| 2471 | `POST /api/ai-stencil` (sync gen soft gate) | JWT (soft) | generation of Light stencil |
| 3040 | `POST /api/ai-stencil-async` (v1 soft gate) | JWT (soft) | Medium/Heavy stencil generation |
| 3342 | `POST /api/ai-stencil-async` v2 (hard gate) | JWT required | Medium/Heavy stencil generation (post-refactor) |
| 6860 | `POST /api/subscription/frontend-sync` | JWT required | RC frontend sync on app cold-start / restore-purchase |
| 6872 | (unreachable — dead code after `return` on L6864, from pre-existing lint issue) | — | never |

### 2.2 Frontend — every `/api/credits` / entitlement fetch

`grep -rEn 'API_URL.*credits|refreshCredits'` in `frontend/app`:

- `refreshCredits(token)` in `index.tsx:947` calls **`GET /api/auth/me`** (NOT `/api/credits` — that route doesn't exist). Invoked at:
  - line 849 — after RC purchase sync
  - line 5215, 5219 — after paywall flow
  - line 5256 — on session restore
  - line 5272, 5348, 5360 — after various user actions
  - `useEffect` mount in main index — on every app foreground/launch

- Generation path (`/api/ai-stencil-async` deduct) — indirectly triggers.
- `POST /api/credits/deduct` — does NOT call `get_user_credits()` internally; only decrements a counter.
- `POST /api/credits/early-access-bridge` — separate paywall-bypass top-up, no expiration effect.
- `POST /api/credits/emergency-stencil` — separate.

### 2.3 Answer to «Does an expired trial normalize automatically with time, or only lazily when the user performs a specific action?»

> **LAZY only.** An expired trial normalizes **only when the user (or a background job on their behalf) invokes an endpoint that calls `get_user_credits()`** — which requires a valid JWT session. Dormant accounts that never return remain stale indefinitely.

There is **no cron, no time-window sweep, no batch job** that iterates dormant subscriptions.

## 3. Historical reconstruction of the 5 Batch D users

| user_id | email | apple_provider | created | trial_start | trial_expiry | days since expiry (@ Batch D) | credits pre-batch | last_event | activity after expiry |
|---|---|---|---|---|---|---:|---:|---|---|
| `user_a413c2ff83f9` | (anonymous) | `apple:test` | 2026-03-01 | 2026-03-01 | 2026-03-04 | 184 | 10 | none | **NONE** — anonymous test seat, never returned |
| `user_5a08baad0eb6` | `test@example.com` | `apple:001234.abcdef` | 2026-03-01 | 2026-03-01 | 2026-03-04 | 184 | 10 | none | **NONE** — likely dev fixture, never returned |
| `user_853c847c8f91` | (anonymous) | `apple:000499…3741b694ebe340ef…1425` | 2026-03-05 | 2026-03-05 | 2026-03-08 | 180 | 10 | none | **NONE** — real anonymous device signup, never returned |
| `user_714df781c4f8` | (anonymous) | `apple:001524…a1997ec6cd0e438e…1519` | 2026-03-17 | 2026-03-17 | 2026-03-20 | 168 | 10 | none | **NONE** — real anonymous device signup, never returned |
| `user_2c877c5ff51f` | (anonymous) | `apple:001071…d87dfd06ac4b4096…1650` | 2026-03-20 | 2026-03-20 | 2026-03-23 | 165 | 10 | none | **NONE** — real anonymous device signup, never returned |

### Evidence

- `available_credits` still `10` at Batch D time — the initial trial grant. **Never consumed a single credit.** In `apply_paid_subscription_state` and `get_user_credits`, credits are only ever decremented via `/api/credits/deduct` (i.e. generation) or refills. **Zero decrements for these 5 → zero generations ever performed.**
- `last_event = None` — no RC webhook (`INITIAL_PURCHASE`, `RENEWAL`, `CANCELLATION`, etc.) ever fired. Also no `PAYWALL_BYPASS`, `ADMIN_*`, `FRONTEND_SYNC` events.
- `revenuecat_customer_id = None` — never opened the RC-linked purchase flow.
- `users.last_login` — never updated past `created_at` (would show a fresh ISO if they'd re-signed in via `apple_sign_in`).

### Critical distinction (per your brief)

> A stale record capable of free access is not necessarily evidence the user actually used free access.

- **Stale record capable of free access:** ✅ all 5. Any of them could have returned, hit `/api/ai-stencil-async` (soft gate), and generated 10 free stencils.
- **Actually exploited free access:** ❌ none. `available_credits` still exactly 10 across the board. Zero generations.

**Conclusion:** these were signup-and-abandon accounts. The stale record was theoretically exploitable but was never actually exploited.

## 4. Git history — the pivotal commits

| commit | date | change | evidence in code |
|---|---|---|---|
| `223861b5` | **2026-03-01** | `create_trial_subscription()` was live: **auto-granted a 3-day, 10-credit trial with `tier='trial'`, `is_trial=True`, `trial_expires_at = now + 3 days` on every Apple sign-in.** `TRIAL_DURATION_DAYS = 3`, `TRIAL_CREDITS = 10`. | matches all 5 Batch D records exactly |
| `c0a882b7` | **2026-03-31 19:38 UTC** | **`create_trial_subscription()` was replaced with `create_initial_subscription()`.** New signups get `tier=None, credits=0` (or `tier='paywall_bypass'` when `TEMP_BYPASS_ENABLED=true`). **No new `tier='trial'` records can be created via this path from 2026-03-31 onward.** | current code L3902-3963 |
| (natural-expiration branch) | pre-2026-03-01 | Already present in `223861b5` at L2835-2854. **Never absent.** | historical + current identical at L3770-3782 |

**Trial signup window that could produce these records:** 2026-03-01 through 2026-03-31 (~30 days). All 5 Batch D users signed up in that window — the pattern fits perfectly.

**Nothing in git history suggests a data-migration was planned or performed** when `create_trial_subscription` was retired. The retirement stopped NEW stale records from appearing but did not clean up EXISTING ones. All records created in the March window that were never revisited by their users survived until Batch D.

## 5. All current trial-creation / restore write paths

Every code path that writes `tier='trial'`, `is_trial=True`, `available_credits=10`, or `trial_expires_at`:

| line | function/route | writes `tier='trial'`? | writes `is_trial=True`? | writes `trial_expires_at`? | can accidentally reactivate an expired user? |
|---:|---|:---:|:---:|:---:|:---:|
| L3947-3963 | `create_initial_subscription()` (Apple/Google new-user signup) | **NO** — writes `tier='paywall_bypass'` or `None` | NO | NO (writes `None`) | ❌ no |
| L3990-4032 | `apple_sign_in` — existing user | NO writes to `subscriptions` at all (only updates `users.last_login`) | NO | NO | ❌ no |
| L4034-4088 | `google_session_exchange` — existing user | same as above | NO | NO | ❌ no |
| L5985-… | `apply_paid_subscription_state()` (RC purchase / webhook / frontend-sync) | NO — writes only tiers from `PRODUCT_CREDIT_MAP` (`walk-in`, `booked-out`, `the-shop`, `the-shop-member`) | writes `is_trial = is_apple_trial` (the Apple free-trial flag) | NO | ❌ no |
| L6259-6273 | `admin/loyalty-bonus` — fallback creates a `tier='trial'` doc **only if the user has no subscription** | **YES** (in this narrow fallback) | YES | NO (writes no expiry — would be an anomalous record) | **⚠️ Admin-gated. Requires an admin manually granting bonus to a user who literally has no subscription doc. Not user-triggerable.** |
| L6291-6303 | `admin/paywall-bypass` | NO — writes `tier='paywall_bypass'` | NO (writes `False`) | NO | ❌ no |
| L6536-6900 | `POST /webhooks/revenuecat` (INITIAL_PURCHASE / RENEWAL / CANCELLATION / EXPIRATION / etc.) | NO — always routes through `apply_paid_subscription_state`, never sets `tier='trial'` | reflects RC's `is_trial_period` | NO (RC-managed trial, not our field) | ❌ no |
| L8110-8130 | trial-reward accounting query (read-only aggregation) | — | — | — | ❌ no |
| L8340-8360 | `admin/cleanup-*` endpoints | NO — writes `tier='expired'` or `tier='trial_expired'` (Batch D endpoint) | NO | NO | ❌ no |

**Result:** on current code, **no user-triggered path can turn an expired user back into `tier='trial'`.** The only remaining trial-creation vector is the `admin/loyalty-bonus` fallback, which requires (a) an admin manually invoking it and (b) the target user having zero subscription documents. Neither can happen to the 5 Batch D users (they had a subscription doc), and neither happens organically.

## 6. Current reproducibility test — preview backend + local Mongo

Script: `/app/audit/rca_reproducer.py`. Fixture-only seeding; no production impact.

| Scenario | Result |
|---|---|
| **A.** Seed dormant expired trial → user hits `/api/auth/me` (JWT-authenticated) | ✅ **DB is correctly normalized:** post-state `tier='trial_expired'`, `available_credits=0`. Natural expiration path fires. |
| **B.** Seed dormant expired trial → no request made | ✅ **DB stays stale:** post-state `tier='trial'`, `available_credits=10`. **Confirms lazy normalization** — no time-based sweep exists. |
| **C.** Simulate fresh Apple sign-in on current code | ✅ **Static analysis proves the current `create_initial_subscription()` can only write `tier='paywall_bypass'` or `None`.** No path today can produce the 5 Batch D shape. |

### 6a. Subtle response-shape defect discovered during Scenario A

Scenario A's `/api/auth/me` response payload — **on the very first call that triggers expiration**:

```json
{ "tier": "trial", "available_credits": 0, "needs_subscription": false, ... }
```

Yet the DB is now `tier='trial_expired'`. The mismatch is because `get_user_credits()` re-reads `tier = sub.get('tier')` from the **in-memory sub dict fetched BEFORE the update** (L3792). On the very next call, `sub.tier` = `'trial_expired'` in DB and the response is correct.

**Impact:** on that single call, the paywall gate (`needs_subscription`) returns `false` even though the trial just expired. However, the generation gate (`available_credits > 0`) correctly returns 0, so generation still fails with "out of credits". Net effect: the user sees "out of credits" but no paywall for ONE call, then everything corrects.

**Not a Batch-D root cause** — those 5 users never made even one call. But it's a real cleanliness defect worth flagging.

## 7. Root-cause classification

### Primary classification: **A. Historical-data artifact** _(dominant)_

Old code (`223861b5` → pre-`c0a882b7`, roughly 2026-03-01 → 2026-03-31) created trial records with `tier='trial'`/`is_trial=True`/`credits=10`/`trial_expires_at=now+3d` on every Apple sign-in. Current code no longer does this. All 5 Batch D records are dated to that exact window.

### Contributing classification: **B. Lazy-normalization design** _(secondary, still active)_

The natural-expiration path is lazy — it only runs when the user hits `/api/auth/me` (or a generation endpoint or `/api/subscription/frontend-sync`). If the user never returns, the record stays stale forever. **This lazy design is by intent** (avoids unnecessary DB churn for dormant users), but combined with the March 1-31 window that auto-created trials on signup, it produced a "silent-death" bucket of records that will never self-heal unless the user comes back.

### Not observed: **C, D, F**

- **C (Current functional defect):** ruled out by Scenario A — the current code correctly normalizes an expired trial as soon as a caller invokes `get_user_credits()`. Every entrypoint that reads entitlement calls it. There is a minor cosmetic bug in the response shape on the very first call after expiration (§6a) but it does not affect the paywall persistently.
- **D (Reactivation defect):** ruled out by §5 — no user-triggered path can restore `tier='trial'` on an expired user.
- **F (Insufficient evidence):** the code history and per-account fingerprints (identical 3-day trial shape, matching March 2026 window, zero credits consumed, zero events) are conclusive.

### Not applicable: **E (Mixed cause)**

A + B is technically a mix, but they operate at different layers (data provenance vs runtime behavior), not conflicting causes. The retired trial-creation path deposited the records; the still-active lazy expiration failed to clear them because the accounts were dormant.

## 8. Present-day risk assessment

| # | Question | Answer | Evidence |
|---:|---|---|---|
| 1 | Can a new trial started today get stuck this way? | **NO** | Current `create_initial_subscription()` (L3902) writes `tier='paywall_bypass'` or `None`; never `'trial'`. `create_trial_subscription()` was deleted at commit `c0a882b7` (2026-03-31). |
| 2 | Can an inactive expired trial remain stale forever? | **YES — for as long as the user is dormant** | §6 Scenario B. No time-based sweep. Only self-heals on the user's next authenticated request. |
| 3 | Can a user actually generate after expiration without triggering normalization? | **NO** — generation endpoints (sync, async v1, async v2) each call `get_user_credits()` before deducting credits (L2471, L3040, L3342). The natural-expiration side-effect fires on the same call that would authorize the generation, and the returned `available_credits=0` blocks it. | Grep at §2.1 |
| 4 | Can a user see the app as subscribed after expiration without hitting `/api/credits`? | **Practically NO.** The app's frontend calls `/api/auth/me` on every foreground/launch (`index.tsx:947` `refreshCredits`), which triggers `get_user_credits()`. A user cannot open the app without that firing. **Exception:** on the *very first* post-expiration call, the response returns `tier='trial'` from the in-memory dict even though the DB was just updated — see §6a. Persists for exactly one call; corrected on the next request. | §6a |
| 5 | Can an expired trial be accidentally recreated? | **NO** via any user-triggered path. **Only** via admin `admin/loyalty-bonus` fallback when the target has NO subscription doc (§5). | §5 table |
| 6 | Reason to believe more hidden `tier='trial'` records exist outside the known universe? | **NO** — the reconciliation audit (`/app/audit/reconciliation.py`) enumerates every `subscriptions` doc with `tier='trial'` in production. Post-Batch-D, the count is exactly **1** (the intentionally-preserved `user_673ab0d5552a` ambiguous 6th). If additional dormant `tier='trial'` records existed they would have surfaced. | §4 of `reconciliation_report.md` — `remaining_tier_trial: 1` |

## 9. Recommendation

### **NO CODE FIX REQUIRED — HISTORICAL/LAZY DATA ONLY**

Optional hardening (not required for correct entitlement enforcement):

1. **§6a cosmetic cleanup (low priority)** — inside `get_user_credits()` (L3792), after the DB update fires, refresh the local `tier` from the target value:
   ```python
   # After L3782 update:
   sub['tier'] = 'trial_expired'
   sub['available_credits'] = 0
   ```
   This closes the one-call response-shape mismatch. Smallest safe conceptual fix. Zero behavior change from the SECOND call onward. **DO NOT IMPLEMENT — flagged only.**

2. **Optional operational improvement (low priority)** — a small idempotent read-only cron that logs (not mutates) any `subscriptions` doc where `tier='trial' AND is_trial=true AND trial_expires_at < now - 7d`. If the number is ever > 0, alarm — suggests a regression re-introduced a trial-creation path. **DO NOT IMPLEMENT — flagged only.**

3. **No time-based sweep needed.** Batch D fixed the historical spill. Current code prevents new spills. Lazy normalization is architecturally sound for a paywall-gated app: users can't consume free credits without hitting the entitlement path, and the entitlement path self-heals.

## Artifacts written

- `/app/audit/rca_reproducer.py` — fixture-only reproducer (preview backend + local Mongo; auto-cleans fixtures)
- `/app/audit/rca_report.md` — this document

---

**HARD STOP.** No production writes. No code modifications. No deploys. No RC changes. No additional cleanup.
