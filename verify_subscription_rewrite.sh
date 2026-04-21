#!/bin/bash
# Live production verification of the subscription-state rewrite.
# Proves:
#   - TRANSFER does NOT mutate paid state (only stamps last_transfer_at + RC id)
#   - INITIAL_PURCHASE applies tier/credits strictly from product_id
#   - RENEWAL preserves correct paid state
#
# Uses the dedicated demo account (user_id=demo_reviewer_account) so it can't
# interfere with a real paying customer.

set -eu

API="${API:-https://bodybound-subs.emergent.host}"

snap() {
  local label="$1" token="$2"
  local body debug
  body=$(curl -s "$API/api/auth/me" -H "Authorization: Bearer $token")
  # Also grab last_event + transfer fields via admin webhook-debug endpoint (uses user_id from JWT)
  debug=$(curl -s "$API/api/admin/user-lookup?user_id=$USER_ID" 2>/dev/null || echo '{}')
  python3 - "$label" "$body" "$debug" <<'PY'
import json, sys
label, body, debug = sys.argv[1], sys.argv[2], sys.argv[3]
r = json.loads(body)
c = r.get('credits', {}) or {}
try:
    d = json.loads(debug)
except Exception:
    d = {}
sub = d.get('subscription') or {}
out = {
    'tier': c.get('tier'),
    'available_credits': c.get('available_credits'),
    'is_trial': c.get('is_trial'),
    'last_event': sub.get('last_event'),
    'last_product_id': sub.get('last_product_id'),
    'revenuecat_customer_id': sub.get('revenuecat_customer_id') or c.get('revenuecat_customer_id'),
    'last_transfer_at': sub.get('last_transfer_at'),
    'last_transfer_from': sub.get('last_transfer_from'),
}
print(f"[{label}]")
for k,v in out.items(): print(f"  {k:>24}: {v}")
PY
}

echo "============================================================"
echo "  LIVE PRODUCTION VERIFICATION — SUBSCRIPTION REWRITE"
echo "  API: $API"
echo "============================================================"

# 1) Demo login (creates/reuses the shared demo_reviewer_account user)
LOGIN=$(curl -s -X POST "$API/api/auth/demo-login")
TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json;print(json.load(sys.stdin)['session_token'])")
USER_ID=$(echo "$LOGIN" | python3 -c "import sys,json;print(json.load(sys.stdin)['user']['user_id'])")
echo
echo ">> Using demo user: $USER_ID"

# 2) Seed to a known paid state so TRANSFER has something to try to overwrite.
#    Use Booked Out (bodybound_2999_1m_3d → booked-out / 500 credits) via the
#    frontend-path /api/subscription/sync. NOT trial.
echo
echo ">> Seeding via /api/subscription/sync (product=bodybound_2999_1m_3d, is_trial=false)"
curl -s -X POST "$API/api/subscription/sync" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"product_id":"bodybound_2999_1m_3d","is_trial":false,"revenuecat_customer_id":"rc_verify_seed_001"}' > /dev/null
echo
echo "=== STEP 1: BEFORE STATE (seeded paid) ==="
snap "BEFORE" "$TOKEN"

# 3) Synthetic TRANSFER — must NOT mutate tier/credits/is_trial.
echo
echo "=== STEP 2: SYNTHETIC TRANSFER → expect NO mutation ==="
TRANSFER_RES=$(curl -s -X POST "$API/api/webhooks/revenuecat" \
  -H "Content-Type: application/json" \
  -d "{\"event\":{\"type\":\"TRANSFER\",\"app_user_id\":\"anon_old_xyz\",\"transferred_from\":[\"anon_old_xyz\"],\"transferred_to\":[\"$USER_ID\"],\"product_id\":\"bodybound_1499_1m_3d\"}}")
echo "webhook response: $TRANSFER_RES"

echo
echo "=== STEP 3: AFTER TRANSFER STATE ==="
snap "AFTER TRANSFER" "$TOKEN"

# 4) Synthetic INITIAL_PURCHASE for Walk-In — must flip to walk-in/125.
echo
echo "=== STEP 4: SYNTHETIC INITIAL_PURCHASE (walk-in) → expect tier=walk-in, credits=125 ==="
IP_RES=$(curl -s -X POST "$API/api/webhooks/revenuecat" \
  -H "Content-Type: application/json" \
  -d "{\"event\":{\"type\":\"INITIAL_PURCHASE\",\"app_user_id\":\"$USER_ID\",\"product_id\":\"bodybound_1499_1m_3d\",\"period_type\":\"NORMAL\"}}")
echo "webhook response: $IP_RES"

echo
echo "=== STEP 5: AFTER INITIAL_PURCHASE STATE ==="
snap "AFTER INITIAL_PURCHASE" "$TOKEN"

# 5) Synthetic RENEWAL for same Walk-In — must keep tier=walk-in, refresh credits=125.
echo
echo "=== STEP 6: SYNTHETIC RENEWAL (walk-in) → expect tier=walk-in, credits=125 (refilled) ==="
R_RES=$(curl -s -X POST "$API/api/webhooks/revenuecat" \
  -H "Content-Type: application/json" \
  -d "{\"event\":{\"type\":\"RENEWAL\",\"app_user_id\":\"$USER_ID\",\"product_id\":\"bodybound_1499_1m_3d\",\"period_type\":\"NORMAL\"}}")
echo "webhook response: $R_RES"

echo
echo "=== STEP 7: AFTER RENEWAL STATE ==="
snap "AFTER RENEWAL" "$TOKEN"

echo
echo "============================================================"
echo "  DONE"
echo "============================================================"
