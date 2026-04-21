"""Regression tests for POST /api/credits/early-access-bridge.

The endpoint gives a ONE-TIME 10-credit top-up to users who are BOTH:
  - tier == 'paywall_bypass'
  - available_credits <= 0
  - received_temp_credits is not set / false / null

Guardrails (non-negotiable):
  - Non-bypass tiers (walk-in / booked-out / the-shop / None / expired /
    referral_premium) NEVER receive the grant.
  - Non-zero credits NEVER receive the grant.
  - received_temp_credits=true user NEVER receives a second grant.
  - Audit log entry written for every grant with admin_email
    'system:early-access-bridge'.
"""
import os
import uuid
import importlib
import pytest
import httpx

API_URL = os.environ.get(
    'DEPLOY_SANITY_API_URL',
    'http://localhost:8001',
)


@pytest.fixture
def api():
    return httpx.Client(base_url=API_URL, timeout=15.0)


def _login(api):
    r = api.post('/api/auth/demo-login')
    assert r.status_code == 200, r.text
    b = r.json()
    return b['user']['user_id'], b['session_token']


async def _prep_sub(server, user_id, tier, credits, received_flag=None):
    """Overwrite the subscription doc so tests start from a known state
    regardless of what previous tests (or signup) left behind."""
    doc = {
        'tier': tier,
        'available_credits': credits,
        # Always reset the flag unless the test explicitly wants it True.
        'received_temp_credits': bool(received_flag) if received_flag is not None else False,
    }
    await server.db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': doc},
        upsert=True,
    )


@pytest.fixture
def server():
    import server as srv
    importlib.reload(srv)
    return srv


@pytest.mark.asyncio
async def test_eligible_bypass_user_at_zero_gets_grant(api, server):
    user_id, token = _login(api)
    await _prep_sub(server, user_id, tier='paywall_bypass', credits=0)

    r = api.post('/api/credits/early-access-bridge',
                 headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['granted'] is True
    assert body['credits'] == 10
    assert 'Early Access Update' in body['message']
    # Flag must be set so a repeat call is a no-op.
    sub = await server.db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    assert sub['received_temp_credits'] is True
    assert sub['available_credits'] == 10


@pytest.mark.asyncio
async def test_repeat_call_is_noop(api, server):
    user_id, token = _login(api)
    await _prep_sub(server, user_id, tier='paywall_bypass', credits=0)

    r1 = api.post('/api/credits/early-access-bridge',
                  headers={'Authorization': f'Bearer {token}'})
    assert r1.json()['granted'] is True

    # Now user consumed credits back to 0. Second call must NOT re-grant.
    await server.db.subscriptions.update_one(
        {'user_id': user_id},
        {'$set': {'available_credits': 0}},
    )
    r2 = api.post('/api/credits/early-access-bridge',
                  headers={'Authorization': f'Bearer {token}'})
    body2 = r2.json()
    assert body2['granted'] is False
    assert body2['reason'] == 'not_eligible'
    # Mongo state unchanged — still 0.
    sub = await server.db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    assert sub['available_credits'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('tier', ['walk-in', 'booked-out', 'the-shop', 'expired', 'referral_premium', None])
async def test_non_bypass_tier_never_gets_grant(api, server, tier):
    user_id, token = _login(api)
    await _prep_sub(server, user_id, tier=tier, credits=0)

    r = api.post('/api/credits/early-access-bridge',
                 headers={'Authorization': f'Bearer {token}'})
    body = r.json()
    assert body['granted'] is False
    sub = await server.db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    assert sub['available_credits'] == 0
    assert sub.get('received_temp_credits') in (None, False)


@pytest.mark.asyncio
async def test_bypass_user_with_positive_credits_is_ignored(api, server):
    user_id, token = _login(api)
    await _prep_sub(server, user_id, tier='paywall_bypass', credits=5)

    r = api.post('/api/credits/early-access-bridge',
                 headers={'Authorization': f'Bearer {token}'})
    assert r.json()['granted'] is False
    sub = await server.db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    # Original positive balance untouched.
    assert sub['available_credits'] == 5


@pytest.mark.asyncio
async def test_already_flagged_user_is_ignored(api, server):
    user_id, token = _login(api)
    await _prep_sub(server, user_id, tier='paywall_bypass', credits=0, received_flag=True)

    r = api.post('/api/credits/early-access-bridge',
                 headers={'Authorization': f'Bearer {token}'})
    assert r.json()['granted'] is False
    sub = await server.db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
    assert sub['available_credits'] == 0


@pytest.mark.asyncio
async def test_audit_log_is_written_on_grant(api, server):
    user_id, token = _login(api)
    await _prep_sub(server, user_id, tier='paywall_bypass', credits=0)
    # Wipe prior audit rows for this user so we count only today's.
    await server.db.admin_actions.delete_many(
        {'action': 'early_access_credit_bridge', 'details.user_id': user_id})

    r = api.post('/api/credits/early-access-bridge',
                 headers={'Authorization': f'Bearer {token}'})
    assert r.json()['granted'] is True

    audit = await server.db.admin_actions.find_one(
        {'action': 'early_access_credit_bridge', 'details.user_id': user_id},
        {'_id': 0},
    )
    assert audit is not None
    assert audit['admin_email'] == 'system:early-access-bridge'
    assert audit['details']['credits_granted'] == 10
    assert audit['details']['tier'] == 'paywall_bypass'
