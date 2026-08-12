"""
Ümumi fixture-lar:
  - `fake_response` / `load_fixture` -> source adapter testləri üçün
    (real şəbəkə çağırışı yoxdur, canned JSON istifadə olunur).
  - `db_conn` -> real Postgres test bazasına (TEST_DATABASE_URL) qoşulur,
    hər testdən sonra rollback edir (mock yoxdur, DB təmiz qalır).
"""

import json
import os

import pytest

from collector.db.connection import get_connection
from collector.db.migrate import run_migrations

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class FakeHTTPResponse:
    """urllib.request.urlopen()-in qaytardığı context manager-i təqlid edir."""

    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


@pytest.fixture
def fake_response():
    return FakeHTTPResponse


@pytest.fixture
def load_fixture():
    def _load(name: str):
        with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    return _load


@pytest.fixture(scope="session")
def _migrated_test_db():
    conn = get_connection(test=True)
    try:
        run_migrations(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db_conn(_migrated_test_db):
    conn = get_connection(test=True)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
