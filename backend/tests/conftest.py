"""Pytest config for backend tests.

Ensures all async tests in this package share a single event loop so that
motor's AsyncIOMotorClient (bound to the loop at import time) stays valid
across tests in the same file.
"""
import asyncio
import pytest


@pytest.fixture(scope='session')
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
