# Batch D Execution Report

- **Batch id:** `BB-CLEANUP-2026-09-04-D`
- **Generated (UTC):** 2026-09-04T13:28:47.949948+00:00
- **Target:** `https://bodybound-subs.emergent.host`
- **Final status:** ✅ **BATCH D COMPLETE — VERIFIED**

## Per-target results

| user_id | HTTP | endpoint status | matched | modified | drift | post.tier | post.credits | needs_sub | success |
|---|:---:|---|:---:|:---:|:---:|---|---:|:---:|:---:|
| `user_a413c2ff83f9` | 200 | `changed` | 1 | 1 | ✅ {} | trial_expired | 0 | True | ✅ |
| `user_5a08baad0eb6` | 200 | `changed` | 1 | 1 | ✅ {} | trial_expired | 0 | True | ✅ |
| `user_853c847c8f91` | 200 | `changed` | 1 | 1 | ✅ {} | trial_expired | 0 | True | ✅ |
| `user_714df781c4f8` | 200 | `changed` | 1 | 1 | ✅ {} | trial_expired | 0 | True | ✅ |
| `user_2c877c5ff51f` | 200 | `changed` | 1 | 1 | ✅ {} | trial_expired | 0 | True | ✅ |

## Protected-field drift verification (per target)

| user_id | client-side drift check | endpoint-reported drift |
|---|:---:|:---:|
| `user_a413c2ff83f9` | ✅ empty | ✅ empty |
| `user_5a08baad0eb6` | ✅ empty | ✅ empty |
| `user_853c847c8f91` | ✅ empty | ✅ empty |
| `user_714df781c4f8` | ✅ empty | ✅ empty |
| `user_2c877c5ff51f` | ✅ empty | ✅ empty |

## Regression: paid cohort

- Pre-batch raw paid: **48**
- Post-batch raw paid: **48**
- Exact user_id set unchanged: **✅**

## Regression: paywall_bypass cohort

- Pre-batch bypass count: **47**
- Post-batch bypass count: **47**
- Exact user_id set unchanged: **✅**

## Regression: trial vs trial_expired counts

- tier='trial' delta: **-5** (expected -5)
- tier='trial_expired' delta: **5** (expected +5)
- Remaining tier='trial' user_ids: **['user_673ab0d5552a']**
- Expected remaining: **['user_673ab0d5552a']**
- Match: **✅**

## Ambiguous 6th (user_673ab0d5552a)

- Post-batch tier: `trial`
- Intact (still `tier='trial'`): ✅

## Audit trail

- Audit entries with `action='normalize_expired_trial'` AND `batch_id='BB-CLEANUP-2026-09-04-D'`: **5** (expected 5)

| target_email/user_id | pre_tier | post_tier | pre_credits | post_credits | matched | modified | drift | timestamp |
|---|---|---|---:|---:|:---:|:---:|:---:|---|
| `user_2c877c5ff51f` | trial | trial_expired | 10 | 0 | 1 | 1 | ✅ | 2026-09-04T13:28:55.227775+00:00 |
| `user_714df781c4f8` | trial | trial_expired | 10 | 0 | 1 | 1 | ✅ | 2026-09-04T13:28:54.278554+00:00 |
| `user_853c847c8f91` | trial | trial_expired | 10 | 0 | 1 | 1 | ✅ | 2026-09-04T13:28:53.498651+00:00 |
| `user_5a08baad0eb6` | trial | trial_expired | 10 | 0 | 1 | 1 | ✅ | 2026-09-04T13:28:52.506385+00:00 |
| `user_a413c2ff83f9` | trial | trial_expired | 10 | 0 | 1 | 1 | ✅ | 2026-09-04T13:28:51.731100+00:00 |

## Full reconciliation rerun (regression proof)

| Metric | Value | Expected |
|---|---|---|
| RAW paid | 48 | 48 |
| Internal/test excluded | 2 | 2 |
| REAL paying | 46 | 46 |
| Gross MRR (code prices) | $734.54 | $734.54 |
| Legacy universe total | 57 | 57 |

---

**Final:** ✅ **BATCH D COMPLETE — VERIFIED**