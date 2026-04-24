"""Tests for Trial Credit Cap and Refer-a-Friend features (Iteration 6).

New features tested:
1. Trial Credit Cap: TRIAL_CREDITS=10 for ALL tiers during Apple trial
2. Refer-a-Friend: GET /api/referral/code and POST /api/referral/redeem

PRODUCT_CREDIT_MAP:
- bodybound_1499_1m_3d → walk-in/125
- bodybound_2999_1m_3d → booked-out/500
- bodybound_9999_1m_3d → the-shop/1500
"""
import pytest
import httpx
import uuid

API_URL = "https://stencil-ai-fallback.preview.emergentagent.com"
REVENUECAT_WEBHOOK_AUTH = os.environ.get("REVENUECAT_WEBHOOK_AUTH", "")
CRON_SECRET = "bb-cron-2026-refresh-c7f3a1"

# Expected values
TRIAL_CREDITS = 10
REFERRAL_BONUS_CREDITS = 20
PRODUCT_CREDITS = {
    "bodybound_1499_1m_3d": {"tier": "walk-in", "credits": 125},
    "bodybound_2999_1m_3d": {"tier": "booked-out", "credits": 500},
    "bodybound_9999_1m_3d": {"tier": "the-shop", "credits": 1500},
}


@pytest.fixture
def api():
    return httpx.Client(base_url=API_URL, timeout=15.0)


@pytest.fixture
def demo_token(api):
    """Get demo account token."""
    r = api.post("/api/auth/demo-login")
    assert r.status_code == 200
    return r.json()["session_token"]


@pytest.fixture
def auth_headers(demo_token):
    """Auth headers for demo account."""
    return {"Authorization": f"Bearer {demo_token}"}


# ============================================================
# HEALTH CHECK
# ============================================================

def test_health(api):
    """GET /api/health returns 200."""
    r = api.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


# ============================================================
# TRIAL CREDIT CAP - /api/subscription/sync
# ============================================================

class TestTrialCreditCapSync:
    """Tests for trial credit cap via /api/subscription/sync endpoint."""
    
    def test_sync_trial_walk_in_returns_10_credits(self, api, auth_headers):
        """POST /api/subscription/sync with is_trial=true for walk-in returns 10 credits."""
        r = api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_1499_1m_3d", "is_trial": True},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == "walk-in"
        assert data["available_credits"] == TRIAL_CREDITS, f"Expected {TRIAL_CREDITS} trial credits, got {data['available_credits']}"
        assert data.get("is_trial") == True
    
    def test_sync_trial_booked_out_returns_10_credits(self, api, auth_headers):
        """POST /api/subscription/sync with is_trial=true for booked-out returns 10 credits."""
        r = api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_2999_1m_3d", "is_trial": True},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == "booked-out"
        assert data["available_credits"] == TRIAL_CREDITS, f"Expected {TRIAL_CREDITS} trial credits, got {data['available_credits']}"
        assert data.get("is_trial") == True
    
    def test_sync_trial_the_shop_returns_10_credits(self, api, auth_headers):
        """POST /api/subscription/sync with is_trial=true for the-shop returns 10 credits."""
        r = api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_9999_1m_3d", "is_trial": True},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == "the-shop"
        assert data["available_credits"] == TRIAL_CREDITS, f"Expected {TRIAL_CREDITS} trial credits, got {data['available_credits']}"
        assert data.get("is_trial") == True
    
    def test_sync_paid_walk_in_returns_125_credits(self, api, auth_headers):
        """POST /api/subscription/sync with is_trial=false for walk-in returns 125 credits."""
        r = api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_1499_1m_3d", "is_trial": False},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == "walk-in"
        assert data["available_credits"] == 125, f"Expected 125 paid credits, got {data['available_credits']}"
        assert data.get("is_trial") == False
    
    def test_sync_paid_booked_out_returns_500_credits(self, api, auth_headers):
        """POST /api/subscription/sync with is_trial=false for booked-out returns 500 credits."""
        r = api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_2999_1m_3d", "is_trial": False},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == "booked-out"
        assert data["available_credits"] == 500, f"Expected 500 paid credits, got {data['available_credits']}"
        assert data.get("is_trial") == False
    
    def test_sync_paid_the_shop_returns_1500_credits(self, api, auth_headers):
        """POST /api/subscription/sync with is_trial=false for the-shop returns 1500 credits."""
        r = api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_9999_1m_3d", "is_trial": False},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == "the-shop"
        assert data["available_credits"] == 1500, f"Expected 1500 paid credits, got {data['available_credits']}"
        assert data.get("is_trial") == False
    
    def test_sync_sets_is_trial_flag(self, api, auth_headers):
        """POST /api/subscription/sync correctly sets is_trial flag in subscription."""
        # First set to trial
        r1 = api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_2999_1m_3d", "is_trial": True},
            headers=auth_headers,
        )
        assert r1.status_code == 200
        assert r1.json().get("is_trial") == True
        
        # Then set to paid
        r2 = api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_2999_1m_3d", "is_trial": False},
            headers=auth_headers,
        )
        assert r2.status_code == 200
        assert r2.json().get("is_trial") == False


# ============================================================
# TRIAL CREDIT CAP - /api/webhooks/revenuecat
# ============================================================

class TestTrialCreditCapWebhook:
    """Tests for trial credit cap via RevenueCat webhook."""
    
    def test_webhook_trial_grants_10_credits(self, api):
        """POST /api/webhooks/revenuecat with period_type=TRIAL grants only 10 credits."""
        webhook_payload = {
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": "demo_reviewer_account",
                "product_id": "bodybound_2999_1m_3d",
                "period_type": "TRIAL",
            }
        }
        r = api.post(
            "/api/webhooks/revenuecat",
            json=webhook_payload,
            headers={"Authorization": f"Bearer {REVENUECAT_WEBHOOK_AUTH}"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        
        # Verify credits via /api/auth/me
        login = api.post("/api/auth/demo-login")
        token = login.json()["session_token"]
        me = api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        credits = me.json()["credits"]
        assert credits["available_credits"] == TRIAL_CREDITS, f"Expected {TRIAL_CREDITS} trial credits, got {credits['available_credits']}"
        assert credits.get("is_trial") == True
    
    def test_webhook_paid_grants_full_credits(self, api):
        """POST /api/webhooks/revenuecat with period_type=NORMAL grants full tier credits."""
        webhook_payload = {
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": "demo_reviewer_account",
                "product_id": "bodybound_2999_1m_3d",
                "period_type": "NORMAL",
            }
        }
        r = api.post(
            "/api/webhooks/revenuecat",
            json=webhook_payload,
            headers={"Authorization": f"Bearer {REVENUECAT_WEBHOOK_AUTH}"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        
        # Verify credits via /api/auth/me
        login = api.post("/api/auth/demo-login")
        token = login.json()["session_token"]
        me = api.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        credits = me.json()["credits"]
        assert credits["available_credits"] == 500, f"Expected 500 paid credits, got {credits['available_credits']}"
        assert credits.get("is_trial") == False


# ============================================================
# NEEDS_SUBSCRIPTION FOR TRIAL USERS
# ============================================================

class TestNeedsSubscriptionTrial:
    """Tests for needs_subscription field for trial users."""
    
    def test_needs_subscription_false_for_trial_users(self, api, auth_headers):
        """GET /api/auth/me needs_subscription is False for trial users (tier not null)."""
        # Set user to trial
        api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_2999_1m_3d", "is_trial": True},
            headers=auth_headers,
        )
        
        # Check needs_subscription
        me = api.get("/api/auth/me", headers=auth_headers)
        assert me.status_code == 200
        credits = me.json()["credits"]
        assert credits["tier"] is not None
        assert credits["needs_subscription"] == False, "Trial users with active tier should have needs_subscription=False"


# ============================================================
# REFERRAL CODE - GET /api/referral/code
# ============================================================

class TestReferralCodeGet:
    """Tests for GET /api/referral/code endpoint."""
    
    def test_get_referral_code_returns_code(self, api, auth_headers):
        """GET /api/referral/code returns a referral code for authenticated user."""
        r = api.get("/api/referral/code", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "referral_code" in data
        assert data["referral_code"].startswith("BB-")
        assert len(data["referral_code"]) == 9  # BB-XXXXXX
    
    def test_get_referral_code_idempotent(self, api, auth_headers):
        """GET /api/referral/code returns same code on subsequent calls (idempotent)."""
        r1 = api.get("/api/referral/code", headers=auth_headers)
        assert r1.status_code == 200
        code1 = r1.json()["referral_code"]
        
        r2 = api.get("/api/referral/code", headers=auth_headers)
        assert r2.status_code == 200
        code2 = r2.json()["referral_code"]
        
        assert code1 == code2, "Referral code should be the same on subsequent calls"
    
    def test_get_referral_code_returns_stats(self, api, auth_headers):
        """GET /api/referral/code returns total_referrals and credits_earned fields."""
        r = api.get("/api/referral/code", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "total_referrals" in data
        assert "credits_earned" in data
        assert isinstance(data["total_referrals"], int)
        assert isinstance(data["credits_earned"], int)
    
    def test_get_referral_code_requires_auth(self, api):
        """GET /api/referral/code requires authentication."""
        r = api.get("/api/referral/code")
        assert r.status_code == 401


# ============================================================
# REFERRAL REDEEM - POST /api/referral/redeem
# ============================================================

class TestReferralRedeem:
    """Tests for POST /api/referral/redeem endpoint."""
    
    def test_redeem_requires_auth(self, api):
        """POST /api/referral/redeem requires auth (401 without token)."""
        r = api.post("/api/referral/redeem", json={"referral_code": "BB-ABCDEF"})
        assert r.status_code == 401
    
    def test_redeem_missing_code_returns_400(self, api, auth_headers):
        """POST /api/referral/redeem returns 400 for missing referral_code."""
        r = api.post("/api/referral/redeem", json={}, headers=auth_headers)
        assert r.status_code == 400
        assert "Missing referral_code" in r.json().get("detail", "")
    
    def test_redeem_invalid_code_returns_404(self, api, auth_headers):
        """POST /api/referral/redeem returns 404 for invalid referral code."""
        r = api.post(
            "/api/referral/redeem",
            json={"referral_code": "BB-INVALID"},
            headers=auth_headers,
        )
        assert r.status_code == 404
        assert "Invalid referral code" in r.json().get("detail", "")
    
    def test_redeem_self_referral_blocked(self, api, auth_headers):
        """POST /api/referral/redeem blocks self-referral with 400."""
        # Get user's own referral code
        code_r = api.get("/api/referral/code", headers=auth_headers)
        assert code_r.status_code == 200
        own_code = code_r.json()["referral_code"]
        
        # Try to redeem own code
        r = api.post(
            "/api/referral/redeem",
            json={"referral_code": own_code},
            headers=auth_headers,
        )
        assert r.status_code == 400
        assert "Cannot redeem your own" in r.json().get("detail", "")


# ============================================================
# PREVIOUS PAYWALL TESTS (REGRESSION)
# ============================================================

class TestPaywallRegression:
    """Regression tests for previous paywall features."""
    
    def test_demo_login_works(self, api):
        """Demo login still works."""
        r = api.post("/api/auth/demo-login")
        assert r.status_code == 200
        assert "session_token" in r.json()
    
    def test_subscription_sync_requires_auth(self, api):
        """Sync endpoint requires authorization."""
        r = api.post("/api/subscription/sync", json={"product_id": "bodybound_2999_1m_3d"})
        assert r.status_code == 401
    
    def test_subscription_sync_requires_product_id(self, api, auth_headers):
        """Sync endpoint requires product_id."""
        r = api.post("/api/subscription/sync", json={}, headers=auth_headers)
        assert r.status_code == 400
    
    def test_subscription_sync_rejects_unknown_product(self, api, auth_headers):
        """Sync endpoint rejects unknown product IDs."""
        r = api.post(
            "/api/subscription/sync",
            json={"product_id": "fake_product_123"},
            headers=auth_headers,
        )
        assert r.status_code == 400
    
    def test_webhook_requires_auth(self, api):
        """RevenueCat webhook requires authorization."""
        r = api.post("/api/webhooks/revenuecat", json={"event": {}})
        assert r.status_code == 401
    
    def test_cron_refresh_requires_secret(self, api):
        """Cron refresh endpoint requires X-Cron-Secret header."""
        r = api.post("/api/tasks/refresh-credits")
        assert r.status_code == 401


# ============================================================
# CLEANUP - Restore demo user to booked-out paid
# ============================================================

class TestCleanup:
    """Cleanup tests - restore demo user to booked-out paid."""
    
    def test_cleanup_restore_demo_to_booked_out_paid(self, api, auth_headers):
        """Restore demo user to booked-out paid subscription for cleanup."""
        r = api.post(
            "/api/subscription/sync",
            json={"product_id": "bodybound_2999_1m_3d", "is_trial": False},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["tier"] == "booked-out"
        assert data["available_credits"] == 500
        assert data.get("is_trial") == False
        print(f"✓ Demo user restored to booked-out paid with 500 credits")
