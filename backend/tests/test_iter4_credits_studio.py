"""
Backend API tests for BODY BOUND Stencil Generator - Iteration 4
Tests: Credit Management & Subscription System with:
  1) 3-day free trial with 10 credits
  2) Anti-abuse using Email + Device ID combo
  3) Studio tier team management (The Shop - $99/mo with 1500 shared credits for up to 5 members)
  
New endpoints tested:
  - GET /api/health
  - POST /api/auth/demo-login
  - GET /api/auth/me (new fields: trial_expires_at, trial_days_remaining, is_studio_team, studio_team_id)
  - POST /api/credits/deduct (with studio team support)
  - GET /api/studio/team
  - POST /api/studio/create
  - POST /api/studio/invite
  - POST /api/studio/accept-invite
  - DELETE /api/studio/member/{user_id}
  - POST /api/studio/leave
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timezone, timedelta

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
# 1. Health Endpoint
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
# 2. Demo Login
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


# ============================================================
# 3. Auth /me - NEW CREDIT FIELDS
# ============================================================
class TestAuthMeNewFields:
    """Test GET /api/auth/me returns new credit structure fields"""

    def test_me_returns_credits_with_trial_fields(self, api_client, auth_headers):
        """Verify /auth/me returns trial_expires_at and trial_days_remaining fields"""
        response = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "credits" in data, "Response missing 'credits'"
        credits = data['credits']
        
        # Check new trial fields exist (can be None for non-trial users)
        assert "trial_expires_at" in credits, "credits missing 'trial_expires_at' field"
        assert "trial_days_remaining" in credits, "credits missing 'trial_days_remaining' field"
        
    def test_me_returns_credits_with_studio_team_fields(self, api_client, auth_headers):
        """Verify /auth/me returns is_studio_team and studio_team_id fields"""
        response = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        credits = response.json()['credits']
        
        # Check new studio team fields exist
        assert "is_studio_team" in credits, "credits missing 'is_studio_team' field"
        assert "studio_team_id" in credits, "credits missing 'studio_team_id' field"
        
    def test_me_demo_account_not_in_studio_team(self, api_client, auth_headers):
        """Demo account should not be part of a studio team"""
        response = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        credits = response.json()['credits']
        
        assert credits['is_studio_team'] is False, "Demo account should not be in studio team"
        assert credits['studio_team_id'] is None, "Demo account should have no studio_team_id"


# ============================================================
# 4. Trial Credits with Device ID Anti-Abuse
# ============================================================
class TestTrialCreditsWithDeviceId:
    """Test 3-day trial with device_id anti-abuse"""

    def test_new_user_gets_10_trial_credits(self, api_client):
        """New user via Apple auth should get 10 trial credits"""
        unique_id = f"trial_test_{uuid.uuid4().hex[:8]}"
        response = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock_token",
            "user_id": unique_id,
            "email": f"{unique_id}@trial.test",
            "full_name": "Trial Test User",
            "device_id": f"device_{unique_id}"
        })
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        token = response.json()['session_token']
        
        # Check credits
        me_resp = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_resp.status_code == 200
        credits = me_resp.json()['credits']
        
        assert credits['available_credits'] == 10, f"Expected 10 trial credits, got {credits['available_credits']}"
        assert credits['is_trial'] is True, "is_trial should be True for new user"
        assert credits['trial_expires_at'] is not None, "trial_expires_at should be set"
        assert credits['trial_days_remaining'] is not None, "trial_days_remaining should be set"
        assert credits['trial_days_remaining'] <= 3, f"trial_days_remaining should be <= 3, got {credits['trial_days_remaining']}"
        
        # Cleanup
        api_client.delete(
            f"{BASE_URL}/api/account/delete",
            headers={"Authorization": f"Bearer {token}"}
        )

    def test_same_device_id_denied_second_trial(self, api_client):
        """Same device_id with different email should be denied trial (anti-abuse)"""
        device_id = f"device_abuse_{uuid.uuid4().hex[:8]}"
        
        # First user with this device
        user1_id = f"abuse_test1_{uuid.uuid4().hex[:8]}"
        resp1 = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": user1_id,
            "email": f"{user1_id}@abuse.test",
            "full_name": "Abuse Test 1",
            "device_id": device_id
        })
        assert resp1.status_code == 200
        token1 = resp1.json()['session_token']
        
        # Verify first user got trial
        me1 = api_client.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token1}"})
        assert me1.json()['credits']['available_credits'] == 10
        assert me1.json()['credits']['is_trial'] is True
        
        # Second user with SAME device_id but different email
        user2_id = f"abuse_test2_{uuid.uuid4().hex[:8]}"
        resp2 = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": user2_id,
            "email": f"{user2_id}@abuse.test",
            "full_name": "Abuse Test 2",
            "device_id": device_id  # Same device!
        })
        assert resp2.status_code == 200
        token2 = resp2.json()['session_token']
        
        # Second user should be denied trial (0 credits)
        me2 = api_client.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token2}"})
        credits2 = me2.json()['credits']
        assert credits2['available_credits'] == 0, f"Expected 0 credits for abuse attempt, got {credits2['available_credits']}"
        assert credits2['is_trial'] is False, "is_trial should be False for denied trial"
        
        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers={"Authorization": f"Bearer {token1}"})
        api_client.delete(f"{BASE_URL}/api/account/delete", headers={"Authorization": f"Bearer {token2}"})

    def test_same_email_denied_second_trial(self, api_client):
        """Same email with different device should be denied trial (anti-abuse)"""
        email = f"same_email_{uuid.uuid4().hex[:8]}@abuse.test"
        
        # First user with this email
        user1_id = f"email_abuse1_{uuid.uuid4().hex[:8]}"
        resp1 = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": user1_id,
            "email": email,
            "full_name": "Email Abuse 1",
            "device_id": f"device1_{uuid.uuid4().hex[:8]}"
        })
        assert resp1.status_code == 200
        token1 = resp1.json()['session_token']
        
        # Verify first user got trial
        me1 = api_client.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token1}"})
        assert me1.json()['credits']['available_credits'] == 10
        
        # Second user with SAME email but different device
        user2_id = f"email_abuse2_{uuid.uuid4().hex[:8]}"
        resp2 = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": user2_id,
            "email": email,  # Same email!
            "full_name": "Email Abuse 2",
            "device_id": f"device2_{uuid.uuid4().hex[:8]}"
        })
        assert resp2.status_code == 200
        token2 = resp2.json()['session_token']
        
        # Second user should be denied trial
        me2 = api_client.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token2}"})
        credits2 = me2.json()['credits']
        assert credits2['available_credits'] == 0, f"Expected 0 credits for email abuse, got {credits2['available_credits']}"
        
        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers={"Authorization": f"Bearer {token1}"})
        api_client.delete(f"{BASE_URL}/api/account/delete", headers={"Authorization": f"Bearer {token2}"})


# ============================================================
# 5. Credit Deduction with Studio Team Support
# ============================================================
class TestCreditDeduction:
    """Test POST /api/credits/deduct"""

    def test_deduct_credit_returns_200(self, api_client, auth_headers):
        """Deduct credit should return 200 for user with credits"""
        # First check if demo user has credits
        me_resp = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        initial_credits = me_resp.json()['credits']['available_credits']
        
        if initial_credits == 0:
            pytest.skip("Demo account has 0 credits - cannot test deduction")
        
        response = api_client.post(f"{BASE_URL}/api/credits/deduct", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_deduct_credit_decrements_by_one(self, api_client, auth_headers):
        """Verify credit count decrements by 1"""
        me_resp = api_client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        initial_credits = me_resp.json()['credits']['available_credits']
        
        if initial_credits == 0:
            pytest.skip("Demo account has 0 credits")
        
        deduct_resp = api_client.post(f"{BASE_URL}/api/credits/deduct", headers=auth_headers)
        assert deduct_resp.status_code == 200
        
        deduct_data = deduct_resp.json()
        assert "available_credits" in deduct_data
        assert deduct_data['available_credits'] == initial_credits - 1

    def test_deduct_without_auth_returns_401(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/credits/deduct")
        assert response.status_code == 401


# ============================================================
# 6. Studio Team - GET /api/studio/team
# ============================================================
class TestStudioTeamGet:
    """Test GET /api/studio/team"""

    def test_studio_team_returns_404_for_non_team_user(self, api_client, auth_headers):
        """Non-team user should get 404 when accessing studio team"""
        response = api_client.get(f"{BASE_URL}/api/studio/team", headers=auth_headers)
        assert response.status_code == 404, f"Expected 404 for non-team user, got {response.status_code}: {response.text}"
        
    def test_studio_team_without_auth_returns_401(self, api_client):
        response = api_client.get(f"{BASE_URL}/api/studio/team")
        assert response.status_code == 401


# ============================================================
# 7. Studio Team - POST /api/studio/create
# ============================================================
class TestStudioTeamCreate:
    """Test POST /api/studio/create"""

    def test_studio_create_requires_the_shop_tier(self, api_client, auth_headers):
        """Creating studio team without 'the-shop' subscription should return 403"""
        response = api_client.post(f"{BASE_URL}/api/studio/create", headers=auth_headers)
        # Demo account has 'pro' tier, not 'the-shop', so should get 403
        assert response.status_code == 403, f"Expected 403 (requires the-shop tier), got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "detail" in data
        assert "shop" in data['detail'].lower() or "subscription" in data['detail'].lower()

    def test_studio_create_without_auth_returns_401(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/studio/create")
        assert response.status_code == 401


# ============================================================
# 8. Studio Team - POST /api/studio/invite
# ============================================================
class TestStudioTeamInvite:
    """Test POST /api/studio/invite"""

    def test_studio_invite_requires_team_admin(self, api_client, auth_headers):
        """Non-admin user should get 403/404 when trying to invite"""
        response = api_client.post(
            f"{BASE_URL}/api/studio/invite",
            headers=auth_headers,
            json={"email": "test@example.com"}
        )
        # Demo user is not a team admin, should get 403 or 404
        assert response.status_code in [403, 404], f"Expected 403/404, got {response.status_code}: {response.text}"

    def test_studio_invite_without_auth_returns_401(self, api_client):
        response = api_client.post(
            f"{BASE_URL}/api/studio/invite",
            json={"email": "test@example.com"}
        )
        assert response.status_code == 401


# ============================================================
# 9. Studio Team - POST /api/studio/accept-invite
# ============================================================
class TestStudioTeamAcceptInvite:
    """Test POST /api/studio/accept-invite"""

    def test_accept_invite_invalid_code_returns_404(self, api_client, auth_headers):
        """Invalid invite code should return 404"""
        response = api_client.post(
            f"{BASE_URL}/api/studio/accept-invite",
            headers=auth_headers,
            json={"invite_code": "invalid_code_12345"}
        )
        assert response.status_code == 404, f"Expected 404 for invalid code, got {response.status_code}: {response.text}"

    def test_accept_invite_without_auth_returns_401(self, api_client):
        response = api_client.post(
            f"{BASE_URL}/api/studio/accept-invite",
            json={"invite_code": "some_code"}
        )
        assert response.status_code == 401


# ============================================================
# 10. Studio Team - DELETE /api/studio/member/{user_id}
# ============================================================
class TestStudioTeamRemoveMember:
    """Test DELETE /api/studio/member/{user_id}"""

    def test_remove_member_requires_admin(self, api_client, auth_headers):
        """Non-admin should get 403 when trying to remove member"""
        response = api_client.delete(
            f"{BASE_URL}/api/studio/member/some_user_id",
            headers=auth_headers
        )
        # Demo user is not a team admin
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"

    def test_remove_member_without_auth_returns_401(self, api_client):
        response = api_client.delete(f"{BASE_URL}/api/studio/member/some_user_id")
        assert response.status_code == 401


# ============================================================
# 11. Studio Team - POST /api/studio/leave
# ============================================================
class TestStudioTeamLeave:
    """Test POST /api/studio/leave"""

    def test_leave_team_returns_404_for_non_member(self, api_client, auth_headers):
        """Non-team member should get 404 when trying to leave"""
        response = api_client.post(f"{BASE_URL}/api/studio/leave", headers=auth_headers)
        assert response.status_code == 404, f"Expected 404 for non-member, got {response.status_code}: {response.text}"

    def test_leave_team_without_auth_returns_401(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/studio/leave")
        assert response.status_code == 401


# ============================================================
# 12. Full Studio Team Flow (Integration Test)
# ============================================================
class TestStudioTeamFullFlow:
    """Integration test for complete studio team workflow"""

    def test_studio_team_full_flow_with_the_shop_subscription(self, api_client):
        """
        Full flow test:
        1. Create user with 'the-shop' subscription via webhook
        2. Create studio team
        3. Verify team info
        4. Invite member
        5. Accept invite (as another user)
        6. Verify shared credits work
        7. Remove member
        8. Cleanup
        """
        # Create admin user
        admin_apple_id = f"studio_admin_{uuid.uuid4().hex[:8]}"
        admin_resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": admin_apple_id,
            "email": f"{admin_apple_id}@studio.test",
            "full_name": "Studio Admin",
            "device_id": f"device_{admin_apple_id}"
        })
        assert admin_resp.status_code == 200
        admin_token = admin_resp.json()['session_token']
        # IMPORTANT: Use the generated user_id from response, not the apple_user_id
        admin_id = admin_resp.json()['user']['user_id']
        admin_headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        
        # Give admin 'the-shop' subscription via webhook using the actual user_id
        webhook_resp = api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": admin_id,  # Use actual user_id, not apple_user_id
                "product_id": "bodybound_9999_1m_3d"  # the-shop = 1500 credits
            }
        })
        assert webhook_resp.status_code == 200
        
        # Verify admin has the-shop tier
        admin_me = api_client.get(f"{BASE_URL}/api/auth/me", headers=admin_headers)
        assert admin_me.status_code == 200
        admin_credits = admin_me.json()['credits']
        assert admin_credits['tier'] == 'the-shop', f"Expected tier=the-shop, got {admin_credits['tier']}"
        assert admin_credits['available_credits'] == 1500
        
        # Step 2: Create studio team
        create_resp = api_client.post(f"{BASE_URL}/api/studio/create", headers=admin_headers)
        assert create_resp.status_code == 200, f"Failed to create studio team: {create_resp.text}"
        team_data = create_resp.json()
        assert "team_id" in team_data
        team_id = team_data['team_id']
        assert team_data['shared_credits'] == 1500
        
        # Step 3: Verify team info
        team_resp = api_client.get(f"{BASE_URL}/api/studio/team", headers=admin_headers)
        assert team_resp.status_code == 200
        team_info = team_resp.json()
        assert team_info['team_id'] == team_id
        assert team_info['admin_user_id'] == admin_id  # Verify admin is the creator
        assert team_info['shared_credits'] == 1500
        
        # Verify admin's /me now shows studio team
        admin_me2 = api_client.get(f"{BASE_URL}/api/auth/me", headers=admin_headers)
        admin_credits2 = admin_me2.json()['credits']
        assert admin_credits2['is_studio_team'] is True
        assert admin_credits2['studio_team_id'] == team_id
        
        # Step 4: Invite a member
        member_email = f"member_{uuid.uuid4().hex[:8]}@studio.test"
        invite_resp = api_client.post(
            f"{BASE_URL}/api/studio/invite",
            headers=admin_headers,
            json={"email": member_email}
        )
        assert invite_resp.status_code == 200, f"Failed to invite: {invite_resp.text}"
        invite_data = invite_resp.json()
        assert "invite_code" in invite_data
        invite_code = invite_data['invite_code']
        
        # Step 5: Create member user and accept invite
        member_apple_id = f"studio_member_{uuid.uuid4().hex[:8]}"
        member_resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": member_apple_id,
            "email": member_email,
            "full_name": "Studio Member",
            "device_id": f"device_{member_apple_id}"
        })
        assert member_resp.status_code == 200
        member_token = member_resp.json()['session_token']
        member_id = member_resp.json()['user']['user_id']  # Use actual user_id
        member_headers = {"Authorization": f"Bearer {member_token}", "Content-Type": "application/json"}
        
        # Accept invite
        accept_resp = api_client.post(
            f"{BASE_URL}/api/studio/accept-invite",
            headers=member_headers,
            json={"invite_code": invite_code}
        )
        assert accept_resp.status_code == 200, f"Failed to accept invite: {accept_resp.text}"
        
        # Step 6: Verify member can see team and shared credits
        member_team = api_client.get(f"{BASE_URL}/api/studio/team", headers=member_headers)
        assert member_team.status_code == 200
        member_team_info = member_team.json()
        assert member_team_info['team_id'] == team_id
        assert member_team_info['admin_user_id'] == admin_id  # Admin is still the creator
        
        # Verify member's /me shows studio team
        member_me = api_client.get(f"{BASE_URL}/api/auth/me", headers=member_headers)
        member_credits = member_me.json()['credits']
        assert member_credits['is_studio_team'] is True
        assert member_credits['studio_team_id'] == team_id
        assert member_credits['available_credits'] == 1500  # Shared pool
        
        # Step 6b: Test credit deduction from shared pool
        deduct_resp = api_client.post(f"{BASE_URL}/api/credits/deduct", headers=member_headers)
        assert deduct_resp.status_code == 200
        deduct_data = deduct_resp.json()
        assert deduct_data['available_credits'] == 1499  # Shared pool decremented
        assert deduct_data.get('is_studio_team') is True
        
        # Verify admin also sees decremented shared pool
        admin_team2 = api_client.get(f"{BASE_URL}/api/studio/team", headers=admin_headers)
        assert admin_team2.json()['shared_credits'] == 1499
        
        # Step 7: Remove member (as admin)
        remove_resp = api_client.delete(
            f"{BASE_URL}/api/studio/member/{member_id}",
            headers=admin_headers
        )
        assert remove_resp.status_code == 200, f"Failed to remove member: {remove_resp.text}"
        
        # Verify member is no longer in team
        member_team2 = api_client.get(f"{BASE_URL}/api/studio/team", headers=member_headers)
        assert member_team2.status_code == 404  # No longer in team
        
        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=admin_headers)
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=member_headers)


# ============================================================
# 13. Studio Team - Admin Cannot Leave
# ============================================================
class TestStudioTeamAdminCannotLeave:
    """Test that admin cannot leave their own team"""

    def test_admin_cannot_leave_own_team(self, api_client):
        """Admin should get 400 when trying to leave their own team"""
        # Create admin with the-shop subscription
        admin_apple_id = f"admin_leave_{uuid.uuid4().hex[:8]}"
        admin_resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": admin_apple_id,
            "email": f"{admin_apple_id}@leave.test",
            "full_name": "Admin Leave Test",
            "device_id": f"device_{admin_apple_id}"
        })
        assert admin_resp.status_code == 200
        admin_token = admin_resp.json()['session_token']
        admin_id = admin_resp.json()['user']['user_id']  # Use actual user_id
        admin_headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        
        # Give the-shop subscription using actual user_id
        api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": admin_id,  # Use actual user_id
                "product_id": "bodybound_9999_1m_3d"
            }
        })
        
        # Create team
        create_resp = api_client.post(f"{BASE_URL}/api/studio/create", headers=admin_headers)
        assert create_resp.status_code == 200
        
        # Try to leave - should fail
        leave_resp = api_client.post(f"{BASE_URL}/api/studio/leave", headers=admin_headers)
        assert leave_resp.status_code == 400, f"Expected 400 for admin leaving, got {leave_resp.status_code}: {leave_resp.text}"
        assert "admin" in leave_resp.json()['detail'].lower()
        
        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=admin_headers)


# ============================================================
# 14. Studio Team - Admin Cannot Remove Self
# ============================================================
class TestStudioTeamAdminCannotRemoveSelf:
    """Test that admin cannot remove themselves"""

    def test_admin_cannot_remove_self(self, api_client):
        """Admin should get 400 when trying to remove themselves"""
        admin_apple_id = f"admin_self_{uuid.uuid4().hex[:8]}"
        admin_resp = api_client.post(f"{BASE_URL}/api/auth/apple", json={
            "identity_token": "mock",
            "user_id": admin_apple_id,
            "email": f"{admin_apple_id}@self.test",
            "full_name": "Admin Self Test",
            "device_id": f"device_{admin_apple_id}"
        })
        assert admin_resp.status_code == 200
        admin_token = admin_resp.json()['session_token']
        admin_id = admin_resp.json()['user']['user_id']  # Use actual user_id
        admin_headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
        
        # Give the-shop subscription using actual user_id
        api_client.post(f"{BASE_URL}/api/webhooks/revenuecat", json={
            "event": {
                "type": "INITIAL_PURCHASE",
                "app_user_id": admin_id,  # Use actual user_id
                "product_id": "bodybound_9999_1m_3d"
            }
        })
        
        # Create team
        create_resp = api_client.post(f"{BASE_URL}/api/studio/create", headers=admin_headers)
        assert create_resp.status_code == 200
        
        # Try to remove self - should fail
        remove_resp = api_client.delete(
            f"{BASE_URL}/api/studio/member/{admin_id}",
            headers=admin_headers
        )
        assert remove_resp.status_code == 400, f"Expected 400, got {remove_resp.status_code}: {remove_resp.text}"
        assert "admin" in remove_resp.json()['detail'].lower()
        
        # Cleanup
        api_client.delete(f"{BASE_URL}/api/account/delete", headers=admin_headers)
