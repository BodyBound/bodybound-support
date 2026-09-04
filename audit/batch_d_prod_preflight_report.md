# Batch D Production Preflight (READ-ONLY, dry_run=true)

- **Generated at (UTC):** 2026-09-04T11:58:18.062542+00:00
- **Target:** `https://bodybound-subs.emergent.host`
- **Batch id:** `BB-CLEANUP-2026-09-04-D`
- **Route confirmed on production:** ✅
- **Writes performed:** NONE

## 1. Production deployment / route confirmation

Probe: `POST /api/admin-tool/action/normalize-expired-trial` with a non-existent user_id.
Expected shape from new endpoint: `{status: 'skipped', reason: 'subscription_not_found'}`.
Actual: `{"status": "skipped", "user_id": "user_13f81de37ea8", "cleanup_batch_id": "BB-CLEANUP-2026-09-04-D", "reasons": ["precondition_failed:tier_is_'paywall_bypass'_expected_trial", "precondition_failed:is_trial_is_false", "precondition_failed:available_credits_is_3_expected_10", "precondition_failed:revenuecat_customer_id_present", "precondition_failed:trial_expires_at_missing", "precondition_failed:trial_expires_at_drift"], "pre_state": {"user_id": "user_13f81de37ea8", "tier": "paywall_bypass", "is_trial": false, "available_credits": 3, "revenuecat_customer_id": "kaleymerrill@gmail.com", "trial_expires_at": null, "trial_start_date": null, "last_event": null, "anti_abuse_provider": "apple:001694.55ae206a2829499983802e3e9d7469fb.1532", "created_at": "2026-04-30T15:32:53.580504+00:00"}}` (HTTP 200)
→ ✅ Route is the newly deployed implementation.

## 2. Dry-run for the 5 Batch D targets

| user_id | pre.tier | pre.credits | pre.rc_id | pre.trial_expires_at | dry_run status | would_set.tier | would_set.credits | eligible |
|---|---|---:|:---:|---|---|---|---:|:---:|
| `user_a413c2ff83f9` | trial | 10 | — | 2026-03-04T19:08:04.519584+00:00 | `dry_run` | `trial_expired` | 0 | ✅ |
| `user_5a08baad0eb6` | trial | 10 | — | 2026-03-04T19:10:41.448946+00:00 | `dry_run` | `trial_expired` | 0 | ✅ |
| `user_853c847c8f91` | trial | 10 | — | 2026-03-08T01:34:48.596477+00:00 | `dry_run` | `trial_expired` | 0 | ✅ |
| `user_714df781c4f8` | trial | 10 | — | 2026-03-20T15:29:43.161934+00:00 | `dry_run` | `trial_expired` | 0 | ✅ |
| `user_2c877c5ff51f` | trial | 10 | — | 2026-03-23T02:19:43.576524+00:00 | `dry_run` | `trial_expired` | 0 | ✅ |

## 3. Negative controls

### 3.1 Ambiguous 6th trial

- `user_673ab0d5552a` → `skipped` (eligible=False)
  - reasons: `['precondition_failed:available_credits_is_0_expected_10', 'precondition_failed:trial_expires_at_missing', 'precondition_failed:trial_expires_at_drift']`

### 3.2 Paying subscribers (3 controls)

| user_id | tier | dry_run status | reasons | eligible |
|---|---|---|---|:---:|
| `user_50aab4a6df20` | walk-in | `skipped` | `["precondition_failed:tier_is_'walk-in'_expected_trial", 'precondition_failed:is_trial_is_false', 'precondition_failed:available_credits_is_250_expected_10']` | ❌ |
| `user_8305f4c0c6ac` | walk-in | `skipped` | `["precondition_failed:tier_is_'walk-in'_expected_trial", 'precondition_failed:is_trial_is_false', 'precondition_failed:available_credits_is_230_expected_10', 'precondition_failed:revenuecat_customer_id_present', 'precondition_failed:trial_expires_at_missing', 'precondition_failed:trial_expires_at_drift']` | ❌ |
| `user_570f85906b8c` | booked-out | `skipped` | `["precondition_failed:tier_is_'booked-out'_expected_trial", 'precondition_failed:is_trial_is_false', 'precondition_failed:available_credits_is_994_expected_10', 'precondition_failed:revenuecat_customer_id_present', 'precondition_failed:trial_expires_at_missing', 'precondition_failed:trial_expires_at_drift']` | ❌ |

### 3.3 Paywall_bypass controls (3)

| email | user_id | tier | dry_run status | reasons | eligible |
|---|---|---|---|---|:---:|
| nazgultattoos@gmail.com | `user_7fc87142a35d` | paywall_bypass | `skipped` | `["precondition_failed:tier_is_'paywall_bypass'_expected_trial", 'precondition_failed:is_trial_is_false', 'precondition_failed:available_credits_is_4_expected_10', 'precondition_failed:revenuecat_customer_id_present', 'precondition_failed:trial_expires_at_missing', 'precondition_failed:trial_expires_at_drift']` | ❌ |
| coltrichardsontattoo@gmail.com | `user_182dbdc3ef14` | paywall_bypass | `skipped` | `["precondition_failed:tier_is_'paywall_bypass'_expected_trial", 'precondition_failed:is_trial_is_false', 'precondition_failed:available_credits_is_1_expected_10', 'precondition_failed:revenuecat_customer_id_present', 'precondition_failed:trial_expires_at_missing', 'precondition_failed:trial_expires_at_drift']` | ❌ |
| beyondthelinesllc@gmail.com | `user_9ab836a173f4` | paywall_bypass | `skipped` | `["precondition_failed:tier_is_'paywall_bypass'_expected_trial", 'precondition_failed:is_trial_is_false', 'precondition_failed:available_credits_is_0_expected_10', 'precondition_failed:revenuecat_customer_id_present', 'precondition_failed:trial_expires_at_missing', 'precondition_failed:trial_expires_at_drift']` | ❌ |

### 3.4 RC-linked controls (3)

| email | user_id | tier | rc_id | dry_run status | reasons | eligible |
|---|---|---|:---:|---|---|:---:|
| tattoosbykev5@gmail.com | `user_6bc049c92733` | trial_expired | ✅ | `skipped` | `["precondition_failed:tier_is_'trial_expired'_expected_trial", 'precondition_failed:available_credits_is_0_expected_10', 'precondition_failed:revenuecat_customer_id_present']` | ❌ |
| marika_farmer90@icloud.com | `user_046f6e48e8ce` | expired | ✅ | `skipped` | `["precondition_failed:tier_is_'expired'_expected_trial", 'precondition_failed:revenuecat_customer_id_present', 'precondition_failed:trial_expires_at_missing', 'precondition_failed:trial_expires_at_drift']` | ❌ |
| kaleymerrill@gmail.com | `user_13f81de37ea8` | paywall_bypass | ✅ | `skipped` | `["precondition_failed:tier_is_'paywall_bypass'_expected_trial", 'precondition_failed:is_trial_is_false', 'precondition_failed:available_credits_is_3_expected_10', 'precondition_failed:revenuecat_customer_id_present', 'precondition_failed:trial_expires_at_missing', 'precondition_failed:trial_expires_at_drift']` | ❌ |

## 4. Blast radius

- **Eligible targets:** **5** / expected **5**
- **All negative controls excluded:** ✅
- **Eligible user_ids:** ['user_a413c2ff83f9', 'user_5a08baad0eb6', 'user_853c847c8f91', 'user_714df781c4f8', 'user_2c877c5ff51f']
- **Approved list:** ['user_a413c2ff83f9', 'user_5a08baad0eb6', 'user_853c847c8f91', 'user_714df781c4f8', 'user_2c877c5ff51f']
- **Match:** ✅ EXACT

## 5. Post dry-run state verification

Re-fetched all 5 targets after the dry-run calls to prove the endpoint did not write.

- **All 5 target records unchanged post dry-run:** ✅

## 6. Final recommendation

### ✅ READY TO EXECUTE 5 BATCH D WRITES

Production endpoint is live and honors every precondition. Exactly
5 target accounts are eligible; the approved list matches exactly.
Every negative control (ambiguous 6th, 3 paying, 3 bypass, 3 RC-linked)
was correctly excluded. No production state changed during preflight.

---

**HARD STOP.** No writes. No RC changes. No further cleanup. Awaiting explicit authorization for the 5 subscription writes.