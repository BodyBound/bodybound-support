"""
Backend API tests - BODY BOUND Stencil Generator - Iteration 3
New in this session:
  1. Renamed cron endpoint: /api/cron/refresh-credits -> /api/tasks/refresh-credits
  2. Changed auth header: 'Authorization: Bearer TOKEN' -> 'X-Cron-Secret: TOKEN'
  3. Verified expo-notifications + expo-device in package.json (static check)
  4. Verified .github/workflows/monthly_refresh.yml (static check)
  5. Old /api/cron/refresh-credits should return 404
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


# ============================================================
# 1. Old cron endpoint should be GONE (404)
# ============================================================
class TestOldCronEndpointGone:
    """Verify old /api/cron/refresh-credits no longer exists"""

    def test_old_cron_endpoint_returns_404_or_405(self, api_client):
        """Old endpoint /api/cron/refresh-credits should return 404 (renamed away)"""
        response = api_client.post(
            f"{BASE_URL}/api/cron/refresh-credits",
            headers={"Authorization": f"Bearer {CRON_SECRET}"}
        )
        assert response.status_code in [404, 405], (
            f"Old /api/cron/refresh-credits should not be accessible; "
            f"expected 404/405, got {response.status_code}: {response.text}"
        )

    def test_old_cron_endpoint_no_auth_also_returns_404_or_405(self, api_client):
        """Old endpoint without auth should also return 404 (not 401)"""
        response = api_client.post(f"{BASE_URL}/api/cron/refresh-credits")
        assert response.status_code in [404, 405], (
            f"Expected 404/405 for missing old endpoint, got {response.status_code}"
        )


# ============================================================
# 2. New /api/tasks/refresh-credits - Auth checks
# ============================================================
class TestTasksRefreshCreditsAuth:
    """Test POST /api/tasks/refresh-credits
    Protected by X-Cron-Secret header (NOT Authorization: Bearer)
    """

    def test_no_header_returns_401(self, api_client):
        """POST without any X-Cron-Secret header should return 401"""
        response = api_client.post(f"{BASE_URL}/api/tasks/refresh-credits")
        assert response.status_code == 401, (
            f"Expected 401 for missing X-Cron-Secret, got {response.status_code}: {response.text}"
        )

    def test_wrong_secret_returns_401(self, api_client):
        """POST with wrong X-Cron-Secret should return 401"""
        response = api_client.post(
            f"{BASE_URL}/api/tasks/refresh-credits",
            headers={"X-Cron-Secret": "wrong-secret-value"}
        )
        assert response.status_code == 401, (
            f"Expected 401 for wrong X-Cron-Secret, got {response.status_code}: {response.text}"
        )

    def test_old_authorization_bearer_returns_401(self, api_client):
        """Old Authorization: Bearer format should NOT work (401) - auth mechanism changed"""
        response = api_client.post(
            f"{BASE_URL}/api/tasks/refresh-credits",
            headers={"Authorization": f"Bearer {CRON_SECRET}"}
        )
        assert response.status_code == 401, (
            f"Old Bearer auth should not work; expected 401, got {response.status_code}: {response.text}"
        )

    def test_correct_x_cron_secret_returns_200(self, api_client):
        """POST with correct X-Cron-Secret should return 200"""
        response = api_client.post(
            f"{BASE_URL}/api/tasks/refresh-credits",
            headers={"X-Cron-Secret": CRON_SECRET}
        )
        assert response.status_code == 200, (
            f"Expected 200 with correct X-Cron-Secret, got {response.status_code}: {response.text}"
        )

    def test_correct_x_cron_secret_returns_required_fields(self, api_client):
        """Response should include refreshed, checked, timestamp"""
        response = api_client.post(
            f"{BASE_URL}/api/tasks/refresh-credits",
            headers={"X-Cron-Secret": CRON_SECRET}
        )
        assert response.status_code == 200
        data = response.json()
        assert "refreshed" in data, f"Response missing 'refreshed' field: {data}"
        assert "checked" in data, f"Response missing 'checked' field: {data}"
        assert "timestamp" in data, f"Response missing 'timestamp' field: {data}"
        assert isinstance(data['refreshed'], int), "refreshed should be an int"
        assert isinstance(data['checked'], int), "checked should be an int"
        assert isinstance(data['timestamp'], str), "timestamp should be a string"

    def test_response_refreshed_lte_checked(self, api_client):
        """refreshed count can't exceed checked count"""
        response = api_client.post(
            f"{BASE_URL}/api/tasks/refresh-credits",
            headers={"X-Cron-Secret": CRON_SECRET}
        )
        assert response.status_code == 200
        data = response.json()
        assert data['refreshed'] <= data['checked'], (
            f"refreshed ({data['refreshed']}) > checked ({data['checked']}) - impossible"
        )


# ============================================================
# 3. Credit refresh logic - renewal_date in past gets refreshed
# ============================================================
class TestTasksRefreshCreditsLogic:
    """Test credit refresh logic via /api/tasks/refresh-credits"""

    def test_expired_subscription_gets_refreshed(self, api_client):
        """Set renewal_date to yesterday, run tasks endpoint, verify credits restored"""
        unique_id = f"tasks_test_{uuid.uuid4().hex[:8]}"

        # Create a user
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@tasks.test",
            "full_name": "Tasks Refresh Test"
        })
        assert resp.status_code == 200
        user_id = resp.json()['user']['user_id']
        token = resp.json()['session_token']
        headers = {"Authorization": f"Bearer {token}"}

        # Give user a hobbyist subscription via webhook (125 credits)
        wh = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": user_id,
                "product_id": "bodybound_1499_1m_3d"
            }
        })
        assert wh.status_code == 200

        # Verify 125 credits
        me_resp = api_client.get(f"{BASE_URL}/api/auth/me", headers=headers)
        assert me_resp.json()['credits']['available_credits'] == 125

        # Spend 10 credits
        for _ in range(10):
            api_client.post(f"{BASE_URL}/api/credits/deduct", headers=headers)

        # Verify credits are now 115
        me_resp2 = api_client.get(f"{BASE_URL}/api/auth/me", headers=headers)
        assert me_resp2.json()['credits']['available_credits'] == 115, (
            f"Expected 115 credits after 10 deductions"
        )

        # Manually set renewal_date to yesterday via pymongo
        import pymongo
        mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
        db_name = os.environ.get('DB_NAME', 'tattoo_stencil')
        mongo_client = pymongo.MongoClient(mongo_url)
        db = mongo_client[db_name]
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {'renewal_date': yesterday, 'is_trial': False}}
        )
        mongo_client.close()

        # Run /api/tasks/refresh-credits with correct X-Cron-Secret
        cron_resp = api_client.post(
            f"{BASE_URL}/api/tasks/refresh-credits",
            headers={"X-Cron-Secret": CRON_SECRET}
        )
        assert cron_resp.status_code == 200
        cron_data = cron_resp.json()
        assert cron_data['refreshed'] >= 1, (
            f"Expected at least 1 subscription refreshed, got {cron_data['refreshed']}"
        )

        # Verify credits restored to 125 (hobbyist tier)
        me_resp3 = api_client.get(f"{BASE_URL}/api/auth/me", headers=headers)
        final_credits = me_resp3.json()['credits']['available_credits']
        assert final_credits == 125, (
            f"Expected credits restored to 125 after tasks refresh, got {final_credits}"
        )

        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=headers)

    def test_future_renewal_not_refreshed(self, api_client):
        """Subscription with future renewal_date should NOT be refreshed"""
        unique_id = f"tasks_future_{uuid.uuid4().hex[:8]}"

        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@tasks.test",
            "full_name": "Tasks Future Test"
        })
        assert resp.status_code == 200
        user_id = resp.json()['user']['user_id']
        token = resp.json()['session_token']
        headers = {"Authorization": f"Bearer {token}"}

        # Give hobbyist subscription (renewal_date = 30 days in future)
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

        credits_before = api_client.get(
            f"{BASE_URL}/api/auth/me", headers=headers
        ).json()['credits']['available_credits']
        assert credits_before == 115

        # Run cron - should NOT refresh this user (renewal in future)
        api_client.post(
            f"{BASE_URL}/api/tasks/refresh-credits",
            headers={"X-Cron-Secret": CRON_SECRET}
        )

        # Credits should remain 115
        credits_after = api_client.get(
            f"{BASE_URL}/api/auth/me", headers=headers
        ).json()['credits']['available_credits']
        assert credits_after == 115, (
            f"Expected credits to remain 115 (future renewal not refreshed), got {credits_after}"
        )

        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=headers)


# ============================================================
# 4. RevenueCat webhook - user_id as app_user_id
# ============================================================
class TestRevenueCatWebhookUserIdMapping:
    """Verify webhook still works with user_id as app_user_id (regression check)"""

    def test_initial_purchase_via_user_id_updates_credits(self, api_client):
        """INITIAL_PURCHASE with real user_id as app_user_id should update subscription"""
        unique_id = f"rc3_test_{uuid.uuid4().hex[:8]}"
        resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": unique_id,
            "email": f"{unique_id}@rc3.test",
            "full_name": "RC3 Test"
        })
        assert resp.status_code == 200
        user_id = resp.json()['user']['user_id']
        token = resp.json()['session_token']

        wh = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": user_id,
                "product_id": "bodybound_1499_1m_3d"
            }
        })
        assert wh.status_code == 200
        assert wh.json().get('status') == 'ok'

        me = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        credits = me.json()['credits']
        assert credits['available_credits'] == 125
        assert credits['tier'] == 'hobbyist'
        assert credits['is_trial'] is False

        # Cleanup
        api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )
