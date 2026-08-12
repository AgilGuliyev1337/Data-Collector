"""
Phase 9 — Fallback + Web Discovery tests.

Validates:
- _normalize_result uses collection.extract_data()
- CKAN is in ADAPTER_DISPATCH
- discover_web_portals logic (mocked HTTP)
"""

import json
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from collector.collection import DataPoint, extract_data
from collector.fallback_runner import ADAPTER_DISPATCH, _normalize_result


# ---------------------------------------------------------------------------
# _normalize_result — uses extract_data
# ---------------------------------------------------------------------------

class TestNormalizeResult:
    def test_world_bank_uses_extract_data(self):
        raw = [
            {"country": {"value": "Azerbaijan"}, "countryiso3code": "AZE",
             "date": 2022, "value": 2.5,
             "indicator": {"value": "NY.GDP.MKTP.KD.ZG"}},
        ]
        result = _normalize_result(raw, "world_bank", 99, "concept_1", "NY.GDP.MKTP.KD.ZG")
        assert len(result) == 1
        assert result[0]["source_id"] == "world_bank"
        assert result[0]["value"] == 2.5
        assert result[0]["country"] == "Azerbaijan"
        assert result[0]["indicator_code"] == "NY.GDP.MKTP.KD.ZG"
        assert result[0]["run_id"] == 99
        assert result[0]["concept"] == "concept_1"

    def test_eurostat_uses_extract_data(self):
        raw = [
            {"geo": "AZ", "time": "2022", "value": 5.2,
             "unit": "IND", "indicator": "une_rt_a"},
        ]
        result = _normalize_result(raw, "eurostat", 1, "c1", "une_rt_a")
        assert len(result) == 1
        assert result[0]["value"] == 5.2
        assert result[0]["unit"] == "IND"

    def test_imf_uses_extract_data(self):
        raw = [
            {"REF_AREA": "AZE", "TIME_PERIOD": "2022",
             "OBS_VALUE": 3.1, "UNIT": "ID", "INDICATOR": "NGDP_R_XDC"},
        ]
        result = _normalize_result(raw, "imf", 1, "c1", "NGDP_R_XDC")
        assert len(result) == 1
        assert result[0]["value"] == 3.1
        assert result[0]["iso3"] == "AZE"

    def test_ckan_uses_extract_data(self):
        raw = [
            {"country": "Azerbaijan", "year": 2022,
             "value": 1500000, "unit": "people",
             "indicator_code": "population_total"},
        ]
        result = _normalize_result(raw, "ckan", 5, "c1", "population_total")
        assert len(result) == 1
        assert result[0]["value"] == 1500000.0
        assert result[0]["unit"] == "people"

    def test_empty_raw(self):
        result = _normalize_result([], "world_bank", 1, "c1", "X")
        assert result == []

    def test_null_value_handling(self):
        raw = [
            {"country": {"value": "X"}, "countryiso3code": "XXX",
             "date": 2020, "value": None,
             "indicator": {"value": "SP.POP.TOTL"}},
        ]
        result = _normalize_result(raw, "world_bank", 1, "c1", "SP.POP.TOTL")
        assert len(result) == 1
        assert result[0]["value"] is None


# ---------------------------------------------------------------------------
# ADAPTER_DISPATCH — CKAN entry
# ---------------------------------------------------------------------------

class TestAdapterDispatch:
    def test_ckan_in_dispatch(self):
        assert "ckan" in ADAPTER_DISPATCH

    def test_ckan_has_adapter_class(self):
        adapter_class, kwargs_fn = ADAPTER_DISPATCH["ckan"]
        assert adapter_class is not None
        # Verify it's a callable class (not a function)
        assert callable(adapter_class)

    def test_ckan_kwargs_transform(self):
        _, kwargs_fn = ADAPTER_DISPATCH["ckan"]
        entry = {"keyword": "population", "indicator_code": "POP"}
        params = {"countries": ["AZE"], "period_start": 2020, "period_end": 2023}
        result = kwargs_fn(entry, params)
        assert "query" in result
        assert result["query"] == "population"
        assert result["start"] == 0
        assert result["rows"] == 100

    def test_all_expected_sources_present(self):
        expected = {"world_bank", "eurostat", "imf", "cbr_russia", "ckan"}
        assert expected.issubset(set(ADAPTER_DISPATCH.keys()))


# ---------------------------------------------------------------------------
# Web discovery — mocked HTTP
# ---------------------------------------------------------------------------

class TestWebDiscovery:
    def _make_response(self, status_code=200, body=None):
        """Mock urllib response."""
        mock_resp = MagicMock()
        mock_resp.status = status_code
        mock_resp.read.return_value = json.dumps(body or {}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_discover_web_portals_no_ckan(self):
        """Mock all portals as non-CKAN — no upserts."""
        from collector.web_discovery import discover_web_portals

        # Mock everything: HEAD fails, so all skipped
        with patch("collector.web_discovery._http_alive", return_value=False):
            result = discover_web_portals(MagicMock())
        assert result["discovered"] == len(__import__("collector.web_discovery", fromlist=["KNOWN_PORTALS"]).KNOWN_PORTALS)
        assert result["ckan_found"] == 0
        assert result["sources_upserted"] == 0

    def test_discover_web_portals_ckan_found(self):
        """Mock one portal as CKAN — 1 upsert."""
        from collector.web_discovery import discover_web_portals

        def alive_side_effect(url, timeout=5):
            if "data.gov.az" in url:
                return True
            return False

        def ckan_side_effect(url, timeout=10):
            if "data.gov.az" in url:
                return True
            return False

        mock_conn = MagicMock()

        with (
            patch("collector.web_discovery._http_alive", side_effect=alive_side_effect),
            patch("collector.web_discovery._is_ckan_portal", side_effect=ckan_side_effect),
        ):
            result = discover_web_portals(mock_conn)

        assert result["discovered"] == len(__import__("collector.web_discovery", fromlist=["KNOWN_PORTALS"]).KNOWN_PORTALS)
        assert result["ckan_found"] >= 1
        assert result["sources_upserted"] >= 1
        assert result["errors"] == []

    def test_web_discovery_writes_run(self):
        """discover_web_portals creates a collection_run."""
        from collector.web_discovery import discover_web_portals

        mock_conn = MagicMock()

        with patch("collector.web_discovery._http_alive", return_value=False):
            discover_web_portals(mock_conn)

        # Verify start_collection_run was called
        mock_conn.cursor().__enter__().execute.assert_called()