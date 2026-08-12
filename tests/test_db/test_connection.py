import pytest

from collector.db.connection import get_connection, get_dsn

pytestmark = pytest.mark.db


def test_get_dsn_reads_test_database_url():
    dsn = get_dsn(test=True)
    assert dsn.startswith("postgresql://")


def test_can_connect_and_query_test_database():
    conn = get_connection(test=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
    finally:
        conn.close()
