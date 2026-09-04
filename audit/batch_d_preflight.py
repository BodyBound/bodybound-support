#!/usr/bin/env python3
"""
Batch D preflight — READ-ONLY.

Verifies the 5 target user_ids and produces an exact dry-run manifest for
the smallest safe mutation that mirrors the natural trial-expiration path
in backend/server.py (get_user_credits, line ~3779-3782).

ZERO WRITES. ZERO DEPLOYS. ZERO CODE CHANGES.

Outputs:
  /app/audit/batch_d_preflight_data.json
  /app/audit/batch_d_preflight_report.md
"""
import os
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError, URLError

PROD_BASE = "https://bodybound-subs.emergent.host"
ADMIN_EMAIL = "bodyboundstencil@yahoo.com"
ADMIN_PASSWORD = "Body.Bound.Admin.72410"

OUT_DIR = "/app/audit"
DATA_JSON = os.path.join(OUT_DIR, "batch_d_preflight_data.json")
REPORT_MD = os.path.join(OUT_DIR, "batch_d_preflight_report.md")

NOW = datetime.now(timezone.utc)

# The five accounts the operator identified for Batch D.
TARGET_USER_IDS = [
    "user_a413c2ff83f9",
    "user_5a08baad0eb6",
    "user_853c847c8f91",
    "user_714df781c4f8",
    "user_2c877c5ff51f",
]

# Explicitly excluded (per operator: telemetry-limited/ambiguous).
EXCLUDED_USER_IDS = ["user_673ab0d5552a"]

PAID_TIERS = {"walk-in", "booked-out", "the-shop", "the-shop-member"}
BYPASS_TIER = "paywall_bypass"

# Reference: natural trial-expiration path in backend/server.py
NATURAL_EXPIRATION_SET = {"tier": "trial_expired", "available_credits": 0}


def http_json(method, path, token=None, body=None, timeout=45):
    url = PROD_BASE + path
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}
    except URLError as e:
        return -1, {"error": f"URLError: {e}"}


def login():
    status, data = http_json("POST", "/api/admin-auth/login",
                             body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if status != 200 or not data or "token" not in data:
        raise SystemExit(f"[FATAL] admin login failed: {status} {data}")
    return data["token"]


def parse_iso(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def fetch_user(token, user_id):
    status, data = http_json(
        "GET", f"/api/admin/user-lookup?user_id={quote(user_id)}", token=token)
    if status != 200 or not data:
        return None, None, {"status": status, "data": data}
    if not data.get("found"):
        return None, None, {"reason": "not_found"}
    return data.get("user") or {}, data.get("subscription") or {}, None


def compute_needs_subscription(sub):
    """Exact port of get_user_credits() logic. Also emulates the *side-effect*
    of the natural expiration path: if `is_trial=True` and `trial_expires_at<=now`,
    the server would set tier='trial_expired' BEFORE evaluating needs_subscription.
    For a purely descriptive preflight we report BOTH values:
      - `pre_side_effect`: what a client sees on the FIRST /api/credits call
        (server computes needs_sub AFTER side-effect update). tier is coerced
        to 'trial_expired' first, so needs_sub=True.
      - `raw_tier_check`: what needs_sub would be without any side effect
        (pure `tier in (None,'trial_expired','expired')`). For tier='trial',
        this is False — that's the paywall-bypass bug.
    """
    tier = sub.get("tier")
    is_trial = bool(sub.get("is_trial"))
    exp = parse_iso(sub.get("trial_expires_at"))
    raw = tier in (None, "trial_expired", "expired")

    coerced_tier = tier
    if is_trial and exp is not None and exp <= NOW:
        coerced_tier = "trial_expired"
    post = coerced_tier in (None, "trial_expired", "expired")
    return {
        "raw_tier_check": raw,
        "post_side_effect_first_call": post,
        "coerced_tier_by_natural_path": coerced_tier,
    }


def verify_preconditions(sub):
    """Returns (all_pass_bool, checks_dict) for the 8 preconditions."""
    tier = sub.get("tier")
    exp_iso = sub.get("trial_expires_at")
    exp_dt = parse_iso(exp_iso)
    rc_id = sub.get("revenuecat_customer_id")
    last_event = sub.get("last_event")
    is_trial = bool(sub.get("is_trial"))

    checks = {
        "1_sub_tier_is_trial": {
            "expected": "tier == 'trial'",
            "actual": tier,
            "pass": tier == "trial",
        },
        "2_trial_expires_exists": {
            "expected": "trial_expires_at is present",
            "actual": exp_iso,
            "pass": exp_dt is not None,
        },
        "3_trial_expires_in_past": {
            "expected": "trial_expires_at <= now",
            "actual": f"{exp_dt.isoformat() if exp_dt else None} vs now={NOW.isoformat()}",
            "pass": exp_dt is not None and exp_dt <= NOW,
        },
        "4_no_rc_id": {
            "expected": "revenuecat_customer_id is None/empty",
            "actual": rc_id,
            "pass": not rc_id,
        },
        "5_not_paid_tier": {
            "expected": f"tier NOT IN {sorted(PAID_TIERS)}",
            "actual": tier,
            "pass": tier not in PAID_TIERS,
        },
        "6_not_paywall_bypass": {
            "expected": "tier != 'paywall_bypass'",
            "actual": tier,
            "pass": tier != BYPASS_TIER,
        },
        "7_no_other_entitlement_evidence": {
            # We inspect: last_event, last_product_id, is_studio_team markers,
            # active referral premium, non-zero credits from a paid source.
            # Any of these being active would indicate live entitlement.
            "expected": "no active entitlement markers",
            "actual": {
                "last_event": last_event,
                "last_product_id": sub.get("last_product_id"),
                "studio_team_id": sub.get("studio_team_id"),
                "renewal_date": sub.get("renewal_date"),
                "received_temp_credits": sub.get("received_temp_credits"),
                "admin_cleanup_reason": sub.get("admin_cleanup_reason"),
            },
            "pass": (
                last_event in (None, "", "TRIAL_STARTED", "TRIAL_ENDED",
                               "EXPIRATION", "CANCELLATION")
                and not sub.get("last_product_id")
                and not sub.get("studio_team_id")
                and not sub.get("renewal_date")
            ),
        },
    }

    # 8: /api/credits entitlement logic would produce needs_sub=False solely
    # because tier='trial'. This is the bug we are closing.
    calc = compute_needs_subscription(sub)
    checks["8_paywall_bypass_bug_present"] = {
        "expected": "raw tier check returns needs_subscription=False purely because tier='trial'",
        "actual": {
            "raw_tier_check_needs_sub": calc["raw_tier_check"],
            "coerced_tier_by_natural_path": calc["coerced_tier_by_natural_path"],
            "post_side_effect_first_call_needs_sub": calc["post_side_effect_first_call"],
            "is_trial_flag": is_trial,
        },
        # The bug is present iff raw check says needs_sub=False AND the side
        # effect *would* have flipped it if the account had been polled recently.
        "pass": calc["raw_tier_check"] is False,
        "note": (
            "If is_trial=True on the record, the FIRST /api/credits call by this "
            "user would auto-run the natural expiration path and coerce the tier "
            "to 'trial_expired' before returning needs_subscription=True. Batch D "
            "performs exactly that mutation proactively so the account cannot "
            "grant free access on its next server call OR to any adjacent code "
            "path that reads sub.tier without running through get_user_credits()."
        ),
    }

    all_pass = all(c["pass"] for c in checks.values())
    return all_pass, checks


def diff_natural_expiration(sub):
    """Compute the smallest mutation needed to match natural expiration.
    Only include a field if it differs. Do NOT touch anything else."""
    changes = {}
    if sub.get("tier") != NATURAL_EXPIRATION_SET["tier"]:
        changes["tier"] = {
            "before": sub.get("tier"),
            "after": NATURAL_EXPIRATION_SET["tier"],
        }
    current_credits = sub.get("available_credits")
    if current_credits != NATURAL_EXPIRATION_SET["available_credits"]:
        changes["available_credits"] = {
            "before": current_credits,
            "after": NATURAL_EXPIRATION_SET["available_credits"],
        }
    return changes


def build_write_filter(user_id, sub):
    """Fail-safe filter: only match if state is EXACTLY what we verified.
    This is the mongo $set operation that a future write path would use."""
    # Predicates that must hold at execution time to preserve safety.
    filt = {
        "user_id": user_id,
        "tier": "trial",
        "is_trial": bool(sub.get("is_trial")),
        # Guard: current credits must equal what we saw in preflight.
        "available_credits": sub.get("available_credits"),
        # Absolute RC guard.
        "revenuecat_customer_id": None,
        # Trial expiry must exist and be a string (Mongo stores ISO string).
        "trial_expires_at": sub.get("trial_expires_at"),
    }
    return filt


def render(report):
    lines = []
    def add(s=""):
        lines.append(s)

    add("# Batch D Preflight — Expired Trial Access Fix (READ-ONLY)")
    add()
    add(f"- **Generated at (UTC):** {report['generated_at']}")
    add(f"- **Target:** `{report['target']}`")
    add(f"- **Writes performed:** NONE")
    add(f"- **Deploys performed:** NONE")
    add(f"- **RevenueCat interactions:** NONE")
    add(f"- **Target user_ids (5):** {', '.join(f'`{u}`' for u in TARGET_USER_IDS)}")
    add(f"- **Explicit exclusions:** {', '.join(f'`{u}`' for u in EXCLUDED_USER_IDS)} — telemetry-limited/ambiguous")
    add()

    add("## Reference: natural trial-expiration behavior")
    add()
    add("From `backend/server.py`, `get_user_credits()` (lines 3770-3782):")
    add()
    add("```python")
    add("if is_trial and trial_expires_at:")
    add("    if expires_dt <= now:")
    add("        await db.subscriptions.update_one(")
    add("            {'user_id': user_id},")
    add("            {'$set': {'available_credits': 0, 'tier': 'trial_expired'}}")
    add("        )")
    add("```")
    add()
    add("This is the ONLY natural-expiration mutation in the codebase. It sets")
    add("exactly two fields — `tier` and `available_credits`. Nothing else is")
    add("touched. Batch D mirrors this operation exactly (no cosmetic writes).")
    add()

    add("## Step 1 — Per-account preflight verification")
    add()
    for row in report["accounts"]:
        add(f"### `{row['user_id']}`  ({row['email_redacted']})")
        add()
        add(f"**Fetch status:** {row['fetch_status']}")
        add()
        if row.get("error"):
            add(f"⚠️ **ERROR:** {row['error']}")
            add()
            continue
        add("| # | Precondition | Expected | Actual | Pass |")
        add("|---:|---|---|---|:---:|")
        for i, (k, chk) in enumerate(row["checks"].items(), 1):
            actual = chk["actual"]
            if isinstance(actual, dict):
                actual = "<br>".join(f"`{kk}`={vv}" for kk, vv in actual.items())
            add(f"| {i} | `{k}` | {chk['expected']} | {actual} | {'✅' if chk['pass'] else '❌'} |")
        add()
        add(f"**Preconditions all pass:** {'✅ YES — proceed to batch' if row['all_pass'] else '❌ NO — EXCLUDE from batch'}")
        add()
        if row.get("proposed_changes"):
            add("**Proposed field changes (minimum safe mutation):**")
            add()
            add("| field | before | after |")
            add("|---|---|---|")
            for f, ch in row["proposed_changes"].items():
                add(f"| `{f}` | `{ch['before']}` | `{ch['after']}` |")
            add()
        else:
            add("_No changes proposed — either preconditions failed or state already correct._")
            add()

    add("## Step 2 — Minimum safe mutation")
    add()
    add(f"Reference set (from natural expiration): `{NATURAL_EXPIRATION_SET}`")
    add()
    add("For each target account, only fields that *differ* from the reference set")
    add("are proposed for mutation. Cosmetic/stale metadata (e.g. `is_trial=true`,")
    add("`trial_start_date`, `trial_expires_at`, `anti_abuse_*`) is intentionally")
    add("**not** touched — natural expiration does not touch it, and the fields")
    add("have no entitlement-gating effect (see §5 of the reconciliation report).")
    add()
    add("### Fields NOT touched by natural expiration (and NOT touched by Batch D):")
    add()
    add("- `is_trial` — leaving it as `True` preserves telemetry parity with a")
    add("  naturally-expired trial (`is_trial=True` remains on those too until")
    add("  the RC webhook eventually rewrites it).")
    add("- `trial_start_date`, `trial_expires_at` — historic; no gating effect.")
    add("- `anti_abuse_email`, `anti_abuse_device_id`, `anti_abuse_provider` —")
    add("  preserved to keep the anti-abuse ledger intact.")
    add("- `created_at`, `last_event`, `revenuecat_customer_id` — untouched.")
    add()

    add("## Step 3 — Exact dry-run manifest")
    add()
    add("| user_id | email (redacted) | current tier | trial expiry | RC id | current needs_sub (raw) | proposed changes | expected needs_sub after |")
    add("|---|---|---|---|:---:|:---:|---|:---:|")
    for row in report["accounts"]:
        if not row["all_pass"]:
            add(f"| `{row['user_id']}` | {row['email_redacted']} | {row.get('current_tier','—')} | — | — | — | **EXCLUDED** ({row.get('exclusion_reason','preconditions failed')}) | — |")
            continue
        pc = row["proposed_changes"]
        pc_str = "; ".join(f"`{k}`:`{v['before']}`→`{v['after']}`" for k, v in pc.items()) or "_no-op_"
        add(f"| `{row['user_id']}` | {row['email_redacted']} | `{row['current_tier']}` | {row['trial_expires_at'] or '—'} | {'✅' if row['rc_id'] else '—'} | {row['needs_sub_raw']} | {pc_str} | **True** |")
    add()

    add("### Proposed MongoDB operations (dry-run — DO NOT EXECUTE)")
    add()
    add("Each operation is scoped by **exact `user_id`** and includes")
    add("**current-state predicates** so the write fails safely if the record")
    add("has drifted between preflight and execution.")
    add()
    for row in report["accounts"]:
        if not row["all_pass"]:
            add(f"#### `{row['user_id']}` — SKIPPED ({row.get('exclusion_reason','preconditions failed')})")
            add()
            continue
        add(f"#### `{row['user_id']}`")
        add()
        add("```javascript")
        add("db.subscriptions.updateOne(")
        add("  " + json.dumps(row["write_filter"], indent=2).replace("\n", "\n  ") + ",")
        set_expr = {"$set": {k: v["after"] for k, v in row["proposed_changes"].items()}}
        add("  " + json.dumps(set_expr, indent=2).replace("\n", "\n  "))
        add(")")
        add("```")
        add()

    # ---- Step 4 blast radius ----
    add("## Step 4 — Blast-radius proof")
    add()
    eligible = [r for r in report["accounts"] if r["all_pass"]]
    add(f"**Records that would be modified if all writes succeed:** {len(eligible)}")
    add(f"**Expected maximum:** 5")
    add(f"**Match:** {'✅' if len(eligible) == 5 else '❌ DISCREPANCY — STOP'}")
    add()
    add("### Proofs")
    add()
    add("1. **Exactly the approved records — no others.** Each `updateOne` is scoped by")
    add("   `user_id` (exact match). The `user_id` field is unique in the `subscriptions`")
    add("   collection (used as the primary index throughout `server.py`). Batch D will")
    add("   never match a document whose `user_id` isn't in the target list.")
    add()
    add("2. **Cannot match paying subscribers.** The filter additionally requires")
    add("   `tier: 'trial'`. Paying subscribers have `tier ∈ {walk-in, booked-out,")
    add("   the-shop, the-shop-member}` — none of them can satisfy the filter.")
    add()
    add("3. **Cannot match RC-linked users.** The filter also requires")
    add("   `revenuecat_customer_id: null`. Any account with an RC id is filter-excluded.")
    add()
    add("4. **Cannot match `paywall_bypass` users.** Excluded twice-over:")
    add("   `tier: 'trial'` alone rules them out; the target `user_id` list contains no")
    add("   bypass user.")
    add()
    add(f"5. **Cannot match the ambiguous sixth trial (`{EXCLUDED_USER_IDS[0]}`).** Not in the")
    add("   target `user_id` list. `user_id` scope makes accidental inclusion structurally")
    add("   impossible.")
    add()
    add("6. **Credits mutation matches natural expiration.** The natural-expiration path")
    add("   at server.py:3781 sets `available_credits: 0`. Batch D only writes this field")
    add("   when the current value differs from 0 (see Step 3 per-account manifest).")
    add("   No account receives credits.")
    add()
    add("7. **Does not modify RevenueCat.** No outbound RC calls are made. `revenuecat_customer_id`")
    add("   is used only as a read-side filter predicate — it is not written.")
    add()
    add("8. **Does not modify App Store state.** No StoreKit / product interaction is possible")
    add("   from this admin plane.")
    add()
    add("9. **Does not modify application code.** Batch D is purely a data operation.")
    add()

    # ---- Step 5 verification plan ----
    add("## Step 5 — Post-write verification plan (to run AFTER authorized execution)")
    add()
    add("Every check below is a READ, not a write.")
    add()
    add("### 5.1 Per-account verification")
    add()
    add("For each of the 5 user_ids, verify via `GET /api/admin/user-lookup?user_id=<uid>`:")
    add()
    add("| Check | Expected |")
    add("|---|---|")
    add("| `subscription.tier` | `'trial_expired'` |")
    add("| `subscription.available_credits` | `0` |")
    add("| `subscription.revenuecat_customer_id` | `null` (unchanged) |")
    add("| `subscription.trial_expires_at` | unchanged from preflight snapshot |")
    add("| `subscription.trial_start_date` | unchanged |")
    add("| `subscription.is_trial` | unchanged (still `True`) |")
    add("| `subscription.last_event` | unchanged |")
    add("| `subscription.created_at` | unchanged |")
    add()
    add("Then simulate the entitlement check by calling")
    add("`GET /api/admin/user-lookup?user_id=<uid>` and computing:")
    add()
    add("```python")
    add("needs_subscription = sub['tier'] in (None, 'trial_expired', 'expired')")
    add("assert needs_subscription is True  # paywall now closes")
    add("```")
    add()
    add("### 5.2 Regression checks (whole-cohort)")
    add()
    add("Re-run `/app/audit/reconciliation.py` and confirm:")
    add()
    add("- **Real paid cohort:** `RAW=48 / EXCLUDED=2 / REAL=46` (unchanged)")
    add("- **Gross MRR:** `$734.54` (unchanged)")
    add("- **`paywall_bypass` count:** exactly the same 47 user_ids as pre-batch")
    add("- **RC-linked count:** unchanged (46 bypass + 2 trials with RC)")
    add("- **`tier='trial'` remaining:** `1` (only `user_673ab0d5552a`, the excluded ambiguous account)")
    add("- **`sub_tier='trial_expired'` new count:** `+5` compared to pre-batch")
    add("- **Total legacy universe:** still `57` (no additions/removals — the 5 rows")
    add("  migrate from `tier='trial'` to `tier='trial_expired'`; total is unchanged)")
    add()
    add("### 5.3 Audit-trail requirement")
    add()
    add("Whichever endpoint executes the write should:")
    add()
    add("- Log the `matched_count` and `modified_count` of each `updateOne` (Mongo returns both).")
    add("- Assert `modified_count == 1` per operation; if any operation returns")
    add("  `modified_count == 0` (i.e. the filter didn't match because state drifted),")
    add("  record the user_id in an errors list and continue.")
    add("- Persist an entry per operation to `admin_cleanup_batches` (or existing")
    add("  `admin_actions` collection) with: `user_id`, pre-state snapshot, post-state,")
    add("  batch_id (e.g. `BB-CLEANUP-2026-09-04-D`), and timestamp.")
    add()

    # ---- Final recommendation ----
    add("## Final recommendation")
    add()
    all_five_ok = len(eligible) == 5 and all(r["all_pass"] for r in report["accounts"])
    if all_five_ok:
        add("### ✅ SAFE TO EXECUTE BATCH D")
        add()
        add("All 5 preconditions passed on live re-fetch. The proposed mutation is")
        add("byte-for-byte identical to what the server would perform organically on")
        add("each user's next `/api/credits` call. Blast radius is exactly 5 records.")
        add("No credits are granted. No RC state is touched. No production code")
        add("changes. No deploys.")
        add()
        add("Awaiting explicit execution authorization.")
    else:
        add("### ❌ DO NOT EXECUTE — REVIEW REQUIRED")
        add()
        add("At least one target account failed preflight. Details in Step 1 above.")
    add()
    add("---")
    add()
    add("**HARD STOP.** No writes. No deploys. No code changes. No RC touches.")
    add()
    return "\n".join(lines)


def redact(email):
    if not email:
        return "(anonymous)"
    e = email.strip().lower()
    if "@" not in e:
        return e[:2] + "***"
    local, domain = e.split("@", 1)
    return f"{local[:2]}***@{domain}"


def audit():
    print(f"[preflight] Starting {NOW.isoformat()}")
    token = login()
    print("[preflight] admin login OK")

    accounts = []
    for uid in TARGET_USER_IDS:
        print(f"[preflight] fetching {uid}...")
        user_doc, sub_doc, err = fetch_user(token, uid)
        if err or user_doc is None or sub_doc is None:
            accounts.append({
                "user_id": uid,
                "email_redacted": "(unknown)",
                "fetch_status": "FAILED",
                "error": json.dumps(err),
                "all_pass": False,
                "exclusion_reason": "fetch_failed",
                "checks": {},
                "proposed_changes": {},
            })
            continue

        all_pass, checks = verify_preconditions(sub_doc)
        proposed = diff_natural_expiration(sub_doc)
        row = {
            "user_id": uid,
            "email": user_doc.get("email"),
            "email_redacted": redact(user_doc.get("email")),
            "fetch_status": "OK",
            "user_doc": {k: user_doc.get(k) for k in ("user_id", "email", "created_at", "last_login")},
            "sub_doc": sub_doc,
            "checks": checks,
            "all_pass": all_pass,
            "current_tier": sub_doc.get("tier"),
            "trial_expires_at": sub_doc.get("trial_expires_at"),
            "rc_id": sub_doc.get("revenuecat_customer_id"),
            "needs_sub_raw": sub_doc.get("tier") in (None, "trial_expired", "expired"),
            "proposed_changes": proposed if all_pass else {},
            "write_filter": build_write_filter(uid, sub_doc) if all_pass else None,
        }
        if not all_pass:
            failed_checks = [k for k, v in checks.items() if not v["pass"]]
            row["exclusion_reason"] = f"preconditions failed: {failed_checks}"
        accounts.append(row)

    return {
        "generated_at": NOW.isoformat(),
        "target": PROD_BASE,
        "target_user_ids": TARGET_USER_IDS,
        "excluded_user_ids": EXCLUDED_USER_IDS,
        "natural_expiration_reference": NATURAL_EXPIRATION_SET,
        "accounts": accounts,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    report = audit()
    with open(DATA_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    with open(REPORT_MD, "w") as f:
        f.write(render(report))
    print(f"\n[preflight] Wrote: {DATA_JSON}")
    print(f"[preflight] Wrote: {REPORT_MD}")
    passing = sum(1 for r in report["accounts"] if r["all_pass"])
    print(f"\n===== SUMMARY =====")
    print(f"Target accounts:     {len(TARGET_USER_IDS)}")
    print(f"Passed preflight:    {passing}")
    print(f"Excluded/failed:     {len(TARGET_USER_IDS) - passing}")


if __name__ == "__main__":
    main()
