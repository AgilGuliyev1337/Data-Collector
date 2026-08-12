# -*- coding: utf-8 -*-
"""
Tests for new sources: STAT.GOV.AZ + Manzil.az
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from unittest.mock import patch, MagicMock

from collector.sources.stat_gov_az_source import STATGOVSource
from collector.sources.manzil_az_source import ManzilAzSource


# ---------------------------------------------------------------------------
# STATGOVSource
# ---------------------------------------------------------------------------

class TestSTATGOVSourceInit:
    def test_default_init(self):
        src = STATGOVSource()
        assert src.id == "stat_gov_az"
        assert src.mode == "open_api"

    def test_cfg_override(self):
        src = STATGOVSource({"mode": "web_parse"})
        assert src.mode == "web_parse"

    def test_validate_connection_check_behavior(self):
        """validate_connection returns bool based on API success."""
        src = STATGOVSource()
        with patch.object(src, '_datastore_search') as mock_search:
            mock_search.return_value = {"success": True, "result": {"records": [{}]}}
            assert src.validate_connection() is True
        with patch.object(src, '_datastore_search') as mock_search:
            mock_search.return_value = {"success": False, "result": {}}
            assert src.validate_connection() is False


class TestSTATGOVSalary:
    def test_fetch_salary_defaults(self):
        src = STATGOVSource()
        rows = src.fetch(concept="maas", countries=["AZE"], period_start=2024, period_end=2025)
        # Should return defaults if DB/API fails
        assert isinstance(rows, list)
        assert len(rows) >= 1
        for r in rows:
            assert r["iso3"] == "AZE"
            assert r["indicator"] == "maas"
            assert r["unit"] == "AZN"

    def test_salary_2024_value(self):
        src = STATGOVSource()
        rows = src.fetch(concept="maas", countries=["AZE"], period_start=2024, period_end=2024)
        values = [r["value"] for r in rows]
        assert 900 in values or 999 in values  # 2024: 999 AZN

    def test_salary_2025_value(self):
        src = STATGOVSource()
        rows = src.fetch(concept="maas", countries=["AZE"], period_start=2025, period_end=2025)
        values = [r["value"] for r in rows]
        assert 1000 in values or 1103 in values  # 2025: 1103 AZN


class TestSTATGOVHousing:
    def test_fetch_housing_defaults(self):
        src = STATGOVSource()
        rows = src.fetch(concept="ev_qiymeti", period_start=2024, period_end=2025)
        assert isinstance(rows, list)
        assert len(rows) >= 1
        for r in rows:
            assert r["iso3"] == "AZE"
            assert r["indicator"] == "ev_qiymeti"

    def test_housing_2025_value(self):
        src = STATGOVSource()
        rows = src.fetch(concept="ev_qiymeti", period_start=2025, period_end=2025)
        values = [r["value"] for r in rows]
        assert 2300 in values or 2388 in values  # 2025: ~2388 AZN/m²


# ---------------------------------------------------------------------------
# ManzilAzSource
# ---------------------------------------------------------------------------

class TestManzilAzSourceInit:
    def test_default_init(self):
        src = ManzilAzSource()
        assert src.id == "manzil_az"

    def test_validate_connection_false_on_error(self):
        src = ManzilAzSource()
        with patch.object(src, '_search', return_value={}):
            assert src.validate_connection() is False


class TestManzilAzHousing:
    def test_fetch_housing_defaults_when_no_api(self):
        src = ManzilAzSource()
        with patch.object(src, '_search', return_value={}):
            rows = src.fetch(concept="ev_qiymeti", period_start=2025, period_end=2025)
            assert isinstance(rows, list)
            assert len(rows) >= 1
            # Check default value is reasonable
            assert rows[0]["value"] > 1000

    def test_get_defaults_2025(self):
        src = ManzilAzSource()
        rows = src._get_defaults(2025, 2025)
        assert len(rows) == 1
        assert rows[0]["value"] == 2388.0
        assert rows[0]["period"] == "2025"

    def test_get_defaults_range(self):
        src = ManzilAzSource()
        rows = src._get_defaults(2023, 2025)
        assert len(rows) == 3
        periods = [r["period"] for r in rows]
        assert "2023" in periods
        assert "2024" in periods
        assert "2025" in periods

    def test_median_single(self):
        src = ManzilAzSource()
        assert src._median([100]) == 100

    def test_median_even(self):
        src = ManzilAzSource()
        assert src._median([100, 200]) == 150.0

    def test_median_odd(self):
        src = ManzilAzSource()
        assert src._median([100, 200, 300]) == 200

    def test_median_empty(self):
        src = ManzilAzSource()
        assert src._median([]) == 0


# ---------------------------------------------------------------------------
# Adapter dispatch integration
# ---------------------------------------------------------------------------

class TestAdapterDispatch:
    def test_stat_gov_in_dispatch(self):
        from collector.fallback_runner import ADAPTER_DISPATCH
        assert "stat_gov_az" in ADAPTER_DISPATCH
        adapter_class, kwargs_fn = ADAPTER_DISPATCH["stat_gov_az"]
        from collector.sources.stat_gov_az_source import STATGOVSource
        assert adapter_class == STATGOVSource

    def test_manzil_az_in_dispatch(self):
        from collector.fallback_runner import ADAPTER_DISPATCH
        assert "manzil_az" in ADAPTER_DISPATCH
        adapter_class, kwargs_fn = ADAPTER_DISPATCH["manzil_az"]
        from collector.sources.manzil_az_source import ManzilAzSource
        assert adapter_class == ManzilAzSource

    def test_stat_gov_kwargs_transform(self):
        from collector.fallback_runner import ADAPTER_DISPATCH
        _, kwargs_fn = ADAPTER_DISPATCH["stat_gov_az"]
        entry = {"indicator_code": "salary_wages_azerbaijan"}
        params = {"countries": ["AZE"], "period_start": 2024, "period_end": 2025}
        result = kwargs_fn(entry, params)
        assert result["concept"] == "salary_wages_azerbaijan"
        assert result["country_codes"] == ["AZE"]
        assert result["period_start"] == 2024

    def test_manzil_kwargs_transform(self):
        from collector.fallback_runner import ADAPTER_DISPATCH
        _, kwargs_fn = ADAPTER_DISPATCH["manzil_az"]
        entry = {"indicator_code": "manzil_az_listings", "district": "Nəsimi"}
        params = {"countries": ["AZE"], "period_start": 2024, "period_end": 2025}
        result = kwargs_fn(entry, params)
        assert result["concept"] == "manzil_az_listings"
        assert result["district"] == "Nəsimi"


# ---------------------------------------------------------------------------
# Fallback runner integration
# ---------------------------------------------------------------------------

class TestFallbackIntegration:
    def test_stat_gov_fetch_works(self):
        """stat_gov_az source should return data even without live API."""
        src = STATGOVSource()
        rows = src.fetch(concept="maas", countries=["AZE"], period_start=2024, period_end=2024)
        assert len(rows) > 0
        assert rows[0]["value"] is not None

    def test_manzil_fetch_works(self):
        """manzil_az source should return fallback data."""
        src = ManzilAzSource()
        with patch.object(src, '_search', return_value={}):
            rows = src.fetch(concept="ev_qiymeti", period_start=2025, period_end=2025)
            assert len(rows) > 0
            assert rows[0]["value"] > 0