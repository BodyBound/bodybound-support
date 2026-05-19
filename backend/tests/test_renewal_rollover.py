"""
Credit Rollover on Renewal — RevenueCat webhook integration tests.

Validates that `apply_paid_subscription_state(source='RENEWAL', ...)` rolls
over unused credits up to the 2× monthly_allowance cap, while every other
source (INITIAL_PURCHASE / PRODUCT_CHANGE / UNCANCELLATION / FRONTEND_SYNC
tier-change) still hard-resets credits.

The Bug (production, May 2026):
    Walk-In user with 100 unused credits hits Apple anniversary renewal.
    Webhook fires RENEWAL → `available_credits` was hard-set to 125, losing
    the 100 banked credits.

The Fix:
    RENEWAL routes through `apply_monthly_refill` (already battle-tested in
    test_credit_rollover.py for the cron path) with an event-id-derived
    cycle_key. Adds monthly_allowance to the existing balance, capped at 2×.
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import server  # noqa: E402


async def _clean(uid):
    await server.db.subscriptions.delete_many({'user_id': uid})


def _uid(tag):
    return f'test_renewal_{tag}_{uuid.uuid4().hex[:8]}'


# ─────────────────────────── RENEWAL: rollover path ────────────────────────

async def test_renewal_rolls_over_unused_credits():
    """Walk-In with 100 unused credits + RENEWAL → 100 + 125 = 225 (under cap)."""
    uid = _uid('walkin_rollover')
    try:
        await _clean(uid)
        # Seed: user is mid-cycle on walk-in with 100 of 125 left
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_init_001'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid},
            {'$set': {'available_credits': 100, 'credits_consumed_this_cycle': 25}},
        )

        # RENEWAL fires
        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL', event_id='evt_renew_001'
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 225, (
            f'Expected 100+125=225 after rollover, got {sub["available_credits"]}'
        )
        assert sub['credits_consumed_this_cycle'] == 0, 'consumed counter must reset'
        assert sub['tier'] == 'walk-in'
        assert sub['last_event'] == 'RENEWAL'
        assert sub['last_product_id'] == '01'
        assert sub['monthly_allowance'] == 125
        assert sub['max_balance_cap'] == 250
    finally:
        await _clean(uid)


async def test_renewal_caps_at_2x_allowance():
    """Walk-In with 200 unused + RENEWAL → 200 + 125 = 325, truncated to cap=250."""
    uid = _uid('walkin_cap')
    try:
        await _clean(uid)
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_init_002'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 200}}
        )

        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL', event_id='evt_renew_002'
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 250, (
            f'Balance must cap at 250 (walk-in 125 × 2), got {sub["available_credits"]}'
        )
    finally:
        await _clean(uid)


async def test_renewal_at_cap_stays_at_cap():
    """User already at 250 (cap) gets RENEWAL → still 250, no underflow."""
    uid = _uid('walkin_at_cap')
    try:
        await _clean(uid)
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_init_003'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 250}}
        )

        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL', event_id='evt_renew_003'
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 250
    finally:
        await _clean(uid)


async def test_renewal_idempotent_same_event_id():
    """Webhook replay with same event_id → does NOT double-refill."""
    uid = _uid('renewal_idempotent')
    try:
        await _clean(uid)
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_init_004'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 50}}
        )

        # First RENEWAL: 50 + 125 = 175
        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL', event_id='evt_renew_dup_004'
        )
        sub_after_1 = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub_after_1['available_credits'] == 175

        # Replay with same event_id → no-op on credits
        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL', event_id='evt_renew_dup_004'
        )
        sub_after_2 = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub_after_2['available_credits'] == 175, (
            f'Replay must NOT re-add credits — got {sub_after_2["available_credits"]}'
        )
    finally:
        await _clean(uid)


async def test_renewal_distinct_events_each_refill():
    """Two RENEWAL events with different event_ids → both refill (true monthly cycle)."""
    uid = _uid('renewal_two_cycles')
    try:
        await _clean(uid)
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_init_005'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 25}}
        )

        # Cycle 1 RENEWAL: 25 + 125 = 150
        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL', event_id='evt_cycle_1'
        )
        sub_1 = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub_1['available_credits'] == 150

        # Simulate the user spending 20 credits between cycles
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 130}}
        )

        # Cycle 2 RENEWAL: 130 + 125 = 255 → capped at 250
        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL', event_id='evt_cycle_2'
        )
        sub_2 = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub_2['available_credits'] == 250, (
            f'Second cycle should refill + cap → 250, got {sub_2["available_credits"]}'
        )
    finally:
        await _clean(uid)


async def test_renewal_booked_out_tier():
    """Booked-Out: 400 unused + RENEWAL → 400 + 500 = 900 (under 1000 cap)."""
    uid = _uid('booked_out')
    try:
        await _clean(uid)
        await server.apply_paid_subscription_state(
            uid, '02', source='INITIAL_PURCHASE', event_id='evt_bo_init'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 400}}
        )

        await server.apply_paid_subscription_state(
            uid, '02', source='RENEWAL', event_id='evt_bo_renew'
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['tier'] == 'booked-out'
        assert sub['available_credits'] == 900
        assert sub['max_balance_cap'] == 1000
    finally:
        await _clean(uid)


# ───────────── Non-RENEWAL paths: hard-reset behavior preserved ───────────

async def test_initial_purchase_hard_resets_credits():
    """Fresh INITIAL_PURCHASE → exactly tier allowance, no rollover."""
    uid = _uid('initial_hard_reset')
    try:
        await _clean(uid)
        # Seed an old doc with bonus credits
        await server.db.subscriptions.update_one(
            {'user_id': uid},
            {'$set': {'available_credits': 999, 'tier': 'expired'}},
            upsert=True,
        )

        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_init_hardreset'
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 125, (
            f'INITIAL_PURCHASE must hard-reset, got {sub["available_credits"]}'
        )
        assert sub['credits_consumed_this_cycle'] == 0
    finally:
        await _clean(uid)


async def test_product_change_upgrade_hard_resets_to_new_tier():
    """Walk-In → Booked-Out via PRODUCT_CHANGE: credits = 500, not 100+500."""
    uid = _uid('product_change')
    try:
        await _clean(uid)
        # Seed: walk-in with 100 unused
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_pc_init'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 100}}
        )

        # Upgrade to booked-out
        await server.apply_paid_subscription_state(
            uid, '02', source='PRODUCT_CHANGE', event_id='evt_pc_upgrade'
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['tier'] == 'booked-out'
        assert sub['available_credits'] == 500, (
            f'Upgrade must hard-reset to new tier allowance, got {sub["available_credits"]}'
        )
    finally:
        await _clean(uid)


async def test_uncancellation_hard_resets():
    """UNCANCELLATION restores full state (current behavior — NOT rollover)."""
    uid = _uid('uncancellation')
    try:
        await _clean(uid)
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_unc_init'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 75}}
        )

        await server.apply_paid_subscription_state(
            uid, '01', source='UNCANCELLATION', event_id='evt_unc'
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        # UNCANCELLATION currently still hard-resets — this is intentional and
        # NOT changed by the rollover fix. If product later decides UNCANCELLATION
        # should also preserve mid-cycle balance, update this test + the apply path.
        assert sub['available_credits'] == 125, (
            f'UNCANCELLATION should still hard-reset, got {sub["available_credits"]}'
        )
        assert sub['last_event'] == 'UNCANCELLATION'
    finally:
        await _clean(uid)


async def test_apple_trial_renewal_does_not_rollover():
    """Trial RENEWAL → TRIAL_CREDITS=10 hard-set (no rollover during free trial)."""
    uid = _uid('trial_renewal')
    try:
        await _clean(uid)
        # Seed: in trial
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE',
            is_apple_trial=True, event_id='evt_trial_init',
        )
        # Force any balance
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 5}}
        )

        # Trial RENEWAL (shouldn't happen in real life — trials don't renew
        # before converting — but we defensively handle it)
        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL',
            is_apple_trial=True, event_id='evt_trial_renew',
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['is_trial'] is True
        # Trial path bypasses rollover and goes through the hard-reset branch.
        assert sub['available_credits'] == server.TRIAL_CREDITS
    finally:
        await _clean(uid)


async def test_renewal_without_event_id_falls_back_to_date_key():
    """RENEWAL without event_id still works (date-bucketed cycle_key)."""
    uid = _uid('no_event_id')
    try:
        await _clean(uid)
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_noid_init'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 50}}
        )

        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL', event_id=None
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['available_credits'] == 175  # 50 + 125
        assert sub['last_event'] == 'RENEWAL'
    finally:
        await _clean(uid)


async def test_renewal_preserves_audit_fields():
    """RENEWAL must still stamp last_event, last_product_id, renewal_date, etc."""
    uid = _uid('audit_fields')
    try:
        await _clean(uid)
        await server.apply_paid_subscription_state(
            uid, '01', source='INITIAL_PURCHASE', event_id='evt_audit_init'
        )
        await server.db.subscriptions.update_one(
            {'user_id': uid}, {'$set': {'available_credits': 75}}
        )

        await server.apply_paid_subscription_state(
            uid, '01', source='RENEWAL', event_id='evt_audit_renew',
            rc_customer_id='rc_cust_audit',
        )

        sub = await server.db.subscriptions.find_one({'user_id': uid})
        assert sub['tier'] == 'walk-in'
        assert sub['last_event'] == 'RENEWAL'
        assert sub['last_product_id'] == '01'
        assert sub['monthly_allowance'] == 125
        assert sub['max_balance_cap'] == 250
        assert sub['revenuecat_customer_id'] == 'rc_cust_audit'
        assert sub['renewal_date'] is not None
        assert sub['last_applied_at'] is not None
        assert sub['last_refill_at'].startswith('rc:renewal:evt_audit_renew')
        assert sub['credits_consumed_this_cycle'] == 0
    finally:
        await _clean(uid)


async def _main():
    scenarios = [
        ('renewal_rolls_over_unused_credits', test_renewal_rolls_over_unused_credits),
        ('renewal_caps_at_2x_allowance', test_renewal_caps_at_2x_allowance),
        ('renewal_at_cap_stays_at_cap', test_renewal_at_cap_stays_at_cap),
        ('renewal_idempotent_same_event_id', test_renewal_idempotent_same_event_id),
        ('renewal_distinct_events_each_refill', test_renewal_distinct_events_each_refill),
        ('renewal_booked_out_tier', test_renewal_booked_out_tier),
        ('initial_purchase_hard_resets_credits', test_initial_purchase_hard_resets_credits),
        ('product_change_upgrade_hard_resets_to_new_tier', test_product_change_upgrade_hard_resets_to_new_tier),
        ('uncancellation_hard_resets', test_uncancellation_hard_resets),
        ('apple_trial_renewal_does_not_rollover', test_apple_trial_renewal_does_not_rollover),
        ('renewal_without_event_id_falls_back_to_date_key', test_renewal_without_event_id_falls_back_to_date_key),
        ('renewal_preserves_audit_fields', test_renewal_preserves_audit_fields),
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
