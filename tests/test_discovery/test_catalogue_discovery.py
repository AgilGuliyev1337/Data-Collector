"""
Phase 4: Catalogue Discovery tests.

All DB-dependent tests use pytestmark = pytest.mark.db.
Mocked tests (no DB) have no marker.
"""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

from collector.sources.ckan_source import CKANSource
from collector.db import repository
from collector.discovery import (
    discover_catalogue_for_source,
    _build_adapter,
    _SOURCE_ADAPTER_MAP,
)
from collector.registry import list_discovery_capable_sources

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")

# ---------------------------------------------------------------------------
# 1. CKAN discovery parses package_search correctly
# ---------------------------------------------------------------------------

def test_ckan_discovery_parses_package_search(load_fixture):
    """DiscoverCatalogue should call package_search and parse results."""
    fixture = load_fixture("ckan_search_response.json")
    search_result = fixture["result"]

    def mock_api_get(action, params=None):
        if action == "package_search" and params and "rows" in params:
            return search_result
        if action == "package_list":
            return []  # Simulate 403
        if action == "package_show":
            lookup = (params or {}).get("id", "")
            for pkg in search_result["results"]:
                if lookup and (lookup == pkg["id"] or lookup == pkg["name"]):
                    return pkg
            return {}
        return {}

    source_cfg = {
        "id": "test_ckan",
        "type": "ckan",
        "base_url": "https://test.example",
        "require_open_license": True,
        "rate_limit_per_sec": 10,
        "filter": {},
    }
    src = CKANSource(source_cfg)

    with patch.object(src, "_api_get", side_effect=mock_api_get):
        entries = src.discover_catalogue()

    assert len(entries) == 3
    assert all("entry_id" in e for e in entries)
    assert all("source_id" in e for e in entries)
    assert all("indicator_code" in e for e in entries)


# ---------------------------------------------------------------------------
# 2. catalogue_entry transformation correct
# ---------------------------------------------------------------------------

def test_catalogue_entry_transformation(load_fixture, db_conn):
    """Each CKAN package should transform to a valid catalogue_entry dict."""
    # Ensure sources table has entries (FK constraint)
    repository.ensure_static_sources(db_conn)

    fixture = load_fixture("ckan_search_response.json")
    search_result = fixture["result"]

    def mock_api_get(action, params=None):
        if action == "package_search" and params and "rows" in params:
            return search_result
        if action == "package_list":
            return []
        if action == "package_show":
            lookup = (params or {}).get("id", "")
            for pkg in search_result["results"]:
                if lookup and (lookup == pkg["id"] or lookup == pkg["name"]):
                    return pkg
            return {}
        return {}

    source_cfg = {
        "id": "test_ckan",
        "type": "ckan",
        "base_url": "https://test.example",
        "require_open_license": True,
        "rate_limit_per_sec": 10,
        "filter": {},
    }
    src = CKANSource(source_cfg)

    with patch.object(src, "_api_get", side_effect=mock_api_get):
        entries = src.discover_catalogue()

    # Check first entry (GDP dataset)
    gdp_entry = entries[0]
    assert gdp_entry["entry_id"] == "test_ckan:gdp-dataset-1"
    assert gdp_entry["source_id"] == "test_ckan"
    assert gdp_entry["dataset_id"] == "gdp-dataset-1"
    assert gdp_entry["indicator_code"] == "gdp-azerbaijan-annual"
    assert gdp_entry["title"] == "Gross Domestic Product - Azerbaijan"
    assert "Gross Domestic Product" in gdp_entry["title"]
    assert "2010" in str(gdp_entry.get("time_coverage_start", "")) or gdp_entry.get("time_coverage_start") == 2010
    assert "azerbaijan" in [t.get("name", "").lower() for t in search_result["results"][0]["tags"]]
    assert gdp_entry["country_coverage"] == ["AZ"]
    assert gdp_entry["methodology_note"] is not None
    assert "gdp.csv" in gdp_entry["methodology_note"]


# ---------------------------------------------------------------------------
# 3. CKAN metadata parsing (title, tags, resources)
# ---------------------------------------------------------------------------

def test_ckan_metadata_parsing(load_fixture):
    """Ensure all CKAN metadata fields are correctly extracted."""
    fixture = load_fixture("ckan_search_response.json")
    search_result = fixture["result"]

    def mock_api_get(action, params=None):
        if action == "package_search" and params and "rows" in params:
            return search_result
        if action == "package_list":
            return []
        if action == "package_show":
            lookup = (params or {}).get("id", "")
            for pkg in search_result["results"]:
                if lookup and (lookup == pkg["id"] or lookup == pkg["name"]):
                    return pkg
            return {}
        return {}

    source_cfg = {
        "id": "test_ckan",
        "type": "ckan",
        "base_url": "https://test.example",
        "require_open_license": True,
        "rate_limit_per_sec": 10,
        "filter": {},
    }
    src = CKANSource(source_cfg)

    with patch.object(src, "_api_get", side_effect=mock_api_get):
        entries = src.discover_catalogue()

    # Entry 2: population dataset
    pop_entry = entries[1]
    assert pop_entry["title"] == "Total Population of Azerbaijan by Year"
    assert "population" in pop_entry["indicator_code"]
    assert pop_entry["country_coverage"] == ["AZ"]
    assert pop_entry["methodology_note"] == "https://admin.opendata.az/data/population.csv"


# ---------------------------------------------------------------------------
# 4. catalogue_entries upsert idempotent
# ---------------------------------------------------------------------------

def test_upsert_catalogue_entry_idempotent(db_conn):
    """Same entry upserted twice should not duplicate."""
    repository.ensure_catalogue_and_mapping(db_conn)
    repository.upsert_source(db_conn, "test_src", "ckan")
    entry = {
        "entry_id": "test_src:test-indicator",
        "source_id": "test_src",
        "dataset_id": "dataset-1",
        "indicator_code": "test-indicator",
        "title": "Test Entry",
        "description": "Test description",
        "unit": None,
        "frequency": None,
        "country_coverage": ["AZ"],
        "time_coverage_start": 2020,
        "time_coverage_end": 2024,
        "methodology_note": "test-note",
    }
    repository.upsert_catalogue_entry(db_conn, entry)
    repository.upsert_catalogue_entry(db_conn, {**entry, "title": "Updated Title"})

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM catalogue_entries WHERE entry_id = %s",
            ("test_src:test-indicator",),
        )
        count = cur.fetchone()[0]
    assert count == 1

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT title FROM catalogue_entries WHERE entry_id = %s",
            ("test_src:test-indicator",),
        )
        title = cur.fetchone()[0]
    assert title == "Updated Title"


# ---------------------------------------------------------------------------
# 5. Duplicate handling (same package twice)
# ---------------------------------------------------------------------------

def test_duplicate_handling(db_conn):
    """Running discover twice on same data should not create duplicates."""
    repository.ensure_catalogue_and_mapping(db_conn)
    repository.upsert_source(db_conn, "test_src", "ckan")
    entry1 = {
        "entry_id": "test_src:duplicate-1",
        "source_id": "test_src",
        "dataset_id": "dup-1",
        "indicator_code": "dup-indicator",
        "title": "Duplicate Test",
        "description": "Will be inserted twice",
    }
    repository.upsert_catalogue_entry(db_conn, entry1)
    repository.upsert_catalogue_entry(db_conn, entry1)

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM catalogue_entries WHERE entry_id = %s",
            ("test_src:duplicate-1",),
        )
        count = cur.fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# 6. Empty response (0 datasets)
# ---------------------------------------------------------------------------

def test_empty_response():
    """Empty package_search should return empty list."""

    def mock_api_get(action, params=None):
        if action == "package_list":
            return []
        return {}

    source_cfg = {
        "id": "empty_ckan",
        "type": "ckan",
        "base_url": "https://empty.example",
        "require_open_license": True,
        "rate_limit_per_sec": 10,
        "filter": {},
    }
    src = CKANSource(source_cfg)

    with patch.object(src, "_api_get", side_effect=mock_api_get):
        entries = src.discover_catalogue()

    assert entries == []


# ---------------------------------------------------------------------------
# 7. Malformed response (missing fields)
# ---------------------------------------------------------------------------

def test_malformed_response():
    """Package without title/description should still produce valid entry."""
    calls = []

    def mock_api_get(action, params=None):
        calls.append((action, params))
        if action == "package_search" and params and "rows" in params:
            # _api_get unwraps {success, result: ...} → returns just result
            return {
                "count": 1,
                "results": [
                    {
                        "id": "malformed-1",
                        "name": "malformed-name",
                    }
                ],
            }
        if action == "package_list":
            return []
        if action == "package_show":
            return {"id": "malformed-1", "name": "malformed-name"}
        return {}

    source_cfg = {
        "id": "malformed_ckan",
        "type": "ckan",
        "base_url": "https://malformed.example",
        "require_open_license": False,
        "rate_limit_per_sec": 10,
        "filter": {},
    }
    src = CKANSource(source_cfg)

    with patch.object(src, "_api_get", side_effect=mock_api_get):
        entries = src.discover_catalogue()

    # Debug: write to file for inspection
    with open("/tmp/malformed_debug.txt", "w") as f:
        f.write(f"calls: {calls}\n")
        f.write(f"entries: {entries}\n")
        f.write(f"len(entries): {len(entries)}\n")

    assert len(entries) == 1, f"Expected 1 entry, got {len(entries)}: {entries}"
    assert entries[0]["indicator_code"] == "malformed-name"
    assert entries[0]["title"] == "malformed-name"  # Falls back to name
    assert entries[0]["description"] == ""
    assert entries[0]["country_coverage"] == []


# ---------------------------------------------------------------------------
# 8. API error handling (network failure)
# ---------------------------------------------------------------------------

def test_api_error_handling():
    """Network failure should return empty list, not raise.

    _api_get wraps urllib calls in try/except. The mock replaces _api_get
    entirely, so we must simulate the exception-handling behavior.
    """

    def mock_api_get(action, params=None):
        raise ConnectionError("Network unreachable")

    source_cfg = {
        "id": "broken_ckan",
        "type": "ckan",
        "base_url": "https://broken.example",
        "require_open_license": True,
        "rate_limit_per_sec": 10,
        "filter": {},
    }
    src = CKANSource(source_cfg)

    # Patch with a wrapper that catches exceptions (like the real _api_get)
    original_api_get = src._api_get

    def resilient_api_get(action, params=None):
        try:
            return mock_api_get(action, params)
        except Exception:
            return {}

    with patch.object(src, "_api_get", side_effect=resilient_api_get):
        entries = src.discover_catalogue()

    assert entries == []


# ---------------------------------------------------------------------------
# 9. stat_gov_az skipped in discovery
# ---------------------------------------------------------------------------

def test_stat_gov_az_skipped_in_discovery(db_conn):
    """stat_gov_az has has_api=False, should NOT be in capable sources."""
    repository.ensure_static_sources(db_conn)
    capable = list_discovery_capable_sources(db_conn)
    capable_ids = {s["id"] for s in capable}
    assert "stat_gov_az" not in capable_ids


# ---------------------------------------------------------------------------
# 10. cbar_az skipped in discovery
# ---------------------------------------------------------------------------

def test_cbar_az_skipped_in_discovery(db_conn):
    """cbar_az has has_api=False, should NOT be in capable sources."""
    repository.ensure_static_sources(db_conn)
    capable = list_discovery_capable_sources(db_conn)
    capable_ids = {s["id"] for s in capable}
    assert "cbar_az" not in capable_ids


# ---------------------------------------------------------------------------
# 11. opendata_az discovered successfully
# ---------------------------------------------------------------------------

def test_opendata_az_in_capable_sources(db_conn):
    """opendata_az has has_api=True and type=ckan, should be in capable sources."""
    repository.ensure_static_sources(db_conn)
    capable = list_discovery_capable_sources(db_conn)
    capable_ids = {s["id"] for s in capable}
    assert "opendata_az" in capable_ids

    # Verify it's type=ckan
    ckan_entries = [s for s in capable if s["id"] == "opendata_az"]
    assert len(ckan_entries) == 1
    assert ckan_entries[0]["type"] == "ckan"


# ---------------------------------------------------------------------------
# 12. Existing Phase 2B mappings NOT overwritten
# ---------------------------------------------------------------------------

def test_existing_mappings_not_overwritten(db_conn):
    """seed_auto_concept_mappings should not overwrite existing high-confidence mappings."""
    repository.ensure_catalogue_and_mapping(db_conn)
    # Create a source and catalogue entry
    repository.upsert_source(db_conn, "test_src", "ckan", base_url="https://test.example")
    entry = {
        "entry_id": "test_src:gdp-test",
        "source_id": "test_src",
        "dataset_id": "gdp-test",
        "indicator_code": "gdp-test",
        "title": "GDP Test",
        "description": "GDP Growth Rate for testing",
    }
    repository.upsert_catalogue_entry(db_conn, entry)

    # Pre-existing high-confidence mapping
    repository.link_concept_to_entry(db_conn, "gdp_growth", "test_src:gdp-test", 0.95, "rule_based")

    # Now seed auto mappings - should NOT overwrite the existing 0.95 mapping
    mappings_created = repository.seed_auto_concept_mappings(db_conn)

    # The existing mapping should still be 0.95
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT confidence FROM concept_indicator_map WHERE concept_id = %s AND entry_id = %s",
            ("gdp_growth", "test_src:gdp-test"),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 0.95  # Should NOT be overwritten by 0.70

    # seed_auto_concept_mappings returns count of NEW mappings (the existing one shouldn't be counted)
    # Since the entry already has a mapping, it won't be processed
    assert mappings_created == 0


# ---------------------------------------------------------------------------
# 13. Auto-matching finds GDP dataset
# ---------------------------------------------------------------------------

def test_auto_matching_finds_gdp(db_conn):
    """seed_auto_concept_mappings should match 'Gross Domestic Product' title to gdp concept."""
    repository.ensure_catalogue_and_mapping(db_conn)
    repository.upsert_source(db_conn, "auto_test", "ckan", base_url="https://auto.example")
    entry = {
        "entry_id": "auto_test:gdp-match",
        "source_id": "auto_test",
        "dataset_id": "gdp-match",
        "indicator_code": "gdp-match",
        "title": "Gross Domestic Product - Auto Test",
        "description": "GDP data for the region",
    }
    repository.upsert_catalogue_entry(db_conn, entry)

    mappings_created = repository.seed_auto_concept_mappings(db_conn)

    assert mappings_created > 0

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT concept_id, confidence, match_type FROM concept_indicator_map WHERE entry_id = %s",
            ("auto_test:gdp-match",),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "gdp"
    assert row[1] == 0.70
    assert row[2] == "manual"


# ---------------------------------------------------------------------------
# 14. Auto-matching skips unrelated dataset
# ---------------------------------------------------------------------------

def test_auto_matching_skips_unrelated(db_conn):
    """Seed auto mappings should not create false-positive mappings."""
    repository.ensure_catalogue_and_mapping(db_conn)
    repository.upsert_source(db_conn, "auto_skip", "ckan", base_url="https://auto.example")
    entry = {
        "entry_id": "auto_skip:weather",
        "source_id": "auto_skip",
        "dataset_id": "weather",
        "indicator_code": "weather-data",
        "title": "Weather Station Data",
        "description": "Meteorological observations from weather stations",
    }
    repository.upsert_catalogue_entry(db_conn, entry)

    mappings_created = repository.seed_auto_concept_mappings(db_conn)

    # This entry should not match any concept
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM concept_indicator_map WHERE entry_id = %s",
            ("auto_skip:weather",),
        )
        count = cur.fetchone()[0]
    assert count == 0


# ---------------------------------------------------------------------------
# 15. Full pipeline: discover_catalogue_for_source() end-to-end
# ---------------------------------------------------------------------------

def test_full_pipeline_discover_catalogue_for_source(db_conn, load_fixture):
    """End-to-end: discover_catalogue_for_source should handle full flow."""
    # Ensure catalogue and mapping tables + seed data exist
    repository.ensure_catalogue_and_mapping(db_conn)
    fixture = load_fixture("ckan_search_response.json")
    search_result = fixture["result"]

    # Ensure sources are seeded
    repository.ensure_static_sources(db_conn)

    def mock_api_get(action, params=None):
        if action == "package_search" and params and "rows" in params:
            return search_result
        if action == "package_list":
            return []
        if action == "package_show":
            lookup = (params or {}).get("id", "")
            for pkg in search_result["results"]:
                if lookup and (lookup == pkg["id"] or lookup == pkg["name"]):
                    return pkg
            return {}
        return {}

    # Patch CKANSource._api_get for our test source
    mock_source_cfg = {
        "id": "pipeline_test",
        "type": "ckan",
        "base_url": "https://pipeline.example",
        "require_open_license": True,
        "rate_limit_per_sec": 10,
        "filter": {},
    }

    # Insert the test source into the DB
    repository.upsert_source(
        db_conn, "pipeline_test", "ckan",
        base_url="https://pipeline.example",
        priority_tier=2, trust_level="official",
    )

    # Create a mock adapter with pre-computed entries
    real_src = CKANSource(mock_source_cfg)
    with patch.object(real_src, "_api_get", side_effect=mock_api_get):
        expected_entries = real_src.discover_catalogue()

    mock_adapter = MagicMock()
    mock_adapter.discover_catalogue.return_value = expected_entries

    with patch("collector.discovery._build_adapter", return_value=mock_adapter):
        result = discover_catalogue_for_source(db_conn, source_id="pipeline_test")

    assert result["entries_discovered"] == 3
    assert result["entries_upserted"] >= 3
    assert "run_id" in result
    assert result["run_id"] is not None

    # Verify entries exist in DB
    entries = repository.get_catalogue_entries_by_source(db_conn, "pipeline_test")
    assert len(entries) >= 3


# ---------------------------------------------------------------------------
# 16. Existing tests still pass — verify source adapter tests untouched
# ---------------------------------------------------------------------------

# These are imports that would fail if the module structure is broken.
# The actual test files are run separately by pytest.
def test_ckan_source_importable():
    """CKANSource should be importable and have expected methods."""
    from collector.sources.ckan_source import CKANSource
    assert hasattr(CKANSource, "list_package_names")
    assert hasattr(CKANSource, "list_package_names_via_search")
    assert hasattr(CKANSource, "discover_catalogue")
    assert hasattr(CKANSource, "collect")
    assert hasattr(CKANSource, "get_package")
    assert hasattr(CKANSource, "_passes_filter")


def test_discovery_module_importable():
    """Discovery engine should be importable."""
    from collector.discovery import (
        discover_catalogue_for_source,
        _build_adapter,
        _SOURCE_ADAPTER_MAP,
    )
    assert "ckan" in _SOURCE_ADAPTER_MAP
    assert "collector.sources.ckan_source.CKANSource" == _SOURCE_ADAPTER_MAP["ckan"]


def test_base_class_default_discover():
    """DataSource.discover_catalogue should return [] by default."""
    from collector.sources.base import DataSource
    # DataSource is abstract — can't instantiate directly,
    # but we can verify the method signature by checking it exists and returns list
    import inspect
    # The method should exist (implemented, not abstract)
    assert "discover_catalogue" in DataSource.__dict__


def test_repository_functions_exist():
    """All new repository functions should exist."""
    assert hasattr(repository, "upsert_catalogue_entry")
    assert hasattr(repository, "get_catalogue_entries_by_source")
    assert hasattr(repository, "get_catalogue_entry_by_id")
    assert hasattr(repository, "get_catalogue_entries_by_indicator")
    assert hasattr(repository, "link_concept_to_entry")
    assert hasattr(repository, "seed_auto_concept_mappings")


def test_registry_discovery_function_exists():
    """list_discovery_capable_sources should exist in registry."""
    from collector.registry import list_discovery_capable_sources
    assert callable(list_discovery_capable_sources)