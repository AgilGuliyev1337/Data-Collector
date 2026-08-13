import pytest

from collector.db.connection import get_connection
from collector.db.migrate import run_migrations

pytestmark = pytest.mark.db

EXPECTED_TABLES = {"sources", "datasets", "collection_runs", "facts", "fx_rates", "schema_migrations"}


def test_run_migrations_is_idempotent():
    conn = get_connection(test=True)
    try:
        first = run_migrations(conn)
        conn.commit()
        second = run_migrations(conn)
        conn.commit()
        assert second == []
        assert "0001_init.sql" in first or "0001_init.sql" not in second
    finally:
        conn.close()


def test_all_expected_tables_exist_after_migration():
    conn = get_connection(test=True)
    try:
        run_migrations(conn)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            tables = {row[0] for row in cur.fetchall()}
        assert EXPECTED_TABLES.issubset(tables)
    finally:
        conn.close()
