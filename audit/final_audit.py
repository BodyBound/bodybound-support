#!/usr/bin/env python3
"""
Post-cleanup legacy access audit (READ-ONLY).

Hits the production backend at https://bodybound-subs.emergent.host using
the admin JWT flow. Does NOT write to the DB. Does NOT deploy. Only issues
GET requests against admin endpoints already deployed on prod.

Output:
- /app/audit/final_audit_data.json   (raw enriched payload)
- /app/audit/final_audit_report.md   (formatted markdown per user spec)
"""
import os
import sys
import json
import time
import statistics
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

PROD_BASE = "https://bodybound-subs.emergent.host"
ADMIN_EMAIL = "bodyboundstencil@yahoo.com"
ADMIN_PASSWORD = "Body.Bound.Admin.72410"

OUT_DIR = "/app/audit"
DATA_JSON = os.path.join(OUT_DIR, "final_audit_data.json")
REPORT_MD = os.path.join(OUT_DIR, "final_audit_report.md")

NOW = datetime.now(timezone.utc)
NINETY_DAYS_SECONDS = 90 * 24 * 3600

# Test/reviewer accounts that must NOT be counted as revenue opportunity.
# Anything ending in these domains or exact emails is treated as test.
TEST_EMAIL_DOMAINS = (
    "@studio.test",
    "@test.local",
    "@example.com",
    "@apple-review.test",
)
TEST_EMAIL_EXACT = {
    "demo_reviewer_account",
}

PAID_TIERS = {"walk-in", "booked-out", "the-shop", "the-shop-member"}
WALK_IN_MONTHLY_PRICE = 14.99


def http_json(method, path, token=None, body=None, timeout=45):
    url = PROD_BASE + path
    data = None
    headers = {"Accept": "application/json"}
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
            payload = json.loads(e.read())
        except Exception:
            payload = {"error": str(e)}
        return e.code, payload
    except URLError as e:
        return -1, {"error": f"URLError: {e}"}


def login():
    status, data = http_json("POST", "/api/admin-auth/login",
                             body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if status != 200 or not data or "token" not in data:
        raise SystemExit(f"[FATAL] admin login failed: status={status} body={data}")
    return data["token"]


def parse_iso(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def days_since(v):
    dt = parse_iso(v)
    if not dt:
        return None
    return (NOW - dt).total_seconds() / 86400.0


def is_test_email(email):
    """Real production users may lack an email (anonymous / device-linked
    RC identities). Only flag as test/reviewer when the email actually
    matches a test domain or the known reviewer alias. Missing email is
    NOT a test signal — treat as an ordinary production account."""
    if not email:
        return False
    e = email.lower().strip()
    if e in TEST_EMAIL_EXACT:
        return True
    return any(e.endswith(d) for d in TEST_EMAIL_DOMAINS)


def fetch_all_users(token):
    status, data = http_json("GET", "/api/admin/all-users", token=token)
    # /admin/all-users currently returns UP TO 500 users (hard cap). Emit a
    # warning if we hit it so the reader knows the audit is truncated.
    if status != 200:
        raise SystemExit(f"[FATAL] /admin/all-users failed: {status} {data}")
    users = data.get("users", [])
    return users, data.get("total", len(users))


def fetch_user_detail(token, email, user_id=None):
    # Prefer user_id lookup (exact, avoids regex ambiguity and works when
    # email is missing). Falls back to email-regex lookup only if we don't
    # have a user_id.
    from urllib.parse import quote
    if user_id:
        status, data = http_json("GET", f"/api/admin/user-lookup?user_id={quote(user_id)}", token=token)
        if status == 200 and data and data.get("found"):
            # Normalize to {user, subscription, admin_history} shape used elsewhere.
            return {
                "user": data.get("user") or {},
                "subscription": data.get("subscription") or {},
                "admin_history": [],
            }
        # fall through to email-based lookup if user-lookup failed
    if not email:
        return None
    status, data = http_json("GET", f"/api/admin-tool/user/{quote(email, safe='@.')}", token=token)
    if status != 200:
        return None
    return data


def build_universe(users):
    """Return dict keyed by user_id → {email, tier, is_trial, credits, last_event, created_at}
    Filtered to any of: tier='paywall_bypass', tier='trial', is_trial=True.
    """
    universe = {}
    for u in users:
        tier = u.get("tier")
        is_trial = bool(u.get("is_trial"))
        if tier == "paywall_bypass" or tier == "trial" or is_trial:
            uid = u.get("user_id") or u.get("email")
            universe[uid] = {
                "email": u.get("email"),
                "user_id": u.get("user_id"),
                "tier": tier,
                "credits": u.get("credits", 0),
                "is_trial": is_trial,
                "last_event": u.get("last_event", "none"),
                "created_at": u.get("created_at"),
            }
    return universe


def enrich(token, universe):
    """For each user in universe, fetch full user+subscription detail from prod."""
    enriched = []
    total = len(universe)
    for i, (uid, base) in enumerate(universe.items(), 1):
        email = base["email"]
        user_id = base["user_id"]
        detail = fetch_user_detail(token, email, user_id=user_id)
        if not detail:
            enriched.append({**base, "detail_error": "detail fetch failed"})
            continue
        user = detail.get("user") or {}
        sub = detail.get("subscription") or {}
        history = detail.get("admin_history") or []
        enriched.append({
            **base,
            # Prefer authoritative email from users doc if base had null
            "email": base["email"] or user.get("email"),
            "user_created_at": user.get("created_at"),
            "user_last_login": user.get("last_login"),
            "sub_tier": sub.get("tier"),
            "sub_available_credits": sub.get("available_credits", 0),
            "sub_credits_consumed_this_cycle": sub.get("credits_consumed_this_cycle", 0),
            "sub_is_trial": bool(sub.get("is_trial")),
            "sub_trial_start_date": sub.get("trial_start_date"),
            "sub_trial_expires_at": sub.get("trial_expires_at"),
            "sub_revenuecat_customer_id": sub.get("revenuecat_customer_id"),
            "sub_last_event": sub.get("last_event"),
            "sub_last_event_at": sub.get("last_event_at"),
            "sub_admin_cleanup_reason": sub.get("admin_cleanup_reason"),
            "sub_admin_cleanup_batch_id": sub.get("admin_cleanup_batch_id"),
            "sub_pre_cleanup_tier": sub.get("pre_cleanup_tier"),
            "sub_pre_cleanup_credits": sub.get("pre_cleanup_credits"),
            "sub_renewal_date": sub.get("renewal_date"),
            "sub_received_temp_credits": bool(sub.get("received_temp_credits")),
            "sub_received_temp_credits_at": sub.get("received_temp_credits_at"),
            "sub_last_product_id": sub.get("last_product_id"),
            "anti_abuse_email": sub.get("anti_abuse_email"),
            "anti_abuse_provider": sub.get("anti_abuse_provider"),
            "admin_history_count": len(history),
            "admin_history_recent": [
                {"action": a.get("action"), "timestamp": a.get("timestamp"),
                 "admin_email": a.get("admin_email")}
                for a in history[:5]
            ],
        })
        if i % 10 == 0:
            print(f"  enriched {i}/{total}", flush=True)
    return enriched


def count_paid(users):
    total = 0
    trial_of_paid_tier = 0
    paid_emails = []
    for u in users:
        tier = u.get("tier")
        is_trial = bool(u.get("is_trial"))
        if tier in PAID_TIERS:
            if is_trial:
                trial_of_paid_tier += 1
                paid_emails.append({"email": u.get("email"), "tier": tier, "is_trial": True})
            else:
                total += 1
                paid_emails.append({"email": u.get("email"), "tier": tier, "is_trial": False})
    return total, trial_of_paid_tier, paid_emails


def classify_bypass(rows):
    """Classify paywall_bypass users into B1/B2/B3 with priority order:
       B1: activity ≤90d (login or generation)
       B2: inactive >90d BUT has RC id / unresolved entitlement evidence
       B3: everything else — must explain reason
    """
    b1, b2, b3 = [], [], []
    for r in rows:
        if r.get("tier") != "paywall_bypass":
            continue
        d_login = days_since(r.get("user_last_login"))
        # Meaningful user activity: last_login within 90d.
        # Generation activity: credits_consumed_this_cycle > 0 AND recent enough.
        # We do NOT have a per-generation timestamp so we use consumed>0 as a
        # weaker "ever generated" signal and mark 'signal' accordingly.
        consumed = int(r.get("sub_credits_consumed_this_cycle") or 0)

        active_login_90 = d_login is not None and d_login <= 90
        active_generation_ever = consumed > 0

        # Generation "recency" proxy: bypass tier was granted at signup with
        # 10 credits; if consumed>0 and last_login is within 90d, treat as
        # in-window generation. If consumed>0 but last_login is >90d, treat
        # as historic generation only (not counted for B1).
        active_generation_90 = active_generation_ever and (d_login is not None and d_login <= 90)

        signals = []
        if active_login_90:
            signals.append("login≤90d")
        if active_generation_90:
            signals.append("generation≤90d")
        if active_generation_ever and not active_generation_90:
            signals.append("generation>90d (historic only)")

        has_rc = bool(r.get("sub_revenuecat_customer_id"))

        if active_login_90 or active_generation_90:
            r["_bucket"] = "B1"
            r["_signals"] = signals
            r["_rc_flag"] = "RC verification required before access change" if has_rc else None
            b1.append(r)
        elif has_rc:
            r["_bucket"] = "B2"
            r["_signals"] = signals or ["inactive>90d", "has_rc_id"]
            b2.append(r)
        else:
            # B3: neither active nor has RC. Explain why it survived cleanup.
            reason_bits = []
            last_event = r.get("sub_last_event") or "none"
            if last_event in ("PAYWALL_BYPASS_GRANT", "INITIAL_PURCHASE", "RENEWAL"):
                reason_bits.append(f"last_event={last_event}")
            if r.get("sub_admin_cleanup_reason"):
                reason_bits.append("previously touched by cleanup")
            else:
                reason_bits.append("not eligible under Batch A/B/C rules")
            if r.get("sub_received_temp_credits"):
                reason_bits.append("received early_access_bridge")
            if consumed > 0:
                reason_bits.append(f"consumed={consumed} historical")
            if not reason_bits:
                reason_bits.append("no cleanup rule matched")
            r["_bucket"] = "B3"
            r["_signals"] = signals or ["no_activity_signals"]
            r["_survival_reason"] = "; ".join(reason_bits)
            b3.append(r)
    return b1, b2, b3


def summarize_active_bypass(b1):
    """Compute the activity/generation histograms requested by the user."""
    buckets = {"0-7d": 0, "8-30d": 0, "31-60d": 0, "61-90d": 0}
    gens_hist = {"1-4": 0, "5-9": 0, "10-19": 0, "20+": 0, "0": 0}
    gens_values = []
    for r in b1:
        d = days_since(r.get("user_last_login"))
        if d is not None:
            if d <= 7: buckets["0-7d"] += 1
            elif d <= 30: buckets["8-30d"] += 1
            elif d <= 60: buckets["31-60d"] += 1
            elif d <= 90: buckets["61-90d"] += 1
        consumed = int(r.get("sub_credits_consumed_this_cycle") or 0)
        gens_values.append(consumed)
        if consumed == 0: gens_hist["0"] += 1
        elif consumed <= 4: gens_hist["1-4"] += 1
        elif consumed <= 9: gens_hist["5-9"] += 1
        elif consumed <= 19: gens_hist["10-19"] += 1
        else: gens_hist["20+"] += 1
    stats = {}
    if gens_values:
        stats = {
            "total_generations": sum(gens_values),
            "avg": round(statistics.mean(gens_values), 2),
            "median": statistics.median(gens_values),
            "max": max(gens_values),
        }
    return buckets, gens_hist, stats


def mrr_scenarios(convertible_count, current_baseline_mrr):
    """Return list of {pct, users_converted, incr_gross_mrr, total_gross_mrr}."""
    out = []
    for pct in (10, 20, 30, 50):
        conv = round(convertible_count * pct / 100.0)
        incr = round(conv * WALK_IN_MONTHLY_PRICE, 2)
        total = round(current_baseline_mrr + incr, 2)
        out.append({"pct": pct, "users_converted": conv,
                    "incr_gross_mrr_usd": incr, "total_gross_mrr_usd": total})
    return out


def audit():
    print(f"[audit] Starting at {NOW.isoformat()}")
    print(f"[audit] Target: {PROD_BASE}")
    print("[audit] Logging in as admin...")
    token = login()
    print("[audit] OK — admin JWT acquired")

    print("[audit] Fetching /admin/all-users ...")
    all_users, total = fetch_all_users(token)
    print(f"[audit]   returned {len(all_users)} rows (endpoint reported total={total})")
    truncation_warning = None
    if len(all_users) >= 500 and total >= 500:
        truncation_warning = "WARNING: /admin/all-users hard-capped at 500 rows; audit may be truncated"

    paid_active, paid_in_trial, paid_emails = count_paid(all_users)
    print(f"[audit]   paid (non-trial): {paid_active}  in-trial-of-paid-tier: {paid_in_trial}")

    universe = build_universe(all_users)
    print(f"[audit]   universe of remaining legacy/free-access rows: {len(universe)}")

    print("[audit] Enriching from /admin-tool/user/{email} ...")
    enriched = enrich(token, universe)

    # Split by primary flag category, but dedupe by user_id so an account
    # that is BOTH tier='trial' AND is_trial=True is counted once.
    bypass_rows = [r for r in enriched if r.get("tier") == "paywall_bypass"]
    trial_tier_rows = [r for r in enriched if r.get("tier") == "trial"]
    is_trial_rows = [r for r in enriched if r.get("is_trial") and r.get("tier") != "trial"]

    # Overlap: users appearing in both tier='trial' and is_trial=True.
    trial_tier_ids = {r.get("user_id") for r in trial_tier_rows}
    is_trial_only_rows = [r for r in is_trial_rows if r.get("user_id") not in trial_tier_ids]

    # Bypass classification
    b1, b2, b3 = classify_bypass(bypass_rows)

    # Ensure B1+B2+B3 == bypass total
    assert len(b1) + len(b2) + len(b3) == len(bypass_rows), \
        f"bypass reconciliation mismatch: {len(b1)}+{len(b2)}+{len(b3)} != {len(bypass_rows)}"

    # Activity buckets for B1
    active_buckets, gens_hist, gen_stats = summarize_active_bypass(b1)

    # Convertible pool = B1 excluding test/reviewer emails.
    convertible = [r for r in b1 if not is_test_email(r.get("email"))]
    convertible_count = len(convertible)

    # Cross-check overlap: any legacy-flagged user who is ALSO in a paid tier?
    # (Shouldn't happen since universe filter excludes them, but guard.)
    # Only compare non-null emails so `None == None` doesn't produce false positives.
    paid_email_set = {p["email"] for p in paid_emails if p.get("email")}
    overlap_paid = [r for r in enriched if r.get("email") and r.get("email") in paid_email_set]

    # Reconcile totals
    total_bypass = len(bypass_rows)
    total_trial_tier = len(trial_tier_rows)
    total_is_trial_only = len(is_trial_only_rows)
    total_unique_legacy = total_bypass + total_trial_tier + total_is_trial_only

    # MRR scenarios anchored on the CURRENT verified paid baseline (paid_active
    # non-trial users × $14.99 as a conservative floor. Real MRR is higher for
    # booked-out / the-shop tiers, but we report Walk-In-equivalent to keep
    # the incremental math apples-to-apples).
    baseline_mrr = round(paid_active * WALK_IN_MONTHLY_PRICE, 2)
    scenarios = mrr_scenarios(convertible_count, baseline_mrr)

    report = {
        "generated_at": NOW.isoformat(),
        "target": PROD_BASE,
        "truncation_warning": truncation_warning,
        "totals": {
            "all_users_returned": len(all_users),
            "paid_active_non_trial": paid_active,
            "paid_in_apple_trial_but_paid_tier": paid_in_trial,
            "remaining_paywall_bypass": total_bypass,
            "remaining_tier_trial": total_trial_tier,
            "remaining_is_trial_only_not_tier_trial": total_is_trial_only,
            "unique_remaining_legacy_free_access": total_unique_legacy,
            "overlap_paid_with_legacy_flag": len(overlap_paid),
        },
        "baseline": {
            "current_verified_paid_subscribers": paid_active,
            "walk_in_price_usd_monthly": WALK_IN_MONTHLY_PRICE,
            "baseline_gross_mrr_usd_walkin_floor": baseline_mrr,
        },
        "bypass_classification": {
            "B1_active": len(b1),
            "B2_rc_linked_ambiguous": len(b2),
            "B3_boundary_other": len(b3),
            "reconciliation_ok": len(b1) + len(b2) + len(b3) == total_bypass,
        },
        "active_bypass_signals": {
            "activity_windows": active_buckets,
            "generation_histogram": gens_hist,
            "generation_stats": gen_stats,
        },
        "convertible_pool": {
            "b1_total": len(b1),
            "b1_excluding_test_reviewer": convertible_count,
            "scenarios": scenarios,
        },
        "bypass_rows": bypass_rows,
        "b1_detail": b1,
        "b2_detail": b2,
        "b3_detail": b3,
        "trial_tier_rows": trial_tier_rows,
        "is_trial_only_rows": is_trial_only_rows,
        "overlap_paid_with_legacy_flag": overlap_paid,
        "paid_subscriber_sample": paid_emails,
    }
    return report


def display_ident(r):
    """Show email if present, else fall back to user_id shortform for
    anonymous/device-linked accounts."""
    e = r.get("email")
    if e:
        return e
    uid = r.get("user_id") or "unknown"
    aa_email = r.get("anti_abuse_email")
    if aa_email:
        return f"(anonymous: {uid}) aa_email={aa_email}"
    return f"(anonymous: {uid})"


def fmt_date(v):
    dt = parse_iso(v)
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d")


def render_markdown(report):
    lines = []
    add = lines.append

    T = report["totals"]
    B = report["baseline"]
    C = report["bypass_classification"]

    add(f"# Post-Cleanup Legacy Access Audit (READ-ONLY)")
    add(f"")
    add(f"- **Generated at (UTC):** {report['generated_at']}")
    add(f"- **Target:** `{report['target']}`")
    if report.get("truncation_warning"):
        add(f"- **⚠️ {report['truncation_warning']}**")
    add(f"- **Write operations performed:** NONE")
    add(f"")

    add(f"## 0. Production paid-cohort cross-check")
    add(f"")
    add(f"| Metric | Value |")
    add(f"|---|---|")
    add(f"| Users returned by /admin/all-users | {T['all_users_returned']} |")
    add(f"| Real paid subscribers (non-trial, paid tier) | **{T['paid_active_non_trial']}** |")
    add(f"| In Apple free-trial of a paid tier | {T['paid_in_apple_trial_but_paid_tier']} |")
    prev = 46
    delta = T["paid_active_non_trial"] - prev
    diff_note = "matches previous 46" if delta == 0 else (f"CHANGED — was 46, now {T['paid_active_non_trial']} ({'+' if delta>0 else ''}{delta})")
    add(f"| vs previous audit (46) | {diff_note} |")
    add(f"| Baseline gross MRR floor (Walk-In equivalent × paid) | ${B['baseline_gross_mrr_usd_walkin_floor']} |")
    add(f"")

    add(f"## 1. Universe of remaining legacy/free-access accounts")
    add(f"")
    add(f"| Category | Count |")
    add(f"|---|---|")
    add(f"| `tier='paywall_bypass'` | {T['remaining_paywall_bypass']} |")
    add(f"| `tier='trial'` | {T['remaining_tier_trial']} |")
    add(f"| `is_trial=true` and NOT `tier='trial'` (dedupe) | {T['remaining_is_trial_only_not_tier_trial']} |")
    add(f"| **TOTAL UNIQUE REMAINING LEGACY/FREE-ACCESS USERS** | **{T['unique_remaining_legacy_free_access']}** |")
    add(f"| Overlap with paid cohort (should be 0) | {T['overlap_paid_with_legacy_flag']} |")
    add(f"")

    # ---- Bypass classification ----
    add(f"## 2. `paywall_bypass` classification (B1 / B2 / B3)")
    add(f"")
    add(f"Priority order used: **B1 (active) → B2 (RC-linked inactive) → B3 (boundary/other)**. Each unique user classified once.")
    add(f"")
    add(f"| Bucket | Count |")
    add(f"|---|---|")
    add(f"| B1 — Active (login or generation ≤90d) | {C['B1_active']} |")
    add(f"| B2 — RC-linked ambiguous (inactive >90d, has RC id) | {C['B2_rc_linked_ambiguous']} |")
    add(f"| B3 — Boundary / other | {C['B3_boundary_other']} |")
    add(f"| **Total (must equal bypass count above)** | **{C['B1_active']+C['B2_rc_linked_ambiguous']+C['B3_boundary_other']}** |")
    add(f"| Reconciliation OK? | {'✅' if C['reconciliation_ok'] else '❌'} |")
    add(f"")

    # ---- B1 detail table ----
    add(f"### 2.1 B1 — Active bypass detail")
    add(f"")
    if not report["b1_detail"]:
        add(f"_None._")
    else:
        add(f"| email | last_login | days_since_login | consumed_gens | credits_remaining | RC id? | qualifying_signal |")
        add(f"|---|---|---:|---:|---:|:---:|---|")
        for r in sorted(report["b1_detail"], key=lambda x: (days_since(x.get('user_last_login')) or 9999)):
            d = days_since(r.get("user_last_login"))
            d_str = f"{d:.1f}" if d is not None else "—"
            rc = "✅" if r.get("sub_revenuecat_customer_id") else "—"
            sig = ", ".join(r.get("_signals") or [])
            rc_flag = r.get("_rc_flag")
            if rc_flag:
                sig = f"{sig} · ⚠️ {rc_flag}"
            add(f"| {display_ident(r)} | {fmt_date(r.get('user_last_login'))} | {d_str} | {r.get('sub_credits_consumed_this_cycle',0)} | {r.get('sub_available_credits',0)} | {rc} | {sig} |")
    add(f"")

    # ---- B2 detail ----
    add(f"### 2.2 B2 — RC-linked ambiguous")
    add(f"")
    if not report["b2_detail"]:
        add(f"_None._")
    else:
        add(f"| email | last_login | days_since_login | RC customer id | last_event | consumed_gens |")
        add(f"|---|---|---:|---|---|---:|")
        for r in sorted(report["b2_detail"], key=lambda x: (days_since(x.get('user_last_login')) or 9999)):
            d = days_since(r.get("user_last_login"))
            d_str = f"{d:.1f}" if d is not None else "—"
            rc = r.get("sub_revenuecat_customer_id") or "—"
            add(f"| {display_ident(r)} | {fmt_date(r.get('user_last_login'))} | {d_str} | `{rc}` | {r.get('sub_last_event','—')} | {r.get('sub_credits_consumed_this_cycle',0)} |")
    add(f"")

    # ---- B3 detail ----
    add(f"### 2.3 B3 — Boundary / other")
    add(f"")
    add(f"Every B3 account must have a documented reason it survived Batch A/B/C.")
    add(f"")
    if not report["b3_detail"]:
        add(f"_None._")
    else:
        add(f"| email | last_login | consumed_gens | last_event | received_bridge | survival_reason |")
        add(f"|---|---|---:|---|:---:|---|")
        for r in sorted(report["b3_detail"], key=lambda x: (x.get('email') or x.get('user_id') or '')):
            add(f"| {display_ident(r)} | {fmt_date(r.get('user_last_login'))} | {r.get('sub_credits_consumed_this_cycle',0)} | {r.get('sub_last_event','—')} | {'✅' if r.get('sub_received_temp_credits') else '—'} | {r.get('_survival_reason','—')} |")
    add(f"")

    # ---- Trial flags ----
    add(f"## 3. Remaining trial flags")
    add(f"")
    add(f"### 3.1 `tier='trial'` (n={len(report['trial_tier_rows'])})")
    add(f"")
    if not report["trial_tier_rows"]:
        add(f"_None._")
    else:
        add(f"| email | trial_start | trial_expires | days_since_expires | RC id? | last_event | consumed_gens | assessment |")
        add(f"|---|---|---|---:|:---:|---|---:|---|")
        for r in report["trial_tier_rows"]:
            exp = r.get("sub_trial_expires_at")
            d_exp = days_since(exp)
            d_str = f"{d_exp:.1f}" if d_exp is not None else "—"
            rc = "✅" if r.get("sub_revenuecat_customer_id") else "—"
            # Assessment logic
            cleanup_reason = r.get("sub_admin_cleanup_reason")
            sub_tier_actual = r.get("sub_tier")
            if cleanup_reason and sub_tier_actual and sub_tier_actual != "trial":
                assess = f"POST-CLEANUP RESIDUAL (sub.tier='{sub_tier_actual}' but users.tier flag stale — needs `users` doc sync)"
            elif d_exp is not None and d_exp > 0:
                assess = "STALE / EXPIRED (trial ended, tier not cleared)"
            elif d_exp is not None and d_exp <= 0:
                assess = "LEGITIMATE (trial in-window)"
            elif rc == "✅":
                assess = "AMBIGUOUS (has RC, missing expiry)"
            else:
                assess = "TELEMETRY-LIMITED (no expiry date / anonymous device-linked)"
            add(f"| {display_ident(r)} | {fmt_date(r.get('sub_trial_start_date'))} | {fmt_date(exp)} | {d_str} | {rc} | {r.get('sub_last_event','—')} | {r.get('sub_credits_consumed_this_cycle',0)} | {assess} |")
    add(f"")

    add(f"### 3.2 `is_trial=true` (deduped — NOT already in `tier='trial'`; n={len(report['is_trial_only_rows'])})")
    add(f"")
    if not report["is_trial_only_rows"]:
        add(f"_None._")
    else:
        add(f"| email | tier | trial_start | trial_expires | RC id? | last_event | consumed_gens | assessment |")
        add(f"|---|---|---|---|:---:|---|---:|---|")
        for r in report["is_trial_only_rows"]:
            exp = r.get("sub_trial_expires_at")
            d_exp = days_since(exp)
            rc = "✅" if r.get("sub_revenuecat_customer_id") else "—"
            tier = r.get("sub_tier") or r.get("tier") or "—"
            if tier in PAID_TIERS:
                assess = "LEGITIMATE (Apple free-trial of paid tier — DO NOT TOUCH)"
            elif d_exp is not None and d_exp > 0:
                assess = "STALE (is_trial=true but trial ended)"
            elif rc == "✅":
                assess = "AMBIGUOUS (has RC — needs RC verification)"
            else:
                assess = "TELEMETRY-LIMITED"
            add(f"| {display_ident(r)} | {tier} | {fmt_date(r.get('sub_trial_start_date'))} | {fmt_date(exp)} | {rc} | {r.get('sub_last_event','—')} | {r.get('sub_credits_consumed_this_cycle',0)} | {assess} |")
    add(f"")

    # ---- Business analysis ----
    add(f"## 4. Business analysis — active free bypass users")
    add(f"")
    ab = report["active_bypass_signals"]
    add(f"### 4.1 Activity windows (B1 only)")
    add(f"")
    add(f"| Window | Users |")
    add(f"|---|---:|")
    for k in ("0-7d", "8-30d", "31-60d", "61-90d"):
        add(f"| {k} | {ab['activity_windows'].get(k,0)} |")
    add(f"| **Total active ≤90d (B1)** | **{sum(ab['activity_windows'].values())}** |")
    add(f"")

    add(f"### 4.2 Generation histogram (B1)")
    add(f"")
    add(f"| Generations | Users |")
    add(f"|---|---:|")
    for k in ("0", "1-4", "5-9", "10-19", "20+"):
        add(f"| {k} | {ab['generation_histogram'].get(k,0)} |")
    stats = ab["generation_stats"] or {}
    add(f"")
    add(f"- Total generations: **{stats.get('total_generations', 0)}**")
    add(f"- Average: **{stats.get('avg', 0)}**")
    add(f"- Median: **{stats.get('median', 0)}**")
    add(f"- Max: **{stats.get('max', 0)}**")
    add(f"")

    # ---- MRR scenarios ----
    add(f"## 5. MRR conversion scenarios")
    add(f"")
    cp = report["convertible_pool"]
    add(f"- Convertible pool: **B1 excluding test/reviewer emails** = **{cp['b1_excluding_test_reviewer']}** users (from B1 total {cp['b1_total']})")
    add(f"- Assumed converted tier: **Walk-In @ ${WALK_IN_MONTHLY_PRICE}/mo** (conservative floor)")
    add(f"- Current verified baseline gross MRR (Walk-In floor × paid): **${B['baseline_gross_mrr_usd_walkin_floor']}**")
    add(f"")
    add(f"| Conversion rate | Users converted | Incremental gross MRR | Total gross MRR |")
    add(f"|---:|---:|---:|---:|")
    for s in cp["scenarios"]:
        add(f"| {s['pct']}% | {s['users_converted']} | ${s['incr_gross_mrr_usd']} | ${s['total_gross_mrr_usd']} |")
    add(f"")
    add(f"_Note: real MRR is higher than the floor above because booked-out ($29.99) and the-shop ($99.99) subscribers contribute more than $14.99 each. The floor is used to keep the incremental math apples-to-apples._")
    add(f"")

    # ---- Final reconciliation ----
    add(f"## 6. Final reconciliation")
    add(f"")
    add(f"### 6.1 Totals")
    add(f"")
    add(f"| Category | Unique users |")
    add(f"|---|---:|")
    add(f"| `tier='paywall_bypass'` | {T['remaining_paywall_bypass']} |")
    add(f"| `tier='trial'` | {T['remaining_tier_trial']} |")
    add(f"| `is_trial=true` only (deduped) | {T['remaining_is_trial_only_not_tier_trial']} |")
    add(f"| **TOTAL UNIQUE REMAINING LEGACY/FREE-ACCESS USERS** | **{T['unique_remaining_legacy_free_access']}** |")
    add(f"")

    # ---- Classification into action categories ----
    add(f"### 6.2 Action-category classification")
    add(f"")
    add(f"_Mutually exclusive — every remaining legacy user appears in exactly one row._")
    add(f"")

    # 1. Conversion opportunity = B1 minus test/reviewer emails.
    #    RC-linked members are still opportunity but carry the "RC verification required" flag.
    conv = [r for r in report["b1_detail"] if not is_test_email(r.get("email"))]
    conv_rc = [r for r in conv if r.get("_rc_flag")]

    # 2. Safe future cleanup = B3 + STALE trials from §3.1 and §3.2 (no RC id, expired trial).
    def _is_stale_trial(r):
        exp = r.get("sub_trial_expires_at")
        d = days_since(exp)
        has_rc = bool(r.get("sub_revenuecat_customer_id"))
        return d is not None and d > 0 and not has_rc
    stale_trial_tier = [r for r in report["trial_tier_rows"] if _is_stale_trial(r)]
    stale_is_trial = [r for r in report["is_trial_only_rows"] if _is_stale_trial(r)]
    safe_cleanup = list(report["b3_detail"]) + stale_trial_tier + stale_is_trial

    # 3. RC verification required = B2 + AMBIGUOUS/telemetry-limited trials (has RC or no expiry data)
    def _is_ambiguous_trial(r):
        exp = r.get("sub_trial_expires_at")
        d = days_since(exp)
        has_rc = bool(r.get("sub_revenuecat_customer_id"))
        # Legitimate in-window trial goes to category 4 instead.
        if d is not None and d <= 0:
            return False
        # Stale (no rc, expired) already handled in category 2.
        if d is not None and d > 0 and not has_rc:
            return False
        return True
    ambiguous_trial_tier = [r for r in report["trial_tier_rows"] if _is_ambiguous_trial(r)]
    ambiguous_is_trial = [r for r in report["is_trial_only_rows"] if _is_ambiguous_trial(r)]
    rc_verify = list(report["b2_detail"]) + ambiguous_trial_tier + ambiguous_is_trial

    # 4. Legitimate paid/trial — DO NOT TOUCH
    #    Apple free-trial of a paid tier (found in is_trial_only where sub_tier in PAID_TIERS)
    #    plus any trial with an in-window expiry.
    def _is_legit_paid_trial(r):
        if r.get("sub_tier") in PAID_TIERS:
            return True
        exp = r.get("sub_trial_expires_at")
        d = days_since(exp)
        return d is not None and d <= 0
    do_not_touch = [r for r in report["trial_tier_rows"] + report["is_trial_only_rows"] if _is_legit_paid_trial(r)]

    # Reconciliation math
    cat_sum = len(conv) + len(safe_cleanup) + len(rc_verify) + len(do_not_touch)
    universe_total = T["unique_remaining_legacy_free_access"]
    # Note: test/reviewer accounts filtered out of `conv` still need a home. Add them explicitly.
    test_reviewer = [r for r in report["b1_detail"] if is_test_email(r.get("email"))]
    cat_sum_full = cat_sum + len(test_reviewer)

    add(f"| Category | Count | Members |")
    add(f"|---|---:|---|")
    add(f"| 1. **Conversion opportunity** (B1 minus test/reviewer) | {len(conv)} | see 2.1 table — of which {len(conv_rc)} carry ⚠️ RC-verify-first flag |")
    add(f"| 1b. Test / reviewer accounts (in B1, excluded from conversion math) | {len(test_reviewer)} | " + (", ".join(t.get("email") or t.get("user_id","?") for t in test_reviewer) or "—") + " |")
    add(f"| 2. **Safe future cleanup** (B3 + STALE trials without RC) | {len(safe_cleanup)} | {len(stale_trial_tier)} from §3.1 + {len(stale_is_trial)} from §3.2 |")
    add(f"| 3. **RC verification required** (B2 + ambiguous/telemetry-limited trials) | {len(rc_verify)} | {len(ambiguous_trial_tier)} from §3.1 + {len(ambiguous_is_trial)} from §3.2 |")
    add(f"| 4. **Legitimate paid/trial — DO NOT TOUCH** | {len(do_not_touch)} | Apple free-trial of paid tier / in-window trials |")
    add(f"| **Sum (must equal {universe_total})** | **{cat_sum_full}** | {'✅' if cat_sum_full == universe_total else '❌ MISMATCH'} |")
    add(f"")

    add(f"### 6.3 Paid-cohort overlap check")
    add(f"")
    if T["overlap_paid_with_legacy_flag"] == 0:
        add(f"✅ **No overlap** — no user is simultaneously in a paid tier AND flagged as legacy/free-access.")
    else:
        add(f"⚠️ **{T['overlap_paid_with_legacy_flag']} overlap(s) detected — DO NOT TOUCH, PAID/ENTITLEMENT REVIEW REQUIRED:**")
        for r in report["overlap_paid_with_legacy_flag"]:
            add(f"- {display_ident(r)} (tier={r.get('sub_tier')}, is_trial={r.get('sub_is_trial')})")
    add(f"")

    # ---- Stop ----
    add(f"---")
    add(f"")
    add(f"**HARD STOP.** No cleanup executed. No production code changed. No RC changes. No credit changes.")
    add(f"")
    return "\n".join(lines)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    report = audit()
    with open(DATA_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    md = render_markdown(report)
    with open(REPORT_MD, "w") as f:
        f.write(md)
    print(f"\n[audit] Wrote: {DATA_JSON}")
    print(f"[audit] Wrote: {REPORT_MD}")
    print(f"\n===== SUMMARY =====")
    T = report["totals"]
    print(f"Paid (non-trial):                 {T['paid_active_non_trial']}")
    print(f"paywall_bypass remaining:         {T['remaining_paywall_bypass']}")
    print(f"tier='trial' remaining:           {T['remaining_tier_trial']}")
    print(f"is_trial=true (deduped):          {T['remaining_is_trial_only_not_tier_trial']}")
    print(f"TOTAL UNIQUE LEGACY REMAINING:    {T['unique_remaining_legacy_free_access']}")
    C = report["bypass_classification"]
    print(f"B1/B2/B3: {C['B1_active']}/{C['B2_rc_linked_ambiguous']}/{C['B3_boundary_other']}  reconcile_ok={C['reconciliation_ok']}")


if __name__ == "__main__":
    main()
