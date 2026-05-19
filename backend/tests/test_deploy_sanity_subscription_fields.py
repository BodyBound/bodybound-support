"""Deploy-sanity tests for the subscription-state rewrite (commit 9b852a22).

These tests fail hard whenever the backend that `API_URL` points at is running
a version of ``server.py`` older than the rewrite that introduced
``apply_paid_subscription_state()``. They deliberately do NOT test tier/credit
behaviour (covered by ``test_paywall_flow.py`` /
``test_paywall_flow_extended.py``) — they only check that the *new audit
fields* written by the rewrite are actually present on the subscription doc
after we apply paid state via the three supported code paths:

- ``/api/subscription/sync``        → source = ``FRONTEND_SYNC``
- ``INITIAL_PURCHASE`` webhook      → source = ``INITIAL_PURCHASE``
- ``RENEWAL`` webhook               → source = ``RENEWAL``

If any of the required fields is missing or None, the test fails — which is
the signal that the production host is serving stale code even though the
rewrite is in the repo. Also covers:

- TRANSFER stamps ``last_transfer_at`` and never mutates tier/credits/is_trial

Point these at production to verify a prod deploy: ``API_URL=...`` env var.
"""
import os
import pytest
import httpx

API_URL = os.environ.get(
    'DEPLOY_SANITY_API_URL',
    'https://stencil-ai-fallback.preview.emergentagent.com',
)

# Fields the rewrite (commit 9b852a22) must write through
# ``apply_paid_subscription_state()``. If any of these is missing / None after
# a successful paid-state application, the backend is running stale code.
REQUIRED_PAID_STATE_FIELDS = (
    'last_product_id',
    'last_applied_at',
    'monthly_allowance',
    'max_balance_cap',
    'credits_consumed_this_cycle',
)

# Known-good product ids from PRODUCT_CREDIT_MAP.
PRODUCTS = {
    'walk-in':    ('bodybound_1499_1m_3d', 125),
    'booked-out': ('bodybound_2999_1m_3d', 500),
    'the-shop':   ('bodybound_9999_1m_3d', 1500),
}


@pytest.fixture
def api():
    return httpx.Client(base_url=API_URL, timeout=20.0)


def _demo_session(api):
    r = api.post('/api/auth/demo-login')
    assert r.status_code == 200, r.text
    body = r.json()
    return body['user']['user_id'], body['session_token']


def _get_subscription(api, user_id):
    r = api.get(f'/api/admin/user-lookup?user_id={user_id}')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get('found') is True, f'user_lookup did not find {user_id}: {body}'
    sub = body.get('subscription') or {}
    return sub


def _assert_paid_state_fields(sub, *, expected_product_id, source_label):
    missing = [f for f in REQUIRED_PAID_STATE_FIELDS if sub.get(f) in (None, '')]
    assert not missing, (
        f'Stale backend deploy detected for {source_label}. '
        f'Subscription doc is missing rewrite fields: {missing}. '
        f'Full doc keys: {sorted(sub.keys())}'
    )
    # last_product_id must match the product we just applied.
    assert sub['last_product_id'] == expected_product_id, (
        f'{source_label}: last_product_id mismatch. '
        f"Expected {expected_product_id!r}, got {sub.get('last_product_id')!r}"
    )


# ---------------------------------------------------------------------------
# /api/subscription/sync  → FRONTEND_SYNC
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('tier,product', list(PRODUCTS.items()))
def test_frontend_sync_writes_rewrite_fields(api, tier, product):
    """Calling /api/subscription/sync must populate every field from the
    rewrite. This is the frontend-authoritative paid-state writer and is the
    path PaywallScreen.tsx uses right after Purchases.purchasePackage()."""
    product_id, expected_credits = product
    user_id, token = _demo_session(api)

    r = api.post(
        '/api/subscription/sync',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'product_id': product_id,
            'is_trial': False,
            'revenuecat_customer_id': 'rc_deploy_sanity_frontend_sync',
        },
    )
    assert r.status_code == 200, r.text

    sub = _get_subscription(api, user_id)

    # Behaviour sanity (already covered elsewhere — kept as a guardrail).
    assert sub.get('tier') == tier, sub
    assert sub.get('available_credits') == expected_credits, sub
    assert sub.get('is_trial') is False, sub
    assert sub.get('last_event') == 'FRONTEND_SYNC', sub

    # The thing this file exists to prove: rewrite fields are live.
    _assert_paid_state_fields(
        sub,
        expected_product_id=product_id,
        source_label=f'FRONTEND_SYNC [{tier}]',
    )
    # max_balance_cap must be exactly 2x monthly_allowance (rollover policy).
    assert sub['max_balance_cap'] == sub['monthly_allowance'] * 2, sub
    # Freshly applied cycle must start at zero consumed.
    assert sub['credits_consumed_this_cycle'] == 0, sub


# ---------------------------------------------------------------------------
# RevenueCat INITIAL_PURCHASE webhook
# ---------------------------------------------------------------------------
def test_initial_purchase_webhook_writes_rewrite_fields(api):
    """INITIAL_PURCHASE must go through apply_paid_subscription_state and
    therefore populate the new audit fields."""
    user_id, _ = _demo_session(api)
    product_id, expected_credits = PRODUCTS['booked-out']

    r = api.post(
        '/api/webhooks/revenuecat',
        json={
            'event': {
                'type': 'INITIAL_PURCHASE',
                'app_user_id': user_id,
                'product_id': product_id,
                'period_type': 'NORMAL',
            },
        },
    )
    assert r.status_code == 200, r.text

    sub = _get_subscription(api, user_id)
    assert sub.get('tier') == 'booked-out', sub
    assert sub.get('available_credits') == expected_credits, sub
    assert sub.get('last_event') == 'INITIAL_PURCHASE', sub

    _assert_paid_state_fields(
        sub,
        expected_product_id=product_id,
        source_label='INITIAL_PURCHASE',
    )


# ---------------------------------------------------------------------------
# RevenueCat RENEWAL webhook
# ---------------------------------------------------------------------------
def test_renewal_webhook_writes_rewrite_fields(api):
    """RENEWAL must also flow through apply_paid_subscription_state and
    refresh all rewrite audit fields (last_applied_at in particular).

    NOTE (May 2026 rollover policy): RENEWAL is now rollover-aware. Demo user
    seeded with full allowance (125) + RENEWAL adds another 125, capped at
    250 (2× walk-in allowance). Audit fields must still be stamped.
    """
    import uuid as _uuid
    user_id, _ = _demo_session(api)
    product_id, expected_credits = PRODUCTS['walk-in']
    rollover_cap = expected_credits * 2  # 250 for walk-in
    evt_id = f'sanity_renewal_evt_{_uuid.uuid4().hex[:12]}'

    r = api.post(
        '/api/webhooks/revenuecat',
        json={
            'event': {
                'type': 'RENEWAL',
                'app_user_id': user_id,
                'product_id': product_id,
                'period_type': 'NORMAL',
                'id': evt_id,
            },
        },
    )
    assert r.status_code == 200, r.text

    sub = _get_subscription(api, user_id)
    assert sub.get('tier') == 'walk-in', sub
    # Either rolled over to cap (250) or partial rollover, but NEVER below
    # the monthly allowance (125) — that would be a regression.
    assert sub.get('available_credits') >= expected_credits, sub
    assert sub.get('available_credits') <= rollover_cap, sub
    assert sub.get('last_event') == 'RENEWAL', sub

    _assert_paid_state_fields(
        sub,
        expected_product_id=product_id,
        source_label='RENEWAL',
    )


# ---------------------------------------------------------------------------
# RevenueCat TRANSFER webhook — log-only, must NOT mutate paid state, and
# must stamp last_transfer_at (new rewrite field).
# ---------------------------------------------------------------------------
def test_transfer_webhook_does_not_mutate_and_stamps_audit_field(api):
    user_id, token = _demo_session(api)

    # 1. Seed a known paid state via frontend sync.
    seed_product = PRODUCTS['booked-out'][0]
    r = api.post(
        '/api/subscription/sync',
        headers={'Authorization': f'Bearer {token}'},
        json={
            'product_id': seed_product,
            'is_trial': False,
            'revenuecat_customer_id': 'rc_deploy_sanity_seed',
        },
    )
    assert r.status_code == 200, r.text
    before = _get_subscription(api, user_id)

    # 2. Fire TRANSFER with a DIFFERENT product id to tempt the old code into
    #    overwriting. A non-stale deploy MUST ignore this for state writes.
    r = api.post(
        '/api/webhooks/revenuecat',
        json={
            'event': {
                'type': 'TRANSFER',
                'app_user_id': 'anon_would_be_overwriter',
                'transferred_from': ['anon_would_be_overwriter'],
                'transferred_to': [user_id],
                'product_id': PRODUCTS['walk-in'][0],  # tempt the downgrade
            },
        },
    )
    assert r.status_code == 200, r.text

    after = _get_subscription(api, user_id)

    # Paid state must be preserved verbatim.
    for field in ('tier', 'available_credits', 'is_trial', 'monthly_allowance',
                  'max_balance_cap', 'last_product_id'):
        assert after.get(field) == before.get(field), (
            f'TRANSFER illegally mutated {field}: before={before.get(field)!r} '
            f'after={after.get(field)!r}'
        )

    # last_event must NOT have been flipped to 'TRANSFER' — paid events are
    # the only legitimate source of last_event writes.
    assert after.get('last_event') == before.get('last_event'), (
        f'TRANSFER illegally rewrote last_event: '
        f'before={before.get("last_event")!r} after={after.get("last_event")!r}'
    )

    # New audit field must be stamped by the rewrite.
    assert after.get('last_transfer_at'), (
        'Stale backend deploy detected for TRANSFER: last_transfer_at was not '
        f'stamped. Full doc keys: {sorted(after.keys())}'
    )
