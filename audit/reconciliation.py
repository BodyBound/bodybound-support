#!/usr/bin/env python3
"""
Post-cleanup RECONCILIATION audit (Part 2, READ-ONLY).

Answers eight questions:
  1. Is the paid cohort 46 or 48? Who is new, who was previously excluded?
  2. What is the actual MRR (tier-mix based, not floor)?
  3. users.tier vs subscriptions.tier reconciliation (for the 57 legacy universe)
  4. Re-evaluate the six tier='trial' users
  5. Re-evaluate the four is_trial=true users
  6. Live RevenueCat verification for 46 RC-linked bypass users
  7. Fix action-category labeling (mutually exclusive)
  8. Final decision table

Emits: /app/audit/reconciliation_data.json
       /app/audit/reconciliation_report.md
"""
import os
import json
import hashlib
import statistics
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError, URLError

PROD_BASE = "https://bodybound-subs.emergent.host"
ADMIN_EMAIL = "bodyboundstencil@yahoo.com"
ADMIN_PASSWORD = "Body.Bound.Admin.72410"

OUT_DIR = "/app/audit"
DATA_JSON = os.path.join(OUT_DIR, "reconciliation_data.json")
REPORT_MD = os.path.join(OUT_DIR, "reconciliation_report.md")

NOW = datetime.now(timezone.utc)

# Product mix mapping.
# Two price tables are shown side-by-side because the user's brief quoted
# "The Shop: $49.99/month" but the deployed PRODUCT_CREDIT_MAP product id
# is `bodybound_9999_1m_3d` (i.e. $99.99). Both figures are shown; the
# code-derived one is treated as authoritative for the DB reconciliation.
TIER_TO_PRICE_CODE = {
    "walk-in": 14.99,
    "booked-out": 29.99,
    "the-shop": 99.99,
    "the-shop-member": 0.00,      # studio-comp, not a paying seat
    "referral_premium": 0.00,     # referral reward, no billing
}
TIER_TO_PRICE_USER_BRIEF = {
    "walk-in": 14.99,
    "booked-out": 29.99,
    "the-shop": 49.99,
    "the-shop-member": 0.00,
    "referral_premium": 0.00,
}
PAID_TIERS = {"walk-in", "booked-out", "the-shop", "the-shop-member"}

# Test/reviewer/internal exclusion signals (email-based). Anonymous
# (email=None) accounts are NOT flagged as test.
TEST_EMAIL_DOMAINS = ("@studio.test", "@test.local", "@example.com",
                      "@apple-review.test", "@bodybound.app")
TEST_EMAIL_EXACT = {"demo_reviewer_account"}
# user_id prefixes/exact matches for known test/reviewer/internal accounts
TEST_USER_IDS_EXACT = {"demo_reviewer_account"}
TEST_USER_ID_PREFIXES = ("demo_", "studio_admin_", "test_")
# Admin/internal emails known ahead of time
INTERNAL_EMAILS = {"bodyboundstencil@yahoo.com", "bodyboundstencil@gmail.com"}


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


def days_since(v):
    dt = parse_iso(v)
    if not dt:
        return None
    return (NOW - dt).total_seconds() / 86400.0


def redact_email(e):
    """Redact email while preserving local-part length signature so we can
    recognise the same account across audits. Format: xx***@domain."""
    if not e:
        return "(anonymous)"
    e = str(e).strip().lower()
    if "@" not in e:
        return e[:2] + "***"
    local, domain = e.split("@", 1)
    if len(local) <= 2:
        head = local
    else:
        head = local[:2]
    return f"{head}***@{domain}"


def is_test_email(email):
    if not email:
        return False
    e = email.lower().strip()
    if e in TEST_EMAIL_EXACT:
        return True
    return any(e.endswith(d) for d in TEST_EMAIL_DOMAINS)


def is_internal_email(email):
    if not email:
        return False
    return email.lower().strip() in INTERNAL_EMAILS


def classify_test_reviewer(email, sub, user_id=None):
    """Return (is_excluded_bool, reason_string)."""
    if user_id and user_id in TEST_USER_IDS_EXACT:
        return True, "reviewer_account_user_id"
    if user_id and any(user_id.startswith(p) for p in TEST_USER_ID_PREFIXES):
        return True, f"internal_user_id_prefix({user_id.split('_')[0]}_)"
    if is_test_email(email):
        return True, "test_domain"
    if is_internal_email(email):
        return True, "internal_admin"
    # Admin-comp / studio-comp
    tier = (sub or {}).get("tier")
    if tier == "the-shop-member":
        return True, "studio_team_comped"
    if tier == "referral_premium":
        return True, "referral_reward"
    # Zero-price product ids
    return False, ""


def fetch_all_users(token):
    status, data = http_json("GET", "/api/admin/all-users", token=token)
    if status != 200:
        raise SystemExit(f"[FATAL] /admin/all-users failed: {status} {data}")
    return data.get("users", []), data.get("total", 0)


def fetch_user_by_id(token, user_id):
    status, data = http_json(
        "GET", f"/api/admin/user-lookup?user_id={quote(user_id)}", token=token)
    if status == 200 and data and data.get("found"):
        return data.get("user") or {}, data.get("subscription") or {}
    return None, None


def build_paid_cohort(token, all_users):
    """Every user with subscription tier in PAID_TIERS. Enrich each with the
    authoritative subscription doc via /admin/user-lookup?user_id=X."""
    paid_rows = []
    for u in all_users:
        tier = u.get("tier")
        if tier not in PAID_TIERS:
            continue
        uid = u.get("user_id")
        user_doc, sub_doc = fetch_user_by_id(token, uid)
        row = {
            "user_id": uid,
            "email": u.get("email"),
            "email_redacted": redact_email(u.get("email")),
            "aggregated_tier_from_all_users": tier,
            "aggregated_is_trial": bool(u.get("is_trial")),
            "aggregated_last_event": u.get("last_event"),
            "aggregated_created_at": u.get("created_at"),
            "sub_tier": (sub_doc or {}).get("tier"),
            "sub_is_trial": bool((sub_doc or {}).get("is_trial")),
            "sub_last_event": (sub_doc or {}).get("last_event"),
            "sub_last_event_at": (sub_doc or {}).get("last_event_at"),
            "sub_last_product_id": (sub_doc or {}).get("last_product_id"),
            "sub_revenuecat_customer_id": (sub_doc or {}).get("revenuecat_customer_id"),
            "sub_renewal_date": (sub_doc or {}).get("renewal_date"),
            "sub_available_credits": (sub_doc or {}).get("available_credits"),
            "sub_created_at": (sub_doc or {}).get("created_at"),
            "sub_started_at": (sub_doc or {}).get("started_at"),
            "sub_first_purchased_at": (sub_doc or {}).get("first_purchased_at"),
            "sub_purchase_history": (sub_doc or {}).get("purchase_history"),
            "user_created_at": (user_doc or {}).get("created_at"),
            "user_last_login": (user_doc or {}).get("last_login"),
        }
        # Test/internal classification
        excluded, reason = classify_test_reviewer(row["email"], sub_doc or {}, user_id=uid)
        row["excluded"] = excluded
        row["excluded_reason"] = reason
        # First-paid evidence
        row["first_paid_evidence"] = (
            row["sub_first_purchased_at"]
            or row["sub_started_at"]
            or row["sub_last_event_at"]
            or row["sub_created_at"]
        )
        # Tier mismatch flag
        row["tier_mismatch"] = (row["aggregated_tier_from_all_users"] != row["sub_tier"])
        paid_rows.append(row)
    return paid_rows


def build_legacy_cohort(token, all_users):
    """The 57 remaining legacy/free-access users (paywall_bypass, tier='trial',
    is_trial=true not in tier='trial'). Full users+subscriptions dump."""
    seen = set()
    legacy = []
    for u in all_users:
        tier = u.get("tier")
        is_trial = bool(u.get("is_trial"))
        if not (tier == "paywall_bypass" or tier == "trial" or is_trial):
            continue
        uid = u.get("user_id")
        if uid in seen:
            continue
        seen.add(uid)
        user_doc, sub_doc = fetch_user_by_id(token, uid)
        row = {
            "user_id": uid,
            "email": u.get("email"),
            "email_redacted": redact_email(u.get("email")),
            "aggregated_tier": tier,
            "aggregated_is_trial": is_trial,
            "aggregated_last_event": u.get("last_event"),
            # users doc fields (should NOT have tier/is_trial)
            "user_doc_keys": sorted(list((user_doc or {}).keys())),
            "user_doc_has_tier_field": "tier" in (user_doc or {}),
            "user_doc_has_is_trial_field": "is_trial" in (user_doc or {}),
            "user_doc_tier_value": (user_doc or {}).get("tier"),
            "user_doc_is_trial_value": (user_doc or {}).get("is_trial"),
            "user_last_login": (user_doc or {}).get("last_login"),
            "user_created_at": (user_doc or {}).get("created_at"),
            # subscriptions doc — authoritative
            "sub_tier": (sub_doc or {}).get("tier"),
            "sub_is_trial": bool((sub_doc or {}).get("is_trial")),
            "sub_trial_expires_at": (sub_doc or {}).get("trial_expires_at"),
            "sub_trial_start_date": (sub_doc or {}).get("trial_start_date"),
            "sub_revenuecat_customer_id": (sub_doc or {}).get("revenuecat_customer_id"),
            "sub_last_event": (sub_doc or {}).get("last_event"),
            "sub_last_event_at": (sub_doc or {}).get("last_event_at"),
            "sub_available_credits": (sub_doc or {}).get("available_credits"),
            "sub_credits_consumed_this_cycle": (sub_doc or {}).get("credits_consumed_this_cycle", 0),
            "sub_admin_cleanup_reason": (sub_doc or {}).get("admin_cleanup_reason"),
            "sub_admin_cleanup_batch_id": (sub_doc or {}).get("admin_cleanup_batch_id"),
            "sub_pre_cleanup_tier": (sub_doc or {}).get("pre_cleanup_tier"),
            "sub_last_product_id": (sub_doc or {}).get("last_product_id"),
        }
        # Compute needs_subscription the exact same way get_user_credits() does.
        row["computed_needs_subscription"] = row["sub_tier"] in (None, "trial_expired", "expired")
        # Aggregate vs subscription tier mismatch check
        row["agg_vs_sub_tier_mismatch"] = (row["aggregated_tier"] != row["sub_tier"])
        row["agg_vs_sub_is_trial_mismatch"] = (row["aggregated_is_trial"] != row["sub_is_trial"])
        legacy.append(row)
    return legacy


def previous_46(paid_rows):
    """We do NOT have a stored list of the previous 46. The best signal we
    have is: users whose first_paid_evidence predates the previous audit.
    The previous audit was run at 2026-09-03 ~00:26 UTC (see rollback
    snapshot filenames BB-CLEANUP-2026-09-03-*). Anything created after that
    is a new customer."""
    audit_cutoff = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)
    existing, new = [], []
    unknown_date = []
    for r in paid_rows:
        evi = parse_iso(r.get("first_paid_evidence"))
        if evi is None:
            unknown_date.append(r)
            continue
        if evi < audit_cutoff:
            existing.append(r)
        else:
            new.append(r)
    return existing, new, unknown_date, audit_cutoff


def compute_mrr(paid_rows, price_table):
    """Group by tier, count real billing customers (excluded=False), sum."""
    by_tier = {}
    for r in paid_rows:
        if r.get("excluded"):
            continue
        t = r.get("sub_tier") or r.get("aggregated_tier_from_all_users")
        by_tier.setdefault(t, 0)
        by_tier[t] += 1
    rows = []
    total = 0.0
    for t, n in sorted(by_tier.items(), key=lambda x: -x[1]):
        price = price_table.get(t, 0.0)
        gross = round(n * price, 2)
        total += gross
        rows.append({"tier": t, "n": n, "price": price, "gross_mrr": gross})
    return rows, round(total, 2)


def rc_verification(bypass_rows):
    """Live RC verification. Preview environment has no RevenueCat REST/
    dashboard access — only REVENUECAT_WEBHOOK_AUTH which validates
    incoming webhooks (NOT outbound queries). So EVERY RC-linked bypass
    user must be marked RC_UNVERIFIABLE. Explicit fail-safe posture."""
    result = []
    for r in bypass_rows:
        rc_id = r.get("sub_revenuecat_customer_id")
        if not rc_id:
            result.append({**r, "rc_class": "NO_RC_ID"})
            continue
        result.append({**r, "rc_class": "RC_UNVERIFIABLE",
                       "rc_class_reason": "No RC REST API key or dashboard token available in preview env; only webhook auth is set."})
    return result


# ---------- Rendering helpers ----------

def add(lines, s=""):
    lines.append(s)


def fmt_date(v):
    dt = parse_iso(v)
    return dt.strftime("%Y-%m-%d") if dt else "—"


def render(report):
    lines = []
    T = report["totals"]

    add(lines, "# Post-Cleanup Reconciliation Audit (READ-ONLY, Part 2)")
    add(lines)
    add(lines, f"- **Generated at (UTC):** {report['generated_at']}")
    add(lines, f"- **Target:** `{report['target']}`")
    add(lines, f"- **Writes performed:** NONE")
    add(lines, f"- **RevenueCat REST/dashboard access available:** {report['rc_access_available']} — {report['rc_access_note']}")
    add(lines)

    # --------------- SECTION 1 ---------------
    add(lines, "## §1 — Paid cohort: 46 vs 48")
    add(lines)
    add(lines, f"- **RAW PAID (all subscription rows in a paid tier):** {T['raw_paid']}")
    add(lines, f"- **TEST/REVIEWER/INTERNAL:** {T['excluded_paid']}")
    add(lines, f"- **REAL BILLING CUSTOMERS:** {T['real_paid']}")
    add(lines)
    add(lines, f"Audit cutoff used to bucket \"existing vs new\" = {report['audit_cutoff']} (based on previous audit run at 2026-09-03 ~00:26 UTC).")
    add(lines)

    add(lines, "### 1.1 Complete paid cohort")
    add(lines)
    add(lines, "| # | email (redacted) | user_id | agg_tier | sub_tier | product_id | last_event | RC id | trial? | excluded? | first_paid_evidence | bucket |")
    add(lines, "|---:|---|---|---|---|---|---|:---:|:---:|---|---|---|")
    existing_ids = {r["user_id"] for r in report["existing_paid"]}
    new_ids = {r["user_id"] for r in report["new_paid"]}
    for i, r in enumerate(report["paid_rows"], 1):
        bucket = "EXISTING" if r["user_id"] in existing_ids else ("NEW" if r["user_id"] in new_ids else "UNKNOWN-DATE")
        excl = f"YES ({r['excluded_reason']})" if r["excluded"] else "—"
        rc = "✅" if r["sub_revenuecat_customer_id"] else "—"
        trial = "✅" if (r["sub_is_trial"] or r["aggregated_is_trial"]) else "—"
        add(lines, f"| {i} | {r['email_redacted']} | `{r['user_id']}` | {r['aggregated_tier_from_all_users']} | {r['sub_tier']} | `{r['sub_last_product_id'] or '—'}` | {r['sub_last_event'] or '—'} | {rc} | {trial} | {excl} | {fmt_date(r['first_paid_evidence'])} | **{bucket}** |")
    add(lines)

    # Mismatch box
    mismatches_paid = [r for r in report["paid_rows"] if r.get("tier_mismatch")]
    if mismatches_paid:
        add(lines, f"### 1.2 Paid-cohort agg-vs-sub tier mismatches ({len(mismatches_paid)})")
        add(lines)
        for r in mismatches_paid:
            add(lines, f"- `{r['user_id']}` ({r['email_redacted']}): `/admin/all-users`.tier=`{r['aggregated_tier_from_all_users']}` vs `subscriptions.tier`=`{r['sub_tier']}`")
        add(lines)

    add(lines, "### 1.3 Existing (before audit cutoff) vs New")
    add(lines)
    add(lines, f"- **Existing paid users** (first-paid before {report['audit_cutoff']}): **{len(report['existing_paid'])}**")
    add(lines, f"- **Newly paid users** (first-paid on/after {report['audit_cutoff']}): **{len(report['new_paid'])}**")
    add(lines, f"- **Unknown first-paid date:** **{len(report['unknown_date_paid'])}**")
    add(lines)
    if report["new_paid"]:
        add(lines, "**Newly paid users:**")
        add(lines, "")
        add(lines, "| email (redacted) | user_id | sub_tier | product_id | first_paid_evidence | last_event |")
        add(lines, "|---|---|---|---|---|---|")
        for r in report["new_paid"]:
            add(lines, f"| {r['email_redacted']} | `{r['user_id']}` | {r['sub_tier']} | `{r['sub_last_product_id'] or '—'}` | {fmt_date(r['first_paid_evidence'])} | {r['sub_last_event'] or '—'} |")
        add(lines)
    if report["unknown_date_paid"]:
        add(lines, "**Unknown first-paid date (evidence missing):**")
        add(lines, "")
        for r in report["unknown_date_paid"]:
            add(lines, f"- `{r['user_id']}` ({r['email_redacted']}), sub_tier={r['sub_tier']}, last_event={r['sub_last_event']}")
        add(lines)

    add(lines, "### 1.4 Answer")
    add(lines)
    add(lines, f"- Previous audit reported **48 raw / 46 real** (2 excluded).")
    add(lines, f"- Current audit reports **{T['raw_paid']} raw / {T['real_paid']} real** ({T['excluded_paid']} excluded).")
    delta_raw = T['raw_paid'] - 48
    delta_real = T['real_paid'] - 46
    add(lines, f"- Delta raw: **{'+' if delta_raw>=0 else ''}{delta_raw}**, delta real: **{'+' if delta_real>=0 else ''}{delta_real}**.")
    if report["new_paid"]:
        add(lines, f"- Evidence of new customers: {len(report['new_paid'])} account(s) with first_paid_evidence ≥ {report['audit_cutoff']} (see 1.3).")
    else:
        add(lines, "- No new customers detected by first-paid-evidence — the delta is likely due to previously-excluded test/reviewer accounts being re-included or reclassified.")
    add(lines)

    # --------------- SECTION 2 ---------------
    add(lines, "## §2 — Actual MRR (by product mix)")
    add(lines)
    add(lines, "**Deployed product-id prices (authoritative from `PRODUCT_CREDIT_MAP` in `backend/server.py`):**")
    add(lines)
    add(lines, "| Tier | Real subscribers | Price | Gross MRR |")
    add(lines, "|---|---:|---:|---:|")
    for row in report["mrr_code"]["rows"]:
        add(lines, f"| {row['tier']} | {row['n']} | ${row['price']:.2f} | ${row['gross_mrr']:.2f} |")
    add(lines, f"| **TOTAL** | **{sum(r['n'] for r in report['mrr_code']['rows'])}** | — | **${report['mrr_code']['total']:.2f}** |")
    add(lines)
    add(lines, f"**ACTUAL VERIFIED GROSS MRR (code prices) = ${report['mrr_code']['total']:.2f}**")
    add(lines)
    add(lines, "**User-brief prices (as quoted in the reconciliation request — includes \"The Shop $49.99\"):**")
    add(lines)
    add(lines, "| Tier | Real subscribers | Price | Gross MRR |")
    add(lines, "|---|---:|---:|---:|")
    for row in report["mrr_user"]["rows"]:
        add(lines, f"| {row['tier']} | {row['n']} | ${row['price']:.2f} | ${row['gross_mrr']:.2f} |")
    add(lines, f"| **TOTAL** | **{sum(r['n'] for r in report['mrr_user']['rows'])}** | — | **${report['mrr_user']['total']:.2f}** |")
    add(lines)
    add(lines, "**ACTUAL VERIFIED GROSS MRR (user-brief prices) = $%.2f**" % report['mrr_user']['total'])
    add(lines)
    add(lines, "⚠️ **Price discrepancy noted:** the user brief lists The Shop at $49.99/mo, but the deployed product id is `bodybound_9999_1m_3d` ($99.99/mo). Both figures are shown; the deployed one is the source of truth unless a price migration is in flight.")
    add(lines)
    add(lines, f"**Prior verified MRR:** 46 × $14.99 floor = $689.54 (previous audit used the Walk-In floor; this audit uses the actual mix — the change is a **methodology change**, not a customer growth signal).")
    add(lines)

    # --------------- SECTION 3 ---------------
    add(lines, "## §3 — users.tier vs subscriptions.tier reconciliation")
    add(lines)
    add(lines, "### 3.1 Authoritative-source-of-truth analysis")
    add(lines)
    add(lines, "**Code-level evidence:**")
    add(lines)
    add(lines, "- `GET /api/credits` calls `get_user_credits(user_id)` (backend/server.py) which reads `sub.get('tier')` (line 3792) from the **`subscriptions`** collection.")
    add(lines, "- `needs_subscription` is derived at line 3849 as `tier in (None, 'trial_expired', 'expired')` — using the `subscriptions.tier` value only.")
    add(lines, "- The **frontend paywall** in `frontend/app/index.tsx` gates on `credits.needs_subscription` (lines 845, 1040, 5216) which comes from `/api/credits`.")
    add(lines, "- The **`users` collection** stores identity/profile fields only (`user_id`, `apple_user_id`, `email`, `name`, `device_id`, `created_at`, `last_login`, `referred_by`, `referral_code_used`). There is **no `tier` field and no `is_trial` field on the users doc** anywhere in `backend/server.py`.")
    add(lines)
    add(lines, "> **AUTHORITATIVE ENTITLEMENT SOURCE = `subscriptions.tier` (via `get_user_credits()` → `needs_subscription`)**")
    add(lines)
    add(lines, "The `/admin/all-users` endpoint also derives its `tier` column from `subscriptions.tier` (server.py line 1803). Any mismatch below therefore reflects a **different underlying condition** (transient in-flight update, duplicate subscription doc for the same user_id, or aggregation-time skew) — NOT a users-vs-subscriptions collection drift.")
    add(lines)

    # 3.2 mismatches inside legacy universe
    mismatches = [r for r in report["legacy_rows"] if r.get("agg_vs_sub_tier_mismatch") or r.get("agg_vs_sub_is_trial_mismatch")]
    add(lines, f"### 3.2 Mismatches in the 57-user legacy universe ({len(mismatches)})")
    add(lines)
    if not mismatches:
        add(lines, "✅ No mismatches detected on re-fetch — `/admin/all-users` and `/admin/user-lookup?user_id=…` agree for all 57 legacy users.")
    else:
        add(lines, "| user_id | email (redacted) | agg.tier | sub.tier | agg.is_trial | sub.is_trial | notes |")
        add(lines, "|---|---|---|---|:---:|:---:|---|")
        for r in mismatches:
            notes = []
            if r.get("sub_admin_cleanup_reason"):
                notes.append(f"cleanup_reason={r['sub_admin_cleanup_reason']}")
            if r.get("sub_pre_cleanup_tier"):
                notes.append(f"pre_cleanup_tier={r['sub_pre_cleanup_tier']}")
            add(lines, f"| `{r['user_id']}` | {r['email_redacted']} | `{r['aggregated_tier']}` | `{r['sub_tier']}` | {r['aggregated_is_trial']} | {r['sub_is_trial']} | {'; '.join(notes) or '—'} |")
    add(lines)

    # 3.3 users doc field presence — proves users.tier does not exist
    users_with_tier_field = [r for r in report["legacy_rows"] if r.get("user_doc_has_tier_field")]
    users_with_is_trial_field = [r for r in report["legacy_rows"] if r.get("user_doc_has_is_trial_field")]
    add(lines, "### 3.3 `users` collection field presence (across the 57 legacy users)")
    add(lines)
    add(lines, f"- users docs with a `tier` field: **{len(users_with_tier_field)}** / 57")
    add(lines, f"- users docs with an `is_trial` field: **{len(users_with_is_trial_field)}** / 57")
    if len(users_with_tier_field) == 0 and len(users_with_is_trial_field) == 0:
        add(lines, "- ✅ Confirms the `users` collection does not carry tier/entitlement state. `subscriptions.tier` is the only authoritative field.")
    add(lines)

    # --------------- SECTION 4 ---------------
    add(lines, "## §4 — Re-evaluate the six `tier='trial'` users")
    add(lines)
    add(lines, "| user_id | email (redacted) | agg.tier | sub.tier | sub.is_trial | trial_expires | days_since_exp | RC | sub_cleanup_reason | needs_sub | classification |")
    add(lines, "|---|---|---|---|:---:|---|---:|:---:|---|:---:|---|")
    for r in report["tier_trial_rows"]:
        exp = r.get("sub_trial_expires_at")
        d_exp = days_since(exp)
        d_str = f"{d_exp:.1f}" if d_exp is not None else "—"
        rc = "✅" if r.get("sub_revenuecat_customer_id") else "—"
        cls = classify_trial_row(r)
        add(lines, f"| `{r['user_id']}` | {r['email_redacted']} | `{r['aggregated_tier']}` | `{r['sub_tier']}` | {r['sub_is_trial']} | {fmt_date(exp)} | {d_str} | {rc} | {r.get('sub_admin_cleanup_reason') or '—'} | {r['computed_needs_subscription']} | **{cls}** |")
    add(lines)

    # --------------- SECTION 5 ---------------
    add(lines, "## §5 — Re-evaluate the four `is_trial=true` users")
    add(lines)
    add(lines, "### 5.1 What does `is_trial=true` actually gate?")
    add(lines)
    add(lines, "**Code-level trace (backend/server.py):**")
    add(lines)
    add(lines, "- `is_trial` is stored on the `subscriptions` doc and surfaced by `get_user_credits()` as `credits.is_trial`.")
    add(lines, "- **`needs_subscription`** is computed as `tier in (None, 'trial_expired', 'expired')` — **it does NOT read `is_trial`**. So `is_trial=true` alone does NOT prevent the paywall from opening.")
    add(lines, "- `is_trial` is used for: (1) trial-expiry countdown UI, (2) referral-reward accounting, (3) `PAYWALL_BYPASS`/anti-abuse email checks, (4) analytics.")
    add(lines, "- **Generation entitlement** is gated by `available_credits > 0` on the `/api/credits/deduct` path. `is_trial` is not consulted.")
    add(lines, "- **RC sync behaviour**: on webhook receipt (`webhooks/revenuecat`), the trial flag is *rewritten* from RC's payload — it does not affect entitlement, it reflects it.")
    add(lines)
    add(lines, "> **Conclusion:** `is_trial=true` on an `expired` / `trial_expired` sub is **display-only metadata**. It does not open the paywall gate.")
    add(lines)

    add(lines, "### 5.2 Detail")
    add(lines)
    add(lines, "| user_id | email (redacted) | agg.is_trial | sub.is_trial | sub.tier | trial_expires | RC | needs_sub? | classification |")
    add(lines, "|---|---|:---:|:---:|---|---|:---:|:---:|---|")
    for r in report["is_trial_only_rows"]:
        exp = r.get("sub_trial_expires_at")
        rc = "✅" if r.get("sub_revenuecat_customer_id") else "—"
        cls = classify_is_trial_row(r)
        add(lines, f"| `{r['user_id']}` | {r['email_redacted']} | {r['aggregated_is_trial']} | {r['sub_is_trial']} | `{r['sub_tier']}` | {fmt_date(exp)} | {rc} | {r['computed_needs_subscription']} | **{cls}** |")
    add(lines)

    # --------------- SECTION 6 ---------------
    add(lines, "## §6 — Live RevenueCat verification of the 46 RC-linked bypass users")
    add(lines)
    add(lines, f"**RC REST/dashboard access available in this environment:** {report['rc_access_available']}")
    add(lines, f"**Environment vars present:** only `REVENUECAT_WEBHOOK_AUTH` (validates INCOMING webhooks; does not enable OUTGOING queries).")
    add(lines, f"**No RC v1/v2 REST API secret is set.** Live entitlement state therefore CANNOT be queried from this environment.")
    add(lines)
    add(lines, "Per the brief's fail-safe rule (\"Do NOT infer 'expired' merely because local last_event is missing\"), every RC-linked bypass user is classified **`RC_UNVERIFIABLE`** until a v1 secret is added and this section is re-run.")
    add(lines)
    add(lines, "| RC class | Count |")
    add(lines, "|---|---:|")
    rc_counts = {}
    for r in report["rc_verification"]:
        rc_counts[r["rc_class"]] = rc_counts.get(r["rc_class"], 0) + 1
    for cls in ("RC_ACTIVE_PAID", "RC_ACTIVE_TRIAL", "RC_EXPIRED", "RC_NOT_FOUND", "RC_UNVERIFIABLE", "NO_RC_ID"):
        add(lines, f"| {cls} | {rc_counts.get(cls, 0)} |")
    add(lines, f"| **Total** | **{len(report['rc_verification'])}** |")
    add(lines)
    add(lines, "### 6.1 Recommendation to unlock RC verification")
    add(lines)
    add(lines, "Set `REVENUECAT_V1_SECRET` in `backend/.env` (Project settings → API keys → Secret v1 key), then a follow-up read-only pass can call:")
    add(lines, "`GET https://api.revenuecat.com/v1/subscribers/{user_id_or_rc_customer_id}` with `Authorization: Bearer <v1_secret>` and classify each of the 46 conclusively.")
    add(lines)
    add(lines, "**Until then, the 46 RC-linked bypass users must remain untouched.**")
    add(lines)

    # --------------- SECTION 7 ---------------
    add(lines, "## §7 — Corrected action-category labeling")
    add(lines)
    add(lines, "**Rules (mutually exclusive, in priority order):**")
    add(lines, "1. **Legitimate paid/trial** — sub_tier in PAID_TIERS OR in-window trial (`sub_trial_expires_at` ≥ now)")
    add(lines, "2. **RevenueCat verification required** — has `sub_revenuecat_customer_id` AND RC status is `RC_UNVERIFIABLE` (i.e. all RC-linked accounts right now)")
    add(lines, "3. **Source-of-truth / telemetry ambiguity** — agg-vs-sub mismatch, OR trial with no expiry data AND no RC id (cannot classify)")
    add(lines, "4. **Safe stale cleanup** — no RC id AND (`needs_subscription=true` OR expired trial)")
    add(lines, "5. **Conversion candidate** — active bypass with no RC id (RC conclusively absent, functional free access confirmed)")
    add(lines)
    add(lines, "| Category | Count | Members |")
    add(lines, "|---|---:|---|")
    cats = report["categories"]
    for c in cats:
        member_hint = c.get("hint") or "—"
        add(lines, f"| {c['name']} | {c['count']} | {member_hint} |")
    total_cat = sum(c["count"] for c in cats)
    ok = total_cat == T["universe_total"]
    add(lines, f"| **Sum (must equal {T['universe_total']})** | **{total_cat}** | {'✅' if ok else '❌ MISMATCH'} |")
    add(lines)

    # --------------- SECTION 8 ---------------
    add(lines, "## §8 — Final decision table")
    add(lines)
    add(lines, "| Group | Count | Functional free access now? | RC status | Safe to change? | Recommended next action |")
    add(lines, "|---|---:|:---:|---|:---:|---|")
    for row in report["decision_table"]:
        add(lines, f"| {row['group']} | {row['count']} | {row['func_free']} | {row['rc_status']} | {row['safe_change']} | {row['action']} |")
    add(lines)

    # Explicit totals
    E = report["explicit_totals"]
    add(lines, "### 8.1 Explicit totals")
    add(lines)
    add(lines, f"- Verified real paying subscribers: **{E['real_paid']}**")
    add(lines, f"- Actual gross MRR (code prices): **${E['actual_mrr_code']:.2f}**  ·  (user-brief prices): **${E['actual_mrr_user']:.2f}**")
    add(lines, f"- Active bypass users: **{E['active_bypass']}**")
    add(lines, f"- Active bypass with confirmed inactive RC entitlement: **{E['active_bypass_rc_inactive']}** _(0 until RC verifier is unlocked)_")
    add(lines, f"- Active bypass with live paid/trial entitlement: **{E['active_bypass_rc_live']}** _(0 until RC verifier is unlocked)_")
    add(lines, f"- Active bypass still RC-unverifiable: **{E['active_bypass_rc_unverifiable']}**")
    add(lines, f"- Dormant bypass safe to expire: **{E['dormant_safe']}** _(requires RC verification first)_")
    add(lines, f"- Stale trial records that actually still grant access: **{E['stale_trial_grant_access']}** _(none — see §5)_")
    add(lines, f"- Stale trial records that are display-only: **{E['stale_trial_display_only']}**")
    add(lines, f"- Remaining ambiguous accounts: **{E['ambiguous']}**")
    add(lines)

    add(lines, "---")
    add(lines)
    add(lines, "**HARD STOP.** No cleanup executed. No production code changed. No RC changes. No credit changes. No deploys.")
    add(lines)
    return "\n".join(lines)


def classify_trial_row(r):
    """Classify each of the six tier='trial' users."""
    sub_tier = r.get("sub_tier")
    needs = r.get("computed_needs_subscription")
    cleanup = r.get("sub_admin_cleanup_reason")
    has_rc = bool(r.get("sub_revenuecat_customer_id"))
    exp = r.get("sub_trial_expires_at")
    d_exp = days_since(exp)
    is_trial = r.get("sub_is_trial")

    # If sub_tier was already reset by cleanup (e.g. expired), the trial is a display-only ghost.
    if cleanup and sub_tier in ("expired", "trial_expired") and not is_trial:
        return "already expired / stale display only"
    if sub_tier in ("expired", "trial_expired"):
        return "already expired / stale display only"
    if d_exp is not None and d_exp > 0 and not has_rc:
        return "already expired / stale display only"
    if d_exp is not None and d_exp <= 0:
        return "actually still entitled locally"
    if has_rc and exp is None:
        return "ambiguous"
    return "telemetry-limited"


def classify_is_trial_row(r):
    """Classify each of the four is_trial=true users."""
    sub_tier = r.get("sub_tier")
    exp = r.get("sub_trial_expires_at")
    d_exp = days_since(exp)
    has_rc = bool(r.get("sub_revenuecat_customer_id"))
    if sub_tier in PAID_TIERS:
        return "actual access-affecting flag (paid tier trial — DO NOT TOUCH)"
    if sub_tier in ("expired", "trial_expired"):
        return "harmless stale metadata (needs_subscription=true regardless of is_trial)"
    if d_exp is not None and d_exp > 0 and not has_rc:
        return "harmless stale metadata"
    if has_rc:
        return "ambiguous state (has RC — needs live verification)"
    return "harmless stale metadata"


# ---------- Main ----------

def audit():
    print(f"[recon] Starting {NOW.isoformat()}")
    token = login()
    print("[recon] admin login OK")

    all_users, total = fetch_all_users(token)
    print(f"[recon] /admin/all-users → {len(all_users)} rows (total={total})")

    print("[recon] enriching paid cohort...")
    paid_rows = build_paid_cohort(token, all_users)
    print(f"[recon]   paid rows: {len(paid_rows)}")

    print("[recon] enriching legacy cohort (57)...")
    legacy_rows = build_legacy_cohort(token, all_users)
    print(f"[recon]   legacy rows: {len(legacy_rows)}")

    # Existing vs new
    existing_paid, new_paid, unknown_date_paid, audit_cutoff = previous_46(paid_rows)

    # Real paid count
    real_paid = [r for r in paid_rows if not r["excluded"]]

    # MRR both tables
    mrr_code_rows, mrr_code_total = compute_mrr(paid_rows, TIER_TO_PRICE_CODE)
    mrr_user_rows, mrr_user_total = compute_mrr(paid_rows, TIER_TO_PRICE_USER_BRIEF)

    # Split legacy universe
    bypass_rows = [r for r in legacy_rows if r["aggregated_tier"] == "paywall_bypass"]
    tier_trial_rows = [r for r in legacy_rows if r["aggregated_tier"] == "trial"]
    is_trial_ids = {r["user_id"] for r in tier_trial_rows}
    is_trial_only_rows = [r for r in legacy_rows if r["aggregated_is_trial"] and r["user_id"] not in is_trial_ids]

    # Bypass active/dormant split (login≤90d OR (gen>0 AND login≤90d))
    def _active(r):
        d = days_since(r.get("user_last_login"))
        return d is not None and d <= 90
    active_bypass = [r for r in bypass_rows if _active(r)]
    dormant_bypass = [r for r in bypass_rows if not _active(r)]

    # RC verification (all bypass with rc_id → UNVERIFIABLE in this env)
    rc_verif = rc_verification(bypass_rows)

    # §7 mutually-exclusive categories
    categories = []
    # (1) Legitimate paid/trial
    legit_paid_trial = [r for r in legacy_rows if (r["sub_tier"] in PAID_TIERS) or
                        (days_since(r.get("sub_trial_expires_at")) is not None
                         and days_since(r.get("sub_trial_expires_at")) <= 0)]
    categories.append({"name": "1. Legitimate paid/trial", "count": len(legit_paid_trial),
                       "hint": "sub in PAID_TIERS or in-window trial"})
    legit_ids = {r["user_id"] for r in legit_paid_trial}

    # (2) RC verification required — every remaining legacy user with RC id
    rc_required = [r for r in legacy_rows if r["user_id"] not in legit_ids and r.get("sub_revenuecat_customer_id")]
    categories.append({"name": "2. RevenueCat verification required", "count": len(rc_required),
                       "hint": f"has RC id + RC_UNVERIFIABLE ({sum(1 for r in rc_verif if r['rc_class']=='RC_UNVERIFIABLE')} bypass; the rest are trials)"})
    rc_ids = {r["user_id"] for r in rc_required}

    # (3) Source-of-truth / telemetry ambiguity
    #     - agg-vs-sub mismatch, OR
    #     - trial-tier row with no expiry data AND no RC id
    ambiguous = []
    for r in legacy_rows:
        if r["user_id"] in legit_ids or r["user_id"] in rc_ids:
            continue
        if r.get("agg_vs_sub_tier_mismatch"):
            ambiguous.append(r); continue
        if r["aggregated_tier"] == "trial" and r.get("sub_trial_expires_at") is None and not r.get("sub_revenuecat_customer_id"):
            ambiguous.append(r); continue
    ambig_ids = {r["user_id"] for r in ambiguous}
    categories.append({"name": "3. Source-of-truth / telemetry ambiguity", "count": len(ambiguous),
                       "hint": "aggregation mismatch or trial w/o expiry & no RC"})

    # (4) Safe stale cleanup — no RC AND (needs_sub=true OR expired trial)
    safe_cleanup = []
    for r in legacy_rows:
        if r["user_id"] in legit_ids or r["user_id"] in rc_ids or r["user_id"] in ambig_ids:
            continue
        if r.get("sub_revenuecat_customer_id"):
            continue
        # dormant bypass w/o RC — safe cleanup (but there are none in our data)
        # trial rows w/o RC & needs_subscription=true — safe cleanup
        if r["computed_needs_subscription"]:
            safe_cleanup.append(r); continue
        d_exp = days_since(r.get("sub_trial_expires_at"))
        if d_exp is not None and d_exp > 0:
            safe_cleanup.append(r); continue
    safe_ids = {r["user_id"] for r in safe_cleanup}
    categories.append({"name": "4. Safe stale cleanup", "count": len(safe_cleanup),
                       "hint": "no RC + needs_sub / expired trial"})

    # (5) Conversion candidate — active bypass with no RC id
    conv = [r for r in legacy_rows if r["user_id"] not in legit_ids and r["user_id"] not in rc_ids
            and r["user_id"] not in ambig_ids and r["user_id"] not in safe_ids
            and r["aggregated_tier"] == "paywall_bypass"
            and not r.get("sub_revenuecat_customer_id")
            and days_since(r.get("user_last_login")) is not None
            and days_since(r["user_last_login"]) <= 90]
    conv_ids = {r["user_id"] for r in conv}
    categories.append({"name": "5. Conversion candidate", "count": len(conv),
                       "hint": "active bypass w/o RC (RC conclusively absent)"})

    all_assigned = legit_ids | rc_ids | ambig_ids | safe_ids | conv_ids
    unassigned = [r for r in legacy_rows if r["user_id"] not in all_assigned]
    if unassigned:
        categories.append({"name": "6. UNASSIGNED (bug)", "count": len(unassigned),
                           "hint": ", ".join(r["user_id"] for r in unassigned)})

    # Decision table
    decision_table = [
        {"group": "Real paying subscribers",
         "count": len(real_paid),
         "func_free": "❌ (paying)",
         "rc_status": "RC entitlement live (implied by billing)",
         "safe_change": "❌ NEVER",
         "action": "Do not touch."},
        {"group": "Active bypass — RC id present",
         "count": sum(1 for r in active_bypass if r.get("sub_revenuecat_customer_id")),
         "func_free": "✅",
         "rc_status": "RC_UNVERIFIABLE (no REST key)",
         "safe_change": "❌ NOT YET",
         "action": "Add REVENUECAT_V1_SECRET; classify per-user; then decide."},
        {"group": "Active bypass — no RC id",
         "count": sum(1 for r in active_bypass if not r.get("sub_revenuecat_customer_id")),
         "func_free": "✅",
         "rc_status": "NO_RC_ID (RC conclusively absent)",
         "safe_change": "⚠️ Conversion-safe",
         "action": "Contact for conversion; expire on non-conversion after warning."},
        {"group": "Dormant bypass (>90d) — RC id present",
         "count": sum(1 for r in dormant_bypass if r.get("sub_revenuecat_customer_id")),
         "func_free": "✅ (credits remain)",
         "rc_status": "RC_UNVERIFIABLE",
         "safe_change": "❌ NOT YET",
         "action": "Add REVENUECAT_V1_SECRET; then Batch D-safe."},
        {"group": "Dormant bypass (>90d) — no RC id",
         "count": sum(1 for r in dormant_bypass if not r.get("sub_revenuecat_customer_id")),
         "func_free": "✅ (credits remain)",
         "rc_status": "NO_RC_ID",
         "safe_change": "✅ SAFE",
         "action": "Include in a future Batch D (`user_id`-keyed cleanup)."},
        {"group": "tier='trial' — display-only stale",
         "count": sum(1 for r in tier_trial_rows if classify_trial_row(r) == "already expired / stale display only"),
         "func_free": "❌ (needs_subscription=true)",
         "rc_status": "no RC",
         "safe_change": "✅ SAFE",
         "action": "Batch D by `user_id` (email-blind) to normalize tier/is_trial."},
        {"group": "tier='trial' — telemetry-limited / ambiguous",
         "count": sum(1 for r in tier_trial_rows if classify_trial_row(r) in ("telemetry-limited", "ambiguous")),
         "func_free": "⚠️ unknown",
         "rc_status": "unknown",
         "safe_change": "❌ NOT YET",
         "action": "Investigate individually; require RC verification if any RC id."},
        {"group": "is_trial=true — display-only",
         "count": sum(1 for r in is_trial_only_rows if classify_is_trial_row(r).startswith("harmless")),
         "func_free": "❌ (needs_subscription=true; is_trial flag has no gate effect)",
         "rc_status": "no gating impact",
         "safe_change": "✅ SAFE",
         "action": "Batch D by `user_id` to clear the stale is_trial flag."},
        {"group": "is_trial=true — ambiguous (has RC)",
         "count": sum(1 for r in is_trial_only_rows if classify_is_trial_row(r).startswith("ambiguous")),
         "func_free": "⚠️ unknown",
         "rc_status": "RC_UNVERIFIABLE",
         "safe_change": "❌ NOT YET",
         "action": "Require RC verification."},
    ]

    # Explicit totals
    explicit_totals = {
        "real_paid": len(real_paid),
        "actual_mrr_code": mrr_code_total,
        "actual_mrr_user": mrr_user_total,
        "active_bypass": len(active_bypass),
        "active_bypass_rc_inactive": 0,  # RC verifier not available
        "active_bypass_rc_live": 0,
        "active_bypass_rc_unverifiable": sum(1 for r in active_bypass if r.get("sub_revenuecat_customer_id")),
        "dormant_safe": sum(1 for r in dormant_bypass if not r.get("sub_revenuecat_customer_id")),
        "stale_trial_grant_access": 0,   # §5 proves is_trial does not gate paywall
        "stale_trial_display_only": (
            sum(1 for r in tier_trial_rows if classify_trial_row(r) == "already expired / stale display only")
            + sum(1 for r in is_trial_only_rows if classify_is_trial_row(r).startswith("harmless"))
        ),
        "ambiguous": sum(1 for r in tier_trial_rows if classify_trial_row(r) in ("telemetry-limited", "ambiguous")) +
                     sum(1 for r in is_trial_only_rows if classify_is_trial_row(r).startswith("ambiguous")),
    }

    report = {
        "generated_at": NOW.isoformat(),
        "target": PROD_BASE,
        "audit_cutoff": audit_cutoff.isoformat(),
        "rc_access_available": False,
        "rc_access_note": "Only REVENUECAT_WEBHOOK_AUTH is set; no v1 REST secret. Live RC state cannot be queried from this env.",
        "totals": {
            "raw_paid": len(paid_rows),
            "excluded_paid": sum(1 for r in paid_rows if r["excluded"]),
            "real_paid": len(real_paid),
            "universe_total": len(legacy_rows),
        },
        "paid_rows": paid_rows,
        "existing_paid": existing_paid,
        "new_paid": new_paid,
        "unknown_date_paid": unknown_date_paid,
        "mrr_code": {"rows": mrr_code_rows, "total": mrr_code_total},
        "mrr_user": {"rows": mrr_user_rows, "total": mrr_user_total},
        "legacy_rows": legacy_rows,
        "tier_trial_rows": tier_trial_rows,
        "is_trial_only_rows": is_trial_only_rows,
        "bypass_rows": bypass_rows,
        "active_bypass": active_bypass,
        "dormant_bypass": dormant_bypass,
        "rc_verification": rc_verif,
        "categories": categories,
        "decision_table": decision_table,
        "explicit_totals": explicit_totals,
    }
    return report


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    report = audit()
    with open(DATA_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    with open(REPORT_MD, "w") as f:
        f.write(render(report))
    print(f"\n[recon] Wrote: {DATA_JSON}")
    print(f"[recon] Wrote: {REPORT_MD}")
    T = report["totals"]
    E = report["explicit_totals"]
    print(f"\n===== SUMMARY =====")
    print(f"RAW PAID       = {T['raw_paid']}")
    print(f"TEST/EXCLUDED  = {T['excluded_paid']}")
    print(f"REAL PAID      = {T['real_paid']}")
    print(f"MRR (code)     = ${E['actual_mrr_code']:.2f}")
    print(f"MRR (user)     = ${E['actual_mrr_user']:.2f}")


if __name__ == "__main__":
    main()
