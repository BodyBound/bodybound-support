"""Tests for POST /admin-tool/action/cleanup-entitlement (Phase 2026-09-03).

Preservation-safe legacy entitlement cleanup. These tests DO NOT hit any
production data. They:
  1. Seed local preview MongoDB with disposable fixture users
  2. Call the endpoint via httpx against the preview backend
  3. Assert the endpoint mutated ONLY the approved fields and preserved
     all protected fields byte-for-byte
  4. Clean up the fixture users after each test

The endpoint's design invariants under test:
  • Only the allow-listed fields are ever written.
  • Preconditions are re-validated at execution time per user.
  • Invalid batch types are rejected.
  • The tier is hard-locked to 'expired' (no arbitrary target_tier param).
  • dry_run=true performs zero writes.
  • Users not matching batch preconditions are skipped, not forced.
"""
import os
import uuid
import pytest
import httpx
from datetime import datetime, timezone
from pymongo import MongoClient        # sync client for seed/teardown

API_URL = os.environ.get(
    'BB_TEST_API_URL',
    'https://stencil-ai-fallback.preview.emergentagent.com',
)
ADMIN_EMAIL = os.environ.get('BB_ADMIN_EMAIL', 'bodyboundstencil@yahoo.com')
ADMIN_PW = os.environ.get('BB_ADMIN_PW', 'Body.Bound.Admin.72410')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'tattoo_stencil')

PROTECTED = {
    'last_event', 'last_product_id', 'last_applied_at',
    'renewal_date', 'trial_expires_at', 'revenuecat_customer_id',
    'available_credits', 'credits_consumed_this_cycle',
    'user_id', 'created_at',
}


# ─── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def client():
    return httpx.Client(base_url=API_URL, timeout=20.0)


@pytest.fixture(scope='module')
def admin_token(client):
    r = client.post('/api/admin-auth/login',
                    json={'email': ADMIN_EMAIL, 'password': ADMIN_PW})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()['token']



@pytest.fixture
def cleanup_fixtures():
    """Sync pymongo client so seed/teardown never touch pytest-asyncio's
    event loop lifecycle. The endpoint under test still uses motor
    internally — the tests exercise that path via HTTP calls."""
    c = MongoClient(MONGO_URL)
    db = c[DB_NAME]
    ids: list[str] = []
    yield db, ids
    if ids:
        db.subscriptions.delete_many({'user_id': {'$in': ids}})
    c.close()


def _seed(db, ids, doc):
    """Insert a disposable subscription doc and track for teardown."""
    uid = f"test_cleanup_{uuid.uuid4().hex[:12]}"
    doc = {**doc, 'user_id': uid}
    db.subscriptions.insert_one(doc)
    ids.append(uid)
    return uid


def _call_endpoint(client, admin_token, body):
    return client.post(
        '/api/admin-tool/action/cleanup-entitlement',
        headers={'Authorization': f'Bearer {admin_token}'},
        json=body,
    )


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


# ─── 1. Input validation ─────────────────────────────────────────────────

def test_rejects_invalid_batch_type(client, admin_token):
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'not_a_real_batch',
        'cleanup_batch_id': 'X', 'user_ids': ['user_x'], 'dry_run': True,
    })
    assert r.status_code == 400
    assert 'batch_type' in r.text


def test_rejects_arbitrary_target_tier(client, admin_token):
    """Body cannot supply target_tier — extra fields are REJECTED (422),
    and the endpoint remains hard-locked to tier='expired' internally."""
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'X',
        'user_ids': ['user_x'],
        'target_tier': 'walk-in',     # UNKNOWN field → 422
        'dry_run': True,
    })
    assert r.status_code == 422, f"expected 422 for extra field, got {r.status_code} {r.text}"
    # Pydantic surfaces the offending field name in the error payload
    assert 'target_tier' in r.text or 'Extra inputs' in r.text or 'extra_forbidden' in r.text


def test_rejects_multiple_unknown_fields(client, admin_token):
    """Even multiple unknown fields must all be surfaced by strict validation."""
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'X', 'user_ids': ['user_x'], 'dry_run': True,
        'target_tier': 'walk-in', 'force': True, 'zero_credits': True,
    })
    assert r.status_code == 422


def test_rejects_typo_in_field_name(client, admin_token):
    """Common typo scenario — 'user_ids' -> 'userids' must not be silently accepted."""
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'X', 'userids': ['user_x'], 'dry_run': True,
    })
    # Either 422 (extra field 'userids') or 400 (missing required 'user_ids')
    assert r.status_code in (400, 422)


def test_rejects_empty_user_ids(client, admin_token):
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'X', 'user_ids': [], 'dry_run': True,
    })
    assert r.status_code == 400


def test_rejects_missing_batch_id(client, admin_token):
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'user_ids': ['user_x'], 'dry_run': True,
    })
    # Pydantic surfaces missing required field as 422; hand-rolled validators
    # earlier raised 400. Accept either — both mean 'invalid request'.
    assert r.status_code in (400, 422)


def test_requires_admin_auth(client):
    r = client.post('/api/admin-tool/action/cleanup-entitlement',
                    json={'batch_type': 'legacy_trial_no_rc_entitlement',
                          'cleanup_batch_id': 'X', 'user_ids': ['x']})
    assert r.status_code == 401


# ─── 2. Dry run performs zero writes ─────────────────────────────────────

async def test_dry_run_writes_nothing(client, admin_token, cleanup_fixtures):
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], {
        'tier': 'trial', 'is_trial': True, 'available_credits': 5,
        'revenuecat_customer_id': None, 'last_event': None,
    })
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'DRYRUN', 'user_ids': [uid],
        'clear_is_trial': True, 'dry_run': True,
    })
    assert r.status_code == 200
    assert r.json()['status'] == 'dry_run'
    after = cleanup_fixtures[0].subscriptions.find_one({'user_id': uid})
    assert after['tier'] == 'trial'
    assert after['is_trial'] is True
    assert 'admin_cleanup_reason' not in after


# ─── 3. Batch A: legacy_trial_no_rc_entitlement ──────────────────────────

async def test_batch_A_happy_path_preserves_all_protected(client, admin_token, cleanup_fixtures):
    pre = {
        'tier': 'trial', 'is_trial': True,
        'available_credits': 42, 'credits_consumed_this_cycle': 7,
        'revenuecat_customer_id': None, 'last_event': None,
        'last_product_id': None, 'last_applied_at': None,
        'trial_expires_at': '2026-04-10T00:00:00+00:00',
        'renewal_date': None,
        'created_at': '2026-03-10T00:00:00+00:00',
    }
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], pre)
    before = cleanup_fixtures[0].subscriptions.find_one({'user_id': uid})
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'BB-CLEANUP-2026-09-03-A',
        'user_ids': [uid], 'clear_is_trial': True, 'dry_run': False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data['status'] == 'executed'
    assert data['changed'] == 1 and data['skipped'] == 0 and not data['errors']

    after = cleanup_fixtures[0].subscriptions.find_one({'user_id': uid})
    # Approved mutations
    assert after['tier'] == 'expired'
    assert after['is_trial'] is False
    assert after['admin_cleanup_reason'] == 'legacy_trial_no_rc_entitlement'
    assert after['cleanup_batch_id'] == 'BB-CLEANUP-2026-09-03-A'
    assert after['pre_cleanup_tier'] == 'trial'
    assert after['pre_cleanup_is_trial'] is True
    # Every protected field byte-for-byte (compared to the real seeded state,
    # not the fixture literal — the fixture doesn't include user_id).
    for f in PROTECTED:
        assert after.get(f) == before.get(f), (
            f"protected field {f!r} drift: {before.get(f)!r} → {after.get(f)!r}"
        )


async def test_batch_A_skips_user_with_rc_id(client, admin_token, cleanup_fixtures):
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], {
        'tier': 'trial', 'is_trial': True, 'available_credits': 5,
        'revenuecat_customer_id': '$RCAnonymousID:abc123',  # RC-linked → skip
        'last_event': None,
    })
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'X', 'user_ids': [uid],
        'clear_is_trial': True, 'dry_run': False,
    })
    data = r.json()
    assert data['changed'] == 0 and data['skipped'] == 1
    assert 'revenuecat_customer_id_present' in data['per_user'][0]['reason']
    after = cleanup_fixtures[0].subscriptions.find_one({'user_id': uid})
    assert after['tier'] == 'trial'
    assert after['revenuecat_customer_id'] == '$RCAnonymousID:abc123'


async def test_batch_A_skips_active_purchase_family(client, admin_token, cleanup_fixtures):
    """Even if tier='trial' and rc_id missing, active RC event → skip."""
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], {
        'tier': 'trial', 'is_trial': True, 'available_credits': 5,
        'revenuecat_customer_id': None,
        'last_event': 'INITIAL_PURCHASE',  # active RC → skip
    })
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'X', 'user_ids': [uid],
        'clear_is_trial': True, 'dry_run': False,
    })
    data = r.json()
    assert data['changed'] == 0 and data['skipped'] == 1
    assert 'active_rc_event_INITIAL_PURCHASE' in data['per_user'][0]['reason']


# ─── 4. Batch B: stale_is_trial_rc_expired ───────────────────────────────

async def test_batch_B_expires_stale_walkin_trial(client, admin_token, cleanup_fixtures):
    pre = {
        'tier': 'walk-in', 'is_trial': True,
        'available_credits': 87, 'credits_consumed_this_cycle': 5,
        'revenuecat_customer_id': '$RCAnonymousID:def456',
        'last_event': 'EXPIRATION',
        'last_product_id': '02',
        'last_applied_at': '2026-07-01T00:00:00+00:00',
        'trial_expires_at': '2026-06-30T00:00:00+00:00',
        'renewal_date': '2026-08-01T00:00:00+00:00',
        'created_at': '2026-06-01T00:00:00+00:00',
    }
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], pre)
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'stale_is_trial_rc_expired',
        'cleanup_batch_id': 'BB-CLEANUP-2026-09-03-B',
        'user_ids': [uid], 'clear_is_trial': True, 'dry_run': False,
    })
    data = r.json()
    assert data['changed'] == 1 and data['skipped'] == 0
    after = cleanup_fixtures[0].subscriptions.find_one({'user_id': uid})
    # THE CRITICAL FIX: tier walked from 'walk-in' → 'expired' (not left as walk-in)
    assert after['tier'] == 'expired'
    assert after['is_trial'] is False
    # RC evidence preserved
    assert after['last_event'] == 'EXPIRATION'
    assert after['last_product_id'] == '02'
    assert after['revenuecat_customer_id'] == '$RCAnonymousID:def456'
    # Credits preserved
    assert after['available_credits'] == 87
    assert after['credits_consumed_this_cycle'] == 5


async def test_batch_B_skips_without_expiration_evidence(client, admin_token, cleanup_fixtures):
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], {
        'tier': 'walk-in', 'is_trial': True,
        'available_credits': 10, 'last_event': 'RENEWAL',  # not RC_DEAD
        'revenuecat_customer_id': 'rc_x',
    })
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'stale_is_trial_rc_expired',
        'cleanup_batch_id': 'X', 'user_ids': [uid], 'clear_is_trial': True,
        'dry_run': False,
    })
    data = r.json()
    assert data['changed'] == 0 and data['skipped'] == 1
    after = cleanup_fixtures[0].subscriptions.find_one({'user_id': uid})
    assert after['tier'] == 'walk-in'  # unchanged


# ─── 5. Batch C: legacy_bypass_no_rc_entitlement ─────────────────────────

async def test_batch_C_bypass_with_no_rc_link(client, admin_token, cleanup_fixtures):
    pre = {
        'tier': 'paywall_bypass', 'is_trial': False,
        'available_credits': 8, 'credits_consumed_this_cycle': 2,
        'revenuecat_customer_id': None,
        'last_event': 'PAYWALL_BYPASS',
        'bypass_granted_at': '2026-04-11T00:00:00+00:00',
        'created_at': '2026-04-11T00:00:00+00:00',
    }
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], pre)
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_bypass_no_rc_entitlement',
        'cleanup_batch_id': 'BB-CLEANUP-2026-09-03-C',
        'user_ids': [uid], 'clear_is_trial': False, 'dry_run': False,
    })
    data = r.json()
    assert data['changed'] == 1 and data['skipped'] == 0
    after = cleanup_fixtures[0].subscriptions.find_one({'user_id': uid})
    assert after['tier'] == 'expired'
    assert after['is_trial'] is False  # was already false; endpoint didn't touch it
    # Preserved
    assert after['last_event'] == 'PAYWALL_BYPASS'  # internal event, still preserved
    assert after['bypass_granted_at'] == '2026-04-11T00:00:00+00:00'
    assert after['available_credits'] == 8
    assert after['credits_consumed_this_cycle'] == 2


async def test_batch_C_refuses_bypass_with_rc_link(client, admin_token, cleanup_fixtures):
    """RC-linked bypass users cannot be cleaned by the no-RC batch."""
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], {
        'tier': 'paywall_bypass', 'is_trial': False,
        'available_credits': 5,
        'revenuecat_customer_id': '$RCAnonymousID:xyz',  # RC-linked → skip
        'last_event': None,
    })
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_bypass_no_rc_entitlement',
        'cleanup_batch_id': 'X', 'user_ids': [uid], 'dry_run': False,
    })
    data = r.json()
    assert data['changed'] == 0 and data['skipped'] == 1
    assert 'revenuecat_customer_id_present' in data['per_user'][0]['reason']


async def test_batch_C_refuses_frontend_sync_event(client, admin_token, cleanup_fixtures):
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], {
        'tier': 'paywall_bypass', 'is_trial': False,
        'available_credits': 5, 'revenuecat_customer_id': None,
        'last_event': 'FRONTEND_SYNC',                  # → skip
    })
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_bypass_no_rc_entitlement',
        'cleanup_batch_id': 'X', 'user_ids': [uid], 'dry_run': False,
    })
    data = r.json()
    assert data['changed'] == 0 and data['skipped'] == 1
    assert 'frontend_sync_present' in data['per_user'][0]['reason']


# ─── 6. Cross-batch guarantees ───────────────────────────────────────────

async def test_mixed_cohort_partial_skip(client, admin_token, cleanup_fixtures):
    """3 users: 2 eligible for Batch A, 1 ineligible → 2 changed / 1 skipped."""
    good1 = _seed(cleanup_fixtures[0], cleanup_fixtures[1], {
        'tier': 'trial', 'is_trial': True, 'available_credits': 3,
        'revenuecat_customer_id': None, 'last_event': None,
    })
    good2 = _seed(cleanup_fixtures[0], cleanup_fixtures[1], {
        'tier': 'trial', 'is_trial': True, 'available_credits': 8,
        'revenuecat_customer_id': None, 'last_event': None,
    })
    bad = _seed(cleanup_fixtures[0], cleanup_fixtures[1], {
        'tier': 'walk-in', 'is_trial': False, 'available_credits': 100,
        'revenuecat_customer_id': 'rc_ok', 'last_event': 'RENEWAL',
    })
    r = _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'MIX',
        'user_ids': [good1, good2, bad], 'clear_is_trial': True,
        'dry_run': False,
    })
    data = r.json()
    assert data['attempted'] == 3
    assert data['changed'] == 2
    assert data['skipped'] == 1
    # bad user unchanged
    after_bad = cleanup_fixtures[0].subscriptions.find_one({'user_id': bad})
    assert after_bad['tier'] == 'walk-in'
    assert after_bad['available_credits'] == 100


async def test_protected_fields_are_bitwise_identical(client, admin_token, cleanup_fixtures):
    """One test that reads every protected field before and after and asserts strict equality."""
    pre = {
        'tier': 'trial', 'is_trial': True,
        'available_credits': 15, 'credits_consumed_this_cycle': 3,
        'revenuecat_customer_id': None,
        'last_event': None, 'last_product_id': None,
        'last_applied_at': '2026-03-01T12:34:56+00:00',
        'trial_expires_at': '2026-03-30T12:34:56+00:00',
        'renewal_date': '2026-04-30T12:34:56+00:00',
        'created_at': '2026-03-01T12:34:56+00:00',
    }
    uid = _seed(cleanup_fixtures[0], cleanup_fixtures[1], pre)
    before = cleanup_fixtures[0].subscriptions.find_one({'user_id': uid})
    _call_endpoint(client, admin_token, {
        'batch_type': 'legacy_trial_no_rc_entitlement',
        'cleanup_batch_id': 'BITWISE', 'user_ids': [uid],
        'clear_is_trial': True, 'dry_run': False,
    })
    after = cleanup_fixtures[0].subscriptions.find_one({'user_id': uid})
    for f in PROTECTED:
        assert before.get(f) == after.get(f), f"drift in {f}"
