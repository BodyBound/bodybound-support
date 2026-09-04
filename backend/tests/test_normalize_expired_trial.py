"""Tests for POST /admin-tool/action/normalize-expired-trial (Batch D — 2026-09-04).

Narrow admin action that mirrors the natural trial-expiration mutation from
`get_user_credits()` at server.py:3779-3782, guarded by exhaustive
compare-and-set predicates. Tests seed disposable fixture subscriptions
against the preview backend's local MongoDB, exercise the endpoint over
HTTP, then tear the fixtures down.

Invariants under test:
  1. Happy path — succeeds only for a matching expired 'trial' record and
     writes exactly {tier:'trial_expired', available_credits:0}.
  2. Refuses in-window (future) trial expiry.
  3. Refuses paid tiers (walk-in / booked-out / the-shop / the-shop-member).
  4. Refuses paywall_bypass.
  5. Refuses RC-linked accounts.
  6. Refuses drifted `available_credits` (not 10 anymore).
  7. Refuses drifted `trial_expires_at` (expected value differs).
  8. Refuses missing `trial_expires_at` (the ambiguous 6th trial shape).
  9. Refuses arbitrary extra params (Pydantic extra='forbid').
 10. dry_run=true performs zero writes.
 11. Semantic parity with natural expiration: post-state equals what
     get_user_credits() would produce on organic expiration.
"""
import os
import uuid
import pytest
import httpx
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

API_URL = os.environ.get(
    'BB_TEST_API_URL',
    'http://localhost:8001',
)
ADMIN_EMAIL = os.environ.get('BB_ADMIN_EMAIL', 'bodyboundstencil@yahoo.com')
ADMIN_PW = os.environ.get('BB_ADMIN_PW', 'Body.Bound.Admin.72410')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'tattoo_stencil')

BATCH_ID = 'TEST-BB-D-2026-09-04'

# Fields that must remain byte-identical between pre- and post- states.
PROTECTED_ON_WRITE = (
    'is_trial', 'trial_start_date', 'trial_expires_at',
    'revenuecat_customer_id', 'last_event', 'last_product_id',
    'renewal_date', 'anti_abuse_email', 'anti_abuse_device_id',
    'anti_abuse_provider', 'studio_team_id', 'created_at',
    'user_id',
)


@pytest.fixture(scope='module')
def client():
    return httpx.Client(base_url=API_URL, timeout=20.0)


@pytest.fixture(scope='module')
def admin_token(client):
    r = client.post('/api/admin-auth/login',
                    json={'email': ADMIN_EMAIL, 'password': ADMIN_PW})
    assert r.status_code == 200, f"admin login: {r.status_code} {r.text}"
    return r.json()['token']


@pytest.fixture
def seed_db():
    """Sync pymongo for seed/teardown so we don't need to juggle asyncio."""
    c = MongoClient(MONGO_URL)
    db = c[DB_NAME]
    ids: list[str] = []
    yield db, ids
    if ids:
        db.subscriptions.delete_many({'user_id': {'$in': ids}})
        db.users.delete_many({'user_id': {'$in': ids}})
    c.close()


def _mk_expired_trial(db, ids, **overrides):
    """Seed a subscription that looks exactly like the 5 Batch D targets:
    tier='trial', is_trial=True, credits=10, no RC, trial_expires_at 6 months ago."""
    uid = f"test_normd_{uuid.uuid4().hex[:12]}"
    expired_at = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
    started_at = (datetime.now(timezone.utc) - timedelta(days=183)).isoformat()
    doc = {
        'user_id': uid,
        'tier': 'trial',
        'is_trial': True,
        'available_credits': 10,
        'trial_start_date': started_at,
        'trial_expires_at': expired_at,
        'revenuecat_customer_id': None,
        'anti_abuse_provider': f'apple:{uid}',
        'created_at': started_at,
    }
    doc.update(overrides)
    db.subscriptions.insert_one(dict(doc))
    ids.append(uid)
    return uid, doc


def _payload(user_id, expected_exp, dry_run=True):
    return {
        'user_id': user_id,
        'expected_trial_expires_at': expected_exp,
        'cleanup_batch_id': BATCH_ID,
        'dry_run': dry_run,
    }


def _headers(token):
    return {'Authorization': f'Bearer {token}'}


# ─── Happy path ─────────────────────────────────────────────────────────

def test_dry_run_reports_would_change_and_writes_nothing(client, admin_token, seed_db):
    db, ids = seed_db
    uid, seeded = _mk_expired_trial(db, ids)

    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid, seeded['trial_expires_at'], dry_run=True),
                    headers=_headers(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['status'] == 'dry_run', data
    assert data['would_set'] == {'tier': 'trial_expired', 'available_credits': 0}

    after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after['tier'] == 'trial'
    assert after['available_credits'] == 10
    assert after['is_trial'] is True


def test_happy_path_changes_only_target_fields(client, admin_token, seed_db):
    db, ids = seed_db
    uid, seeded = _mk_expired_trial(db, ids)

    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid, seeded['trial_expires_at'], dry_run=False),
                    headers=_headers(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['status'] == 'changed', data
    assert data['matched_count'] == 1
    assert data['modified_count'] == 1
    assert data['drift'] == {}, f"unexpected drift: {data['drift']}"

    after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after['tier'] == 'trial_expired'
    assert after['available_credits'] == 0
    # Everything else must be byte-identical.
    for k in PROTECTED_ON_WRITE:
        assert after.get(k) == seeded.get(k), \
            f"protected field {k!r} changed: before={seeded.get(k)!r} after={after.get(k)!r}"


# ─── Precondition refusals ──────────────────────────────────────────────

def test_refuses_future_trial_expiry_via_request_validation(client, admin_token, seed_db):
    """Even if a caller supplies a future expected_trial_expires_at, the
    endpoint 400s before running any read."""
    future = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json={'user_id': 'user_doesnotmatter',
                          'expected_trial_expires_at': future,
                          'cleanup_batch_id': BATCH_ID,
                          'dry_run': True},
                    headers=_headers(admin_token))
    assert r.status_code == 400
    assert 'future' in r.text.lower()


def test_refuses_unexpired_trial_stored_state(client, admin_token, seed_db):
    """If the record itself has a future trial expiry (in-window trial),
    even a caller who correctly reports the future timestamp is 400'd
    by request validation. If the caller lies about the timestamp (past
    expected), the drift check catches it."""
    db, ids = seed_db
    future_exp = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    uid, seeded = _mk_expired_trial(db, ids, trial_expires_at=future_exp)

    # Caller supplies the (future) actual value → 400 at request layer.
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid, future_exp, dry_run=False),
                    headers=_headers(admin_token))
    assert r.status_code == 400, r.text

    # DB unchanged.
    after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after['tier'] == 'trial'
    assert after['available_credits'] == 10


def test_refuses_paid_tier(client, admin_token, seed_db):
    db, ids = seed_db
    for paid_tier in ('walk-in', 'booked-out', 'the-shop', 'the-shop-member'):
        expired_at = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
        uid, seeded = _mk_expired_trial(db, ids,
                                         tier=paid_tier,
                                         is_trial=False,
                                         trial_expires_at=expired_at)
        r = client.post('/api/admin-tool/action/normalize-expired-trial',
                        json=_payload(uid, seeded['trial_expires_at'], dry_run=False),
                        headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data['status'] == 'skipped', data
        assert any(f'tier_is_{paid_tier!r}' in reason for reason in data['reasons']), data
        after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
        assert after['tier'] == paid_tier
        assert after['available_credits'] == 10


def test_refuses_paywall_bypass(client, admin_token, seed_db):
    db, ids = seed_db
    uid, seeded = _mk_expired_trial(db, ids, tier='paywall_bypass', is_trial=False)
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid, seeded['trial_expires_at'], dry_run=False),
                    headers=_headers(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['status'] == 'skipped', data
    assert any("'paywall_bypass'" in reason for reason in data['reasons']), data
    after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after['tier'] == 'paywall_bypass'


def test_refuses_rc_linked(client, admin_token, seed_db):
    db, ids = seed_db
    uid, seeded = _mk_expired_trial(db, ids, revenuecat_customer_id='rc_customer_xxx')
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid, seeded['trial_expires_at'], dry_run=False),
                    headers=_headers(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['status'] == 'skipped', data
    assert any('revenuecat_customer_id_present' in reason for reason in data['reasons']), data
    after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after['revenuecat_customer_id'] == 'rc_customer_xxx'
    assert after['tier'] == 'trial'
    assert after['available_credits'] == 10


def test_refuses_drifted_credits(client, admin_token, seed_db):
    """Any account whose credits are not exactly 10 (e.g. partially spent)
    is refused — matches the observed pre-state of the 5 Batch D targets."""
    db, ids = seed_db
    uid, seeded = _mk_expired_trial(db, ids, available_credits=7)
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid, seeded['trial_expires_at'], dry_run=False),
                    headers=_headers(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['status'] == 'skipped', data
    assert any('available_credits_is_7' in reason for reason in data['reasons']), data
    after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after['tier'] == 'trial'
    assert after['available_credits'] == 7


def test_refuses_drifted_expected_trial_expires_at(client, admin_token, seed_db):
    """Caller supplies an expected timestamp that differs from what's on the
    record → skip (compare-and-set refuses drift)."""
    db, ids = seed_db
    uid, seeded = _mk_expired_trial(db, ids)
    # Off by 1 second.
    real = datetime.fromisoformat(seeded['trial_expires_at'].replace('Z', '+00:00'))
    fake_expected = (real - timedelta(seconds=1)).isoformat()
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid, fake_expected, dry_run=False),
                    headers=_headers(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['status'] == 'skipped', data
    assert any('trial_expires_at_drift' in reason for reason in data['reasons']), data
    after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after['tier'] == 'trial'
    assert after['available_credits'] == 10


def test_refuses_missing_trial_expiry_ambiguous_sixth(client, admin_token, seed_db):
    """Mirrors user_673ab0d5552a: tier='trial' with no trial_expires_at.
    Caller must supply *some* timestamp to satisfy request validation, but
    the precondition check surfaces the missing-field skip reason."""
    db, ids = seed_db
    uid, seeded = _mk_expired_trial(db, ids, trial_expires_at=None)
    fake_exp = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid, fake_exp, dry_run=False),
                    headers=_headers(admin_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['status'] == 'skipped', data
    assert any('trial_expires_at_missing' in reason for reason in data['reasons']), data
    assert any('trial_expires_at_drift' in reason for reason in data['reasons']), data
    after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after['tier'] == 'trial'


def test_rejects_extra_body_fields(client, admin_token, seed_db):
    """Pydantic extra='forbid' — no target_tier / credits overrides possible."""
    db, ids = seed_db
    uid, seeded = _mk_expired_trial(db, ids)
    payload = _payload(uid, seeded['trial_expires_at'], dry_run=False)
    payload['target_tier'] = 'walk-in'
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=payload,
                    headers=_headers(admin_token))
    assert r.status_code == 422, r.text
    after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after['tier'] == 'trial'


def test_requires_admin_auth(client, seed_db):
    db, ids = seed_db
    uid, seeded = _mk_expired_trial(db, ids)
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid, seeded['trial_expires_at'], dry_run=False))
    assert r.status_code == 401, r.text


# ─── Semantic parity ────────────────────────────────────────────────────

def test_semantic_parity_with_get_user_credits_natural_expiration(client, admin_token, seed_db):
    """Post-state after this endpoint == post-state after the natural
    expiration path in get_user_credits() (server.py:3779-3782)."""
    db, ids = seed_db

    # 1. Seed two identical expired trials.
    uid_a, seeded_a = _mk_expired_trial(db, ids)
    uid_b, seeded_b = _mk_expired_trial(db, ids)
    # Force identical timestamps so semantic parity is exact.
    same_exp = seeded_a['trial_expires_at']
    same_start = seeded_a['trial_start_date']
    same_created = seeded_a['created_at']
    db.subscriptions.update_one(
        {'user_id': uid_b},
        {'$set': {
            'trial_expires_at': same_exp,
            'trial_start_date': same_start,
            'created_at': same_created,
        }},
    )
    seeded_b['trial_expires_at'] = same_exp

    # 2. Run the endpoint on uid_a.
    r = client.post('/api/admin-tool/action/normalize-expired-trial',
                    json=_payload(uid_a, seeded_a['trial_expires_at'], dry_run=False),
                    headers=_headers(admin_token))
    assert r.status_code == 200 and r.json()['status'] == 'changed', r.text

    # 3. Simulate the natural expiration path directly (mirrors L3779-3782).
    db.subscriptions.update_one(
        {'user_id': uid_b},
        {'$set': {'available_credits': 0, 'tier': 'trial_expired'}}
    )

    # 4. Compare — the two rows must be structurally identical (both
    # post-states must have the same set of keys and same values across
    # every field). We compare all fields except user_id.
    a = db.subscriptions.find_one({'user_id': uid_a}, {'_id': 0})
    b = db.subscriptions.find_one({'user_id': uid_b}, {'_id': 0})
    a.pop('user_id'); b.pop('user_id')
    # anti_abuse_provider differs by construction (contains uid).
    a.pop('anti_abuse_provider', None); b.pop('anti_abuse_provider', None)
    assert a == b, f"semantic parity failed:\nA={a}\nB={b}"


def test_batch_of_five_matches_dry_run_all_eligible(client, admin_token, seed_db):
    """Simulate Batch D shape: 5 accounts, each with the exact target
    profile. In dry_run, all 5 return 'dry_run'/'would_set'."""
    db, ids = seed_db
    seeded = [_mk_expired_trial(db, ids) for _ in range(5)]

    results = []
    for uid, doc in seeded:
        r = client.post('/api/admin-tool/action/normalize-expired-trial',
                        json=_payload(uid, doc['trial_expires_at'], dry_run=True),
                        headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        results.append(r.json())

    for res in results:
        assert res['status'] == 'dry_run', res
        assert res['would_set'] == {'tier': 'trial_expired', 'available_credits': 0}
    # No writes performed.
    for uid, _ in seeded:
        after = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
        assert after['tier'] == 'trial'
        assert after['available_credits'] == 10
