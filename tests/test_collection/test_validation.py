"""
Phase 11 — Validation Engine tests.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from collector.collection import DataPoint
from collector.validation import (
    validate_value,
    validate_batch,
    filter_valid,
    filter_valid_with_result,
    get_validation_summary,
    validate_population,
    validate_gdp_growth,
    validate_unemployment,
    validate_exchange_rate,
    validate_generic,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Population validation
# ---------------------------------------------------------------------------

class TestValidatePopulation:
    def test_valid_population(self):
        checks = validate_population(10_000_000)
        assert all(c.passed for c in checks)

    def test_negative_population(self):
        checks = validate_population(-500)
        assert not checks[0].passed
        assert checks[0].name == "positive"

    def test_too_large(self):
        checks = validate_population(20_000_000_000)
        assert not checks[1].passed
        assert "reasonable_range" in checks[1].name

    def test_none_value(self):
        checks = validate_population(None)
        assert not checks[0].passed
        assert checks[0].name == "not_none"

    def test_non_integer_population(self):
        checks = validate_population(10_500_500.5)
        # Check by name, not index (not_none check only added for None values)
        int_check = [c for c in checks if c.name == "integer"]
        assert len(int_check) == 1
        assert not int_check[0].passed

    def test_zero_population(self):
        checks = validate_population(0)
        assert checks[0].passed  # positive (0 is not negative)
        assert checks[1].passed  # reasonable_range


# ---------------------------------------------------------------------------
# GDP growth validation
# ---------------------------------------------------------------------------

class TestValidateGDPGrowth:
    def test_normal_growth(self):
        checks = validate_gdp_growth(2.5)
        assert all(c.passed for c in checks)

    def test_negative_growth(self):
        checks = validate_gdp_growth(-3.2)
        assert all(c.passed for c in checks)

    def test_extreme_growth(self):
        checks = validate_gdp_growth(200.0)
        assert not checks[1].passed

    def test_very_negative_growth(self):
        checks = validate_gdp_growth(-80.0)
        assert not checks[1].passed

    def test_none_value(self):
        checks = validate_gdp_growth(None)
        assert not checks[0].passed

    def test_boundary_normal(self):
        checks = validate_gdp_growth(50.0)
        assert checks[1].passed  # Exactly at boundary


# ---------------------------------------------------------------------------
# Unemployment validation
# ---------------------------------------------------------------------------

class TestValidateUnemployment:
    def test_normal_rate(self):
        checks = validate_unemployment(5.2)
        assert all(c.passed for c in checks)

    def test_zero_unemployment(self):
        checks = validate_unemployment(0.0)
        assert all(c.passed for c in checks)

    def test_100_percent(self):
        checks = validate_unemployment(100.0)
        assert all(c.passed for c in checks)

    def test_negative_rate(self):
        checks = validate_unemployment(-2.0)
        assert not checks[0].passed

    def test_over_100_percent(self):
        checks = validate_unemployment(150.0)
        assert not checks[1].passed

    def test_none_value(self):
        checks = validate_unemployment(None)
        assert not checks[0].passed


# ---------------------------------------------------------------------------
# Exchange rate validation
# ---------------------------------------------------------------------------

class TestValidateExchangeRate:
    def test_positive_rate(self):
        checks = validate_exchange_rate(83.50)
        assert all(c.passed for c in checks)

    def test_zero_rate(self):
        checks = validate_exchange_rate(0.0)
        assert not checks[0].passed

    def test_negative_rate(self):
        checks = validate_exchange_rate(-5.0)
        assert not checks[0].passed

    def test_none_value(self):
        checks = validate_exchange_rate(None)
        assert not checks[0].passed


# ---------------------------------------------------------------------------
# Generic validation
# ---------------------------------------------------------------------------

class TestValidateGeneric:
    def test_normal_value(self):
        checks = validate_generic(42.0)
        assert all(c.passed for c in checks)

    def test_none_value(self):
        checks = validate_generic(None)
        assert not checks[0].passed

    def test_extreme_value(self):
        checks = validate_generic(1e16)
        assert not checks[2].passed

    def test_large_normal(self):
        checks = validate_generic(1e14)
        assert all(c.passed for c in checks)

    def test_negative_value(self):
        checks = validate_generic(-100.0)
        # Negative is OK for generic validation
        assert checks[0].passed  # has_value


# ---------------------------------------------------------------------------
# validate_value (full pipeline)
# ---------------------------------------------------------------------------

class TestValidateValue:
    def test_population_indicator(self):
        status, msgs, checks = validate_value(10_000_000, "SP.POP.TOTL")
        assert status == "valid"

    def test_gdp_growth_indicator(self):
        status, msgs, checks = validate_value(2.5, "NY.GDP.MKTP.KD.ZG")
        assert status == "valid"

    def test_unemployment_indicator(self):
        status, msgs, checks = validate_value(5.0, "SL.UEM.TOTL.ZS")
        assert status == "valid"

    def test_unknown_indicator(self):
        status, msgs, checks = validate_value(42.0, "UNKNOWN_INDICATOR")
        assert status == "valid"

    def test_none_with_indicator(self):
        status, msgs, checks = validate_value(None, "SP.POP.TOTL")
        assert status == "invalid"

    def test_extreme_gdp_growth(self):
        status, msgs, checks = validate_value(200.0, "NY.GDP.MKTP.KD.ZG")
        assert status == "warning"


# ---------------------------------------------------------------------------
# validate_batch
# ---------------------------------------------------------------------------

class TestValidateBatch:
    def test_all_valid(self):
        points = [
            DataPoint(country="AZ", value=10_000_000, indicator_code="SP.POP.TOTL"),
            DataPoint(country="AZ", value=2.5, indicator_code="NY.GDP.MKTP.KD.ZG"),
        ]
        results = validate_batch(points)
        assert len(results) == 2
        assert all(r.status == "valid" for r in results)

    def test_mixed_statuses(self):
        points = [
            DataPoint(country="AZ", value=10_000_000, indicator_code="SP.POP.TOTL"),
            DataPoint(country="AZ", value=None, indicator_code="SP.POP.TOTL"),
            DataPoint(country="AZ", value=200.0, indicator_code="NY.GDP.MKTP.KD.ZG"),
        ]
        results = validate_batch(points)
        statuses = [r.status for r in results]
        assert "valid" in statuses
        assert "invalid" in statuses
        assert "warning" in statuses

    def test_metadata_stored(self):
        points = [DataPoint(country="AZ", value=5.0, indicator_code="SL.UEM.TOTL.ZS")]
        validate_batch(points)
        assert "_validation" in points[0].metadata
        assert points[0].metadata["_validation"]["status"] == "valid"


# ---------------------------------------------------------------------------
# filter_valid / filter_valid_with_result
# ---------------------------------------------------------------------------

class TestFilterValid:
    def test_filter_all_valid(self):
        points = [
            DataPoint(country="AZ", value=10_000_000, indicator_code="SP.POP.TOTL"),
        ]
        validate_batch(points)
        filtered = filter_valid(points)
        assert len(filtered) == 1

    def test_filter_removes_invalid(self):
        points = [
            DataPoint(country="AZ", value=10_000_000, indicator_code="SP.POP.TOTL"),
            DataPoint(country="AZ", value=None, indicator_code="SP.POP.TOTL"),
        ]
        validate_batch(points)
        filtered = filter_valid(points)
        assert len(filtered) == 1
        assert filtered[0].value == 10_000_000

    def test_filter_with_warnings(self):
        points = [
            DataPoint(country="AZ", value=10_000_000, indicator_code="SP.POP.TOTL"),
            DataPoint(country="AZ", value=200.0, indicator_code="NY.GDP.MKTP.KD.ZG"),
        ]
        validate_batch(points)
        # Without warnings
        filtered = filter_valid(points)
        assert len(filtered) == 1
        # With warnings
        filtered_warn = filter_valid_with_result(points, include_warnings=True)
        assert len(filtered_warn) == 2


# ---------------------------------------------------------------------------
# get_validation_summary
# ---------------------------------------------------------------------------

class TestValidationSummary:
    def test_all_valid(self):
        results = [
            ValidationResult(point=DataPoint(country="AZ"), status="valid"),
            ValidationResult(point=DataPoint(country="AZ"), status="valid"),
        ]
        summary = get_validation_summary(results)
        assert summary["total"] == 2
        assert summary["valid"] == 2
        assert summary["invalid"] == 0
        assert summary["pass_rate"] == 1.0

    def test_mixed(self):
        results = [
            ValidationResult(point=DataPoint(country="AZ"), status="valid"),
            ValidationResult(point=DataPoint(country="AZ"), status="warning"),
            ValidationResult(point=DataPoint(country="AZ"), status="invalid"),
        ]
        summary = get_validation_summary(results)
        assert summary["total"] == 3
        assert summary["valid"] == 1
        assert summary["warning"] == 1
        assert summary["invalid"] == 1
        assert summary["pass_rate"] == pytest.approx(1/3, abs=0.01)

    def test_empty(self):
        summary = get_validation_summary([])
        assert summary["total"] == 0
        assert summary["pass_rate"] == 0.0