"""
Phase 8 — Collection extraction tests.

Validates each extractor produces correct DataPoints from adapter output.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from collector.collection import (
    DataPoint,
    extract_worldbank,
    extract_eurostat,
    extract_imf,
    extract_cbr,
    extract_ckan,
    extract_data,
    _extract_generic,
    _to_float,
    _parse_year_from_time,
)


# ---------------------------------------------------------------------------
# _to_float
# ---------------------------------------------------------------------------

class TestToFloat:
    def test_none(self):
        assert _to_float(None) is None

    def test_int(self):
        assert _to_float(42) == 42.0

    def test_float(self):
        assert _to_float(3.14) == 3.14

    def test_string_number(self):
        assert _to_float("123.45") == 123.45

    def test_string_zero(self):
        assert _to_float("0") == 0.0

    def test_inf(self):
        assert _to_float("inf") is None
        assert _to_float("-inf") is None

    def test_non_numeric_string(self):
        assert _to_float("abc") is None

    def test_empty_string(self):
        assert _to_float("") is None


# ---------------------------------------------------------------------------
# _parse_year_from_time
# ---------------------------------------------------------------------------

class TestParseYear:
    def test_plain_year(self):
        assert _parse_year_from_time(2023) == 2023

    def test_string_year(self):
        assert _parse_year_from_time("2023") == 2023

    def test_quarter(self):
        assert _parse_year_from_time("2023Q1") == 2023
        assert _parse_year_from_time("2023q1") == 2023

    def test_month(self):
        assert _parse_year_from_time("2023-06") == 2023

    def test_none(self):
        assert _parse_year_from_time(None) is None

    def test_arbitrary(self):
        assert _parse_year_from_time("Jan 2023") is None


# ---------------------------------------------------------------------------
# World Bank extractor (adapter-transformed format)
# ---------------------------------------------------------------------------

class TestWorldBank:
    def test_basic(self):
        # Adapter output (after compare() transform):
        raw = {
            "country": "Azerbaijan",
            "iso3": "AZE",
            "indicator": "GDP per capita (current US$)",
            "year": "2022",
            "value": 2.5,
        }
        dp = extract_worldbank(raw)
        assert dp.country == "Azerbaijan"
        assert dp.iso3 == "AZE"
        assert dp.year == 2022
        assert dp.period == "2022"
        assert dp.value == 2.5
        assert dp.indicator_code == "GDP per capita (current US$)"
        assert dp.source_id == "world_bank"
        assert "_raw" in dp.metadata

    def test_raw_api_format(self):
        # Raw API format (nested country/indicator dicts):
        raw = {
            "country": {"id": "AZ", "value": "Azerbaijan"},
            "countryiso3code": "AZE",
            "date": 2022,
            "value": 2.5,
            "indicator": {"id": "NY.GDP.PCAP.CD", "value": "GDP per capita"},
        }
        dp = extract_worldbank(raw)
        assert dp.country == "Azerbaijan"
        assert dp.iso3 == "AZE"
        assert dp.year == 2022
        assert dp.value == 2.5
        assert dp.indicator_code == "GDP per capita"

    def test_null_value(self):
        raw = {
            "country": "World",
            "iso3": "WLD",
            "year": "2020",
            "value": None,
            "indicator": "SP.POP.TOTL",
        }
        dp = extract_worldbank(raw)
        assert dp.value is None

    def test_source_id_override(self):
        raw = {"country": "X", "year": "2021", "value": 1.0, "indicator": "X"}
        dp = extract_worldbank(raw, source_id="custom_wb")
        assert dp.source_id == "custom_wb"

    def test_gdp_kd_unit(self):
        """GDP not KD → unit=USD; GDP KD → unit=None."""
        raw = {"country": "X", "year": "2021", "value": 1.0,
               "indicator": "NY.GDP.MKTP.KD.ZG"}
        dp = extract_worldbank(raw)
        assert dp.unit is None  # KD series

        raw2 = {"country": "X", "year": "2021", "value": 1.0,
                "indicator": "NY.GDP.MKTP.CD"}
        dp2 = extract_worldbank(raw2)
        assert dp2.unit == "USD"


# ---------------------------------------------------------------------------
# Eurostat extractor (adapter-transformed format)
# ---------------------------------------------------------------------------

class TestEurostat:
    def test_basic(self):
        # Adapter output (after get_indicator() transform):
        raw = {
            "country": "AZ",
            "iso3": "AZ",
            "indicator": "une_rt_a",
            "year": "2022",
            "value": "5.2",
        }
        dp = extract_eurostat(raw)
        assert dp.country == "AZ"
        assert dp.iso3 == "AZ"
        assert dp.period == "2022"
        assert dp.year == 2022
        assert dp.value == 5.2
        assert dp.indicator_code == "une_rt_a"

    def test_null_value(self):
        raw = {"country": "EU", "iso3": "EU", "year": "2020", "value": None, "indicator": "xyz"}
        dp = extract_eurostat(raw)
        assert dp.value is None

    def test_raw_api_format(self):
        # Raw JSON-stat API format:
        raw = {
            "geo": "AZ",
            "time": "2022",
            "value": 5.2,
            "unit": "IND",
            "indicator": "une_rt_a",
        }
        dp = extract_eurostat(raw)
        assert dp.country == "AZ"
        assert dp.period == "2022"
        assert dp.year == 2022
        assert dp.value == 5.2
        assert dp.unit == "IND"


# ---------------------------------------------------------------------------
# IMF extractor (adapter-transformed format)
# ---------------------------------------------------------------------------

class TestIMF:
    def test_adapter_format(self):
        # Adapter output (after get_series() transform):
        raw = {
            "country": "AZE",
            "iso3": "AZE",
            "indicator": "NGDP_R_XDC",
            "year": "2022",
            "value": "3.1",
        }
        dp = extract_imf(raw)
        assert dp.country == "AZE"
        assert dp.iso3 == "AZE"
        assert dp.year == 2022
        assert dp.value == 3.1
        assert dp.indicator_code == "NGDP_R_XDC"

    def test_raw_api_format(self):
        # Raw SDMX-JSON format:
        raw = {
            "@REF_AREA": "AZE",
            "@TIME_PERIOD": "2022",
            "@OBS_VALUE": 3.1,
            "UNIT": "ID",
            "INDICATOR": "NGDP_R_XDC",
        }
        dp = extract_imf(raw)
        assert dp.country == "AZE"
        assert dp.iso3 == "AZE"
        assert dp.year == 2022
        assert dp.value == 3.1
        assert dp.unit == "ID"

    def test_none_value(self):
        raw = {"country": "X", "iso3": "XXX", "year": "2020", "value": None, "indicator": "X"}
        dp = extract_imf(raw)
        assert dp.value is None

    def test_list_obs_raw(self):
        # Raw API with Obs list (for SDMX response):
        raw = {
            "@REF_AREA": "TUR",
            "@TIME_PERIOD": "2021",
            "@OBS_VALUE": 4.0,
        }
        dp = extract_imf(raw)
        assert dp.country == "TUR"
        assert dp.value == 4.0


# ---------------------------------------------------------------------------
# CBR extractor (adapter-transformed format)
# ---------------------------------------------------------------------------

class TestCBR:
    def test_basic(self):
        # Adapter output (after get_daily_rates() transform):
        raw = {
            "currency": "USD",
            "name": "US Dollar",
            "nominal": 1,
            "value_rub": 83.50,
            "date": "2023-08-01",
        }
        dp = extract_cbr(raw)
        assert dp.country == "RU"
        assert dp.iso3 == "RUS"
        assert dp.period == "2023-08-01"
        assert dp.year == 2023
        assert dp.value == 83.50
        assert dp.unit == "USD"
        assert dp.indicator_code == "USD"

    def test_null_rate(self):
        raw = {"currency": "EUR", "name": "Euro", "nominal": 1,
               "value_rub": None, "date": "2023-08-01"}
        dp = extract_cbr(raw)
        assert dp.value is None

    def test_nominal_division(self):
        raw = {"currency": "EUR", "name": "Euro", "nominal": 5,
               "value_rub": 417.5, "date": "2023-08-01"}
        dp = extract_cbr(raw)
        assert dp.value == 83.50  # 417.5 / 5


# ---------------------------------------------------------------------------
# CKAN extractor
# ---------------------------------------------------------------------------

class TestCKAN:
    def test_basic(self):
        raw = {
            "country": "Azerbaijan",
            "year": 2022,
            "value": 1500000,
            "unit": "people",
            "indicator_code": "population_total",
        }
        dp = extract_ckan(raw)
        assert dp.country == "Azerbaijan"
        assert dp.period == "2022"
        assert dp.year == 2022
        assert dp.value == 1500000.0
        assert dp.unit == "people"
        assert dp.indicator_code == "population_total"

    def test_global_default(self):
        raw = {"year": 2020, "value": 100}
        dp = extract_ckan(raw)
        assert dp.country == "global"
        assert dp.iso3 is None


# ---------------------------------------------------------------------------
# Dispatch: extract_data
# ---------------------------------------------------------------------------

class TestExtractData:
    def test_world_bank(self):
        rows = [{"country": "AZ", "iso3": "AZE",
                 "year": "2022", "value": 2.5, "indicator": "X"}]
        points = extract_data(rows, "world_bank", "NY.GDP.MKTP.KD.ZG")
        assert len(points) == 1
        assert points[0].indicator_code == "NY.GDP.MKTP.KD.ZG"
        assert points[0].value == 2.5

    def test_generic_extractor(self):
        rows = [{"country": "TestLand", "value": 42, "year": 2021}]
        points = extract_data(rows, "unknown_source", "test_code")
        assert len(points) == 1
        assert points[0].country == "TestLand"
        assert points[0].value == 42.0
        assert points[0].indicator_code == "test_code"
        assert points[0].source_id == "unknown_source"

    def test_multiple_rows(self):
        rows = [
            {"country": "AZ", "iso3": "AZE", "year": "2021", "value": 1.0, "indicator": "X"},
            {"country": "AZ", "iso3": "AZE", "year": "2022", "value": 2.0, "indicator": "X"},
        ]
        points = extract_data(rows, "world_bank", "X")
        assert len(points) == 2
        assert points[0].year == 2021
        assert points[1].year == 2022


# ---------------------------------------------------------------------------
# Generic extractor
# ---------------------------------------------------------------------------

class TestGenericExtractor:
    def test_upper_case_keys(self):
        raw = {"Country": "Test", "ISO3": "TST", "Year": 2020, "Value": 99}
        dp = _extract_generic(raw, "test_source")
        assert dp.country == "Test"
        assert dp.iso3 == "TST"
        assert dp.year == 2020
        assert dp.value == 99.0

    def test_empty_raw(self):
        dp = _extract_generic({}, "test")
        assert dp.country == ""
        assert dp.value is None
        assert dp.indicator_code == ""

    def test_metadata_preserves_raw(self):
        raw = {"foo": "bar", "value": 1}
        dp = _extract_generic(raw, "test")
        assert dp.metadata == {"_raw": raw}


# ---------------------------------------------------------------------------
# DataPoint.to_dict
# ---------------------------------------------------------------------------

class TestDataPoint:
    def test_to_dict(self):
        dp = DataPoint(country="AZ", year=2023, value=42.0)
        d = dp.to_dict()
        assert d["country"] == "AZ"
        assert d["year"] == 2023
        assert d["value"] == 42.0
        assert d["iso3"] is None
        assert d["metadata"] == {}

    def test_empty_defaults(self):
        dp = DataPoint(country="")
        assert dp.period == ""
        assert dp.source_id == ""
        assert dp.indicator_code == ""