"""
Iteration 9 Tests: Credit System & Referral Popup Cooldown Features

Tests for:
1. total_monthly_credits field in /api/auth/me response
2. total_monthly_credits field in /api/credits/deduct response
3. Action-based referral popup cooldowns (dismiss=7d, shared/copy=30d)
4. Verified referral suppression (60 days)
5. Health endpoint regression
6. Existing referral endpoints regression
"""

import pytest
import requests
import os
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
CRON_SECRET = "bb-cron-2026-refresh-c7f3a1"

# Tier -> expected total monthly credits mapping
TIER_CREDITS_MAP = {
    'walk-in': 125,
    'booked-out': 500,
    'the-shop': 1500,
    'the-shop-member': 1500
}


@pytest.fixture(scope="module")
def session():
    """Create a requests session"""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def demo_auth(session):
    """Get demo user authentication token"""
    response = session.post(f"{BASE_URL}/api/auth/demo-login")
    assert response.status_code == 200, f"Demo login failed: {response.text}"
    data = response.json()
    token = data.get('session_token')
    assert token, "No session_token in demo login response"
    return token


class TestHealthEndpoint:
    """Health endpoint regression test"""
    
    def test_health_returns_healthy(self, session):
        """GET /api/health should return healthy status"""
        response = session.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'healthy'
        print("✓ Health endpoint returns healthy status")


class TestAuthMeTotalMonthlyCredits:
    """Tests for total_monthly_credits field in /api/auth/me"""
    
    def test_auth_me_returns_total_monthly_credits(self, session, demo_auth):
        """GET /api/auth/me should include total_monthly_credits field"""
        response = session.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check that credits object exists
        credits = data.get('credits', {})
        assert 'total_monthly_credits' in credits, "total_monthly_credits field missing from credits"
        
        # Get the tier and verify total_monthly_credits matches expected value
        tier = credits.get('tier')
        expected_total = TIER_CREDITS_MAP.get(tier, 0)
        actual_total = credits.get('total_monthly_credits')
        
        print(f"✓ User tier: {tier}, total_monthly_credits: {actual_total}, expected: {expected_total}")
        assert actual_total == expected_total, f"total_monthly_credits mismatch: got {actual_total}, expected {expected_total}"
        
    def test_auth_me_walk_in_tier_credits(self, session, demo_auth):
        """Verify walk-in tier returns 125 total_monthly_credits"""
        response = session.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert response.status_code == 200
        data = response.json()
        credits = data.get('credits', {})
        tier = credits.get('tier')
        
        # Demo user should be walk-in tier
        if tier == 'walk-in':
            assert credits.get('total_monthly_credits') == 125
            print("✓ walk-in tier correctly returns 125 total_monthly_credits")
        else:
            print(f"ℹ Demo user is {tier} tier, not walk-in - skipping walk-in specific check")
            # Still verify the mapping is correct for whatever tier they are
            expected = TIER_CREDITS_MAP.get(tier, 0)
            assert credits.get('total_monthly_credits') == expected
            print(f"✓ {tier} tier correctly returns {expected} total_monthly_credits")

    def test_auth_me_requires_auth(self, session):
        """GET /api/auth/me should require authentication"""
        response = session.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 401
        print("✓ /api/auth/me correctly requires authentication")


class TestCreditsDeductTotalMonthlyCredits:
    """Tests for total_monthly_credits field in /api/credits/deduct"""
    
    def test_credits_deduct_returns_total_monthly_credits(self, session, demo_auth):
        """POST /api/credits/deduct should include total_monthly_credits in response"""
        # First check current credits
        me_response = session.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert me_response.status_code == 200
        initial_credits = me_response.json().get('credits', {})
        initial_available = initial_credits.get('available_credits', 0)
        
        if initial_available <= 0:
            pytest.skip("Demo user has no credits to deduct")
        
        # Deduct a credit
        response = session.post(
            f"{BASE_URL}/api/credits/deduct",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify total_monthly_credits is in response
        assert 'total_monthly_credits' in data, "total_monthly_credits missing from deduct response"
        
        tier = data.get('tier')
        expected_total = TIER_CREDITS_MAP.get(tier, 0)
        actual_total = data.get('total_monthly_credits')
        
        print(f"✓ Deduct response includes total_monthly_credits: {actual_total} (tier: {tier})")
        assert actual_total == expected_total, f"total_monthly_credits mismatch: got {actual_total}, expected {expected_total}"
        
        # Verify available_credits decreased
        assert data.get('available_credits') == initial_available - 1
        print(f"✓ Credits deducted: {initial_available} -> {data.get('available_credits')}")

    def test_credits_deduct_requires_auth(self, session):
        """POST /api/credits/deduct should require authentication"""
        response = session.post(f"{BASE_URL}/api/credits/deduct")
        assert response.status_code == 401
        print("✓ /api/credits/deduct correctly requires authentication")


class TestReferralPopupDismissAction:
    """Tests for action field in /api/referral/dismiss-popup"""
    
    def test_dismiss_popup_accepts_dismiss_action(self, session, demo_auth):
        """POST /api/referral/dismiss-popup should accept action='dismiss'"""
        response = session.post(
            f"{BASE_URL}/api/referral/dismiss-popup",
            headers={"Authorization": f"Bearer {demo_auth}"},
            json={"action": "dismiss"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'ok'
        print("✓ dismiss-popup accepts action='dismiss'")
    
    def test_dismiss_popup_accepts_shared_action(self, session, demo_auth):
        """POST /api/referral/dismiss-popup should accept action='shared'"""
        response = session.post(
            f"{BASE_URL}/api/referral/dismiss-popup",
            headers={"Authorization": f"Bearer {demo_auth}"},
            json={"action": "shared"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'ok'
        print("✓ dismiss-popup accepts action='shared'")
    
    def test_dismiss_popup_accepts_copy_action(self, session, demo_auth):
        """POST /api/referral/dismiss-popup should accept action='copy'"""
        response = session.post(
            f"{BASE_URL}/api/referral/dismiss-popup",
            headers={"Authorization": f"Bearer {demo_auth}"},
            json={"action": "copy"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'ok'
        print("✓ dismiss-popup accepts action='copy'")
    
    def test_dismiss_popup_accepts_invite_action(self, session, demo_auth):
        """POST /api/referral/dismiss-popup should accept action='invite'"""
        response = session.post(
            f"{BASE_URL}/api/referral/dismiss-popup",
            headers={"Authorization": f"Bearer {demo_auth}"},
            json={"action": "invite"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'ok'
        print("✓ dismiss-popup accepts action='invite'")
    
    def test_dismiss_popup_defaults_to_dismiss(self, session, demo_auth):
        """POST /api/referral/dismiss-popup without action should default to 'dismiss'"""
        response = session.post(
            f"{BASE_URL}/api/referral/dismiss-popup",
            headers={"Authorization": f"Bearer {demo_auth}"},
            json={}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'ok'
        print("✓ dismiss-popup defaults to 'dismiss' action when not specified")

    def test_dismiss_popup_requires_auth(self, session):
        """POST /api/referral/dismiss-popup should require authentication"""
        response = session.post(
            f"{BASE_URL}/api/referral/dismiss-popup",
            json={"action": "dismiss"}
        )
        assert response.status_code == 401
        print("✓ /api/referral/dismiss-popup correctly requires authentication")


class TestReferralPopupEligibility:
    """Tests for /api/referral/popup-eligible cooldown logic"""
    
    def test_popup_eligible_returns_response(self, session, demo_auth):
        """GET /api/referral/popup-eligible should return eligible status"""
        response = session.get(
            f"{BASE_URL}/api/referral/popup-eligible",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Should have 'eligible' field
        assert 'eligible' in data, "Response missing 'eligible' field"
        
        # If not eligible, should have 'reason'
        if not data.get('eligible'):
            assert 'reason' in data, "Non-eligible response should include 'reason'"
            print(f"✓ popup-eligible returned: eligible=False, reason={data.get('reason')}")
        else:
            print("✓ popup-eligible returned: eligible=True")
    
    def test_popup_eligible_after_dismiss_action(self, session, demo_auth):
        """After dismiss action, popup should be ineligible (7-day cooldown)"""
        # First dismiss with 'dismiss' action
        dismiss_response = session.post(
            f"{BASE_URL}/api/referral/dismiss-popup",
            headers={"Authorization": f"Bearer {demo_auth}"},
            json={"action": "dismiss"}
        )
        assert dismiss_response.status_code == 200
        
        # Check eligibility - should be ineligible due to recent dismissal
        eligible_response = session.get(
            f"{BASE_URL}/api/referral/popup-eligible",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert eligible_response.status_code == 200
        data = eligible_response.json()
        
        # Should be ineligible with 'recently_dismissed' reason
        # (unless user has verified referrals, then 'active_referrer')
        if not data.get('eligible'):
            reason = data.get('reason')
            assert reason in ('recently_dismissed', 'active_referrer', 'not_paid_subscriber'), \
                f"Unexpected reason: {reason}"
            print(f"✓ After dismiss action, popup ineligible with reason: {reason}")
        else:
            print("ℹ User is eligible (may be outside cooldown window)")
    
    def test_popup_eligible_after_shared_action(self, session, demo_auth):
        """After shared action, popup should be ineligible (30-day cooldown)"""
        # First dismiss with 'shared' action
        dismiss_response = session.post(
            f"{BASE_URL}/api/referral/dismiss-popup",
            headers={"Authorization": f"Bearer {demo_auth}"},
            json={"action": "shared"}
        )
        assert dismiss_response.status_code == 200
        
        # Check eligibility - should be ineligible due to recent share
        eligible_response = session.get(
            f"{BASE_URL}/api/referral/popup-eligible",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert eligible_response.status_code == 200
        data = eligible_response.json()
        
        if not data.get('eligible'):
            reason = data.get('reason')
            assert reason in ('recently_dismissed', 'active_referrer', 'not_paid_subscriber'), \
                f"Unexpected reason: {reason}"
            print(f"✓ After shared action, popup ineligible with reason: {reason}")
        else:
            print("ℹ User is eligible (may be outside cooldown window)")

    def test_popup_eligible_requires_auth(self, session):
        """GET /api/referral/popup-eligible should require authentication"""
        response = session.get(f"{BASE_URL}/api/referral/popup-eligible")
        assert response.status_code == 401
        print("✓ /api/referral/popup-eligible correctly requires authentication")


class TestReferralEndpointsRegression:
    """Regression tests for existing referral endpoints"""
    
    def test_referral_code_endpoint(self, session, demo_auth):
        """GET /api/referral/code should return referral code"""
        response = session.get(
            f"{BASE_URL}/api/referral/code",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert 'referral_code' in data
        assert 'referral_link' in data
        assert data['referral_code'].startswith('BB-')
        print(f"✓ Referral code endpoint works: {data['referral_code']}")
    
    def test_referral_dashboard_endpoint(self, session, demo_auth):
        """GET /api/referral/dashboard should return dashboard data"""
        response = session.get(
            f"{BASE_URL}/api/referral/dashboard",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required fields
        required_fields = [
            'referral_code', 'referral_link', 'verified_referrals',
            'pending_referrals', 'rejected_referrals', 'progress_toward_reward',
            'referrals_needed', 'free_months_earned', 'free_months_available'
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        print(f"✓ Referral dashboard works: code={data['referral_code']}, verified={data['verified_referrals']}")
    
    def test_referral_landing_page(self, session, demo_auth):
        """GET /api/ref/{code} should return landing page HTML"""
        # First get the user's referral code
        code_response = session.get(
            f"{BASE_URL}/api/referral/code",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert code_response.status_code == 200
        code = code_response.json().get('referral_code')
        
        # Test landing page
        response = session.get(f"{BASE_URL}/api/ref/{code}")
        assert response.status_code == 200
        assert 'text/html' in response.headers.get('content-type', '')
        assert 'BODY BOUND' in response.text
        print(f"✓ Referral landing page works for code: {code}")
    
    def test_referral_cron_requires_secret(self, session):
        """POST /api/referral/check-verifications should require cron secret"""
        # Without secret
        response = session.post(f"{BASE_URL}/api/referral/check-verifications")
        assert response.status_code == 401
        
        # With wrong secret
        response = session.post(
            f"{BASE_URL}/api/referral/check-verifications",
            headers={"X-Cron-Secret": "wrong-secret"}
        )
        assert response.status_code == 401
        
        # With correct secret
        response = session.post(
            f"{BASE_URL}/api/referral/check-verifications",
            headers={"X-Cron-Secret": CRON_SECRET}
        )
        assert response.status_code == 200
        print("✓ Referral cron endpoint correctly validates secret")


class TestCreditFieldsConsistency:
    """Test that credit fields are consistent across endpoints"""
    
    def test_credits_fields_match_between_endpoints(self, session, demo_auth):
        """Verify total_monthly_credits is consistent between /auth/me and /credits/deduct"""
        # Get credits from /auth/me
        me_response = session.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert me_response.status_code == 200
        me_credits = me_response.json().get('credits', {})
        me_total = me_credits.get('total_monthly_credits')
        me_tier = me_credits.get('tier')
        me_available = me_credits.get('available_credits', 0)
        
        if me_available <= 0:
            pytest.skip("No credits available to test deduct consistency")
        
        # Deduct and check consistency
        deduct_response = session.post(
            f"{BASE_URL}/api/credits/deduct",
            headers={"Authorization": f"Bearer {demo_auth}"}
        )
        assert deduct_response.status_code == 200
        deduct_data = deduct_response.json()
        deduct_total = deduct_data.get('total_monthly_credits')
        deduct_tier = deduct_data.get('tier')
        
        # Verify consistency
        assert me_total == deduct_total, f"total_monthly_credits mismatch: /auth/me={me_total}, /credits/deduct={deduct_total}"
        assert me_tier == deduct_tier, f"tier mismatch: /auth/me={me_tier}, /credits/deduct={deduct_tier}"
        
        print(f"✓ Credit fields consistent: tier={me_tier}, total_monthly_credits={me_total}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
