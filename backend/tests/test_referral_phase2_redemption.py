"""
Phase 2 Referral Reward Redemption Tests (Simple Credit-Based Path)
====================================================================
Directly exercises `maybe_redeem_referral_month` against the live MongoDB.
All scenarios are executed inside a single asyncio loop so motor's client
stays valid for the whole run.

QA cases covered:
1. User earns 1 free month and gets premium immediately
2. User earns multiple months — chain correctly one at a time
3. User with paid premium also earns referral months (bank, don't activate)
4. No duplicate credit refill on repeated calls
5. Expired referral month correctly falls back to free state
6. App reopen / sync / webhook retries do not reapply the same month twice
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import server  # noqa: E402


# ---------- Helpers ----------

async def _clean(user_id: str):
    await server.db.referral_rewards.delete_many({'user_id': user_id})
    await server.db.subscriptions.delete_many({'user_id': user_id})


async def _seed_reward(user_id: str, available: int, until=None,
                       last_redeemed_at=None, granted_for=None):
    await server.db.referral_rewards.insert_one({
        'user_id': user_id,
        'rewards_earned': available,
        'free_months_available': available,
        'referral_premium_until': until,
        'last_referral_month_redeemed_at': last_redeemed_at,
        'referral_credits_granted_for': granted_for,
        'last_reward_at': datetime.now(timezone.utc).isoformat(),
    })


async def _seed_sub(user_id: str, tier, is_trial: bool = False, credits: int = 0):
    await server.db.subscriptions.insert_one({
        'user_id': user_id,
        'tier': tier,
        'available_credits': credits,
        'is_trial': is_trial,
    })


def _uid(tag: str) -> str:
    return f'test_phase2_{tag}_{uuid.uuid4().hex[:8]}'


# ---------- Scenarios ----------

async def case1_earn_one_month_activates_immediately():
    uid = _uid('one')
    try:
        await _clean(uid)
        await _seed_reward(uid, available=1)

        result = await server.maybe_redeem_referral_month(uid)

        assert result['free_months_available'] == 0
        assert result['referral_premium_until'] is not None
        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub is not None
        assert sub['tier'] == server.REFERRAL_PREMIUM_TIER
        assert sub['available_credits'] == server.REFERRAL_PREMIUM_CREDITS
        until_dt = datetime.fromisoformat(result['referral_premium_until'].replace('Z', '+00:00'))
        delta_days = (until_dt - datetime.now(timezone.utc)).days
        assert 28 <= delta_days <= 30
    finally:
        await _clean(uid)


async def case2_multiple_months_chain_correctly():
    uid = _uid('chain')
    try:
        await _clean(uid)
        await _seed_reward(uid, available=3)

        r1 = await server.maybe_redeem_referral_month(uid)
        assert r1['free_months_available'] == 2
        first_until = r1['referral_premium_until']

        r2 = await server.maybe_redeem_referral_month(uid)
        assert r2['free_months_available'] == 2
        assert r2['referral_premium_until'] == first_until

        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        await server.db.referral_rewards.update_one(
            {'user_id': uid}, {'$set': {'referral_premium_until': past}}
        )
        sub_before = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub_before['tier'] == server.REFERRAL_PREMIUM_TIER

        r3 = await server.maybe_redeem_referral_month(uid)
        assert r3['free_months_available'] == 1
        until_dt = datetime.fromisoformat(r3['referral_premium_until'].replace('Z', '+00:00'))
        assert until_dt > datetime.now(timezone.utc)

        sub_after = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub_after['tier'] == server.REFERRAL_PREMIUM_TIER
        # Rollover policy: previous 125 credits + 125 new = 250 (at cap 250)
        assert sub_after['available_credits'] == 250, (
            f'Expected 250 (rollover at cap), got {sub_after["available_credits"]}'
        )
    finally:
        await _clean(uid)


async def case3_paid_user_banks_months_no_activation():
    uid = _uid('paid')
    try:
        await _clean(uid)
        await _seed_sub(uid, tier='booked-out', is_trial=False, credits=500)
        await _seed_reward(uid, available=2)

        result = await server.maybe_redeem_referral_month(uid)
        assert result['free_months_available'] == 2
        assert result.get('referral_premium_until') is None
        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['tier'] == 'booked-out'
        assert sub['available_credits'] == 500
    finally:
        await _clean(uid)


async def case4_no_duplicate_credit_refill_on_repeated_calls():
    uid = _uid('nodup')
    try:
        await _clean(uid)
        await _seed_reward(uid, available=1)

        await server.maybe_redeem_referral_month(uid)
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 115}}
        )

        for _ in range(10):
            await server.maybe_redeem_referral_month(uid)

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 115, (
            f'Credits must stay at 115, got {sub["available_credits"]}'
        )
        r = await server.db.referral_rewards.find_one({'user_id': uid})
        assert r['free_months_available'] == 0
    finally:
        await _clean(uid)


async def case5_expired_with_no_queued_falls_back_to_free():
    uid = _uid('expired')
    try:
        await _clean(uid)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        await _seed_reward(uid, available=0, until=past,
                           last_redeemed_at=past, granted_for=past)
        await _seed_sub(uid, tier=server.REFERRAL_PREMIUM_TIER, credits=0)

        await server.maybe_redeem_referral_month(uid)

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['tier'] == 'expired'
    finally:
        await _clean(uid)


async def case6_idempotent_against_webhook_retry_storms():
    uid = _uid('idem')
    try:
        await _clean(uid)
        await _seed_reward(uid, available=2)

        await asyncio.gather(*[
            server.maybe_redeem_referral_month(uid) for _ in range(50)
        ])

        r = await server.db.referral_rewards.find_one({'user_id': uid})
        assert r['free_months_available'] == 1, (
            f'Expected 1 remaining, got {r["free_months_available"]}'
        )
        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['tier'] == server.REFERRAL_PREMIUM_TIER
        assert sub['available_credits'] == server.REFERRAL_PREMIUM_CREDITS
    finally:
        await _clean(uid)


async def case7_free_user_with_no_rewards_is_noop():
    uid = _uid('noop')
    try:
        await _clean(uid)
        result = await server.maybe_redeem_referral_month(uid)
        assert result is None
        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub is None
    finally:
        await _clean(uid)


async def case8_trial_user_counts_as_not_paid():
    uid = _uid('trial')
    try:
        await _clean(uid)
        await _seed_sub(uid, tier='walk-in', is_trial=True, credits=15)
        await _seed_reward(uid, available=1)

        await server.maybe_redeem_referral_month(uid)

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['tier'] == server.REFERRAL_PREMIUM_TIER
        # Rollover: trial's 15 credits + 125 = 140 (below cap 250)
        assert sub['available_credits'] == 140, (
            f'Expected 140 (15 + 125 rollover), got {sub["available_credits"]}'
        )
    finally:
        await _clean(uid)


async def _main():
    scenarios = [
        ('case1_earn_one_month_activates_immediately', case1_earn_one_month_activates_immediately),
        ('case2_multiple_months_chain_correctly', case2_multiple_months_chain_correctly),
        ('case3_paid_user_banks_months_no_activation', case3_paid_user_banks_months_no_activation),
        ('case4_no_duplicate_credit_refill_on_repeated_calls', case4_no_duplicate_credit_refill_on_repeated_calls),
        ('case5_expired_with_no_queued_falls_back_to_free', case5_expired_with_no_queued_falls_back_to_free),
        ('case6_idempotent_against_webhook_retry_storms', case6_idempotent_against_webhook_retry_storms),
        ('case7_free_user_with_no_rewards_is_noop', case7_free_user_with_no_rewards_is_noop),
        ('case8_trial_user_counts_as_not_paid', case8_trial_user_counts_as_not_paid),
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
