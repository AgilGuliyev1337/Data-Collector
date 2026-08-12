import datetime

import pytest

from collector.db import repository

pytestmark = pytest.mark.db


def _count(conn, table, where="", params=()):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} {where}", params)
        return cur.fetchone()[0]


def test_upsert_source_inserts_then_updates(db_conn):
    repository.upsert_source(db_conn, "test_src", "ckan", base_url="https://a.example",
                              priority_tier=2, trust_level="official")
    with db_conn.cursor() as cur:
        cur.execute("SELECT type, base_url, priority_tier, trust_level FROM sources WHERE id = %s",
                    ("test_src",))
        row = cur.fetchone()
    assert row == ("ckan", "https://a.example", 2, "official")

    repository.upsert_source(db_conn, "test_src", "ckan", base_url="https://b.example",
                              priority_tier=2, trust_level="official")
    with db_conn.cursor() as cur:
        cur.execute("SELECT base_url FROM sources WHERE id = %s", ("test_src",))
        row = cur.fetchone()
    assert row == ("https://b.example",)
    assert _count(db_conn, "sources", "WHERE id = %s", ("test_src",)) == 1


def test_ensure_static_sources_creates_all_known_sources(db_conn):
    repository.ensure_static_sources(db_conn)
    with db_conn.cursor() as cur:
        cur.execute("SELECT id, discovery_method FROM sources ORDER BY id")
        rows = cur.fetchall()
    ids = {r[0] for r in rows}
    # Phase 2A: 4 global + Phase 3: 3 Azerbaijan
    assert ids == {"world_bank", "eurostat", "imf", "cbr_russia",
                   "stat_gov_az", "opendata_az", "cbar_az"}
    assert all(r[1] == "static" for r in rows)


def test_upsert_dataset_upserts_on_conflict(db_conn):
    repository.upsert_source(db_conn, "ds_src", "ckan")
    record = {
        "source_id": "ds_src", "dataset_id": "pkg-1", "name": "pkg-1",
        "title": "Original title", "org": "org-a", "license": "cc-by",
        "license_id": "cc-by", "modified": "2024-01-01", "tags": ["a"],
        "groups": [], "resources": [{"url": "http://x"}],
    }
    repository.upsert_dataset(db_conn, record)
    record["title"] = "Updated title"
    repository.upsert_dataset(db_conn, record)

    with db_conn.cursor() as cur:
        cur.execute("SELECT title FROM datasets WHERE source_id = %s AND dataset_id = %s",
                    ("ds_src", "pkg-1"))
        row = cur.fetchone()
    assert row == ("Updated title",)
    assert _count(db_conn, "datasets", "WHERE source_id = %s", ("ds_src",)) == 1


def test_collection_run_lifecycle(db_conn):
    run_id = repository.start_collection_run(db_conn, "run", {"source": "ds_src"})
    with db_conn.cursor() as cur:
        cur.execute("SELECT status, records_collected, finished_at FROM collection_runs WHERE id = %s",
                    (run_id,))
        status, records, finished_at = cur.fetchone()
    assert status == "running"
    assert records == 0
    assert finished_at is None

    repository.finish_collection_run(db_conn, run_id, "success", 5)
    with db_conn.cursor() as cur:
        cur.execute("SELECT status, records_collected, finished_at FROM collection_runs WHERE id = %s",
                    (run_id,))
        status, records, finished_at = cur.fetchone()
    assert status == "success"
    assert records == 5
    assert finished_at is not None


def test_insert_facts_is_append_only(db_conn):
    repository.upsert_source(db_conn, "wb", "worldbank")
    rows = [
        {"source_id": "wb", "concept": "gdp_per_capita", "indicator_code": "NY.GDP.PCAP.CD",
         "country": "Azerbaijan", "iso3": "AZE", "period": "2020", "value": 4000, "unit": "USD"},
    ]
    repository.insert_facts(db_conn, rows)
    repository.insert_facts(db_conn, rows)

    assert _count(db_conn, "facts", "WHERE source_id = %s", ("wb",)) == 2
    with db_conn.cursor() as cur:
        cur.execute("SELECT period_year FROM facts WHERE source_id = %s LIMIT 1", ("wb",))
        assert cur.fetchone() == (2020,)


def test_insert_facts_noop_on_empty_list(db_conn):
    repository.insert_facts(db_conn, [])


def test_upsert_fx_rates_upserts_on_conflict_currency_date(db_conn):
    repository.upsert_source(db_conn, "cbr_russia", "cbr")
    rate_date = datetime.date(2024, 1, 15)
    rows = [
        {"source_id": "cbr_russia", "currency_code": "USD", "currency_name": "US Dollar",
         "nominal": 1, "value_rub": 90.0, "rate_date": rate_date},
    ]
    repository.upsert_fx_rates(db_conn, rows)
    rows[0]["value_rub"] = 91.5
    repository.upsert_fx_rates(db_conn, rows)

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT value_rub FROM fx_rates WHERE currency_code = %s AND rate_date = %s",
            ("USD", rate_date),
        )
        row = cur.fetchone()
    assert row == (91.5,)
    assert _count(db_conn, "fx_rates", "WHERE currency_code = %s AND rate_date = %s",
                  ("USD", rate_date)) == 1


def test_upsert_fx_rates_noop_on_empty_list(db_conn):
    repository.upsert_fx_rates(db_conn, [])
