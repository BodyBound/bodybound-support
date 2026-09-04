"""Regression tests for the first-call trial-expiration response mismatch fix.

Before the fix: `get_user_credits()` updated the DB to
`{tier: 'trial_expired', available_credits: 0}` but read `tier` from the
in-memory `sub` dict AFTER the update, returning stale `tier='trial'` and
`needs_subscription=false` on the very first call. Subsequent calls were
correct.

After the fix: the in-memory dict is synced immediately post-update so the
first call returns the correct `tier='trial_expired'` /
`needs_subscription=true`.

These tests exercise `/api/auth/me`, which is the frontend's entitlement
entrypoint (calls `get_user_credits()` internally).
"""
import os
import uuid
import pytest
import httpx
from datetime import datetime, timezone, timedelta
import jwt as pyjwt
from pymongo import MongoClient

API_URL = os.environ.get('BB_TEST_API_URL', 'http://localhost:8001')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'tattoo_stencil')
JWT_SECRET = os.environ.get(
    'JWT_SECRET',
    'body-bound-stencil-generator-jwt-secret-key-2026-secure',
)


def _make_token(user_id: str) -> str:
    payload = {
        'user_id': user_id,
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm='HS256')


@pytest.fixture(scope='module')
def client():
    return httpx.Client(base_url=API_URL, timeout=15.0)


@pytest.fixture
def db_ids():
    """Provide a Mongo handle + accumulator for cleanup."""
    c = MongoClient(MONGO_URL)
    db = c[DB_NAME]
    ids = []
    yield db, ids
    if ids:
        db.users.delete_many({'user_id': {'$in': ids}})
        db.subscriptions.delete_many({'user_id': {'$in': ids}})
    c.close()


def _seed(db, ids, sub_overrides=None):
    uid = f'test_expfix_{uuid.uuid4().hex[:12]}'
    now = datetime.now(timezone.utc)
    started = (now - timedelta(days=183)).isoformat()
    expired = (now - timedelta(days=180)).isoformat()
    db.users.insert_one({
        'user_id': uid,
        'email': f'{uid}@expfix.test',
        'apple_user_id': f'apple:{uid}',
        'name': 'Fixture',
        'created_at': started,
        'last_login': started,
    })
    doc = {
        'user_id': uid,
        'tier': 'trial',
        'is_trial': True,
        'available_credits': 10,
        'trial_start_date': started,
        'trial_expires_at': expired,
        'revenuecat_customer_id': None,
        'anti_abuse_email': f'{uid}@expfix.test',
        'anti_abuse_device_id': None,
        'anti_abuse_provider': f'apple:{uid}',
        'created_at': started,
    }
    if sub_overrides:
        doc.update(sub_overrides)
    db.subscriptions.insert_one(doc)
    ids.append(uid)
    return uid, doc


def _me(client, token):
    return client.get('/api/auth/me',
                      headers={'Authorization': f'Bearer {token}'})


# ─── The one true test the fix is for ────────────────────────────────

def test_first_call_returns_expired_state(client, db_ids):
    """Test #2 in the brief. Also covers #1 (seed shape) and #7 (no
    unrelated field mutation)."""
    db, ids = db_ids
    uid, seeded = _seed(db, ids)
    tok = _make_token(uid)

    # Sanity: DB pre-state is what test #1 requires.
    pre = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert pre['tier'] == 'trial'
    assert pre['available_credits'] == 10
    assert pre['is_trial'] is True
    exp_dt = datetime.fromisoformat(pre['trial_expires_at'].replace('Z', '+00:00'))
    assert exp_dt < datetime.now(timezone.utc)

    # First call — the fix says this must return the expired shape.
    r = _me(client, tok)
    assert r.status_code == 200, r.text
    body = r.json()
    creds = body['credits']
    assert creds['tier'] == 'trial_expired', \
        f"first-call tier still stale: {creds['tier']!r}"
    assert creds['available_credits'] == 0
    assert creds['needs_subscription'] is True

    # DB must also be updated (that's not new — it worked before too).
    post = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert post['tier'] == 'trial_expired'
    assert post['available_credits'] == 0

    # No unrelated field mutation (test #7).
    protected = ('is_trial', 'trial_start_date', 'trial_expires_at',
                 'revenuecat_customer_id', 'anti_abuse_email',
                 'anti_abuse_device_id', 'anti_abuse_provider',
                 'created_at', 'user_id')
    for k in protected:
        assert post.get(k) == seeded.get(k), \
            f'protected field {k!r} drifted: {seeded.get(k)!r} → {post.get(k)!r}'


def test_second_call_is_idempotent(client, db_ids):
    """Test #3. After the first call flips the record, a second call must
    return the identical entitlement state and must not re-write."""
    db, ids = db_ids
    uid, _ = _seed(db, ids)
    tok = _make_token(uid)

    r1 = _me(client, tok)
    assert r1.status_code == 200
    c1 = r1.json()['credits']

    # Snapshot the DB *after* the first call.
    mid = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})

    r2 = _me(client, tok)
    assert r2.status_code == 200
    c2 = r2.json()['credits']
    assert c1 == c2, f'entitlement diverged between calls:\n c1={c1}\n c2={c2}'

    # DB unchanged between call 1 and call 2.
    after2 = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert after2 == mid, 'DB re-mutated on the second call'


def test_unexpired_trial_untouched(client, db_ids):
    """Test #4."""
    db, ids = db_ids
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    uid, seeded = _seed(db, ids, {'trial_expires_at': future})
    tok = _make_token(uid)

    r = _me(client, tok)
    assert r.status_code == 200
    c = r.json()['credits']
    assert c['tier'] == 'trial', \
        'unexpired trial was incorrectly normalised'
    assert c['available_credits'] == 10
    assert c['needs_subscription'] is False

    post = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert post['tier'] == 'trial'
    assert post['available_credits'] == 10
    assert post['trial_expires_at'] == future


def test_paid_subscription_untouched(client, db_ids):
    """Test #5."""
    db, ids = db_ids
    uid, seeded = _seed(db, ids, {
        'tier': 'walk-in',
        'is_trial': False,
        'available_credits': 100,
        'trial_expires_at': None,     # not applicable
    })
    tok = _make_token(uid)

    r = _me(client, tok)
    assert r.status_code == 200
    c = r.json()['credits']
    assert c['tier'] == 'walk-in'
    assert c['available_credits'] == 100
    assert c['needs_subscription'] is False

    post = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert post['tier'] == 'walk-in'
    assert post['available_credits'] == 100


def test_paywall_bypass_untouched(client, db_ids):
    """Test #6."""
    db, ids = db_ids
    uid, seeded = _seed(db, ids, {
        'tier': 'paywall_bypass',
        'is_trial': False,
        'available_credits': 10,
        'trial_expires_at': None,
    })
    tok = _make_token(uid)

    r = _me(client, tok)
    assert r.status_code == 200
    c = r.json()['credits']
    assert c['tier'] == 'paywall_bypass'
    assert c['available_credits'] == 10
    assert c['needs_subscription'] is False

    post = db.subscriptions.find_one({'user_id': uid}, {'_id': 0})
    assert post['tier'] == 'paywall_bypass'
    assert post['available_credits'] == 10


def test_generation_blocked_after_first_call_expiration(client, db_ids):
    """Test #8. Even with the fix, the natural-expiration path must still
    block generation (available_credits=0 keeps the credit gate closed
    exactly as before)."""
    db, ids = db_ids
    uid, seeded = _seed(db, ids)
    tok = _make_token(uid)

    # Fire the expiration via /api/auth/me.
    r_me = _me(client, tok)
    assert r_me.status_code == 200
    assert r_me.json()['credits']['available_credits'] == 0
    assert r_me.json()['credits']['needs_subscription'] is True

    # Now try to deduct a credit — must be rejected.
    r_ded = client.post(
        '/api/credits/deduct',
        headers={'Authorization': f'Bearer {tok}'},
        json={'amount': 1},
    )
    assert r_ded.status_code in (400, 402, 403), \
        f'expected deduct to be rejected, got HTTP {r_ded.status_code}: {r_ded.text}'


def test_batch_d_endpoint_still_semantic_parity(client, db_ids):
    """Regression: the natural-expiration side-effect and the Batch D admin
    endpoint must still land the same subscription in the same shape."""
    db, ids = db_ids
    # Two identical fixtures.
    uid_nat, doc_nat = _seed(db, ids)
    uid_adm, _ = _seed(db, ids, {
        'trial_expires_at': doc_nat['trial_expires_at'],
        'trial_start_date': doc_nat['trial_start_date'],
        'created_at': doc_nat['created_at'],
    })

    # Natural path: user hits /api/auth/me.
    tok_nat = _make_token(uid_nat)
    r = _me(client, tok_nat)
    assert r.status_code == 200

    # Admin path: dry_run=false via the Batch D endpoint. We need admin
    # auth for that; login as the admin fixture.
    admin_r = client.post('/api/admin-auth/login', json={
        'email': os.environ.get('BB_ADMIN_EMAIL', 'bodyboundstencil@yahoo.com'),
        'password': os.environ.get('BB_ADMIN_PW', 'Body.Bound.Admin.72410'),
    })
    assert admin_r.status_code == 200
    admin_tok = admin_r.json()['token']

    adm = client.post(
        '/api/admin-tool/action/normalize-expired-trial',
        headers={'Authorization': f'Bearer {admin_tok}'},
        json={
            'user_id': uid_adm,
            'expected_trial_expires_at': doc_nat['trial_expires_at'],
            'cleanup_batch_id': 'TEST-PARITY',
            'dry_run': False,
        },
    )
    assert adm.status_code == 200, adm.text
    assert adm.json()['status'] == 'changed'

    # Both post-states must be structurally identical.
    a = db.subscriptions.find_one({'user_id': uid_nat}, {'_id': 0})
    b = db.subscriptions.find_one({'user_id': uid_adm}, {'_id': 0})
    a.pop('user_id'); b.pop('user_id')
    a.pop('anti_abuse_email', None); b.pop('anti_abuse_email', None)
    a.pop('anti_abuse_provider', None); b.pop('anti_abuse_provider', None)
    assert a == b, f'natural vs admin parity broke:\n natural={a}\n admin={b}'
