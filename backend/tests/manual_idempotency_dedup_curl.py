"""Curl-style validation of P2 reroll idempotency + P3 RC webhook event.id dedup
against the running localhost:8001 backend. Replaces the TestClient unit
tests that hit a motor/asyncio loop conflict."""
import asyncio
import json
import os
import sys
import urllib.request

import jwt

sys.path.insert(0, '/app/backend')
from server import db, JWT_SECRET  # noqa: E402

API = "http://localhost:8001"


def _post(path: str, body: dict, token: str = None, auth: str = None) -> tuple[int, dict]:
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if auth:
        headers['Authorization'] = auth
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode(),
        headers=headers,
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, {'error': e.read().decode()}


async def seed_user(email: str, available: int, consumed: int) -> tuple[str, str]:
    user_id = f"test_{email.replace('@','_').replace('.','_')}"
    await db.users.delete_many({'email': email})
    await db.users.insert_one({'user_id': user_id, 'email': email, 'name': 'T'})
    await db.subscriptions.delete_one({'user_id': user_id})
    await db.subscriptions.insert_one({
        'user_id': user_id, 'tier': 'walk-in',
        'available_credits': available,
        'credits_consumed_this_cycle': consumed,
        'last_product_id': 'bodybound_1499_1m_3d',
        'last_event': 'INITIAL_PURCHASE', 'is_trial': False,
    })
    token = jwt.encode({'user_id': user_id, 'email': email}, JWT_SECRET, algorithm='HS256')
    return user_id, token


async def cleanup(user_id: str):
    await db.users.delete_one({'user_id': user_id})
    await db.subscriptions.delete_one({'user_id': user_id})
    await db.credit_deduct_idempotency.delete_many({'user_id': user_id})


async def main():
    print("=" * 60)
    print("P2: Reroll Idempotency")
    print("=" * 60)

    # --- Test 1: same reroll_id twice → only one deduction
    user_id, token = await seed_user('p2_dup@test.com', 10, 0)
    try:
        rid = 'rid_dup_test_1'
        s1, r1 = _post('/api/credits/deduct', {'reroll_id': rid}, token=token)
        s2, r2 = _post('/api/credits/deduct', {'reroll_id': rid}, token=token)
        assert s1 == 200 and s2 == 200, f"statuses {s1}, {s2}"
        assert r1['available_credits'] == 9, f"first call should deduct: {r1}"
        assert r2['available_credits'] == 9, f"replay should return cached: {r2}"
        sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
        assert sub['available_credits'] == 9 and sub['credits_consumed_this_cycle'] == 1
        print("✓ Same reroll_id twice → only one deduction (P2 OK)")
    finally:
        await cleanup(user_id)

    # --- Test 2: distinct reroll_ids → each charges
    user_id, token = await seed_user('p2_distinct@test.com', 10, 0)
    try:
        for rid in ['rid_a', 'rid_b', 'rid_c']:
            s, _ = _post('/api/credits/deduct', {'reroll_id': rid}, token=token)
            assert s == 200
        sub = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
        assert sub['available_credits'] == 7 and sub['credits_consumed_this_cycle'] == 3
        print("✓ Distinct reroll_ids → each charges (P2 OK)")
    finally:
        await cleanup(user_id)

    # --- Test 3: no reroll_id → backwards-compat (charges every time)
    user_id, token = await seed_user('p2_no_key@test.com', 10, 0)
    try:
        s1, r1 = _post('/api/credits/deduct', {}, token=token)
        s2, r2 = _post('/api/credits/deduct', {}, token=token)
        assert s1 == 200 and s2 == 200
        assert r1['available_credits'] == 9 and r2['available_credits'] == 8
        print("✓ No reroll_id → backwards-compatible double charge (P2 OK)")
    finally:
        await cleanup(user_id)

    print("\n" + "=" * 60)
    print("P3: RevenueCat webhook event.id dedup")
    print("=" * 60)

    rc_auth = os.environ.get('REVENUECAT_WEBHOOK_AUTH', '')
    auth_hdr = f"Bearer {rc_auth.replace('Bearer ', '').strip()}" if rc_auth else None

    # --- Test 4: replay of CANCELLATION returns duplicate
    user_id, _ = await seed_user('p3_cancel@test.com', 50, 75)
    try:
        evt_id = 'evt_p3_cancel_aaa'
        payload = {'event': {
            'id': evt_id, 'type': 'CANCELLATION',
            'app_user_id': user_id, 'product_id': 'bodybound_1499_1m_3d',
            'aliases': [],
        }}
        s1, r1 = _post('/api/webhooks/revenuecat', payload, auth=auth_hdr)
        s2, r2 = _post('/api/webhooks/revenuecat', payload, auth=auth_hdr)
        assert s1 == 200 and s2 == 200, f"statuses {s1}, {s2}"
        assert r2.get('duplicate') is True, f"replay must report duplicate: {r2}"
        assert r2.get('event_id') == evt_id
        print("✓ CANCELLATION replay returns duplicate=True (P3 OK)")
    finally:
        await db.revenuecat_webhook_events.delete_one({'_id': 'evt_p3_cancel_aaa'})
        await cleanup(user_id)

    # --- Test 5: RENEWAL replay does NOT re-reset credits
    user_id, _ = await seed_user('p3_renewal@test.com', 70, 55)
    try:
        evt_id = 'evt_p3_renewal_zzz'
        payload = {'event': {
            'id': evt_id, 'type': 'RENEWAL',
            'app_user_id': user_id, 'product_id': 'bodybound_1499_1m_3d',
            'aliases': [],
        }}
        # First call legitimately resets to 125 / 0
        s1, _ = _post('/api/webhooks/revenuecat', payload, auth=auth_hdr)
        assert s1 == 200
        first = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
        assert first['available_credits'] == 125 and first['credits_consumed_this_cycle'] == 0

        # Simulate user spending some credits before the replay
        await db.subscriptions.update_one(
            {'user_id': user_id},
            {'$set': {'available_credits': 100, 'credits_consumed_this_cycle': 25}},
        )

        # Replay — must be no-op
        s2, r2 = _post('/api/webhooks/revenuecat', payload, auth=auth_hdr)
        assert s2 == 200 and r2.get('duplicate') is True
        after = await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0})
        assert after['available_credits'] == 100, f"replay reset credits: {after}"
        assert after['credits_consumed_this_cycle'] == 25
        print("✓ RENEWAL replay does NOT reset credits (P3 OK)")
    finally:
        await db.revenuecat_webhook_events.delete_one({'_id': 'evt_p3_renewal_zzz'})
        await cleanup(user_id)

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
