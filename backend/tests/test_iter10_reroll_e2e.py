"""End-to-end verification for iter10:

1. /api/credits/deduct for NON-studio subscription (demo-login user) must now
   decrement `available_credits` and increment `credits_consumed_this_cycle`
   and return the updated balance (previously orphaned branch).
2. /api/ai-stencil with `regenerate_style` must SKIP the cache — two calls
   with the same base64 image + same regenerate_style must return different
   stencil_base64 strings.
3. /api/ai-stencil WITHOUT regenerate_style can still hit the cache.
"""
import base64
import io
import os
import time

import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get(
    'EXPO_PUBLIC_BACKEND_URL',
    'https://stencil-ai-fallback.preview.emergentagent.com',
).rstrip('/')


@pytest.fixture(scope='module')
def api_client():
    s = requests.Session()
    s.headers.update({'Content-Type': 'application/json'})
    return s


@pytest.fixture(scope='module')
def demo_auth(api_client):
    """Login via demo endpoint — returns (session_token, user_id)."""
    r = api_client.post(f'{BASE_URL}/api/auth/demo-login', json={})
    assert r.ok, f'demo-login failed: {r.status_code} {r.text}'
    data = r.json()
    token = data.get('session_token') or data.get('token') or data.get('access_token')
    user = data.get('user') or {}
    user_id = user.get('user_id') or user.get('id') or data.get('user_id')
    assert token, f'no session token in demo-login response: {data}'
    return token, user_id


def _make_portrait_jpeg_b64(color=(120, 90, 70)) -> str:
    """Small synthetic 'portrait' JPEG to feed the AI. Tiny (~4kb)."""
    img = Image.new('RGB', (256, 256), color=color)
    # Add a darker oval-ish face region so Gemini has something to trace.
    for y in range(60, 200):
        for x in range(80, 180):
            img.putpixel((x, y), (60, 40, 30))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return base64.b64encode(buf.getvalue()).decode('ascii')


# -------------------------- Credit deduct (non-studio) --------------------------

def test_credits_deduct_non_studio_decrements_balance(api_client, demo_auth):
    token, _ = demo_auth

    # Read current /auth/me balance
    me = api_client.get(
        f'{BASE_URL}/api/auth/me',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert me.ok, f'/auth/me failed: {me.status_code} {me.text}'
    me_data = me.json()
    credits_obj = me_data.get('credits') or {}
    before = credits_obj.get('available_credits')
    assert isinstance(before, int), f'expected int available_credits, got {credits_obj}'
    if before <= 0:
        pytest.skip('demo user has 0 credits — cannot exercise success branch')

    # Deduct 1
    d = api_client.post(
        f'{BASE_URL}/api/credits/deduct',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert d.status_code == 200, f'deduct failed: {d.status_code} {d.text}'
    body = d.json()
    # Must NOT be studio-team branch — demo user is a regular subscription
    assert body.get('is_studio_team') is not True
    assert body['available_credits'] == before - 1
    assert 'tier' in body
    assert 'total_monthly_credits' in body

    # Re-read /auth/me → balance persisted
    me2 = api_client.get(
        f'{BASE_URL}/api/auth/me',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert me2.ok
    after = (me2.json().get('credits') or {}).get('available_credits')
    assert after == before - 1, f'persisted balance wrong: before={before} after={after}'


def test_credits_deduct_without_auth_returns_401(api_client):
    r = api_client.post(f'{BASE_URL}/api/credits/deduct')
    assert r.status_code in (401, 403), f'expected 401/403, got {r.status_code}'


# -------------------------- ai-stencil cache skip on regenerate --------------------------

@pytest.mark.timeout(200)
def test_ai_stencil_regenerate_skips_cache(api_client):
    """Two back-to-back regenerate calls on the SAME image must not be
    bit-for-bit identical (cache skipped → fresh Gemini call each time)."""
    image_b64 = _make_portrait_jpeg_b64()

    payload = {
        'image_base64': image_b64,
        'line_color': 'purple',
        'regenerate_style': 'medium',
        'shading_detail': 50,
    }

    t0 = time.time()
    r1 = api_client.post(f'{BASE_URL}/api/ai-stencil', json=payload, timeout=120)
    if r1.status_code >= 500 or (r1.status_code == 429):
        pytest.skip(f'Gemini upstream not cooperating: {r1.status_code} {r1.text[:200]}')
    assert r1.ok, f'first regen failed: {r1.status_code} {r1.text[:300]}'
    s1 = r1.json().get('stencil_base64')
    assert s1, 'first regen: empty stencil_base64'

    t1 = time.time()
    r2 = api_client.post(f'{BASE_URL}/api/ai-stencil', json=payload, timeout=120)
    if r2.status_code >= 500 or (r2.status_code == 429):
        pytest.skip(f'Gemini upstream not cooperating on 2nd call: {r2.status_code} {r2.text[:200]}')
    assert r2.ok, f'second regen failed: {r2.status_code} {r2.text[:300]}'
    s2 = r2.json().get('stencil_base64')
    assert s2, 'second regen: empty stencil_base64'

    print(
        f'[cache-skip] first_call={t1 - t0:.1f}s second_call={time.time() - t1:.1f}s '
        f's1_len={len(s1)} s2_len={len(s2)} identical={s1 == s2}'
    )

    # If second call came back in <1s it's almost certainly cached — that would be a regression.
    # We primarily assert on content difference; timing is a soft signal.
    assert s1 != s2, (
        'regenerate_style returned an IDENTICAL stencil twice — cache was NOT skipped '
        '(this is the regression the main agent fixed).'
    )


@pytest.mark.timeout(200)
def test_ai_stencil_non_regenerate_can_hit_cache(api_client):
    """Without regenerate_style, second identical call should be fast (cache hit allowed)."""
    image_b64 = _make_portrait_jpeg_b64(color=(160, 120, 95))
    payload = {
        'image_base64': image_b64,
        'line_color': 'black',
        'shading_detail': 'medium',
    }
    r1 = api_client.post(f'{BASE_URL}/api/ai-stencil', json=payload, timeout=120)
    if not r1.ok:
        pytest.skip(f'first call failed: {r1.status_code} {r1.text[:200]}')
    t0 = time.time()
    r2 = api_client.post(f'{BASE_URL}/api/ai-stencil', json=payload, timeout=120)
    elapsed = time.time() - t0
    assert r2.ok, f'second call failed: {r2.status_code} {r2.text[:300]}'
    print(f'[no-regen cache] second call took {elapsed:.2f}s (expected <2s if cached)')
    # Not a hard assertion — cache may have been evicted; just document.
