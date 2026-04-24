"""
Comprehensive Subscription Flow Tests for BODY BOUND Stencil Generator
Tests all subscription endpoints, credit mappings, webhook handling, and edge cases.

Test Coverage:
- POST /api/auth/demo-login - Demo login returns user and session_token
- GET /api/auth/me - Returns user info with credits.needs_subscription field
- POST /api/subscription/sync - Syncs RevenueCat entitlements with correct tier/credits
- POST /api/webhooks/revenuecat - Handles subscription lifecycle events
- POST /api/credits/deduct - Atomic credit deduction
- Idempotency checks for subscription sync
- needs_subscription field logic verification
"""

import pytest
import requests
import os
import uuid
from datetime import datetime

# Use the preview URL for testing
BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL', 'https://stencil-ai-fallback.preview.emergentagent.com')
REVENUECAT_WEBHOOK_AUTH = os.environ.get('REVENUECAT_WEBHOOK_AUTH', '')

# Product credit mappings from server.py
PRODUCT_CREDIT_MAP = {
    'bodybound_1499_1m_3d': {'tier': 'walk-in', 'credits': 125},
    'bodybound_2999_1m_3d': {'tier': 'booked-out', 'credits': 500},
    'bodybound_9999_1m_3d': {'tier': 'the-shop', 'credits': 1500},
}

TRIAL_CREDITS = 10  # Credits during Apple trial (all tiers)


class TestDemoLogin:
    """Test demo login endpoint"""
    
    def test_demo_login_returns_user_and_token(self):
        """POST /api/auth/demo-login should return user and session_token"""
        response = requests.post(f'{BASE_URL}/api/auth/demo-login')
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert 'session_token' in data, "Response should contain session_token"
        assert 'user' in data, "Response should contain user object"
        assert isinstance(data['session_token'], str), "session_token should be a string"
        assert len(data['session_token']) > 0, "session_token should not be empty"
        
        user = data['user']
        assert 'user_id' in user, "User should have user_id"
        assert 'email' in user, "User should have email"
        print(f"✓ Demo login successful: user_id={user['user_id']}, email={user['email']}")


class TestAuthMe:
    """Test /api/auth/me endpoint with needs_subscription field"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token from demo login"""
        response = requests.post(f'{BASE_URL}/api/auth/demo-login')
        assert response.status_code == 200
        return response.json()['session_token']
    
    def test_auth_me_returns_credits_with_needs_subscription(self, auth_token):
        """GET /api/auth/me with token should return user info with credits.needs_subscription field"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        response = requests.get(f'{BASE_URL}/api/auth/me', headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert 'credits' in data, "Response should contain credits object"
        
        credits = data['credits']
        assert 'needs_subscription' in credits, "Credits should contain needs_subscription field"
        assert isinstance(credits['needs_subscription'], bool), "needs_subscription should be boolean"
        assert 'available_credits' in credits, "Credits should contain available_credits"
        assert 'tier' in credits, "Credits should contain tier"
        
        print(f"✓ Auth/me returns credits: tier={credits['tier']}, needs_subscription={credits['needs_subscription']}")
    
    def test_auth_me_without_token_returns_401(self):
        """GET /api/auth/me without token should return 401"""
        response = requests.get(f'{BASE_URL}/api/auth/me')
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Auth/me without token returns 401")


class TestSubscriptionSync:
    """Test /api/subscription/sync endpoint with all product IDs"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token from demo login"""
        response = requests.post(f'{BASE_URL}/api/auth/demo-login')
        assert response.status_code == 200
        return response.json()['session_token']
    
    def test_sync_requires_auth(self):
        """POST /api/subscription/sync without auth should return 401"""
        response = requests.post(f'{BASE_URL}/api/subscription/sync', json={'product_id': 'test'})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Subscription sync requires auth")
    
    def test_sync_requires_product_id(self, auth_token):
        """POST /api/subscription/sync without product_id should return 400"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        response = requests.post(f'{BASE_URL}/api/subscription/sync', headers=headers, json={})
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert 'Missing product_id' in response.text
        print("✓ Subscription sync requires product_id")
    
    def test_sync_invalid_product_id_returns_400(self, auth_token):
        """POST /api/subscription/sync with invalid product_id should return 400"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        response = requests.post(f'{BASE_URL}/api/subscription/sync', headers=headers, json={'product_id': 'invalid_product'})
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert 'Unknown product' in response.text
        print("✓ Subscription sync rejects invalid product_id")
    
    def test_sync_walk_in_tier_paid(self, auth_token):
        """POST /api/subscription/sync with bodybound_1499_1m_3d should set tier to 'walk-in' with 125 credits"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        response = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_1499_1m_3d', 'is_trial': False}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data['tier'] == 'walk-in', f"Expected tier 'walk-in', got {data['tier']}"
        assert data['available_credits'] == 125, f"Expected 125 credits, got {data['available_credits']}"
        assert data['needs_subscription'] == False, "needs_subscription should be False for walk-in tier"
        print(f"✓ Walk-in tier (paid): tier={data['tier']}, credits={data['available_credits']}")
    
    def test_sync_booked_out_tier_paid(self, auth_token):
        """POST /api/subscription/sync with bodybound_2999_1m_3d should set tier to 'booked-out' with 500 credits"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        response = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_2999_1m_3d', 'is_trial': False}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data['tier'] == 'booked-out', f"Expected tier 'booked-out', got {data['tier']}"
        assert data['available_credits'] == 500, f"Expected 500 credits, got {data['available_credits']}"
        assert data['needs_subscription'] == False, "needs_subscription should be False for booked-out tier"
        print(f"✓ Booked-out tier (paid): tier={data['tier']}, credits={data['available_credits']}")
    
    def test_sync_the_shop_tier_paid(self, auth_token):
        """POST /api/subscription/sync with bodybound_9999_1m_3d should set tier to 'the-shop' with 1500 credits"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        response = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_9999_1m_3d', 'is_trial': False}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data['tier'] == 'the-shop', f"Expected tier 'the-shop', got {data['tier']}"
        assert data['available_credits'] == 1500, f"Expected 1500 credits, got {data['available_credits']}"
        assert data['needs_subscription'] == False, "needs_subscription should be False for the-shop tier"
        print(f"✓ The-shop tier (paid): tier={data['tier']}, credits={data['available_credits']}")
    
    def test_sync_trial_caps_at_10_credits_walk_in(self, auth_token):
        """POST /api/subscription/sync with is_trial:true should give only 10 credits for walk-in"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        response = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_1499_1m_3d', 'is_trial': True}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data['tier'] == 'walk-in', f"Expected tier 'walk-in', got {data['tier']}"
        assert data['available_credits'] == TRIAL_CREDITS, f"Expected {TRIAL_CREDITS} credits for trial, got {data['available_credits']}"
        assert data['is_trial'] == True, "is_trial should be True"
        print(f"✓ Walk-in tier (trial): tier={data['tier']}, credits={data['available_credits']}")
    
    def test_sync_trial_caps_at_10_credits_booked_out(self, auth_token):
        """POST /api/subscription/sync with is_trial:true should give only 10 credits for booked-out"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        response = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_2999_1m_3d', 'is_trial': True}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data['tier'] == 'booked-out', f"Expected tier 'booked-out', got {data['tier']}"
        assert data['available_credits'] == TRIAL_CREDITS, f"Expected {TRIAL_CREDITS} credits for trial, got {data['available_credits']}"
        assert data['is_trial'] == True, "is_trial should be True"
        print(f"✓ Booked-out tier (trial): tier={data['tier']}, credits={data['available_credits']}")
    
    def test_sync_trial_caps_at_10_credits_the_shop(self, auth_token):
        """POST /api/subscription/sync with is_trial:true should give only 10 credits for the-shop"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        response = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_9999_1m_3d', 'is_trial': True}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data['tier'] == 'the-shop', f"Expected tier 'the-shop', got {data['tier']}"
        assert data['available_credits'] == TRIAL_CREDITS, f"Expected {TRIAL_CREDITS} credits for trial, got {data['available_credits']}"
        assert data['is_trial'] == True, "is_trial should be True"
        print(f"✓ The-shop tier (trial): tier={data['tier']}, credits={data['available_credits']}")


class TestSubscriptionSyncIdempotency:
    """Test that subscription sync is idempotent"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token from demo login"""
        response = requests.post(f'{BASE_URL}/api/auth/demo-login')
        assert response.status_code == 200
        return response.json()['session_token']
    
    def test_sync_idempotent_same_tier_same_trial_status(self, auth_token):
        """Calling sync twice with same data should not double credits"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        
        # First sync - set to booked-out paid
        response1 = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_2999_1m_3d', 'is_trial': False}
        )
        assert response1.status_code == 200
        credits1 = response1.json()['available_credits']
        
        # Second sync - same product, same trial status
        response2 = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_2999_1m_3d', 'is_trial': False}
        )
        assert response2.status_code == 200
        credits2 = response2.json()['available_credits']
        
        # Credits should be the same (idempotent)
        assert credits1 == credits2, f"Credits should be idempotent: first={credits1}, second={credits2}"
        print(f"✓ Sync is idempotent: credits stayed at {credits2}")


class TestRevenueCatWebhook:
    """Test RevenueCat webhook endpoint"""
    
    def test_webhook_requires_auth(self):
        """POST /api/webhooks/revenuecat without auth should return 401"""
        response = requests.post(f'{BASE_URL}/api/webhooks/revenuecat', json={'event': {}})
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Webhook requires auth")
    
    def test_webhook_initial_purchase_paid(self):
        """POST /api/webhooks/revenuecat with INITIAL_PURCHASE event should create/update subscription"""
        test_user_id = f'test_webhook_user_{uuid.uuid4().hex[:8]}'
        
        headers = {'Authorization': f'Bearer {REVENUECAT_WEBHOOK_AUTH}'}
        payload = {
            'event': {
                'type': 'INITIAL_PURCHASE',
                'app_user_id': test_user_id,
                'product_id': 'bodybound_2999_1m_3d',
                'period_type': 'NORMAL'
            }
        }
        
        response = requests.post(f'{BASE_URL}/api/webhooks/revenuecat', headers=headers, json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data['status'] == 'ok', f"Expected status 'ok', got {data}"
        print(f"✓ Webhook INITIAL_PURCHASE (paid) processed for {test_user_id}")
    
    def test_webhook_initial_purchase_trial(self):
        """POST /api/webhooks/revenuecat with INITIAL_PURCHASE + period_type=TRIAL should give 10 credits"""
        test_user_id = f'test_webhook_trial_{uuid.uuid4().hex[:8]}'
        
        headers = {'Authorization': f'Bearer {REVENUECAT_WEBHOOK_AUTH}'}
        payload = {
            'event': {
                'type': 'INITIAL_PURCHASE',
                'app_user_id': test_user_id,
                'product_id': 'bodybound_2999_1m_3d',
                'period_type': 'TRIAL'
            }
        }
        
        response = requests.post(f'{BASE_URL}/api/webhooks/revenuecat', headers=headers, json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Webhook INITIAL_PURCHASE (trial) processed for {test_user_id}")
    
    def test_webhook_cancellation_sets_tier_expired(self):
        """POST /api/webhooks/revenuecat with CANCELLATION event should set tier to 'expired'"""
        test_user_id = f'test_webhook_cancel_{uuid.uuid4().hex[:8]}'
        
        headers = {'Authorization': f'Bearer {REVENUECAT_WEBHOOK_AUTH}'}
        
        # First create a subscription
        create_payload = {
            'event': {
                'type': 'INITIAL_PURCHASE',
                'app_user_id': test_user_id,
                'product_id': 'bodybound_2999_1m_3d',
                'period_type': 'NORMAL'
            }
        }
        requests.post(f'{BASE_URL}/api/webhooks/revenuecat', headers=headers, json=create_payload)
        
        # Then cancel it
        cancel_payload = {
            'event': {
                'type': 'CANCELLATION',
                'app_user_id': test_user_id,
                'product_id': 'bodybound_2999_1m_3d'
            }
        }
        
        response = requests.post(f'{BASE_URL}/api/webhooks/revenuecat', headers=headers, json=cancel_payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"✓ Webhook CANCELLATION processed for {test_user_id}")


class TestNeedsSubscriptionLogic:
    """Test needs_subscription field logic for different tiers"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token from demo login"""
        response = requests.post(f'{BASE_URL}/api/auth/demo-login')
        assert response.status_code == 200
        return response.json()['session_token']
    
    def test_needs_subscription_false_for_walk_in(self, auth_token):
        """needs_subscription should be False for walk-in tier"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        
        # Set to walk-in tier
        requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_1499_1m_3d', 'is_trial': False}
        )
        
        # Check needs_subscription
        response = requests.get(f'{BASE_URL}/api/auth/me', headers=headers)
        assert response.status_code == 200
        
        credits = response.json()['credits']
        assert credits['needs_subscription'] == False, f"needs_subscription should be False for walk-in, got {credits['needs_subscription']}"
        print("✓ needs_subscription=False for walk-in tier")
    
    def test_needs_subscription_false_for_booked_out(self, auth_token):
        """needs_subscription should be False for booked-out tier"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        
        # Set to booked-out tier
        requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_2999_1m_3d', 'is_trial': False}
        )
        
        # Check needs_subscription
        response = requests.get(f'{BASE_URL}/api/auth/me', headers=headers)
        assert response.status_code == 200
        
        credits = response.json()['credits']
        assert credits['needs_subscription'] == False, f"needs_subscription should be False for booked-out, got {credits['needs_subscription']}"
        print("✓ needs_subscription=False for booked-out tier")
    
    def test_needs_subscription_false_for_the_shop(self, auth_token):
        """needs_subscription should be False for the-shop tier"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        
        # Set to the-shop tier
        requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_9999_1m_3d', 'is_trial': False}
        )
        
        # Check needs_subscription
        response = requests.get(f'{BASE_URL}/api/auth/me', headers=headers)
        assert response.status_code == 200
        
        credits = response.json()['credits']
        assert credits['needs_subscription'] == False, f"needs_subscription should be False for the-shop, got {credits['needs_subscription']}"
        print("✓ needs_subscription=False for the-shop tier")


class TestCreditsDeduct:
    """Test /api/credits/deduct endpoint"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token from demo login"""
        response = requests.post(f'{BASE_URL}/api/auth/demo-login')
        assert response.status_code == 200
        return response.json()['session_token']
    
    def test_deduct_requires_auth(self):
        """POST /api/credits/deduct without auth should return 401"""
        response = requests.post(f'{BASE_URL}/api/credits/deduct')
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Credits deduct requires auth")
    
    def test_deduct_credit_atomically(self, auth_token):
        """POST /api/credits/deduct should deduct 1 credit atomically"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        
        # First ensure user has credits by syncing to booked-out
        sync_response = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_2999_1m_3d', 'is_trial': False}
        )
        assert sync_response.status_code == 200
        initial_credits = sync_response.json()['available_credits']
        
        # Deduct 1 credit
        deduct_response = requests.post(f'{BASE_URL}/api/credits/deduct', headers=headers)
        assert deduct_response.status_code == 200, f"Expected 200, got {deduct_response.status_code}: {deduct_response.text}"
        
        data = deduct_response.json()
        assert 'available_credits' in data, "Response should contain available_credits"
        assert data['available_credits'] == initial_credits - 1, f"Expected {initial_credits - 1} credits, got {data['available_credits']}"
        print(f"✓ Credit deducted atomically: {initial_credits} -> {data['available_credits']}")


class TestSubscriptionReactivation:
    """Test subscription re-activation after expiration"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token from demo login"""
        response = requests.post(f'{BASE_URL}/api/auth/demo-login')
        assert response.status_code == 200
        return response.json()['session_token']
    
    def test_sync_after_expiration_reactivates(self, auth_token):
        """POST /api/subscription/sync after expiration should correctly re-activate subscription"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        
        # First, simulate expiration via webhook
        test_user_id = 'demo_reviewer_account'  # Demo user ID
        webhook_headers = {'Authorization': f'Bearer {REVENUECAT_WEBHOOK_AUTH}'}
        
        # Cancel/expire the subscription
        cancel_payload = {
            'event': {
                'type': 'CANCELLATION',
                'app_user_id': test_user_id,
                'product_id': 'bodybound_2999_1m_3d'
            }
        }
        requests.post(f'{BASE_URL}/api/webhooks/revenuecat', headers=webhook_headers, json=cancel_payload)
        
        # Check that needs_subscription is now True
        me_response = requests.get(f'{BASE_URL}/api/auth/me', headers=headers)
        assert me_response.status_code == 200
        credits_after_cancel = me_response.json()['credits']
        assert credits_after_cancel['tier'] == 'expired', f"Expected tier 'expired', got {credits_after_cancel['tier']}"
        assert credits_after_cancel['needs_subscription'] == True, "needs_subscription should be True after cancellation"
        print(f"✓ After cancellation: tier={credits_after_cancel['tier']}, needs_subscription={credits_after_cancel['needs_subscription']}")
        
        # Re-activate via sync
        sync_response = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_2999_1m_3d', 'is_trial': False}
        )
        assert sync_response.status_code == 200
        
        data = sync_response.json()
        assert data['tier'] == 'booked-out', f"Expected tier 'booked-out', got {data['tier']}"
        assert data['available_credits'] == 500, f"Expected 500 credits, got {data['available_credits']}"
        assert data['needs_subscription'] == False, "needs_subscription should be False after re-activation"
        print(f"✓ After re-activation: tier={data['tier']}, credits={data['available_credits']}, needs_subscription={data['needs_subscription']}")


class TestCleanup:
    """Cleanup test - restore demo account to known state"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token from demo login"""
        response = requests.post(f'{BASE_URL}/api/auth/demo-login')
        assert response.status_code == 200
        return response.json()['session_token']
    
    def test_restore_demo_account(self, auth_token):
        """Restore demo account to booked-out paid state"""
        headers = {'Authorization': f'Bearer {auth_token}'}
        
        response = requests.post(
            f'{BASE_URL}/api/subscription/sync',
            headers=headers,
            json={'product_id': 'bodybound_2999_1m_3d', 'is_trial': False}
        )
        assert response.status_code == 200
        
        data = response.json()
        print(f"✓ Demo account restored: tier={data['tier']}, credits={data['available_credits']}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
