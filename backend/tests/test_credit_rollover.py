"""
Credit Rollover Policy tests (monthly allowance × 2 cap).

Acceptance criteria:
- Credits roll over correctly between months
- Balance never exceeds cap
- Referral months trigger correct refill
- No duplicate or stacked refills occur
- Credit behavior is consistent across app restarts and sessions
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import server  # noqa: E402


async def _clean(uid):
    await server.db.subscriptions.delete_many({'user_id': uid})
    await server.db.referral_rewards.delete_many({'user_id': uid})


def _uid(tag):
    return f'test_rollover_{tag}_{uuid.uuid4().hex[:8]}'


# -------- Credit refill primitive --------

async def test_rollover_cap_walk_in():
    """Balance rolls over but never exceeds 2× monthly allowance."""
    uid = _uid('cap_walkin')
    try:
        await _clean(uid)
        # Cycle 1: fresh user, no doc yet
        r1 = await server.apply_monthly_refill(uid, 125, 'cycle-1', tier='walk-in')
        assert r1['applied'] is True, r1
        assert r1['new_balance'] == 125
        assert r1['max_balance_cap'] == 250

        # Cycle 2: unused credits roll over → 125 + 125 = 250 (at cap)
        r2 = await server.apply_monthly_refill(uid, 125, 'cycle-2', tier='walk-in')
        assert r2['applied'] is True
        assert r2['previous_balance'] == 125
        assert r2['new_balance'] == 250

        # Cycle 3: user is already AT cap → refill truncates at 250
        r3 = await server.apply_monthly_refill(uid, 125, 'cycle-3', tier='walk-in')
        assert r3['applied'] is True
        assert r3['previous_balance'] == 250
        assert r3['new_balance'] == 250, 'Balance must not exceed cap'
    finally:
        await _clean(uid)


async def test_partial_rollover():
    """User spent some credits → refill adds up to cap, not beyond."""
    uid = _uid('partial')
    try:
        await _clean(uid)
        # Cycle 1: start with 125
        await server.apply_monthly_refill(uid, 125, 'c1', tier='walk-in')
        # Simulate using 30 credits
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 95}}
        )
        # Cycle 2: 95 + 125 = 220 (below 250 cap)
        r2 = await server.apply_monthly_refill(uid, 125, 'c2', tier='walk-in')
        assert r2['new_balance'] == 220
        # Cycle 3: 220 + 125 = 345 → truncated to 250
        r3 = await server.apply_monthly_refill(uid, 125, 'c3', tier='walk-in')
        assert r3['new_balance'] == 250
    finally:
        await _clean(uid)


async def test_idempotent_same_cycle_key():
    """Second call with same cycle_key is a no-op (no double-refill)."""
    uid = _uid('idem')
    try:
        await _clean(uid)
        r1 = await server.apply_monthly_refill(uid, 125, 'same-key', tier='walk-in')
        assert r1['applied'] is True
        assert r1['new_balance'] == 125

        # Spend some
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 50}}
        )

        # 10 more calls with same cycle_key → none should refill
        for _ in range(10):
            r = await server.apply_monthly_refill(uid, 125, 'same-key', tier='walk-in')
            assert r['applied'] is False, f'Second call refilled! {r}'

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 50
    finally:
        await _clean(uid)


async def test_concurrent_refill_storm():
    """50 concurrent refills with the SAME cycle_key must only apply once."""
    uid = _uid('storm')
    try:
        await _clean(uid)
        results = await asyncio.gather(*[
            server.apply_monthly_refill(uid, 125, 'same-cycle', tier='walk-in')
            for _ in range(50)
        ])
        applied_count = sum(1 for r in results if r['applied'])
        assert applied_count == 1, f'Exactly one refill must be applied, got {applied_count}'

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 125, f'Balance should be 125, got {sub["available_credits"]}'
    finally:
        await _clean(uid)


async def test_booked_out_tier_500_cap_1000():
    """Booked-out plan: 500 monthly → 1000 cap."""
    uid = _uid('booked')
    try:
        await _clean(uid)
        r1 = await server.apply_monthly_refill(uid, 500, 'c1', tier='booked-out')
        assert r1['max_balance_cap'] == 1000
        assert r1['new_balance'] == 500
        r2 = await server.apply_monthly_refill(uid, 500, 'c2', tier='booked-out')
        assert r2['new_balance'] == 1000
        r3 = await server.apply_monthly_refill(uid, 500, 'c3', tier='booked-out')
        assert r3['new_balance'] == 1000  # capped
    finally:
        await _clean(uid)


# -------- Referral integration --------

async def test_referral_uses_rollover_refill():
    """Referral month activation should add credits with rollover+cap."""
    uid = _uid('ref_rollover')
    try:
        await _clean(uid)
        # User has 200 leftover credits (from previous subscription that ended)
        await server.db.subscriptions.insert_one({
            'user_id': uid,
            'tier': 'expired',
            'available_credits': 200,
            'is_trial': False,
        })
        await server.db.referral_rewards.insert_one({
            'user_id': uid,
            'rewards_earned': 1,
            'free_months_available': 1,
            'last_reward_at': datetime.now(timezone.utc).isoformat(),
        })

        await server.maybe_redeem_referral_month(uid)

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        # 200 + 125 = 325 → capped at 250
        assert sub['available_credits'] == 250, (
            f'Expected 250 (capped), got {sub["available_credits"]}'
        )
        assert sub['tier'] == server.REFERRAL_PREMIUM_TIER
        assert sub['max_balance_cap'] == 250
        assert sub['monthly_allowance'] == 125
    finally:
        await _clean(uid)


async def test_referral_fresh_user_gets_full_allowance():
    """Referral month on a brand-new user grants full 125 credits."""
    uid = _uid('ref_fresh')
    try:
        await _clean(uid)
        await server.db.referral_rewards.insert_one({
            'user_id': uid,
            'rewards_earned': 1,
            'free_months_available': 1,
            'last_reward_at': datetime.now(timezone.utc).isoformat(),
        })
        await server.maybe_redeem_referral_month(uid)
        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 125
        assert sub['tier'] == server.REFERRAL_PREMIUM_TIER
    finally:
        await _clean(uid)


async def test_referral_idempotent_no_duplicate_refill():
    """Repeated /auth/me hits during one active referral month don't double-refill."""
    uid = _uid('ref_idem')
    try:
        await _clean(uid)
        await server.db.referral_rewards.insert_one({
            'user_id': uid,
            'rewards_earned': 1,
            'free_months_available': 1,
            'last_reward_at': datetime.now(timezone.utc).isoformat(),
        })
        await server.maybe_redeem_referral_month(uid)
        # User spends 20 credits
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 105}}
        )
        # 20 more calls simulating /auth/me reloads
        for _ in range(20):
            await server.maybe_redeem_referral_month(uid)
        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 105, (
            f'Credits must stay at 105, got {sub["available_credits"]}'
        )
    finally:
        await _clean(uid)


async def _main():
    scenarios = [
        ('rollover_cap_walk_in', test_rollover_cap_walk_in),
        ('partial_rollover', test_partial_rollover),
        ('idempotent_same_cycle_key', test_idempotent_same_cycle_key),
        ('concurrent_refill_storm', test_concurrent_refill_storm),
        ('booked_out_tier_500_cap_1000', test_booked_out_tier_500_cap_1000),
        ('referral_uses_rollover_refill', test_referral_uses_rollover_refill),
        ('referral_fresh_user_gets_full_allowance', test_referral_fresh_user_gets_full_allowance),
        ('referral_idempotent_no_duplicate_refill', test_referral_idempotent_no_duplicate_refill),
    ]
    passed, failed = 0, []
    for name, fn in scenarios:
        try:
            await fn()
            print(f'  ✓ {name}')
            passed += 1
        except AssertionError as e:
            print(f'  ✗ {name} — {e}')
            failed.append(name)
        except Exception as e:
            print(f'  ✗ {name} — EXCEPTION: {type(e).__name__}: {e}')
            failed.append(name)
    print(f'\n{passed}/{len(scenarios)} scenarios passed')
    if failed:
        print(f'FAILED: {failed}')
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(_main())
