"""Extended tests for the Paywall-First subscription flow.

Tests all features from the review request:
1. GET /api/health returns 200
2. POST /api/auth/demo-login returns session_token and user
3. GET /api/auth/me returns credits with needs_subscription field
4. needs_subscription is False for users with active subscription tier
5. POST /api/subscription/sync requires authorization (401 without token)
6. POST /api/subscription/sync requires product_id (400 without it)
7. POST /api/subscription/sync rejects unknown product_id (400)
8. POST /api/subscription/sync with valid product_id updates tier and credits correctly
9. POST /api/subscription/sync with bodybound_1499_1m_3d sets tier to walk-in and credits to 125
10. POST /api/subscription/sync with bodybound_2999_1m_3d sets tier to booked-out and credits to 500
11. POST /api/subscription/sync with bodybound_9999_1m_3d sets tier to the-shop and credits to 1500
12. POST /api/subscription/sync idempotent — calling twice with same product doesn't change credits
13. POST /api/webhooks/revenuecat still works for INITIAL_PURCHASE events
14. POST /api/tasks/refresh-credits endpoint still exists and works with cron secret
"""
import pytest
import httpx
import os

API_URL = "https://stencil-ai-fallback.preview.emergentagent.com"
CRON_SECRET = "bb-cron-2026-refresh-c7f3a1"
REVENUECAT_WEBHOOK_AUTH = "bb-rc-webhook-2026-secure-x9k2m"


@pytest.fixture
def api():
    return httpx.Client(base_url=API_URL, timeout=15.0)


@pytest.fixture
def demo_token(api):
    """Get a demo login token for authenticated tests."""
    r = api.post("/api/auth/demo-login")
    assert r.status_code == 200
    return r.json()["session_token"]


# ============================================
# Test 1: GET /api/health returns 200
# ============================================
def test_health_endpoint(api):
    """GET /api/health returns 200 with status=healthy."""
    r = api.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "healthy"
    print("✓ Health endpoint returns 200 with status=healthy")


# ============================================
# Test 2: POST /api/auth/demo-login returns session_token and user
# ============================================
def test_demo_login_returns_session_token_and_user(api):
    """Demo login returns session_token and user object."""
    r = api.post("/api/auth/demo-login")
    assert r.status_code == 200
    data = r.json()
    assert "session_token" in data, "Missing session_token in response"
    assert "user" in data, "Missing user in response"
    assert isinstance(data["session_token"], str)
    assert len(data["session_token"]) > 0
    print(f"✓ Demo login returns session_token and user")


# ============================================
# Test 3: GET /api/auth/me returns credits with needs_subscription field
# ============================================
def test_auth_me_returns_needs_subscription_field(api, demo_token):
    """GET /api/auth/me returns credits with needs_subscription field."""
    r = api.get("/api/auth/me", headers={"Authorization": f"Bearer {demo_token}"})
    assert r.status_code == 200
    data = r.json()
    assert "credits" in data, "Missing credits in response"
    credits = data["credits"]
    assert "needs_subscription" in credits, "Missing needs_subscription in credits"
    print(f"✓ /api/auth/me returns needs_subscription field: {credits['needs_subscription']}")


# ============================================
# Test 4: needs_subscription is False for users with active subscription tier
# ============================================
def test_needs_subscription_false_for_active_tier(api, demo_token):
    """needs_subscription is False for users with active subscription tier."""
    # Demo account has an active tier (booked-out)
    r = api.get("/api/auth/me", headers={"Authorization": f"Bearer {demo_token}"})
    assert r.status_code == 200
    credits = r.json()["credits"]
    assert credits["needs_subscription"] == False, f"Expected needs_subscription=False, got {credits['needs_subscription']}"
    assert credits["tier"] is not None, "Expected tier to be set"
    print(f"✓ needs_subscription=False for active tier '{credits['tier']}'")


# ============================================
# Test 5: POST /api/subscription/sync requires authorization (401 without token)
# ============================================
def test_subscription_sync_requires_auth(api):
    """Sync endpoint requires authorization - returns 401 without token."""
    r = api.post("/api/subscription/sync", json={"product_id": "bodybound_2999_1m_3d"})
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    print("✓ /api/subscription/sync returns 401 without auth token")


# ============================================
# Test 6: POST /api/subscription/sync requires product_id (400 without it)
# ============================================
def test_subscription_sync_requires_product_id(api, demo_token):
    """Sync endpoint requires product_id - returns 400 without it."""
    r = api.post(
        "/api/subscription/sync",
        json={},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    print("✓ /api/subscription/sync returns 400 without product_id")


# ============================================
# Test 7: POST /api/subscription/sync rejects unknown product_id (400)
# ============================================
def test_subscription_sync_rejects_unknown_product(api, demo_token):
    """Sync endpoint rejects unknown product IDs with 400."""
    r = api.post(
        "/api/subscription/sync",
        json={"product_id": "fake_product_xyz_123"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    print("✓ /api/subscription/sync returns 400 for unknown product_id")


# ============================================
# Test 8: POST /api/subscription/sync with valid product_id updates tier and credits correctly
# ============================================
def test_subscription_sync_updates_tier_and_credits(api, demo_token):
    """Sync with valid product_id updates subscription tier and credits."""
    # Sync with walk-in product
    r = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_1499_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert "tier" in data, "Missing tier in response"
    assert "available_credits" in data, "Missing available_credits in response"
    assert "needs_subscription" in data, "Missing needs_subscription in response"
    print(f"✓ Sync updates tier to '{data['tier']}' with {data['available_credits']} credits")
    
    # Restore to booked-out for cleanup
    api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_2999_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )


# ============================================
# Test 9: POST /api/subscription/sync with bodybound_1499_1m_3d sets tier to walk-in and credits to 125
# ============================================
def test_subscription_sync_walk_in_tier(api, demo_token):
    """Sync with bodybound_1499_1m_3d sets tier to walk-in and credits to 125."""
    r = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_1499_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["tier"] == "walk-in", f"Expected tier='walk-in', got '{data['tier']}'"
    assert data["available_credits"] == 125, f"Expected 125 credits, got {data['available_credits']}"
    assert data["needs_subscription"] == False
    print("✓ bodybound_1499_1m_3d → walk-in tier with 125 credits")
    
    # Restore to booked-out
    api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_2999_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )


# ============================================
# Test 10: POST /api/subscription/sync with bodybound_2999_1m_3d sets tier to booked-out and credits to 500
# ============================================
def test_subscription_sync_booked_out_tier(api, demo_token):
    """Sync with bodybound_2999_1m_3d sets tier to booked-out and credits to 500."""
    r = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_2999_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["tier"] == "booked-out", f"Expected tier='booked-out', got '{data['tier']}'"
    assert data["available_credits"] == 500, f"Expected 500 credits, got {data['available_credits']}"
    assert data["needs_subscription"] == False
    print("✓ bodybound_2999_1m_3d → booked-out tier with 500 credits")


# ============================================
# Test 11: POST /api/subscription/sync with bodybound_9999_1m_3d sets tier to the-shop and credits to 1500
# ============================================
def test_subscription_sync_the_shop_tier(api, demo_token):
    """Sync with bodybound_9999_1m_3d sets tier to the-shop and credits to 1500."""
    r = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_9999_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["tier"] == "the-shop", f"Expected tier='the-shop', got '{data['tier']}'"
    assert data["available_credits"] == 1500, f"Expected 1500 credits, got {data['available_credits']}"
    assert data["needs_subscription"] == False
    print("✓ bodybound_9999_1m_3d → the-shop tier with 1500 credits")
    
    # Restore to booked-out
    api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_2999_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )


# ============================================
# Test 12: POST /api/subscription/sync idempotent — calling twice with same product doesn't change credits
# ============================================
def test_subscription_sync_idempotent(api, demo_token):
    """Sync is idempotent - calling twice with same product doesn't reset credits."""
    # First sync to walk-in
    r1 = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_1499_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r1.status_code == 200
    credits_after_first = r1.json()["available_credits"]
    
    # Second sync with same product - should not reset credits
    r2 = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_1499_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r2.status_code == 200
    credits_after_second = r2.json()["available_credits"]
    
    # Credits should remain the same (idempotent)
    assert credits_after_first == credits_after_second, \
        f"Credits changed from {credits_after_first} to {credits_after_second} on second sync"
    print(f"✓ Sync is idempotent - credits remain {credits_after_second} after second call")
    
    # Restore to booked-out
    api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_2999_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )


# ============================================
# Test 13: POST /api/webhooks/revenuecat still works for INITIAL_PURCHASE events
# ============================================
def test_revenuecat_webhook_initial_purchase(api):
    """RevenueCat webhook handles INITIAL_PURCHASE events."""
    # Test without auth - should return 401
    r_no_auth = api.post("/api/webhooks/revenuecat", json={
        "event": {
            "type": "INITIAL_PURCHASE",
            "app_user_id": "test_webhook_user",
            "product_id": "bodybound_2999_1m_3d"
        }
    })
    assert r_no_auth.status_code == 401, f"Expected 401 without auth, got {r_no_auth.status_code}"
    print("✓ Webhook returns 401 without auth")
    
    # Test with correct auth
    r_with_auth = api.post(
        "/api/webhooks/revenuecat",
        json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": "test_webhook_user_123",
                "product_id": "bodybound_2999_1m_3d"
            }
        },
        headers={"Authorization": f"Bearer {REVENUECAT_WEBHOOK_AUTH}"}
    )
    assert r_with_auth.status_code == 200, f"Expected 200, got {r_with_auth.status_code}"
    data = r_with_auth.json()
    assert data.get("status") == "ok", f"Expected status='ok', got {data}"
    print("✓ Webhook handles INITIAL_PURCHASE event successfully")


# ============================================
# Test 14: POST /api/tasks/refresh-credits endpoint still exists and works with cron secret
# ============================================
def test_refresh_credits_endpoint(api):
    """Refresh credits endpoint works with cron secret."""
    # Test without secret - should return 401
    r_no_secret = api.post("/api/tasks/refresh-credits")
    assert r_no_secret.status_code == 401, f"Expected 401 without secret, got {r_no_secret.status_code}"
    print("✓ Refresh credits returns 401 without cron secret")
    
    # Test with correct secret
    r_with_secret = api.post(
        "/api/tasks/refresh-credits",
        headers={"X-Cron-Secret": CRON_SECRET}
    )
    assert r_with_secret.status_code == 200, f"Expected 200, got {r_with_secret.status_code}"
    data = r_with_secret.json()
    assert "refreshed" in data, "Missing 'refreshed' in response"
    assert "checked" in data, "Missing 'checked' in response"
    assert "timestamp" in data, "Missing 'timestamp' in response"
    print(f"✓ Refresh credits works: refreshed={data['refreshed']}, checked={data['checked']}")


# ============================================
# Additional Test: Verify all credit fields in /api/auth/me response
# ============================================
def test_auth_me_credit_fields_complete(api, demo_token):
    """Verify all expected credit fields are present in /api/auth/me response."""
    r = api.get("/api/auth/me", headers={"Authorization": f"Bearer {demo_token}"})
    assert r.status_code == 200
    credits = r.json()["credits"]
    
    expected_fields = [
        "available_credits",
        "tier",
        "is_trial",
        "trial_expires_at",
        "trial_days_remaining",
        "renewal_date",
        "needs_subscription",
        "is_studio_team",
        "studio_team_id"
    ]
    
    for field in expected_fields:
        assert field in credits, f"Missing field '{field}' in credits response"
    
    print(f"✓ All expected credit fields present: {list(credits.keys())}")


# ============================================
# Additional Test: Verify tier transitions work correctly
# ============================================
def test_tier_transitions(api, demo_token):
    """Test that tier transitions work correctly in both directions."""
    # Start with walk-in
    r1 = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_1499_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r1.status_code == 200
    assert r1.json()["tier"] == "walk-in"
    
    # Upgrade to the-shop
    r2 = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_9999_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r2.status_code == 200
    assert r2.json()["tier"] == "the-shop"
    assert r2.json()["available_credits"] == 1500
    
    # Downgrade to booked-out
    r3 = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_2999_1m_3d"},
        headers={"Authorization": f"Bearer {demo_token}"},
    )
    assert r3.status_code == 200
    assert r3.json()["tier"] == "booked-out"
    assert r3.json()["available_credits"] == 500
    
    print("✓ Tier transitions work correctly: walk-in → the-shop → booked-out")
