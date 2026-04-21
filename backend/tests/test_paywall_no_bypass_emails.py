"""Regression tests for the paywall-QA bypass escape hatch.

Background: during paywall validation we hit a contamination issue —
bodyboundstencilapp@gmail.com was recreated after deletion and the
new account was auto-placed into tier=paywall_bypass with 10 credits
because TEMP_BYPASS_ENABLED=true is set globally (so every signup walks
in with 10 free credits while subscription loading is stabilized).

Fix: a comma-separated env allowlist `PAYWALL_NO_BYPASS_EMAILS` — emails
in it NEVER receive the bypass at signup, even with
TEMP_BYPASS_ENABLED=true. Match is case-insensitive and trim-tolerant.

These tests lock the escape hatch contract so subscription validation
can't be silently broken again by a rename / removal of the env var.
"""
import os
import uuid
import importlib
import pytest


@pytest.fixture
def server(monkeypatch):
    """Import `server` with controlled env vars. We set vars before import
    because create_initial_subscription reads os.environ at call time, but
    we also need the module's db client to talk to the same Mongo as the
    running backend."""
    monkeypatch.setenv('TEMP_BYPASS_ENABLED', 'true')
    monkeypatch.setenv(
        'PAYWALL_NO_BYPASS_EMAILS',
        '  qa.clean@test.com , bodyboundstencilapp@gmail.com,'
        'formyuselessstuff1@gmail.com ',
    )
    import server as srv
    importlib.reload(srv)
    return srv


@pytest.mark.asyncio
async def test_bypass_granted_to_normal_email(server):
    uid = 'user_test_' + uuid.uuid4().hex[:10]
    try:
        sub = await server.create_initial_subscription(
            uid, 'normal.user@test.com', 'dev1', 'google', 'g1')
        assert sub['tier'] == 'paywall_bypass'
        assert sub['available_credits'] == 10
    finally:
        await server.db.subscriptions.delete_one({'user_id': uid})


@pytest.mark.asyncio
async def test_blocklisted_email_skips_bypass(server):
    """The exact email from the reported contamination bug."""
    uid = 'user_test_' + uuid.uuid4().hex[:10]
    try:
        sub = await server.create_initial_subscription(
            uid, 'bodyboundstencilapp@gmail.com', 'dev2', 'apple', 'a1')
        assert sub['tier'] is None, f'paywall_bypass leaked for QA email: {sub}'
        assert sub['available_credits'] == 0
    finally:
        await server.db.subscriptions.delete_one({'user_id': uid})


@pytest.mark.asyncio
async def test_blocklist_is_case_insensitive(server):
    """Mixed-case signup must still hit the blocklist."""
    uid = 'user_test_' + uuid.uuid4().hex[:10]
    try:
        sub = await server.create_initial_subscription(
            uid, 'QA.Clean@TEST.com', 'dev3', 'google', 'g3')
        assert sub['tier'] is None
        assert sub['available_credits'] == 0
    finally:
        await server.db.subscriptions.delete_one({'user_id': uid})


@pytest.mark.asyncio
async def test_blocklist_tolerates_whitespace(server):
    """The raw env string above has inconsistent spacing / trailing comma.
    Each email must still resolve correctly."""
    uid = 'user_test_' + uuid.uuid4().hex[:10]
    try:
        sub = await server.create_initial_subscription(
            uid, 'formyuselessstuff1@gmail.com', 'dev4', 'apple', 'a2')
        assert sub['tier'] is None
        assert sub['available_credits'] == 0
    finally:
        await server.db.subscriptions.delete_one({'user_id': uid})


@pytest.mark.asyncio
async def test_empty_blocklist_preserves_bypass(monkeypatch):
    monkeypatch.setenv('TEMP_BYPASS_ENABLED', 'true')
    monkeypatch.setenv('PAYWALL_NO_BYPASS_EMAILS', '')
    import server as srv
    importlib.reload(srv)
    uid = 'user_test_' + uuid.uuid4().hex[:10]
    try:
        sub = await srv.create_initial_subscription(
            uid, 'anybody@test.com', 'dev5', 'google', 'g5')
        assert sub['tier'] == 'paywall_bypass'
        assert sub['available_credits'] == 10
    finally:
        await srv.db.subscriptions.delete_one({'user_id': uid})
