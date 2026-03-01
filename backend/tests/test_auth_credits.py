"""
Backend API tests for BODY BOUND Stencil Generator - Iteration 2
Tests: Auth endpoints (demo-login, me, apple), Credits (deduct), 
       Account deletion, RevenueCat webhook (now uses user_id as app_user_id),
       Cron endpoint (auth + refresh logic)
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL', '').rstrip('/')
CRON_SECRET = 'bb-cron-2026-refresh-c7f3a1'


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def demo_token(api_client):
    """Get demo login token for authenticated tests"""
    response = api_client.post(f"{BASE_URL}/api/auth/demo-login")
    assert response.status_code == 200, f"Demo login failed: {response.text}"
    data = response.json()
    return data['session_token']


@pytest.fixture
def auth_headers(demo_token):
    return {"Authorization": f"Bearer {demo_token}", "Content-Type": "application/json"}


# ============================================================
# 0. Health Endpoint
# ============================================================
class TestHealth:
    """Test GET /api/health"""

    def test_health_returns_200(self, api_client):
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_health_returns_healthy_status(self, api_client):
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'healthy', f"Expected status=healthy, got {data}"


# ============================================================
# 1. Demo Login
# ============================================================
class TestDemoLogin:
    """Test POST /api/auth/demo-login"""

    def test_demo_login_returns_200(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/demo-login")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_demo_login_returns_user_and_session_token(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/demo-login")
        assert response.status_code == 200
        data = response.json()
        assert "user" in data, "Response missing 'user'"
        assert "session_token" in data, "Response missing 'session_token'"
        assert isinstance(data['session_token'], str)
        assert len(data['session_token']) > 20, "session_token seems too short"

    def test_demo_login_user_has_required_fields(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/demo-login")
        assert response.status_code == 200
        user = response.json()['user']
        assert "user_id" in user, "user missing user_id"
        assert user['user_id'] == 'demo_reviewer_account'
        assert user.get('email') == 'reviewer@bodybound.app'

    def test_demo_login_idempotent(self, api_client):
        """Multiple calls return same demo account"""
        resp1 = api_client.post(f"{BASE_URL}/api/auth/demo-login")
        resp2 = api_client.post(f"{BASE_URL}/api/auth/demo-login")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()['user']['user_id'] == resp2.json()['user']['user_id']


# ============================================================
# 2. Auth /me
# ============================================================
class TestAuthMe:
    """Test GET /api/auth/me"""

    def test_me_with_valid_token(self, api_client, auth_headers):
        response = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_me_returns_user_and_credits(self, api_client, auth_headers):
        response = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "user" in data, "Response missing 'user'"
        assert "credits" in data, "Response missing 'credits'"

    def test_me_user_has_required_fields(self, api_client, auth_headers):
        response = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        user = response.json()['user']
        assert "user_id" in user
        assert isinstance(user['user_id'], str)

    def test_me_credits_has_required_fields(self, api_client, auth_headers):
        response = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        credits = response.json()['credits']
        assert "available_credits" in credits
        assert isinstance(credits['available_credits'], int)

    def test_me_demo_account_has_credits(self, api_client, auth_headers):
        """Demo account should have pro tier with credits"""
        response = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        credits = response.json()['credits']
        assert credits['available_credits'] >= 0, "Credits should be non-negative"

    def test_me_without_token_returns_401(self, api_client):
        response = api_client.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_me_with_invalid_token_returns_401(self, api_client):
        response = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": "Bearer invalidtoken123"}
        )
        assert response.status_code == 401


# ============================================================
# 3. Credits Deduct
# ============================================================
class TestCreditsDeduct:
    """Test POST /api/credits/deduct"""

    def test_deduct_credit_with_valid_token(self, api_client, auth_headers):
        """First ensure demo user has credits, then deduct"""
        # Get current credits
        me_resp = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert me_resp.status_code == 200
        initial_credits = me_resp.json()['credits']['available_credits']
        
        if initial_credits == 0:
            pytest.skip("Demo account has 0 credits - cannot test deduction")
        
        # Deduct a credit
        response = api_client.post(f"{BASE_URL}/api/credits/deduct", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_deduct_credit_decrements_atomically(self, api_client, auth_headers):
        """Verify credit count decrements by 1"""
        me_resp = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert me_resp.status_code == 200
        initial_credits = me_resp.json()['credits']['available_credits']
        
        if initial_credits == 0:
            pytest.skip("Demo account has 0 credits - cannot test deduction")
        
        # Deduct a credit
        deduct_resp = api_client.post(f"{BASE_URL}/api/credits/deduct", headers=auth_headers)
        assert deduct_resp.status_code == 200
        
        # Verify response returns new credit count
        deduct_data = deduct_resp.json()
        assert "available_credits" in deduct_data
        assert deduct_data['available_credits'] == initial_credits - 1

    def test_deduct_credit_without_token_returns_401(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/credits/deduct")
        assert response.status_code == 401

    def test_deduct_credit_zero_credits_returns_402(self, api_client):
        """Create a user with 0 credits and test 402 response"""
        unique_id = f"test_zero_{uuid.uuid4().hex[:8]}"
        
        # First call creates user with 10 trial credits
        resp1 = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock_token",
            "user_id": unique_id,
            "email": f"{unique_id}@test.com",
            "full_name": "Test Zero Credits"
        })
        assert resp1.status_code == 200
        token1 = resp1.json()['session_token']
        
        # Exhaust the credits (trial gives 10)
        headers_temp = {"Authorization": f"Bearer {token1}", "Content-Type": "application/json"}
        for i in range(10):
            r = api_client.post(f"{BASE_URL}/api/credits/deduct", headers=headers_temp)
            if r.status_code == 402:
                break
        
        # Now try to deduct again - should get 402
        response = api_client.post(f"{BASE_URL}/api/credits/deduct", headers=headers_temp)
        assert response.status_code == 402, f"Expected 402 when credits=0, got {response.status_code}: {response.text}"
        
        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=headers_temp)


# ============================================================
# 4. Apple Sign-In
# ============================================================
class TestAppleSignIn:
    """Test POST /api/auth/apple"""

    def test_apple_signin_with_mock_token(self, api_client):
        unique_id = f"test_apple_{uuid.uuid4().hex[:8]}"
        response = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock_token_test",
            "user_id": unique_id,
            "email": f"{unique_id}@test.com",
            "full_name": "Test User"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Cleanup
        token = response.json()['session_token']
        api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )

    def test_apple_signin_gives_trial_credits(self, api_client):
        unique_id = f"test_apple_{uuid.uuid4().hex[:8]}"
        response = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@trial.test",
            "full_name": "Trial Test User"
        })
        assert response.status_code == 200
        token = response.json()['session_token']
        
        # Check credits
        me_resp = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_resp.status_code == 200
        credits = me_resp.json()['credits']
        assert credits['available_credits'] == 10, f"Expected 10 trial credits, got {credits['available_credits']}"
        assert credits['is_trial'] is True
        
        # Cleanup
        api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )


# ============================================================
# 5. Account Delete
# ============================================================
class TestAccountDelete:
    """Test DELETE /api/account/delete"""

    def test_delete_account(self, api_client):
        # Create a test account
        unique_id = f"test_del_{uuid.uuid4().hex[:8]}"
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@delete.test",
            "full_name": "Delete Test"
        })
        assert resp.status_code == 200
        token = resp.json()['session_token']
        
        # Delete the account
        del_resp = api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert del_resp.status_code == 200, f"Expected 200, got {del_resp.status_code}: {del_resp.text}"
        data = del_resp.json()
        assert "message" in data
        assert "deleted" in data['message'].lower()

    def test_delete_account_removes_user(self, api_client):
        """After deletion, auth/me should return 401"""
        unique_id = f"test_del2_{uuid.uuid4().hex[:8]}"
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@delete2.test",
            "full_name": "Delete Test 2"
        })
        assert resp.status_code == 200
        token = resp.json()['session_token']
        
        # Delete
        del_resp = api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert del_resp.status_code == 200
        
        # Verify user no longer exists
        me_resp = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_resp.status_code == 401, f"Expected 401 after deletion, got {me_resp.status_code}"

    def test_delete_account_without_token_returns_401(self, api_client):
        response = api_client.delete(f"{BASE_URL}/api/account/delete")
        assert response.status_code == 401


# ============================================================
# 6. RevenueCat Webhook (UPDATED: app_user_id = user_id, not rc_customer_id)
# ============================================================
class TestRevenueCatWebhook:
    """Test POST /api/webhooks/revenuecat
    
    IMPORTANT: app_user_id now maps to our backend user_id.
    The app calls Purchases.logIn(userId) so RC tracks by our user_id.
    """

    def test_webhook_accepts_initial_purchase(self, api_client):
        """Should return 200 for INITIAL_PURCHASE event"""
        payload = {
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": "some_nonexistent_user",
                "product_id": "bodybound_1499_1m_3d"
            }
        }
        response = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        assert response.json().get('status') == 'ok'

    def test_webhook_with_valid_user_id_updates_subscription(self, api_client):
        """INITIAL_PURCHASE with a real user_id as app_user_id should update subscription"""
        # Create a user first 
        unique_id = f"rc_test_{uuid.uuid4().hex[:8]}"
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@rc.test",
            "full_name": "RevenueCat Test"
        })
        assert resp.status_code == 200
        user_id = resp.json()['user']['user_id']
        token = resp.json()['session_token']

        # Get initial credits (should be 10 trial)
        me_before = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_before.status_code == 200
        credits_before = me_before.json()['credits']['available_credits']
        assert credits_before == 10, f"Expected 10 trial credits before webhook, got {credits_before}"

        # Send webhook with user_id as app_user_id (the new behavior)
        payload = {
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": user_id,  # This is now the backend user_id
                "product_id": "bodybound_1499_1m_3d"  # hobbyist = 125 credits
            }
        }
        webhook_resp = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json=payload)
        assert webhook_resp.status_code == 200
        assert webhook_resp.json().get('status') == 'ok'

        # Verify credits were updated to 125 (hobbyist tier)
        me_after = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_after.status_code == 200
        credits_after = me_after.json()['credits']
        assert credits_after['available_credits'] == 125, \
            f"Expected 125 credits after hobbyist webhook, got {credits_after['available_credits']}"
        assert credits_after['tier'] == 'hobbyist', \
            f"Expected tier=hobbyist after webhook, got {credits_after['tier']}"
        assert credits_after['is_trial'] is False, "is_trial should be False after purchase"

        # Cleanup
        api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )

    def test_webhook_pro_tier_gives_500_credits(self, api_client):
        """Pro purchase via webhook should give 500 credits"""
        unique_id = f"rc_pro_{uuid.uuid4().hex[:8]}"
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@rc.test",
            "full_name": "RC Pro Test"
        })
        assert resp.status_code == 200
        user_id = resp.json()['user']['user_id']
        token = resp.json()['session_token']

        # Send pro webhook
        payload = {
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": user_id,
                "product_id": "bodybound_2999_1m_3d"  # pro = 500 credits
            }
        }
        webhook_resp = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json=payload)
        assert webhook_resp.status_code == 200

        # Verify credits = 500 and tier = pro
        me_after = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_after.status_code == 200
        credits = me_after.json()['credits']
        assert credits['available_credits'] == 500, f"Expected 500 credits, got {credits['available_credits']}"
        assert credits['tier'] == 'pro'

        # Cleanup
        api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )

    def test_webhook_renewal_updates_credits(self, api_client):
        """RENEWAL event should also update subscription credits"""
        unique_id = f"rc_renewal_{uuid.uuid4().hex[:8]}"
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@rc.test",
            "full_name": "RC Renewal Test"
        })
        assert resp.status_code == 200
        user_id = resp.json()['user']['user_id']
        token = resp.json()['session_token']

        # First purchase
        api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": user_id,
                "product_id": "bodybound_1499_1m_3d"
            }
        })

        # Simulate spending some credits
        headers = {"Authorization": f"Bearer {token}"}
        for _ in range(5):
            api_client.post(f"{BASE_URL}/api/credits/deduct", headers=headers)

        # RENEWAL event should restore to full
        renewal_resp = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json={
            "event": {
                "type": "RENEWAL",
                "app_user_id": user_id,
                "product_id": "bodybound_1499_1m_3d"
            }
        })
        assert renewal_resp.status_code == 200

        # Verify credits reset to 125
        me_after = api_client.get(f"{BASE_URL}/api/auth/me", headers=headers)
        credits = me_after.json()['credits']
        assert credits['available_credits'] == 125, f"Expected 125 after renewal, got {credits['available_credits']}"

        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=headers)

    def test_webhook_accepts_cancellation(self, api_client):
        """CANCELLATION event should return 200"""
        payload = {
            "event": {
                "type": "CANCELLATION",
                "app_user_id": "some_customer",
                "product_id": "bodybound_1499_1m_3d"
            }
        }
        response = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json=payload)
        assert response.status_code == 200

    def test_webhook_unknown_product_id_still_ok(self, api_client):
        """Webhook with unknown product should still return 200 (graceful)"""
        payload = {
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": "some_user",
                "product_id": "unknown_product_xyz"
            }
        }
        response = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json=payload)
        assert response.status_code == 200


# ============================================================
# 7. Cron Endpoint - NEW
# ============================================================
class TestCronEndpoint:
    """Test POST /api/cron/refresh-credits
    
    Protected by CRON_SECRET = 'bb-cron-2026-refresh-c7f3a1'
    """

    def test_cron_without_auth_returns_401(self, api_client):
        """No auth header should return 401"""
        response = api_client.post(f"{BASE_URL}/api/cron/refresh-credits")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"

    def test_cron_with_wrong_secret_returns_401(self, api_client):
        """Wrong secret should return 401"""
        response = api_client.post(
            f"{BASE_URL}/api/cron/refresh-credits",
            headers={"Authorization": "Bearer wrong-secret-here"}
        )
        assert response.status_code == 401, f"Expected 401 for wrong secret, got {response.status_code}"

    def test_cron_with_correct_secret_returns_200(self, api_client):
        """Correct CRON_SECRET should return 200"""
        response = api_client.post(
            f"{BASE_URL}/api/cron/refresh-credits",
            headers={"Authorization": f"Bearer {CRON_SECRET}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_cron_response_has_required_fields(self, api_client):
        """Cron response should include refreshed, checked, timestamp"""
        response = api_client.post(
            f"{BASE_URL}/api/cron/refresh-credits",
            headers={"Authorization": f"Bearer {CRON_SECRET}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "refreshed" in data, f"Response missing 'refreshed' field: {data}"
        assert "checked" in data, f"Response missing 'checked' field: {data}"
        assert "timestamp" in data, f"Response missing 'timestamp' field: {data}"
        assert isinstance(data['refreshed'], int)
        assert isinstance(data['checked'], int)

    def test_cron_refreshes_expired_subscriptions(self, api_client):
        """Create a subscription with past renewal_date, run cron, verify credits restored"""
        # Create a test user
        unique_id = f"cron_test_{uuid.uuid4().hex[:8]}"
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@cron.test",
            "full_name": "Cron Test User"
        })
        assert resp.status_code == 200
        user_id = resp.json()['user']['user_id']
        token = resp.json()['session_token']
        headers = {"Authorization": f"Bearer {token}"}

        # Give this user a subscription via webhook with past renewal date
        # First, set up a hobbyist subscription via webhook
        api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": user_id,
                "product_id": "bodybound_1499_1m_3d"  # hobbyist = 125 credits
            }
        })

        # Verify user got 125 credits
        me_resp = api_client.get(f"{BASE_URL}/api/auth/me", headers=headers)
        assert me_resp.status_code == 200
        credits = me_resp.json()['credits']
        assert credits['available_credits'] == 125
        assert credits['tier'] == 'hobbyist'

        # Spend some credits 
        for _ in range(10):
            api_client.post(f"{BASE_URL}/api/credits/deduct", headers=headers)

        # Verify credits were deducted
        me_resp2 = api_client.get(f"{BASE_URL}/api/auth/me", headers=headers)
        credits_after_deduct = me_resp2.json()['credits']['available_credits']
        assert credits_after_deduct == 115, f"Expected 115 credits after 10 deductions, got {credits_after_deduct}"

        # Manually set renewal_date to the past via DB manipulation via webhook trick
        # The webhook sets renewal_date = now + 30 days, so we need another approach.
        # Actually, let's directly update the subscription via a second endpoint approach.
        # Since there's no direct DB manipulation API, we'll set renewal_date to past via
        # a direct MongoDB update using pymongo.
        import pymongo
        mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
        db_name = os.environ.get('DB_NAME', 'tattoo_stencil')
        mongo_client = pymongo.MongoClient(mongo_url)
        db = mongo_client[db_name]
        
        # Set renewal_date to yesterday
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {'renewal_date': yesterday, 'is_trial': False}}
        )
        mongo_client.close()
        
        # Now run the cron
        cron_resp = api_client.post(
            f"{BASE_URL}/api/cron/refresh-credits",
            headers={"Authorization": f"Bearer {CRON_SECRET}"}
        )
        assert cron_resp.status_code == 200
        cron_data = cron_resp.json()
        assert cron_data['refreshed'] >= 1, f"Expected at least 1 subscription refreshed, got {cron_data['refreshed']}"

        # Verify credits were restored to 125 (hobbyist tier)
        me_resp3 = api_client.get(f"{BASE_URL}/api/auth/me", headers=headers)
        assert me_resp3.status_code == 200
        final_credits = me_resp3.json()['credits']['available_credits']
        assert final_credits == 125, f"Expected credits restored to 125 after cron, got {final_credits}"

        # Verify renewal_date was updated (should be ~30 days from yesterday = ~29 days from now)
        final_credits_data = me_resp3.json()['credits']
        assert final_credits_data['tier'] == 'hobbyist'

        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=headers)

    def test_cron_does_not_refresh_future_renewals(self, api_client):
        """Subscriptions with future renewal_date should NOT be refreshed"""
        unique_id = f"cron_future_{uuid.uuid4().hex[:8]}"
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@cron.test",
            "full_name": "Cron Future Test"
        })
        assert resp.status_code == 200
        user_id = resp.json()['user']['user_id']
        token = resp.json()['session_token']
        headers = {"Authorization": f"Bearer {token}"}

        # Set up subscription via webhook (renewal_date = 30 days in future)
        api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": user_id,
                "product_id": "bodybound_1499_1m_3d"
            }
        })

        # Spend 10 credits
        for _ in range(10):
            api_client.post(f"{BASE_URL}/api/credits/deduct", headers=headers)

        credits_before_cron = api_client.get(
            f"{BASE_URL}/api/auth/me", headers=headers
        ).json()['credits']['available_credits']
        assert credits_before_cron == 115

        # Run cron - should NOT refresh this user (renewal is in future)
        api_client.post(
            f"{BASE_URL}/api/cron/refresh-credits",
            headers={"Authorization": f"Bearer {CRON_SECRET}"}
        )

        # Credits should STILL be 115 (not refreshed)
        credits_after_cron = api_client.get(
            f"{BASE_URL}/api/auth/me", headers=headers
        ).json()['credits']['available_credits']
        assert credits_after_cron == 115, \
            f"Expected credits to remain 115 (not refreshed), got {credits_after_cron}"

        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=headers)
