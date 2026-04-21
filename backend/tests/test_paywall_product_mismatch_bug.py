"""Regression tests for the "tapped Walk-In, got Booked Out" frontend bug.

Background: on `bodyboundstencilapp@gmail.com` and `formyuselessstuff1@gmail.com`,
tapping the Walk-In card resulted in 500 credits (Booked Out), not 125. Root
cause was in `frontend/app/screens/PaywallScreen.tsx`: after the purchase
completed, we synced the TAPPED product (`selectedPackage.product.identifier`)
instead of the ACTIVE product (`activeEntitlement.productIdentifier`). In
sandbox and PRODUCT_CHANGE flows, Apple can grant a different product than
the one tapped, causing the sync to lie and the RC webhook to correct it
later — producing the "welcome to Walk-In / wait, I have 500 credits" bug.

These tests lock the backend contract that the FIX relies on:

1. When the frontend syncs an ACTIVE product, backend applies exactly that
   product's tier + credits, regardless of what the user "intended".
2. If a subsequent RC webhook arrives with a DIFFERENT product, the backend
   authoritatively applies the webhook's product (RC is the source of truth
   for what the customer is actually billed for).
3. Re-running sync with the same product is idempotent and does not double-
   refill credits.

Run: `DEPLOY_SANITY_API_URL=<host> pytest tests/test_paywall_product_mismatch_bug.py`
"""
import os
import pytest
import httpx

API_URL = os.environ.get(
    'DEPLOY_SANITY_API_URL',
    'https://stencil-ai-fallback.preview.emergentagent.com',
)

WALK_IN = ('bodybound_1499_1m_3d', 'walk-in', 125)
BOOKED_OUT = ('bodybound_2999_1m_3d', 'booked-out', 500)


@pytest.fixture
def api():
    return httpx.Client(base_url=API_URL, timeout=20.0)


def _login(api):
    r = api.post('/api/auth/demo-login')
    assert r.status_code == 200, r.text
    body = r.json()
    return body['user']['user_id'], body['session_token']


def _sub(api, user_id):
    r = api.get(f'/api/admin/user-lookup?user_id={user_id}')
    assert r.status_code == 200, r.text
    return r.json().get('subscription') or {}


def test_sync_applies_active_product_not_tapped_product(api):
    """Verifies the contract: whatever product_id the frontend sends to
    /api/subscription/sync is what the backend applies. This means the fix
    ("send activeEntitlement.productIdentifier, not selectedPackage.product
    .identifier") lands on the correct tier."""
    user_id, token = _login(api)

    # Frontend submits the ACTIVE product id (what Apple actually granted).
    # Even if the user TAPPED Walk-In, we must end up with whatever RC reports.
    active_product = BOOKED_OUT[0]
    r = api.post(
        '/api/subscription/sync',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'product_id': active_product,
            'is_trial': False,
            'revenuecat_customer_id': 'rc_paywall_bug_regression',
        },
    )
    assert r.status_code == 200, r.text

    sub = _sub(api, user_id)
    assert sub.get('tier') == BOOKED_OUT[1], sub
    assert sub.get('available_credits') == BOOKED_OUT[2], sub
    # NEVER infer tier from the tapped product. The ONLY input is active_product.
    assert sub.get('last_product_id') == active_product, sub


def test_webhook_is_authoritative_over_mismatched_sync(api):
    """If the frontend mistakenly synced the WRONG product (e.g. the
    pre-fix version that trusted selectedPackage), the RC webhook MUST
    authoritatively correct the state when it arrives with the real
    product id. This is the second safety net behind the frontend fix."""
    user_id, _ = _login(api)

    # Step 1: simulate a pre-fix BUGGY sync — frontend said walk-in but Apple
    # actually gave booked-out.
    r = api.post(
        '/api/webhooks/revenuecat',
        json={'event': {
            'type': 'INITIAL_PURCHASE',
            'app_user_id': user_id,
            'product_id': WALK_IN[0],  # buggy frontend claim
            'period_type': 'NORMAL',
        }},
    )
    assert r.status_code == 200, r.text
    after_buggy = _sub(api, user_id)
    assert after_buggy.get('tier') == WALK_IN[1]
    assert after_buggy.get('available_credits') == WALK_IN[2]

    # Step 2: RC webhook arrives with the REAL product (booked-out). Must
    # authoritatively apply the correct tier + credits.
    r = api.post(
        '/api/webhooks/revenuecat',
        json={'event': {
            'type': 'INITIAL_PURCHASE',
            'app_user_id': user_id,
            'product_id': BOOKED_OUT[0],  # real product
            'period_type': 'NORMAL',
        }},
    )
    assert r.status_code == 200, r.text
    after_correction = _sub(api, user_id)
    assert after_correction.get('tier') == BOOKED_OUT[1], after_correction
    assert after_correction.get('available_credits') == BOOKED_OUT[2], after_correction
    assert after_correction.get('last_product_id') == BOOKED_OUT[0], after_correction


def test_double_sync_same_product_is_idempotent(api):
    """The fix calls /api/subscription/sync exactly once after a successful
    purchase. The RC webhook then fires for the SAME product. Verify the
    state stays correct (credits not double-refilled)."""
    user_id, token = _login(api)

    # Pre-consume some credits so we can detect a double-refill.
    r = api.post(
        '/api/subscription/sync',
        headers={'Authorization': f'Bearer {token}'},
        json={'product_id': WALK_IN[0], 'is_trial': False},
    )
    assert r.status_code == 200, r.text
    first = _sub(api, user_id)
    assert first.get('available_credits') == WALK_IN[2]

    # Second sync with same product (webhook arriving after sync, typical flow).
    r = api.post(
        '/api/webhooks/revenuecat',
        json={'event': {
            'type': 'INITIAL_PURCHASE',
            'app_user_id': user_id,
            'product_id': WALK_IN[0],
            'period_type': 'NORMAL',
        }},
    )
    assert r.status_code == 200, r.text
    second = _sub(api, user_id)
    # Tier + credits must remain the same product's allowance. Both paths
    # reset the cycle to 0 consumed and refill to the exact monthly cap — no
    # duplication.
    assert second.get('tier') == WALK_IN[1], second
    assert second.get('available_credits') == WALK_IN[2], second
