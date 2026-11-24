import os

import pytest

# Set before the app is imported. Environment variables win over the repo-root .env, so unit tests
# never touch real services or real keys. With PROVENANCE_LIVE=1 the real .env is used instead, so the
# fake-key unit tests are skipped and only the tests/test_live_*.py files run.
LIVE = bool(os.environ.get('PROVENANCE_LIVE'))
if not LIVE:
    os.environ.update(
        SUPABASE_URL='https://test.supabase.invalid',
        SUPABASE_ANON_KEY='anon-test',
        SUPABASE_SERVICE_ROLE_KEY='service-test',
    )


def pytest_collection_modifyitems(config, items):
    if LIVE:
        skip = pytest.mark.skip(reason='unit tests use fake keys; unset PROVENANCE_LIVE')
        for item in items:
            if 'test_live_' not in item.nodeid:
                item.add_marker(skip)
