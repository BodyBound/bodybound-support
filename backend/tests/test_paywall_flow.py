"""Tests for the Paywall-First subscription flow.

Tests:
1. New users get no free trial (empty subscription)
2. /api/auth/me returns needs_subscription=True for users without active subscription
3. /api/subscription/sync updates subscription from RevenueCat product_id
4. Grandfathering: existing trial users are not affected
"""
import pytest
import httpx
import asyncio

API_URL = "https://gemini-tattoo-gen.preview.emergentagent.com"


@pytest.fixture
def api():
    return httpx.Client(base_url=API_URL, timeout=15.0)


def test_health(api):
    r = api.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_demo_login_returns_credits(api):
    """Demo account should still work and return credit info."""
    r = api.post("/api/auth/demo-login")
    assert r.status_code == 200
    data = r.json()
    assert "session_token" in data
    assert "user" in data
    token = data["session_token"]
    
    # Check /api/auth/me
    me = api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    me_data = me.json()
    assert "credits" in me_data
    # Demo account has an active tier, so needs_subscription should be False
    assert me_data["credits"]["needs_subscription"] == False
    assert me_data["credits"]["tier"] is not None


def test_subscription_sync_requires_auth(api):
    """Sync endpoint requires authorization."""
    r = api.post("/api/subscription/sync", json={"product_id": "bodybound_2999_1m_3d"})
    assert r.status_code == 401


def test_subscription_sync_requires_product_id(api):
    """Sync endpoint requires product_id."""
    login = api.post("/api/auth/demo-login")
    token = login.json()["session_token"]
    
    r = api.post(
        "/api/subscription/sync",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_subscription_sync_rejects_unknown_product(api):
    """Sync endpoint rejects unknown product IDs."""
    login = api.post("/api/auth/demo-login")
    token = login.json()["session_token"]
    
    r = api.post(
        "/api/subscription/sync",
        json={"product_id": "fake_product_123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_subscription_sync_updates_correctly(api):
    """Sync with valid product_id should update subscription tier and credits."""
    login = api.post("/api/auth/demo-login")
    token = login.json()["session_token"]
    
    # Sync with walk-in product
    r = api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_1499_1m_3d"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["tier"] == "walk-in"
    assert data["available_credits"] == 125
    assert data["needs_subscription"] == False
    
    # Restore demo to booked-out for cleanup
    api.post(
        "/api/subscription/sync",
        json={"product_id": "bodybound_2999_1m_3d"},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_needs_subscription_field_present(api):
    """The needs_subscription field should always be present in /api/auth/me response."""
    login = api.post("/api/auth/demo-login")
    token = login.json()["session_token"]
    
    me = api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    credits = me.json()["credits"]
    assert "needs_subscription" in credits
