"""
Shared pytest fixtures. Reuses the existing committed output/*.json bundles
as test fixtures rather than inventing synthetic ones -- they already span
the real edge cases that matter (MBLY's null P/E, QQQ's thin/missing-section
data), and keeping them as the single source of truth means a test failure
here means the actual example files people look at are broken too.
"""

import json
import os

import pytest

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

# Every bundle JSON currently committed in output/. Kept as a plain list
# (not a glob) so a fixture file being renamed/removed fails loudly here
# rather than silently shrinking test coverage.
BUNDLE_NAMES = ["AAPL", "mobileye", "qqq", "google", "spcx", "aapl_dryrun"]


@pytest.fixture(params=BUNDLE_NAMES)
def sample_bundle(request):
    """Parametrized fixture: a test using this fixture runs once per
    committed bundle file. Use this (not load_bundle) when a test should
    hold for every example bundle, not just one."""
    return load_bundle(request.param)


def load_bundle(name: str) -> dict:
    """Non-fixture helper for tests that want one specific bundle by name
    rather than running against all of them."""
    path = os.path.join(OUTPUT_DIR, f"{name}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """Points storage.db at a throwaway sqlite file for the duration of one
    test. Patches storage.db.DB_PATH directly (not config.DB_PATH) because
    `from config import DB_PATH` in storage/db.py already bound a local
    name at import time -- patching config's copy after the fact wouldn't
    reach the name storage.db actually uses."""
    import storage.db as db_module

    db_path = tmp_path / "test_stockllm.db"
    monkeypatch.setattr(db_module, "DB_PATH", str(db_path))
    db_module.init_db()
    return db_module


@pytest.fixture
def flask_client():
    """Flask test client for webapp/app.py's routes. Importing webapp.app
    has no side effects that touch the network (its only I/O at import
    time is the optional /data/options.json read, which is a no-op outside
    a real HA container)."""
    import webapp.app as wa
    wa.app.config.update(TESTING=True)
    return wa.app.test_client()
