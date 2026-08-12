"""
Phase 14 — Cross-Source Validation tests.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from collector.collection import DataPoint
from collector.cross_source import (
    compare_values,
    validate_cross_source,
    find_discrepancies,
    report_anomalies,
    cross_source_quality_score,
    _median,
    CrossSourceResult,
)


# ---------------------------------------------------------------------------
# _median
# ---------------------------------------------------------------------------

class TestMedian:
    def test_single(self):
        assert _median([5]) == 5

    def test_even_count(self):
        assert _median([1, 3]) == 2.0

    def test_odd_count(self):
        assert _median([1, 3, 5]) == 3

    def test_unsorted(self):
        assert _median([5, 1, 3]) == 3

    def test_empty(self):
        assert _median([]) is None

    def test_all_same(self):
        assert _median([4, 4, 4]) == 4


# ---------------------------------------------------------------------------
# compare_values
# ---------------------------------------------------------------------------

class TestCompareValues:
    def test_identical_values(self):
        vals = [
            {"source_id": "wb", "value": 100, "unit": "USD"},
            {"source_id": "imf", "value": 100, "unit": "USD"},
        ]
        result = compare_values(vals)
        assert result.consensus_value == 100.0
        assert not result.anomaly_detected
        assert result.anomalies == []

    def test_two_x_deviation(self):
        vals = [
            {"source_id": "wb", "value": 100, "unit": "USD"},
            {"source_id": "imf", "value": 5, "unit": "USD"},  # 20x deviation
        ]
        result = compare_values(vals, tolerance_multiplier=0.5)
        # median of [5, 100] = 52.5, both > 50% from median → anomaly
        assert result.consensus_value == 52.5
        assert result.anomaly_detected
        assert len(result.anomalies) >= 1

    def test_three_sources_agreement(self):
        vals = [
            {"source_id": "wb", "value": 100, "unit": "USD"},
            {"source_id": "imf", "value": 102, "unit": "USD"},
            {"source_id": "cbr", "value": 98, "unit": "USD"},
        ]
        result = compare_values(vals)
        assert result.consensus_value == 100.0
        assert not result.anomaly_detected

    def test_median_not_mean(self):
        """Median should be used (robust), not mean."""
        vals = [
            {"source_id": "wb", "value": 100, "unit": "USD"},
            {"source_id": "imf", "value": 100, "unit": "USD"},
            {"source_id": "extreme", "value": 10000, "unit": "USD"},
        ]
        result = compare_values(vals)
        # Median of [100, 100, 10000] = 100
        assert result.consensus_value == 100.0
        # extreme value should be flagged
        assert result.anomaly_detected

    def test_none_values(self):
        vals = [
            {"source_id": "wb", "value": 100, "unit": "USD"},
            {"source_id": "imf", "value": None, "unit": None},
        ]
        result = compare_values(vals)
        assert result.consensus_value == 100.0
        assert not result.anomaly_detected

    def test_negative_values(self):
        vals = [
            {"source_id": "wb", "value": -5, "unit": "%"},
            {"source_id": "imf", "value": -3, "unit": "%"},
        ]
        result = compare_values(vals)
        assert result.consensus_value == -4.0
        assert not result.anomaly_detected


# ---------------------------------------------------------------------------
# validate_cross_source
# ---------------------------------------------------------------------------

class TestValidateCrossSource:
    def test_grouping_by_indicator(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=102, source_id="imf",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=95, source_id="wb",
                      indicator_code="POP", period="2022"),
        ]
        results = validate_cross_source(points)
        # Only GDP has 2+ sources, POP has 1
        assert len(results) == 1
        assert results[0].indicator_code == "GDP"

    def test_no_comparison_for_single_source(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="X", period="2022"),
            DataPoint(country="AZ", value=200, source_id="imf",
                      indicator_code="Y", period="2022"),
        ]
        results = validate_cross_source(points)
        assert len(results) == 0  # Different indicators, no comparison

    def test_different_countries_not_grouped(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="USA", value=100, source_id="imf",
                      indicator_code="GDP", period="2022"),
        ]
        results = validate_cross_source(points)
        assert len(results) == 0  # Different countries

    def test_different_periods_not_grouped(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2021"),
            DataPoint(country="AZ", value=100, source_id="imf",
                      indicator_code="GDP", period="2022"),
        ]
        results = validate_cross_source(points)
        assert len(results) == 0  # Different periods


# ---------------------------------------------------------------------------
# find_discrepancies
# ---------------------------------------------------------------------------

class TestFindDiscrepancies:
    def test_no_discrepancies(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=102, source_id="imf",
                      indicator_code="GDP", period="2022"),
        ]
        discrepancies = find_discrepancies(points, tolerance_pct=25.0)
        assert len(discrepancies) == 0  # Within 25% tolerance

    def test_discrepancy_found(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=20, source_id="imf",
                      indicator_code="GDP", period="2022"),
        ]
        discrepancies = find_discrepancies(points, tolerance_pct=25.0)
        assert len(discrepancies) == 1
        assert discrepancies[0]["max_deviation_pct"] > 25
        assert discrepancies[0]["severity"] in ("low", "medium", "high")

    def test_severity_levels(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=90, source_id="imf",
                      indicator_code="GDP", period="2022"),
        ]
        discrepancies = find_discrepancies(points, tolerance_pct=25.0)
        assert len(discrepancies) == 0  # Only 10% deviation


# ---------------------------------------------------------------------------
# report_anomalies
# ---------------------------------------------------------------------------

class TestReportAnomalies:
    def test_no_anomaly(self):
        result = CrossSourceResult(
            indicator_code="GDP", country="AZ", period="2022",
            consensus_value=100.0, anomaly_detected=False, anomalies=[],
        )
        lines = report_anomalies(result)
        assert "OK" in lines[0]

    def test_anomaly_reported(self):
        result = CrossSourceResult(
            indicator_code="GDP", country="AZ", period="2022",
            consensus_value=100.0, anomaly_detected=True,
            anomalies=["wb: 500 is 400.0% from consensus"],
            sources=[{"source_id": "wb", "value": 500}],
        )
        lines = report_anomalies(result)
        assert "ANOMALY" in lines[0]
        assert "500" in lines[-1]


# ---------------------------------------------------------------------------
# cross_source_quality_score
# ---------------------------------------------------------------------------

class TestCrossSourceQualityScore:
    def test_all_agree(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=102, source_id="imf",
                      indicator_code="GDP", period="2022"),
        ]
        score = cross_source_quality_score(points)
        assert score["quality"] == "high"
        assert score["total_comparisons"] == 1
        assert score["agreed"] == 1

    def test_mixed_quality(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=500, source_id="imf",
                      indicator_code="GDP", period="2022"),
        ]
        score = cross_source_quality_score(points, tolerance_pct=25.0)
        assert score["total_comparisons"] == 1
        # median=300, both 66.7% from median → anomaly
        assert score["quality"] in ("medium", "low")

    def test_no_comparisons(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2022"),
        ]
        score = cross_source_quality_score(points)
        assert score["quality"] == "high"
        assert score["total_comparisons"] == 0

    def test_low_quality_many_conflicts(self):
        points = [
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=500, source_id="imf",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=50, source_id="cbr",
                      indicator_code="GDP", period="2022"),
            DataPoint(country="AZ", value=100, source_id="wb",
                      indicator_code="POP", period="2022"),
            DataPoint(country="AZ", value=900, source_id="imf",
                      indicator_code="POP", period="2022"),
        ]
        score = cross_source_quality_score(points)
        assert score["total_comparisons"] == 2  # GDP + POP