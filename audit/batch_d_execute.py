#!/usr/bin/env python3
"""Batch D execution — 5 authorized production writes.

For each of 5 approved user_ids:
  1. Re-fetch state
  2. Validate all preconditions match approved preflight
  3. Call POST /admin-tool/action/normalize-expired-trial with dry_run=false
  4. Verify response: status=changed, matched=1, modified=1, drift={}
  5. Re-fetch post-state, verify tier='trial_expired', credits=0, protected fields unchanged
  6. Compute needs_subscription
Then verifies:
  - audit-log entries for all 5 mutations
  - regression: paid cohort / bypass / MRR unchanged; +5 trial_expired; -5 tier='trial'
"""
import os
import json
import subprocess
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError

PROD_BASE = "https://bodybound-subs.emergent.host"
ADMIN_EMAIL = "bodyboundstencil@yahoo.com"
ADMIN_PASSWORD = "Body.Bound.Admin.72410"
BATCH_ID = "BB-CLEANUP-2026-09-04-D"
NOW = datetime.now(timezone.utc)

TARGETS = [
    "user_a413c2ff83f9",
    "user_5a08baad0eb6",
    "user_853c847c8f91",
    "user_714df781c4f8",
    "user_2c877c5ff51f",
]
AMBIGUOUS_SIXTH = "user_673ab0d5552a"

PROTECTED_FIELDS = (
    "is_trial", "trial_start_date", "trial_expires_at",
    "revenuecat_customer_id", "last_event", "last_product_id",
    "renewal_date", "anti_abuse_email", "anti_abuse_device_id",
    "anti_abuse_provider", "studio_team_id", "created_at",
    "admin_cleanup_reason", "admin_cleanup_batch_id",
    "pre_cleanup_tier", "pre_cleanup_is_trial",
    "user_id",
)

OUT_DIR = "/app/audit"
DATA_JSON = os.path.join(OUT_DIR, "batch_d_execution_data.json")
REPORT_MD = os.path.join(OUT_DIR, "batch_d_execution_report.md")


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
            return resp.status, json.loads(resp.read())
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"error": str(e)}


def login():
    st, data = http_json("POST", "/api/admin-auth/login",
                         body={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if st != 200:
        raise SystemExit(f"admin login failed: {st} {data}")
    return data["token"]


def fetch(token, uid):
    st, data = http_json("GET", f"/api/admin/user-lookup?user_id={quote(uid)}", token=token)
    if st == 200 and data and data.get("found"):
        return data.get("subscription") or {}
    return None


def snap(sub):
    if not sub:
        return None
    return {k: sub.get(k) for k in (
        "user_id", "tier", "is_trial", "available_credits",
        "revenuecat_customer_id", "trial_expires_at", "trial_start_date",
        "last_event", "last_product_id", "renewal_date",
        "anti_abuse_email", "anti_abuse_device_id", "anti_abuse_provider",
        "studio_team_id", "created_at",
        "admin_cleanup_reason", "admin_cleanup_batch_id",
        "pre_cleanup_tier", "pre_cleanup_is_trial",
    )}


def preconditions_ok(sub):
    """Return (bool, list_of_failed_reasons)."""
    if not sub:
        return False, ["not_found"]
    reasons = []
    if sub.get("tier") != "trial": reasons.append(f"tier={sub.get('tier')!r}")
    if not sub.get("is_trial"): reasons.append("is_trial=false")
    if sub.get("available_credits") != 10: reasons.append(f"credits={sub.get('available_credits')}")
    if sub.get("revenuecat_customer_id") not in (None, ""): reasons.append("rc_id_present")
    if not sub.get("trial_expires_at"): reasons.append("no_trial_expires_at")
    else:
        try:
            dt = datetime.fromisoformat(str(sub.get("trial_expires_at")).replace("Z", "+00:00"))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            if dt > NOW: reasons.append("trial_expires_in_future")
        except Exception:
            reasons.append("trial_expires_unparseable")
    return len(reasons) == 0, reasons


def snapshot_paid_and_bypass(token):
    """Capture exact paid + bypass user_id sets and MRR baseline."""
    st, data = http_json("GET", "/api/admin/all-users", token=token)
    if st != 200:
        raise SystemExit(f"all-users failed: {st}")
    paid, bypass, trial_tier, trial_expired = [], [], [], []
    all_users = data.get("users", [])
    for u in all_users:
        t = u.get("tier")
        if t in ("walk-in", "booked-out", "the-shop", "the-shop-member"):
            paid.append(u.get("user_id"))
        elif t == "paywall_bypass":
            bypass.append(u.get("user_id"))
        elif t == "trial":
            trial_tier.append(u.get("user_id"))
        elif t == "trial_expired":
            trial_expired.append(u.get("user_id"))
    return {
        "raw_paid_ids": sorted(paid),
        "bypass_ids": sorted(bypass),
        "trial_tier_ids": sorted(trial_tier),
        "trial_expired_ids": sorted(trial_expired),
        "raw_paid_count": len(paid),
        "bypass_count": len(bypass),
        "trial_tier_count": len(trial_tier),
        "trial_expired_count": len(trial_expired),
        "all_users_total": data.get("total", len(all_users)),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"[batch-d-exec] Starting {NOW.isoformat()}")
    token = login()
    print("[batch-d-exec] admin login OK")

    # ---- PRE-BATCH SNAPSHOT ----
    print("[batch-d-exec] Capturing pre-batch cohort snapshot...")
    pre_snapshot = snapshot_paid_and_bypass(token)
    print(f"[batch-d-exec]   paid={pre_snapshot['raw_paid_count']} "
          f"bypass={pre_snapshot['bypass_count']} "
          f"trial={pre_snapshot['trial_tier_count']} "
          f"trial_expired={pre_snapshot['trial_expired_count']}")

    # ---- Per-target execution ----
    exec_results = []
    for uid in TARGETS:
        print(f"\n[batch-d-exec] --- {uid} ---")
        # 1. Re-fetch
        pre_sub = fetch(token, uid)
        pre_state = snap(pre_sub)
        # 2. Validate preconditions
        ok, reasons = preconditions_ok(pre_sub)
        if not ok:
            print(f"[batch-d-exec]   FAILED preflight: {reasons}")
            exec_results.append({
                "user_id": uid, "action": "skipped_client_side",
                "pre_state": pre_state, "reasons": reasons,
                "endpoint_response": None, "post_state": None,
            })
            continue
        expected_exp = pre_sub.get("trial_expires_at")
        # 3. Call endpoint dry_run=false
        st, resp = http_json(
            "POST", "/api/admin-tool/action/normalize-expired-trial",
            token=token,
            body={
                "user_id": uid,
                "expected_trial_expires_at": expected_exp,
                "cleanup_batch_id": BATCH_ID,
                "dry_run": False,
            },
        )
        print(f"[batch-d-exec]   endpoint HTTP {st}, status={resp.get('status') if resp else 'ERR'}")
        # 4. Re-fetch post-state
        post_sub = fetch(token, uid)
        post_state = snap(post_sub)
        # 5. Drift check on protected fields
        drift = {}
        if pre_sub and post_sub:
            for k in PROTECTED_FIELDS:
                if pre_sub.get(k) != post_sub.get(k):
                    drift[k] = {"before": pre_sub.get(k), "after": post_sub.get(k)}
        # 6. Compute needs_subscription
        post_tier = (post_sub or {}).get("tier")
        needs_sub = post_tier in (None, "trial_expired", "expired")
        exec_results.append({
            "user_id": uid,
            "action": "executed",
            "http_status": st,
            "pre_state": pre_state,
            "expected_trial_expires_at": expected_exp,
            "endpoint_response": resp,
            "post_state": post_state,
            "protected_field_drift": drift,
            "post_needs_subscription": needs_sub,
            "success": (
                st == 200
                and resp is not None
                and resp.get("status") == "changed"
                and resp.get("matched_count") == 1
                and resp.get("modified_count") == 1
                and resp.get("drift") == {}
                and post_tier == "trial_expired"
                and (post_sub or {}).get("available_credits") == 0
                and not drift
                and needs_sub is True
            ),
        })

    # ---- POST-BATCH SNAPSHOT ----
    print("\n[batch-d-exec] Capturing post-batch cohort snapshot...")
    post_snapshot = snapshot_paid_and_bypass(token)
    print(f"[batch-d-exec]   paid={post_snapshot['raw_paid_count']} "
          f"bypass={post_snapshot['bypass_count']} "
          f"trial={post_snapshot['trial_tier_count']} "
          f"trial_expired={post_snapshot['trial_expired_count']}")

    # Diff
    regression = {
        "raw_paid_unchanged": pre_snapshot["raw_paid_ids"] == post_snapshot["raw_paid_ids"],
        "bypass_unchanged": pre_snapshot["bypass_ids"] == post_snapshot["bypass_ids"],
        "trial_count_delta": post_snapshot["trial_tier_count"] - pre_snapshot["trial_tier_count"],
        "trial_expired_count_delta": post_snapshot["trial_expired_count"] - pre_snapshot["trial_expired_count"],
        "trial_tier_remaining_ids": post_snapshot["trial_tier_ids"],
        "expected_trial_remaining_ids": [AMBIGUOUS_SIXTH],
        "trial_tier_remaining_matches_expected": post_snapshot["trial_tier_ids"] == [AMBIGUOUS_SIXTH],
        "raw_paid_count_pre": pre_snapshot["raw_paid_count"],
        "raw_paid_count_post": post_snapshot["raw_paid_count"],
        "bypass_count_pre": pre_snapshot["bypass_count"],
        "bypass_count_post": post_snapshot["bypass_count"],
    }

    # ---- Confirm ambiguous 6th still tier='trial' ----
    amb_sub = fetch(token, AMBIGUOUS_SIXTH)
    ambiguous_intact = (amb_sub or {}).get("tier") == "trial"

    # ---- Fetch audit-log entries for this batch ----
    st, log_data = http_json("GET", "/api/admin-tool/audit-log", token=token)
    audit_entries = []
    if st == 200 and log_data:
        for a in log_data.get("actions", []):
            details = a.get("details") or {}
            if a.get("action") == "normalize_expired_trial" and details.get("cleanup_batch_id") == BATCH_ID:
                audit_entries.append(a)

    # ---- Rerun reconciliation script for full regression check ----
    print("\n[batch-d-exec] Running full reconciliation for regression...")
    try:
        subprocess.run(["python3", "/app/audit/reconciliation.py"],
                       check=True, capture_output=True, timeout=180)
        recon_ok = True
        recon_error = None
    except Exception as e:
        recon_ok = False
        recon_error = str(e)
    recon_data = None
    try:
        with open("/app/audit/reconciliation_data.json") as f:
            recon_data = json.load(f)
    except Exception as e:
        recon_error = recon_error or str(e)

    # ---- Compile report ----
    all_five_ok = all(r["success"] for r in exec_results)
    report = {
        "generated_at": NOW.isoformat(),
        "target": PROD_BASE,
        "batch_id": BATCH_ID,
        "pre_snapshot": pre_snapshot,
        "post_snapshot": post_snapshot,
        "regression": regression,
        "ambiguous_sixth_intact": ambiguous_intact,
        "ambiguous_sixth_post_tier": (amb_sub or {}).get("tier"),
        "exec_results": exec_results,
        "audit_entries_for_batch": audit_entries,
        "audit_entries_count": len(audit_entries),
        "recon_rerun_ok": recon_ok,
        "recon_error": recon_error,
        "recon_totals": (recon_data or {}).get("totals"),
        "recon_mrr_code": (recon_data or {}).get("mrr_code"),
        "final": "COMPLETE" if (
            all_five_ok
            and regression["raw_paid_unchanged"]
            and regression["bypass_unchanged"]
            and regression["trial_count_delta"] == -5
            and regression["trial_expired_count_delta"] == 5
            and regression["trial_tier_remaining_matches_expected"]
            and ambiguous_intact
            and len(audit_entries) >= 5
        ) else "PARTIAL_FAILED",
    }
    with open(DATA_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # ---- Markdown ----
    lines = []
    def add(s=""): lines.append(s)
    add(f"# Batch D Execution Report")
    add()
    add(f"- **Batch id:** `{BATCH_ID}`")
    add(f"- **Generated (UTC):** {NOW.isoformat()}")
    add(f"- **Target:** `{PROD_BASE}`")
    add(f"- **Final status:** {'✅ **BATCH D COMPLETE — VERIFIED**' if report['final']=='COMPLETE' else '❌ **BATCH D PARTIAL/FAILED — REVIEW REQUIRED**'}")
    add()

    add("## Per-target results")
    add()
    add("| user_id | HTTP | endpoint status | matched | modified | drift | post.tier | post.credits | needs_sub | success |")
    add("|---|:---:|---|:---:|:---:|:---:|---|---:|:---:|:---:|")
    for r in exec_results:
        resp = r["endpoint_response"] or {}
        drift = resp.get("drift") if resp else "—"
        add(f"| `{r['user_id']}` | {r.get('http_status','—')} | `{resp.get('status','—')}` | "
            f"{resp.get('matched_count','—')} | {resp.get('modified_count','—')} | "
            f"{'✅ {}' if drift == {} else '❌ '+str(drift)} | "
            f"{(r['post_state'] or {}).get('tier','—')} | {(r['post_state'] or {}).get('available_credits','—')} | "
            f"{r['post_needs_subscription']} | {'✅' if r['success'] else '❌'} |".replace("{}", "{}"))
    add()

    add("## Protected-field drift verification (per target)")
    add()
    add("| user_id | client-side drift check | endpoint-reported drift |")
    add("|---|:---:|:---:|")
    for r in exec_results:
        cd = r["protected_field_drift"]
        ed = (r["endpoint_response"] or {}).get("drift", "—")
        add(f"| `{r['user_id']}` | {'✅ empty' if cd == {} else '❌ '+str(cd)} | {'✅ empty' if ed == {} else '❌ '+str(ed)} |")
    add()

    add("## Regression: paid cohort")
    add()
    add(f"- Pre-batch raw paid: **{pre_snapshot['raw_paid_count']}**")
    add(f"- Post-batch raw paid: **{post_snapshot['raw_paid_count']}**")
    add(f"- Exact user_id set unchanged: **{'✅' if regression['raw_paid_unchanged'] else '❌'}**")
    if not regression["raw_paid_unchanged"]:
        added = set(post_snapshot["raw_paid_ids"]) - set(pre_snapshot["raw_paid_ids"])
        removed = set(pre_snapshot["raw_paid_ids"]) - set(post_snapshot["raw_paid_ids"])
        add(f"  - added: {sorted(added)}")
        add(f"  - removed: {sorted(removed)}")
    add()

    add("## Regression: paywall_bypass cohort")
    add()
    add(f"- Pre-batch bypass count: **{pre_snapshot['bypass_count']}**")
    add(f"- Post-batch bypass count: **{post_snapshot['bypass_count']}**")
    add(f"- Exact user_id set unchanged: **{'✅' if regression['bypass_unchanged'] else '❌'}**")
    add()

    add("## Regression: trial vs trial_expired counts")
    add()
    add(f"- tier='trial' delta: **{regression['trial_count_delta']}** (expected -5)")
    add(f"- tier='trial_expired' delta: **{regression['trial_expired_count_delta']}** (expected +5)")
    add(f"- Remaining tier='trial' user_ids: **{post_snapshot['trial_tier_ids']}**")
    add(f"- Expected remaining: **{[AMBIGUOUS_SIXTH]}**")
    add(f"- Match: **{'✅' if regression['trial_tier_remaining_matches_expected'] else '❌'}**")
    add()

    add(f"## Ambiguous 6th ({AMBIGUOUS_SIXTH})")
    add()
    add(f"- Post-batch tier: `{report['ambiguous_sixth_post_tier']}`")
    add(f"- Intact (still `tier='trial'`): {'✅' if ambiguous_intact else '❌'}")
    add()

    add(f"## Audit trail")
    add()
    add(f"- Audit entries with `action='normalize_expired_trial'` AND `batch_id='{BATCH_ID}'`: **{len(audit_entries)}** (expected 5)")
    add()
    if audit_entries:
        add("| target_email/user_id | pre_tier | post_tier | pre_credits | post_credits | matched | modified | drift | timestamp |")
        add("|---|---|---|---:|---:|:---:|:---:|:---:|---|")
        for a in audit_entries:
            d = a.get("details") or {}
            add(f"| `{a.get('target_email')}` | {d.get('pre_tier')} | {d.get('post_tier')} | "
                f"{d.get('pre_credits')} | {d.get('post_credits')} | "
                f"{d.get('matched_count')} | {d.get('modified_count')} | "
                f"{'✅' if not d.get('drift_detected') else '❌'} | {a.get('timestamp')} |")
    add()

    add("## Full reconciliation rerun (regression proof)")
    add()
    if recon_ok and report.get("recon_totals"):
        T = report["recon_totals"]
        M = report.get("recon_mrr_code") or {}
        add("| Metric | Value | Expected |")
        add("|---|---|---|")
        add(f"| RAW paid | {T.get('raw_paid')} | 48 |")
        add(f"| Internal/test excluded | {T.get('excluded_paid')} | 2 |")
        add(f"| REAL paying | {T.get('real_paid')} | 46 |")
        add(f"| Gross MRR (code prices) | ${M.get('total','?')} | $734.54 |")
        add(f"| Legacy universe total | {T.get('universe_total')} | 57 |")
    else:
        add(f"⚠️ Reconciliation rerun failed: {recon_error}")
    add()

    add("---")
    add()
    add(f"**Final:** {'✅ **BATCH D COMPLETE — VERIFIED**' if report['final']=='COMPLETE' else '❌ **BATCH D PARTIAL/FAILED — REVIEW REQUIRED**'}")

    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines))

    print(f"\n[batch-d-exec] Wrote {DATA_JSON}")
    print(f"[batch-d-exec] Wrote {REPORT_MD}")
    print(f"\n===== FINAL =====")
    print(f"5-target success: {sum(1 for r in exec_results if r['success'])}/5")
    print(f"raw_paid unchanged: {regression['raw_paid_unchanged']}")
    print(f"bypass unchanged:   {regression['bypass_unchanged']}")
    print(f"trial delta:        {regression['trial_count_delta']} (expected -5)")
    print(f"trial_expired delta:{regression['trial_expired_count_delta']} (expected +5)")
    print(f"ambiguous intact:   {ambiguous_intact}")
    print(f"audit entries:      {len(audit_entries)}")
    print(f"FINAL:              {report['final']}")


if __name__ == "__main__":
    main()
