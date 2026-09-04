# Post-Cleanup Legacy Access Audit (READ-ONLY)

- **Generated at (UTC):** 2026-09-04T01:13:16.401210+00:00
- **Target:** `https://bodybound-subs.emergent.host`
- **Write operations performed:** NONE

## 0. Production paid-cohort cross-check

| Metric | Value |
|---|---|
| Users returned by /admin/all-users | 388 |
| Real paid subscribers (non-trial, paid tier) | **48** |
| In Apple free-trial of a paid tier | 0 |
| vs previous audit (46) | CHANGED — was 46, now 48 (+2) |
| Baseline gross MRR floor (Walk-In equivalent × paid) | $719.52 |

## 1. Universe of remaining legacy/free-access accounts

| Category | Count |
|---|---|
| `tier='paywall_bypass'` | 47 |
| `tier='trial'` | 6 |
| `is_trial=true` and NOT `tier='trial'` (dedupe) | 4 |
| **TOTAL UNIQUE REMAINING LEGACY/FREE-ACCESS USERS** | **57** |
| Overlap with paid cohort (should be 0) | 0 |

## 2. `paywall_bypass` classification (B1 / B2 / B3)

Priority order used: **B1 (active) → B2 (RC-linked inactive) → B3 (boundary/other)**. Each unique user classified once.

| Bucket | Count |
|---|---|
| B1 — Active (login or generation ≤90d) | 31 |
| B2 — RC-linked ambiguous (inactive >90d, has RC id) | 16 |
| B3 — Boundary / other | 0 |
| **Total (must equal bypass count above)** | **47** |
| Reconciliation OK? | ✅ |

### 2.1 B1 — Active bypass detail

| email | last_login | days_since_login | consumed_gens | credits_remaining | RC id? | qualifying_signal |
|---|---|---:|---:|---:|:---:|---|
| nazgultattoos@gmail.com | 2026-09-03 | 0.2 | 5 | 5 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| 8qjsbhnhk7@privaterelay.appleid.com | 2026-09-03 | 0.2 | 12 | 8 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| alangarciaart1@gmail.com | 2026-09-02 | 1.1 | 3 | 7 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| tilldeathweds@gmail.com | 2026-08-28 | 6.4 | 4 | 6 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| coltrichardsontattoo@gmail.com | 2026-08-27 | 7.3 | 19 | 1 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| 2cfspg99r4@privaterelay.appleid.com | 2026-08-25 | 9.9 | 5 | 5 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| bugsalyer@gmail.com | 2026-08-24 | 10.8 | 1 | 9 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| amy.zager@gmail.com | 2026-08-22 | 12.4 | 3 | 10 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| fergusw98@gmail.com | 2026-08-21 | 13.7 | 6 | 4 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| beyondthelinesllc@gmail.com | 2026-08-20 | 14.4 | 10 | 0 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| libbie955@gmail.com | 2026-08-19 | 15.1 | 21 | 0 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| b8jgyy97sq@privaterelay.appleid.com | 2026-08-16 | 19.0 | 1 | 9 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| gcfvgy25gr@privaterelay.appleid.com | 2026-08-14 | 20.3 | 7 | 3 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| (anonymous: user_fa542aed6455) | 2026-08-07 | 27.2 | 20 | 0 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| carolinepearl40@icloud.com | 2026-08-06 | 28.3 | 12 | 9 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| parsonsalec568@gmail.com | 2026-08-01 | 33.6 | 10 | 0 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| artisticdelusions@gmail.com | 2026-07-21 | 44.2 | 7 | 3 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| ink33king@gmail.com | 2026-07-18 | 47.5 | 13 | 7 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| s59zbcgpvb@privaterelay.appleid.com | 2026-07-17 | 48.1 | 3 | 7 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| 9vnrmhzn8z@privaterelay.appleid.com | 2026-07-16 | 50.0 | 10 | 0 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| ccn69cfkts@privaterelay.appleid.com | 2026-07-12 | 53.8 | 1 | 9 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| nfkbg9j846@privaterelay.appleid.com | 2026-07-09 | 56.3 | 4 | 6 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| 5gqhw7k9mk@privaterelay.appleid.com | 2026-07-07 | 58.7 | 1 | 9 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| angelbriones1@gmail.com | 2026-07-06 | 59.1 | 9 | 1 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| ysrn8hzcm4@privaterelay.appleid.com | 2026-06-27 | 68.4 | 0 | 10 | — | login≤90d |
| kirstenlw717@icloud.com | 2026-06-26 | 69.3 | 7 | 3 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| reliecarttattoos@gmail.com | 2026-06-26 | 69.4 | 3 | 7 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| mq6gkqbk56@privaterelay.appleid.com | 2026-06-26 | 69.9 | 2 | 8 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| w5vfcg6x4z@privaterelay.appleid.com | 2026-06-13 | 82.3 | 4 | 6 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| t95ss9rp75@privaterelay.appleid.com | 2026-06-13 | 83.0 | 2 | 8 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |
| broadstreettattoostudio@gmail.com | 2026-06-07 | 88.9 | 4 | 6 | ✅ | login≤90d, generation≤90d · ⚠️ RC verification required before access change |

### 2.2 B2 — RC-linked ambiguous

| email | last_login | days_since_login | RC customer id | last_event | consumed_gens |
|---|---|---:|---|---|---:|
| kaleymerrill@gmail.com | 2026-05-31 | 95.4 | `kaleymerrill@gmail.com` | None | 7 |
| joshshawtattoos@gmail.com | 2026-05-22 | 104.1 | `joshshawtattoos@gmail.com` | PAYWALL_BYPASS | 5 |
| Tattooxcolorado@hotmail.com | 2026-05-22 | 104.2 | `tattooxcolorado@hotmail.com` | None | 4 |
| (anonymous: user_568adee536a8) | 2026-05-21 | 105.4 | `user_568adee536a8` | None | 10 |
| nosympathytattoo@icloud.com | 2026-05-20 | 106.6 | `nosympathytattoo@icloud.com` | None | 4 |
| 9z7y2wps59@privaterelay.appleid.com | 2026-05-15 | 111.4 | `9z7y2wps59@privaterelay.appleid.com` | None | 0 |
| j4npvywz6j@privaterelay.appleid.com | 2026-05-13 | 113.4 | `j4npvywz6j@privaterelay.appleid.com` | PAYWALL_BYPASS | 0 |
| moidzn@gmail.com | 2026-05-11 | 115.3 | `moidzn@gmail.com` | PAYWALL_BYPASS | 2 |
| mbsvr8kk45@privaterelay.appleid.com | 2026-05-09 | 117.2 | `mbsvr8kk45@privaterelay.appleid.com` | PAYWALL_BYPASS | 1 |
| somoslobos@gmail.com | 2026-05-06 | 121.0 | `somoslobos@gmail.com` | None | 0 |
| matthew.gasca@gmail.com | 2026-05-05 | 121.1 | `matthew.gasca@gmail.com` | None | 0 |
| mctvr8xt4n@privaterelay.appleid.com | 2026-05-05 | 121.8 | `mctvr8xt4n@privaterelay.appleid.com` | None | 0 |
| rty7jgcxs5@privaterelay.appleid.com | 2026-05-04 | 122.5 | `rty7jgcxs5@privaterelay.appleid.com` | None | 7 |
| hein_htetsoe123@icloud.com | 2026-05-04 | 123.0 | `hein_htetsoe123@icloud.com` | None | 4 |
| brandonlejmantattoos@gmail.com | 2026-05-03 | 123.1 | `brandonlejmantattoos@gmail.com` | None | 1 |
| Criaderomendoza701@icloud.com | 2026-05-03 | 123.5 | `criaderomendoza701@icloud.com` | None | 3 |

### 2.3 B3 — Boundary / other

Every B3 account must have a documented reason it survived Batch A/B/C.

_None._

## 3. Remaining trial flags

### 3.1 `tier='trial'` (n=6)

| email | trial_start | trial_expires | days_since_expires | RC id? | last_event | consumed_gens | assessment |
|---|---|---|---:|:---:|---|---:|---|
| (anonymous: user_673ab0d5552a) | — | — | — | — | None | 0 | TELEMETRY-LIMITED (no expiry date / anonymous device-linked) |
| (anonymous: user_a413c2ff83f9) | 2026-03-01 | 2026-03-04 | 183.3 | — | None | 0 | STALE / EXPIRED (trial ended, tier not cleared) |
| test@example.com | 2026-03-01 | 2026-03-04 | 183.3 | — | None | 0 | STALE / EXPIRED (trial ended, tier not cleared) |
| (anonymous: user_853c847c8f91) | 2026-03-05 | 2026-03-08 | 180.0 | — | None | 0 | STALE / EXPIRED (trial ended, tier not cleared) |
| (anonymous: user_714df781c4f8) | 2026-03-17 | 2026-03-20 | 167.4 | — | None | 0 | STALE / EXPIRED (trial ended, tier not cleared) |
| (anonymous: user_2c877c5ff51f) | 2026-03-20 | 2026-03-23 | 165.0 | — | None | 0 | STALE / EXPIRED (trial ended, tier not cleared) |

### 3.2 `is_trial=true` (deduped — NOT already in `tier='trial'`; n=4)

| email | tier | trial_start | trial_expires | RC id? | last_event | consumed_gens | assessment |
|---|---|---|---|:---:|---|---:|---|
| yoniimtz@icloud.com | trial_expired | 2026-03-17 | 2026-03-20 | — | None | 0 | STALE (is_trial=true but trial ended) |
| tattoosbykev5@gmail.com | trial_expired | 2026-03-20 | 2026-03-23 | ✅ | None | 0 | STALE (is_trial=true but trial ended) |
| (anonymous: user_bb51f47bab8a) | trial_expired | 2026-03-27 | 2026-03-30 | — | None | 0 | STALE (is_trial=true but trial ended) |
| marika_farmer90@icloud.com | expired | — | — | ✅ | CANCELLATION | 0 | AMBIGUOUS (has RC — needs RC verification) |

## 4. Business analysis — active free bypass users

### 4.1 Activity windows (B1 only)

| Window | Users |
|---|---:|
| 0-7d | 4 |
| 8-30d | 11 |
| 31-60d | 9 |
| 61-90d | 7 |
| **Total active ≤90d (B1)** | **31** |

### 4.2 Generation histogram (B1)

| Generations | Users |
|---|---:|
| 0 | 1 |
| 1-4 | 14 |
| 5-9 | 7 |
| 10-19 | 7 |
| 20+ | 2 |

- Total generations: **209**
- Average: **6.74**
- Median: **5**
- Max: **21**

## 5. MRR conversion scenarios

- Convertible pool: **B1 excluding test/reviewer emails** = **31** users (from B1 total 31)
- Assumed converted tier: **Walk-In @ $14.99/mo** (conservative floor)
- Current verified baseline gross MRR (Walk-In floor × paid): **$719.52**

| Conversion rate | Users converted | Incremental gross MRR | Total gross MRR |
|---:|---:|---:|---:|
| 10% | 3 | $44.97 | $764.49 |
| 20% | 6 | $89.94 | $809.46 |
| 30% | 9 | $134.91 | $854.43 |
| 50% | 16 | $239.84 | $959.36 |

_Note: real MRR is higher than the floor above because booked-out ($29.99) and the-shop ($99.99) subscribers contribute more than $14.99 each. The floor is used to keep the incremental math apples-to-apples._

## 6. Final reconciliation

### 6.1 Totals

| Category | Unique users |
|---|---:|
| `tier='paywall_bypass'` | 47 |
| `tier='trial'` | 6 |
| `is_trial=true` only (deduped) | 4 |
| **TOTAL UNIQUE REMAINING LEGACY/FREE-ACCESS USERS** | **57** |

### 6.2 Action-category classification

_Mutually exclusive — every remaining legacy user appears in exactly one row._

| Category | Count | Members |
|---|---:|---|
| 1. **Conversion opportunity** (B1 minus test/reviewer) | 31 | see 2.1 table — of which 30 carry ⚠️ RC-verify-first flag |
| 1b. Test / reviewer accounts (in B1, excluded from conversion math) | 0 | — |
| 2. **Safe future cleanup** (B3 + STALE trials without RC) | 7 | 5 from §3.1 + 2 from §3.2 |
| 3. **RC verification required** (B2 + ambiguous/telemetry-limited trials) | 19 | 1 from §3.1 + 2 from §3.2 |
| 4. **Legitimate paid/trial — DO NOT TOUCH** | 0 | Apple free-trial of paid tier / in-window trials |
| **Sum (must equal 57)** | **57** | ✅ |

### 6.3 Paid-cohort overlap check

✅ **No overlap** — no user is simultaneously in a paid tier AND flagged as legacy/free-access.

---

**HARD STOP.** No cleanup executed. No production code changed. No RC changes. No credit changes.
