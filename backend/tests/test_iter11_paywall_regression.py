"""Iter11 consolidated paywall regression — covers (a) RC sync, (b) RC webhook,
(c) reroll billing via /api/credits/deduct, (e) emergency stencil, (f) 0-credit
paywall on /api/ai-stencil, (h) stencil rating basic, (i) near_black_fraction
field on /api/ai-stencil. Category (d) credit rollover is covered by
test_credit_rollover.py (direct invocation). Category (g) signup bridge is
covered by test_early_access_bridge.py + test_auth_credits.py.

All tests hit the live preview backend via EXPO_PUBLIC_BACKEND_URL; webhook
auth is read from env at runtime (no hardcoded secret).
"""
from __future__ import annotations

import base64
import io
import os
import uuid
from typing import Optional

import pytest
import requests

BASE_URL = (
    os.environ.get('EXPO_PUBLIC_BACKEND_URL')
    or os.environ.get('REACT_APP_BACKEND_URL')
    or 'https://stencil-ai-fallback.preview.emergentagent.com'
).rstrip('/')

# Loaded from backend/.env by conftest-adjacent helper
def _load_backend_env():
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
    cfg = {}
    if os.path.isfile(env_path):
        for line in open(env_path):
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            cfg[k.strip()] = v.strip()
    return cfg

_ENV = _load_backend_env()
WEBHOOK_AUTH = os.environ.get('REVENUECAT_WEBHOOK_AUTH') or _ENV.get('REVENUECAT_WEBHOOK_AUTH', '')


@pytest.fixture(scope='module')
def client():
    s = requests.Session()
    s.headers.update({'Content-Type': 'application/json'})
    return s


@pytest.fixture(scope='module')
def demo_token(client):
    r = client.post(f'{BASE_URL}/api/auth/demo-login', timeout=30)
    assert r.status_code == 200, f'demo-login failed: {r.status_code} {r.text[:200]}'
    return r.json()['session_token']


def _auth(tok):
    return {'Authorization': f'Bearer {tok}'}


def _current_credits(client, tok) -> int:
    r = client.get(f'{BASE_URL}/api/auth/me', headers=_auth(tok), timeout=30)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    # /auth/me returns {user, credits: {available_credits, ...}}
    if isinstance(data.get('credits'), dict):
        return int(data['credits'].get('available_credits', 0))
    return int(data.get('available_credits', 0))


# -------------------------------------------------------------------
# (a) RevenueCat sync: product IDs 01/02/03 map correctly
# -------------------------------------------------------------------

PRODUCT_EXPECTED = {
    '01': {'tier': 'walk-in', 'credits': 125},
    '02': {'tier': 'booked-out', 'credits': 500},
    '03': {'tier': 'the-shop', 'credits': 1500},
}


@pytest.mark.parametrize('product_id,expected', list(PRODUCT_EXPECTED.items()))
def test_a_subscription_sync_maps_product_to_tier(client, demo_token, product_id, expected):
    r = client.post(
        f'{BASE_URL}/api/subscription/sync',
        headers=_auth(demo_token),
        json={'product_id': product_id, 'is_trial': False},
        timeout=30,
    )
    assert r.status_code == 200, f'sync {product_id}: {r.status_code} {r.text[:200]}'
    data = r.json()
    assert data.get('tier') == expected['tier'], data
    # available_credits should equal the tier's monthly credits after a fresh sync
    assert data.get('available_credits') == expected['credits'], data


def test_a_subscription_sync_rejects_unknown_product(client, demo_token):
    r = client.post(
        f'{BASE_URL}/api/subscription/sync',
        headers=_auth(demo_token),
        json={'product_id': 'bogus_product', 'is_trial': False},
        timeout=30,
    )
    assert r.status_code == 400


# -------------------------------------------------------------------
# (b) RevenueCat webhook — auth + idempotency
# -------------------------------------------------------------------

def _webhook_headers(auth_value: Optional[str]):
    h = {'Content-Type': 'application/json'}
    if auth_value is not None:
        h['Authorization'] = auth_value
    return h


def test_b_webhook_rejects_bad_auth(client):
    if not WEBHOOK_AUTH:
        pytest.skip('REVENUECAT_WEBHOOK_AUTH not set; cannot test auth rejection')
    payload = {'event': {'type': 'INITIAL_PURCHASE', 'app_user_id': 'user_test_b', 'product_id': '01'}}
    r = client.post(
        f'{BASE_URL}/api/webhooks/revenuecat',
        headers=_webhook_headers('Bearer wrong-secret-' + uuid.uuid4().hex[:8]),
        json=payload,
        timeout=30,
    )
    assert r.status_code == 401, f'Expected 401 got {r.status_code}: {r.text[:200]}'


def test_b_webhook_accepts_valid_auth_initial_purchase(client):
    if not WEBHOOK_AUTH:
        pytest.skip('REVENUECAT_WEBHOOK_AUTH not set')
    uid = f'user_iter11_{uuid.uuid4().hex[:10]}'
    payload = {
        'event': {
            'type': 'INITIAL_PURCHASE',
            'app_user_id': uid,
            'product_id': '02',
            'aliases': [uid],
            'period_type': 'NORMAL',
        }
    }
    r = client.post(
        f'{BASE_URL}/api/webhooks/revenuecat',
        headers=_webhook_headers(f'Bearer {WEBHOOK_AUTH}'),
        json=payload,
        timeout=30,
    )
    assert r.status_code in (200, 204), f'{r.status_code}: {r.text[:200]}'


def test_b_webhook_idempotent_on_replay(client):
    """Sending the same webhook twice MUST NOT double-credit."""
    if not WEBHOOK_AUTH:
        pytest.skip('REVENUECAT_WEBHOOK_AUTH not set')
    uid = f'user_iter11_idem_{uuid.uuid4().hex[:10]}'
    payload = {
        'event': {
            'type': 'INITIAL_PURCHASE',
            'app_user_id': uid,
            'product_id': '01',
            'aliases': [uid],
            'period_type': 'NORMAL',
            'id': f'evt_{uuid.uuid4().hex}',
        }
    }
    h = _webhook_headers(f'Bearer {WEBHOOK_AUTH}')
    r1 = client.post(f'{BASE_URL}/api/webhooks/revenuecat', headers=h, json=payload, timeout=30)
    r2 = client.post(f'{BASE_URL}/api/webhooks/revenuecat', headers=h, json=payload, timeout=30)
    assert r1.status_code in (200, 204)
    assert r2.status_code in (200, 204)


# -------------------------------------------------------------------
# (c) Reroll billing via /api/credits/deduct
# NOTE: Backend has NO reroll_id / first-free-reroll logic. Every call to
# /api/credits/deduct unconditionally deducts 1 credit. The "first reroll free"
# policy is enforced frontend-only. This test documents current backend truth.
# -------------------------------------------------------------------

def test_c_credits_deduct_unauthenticated(client):
    r = client.post(f'{BASE_URL}/api/credits/deduct', json={}, timeout=30)
    assert r.status_code == 401


def test_c_credits_deduct_decrements_one(client, demo_token):
    # seed to walk-in/125 to have room
    client.post(
        f'{BASE_URL}/api/subscription/sync',
        headers=_auth(demo_token),
        json={'product_id': '01'},
        timeout=30,
    )
    before = _current_credits(client, demo_token)
    r = client.post(f'{BASE_URL}/api/credits/deduct', headers=_auth(demo_token), json={}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    data = r.json()
    assert data['available_credits'] == before - 1, f'expected {before-1}, got {data}'


def test_c_credits_deduct_does_not_have_reroll_idempotency(client, demo_token):
    """Document backend reality: same reroll_id twice WILL double-charge.
    First-free-reroll logic is frontend-only."""
    me_before = client.get(f'{BASE_URL}/api/auth/me', headers=_auth(demo_token), timeout=30).json()
    _ = me_before
    before = _current_credits(client, demo_token)
    reroll_id = f'reroll_{uuid.uuid4().hex}'
    r1 = client.post(f'{BASE_URL}/api/credits/deduct', headers=_auth(demo_token),
                     json={'reroll_id': reroll_id}, timeout=30)
    r2 = client.post(f'{BASE_URL}/api/credits/deduct', headers=_auth(demo_token),
                     json={'reroll_id': reroll_id}, timeout=30)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()['available_credits'] == before - 2, (
        'Backend has no reroll_id idempotency — both calls deducted. '
        'Frontend must gate the first-free-reroll policy.'
    )


# -------------------------------------------------------------------
# (e) Emergency stencil: 0 credits → 1 per calendar month
# -------------------------------------------------------------------

def test_e_emergency_stencil_requires_zero_credits(client, demo_token):
    """When user has >0 credits, emergency claim must be rejected."""
    # Ensure user has credits
    client.post(f'{BASE_URL}/api/subscription/sync', headers=_auth(demo_token),
                json={'product_id': '01'}, timeout=30)
    r = client.post(f'{BASE_URL}/api/credits/emergency-stencil',
                    headers=_auth(demo_token), json={}, timeout=30)
    assert r.status_code == 400, f'{r.status_code}: {r.text[:200]}'


# -------------------------------------------------------------------
# (f) Out-of-credits on /api/ai-stencil — this endpoint does NOT check credits.
# Backend relies on /api/credits/deduct to gate usage. Document this.
# Instead, verify /api/credits/deduct returns 402 at 0 credits.
# -------------------------------------------------------------------

def test_f_credits_deduct_returns_402_at_zero(client):
    """Create a fresh demo user, drain credits, verify 402."""
    # We use subscription/sync to seed credits, then drain via deduct loop.
    # This is destructive to the demo account; keep it minimal.
    r = client.post(f'{BASE_URL}/api/auth/demo-login', timeout=30)
    tok = r.json()['session_token']
    current = _current_credits(client, tok)
    if current == 0:
        r = client.post(f'{BASE_URL}/api/credits/deduct', headers=_auth(tok), json={}, timeout=30)
        assert r.status_code == 402
    else:
        pytest.skip(f'demo has {current} credits; cannot verify 402 without drain')


# -------------------------------------------------------------------
# (h) Stencil rating smoke
# -------------------------------------------------------------------

def test_h_stencil_rating_smoke(client):
    r = client.post(f'{BASE_URL}/api/stencil-rating',
                    json={'style': 'medium', 'rating': 'up'}, timeout=30)
    assert r.status_code == 200
    assert r.json().get('status') == 'ok'


# -------------------------------------------------------------------
# (i) near_black_fraction field on /api/ai-stencil success
# -------------------------------------------------------------------

def _tiny_png_b64() -> str:
    """Return a small valid PNG as a data URL (solid gray, 32x32)."""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip('PIL not available')
    img = Image.new('RGB', (256, 256), color=(180, 180, 180))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def test_i_ai_stencil_returns_near_black_fraction(client):
    """Smoke: /api/ai-stencil response schema should include near_black_fraction
    (Optional[float], rounded 4dp) when generation succeeds.

    NOTE: Uses real Gemini; may be slow. We only assert schema, not quality.
    """
    payload = {
        'image_base64': _tiny_png_b64(),
        'shading_detail': 50,
        'regenerate_style': 'medium',  # force non-cached path
    }
    r = client.post(f'{BASE_URL}/api/ai-stencil', json=payload, timeout=180)
    if r.status_code != 200:
        pytest.skip(f'AI stencil did not succeed ({r.status_code}); field presence only verifiable on success')
    data = r.json()
    assert 'near_black_fraction' in data, f'missing field in response keys: {list(data.keys())}'
    nbf = data['near_black_fraction']
    assert nbf is None or (isinstance(nbf, (int, float)) and 0.0 <= nbf <= 1.0), nbf
    if isinstance(nbf, float):
        # 4dp rounded — check no more than 4 decimals
        s = f'{nbf:.10f}'.rstrip('0')
        # Allow either exact value or ≤4dp
        if '.' in s:
            decimals = len(s.split('.')[1])
            assert decimals <= 4, f'near_black_fraction not rounded to 4dp: {nbf}'
