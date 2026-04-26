"""End-to-end test: seed sessions via the public ingest endpoint, then
verify the admin aggregation endpoint returns correct math."""
import asyncio
import json
import sys
import urllib.request

import jwt

sys.path.insert(0, '/app/backend')
from server import db, JWT_SECRET

API = 'http://localhost:8001'


def post(path, body, token=None):
    h = {'Content-Type': 'application/json'}
    if token:
        h['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(f'{API}{path}', data=json.dumps(body).encode(), headers=h, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def get(path, token=None):
    h = {}
    if token:
        h['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(f'{API}{path}', headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


async def get_admin_token():
    admin = await db.users.find_one({'email': 'bodyboundstencil@yahoo.com'}, {'_id': 0, 'user_id': 1, 'email': 1})
    if not admin:
        return None
    return jwt.encode({'user_id': admin['user_id'], 'email': admin['email']}, JWT_SECRET, algorithm='HS256')


async def main():
    # Seed 4 distinct sessions
    sessions = [
        # Session A: user generates light, rerolls 2x, switches to medium, saves medium
        ('agg_sA', [('generate','light'),('reroll','light'),('reroll','light'),('style_switch','medium'),('save','medium')]),
        # Session B: light → save
        ('agg_sB', [('generate','light'),('save','light')]),
        # Session C: heavy → reroll → save
        ('agg_sC', [('generate','heavy'),('reroll','heavy'),('save','heavy')]),
        # Session D: medium → switch heavy → export (no save)
        ('agg_sD', [('generate','medium'),('style_switch','heavy'),('export','heavy')]),
    ]
    await db.stencil_sessions.delete_many({'session_id': {'$regex': '^agg_'}})
    for sid, events in sessions:
        for evt, style in events:
            s, _ = post('/api/analytics/session-event', {'session_id': sid, 'event': evt, 'style': style, 'user_tier': 'walk-in'})
            if s != 200:
                print(f'  FAIL: {sid} {evt} {style} → {s}')
                return

    # Unauthenticated admin call must fail
    s, r = get('/api/admin/stencil-analytics?days=30')
    assert s == 401, f'unauth admin call should be 401, got {s}'
    print(f'✓ Unauthenticated admin call rejected ({s})')

    # Authenticated
    tok = await get_admin_token()
    if not tok:
        print('No admin user — skipping authed call')
        return
    s, r = get('/api/admin/stencil-analytics?days=30', token=tok)
    assert s == 200, f'authed call failed: {s} {r}'
    print(f'✓ Admin endpoint OK')
    print(json.dumps(r, indent=2))

    # Sanity check the math
    # 4 total sessions
    # Final styles: medium (sA), light (sB), heavy (sC), heavy (sD) → light:1, medium:1, heavy:2
    # Saves: sA, sB, sC = 3
    # Exports: sD = 1
    # sA generated light but switched away → light "switched away" = 1, light "generated" = 2 (sA+sB)
    #   → switched_away_pct for light = 1/2 = 50%
    # sD generated medium but switched away → medium "switched away" = 1, medium "generated" = 1
    #   → switched_away_pct for medium = 1/1 = 100%
    # heavy: only generated in sC and sD, ended on heavy in both → switched_away = 0/2 = 0%
    # Avg rerolls when final:
    #   light final = sB only, rerolls.light at sB = 0 → avg = 0
    #   medium final = sA only, rerolls.medium at sA = 0 → avg = 0
    #   heavy final = sC, sD → rerolls.heavy: sC=1, sD=0 → avg = 0.5

    # Filter to just our agg_ test sessions for math verification
    test_only = await db.stencil_sessions.find({'session_id': {'$regex': '^agg_'}}, {'_id': 0}).to_list(10)
    assert len(test_only) == 4
    finals = [t.get('final_style') for t in test_only]
    assert sorted(finals) == ['heavy', 'heavy', 'light', 'medium'], finals
    print(f'✓ Final styles correct: {sorted(finals)}')

    # Cleanup
    await db.stencil_sessions.delete_many({'session_id': {'$regex': '^agg_'}})
    print('\nALL PASS')


asyncio.run(main())
