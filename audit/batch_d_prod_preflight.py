#!/usr/bin/env python3
"""Phase 4 production preflight — READ-ONLY.

Runs POST /api/admin-tool/action/normalize-expired-trial with dry_run=true
against the newly deployed production endpoint. Verifies exactly 5
eligible targets and multiple negative controls stay excluded.

ZERO WRITES. dry_run=true only.

Outputs:
  /app/audit/batch_d_prod_preflight_data.json
  /app/audit/batch_d_prod_preflight_report.md
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
DATA_JSON = os.path.join(OUT_DIR, "batch_d_prod_preflight_data.json")
REPORT_MD = os.path.join(OUT_DIR, "batch_d_prod_preflight_report.md")

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

# Negative controls (from reconciliation data — 3 of each shape).
# Paying subscribers (walk-in) picked from the top of the paid cohort.
PAYING_CONTROLS = [
    "user_50aab4a6df20",  # co***@icloud.com (walk-in, ADMIN_FIX)
    "user_8305f4c0c6ac",  # pa***@gmail.com (walk-in, FRONTEND_SYNC + RC)
    "user_570f85906b8c",  # ri***@gmail.com (booked-out, RENEWAL + RC)
]
# Paywall_bypass — picked from the B1 active-bypass list (from earlier audit)
BYPASS_CONTROLS_LOOKUP_EMAILS = [
    "nazgultattoos@gmail.com",
    "coltrichardsontattoo@gmail.com",
    "beyondthelinesllc@gmail.com",
]
# RC-linked non-paying — picked from B2 (dormant bypass with RC id).
# These overlap with paywall_bypass — the RC check should skip them regardless
# (both preconditions fail). We'll pick a distinct set from tier='trial' with RC.
# The 2 known trial-with-RC are tattoosbykev5@gmail.com and marika_farmer90@icloud.com.
RC_LINKED_CONTROLS_EMAILS = [
    "tattoosbykev5@gmail.com",       # is_trial=true, has RC
    "marika_farmer90@icloud.com",    # is_trial=true, has RC
    "kaleymerrill@gmail.com",        # paywall_bypass with RC (B2)
]


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
    if status != 200 or "token" not in (data or {}):
        raise SystemExit(f"admin login failed: {status} {data}")
    return data["token"]


def fetch_user_by_id(token, user_id):
    status, data = http_json("GET", f"/api/admin/user-lookup?user_id={quote(user_id)}", token=token)
    if status == 200 and data and data.get("found"):
        return data.get("user") or {}, data.get("subscription") or {}
    return None, None


def find_user_id_by_email(token, email):
    status, data = http_json("GET", f"/api/admin/user-lookup?email={quote(email)}", token=token)
    if status == 200 and data and data.get("found"):
        return (data.get("user") or {}).get("user_id"), data.get("subscription") or {}
    return None, None


def snap(sub):
    if not sub:
        return None
    return {k: sub.get(k) for k in (
        "user_id", "tier", "is_trial", "available_credits",
        "revenuecat_customer_id", "trial_expires_at", "trial_start_date",
        "last_event", "last_product_id", "renewal_date",
    )}


def dry_run(token, user_id, expected_exp):
    """Call the new endpoint with dry_run=true."""
    body = {
        "user_id": user_id,
        "expected_trial_expires_at": expected_exp or "",
        "cleanup_batch_id": BATCH_ID,
        "dry_run": True,
    }
    return http_json("POST", "/api/admin-tool/action/normalize-expired-trial",
                     token=token, body=body)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"[preflight-prod] Starting at {NOW.isoformat()}")
    token = login()
    print("[preflight-prod] admin login OK")

    # Confirm production route is our new implementation via a shape probe.
    print("[preflight-prod] Probing route shape...")
    st, resp = http_json("POST", "/api/admin-tool/action/normalize-expired-trial",
                         token=token, body={"user_id": "PROBE_NONEXISTENT_UID",
                                            "expected_trial_expires_at":
                                                (NOW - __import__("datetime").timedelta(days=1)).isoformat(),
                                            "cleanup_batch_id": "PROBE",
                                            "dry_run": True})
    route_confirmed = (st == 200 and resp and resp.get("status") == "skipped"
                       and resp.get("reason") == "subscription_not_found")
    print(f"[preflight-prod]   route_confirmed={route_confirmed} (status={st}, response={resp})")

    # ----- Targets -----
    target_results = []
    for uid in TARGETS:
        user_doc, sub_doc = fetch_user_by_id(token, uid)
        pre_state = snap(sub_doc)
        if not sub_doc:
            target_results.append({"user_id": uid, "pre_fetch": None,
                                   "dry_run_status": None, "dry_run_response": None,
                                   "eligible": False, "error": "not_found"})
            continue
        expected_exp = sub_doc.get("trial_expires_at")
        st, resp = dry_run(token, uid, expected_exp)
        eligible = (resp or {}).get("status") == "dry_run"
        target_results.append({
            "user_id": uid,
            "pre_fetch": pre_state,
            "expected_trial_expires_at": expected_exp,
            "dry_run_http_status": st,
            "dry_run_response": resp,
            "eligible": eligible,
        })
        print(f"[preflight-prod]   {uid} eligible={eligible} status={resp.get('status') if resp else 'ERR'}")

    # ----- Ambiguous 6th -----
    print("[preflight-prod] Ambiguous 6th trial control:")
    user_doc, sub_doc = fetch_user_by_id(token, AMBIGUOUS_SIXTH)
    fake_exp = (NOW - __import__("datetime").timedelta(days=30)).isoformat()
    st, resp = dry_run(token, AMBIGUOUS_SIXTH, sub_doc.get("trial_expires_at") if sub_doc and sub_doc.get("trial_expires_at") else fake_exp)
    sixth_result = {
        "user_id": AMBIGUOUS_SIXTH,
        "pre_fetch": snap(sub_doc),
        "dry_run_http_status": st,
        "dry_run_response": resp,
        "eligible": (resp or {}).get("status") == "dry_run",
    }
    print(f"[preflight-prod]   {AMBIGUOUS_SIXTH} eligible={sixth_result['eligible']}")

    # ----- Paying controls -----
    paying_results = []
    for uid in PAYING_CONTROLS:
        user_doc, sub_doc = fetch_user_by_id(token, uid)
        # Use whatever expiry is on the record; if none, use a past ISO.
        exp = sub_doc.get("trial_expires_at") if sub_doc else None
        if not exp:
            exp = (NOW - __import__("datetime").timedelta(days=30)).isoformat()
        st, resp = dry_run(token, uid, exp)
        paying_results.append({
            "user_id": uid,
            "pre_fetch": snap(sub_doc),
            "dry_run_http_status": st,
            "dry_run_response": resp,
            "eligible": (resp or {}).get("status") == "dry_run",
        })

    # ----- Bypass controls (lookup by email → user_id first) -----
    bypass_results = []
    for email in BYPASS_CONTROLS_LOOKUP_EMAILS:
        uid, sub_doc = find_user_id_by_email(token, email)
        if not uid:
            bypass_results.append({"email": email, "error": "not_found"})
            continue
        exp = (sub_doc or {}).get("trial_expires_at") \
              or (NOW - __import__("datetime").timedelta(days=30)).isoformat()
        st, resp = dry_run(token, uid, exp)
        bypass_results.append({
            "email": email,
            "user_id": uid,
            "pre_fetch": snap(sub_doc),
            "dry_run_http_status": st,
            "dry_run_response": resp,
            "eligible": (resp or {}).get("status") == "dry_run",
        })

    # ----- RC-linked controls -----
    rc_results = []
    for email in RC_LINKED_CONTROLS_EMAILS:
        uid, sub_doc = find_user_id_by_email(token, email)
        if not uid:
            rc_results.append({"email": email, "error": "not_found"})
            continue
        exp = (sub_doc or {}).get("trial_expires_at") \
              or (NOW - __import__("datetime").timedelta(days=30)).isoformat()
        st, resp = dry_run(token, uid, exp)
        rc_results.append({
            "email": email,
            "user_id": uid,
            "pre_fetch": snap(sub_doc),
            "dry_run_http_status": st,
            "dry_run_response": resp,
            "eligible": (resp or {}).get("status") == "dry_run",
        })

    # ----- Re-fetch 5 targets AFTER dry-run to prove no state change -----
    print("[preflight-prod] Re-fetching targets to prove no drift...")
    post_states = {}
    for uid in TARGETS:
        _, sub_doc = fetch_user_by_id(token, uid)
        post_states[uid] = snap(sub_doc)

    # Diff pre vs post
    unchanged = True
    diffs = {}
    for r in target_results:
        uid = r["user_id"]
        pre = r["pre_fetch"]
        post = post_states.get(uid)
        if pre != post:
            unchanged = False
            diffs[uid] = {"pre": pre, "post": post}

    eligible_count = sum(1 for r in target_results if r["eligible"])
    negative_ok = (not sixth_result["eligible"]
                   and all(not r["eligible"] for r in paying_results)
                   and all((r.get("eligible") is False) for r in bypass_results)
                   and all((r.get("eligible") is False) for r in rc_results))

    report = {
        "generated_at": NOW.isoformat(),
        "target": PROD_BASE,
        "batch_id": BATCH_ID,
        "route_confirmed": route_confirmed,
        "targets": target_results,
        "ambiguous_sixth": sixth_result,
        "paying_controls": paying_results,
        "bypass_controls": bypass_results,
        "rc_linked_controls": rc_results,
        "post_dry_run_states": post_states,
        "post_dry_run_unchanged": unchanged,
        "post_dry_run_diffs": diffs,
        "summary": {
            "eligible_targets": eligible_count,
            "expected_eligible": 5,
            "all_negative_controls_excluded": negative_ok,
        },
    }
    with open(DATA_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # ------- Render markdown -------
    lines = []
    add = lines.append
    add("# Batch D Production Preflight (READ-ONLY, dry_run=true)")
    add("")
    add(f"- **Generated at (UTC):** {NOW.isoformat()}")
    add(f"- **Target:** `{PROD_BASE}`")
    add(f"- **Batch id:** `{BATCH_ID}`")
    add(f"- **Route confirmed on production:** {'✅' if route_confirmed else '❌'}")
    add(f"- **Writes performed:** NONE")
    add("")
    add("## 1. Production deployment / route confirmation")
    add("")
    add("Probe: `POST /api/admin-tool/action/normalize-expired-trial` with a non-existent user_id.")
    add("Expected shape from new endpoint: `{status: 'skipped', reason: 'subscription_not_found'}`.")
    add(f"Actual: `{json.dumps(resp)}` (HTTP {st})")
    add(f"→ {'✅ Route is the newly deployed implementation.' if route_confirmed else '❌ Route did not respond with expected shape.'}")
    add("")

    add("## 2. Dry-run for the 5 Batch D targets")
    add("")
    add("| user_id | pre.tier | pre.credits | pre.rc_id | pre.trial_expires_at | dry_run status | would_set.tier | would_set.credits | eligible |")
    add("|---|---|---:|:---:|---|---|---|---:|:---:|")
    for r in target_results:
        pre = r["pre_fetch"] or {}
        rc = "✅" if pre.get("revenuecat_customer_id") else "—"
        resp = r["dry_run_response"] or {}
        ws = resp.get("would_set") or {}
        add(f"| `{r['user_id']}` | {pre.get('tier')} | {pre.get('available_credits')} | {rc} | {pre.get('trial_expires_at')} | `{resp.get('status','—')}` | `{ws.get('tier','—')}` | {ws.get('available_credits','—')} | {'✅' if r['eligible'] else '❌'} |")
    add("")

    add("## 3. Negative controls")
    add("")
    add("### 3.1 Ambiguous 6th trial")
    add("")
    resp6 = sixth_result["dry_run_response"] or {}
    reasons6 = resp6.get("reasons") or ([resp6.get("reason")] if resp6.get("reason") else [])
    add(f"- `{AMBIGUOUS_SIXTH}` → `{resp6.get('status','—')}` (eligible={sixth_result['eligible']})")
    add(f"  - reasons: `{reasons6}`")
    add("")

    add("### 3.2 Paying subscribers (3 controls)")
    add("")
    add("| user_id | tier | dry_run status | reasons | eligible |")
    add("|---|---|---|---|:---:|")
    for r in paying_results:
        pre = r["pre_fetch"] or {}
        resp = r["dry_run_response"] or {}
        reasons = resp.get("reasons") or ([resp.get("reason")] if resp.get("reason") else [])
        add(f"| `{r['user_id']}` | {pre.get('tier')} | `{resp.get('status','—')}` | `{reasons}` | {'✅' if r['eligible'] else '❌'} |")
    add("")

    add("### 3.3 Paywall_bypass controls (3)")
    add("")
    add("| email | user_id | tier | dry_run status | reasons | eligible |")
    add("|---|---|---|---|---|:---:|")
    for r in bypass_results:
        if r.get("error"):
            add(f"| {r['email']} | — | — | — | ERROR: {r['error']} | — |")
            continue
        pre = r["pre_fetch"] or {}
        resp = r["dry_run_response"] or {}
        reasons = resp.get("reasons") or ([resp.get("reason")] if resp.get("reason") else [])
        add(f"| {r['email']} | `{r['user_id']}` | {pre.get('tier')} | `{resp.get('status','—')}` | `{reasons}` | {'✅' if r['eligible'] else '❌'} |")
    add("")

    add("### 3.4 RC-linked controls (3)")
    add("")
    add("| email | user_id | tier | rc_id | dry_run status | reasons | eligible |")
    add("|---|---|---|:---:|---|---|:---:|")
    for r in rc_results:
        if r.get("error"):
            add(f"| {r['email']} | — | — | — | — | ERROR: {r['error']} | — |")
            continue
        pre = r["pre_fetch"] or {}
        rc = "✅" if pre.get("revenuecat_customer_id") else "—"
        resp = r["dry_run_response"] or {}
        reasons = resp.get("reasons") or ([resp.get("reason")] if resp.get("reason") else [])
        add(f"| {r['email']} | `{r['user_id']}` | {pre.get('tier')} | {rc} | `{resp.get('status','—')}` | `{reasons}` | {'✅' if r['eligible'] else '❌'} |")
    add("")

    add("## 4. Blast radius")
    add("")
    add(f"- **Eligible targets:** **{eligible_count}** / expected **5**")
    add(f"- **All negative controls excluded:** {'✅' if negative_ok else '❌'}")
    add(f"- **Eligible user_ids:** {[r['user_id'] for r in target_results if r['eligible']]}")
    add(f"- **Approved list:** {TARGETS}")
    add(f"- **Match:** {'✅ EXACT' if [r['user_id'] for r in target_results if r['eligible']] == TARGETS else '❌ MISMATCH'}")
    add("")

    add("## 5. Post dry-run state verification")
    add("")
    add("Re-fetched all 5 targets after the dry-run calls to prove the endpoint did not write.")
    add("")
    add(f"- **All 5 target records unchanged post dry-run:** {'✅' if unchanged else '❌'}")
    if not unchanged:
        add("")
        add("**Drift detected:**")
        for uid, d in diffs.items():
            add(f"- `{uid}`: pre={d['pre']} post={d['post']}")
    add("")

    # Final
    all_ok = (route_confirmed and eligible_count == 5
              and [r['user_id'] for r in target_results if r['eligible']] == TARGETS
              and negative_ok and unchanged)
    add("## 6. Final recommendation")
    add("")
    if all_ok:
        add("### ✅ READY TO EXECUTE 5 BATCH D WRITES")
        add("")
        add("Production endpoint is live and honors every precondition. Exactly")
        add("5 target accounts are eligible; the approved list matches exactly.")
        add("Every negative control (ambiguous 6th, 3 paying, 3 bypass, 3 RC-linked)")
        add("was correctly excluded. No production state changed during preflight.")
    else:
        add("### ❌ DO NOT EXECUTE — REVIEW REQUIRED")
        add("")
        add("At least one check did not pass. See above for details.")
    add("")
    add("---")
    add("")
    add("**HARD STOP.** No writes. No RC changes. No further cleanup. Awaiting explicit authorization for the 5 subscription writes.")

    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines))

    print(f"\n[preflight-prod] Wrote: {DATA_JSON}")
    print(f"[preflight-prod] Wrote: {REPORT_MD}")
    print(f"\n===== SUMMARY =====")
    print(f"Route confirmed:        {route_confirmed}")
    print(f"Eligible targets:       {eligible_count} / 5")
    print(f"Negative controls OK:   {negative_ok}")
    print(f"Post-preflight unchanged: {unchanged}")
    print(f"Final: {'✅ READY' if all_ok else '❌ REVIEW REQUIRED'}")


if __name__ == "__main__":
    main()
