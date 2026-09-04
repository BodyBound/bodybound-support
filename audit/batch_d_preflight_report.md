# Batch D Preflight — Expired Trial Access Fix (READ-ONLY)

- **Generated at (UTC):** 2026-09-04T03:14:46.758577+00:00
- **Target:** `https://bodybound-subs.emergent.host`
- **Writes performed:** NONE
- **Deploys performed:** NONE
- **RevenueCat interactions:** NONE
- **Target user_ids (5):** `user_a413c2ff83f9`, `user_5a08baad0eb6`, `user_853c847c8f91`, `user_714df781c4f8`, `user_2c877c5ff51f`
- **Explicit exclusions:** `user_673ab0d5552a` — telemetry-limited/ambiguous

## Reference: natural trial-expiration behavior

From `backend/server.py`, `get_user_credits()` (lines 3770-3782):

```python
if is_trial and trial_expires_at:
    if expires_dt <= now:
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {'available_credits': 0, 'tier': 'trial_expired'}}
        )
```

This is the ONLY natural-expiration mutation in the codebase. It sets
exactly two fields — `tier` and `available_credits`. Nothing else is
touched. Batch D mirrors this operation exactly (no cosmetic writes).

## Step 1 — Per-account preflight verification

### `user_a413c2ff83f9`  ((anonymous))

**Fetch status:** OK

| # | Precondition | Expected | Actual | Pass |
|---:|---|---|---|:---:|
| 1 | `1_sub_tier_is_trial` | tier == 'trial' | trial | ✅ |
| 2 | `2_trial_expires_exists` | trial_expires_at is present | 2026-03-04T19:08:04.519584+00:00 | ✅ |
| 3 | `3_trial_expires_in_past` | trial_expires_at <= now | 2026-03-04T19:08:04.519584+00:00 vs now=2026-09-04T03:14:46.758577+00:00 | ✅ |
| 4 | `4_no_rc_id` | revenuecat_customer_id is None/empty | None | ✅ |
| 5 | `5_not_paid_tier` | tier NOT IN ['booked-out', 'the-shop', 'the-shop-member', 'walk-in'] | trial | ✅ |
| 6 | `6_not_paywall_bypass` | tier != 'paywall_bypass' | trial | ✅ |
| 7 | `7_no_other_entitlement_evidence` | no active entitlement markers | `last_event`=None<br>`last_product_id`=None<br>`studio_team_id`=None<br>`renewal_date`=None<br>`received_temp_credits`=None<br>`admin_cleanup_reason`=None | ✅ |
| 8 | `8_paywall_bypass_bug_present` | raw tier check returns needs_subscription=False purely because tier='trial' | `raw_tier_check_needs_sub`=False<br>`coerced_tier_by_natural_path`=trial_expired<br>`post_side_effect_first_call_needs_sub`=True<br>`is_trial_flag`=True | ✅ |

**Preconditions all pass:** ✅ YES — proceed to batch

**Proposed field changes (minimum safe mutation):**

| field | before | after |
|---|---|---|
| `tier` | `trial` | `trial_expired` |
| `available_credits` | `10` | `0` |

### `user_5a08baad0eb6`  (te***@example.com)

**Fetch status:** OK

| # | Precondition | Expected | Actual | Pass |
|---:|---|---|---|:---:|
| 1 | `1_sub_tier_is_trial` | tier == 'trial' | trial | ✅ |
| 2 | `2_trial_expires_exists` | trial_expires_at is present | 2026-03-04T19:10:41.448946+00:00 | ✅ |
| 3 | `3_trial_expires_in_past` | trial_expires_at <= now | 2026-03-04T19:10:41.448946+00:00 vs now=2026-09-04T03:14:46.758577+00:00 | ✅ |
| 4 | `4_no_rc_id` | revenuecat_customer_id is None/empty | None | ✅ |
| 5 | `5_not_paid_tier` | tier NOT IN ['booked-out', 'the-shop', 'the-shop-member', 'walk-in'] | trial | ✅ |
| 6 | `6_not_paywall_bypass` | tier != 'paywall_bypass' | trial | ✅ |
| 7 | `7_no_other_entitlement_evidence` | no active entitlement markers | `last_event`=None<br>`last_product_id`=None<br>`studio_team_id`=None<br>`renewal_date`=None<br>`received_temp_credits`=None<br>`admin_cleanup_reason`=None | ✅ |
| 8 | `8_paywall_bypass_bug_present` | raw tier check returns needs_subscription=False purely because tier='trial' | `raw_tier_check_needs_sub`=False<br>`coerced_tier_by_natural_path`=trial_expired<br>`post_side_effect_first_call_needs_sub`=True<br>`is_trial_flag`=True | ✅ |

**Preconditions all pass:** ✅ YES — proceed to batch

**Proposed field changes (minimum safe mutation):**

| field | before | after |
|---|---|---|
| `tier` | `trial` | `trial_expired` |
| `available_credits` | `10` | `0` |

### `user_853c847c8f91`  ((anonymous))

**Fetch status:** OK

| # | Precondition | Expected | Actual | Pass |
|---:|---|---|---|:---:|
| 1 | `1_sub_tier_is_trial` | tier == 'trial' | trial | ✅ |
| 2 | `2_trial_expires_exists` | trial_expires_at is present | 2026-03-08T01:34:48.596477+00:00 | ✅ |
| 3 | `3_trial_expires_in_past` | trial_expires_at <= now | 2026-03-08T01:34:48.596477+00:00 vs now=2026-09-04T03:14:46.758577+00:00 | ✅ |
| 4 | `4_no_rc_id` | revenuecat_customer_id is None/empty | None | ✅ |
| 5 | `5_not_paid_tier` | tier NOT IN ['booked-out', 'the-shop', 'the-shop-member', 'walk-in'] | trial | ✅ |
| 6 | `6_not_paywall_bypass` | tier != 'paywall_bypass' | trial | ✅ |
| 7 | `7_no_other_entitlement_evidence` | no active entitlement markers | `last_event`=None<br>`last_product_id`=None<br>`studio_team_id`=None<br>`renewal_date`=None<br>`received_temp_credits`=None<br>`admin_cleanup_reason`=None | ✅ |
| 8 | `8_paywall_bypass_bug_present` | raw tier check returns needs_subscription=False purely because tier='trial' | `raw_tier_check_needs_sub`=False<br>`coerced_tier_by_natural_path`=trial_expired<br>`post_side_effect_first_call_needs_sub`=True<br>`is_trial_flag`=True | ✅ |

**Preconditions all pass:** ✅ YES — proceed to batch

**Proposed field changes (minimum safe mutation):**

| field | before | after |
|---|---|---|
| `tier` | `trial` | `trial_expired` |
| `available_credits` | `10` | `0` |

### `user_714df781c4f8`  ((anonymous))

**Fetch status:** OK

| # | Precondition | Expected | Actual | Pass |
|---:|---|---|---|:---:|
| 1 | `1_sub_tier_is_trial` | tier == 'trial' | trial | ✅ |
| 2 | `2_trial_expires_exists` | trial_expires_at is present | 2026-03-20T15:29:43.161934+00:00 | ✅ |
| 3 | `3_trial_expires_in_past` | trial_expires_at <= now | 2026-03-20T15:29:43.161934+00:00 vs now=2026-09-04T03:14:46.758577+00:00 | ✅ |
| 4 | `4_no_rc_id` | revenuecat_customer_id is None/empty | None | ✅ |
| 5 | `5_not_paid_tier` | tier NOT IN ['booked-out', 'the-shop', 'the-shop-member', 'walk-in'] | trial | ✅ |
| 6 | `6_not_paywall_bypass` | tier != 'paywall_bypass' | trial | ✅ |
| 7 | `7_no_other_entitlement_evidence` | no active entitlement markers | `last_event`=None<br>`last_product_id`=None<br>`studio_team_id`=None<br>`renewal_date`=None<br>`received_temp_credits`=None<br>`admin_cleanup_reason`=None | ✅ |
| 8 | `8_paywall_bypass_bug_present` | raw tier check returns needs_subscription=False purely because tier='trial' | `raw_tier_check_needs_sub`=False<br>`coerced_tier_by_natural_path`=trial_expired<br>`post_side_effect_first_call_needs_sub`=True<br>`is_trial_flag`=True | ✅ |

**Preconditions all pass:** ✅ YES — proceed to batch

**Proposed field changes (minimum safe mutation):**

| field | before | after |
|---|---|---|
| `tier` | `trial` | `trial_expired` |
| `available_credits` | `10` | `0` |

### `user_2c877c5ff51f`  ((anonymous))

**Fetch status:** OK

| # | Precondition | Expected | Actual | Pass |
|---:|---|---|---|:---:|
| 1 | `1_sub_tier_is_trial` | tier == 'trial' | trial | ✅ |
| 2 | `2_trial_expires_exists` | trial_expires_at is present | 2026-03-23T02:19:43.576524+00:00 | ✅ |
| 3 | `3_trial_expires_in_past` | trial_expires_at <= now | 2026-03-23T02:19:43.576524+00:00 vs now=2026-09-04T03:14:46.758577+00:00 | ✅ |
| 4 | `4_no_rc_id` | revenuecat_customer_id is None/empty | None | ✅ |
| 5 | `5_not_paid_tier` | tier NOT IN ['booked-out', 'the-shop', 'the-shop-member', 'walk-in'] | trial | ✅ |
| 6 | `6_not_paywall_bypass` | tier != 'paywall_bypass' | trial | ✅ |
| 7 | `7_no_other_entitlement_evidence` | no active entitlement markers | `last_event`=None<br>`last_product_id`=None<br>`studio_team_id`=None<br>`renewal_date`=None<br>`received_temp_credits`=None<br>`admin_cleanup_reason`=None | ✅ |
| 8 | `8_paywall_bypass_bug_present` | raw tier check returns needs_subscription=False purely because tier='trial' | `raw_tier_check_needs_sub`=False<br>`coerced_tier_by_natural_path`=trial_expired<br>`post_side_effect_first_call_needs_sub`=True<br>`is_trial_flag`=True | ✅ |

**Preconditions all pass:** ✅ YES — proceed to batch

**Proposed field changes (minimum safe mutation):**

| field | before | after |
|---|---|---|
| `tier` | `trial` | `trial_expired` |
| `available_credits` | `10` | `0` |

## Step 2 — Minimum safe mutation

Reference set (from natural expiration): `{'tier': 'trial_expired', 'available_credits': 0}`

For each target account, only fields that *differ* from the reference set
are proposed for mutation. Cosmetic/stale metadata (e.g. `is_trial=true`,
`trial_start_date`, `trial_expires_at`, `anti_abuse_*`) is intentionally
**not** touched — natural expiration does not touch it, and the fields
have no entitlement-gating effect (see §5 of the reconciliation report).

### Fields NOT touched by natural expiration (and NOT touched by Batch D):

- `is_trial` — leaving it as `True` preserves telemetry parity with a
  naturally-expired trial (`is_trial=True` remains on those too until
  the RC webhook eventually rewrites it).
- `trial_start_date`, `trial_expires_at` — historic; no gating effect.
- `anti_abuse_email`, `anti_abuse_device_id`, `anti_abuse_provider` —
  preserved to keep the anti-abuse ledger intact.
- `created_at`, `last_event`, `revenuecat_customer_id` — untouched.

## Step 3 — Exact dry-run manifest

| user_id | email (redacted) | current tier | trial expiry | RC id | current needs_sub (raw) | proposed changes | expected needs_sub after |
|---|---|---|---|:---:|:---:|---|:---:|
| `user_a413c2ff83f9` | (anonymous) | `trial` | 2026-03-04T19:08:04.519584+00:00 | — | False | `tier`:`trial`→`trial_expired`; `available_credits`:`10`→`0` | **True** |
| `user_5a08baad0eb6` | te***@example.com | `trial` | 2026-03-04T19:10:41.448946+00:00 | — | False | `tier`:`trial`→`trial_expired`; `available_credits`:`10`→`0` | **True** |
| `user_853c847c8f91` | (anonymous) | `trial` | 2026-03-08T01:34:48.596477+00:00 | — | False | `tier`:`trial`→`trial_expired`; `available_credits`:`10`→`0` | **True** |
| `user_714df781c4f8` | (anonymous) | `trial` | 2026-03-20T15:29:43.161934+00:00 | — | False | `tier`:`trial`→`trial_expired`; `available_credits`:`10`→`0` | **True** |
| `user_2c877c5ff51f` | (anonymous) | `trial` | 2026-03-23T02:19:43.576524+00:00 | — | False | `tier`:`trial`→`trial_expired`; `available_credits`:`10`→`0` | **True** |

### Proposed MongoDB operations (dry-run — DO NOT EXECUTE)

Each operation is scoped by **exact `user_id`** and includes
**current-state predicates** so the write fails safely if the record
has drifted between preflight and execution.

#### `user_a413c2ff83f9`

```javascript
db.subscriptions.updateOne(
  {
    "user_id": "user_a413c2ff83f9",
    "tier": "trial",
    "is_trial": true,
    "available_credits": 10,
    "revenuecat_customer_id": null,
    "trial_expires_at": "2026-03-04T19:08:04.519584+00:00"
  },
  {
    "$set": {
      "tier": "trial_expired",
      "available_credits": 0
    }
  }
)
```

#### `user_5a08baad0eb6`

```javascript
db.subscriptions.updateOne(
  {
    "user_id": "user_5a08baad0eb6",
    "tier": "trial",
    "is_trial": true,
    "available_credits": 10,
    "revenuecat_customer_id": null,
    "trial_expires_at": "2026-03-04T19:10:41.448946+00:00"
  },
  {
    "$set": {
      "tier": "trial_expired",
      "available_credits": 0
    }
  }
)
```

#### `user_853c847c8f91`

```javascript
db.subscriptions.updateOne(
  {
    "user_id": "user_853c847c8f91",
    "tier": "trial",
    "is_trial": true,
    "available_credits": 10,
    "revenuecat_customer_id": null,
    "trial_expires_at": "2026-03-08T01:34:48.596477+00:00"
  },
  {
    "$set": {
      "tier": "trial_expired",
      "available_credits": 0
    }
  }
)
```

#### `user_714df781c4f8`

```javascript
db.subscriptions.updateOne(
  {
    "user_id": "user_714df781c4f8",
    "tier": "trial",
    "is_trial": true,
    "available_credits": 10,
    "revenuecat_customer_id": null,
    "trial_expires_at": "2026-03-20T15:29:43.161934+00:00"
  },
  {
    "$set": {
      "tier": "trial_expired",
      "available_credits": 0
    }
  }
)
```

#### `user_2c877c5ff51f`

```javascript
db.subscriptions.updateOne(
  {
    "user_id": "user_2c877c5ff51f",
    "tier": "trial",
    "is_trial": true,
    "available_credits": 10,
    "revenuecat_customer_id": null,
    "trial_expires_at": "2026-03-23T02:19:43.576524+00:00"
  },
  {
    "$set": {
      "tier": "trial_expired",
      "available_credits": 0
    }
  }
)
```

## Step 4 — Blast-radius proof

**Records that would be modified if all writes succeed:** 5
**Expected maximum:** 5
**Match:** ✅

### Proofs

1. **Exactly the approved records — no others.** Each `updateOne` is scoped by
   `user_id` (exact match). The `user_id` field is unique in the `subscriptions`
   collection (used as the primary index throughout `server.py`). Batch D will
   never match a document whose `user_id` isn't in the target list.

2. **Cannot match paying subscribers.** The filter additionally requires
   `tier: 'trial'`. Paying subscribers have `tier ∈ {walk-in, booked-out,
   the-shop, the-shop-member}` — none of them can satisfy the filter.

3. **Cannot match RC-linked users.** The filter also requires
   `revenuecat_customer_id: null`. Any account with an RC id is filter-excluded.

4. **Cannot match `paywall_bypass` users.** Excluded twice-over:
   `tier: 'trial'` alone rules them out; the target `user_id` list contains no
   bypass user.

5. **Cannot match the ambiguous sixth trial (`user_673ab0d5552a`).** Not in the
   target `user_id` list. `user_id` scope makes accidental inclusion structurally
   impossible.

6. **Credits mutation matches natural expiration.** The natural-expiration path
   at server.py:3781 sets `available_credits: 0`. Batch D only writes this field
   when the current value differs from 0 (see Step 3 per-account manifest).
   No account receives credits.

7. **Does not modify RevenueCat.** No outbound RC calls are made. `revenuecat_customer_id`
   is used only as a read-side filter predicate — it is not written.

8. **Does not modify App Store state.** No StoreKit / product interaction is possible
   from this admin plane.

9. **Does not modify application code.** Batch D is purely a data operation.

## Step 5 — Post-write verification plan (to run AFTER authorized execution)

Every check below is a READ, not a write.

### 5.1 Per-account verification

For each of the 5 user_ids, verify via `GET /api/admin/user-lookup?user_id=<uid>`:

| Check | Expected |
|---|---|
| `subscription.tier` | `'trial_expired'` |
| `subscription.available_credits` | `0` |
| `subscription.revenuecat_customer_id` | `null` (unchanged) |
| `subscription.trial_expires_at` | unchanged from preflight snapshot |
| `subscription.trial_start_date` | unchanged |
| `subscription.is_trial` | unchanged (still `True`) |
| `subscription.last_event` | unchanged |
| `subscription.created_at` | unchanged |

Then simulate the entitlement check by calling
`GET /api/admin/user-lookup?user_id=<uid>` and computing:

```python
needs_subscription = sub['tier'] in (None, 'trial_expired', 'expired')
assert needs_subscription is True  # paywall now closes
```

### 5.2 Regression checks (whole-cohort)

Re-run `/app/audit/reconciliation.py` and confirm:

- **Real paid cohort:** `RAW=48 / EXCLUDED=2 / REAL=46` (unchanged)
- **Gross MRR:** `$734.54` (unchanged)
- **`paywall_bypass` count:** exactly the same 47 user_ids as pre-batch
- **RC-linked count:** unchanged (46 bypass + 2 trials with RC)
- **`tier='trial'` remaining:** `1` (only `user_673ab0d5552a`, the excluded ambiguous account)
- **`sub_tier='trial_expired'` new count:** `+5` compared to pre-batch
- **Total legacy universe:** still `57` (no additions/removals — the 5 rows
  migrate from `tier='trial'` to `tier='trial_expired'`; total is unchanged)

### 5.3 Audit-trail requirement

Whichever endpoint executes the write should:

- Log the `matched_count` and `modified_count` of each `updateOne` (Mongo returns both).
- Assert `modified_count == 1` per operation; if any operation returns
  `modified_count == 0` (i.e. the filter didn't match because state drifted),
  record the user_id in an errors list and continue.
- Persist an entry per operation to `admin_cleanup_batches` (or existing
  `admin_actions` collection) with: `user_id`, pre-state snapshot, post-state,
  batch_id (e.g. `BB-CLEANUP-2026-09-04-D`), and timestamp.

## Final recommendation

### ✅ SAFE TO EXECUTE BATCH D

All 5 preconditions passed on live re-fetch. The proposed mutation is
byte-for-byte identical to what the server would perform organically on
each user's next `/api/credits` call. Blast radius is exactly 5 records.
No credits are granted. No RC state is touched. No production code
changes. No deploys.

Awaiting explicit execution authorization.

---

**HARD STOP.** No writes. No deploys. No code changes. No RC touches.
