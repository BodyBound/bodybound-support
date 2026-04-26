"""Regression tests for /api/subscription/sync idempotency.

The bug: every cold-start of the iOS app calls /api/subscription/sync,
which previously called apply_paid_subscription_state(source='FRONTEND_SYNC'),
which UNCONDITIONALLY reset available_credits to the tier base and
credits_consumed_this_cycle to 0. Result: users got their credits "refilled"
on every app launch — and in particular every TestFlight update would
visibly reset their balance to 125 / 500 / 1500.

Fix: when source='FRONTEND_SYNC' AND the existing sub already has the same
tier + last_product_id + is_trial, skip the credit/consumed reset. Only
update last_event, last_applied_at, and revenuecat_customer_id.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
from server import apply_paid_subscription_state, db


@pytest.fixture(scope='module')
def event_loop():
    """Module-scoped loop — motor's async client binds to a single loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def _seed(user_id: str, tier: str, product_id: str, available: int, consumed: int):
    """Place a subscription doc directly so we can simulate a mid-cycle state."""
    await db.subscriptions.delete_one({'user_id': user_id})
    await db.subscriptions.insert_one({
        'user_id': user_id,
        'tier': tier,
        'available_credits': available,
        'credits_consumed_this_cycle': consumed,
        'last_product_id': product_id,
        'last_event': 'INITIAL_PURCHASE',
        'is_trial': False,
        'monthly_allowance': 125,
        'period_type': 'NORMAL',
    })


async def _read(user_id: str) -> dict:
    return await db.subscriptions.find_one({'user_id': user_id}, {'_id': 0}) or {}


async def _cleanup(user_id: str):
    await db.subscriptions.delete_one({'user_id': user_id})


def test_frontend_sync_preserves_credits_when_tier_unchanged(event_loop):
    """The exact bug Bryan reported: app cold-start must not refill credits."""
    user_id = 'test_sync_idempotent_walkin'
    product = 'bodybound_1499_1m_3d'  # walk-in, base 125 credits

    async def run():
        await _seed(user_id, 'walk-in', product, available=70, consumed=55)
        await apply_paid_subscription_state(
            user_id=user_id, product_id=product, source='FRONTEND_SYNC',
            rc_customer_id='rc_xyz_123', is_apple_trial=False,
        )
        sub = await _read(user_id)
        await _cleanup(user_id)
        return sub

    sub = event_loop.run_until_complete(run())
    # Credits MUST be preserved — this is the regression guard.
    assert sub['available_credits'] == 70, f"available_credits={sub['available_credits']}"
    assert sub['credits_consumed_this_cycle'] == 55, f"consumed={sub['credits_consumed_this_cycle']}"
    # rc_customer_id should still be picked up on resync (light-touch update)
    assert sub.get('revenuecat_customer_id') == 'rc_xyz_123'
    # Audit trail still written
    assert sub.get('last_event') == 'FRONTEND_SYNC'


def test_frontend_sync_resets_credits_on_tier_change(event_loop):
    """Genuine upgrade (walk-in → booked-out) must reset to new tier base."""
    user_id = 'test_sync_tier_change'

    async def run():
        await _seed(user_id, 'walk-in', 'bodybound_1499_1m_3d', available=20, consumed=105)
        # User upgrades to booked-out via the App Store; sync arrives with
        # the new product. Backend MUST apply the new state with full credits.
        await apply_paid_subscription_state(
            user_id=user_id, product_id='bodybound_2999_1m_3d',
            source='FRONTEND_SYNC', is_apple_trial=False,
        )
        sub = await _read(user_id)
        await _cleanup(user_id)
        return sub

    sub = event_loop.run_until_complete(run())
    assert sub['tier'] == 'booked-out'
    assert sub['available_credits'] == 500  # new tier base
    assert sub['credits_consumed_this_cycle'] == 0


def test_initial_purchase_still_resets_credits(event_loop):
    """Webhook INITIAL_PURCHASE must continue to apply full state — fresh cycle."""
    user_id = 'test_initial_purchase_resets'
    product = 'bodybound_1499_1m_3d'

    async def run():
        await _seed(user_id, 'walk-in', product, available=20, consumed=105)
        await apply_paid_subscription_state(
            user_id=user_id, product_id=product, source='INITIAL_PURCHASE',
            is_apple_trial=False,
        )
        sub = await _read(user_id)
        await _cleanup(user_id)
        return sub

    sub = event_loop.run_until_complete(run())
    assert sub['available_credits'] == 125
    assert sub['credits_consumed_this_cycle'] == 0
    assert sub['last_event'] == 'INITIAL_PURCHASE'


def test_renewal_still_resets_credits(event_loop):
    """Webhook RENEWAL signals a new billing cycle — must reset."""
    user_id = 'test_renewal_resets'
    product = 'bodybound_2999_1m_3d'

    async def run():
        await _seed(user_id, 'booked-out', product, available=10, consumed=490)
        await apply_paid_subscription_state(
            user_id=user_id, product_id=product, source='RENEWAL',
            is_apple_trial=False,
        )
        sub = await _read(user_id)
        await _cleanup(user_id)
        return sub

    sub = event_loop.run_until_complete(run())
    assert sub['available_credits'] == 500
    assert sub['credits_consumed_this_cycle'] == 0


def test_frontend_sync_resets_credits_when_trial_state_flips(event_loop):
    """Trial→paid transition (via FRONTEND_SYNC) must reset to full paid credits."""
    user_id = 'test_sync_trial_to_paid'
    product = 'bodybound_1499_1m_3d'

    async def run():
        # Trial state with low credits remaining
        await db.subscriptions.delete_one({'user_id': user_id})
        await db.subscriptions.insert_one({
            'user_id': user_id,
            'tier': 'walk-in',
            'available_credits': 1,
            'credits_consumed_this_cycle': server.TRIAL_CREDITS - 1,
            'last_product_id': product,
            'last_event': 'INITIAL_PURCHASE',
            'is_trial': True,
            'period_type': 'TRIAL',
        })
        # Trial converts to paid — frontend now sends is_trial=False.
        await apply_paid_subscription_state(
            user_id=user_id, product_id=product, source='FRONTEND_SYNC',
            is_apple_trial=False,
        )
        sub = await _read(user_id)
        await _cleanup(user_id)
        return sub

    sub = event_loop.run_until_complete(run())
    assert sub['is_trial'] is False
    assert sub['available_credits'] == 125  # full paid credits granted
    assert sub['credits_consumed_this_cycle'] == 0
