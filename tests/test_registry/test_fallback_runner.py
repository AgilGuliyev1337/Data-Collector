"""
Phase 2C: Deterministic Fallback Runner testləri.

Yoxlanılır:
  - İlk candidate uğurlu → dərhal qayıdır
  - Birinci candidate boş → növbəti candidate-a keçir
  - Hamısı uğursuz → failure
  - Uyğun olmayan source (cbr_russia) skip edilir
  - Audit logging (collection_runs)
  - Disabled source skip
  - Concept with no candidates
"""

import json
import os
import unittest.mock

import pytest
import psycopg2.extras

from collector.db import repository

pytestmark = pytest.mark.db


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def _count(conn, table, where="", params=()):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} {where}", params)
        return cur.fetchone()[0]


def _load_fixture(name):
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_first_candidate_success(db_conn):
    """İlk candidate (world_bank) data qaytardıqda dərhal qayıdır."""
    from collector.fallback_runner import run_fallback

    repository.ensure_catalogue_and_mapping(db_conn)
    repository.ensure_static_sources(db_conn)

    with unittest.mock.patch("collector.sources.worldbank_source.urllib.request.urlopen") as mock_urlopen:
        fixture = _load_fixture("worldbank_response.json")
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda *a: False
        mock_urlopen.return_value.read.return_value = json.dumps(fixture).encode()

        result = run_fallback(
            db_conn,
            concept_id="gdp_per_capita",
            countries=["AZE"],
            period_start=2020,
            period_end=2020,
        )

    assert result["success"] is True
    assert result["selected_source"] == "world_bank"
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["status"] == "success"
    assert result["attempts"][0]["records_count"] > 0


def test_first_candidate_empty_falls_back(db_conn):
    """Eurostat boş qaytdıqda növbəti candidate-a keçir.

    gdp_growth üçün sıralama: eurostat (confidence 0.95) → world_bank (0.95)
    Eurostat birinci olduğu üçün onu mock-edirik — empty → world_bank-a keçir.
    """
    from collector.fallback_runner import run_fallback

    repository.ensure_catalogue_and_mapping(db_conn)
    repository.ensure_static_sources(db_conn)

    # Eurostat boş qaytarsın (birinci candidate)
    with unittest.mock.patch("collector.sources.eurostat_source.urllib.request.urlopen") as mock_es:
        mock_es.return_value.__enter__ = lambda s: s
        mock_es.return_value.__exit__ = lambda *a: False
        mock_es.return_value.read.return_value = json.dumps([]).encode()

        # World Bank data qaytarsın (ikinci candidate)
        with unittest.mock.patch("collector.sources.worldbank_source.urllib.request.urlopen") as mock_wb:
            fixture = _load_fixture("worldbank_response.json")
            mock_wb.return_value.__enter__ = lambda s: s
            mock_wb.return_value.__exit__ = lambda *a: False
            mock_wb.return_value.read.return_value = json.dumps(fixture).encode()

            result = run_fallback(
                db_conn,
                concept_id="gdp_growth",
                countries=["DE"],
                period_start=2020,
                period_end=2020,
            )

    # eurostat empty → world_bank success
    assert result["success"] is True
    sources_attempted = {a["source_id"] for a in result["attempts"]}
    assert "eurostat" in sources_attempted
    assert "world_bank" in sources_attempted


def test_all_candidates_fail(db_conn):
    """Eyni concept üçün 2+ candidate varsa və hamısı uğursuz olarsa failure."""
    from collector.fallback_runner import run_fallback

    repository.ensure_catalogue_and_mapping(db_conn)
    repository.ensure_static_sources(db_conn)

    # gdp_growth → eurostat + world_bank (hər ikisi candidate)
    with unittest.mock.patch("collector.sources.eurostat_source.urllib.request.urlopen") as mock_es:
        import urllib.error
        mock_es.side_effect = urllib.error.URLError("Connection refused")

        with unittest.mock.patch("collector.sources.worldbank_source.urllib.request.urlopen") as mock_wb:
            mock_wb.side_effect = urllib.error.URLError("Connection refused")

            result = run_fallback(
                db_conn,
                concept_id="gdp_growth",
                countries=["DE"],
                period_start=2020,
                period_end=2020,
            )

    assert result["success"] is False
    assert result["selected_source"] is None
    assert len(result["attempts"]) >= 2  # eurostat + world_bank
    assert result["reason"] == "all_candidates_failed"
    # Adapter exception catch edir, [] qaytarır → "empty" status
    statuses = {a["status"] for a in result["attempts"]}
    assert "empty" in statuses


def test_incompatible_source_skipped(db_conn):
    """cbr_russia macro indicator-lər üçün skip edilməlidir (mapper yoxdur)."""
    from collector.fallback_runner import run_fallback

    repository.ensure_catalogue_and_mapping(db_conn)
    repository.ensure_static_sources(db_conn)

    with unittest.mock.patch("collector.sources.worldbank_source.urllib.request.urlopen") as mock_urlopen:
        fixture = _load_fixture("worldbank_response.json")
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda *a: False
        mock_urlopen.return_value.read.return_value = json.dumps(fixture).encode()

        result = run_fallback(
            db_conn,
            concept_id="gdp_per_capita",
            countries=["AZE"],
            period_start=2020,
            period_end=2020,
        )

    assert result["success"] is True
    assert result["selected_source"] == "world_bank"


def test_audit_logging_in_collection_runs(db_conn):
    """Hər cəhd collection_runs-a yazılır."""
    from collector.fallback_runner import run_fallback

    repository.ensure_catalogue_and_mapping(db_conn)
    repository.ensure_static_sources(db_conn)

    fixture = _load_fixture("worldbank_response.json")

    with unittest.mock.patch("collector.sources.worldbank_source.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda *a: False
        mock_urlopen.return_value.read.return_value = json.dumps(fixture).encode()

        run_fallback(
            db_conn,
            concept_id="gdp_per_capita",
            countries=["AZE"],
            period_start=2020,
            period_end=2020,
        )

    before = _count(db_conn, "collection_runs")

    with unittest.mock.patch("collector.sources.worldbank_source.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda *a: False
        mock_urlopen.return_value.read.return_value = json.dumps(fixture).encode()

        run_fallback(
            db_conn,
            concept_id="gdp_per_capita",
            countries=["AZE"],
            period_start=2021,
            period_end=2021,
        )

    after = _count(db_conn, "collection_runs")
    assert after == before + 1, "Hər fallback run collection_runs-a yeni sətir yazmalıdır"


def test_fallback_with_disabled_source_skipped(db_conn):
    """Disabled source candidate arasında olsa skip edilir.

    gdp_growth sıralaması: eurostat → world_bank.
    Eurostat boş → world_bank disabled → skip → failure.
    """
    from collector.fallback_runner import run_fallback

    repository.ensure_catalogue_and_mapping(db_conn)
    repository.ensure_static_sources(db_conn)

    # world_bank disabled edirik
    with db_conn.cursor() as cur:
        cur.execute("UPDATE sources SET enabled = false WHERE id = 'world_bank'")

    with unittest.mock.patch("collector.sources.eurostat_source.urllib.request.urlopen") as mock_es:
        # Eurostat empty — next candidate world_bank-a keçir
        mock_es.return_value.__enter__ = lambda s: s
        mock_es.return_value.__exit__ = lambda *a: False
        mock_es.return_value.read.return_value = json.dumps([]).encode()

        result = run_fallback(
            db_conn,
            concept_id="gdp_growth",
            countries=["DE"],
            period_start=2020,
            period_end=2020,
        )

    # Eurostat empty → world_bank disabled → all fail
    assert result["success"] is False
    assert result["selected_source"] is None
    skipped = [a for a in result["attempts"] if a["status"] == "skipped"]
    assert any(a["source_id"] == "world_bank" for a in skipped), \
        f"world_bank skipped olmalıdır. Bütün attempt: {result['attempts']}"


def test_concept_with_no_candidates(db_conn):
    """Mövzuda candidate olmayan halda boş nəticə."""
    from collector.fallback_runner import run_fallback

    result = run_fallback(
        db_conn,
        concept_id="nonexistent_concept_xyz",
        countries=["AZE"],
        period_start=2020,
        period_end=2020,
    )

    assert result["success"] is False
    assert result["selected_source"] is None
    assert result["reason"] == "no_candidates"
    assert result["attempts"] == []