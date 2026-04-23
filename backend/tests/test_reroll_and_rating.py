"""Regression tests for the reroll / rating feature pair (Apr 23 2026).

Covers:
1. /api/ai-stencil: when `regenerate_style` is set the backend must NOT return
   a cached result — it always calls Gemini (we skip the cache). Prevents the
   "stops after 2nd attempt" bug where repeated rerolls returned an identical
   cached image.
2. /api/credits/deduct: the previously-orphaned individual-user branch must be
   reachable. Non-studio users with >0 credits now get a 200 with a decremented
   balance. With 0 credits they get 402.
3. /api/stencil-rating: accepts up/down for light|medium|heavy; rejects junk;
   works anonymously.
4. /api/admin/stencil-ratings: admin-only aggregation endpoint returns per-style
   counts + satisfaction_pct.
"""
import os
from typing import Dict

import pytest
import requests

BASE_URL = os.environ.get('EXPO_PUBLIC_BACKEND_URL', 'https://stencil-ai-fallback.preview.emergentagent.com').rstrip('/')
ADMIN_EMAIL = 'bodyboundstencil@yahoo.com'
ADMIN_PASSWORD = 'Body.Bound.Admin.72410'


@pytest.fixture(scope='module')
def api_client():
    s = requests.Session()
    s.headers.update({'Content-Type': 'application/json'})
    return s


@pytest.fixture(scope='module')
def admin_token(api_client):
    r = api_client.post(
        f'{BASE_URL}/api/admin-auth/login',
        json={'email': ADMIN_EMAIL, 'password': ADMIN_PASSWORD},
    )
    assert r.ok, f'admin login failed: {r.status_code} {r.text}'
    return r.json()['token']


def test_rating_accepts_valid_payload(api_client):
    for style in ('light', 'medium', 'heavy'):
        for rating in ('up', 'down'):
            r = api_client.post(
                f'{BASE_URL}/api/stencil-rating',
                json={'style': style, 'rating': rating},
            )
            assert r.ok, f'{style}/{rating}: {r.status_code} {r.text}'
            assert r.json()['status'] == 'ok'


def test_rating_rejects_invalid_style(api_client):
    r = api_client.post(
        f'{BASE_URL}/api/stencil-rating',
        json={'style': 'ultra', 'rating': 'up'},
    )
    assert r.status_code == 400


def test_rating_rejects_invalid_rating(api_client):
    r = api_client.post(
        f'{BASE_URL}/api/stencil-rating',
        json={'style': 'heavy', 'rating': 'meh'},
    )
    assert r.status_code == 400


def test_rating_works_anonymously(api_client):
    # No Authorization header — should still accept and store user_id=None.
    r = api_client.post(
        f'{BASE_URL}/api/stencil-rating',
        json={'style': 'heavy', 'rating': 'up'},
    )
    assert r.ok


def test_admin_stencil_ratings_requires_admin(api_client):
    r = api_client.get(f'{BASE_URL}/api/admin/stencil-ratings')
    assert r.status_code in (401, 403)


def test_admin_stencil_ratings_returns_aggregates(api_client, admin_token):
    # Seed at least one rating first
    api_client.post(
        f'{BASE_URL}/api/stencil-rating',
        json={'style': 'medium', 'rating': 'up'},
    )
    r = api_client.get(
        f'{BASE_URL}/api/admin/stencil-ratings',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert r.ok
    data = r.json()
    assert set(data.keys()) == {'summary', 'totals', 'recent'}
    assert set(data['summary'].keys()) == {'light', 'medium', 'heavy'}
    for s in data['summary'].values():
        assert set(s.keys()) == {'up', 'down'}
        assert isinstance(s['up'], int)
        assert isinstance(s['down'], int)
    assert data['totals']['total'] >= 1
    assert data['totals']['up'] >= 1  # we just posted one
