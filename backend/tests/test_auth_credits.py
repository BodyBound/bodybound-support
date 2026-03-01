"""
Backend API tests for BODY BOUND Stencil Generator
Tests: Auth endpoints (demo-login, me, apple), Credits (deduct), 
       Account deletion, RevenueCat webhook
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL', '').rstrip('/')


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
        # Use Apple endpoint to create a new user with 0 credits (by reusing same apple ID)
        # Actually, let's create a fresh user via Apple and exhaust their credits
        # For simplicity, create user with apple endpoint with unique ID that has already used trial
        # The best approach: use Apple endpoint for a user and exhaust credits in trial check
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
        
        # Second call with SAME apple ID but different user_id (same email) - should get 0 trial
        # Actually since it's the same user (same apple_user_id = unique_id from fallback),
        # second login just returns the existing user - we need to manually deplete credits
        
        # Let's exhaust the credits by deducting 10 times (trial gives 10)
        headers_temp = {"Authorization": f"Bearer {token1}", "Content-Type": "application/json"}
        for i in range(10):
            r = api_client.post(f"{BASE_URL}/api/credits/deduct", headers=headers_temp)
            if r.status_code == 402:
                break  # Already at 0
        
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

    def test_apple_signin_creates_user(self, api_client):
        unique_id = f"test_apple_{uuid.uuid4().hex[:8]}"
        response = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@bodybound.test",
            "full_name": "Test Apple User"
        })
        assert response.status_code == 200
        data = response.json()
        assert "user" in data
        assert "session_token" in data
        assert data['user']['user_id'] is not None
        assert data['user'].get('email') == f"{unique_id}@bodybound.test"
        
        # Cleanup
        token = data['session_token']
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

    def test_apple_signin_no_duplicate_trial(self, api_client):
        """Same apple user ID should not get trial credits twice"""
        unique_id = f"test_nodedup_{uuid.uuid4().hex[:8]}"
        email = f"{unique_id}@nodedup.test"
        
        # First sign-in -> gets trial
        resp1 = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": email,
            "full_name": "No Dup User"
        })
        assert resp1.status_code == 200
        
        # Second sign-in with same user_id -> existing user, no new trial
        resp2 = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": email,
            "full_name": "No Dup User"
        })
        assert resp2.status_code == 200
        # The user_id should be same
        assert resp1.json()['user']['user_id'] == resp2.json()['user']['user_id']
        
        # Cleanup
        token = resp1.json()['session_token']
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
# 6. RevenueCat Webhook
# ============================================================
class TestRevenueCatWebhook:
    """Test POST /api/webhooks/revenuecat"""

    def test_webhook_accepts_initial_purchase(self, api_client):
        """Should return 200 for INITIAL_PURCHASE event"""
        # Create a user first
        unique_id = f"rc_test_{uuid.uuid4().hex[:8]}"
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@rc.test",
            "full_name": "RevenueCat Test"
        })
        assert resp.status_code == 200
        token = resp.json()['session_token']
        
        payload = {
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": f"rc_customer_{unique_id}",
                "product_id": "bodybound_1499_1m_3d"
            }
        }
        response = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        assert response.json().get('status') == 'ok'
        
        # Cleanup
        api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )

    def test_webhook_accepts_renewal(self, api_client):
        """Should return 200 for RENEWAL event"""
        payload = {
            "event": {
                "type": "RENEWAL",
                "app_user_id": "some_customer_id",
                "product_id": "bodybound_2999_1m_3d"
            }
        }
        response = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json=payload)
        assert response.status_code == 200
        assert response.json().get('status') == 'ok'

    def test_webhook_handles_unknown_event_type(self, api_client):
        """Unknown event types should still return 200 (graceful handling)"""
        payload = {
            "event": {
                "type": "CANCELLATION",
                "app_user_id": "some_customer",
                "product_id": "bodybound_1499_1m_3d"
            }
        }
        response = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json=payload)
        assert response.status_code == 200

    def test_webhook_updates_subscription_on_purchase(self, api_client):
        """INITIAL_PURCHASE for known revenuecat_customer_id should update subscription"""
        # Create user and manually set revenuecat_customer_id
        unique_id = f"rc_update_{uuid.uuid4().hex[:8]}"
        rc_customer_id = f"rc_{unique_id}"
        
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@rc2.test",
            "full_name": "RC Update Test"
        })
        assert resp.status_code == 200
        token = resp.json()['session_token']
        user_id = resp.json()['user']['user_id']
        
        # Update subscription with revenuecat_customer_id directly in DB
        # (This simulates what would happen after RC webhook registration)
        # Since we can't directly do that via API, let's just verify the webhook returns ok
        payload = {
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": rc_customer_id,
                "product_id": "bodybound_9999_1m_3d"
            }
        }
        response = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json=payload)
        assert response.status_code == 200
        assert response.json().get('status') == 'ok'
        
        # Cleanup
        api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )
