"""
Phase 10 — Normalization Engine tests.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from collector.collection import DataPoint
from collector.normalization import (
    normalize_currency,
    normalize_percentage,
    normalize_scale,
    normalize_value,
    normalize_all,
    NormalizeResult,
    CURRENCY_RATES,
)


# ---------------------------------------------------------------------------
# Currency normalization
# ---------------------------------------------------------------------------

class TestNormalizeCurrency:
    def test_usd_to_usd_no_change(self):
        val, detail = normalize_currency(100.0, "USD", "USD")
        assert val == 100.0

    def test_usd_to_azn(self):
        val, detail = normalize_currency(100.0, "USD", "AZN")
        # 100 USD / 1.0 * 1.70 = 170 AZN
        assert val == pytest.approx(170.0, abs=0.01)
        assert "USD" in detail

    def test_eur_to_usd(self):
        val, detail = normalize_currency(100.0, "EUR", "USD")
        # 100 EUR / 1.08 * 1.0 = 92.59 USD
        assert val == pytest.approx(92.59, abs=0.1)

    def test_unknown_from_currency(self):
        val, detail = normalize_currency(100.0, "XYZ", "USD")
        assert val == 100.0  # Returns original on unknown
        assert "Unknown" in detail

    def test_unknown_to_currency(self):
        val, detail = normalize_currency(100.0, "USD", "XYZ")
        assert val == 100.0
        assert "Unknown" in detail

    def test_none_value(self):
        val, detail = normalize_currency(None, "USD", "AZN")
        assert val is None

    def test_case_insensitive(self):
        val, _ = normalize_currency(100.0, "usd", "azn")
        assert val == pytest.approx(170.0, abs=0.01)


# ---------------------------------------------------------------------------
# Percentage normalization
# ---------------------------------------------------------------------------

class TestNormalizePercentage:
    def test_percentage_with_unit(self):
        val, detail = normalize_percentage(5.2, "%")
        assert val == pytest.approx(0.052, abs=0.001)
        assert "Percentage" in detail

    def test_percentage_pct_unit(self):
        val, detail = normalize_percentage(10.0, "PCT")
        assert val == pytest.approx(0.1, abs=0.001)

    def test_not_percentage(self):
        val, detail = normalize_percentage(1500000.0, "people")
        assert val == 1500000.0
        assert "Already decimal" in detail

    def test_no_unit(self):
        val, detail = normalize_percentage(5.2, None)
        assert val == 5.2
        assert "Already decimal" in detail

    def test_none_value(self):
        val, detail = normalize_percentage(None, "%")
        assert val is None

    def test_zero_percentage(self):
        val, detail = normalize_percentage(0.0, "%")
        assert val == 0.0


# ---------------------------------------------------------------------------
# Scale normalization
# ---------------------------------------------------------------------------

class TestNormalizeScale:
    def test_billion(self):
        val, detail = normalize_scale(2.5, "Billion USD", "NY.GDP")
        assert val == pytest.approx(2.5e9, abs=1)
        assert "billion" in detail

    def test_million(self):
        val, detail = normalize_scale(3.0, "Million USD", "SP.POP")
        assert val == pytest.approx(3.0e6, abs=1)
        assert "million" in detail

    def test_thousand(self):
        val, detail = normalize_scale(5.0, "Thousand USD", "X")
        assert val == pytest.approx(5000.0, abs=1)
        assert "thousand" in detail

    def test_no_scale(self):
        val, detail = normalize_scale(100.0, "USD", "X")
        assert val == 100.0
        assert "No scale" in detail

    def test_indicator_code_hint(self):
        val, detail = normalize_scale(2.5, None, "GDP_BILLION_USD")
        assert val == pytest.approx(2.5e9, abs=1)

    def test_none_value(self):
        val, detail = normalize_scale(None, "Billion USD", "X")
        assert val is None


# ---------------------------------------------------------------------------
# Full normalize_value
# ---------------------------------------------------------------------------

class TestNormalizeValue:
    def test_percentage_only(self):
        val, details = normalize_value(5.2, "%", "NY.GDP.MKTP.KD.ZG")
        assert val == pytest.approx(0.052, abs=0.001)
        assert len(details) >= 1

    def test_scale_only(self):
        val, details = normalize_value(2.5, "Billion USD", "NY.GDP.MKTP.CD")
        assert val == pytest.approx(2.5e9, abs=1)

    def test_no_normalization_needed(self):
        val, details = normalize_value(42.0, "USD", "NY.GDP.MKTP.CD")
        assert val == 42.0
        assert len(details) == 0

    def test_currency_conversion(self):
        val, details = normalize_value(100.0, "EUR", "X")
        assert val == pytest.approx(100.0 / 1.08, abs=0.1)
        assert any("EUR" in d for d in details)

    def test_none_value(self):
        val, details = normalize_value(None, "%", "X")
        assert val is None
        assert len(details) == 0


# ---------------------------------------------------------------------------
# Batch normalization (normalize_all)
# ---------------------------------------------------------------------------

class TestNormalizeAll:
    def test_empty_batch(self):
        result = normalize_all([])
        assert result.data_points == []
        assert result.normalizations == []

    def test_normal_values_no_change(self):
        # Both units are already USD → no normalization
        points = [
            DataPoint(country="AZ", value=42.0, unit="USD", indicator_code="X"),
            DataPoint(country="AZ", value=100.0, unit="USD", indicator_code="Y"),
        ]
        result = normalize_all(points, target_currency="USD")
        assert len(result.data_points) == 2
        assert result.normalizations == []

    def test_original_preserved(self):
        points = [DataPoint(country="AZ", value=5.2, unit="%", indicator_code="X")]
        result = normalize_all(points)
        assert result.data_points[0].metadata["_original_value"] == 5.2

    def test_percentage_normalized(self):
        points = [DataPoint(country="AZ", value=5.2, unit="%", indicator_code="X")]
        result = normalize_all(points)
        assert result.data_points[0].value == pytest.approx(0.052, abs=0.001)
        assert len(result.normalizations) == 1

    def test_mixed_validity(self):
        points = [
            DataPoint(country="AZ", value=5.2, unit="%", indicator_code="X"),
            DataPoint(country="AZ", value=None, unit="USD", indicator_code="Y"),
        ]
        result = normalize_all(points)
        assert result.data_points[0].value == pytest.approx(0.052, abs=0.001)
        assert result.data_points[1].value is None

    def test_normalization_records_metadata(self):
        points = [DataPoint(country="AZ", value=5.2, unit="%", indicator_code="X")]
        result = normalize_all(points)
        history = result.data_points[0].metadata.get("_normalizations", [])
        assert len(history) >= 1
        assert history[0]["step"] == "percentage"
        assert history[0]["original"] == 5.2

    def test_currency_normalization_batch(self):
        points = [
            DataPoint(country="AZ", value=100.0, unit="EUR", indicator_code="X"),
        ]
        result = normalize_all(points, target_currency="USD")
        assert result.data_points[0].value == pytest.approx(100.0 / 1.08, abs=0.1)
        assert len(result.normalizations) == 1
        assert result.normalizations[0].step == "currency"