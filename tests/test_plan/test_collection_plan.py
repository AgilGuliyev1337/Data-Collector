"""
Phase 7 — Collection Plan Engine tests.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from collector.collection_plan import (
    build_plan,
    build_plan_from_parsed,
    validate_plan,
    PlanCandidate,
    CollectionPlan,
)


# ---------------------------------------------------------------------------
# Schema validation tests (no DB needed)
# ---------------------------------------------------------------------------

class TestValidatePlan:
    def test_valid_plan(self):
        plan = {
            "concept": "gdp_growth",
            "country": "AZ",
            "candidates": [
                {
                    "source_id": "world_bank",
                    "indicator_code": "NY.GDP.MKTP.KD.ZG",
                    "dataset_id": "WDI",
                    "priority_tier": 4,
                    "confidence": 0.95,
                    "trust_level": "official",
                }
            ],
        }
        valid, errors = validate_plan(plan)
        assert valid is True
        assert errors == []

    def test_missing_concept(self):
        plan = {"country": "AZ", "candidates": []}
        valid, errors = validate_plan(plan)
        assert valid is False

    def test_missing_candidates(self):
        plan = {"concept": "gdp_growth", "country": "AZ"}
        valid, errors = validate_plan(plan)
        assert valid is False

    def test_invalid_confidence(self):
        plan = {
            "concept": "gdp_growth", "country": "AZ",
            "candidates": [{"source_id": "wb", "indicator_code": "t",
                           "dataset_id": "t", "priority_tier": 4,
                           "confidence": 1.5, "trust_level": "official"}],
        }
        valid, errors = validate_plan(plan)
        assert valid is False

    def test_invalid_tier(self):
        plan = {
            "concept": "gdp_growth", "country": "AZ",
            "candidates": [{"source_id": "wb", "indicator_code": "t",
                           "dataset_id": "t", "priority_tier": -1,
                           "confidence": 0.9, "trust_level": "official"}],
        }
        valid, errors = validate_plan(plan)
        assert valid is False

    def test_not_a_dict(self):
        valid, errors = validate_plan("not a dict")
        assert valid is False

    def test_candidate_missing_fields(self):
        plan = {
            "concept": "gdp_growth", "country": "AZ",
            "candidates": [{"source_id": "wb"}],
        }
        valid, errors = validate_plan(plan)
        assert valid is False
        assert len(errors) >= 3


# ---------------------------------------------------------------------------
# Dataclass tests (no DB needed)
# ---------------------------------------------------------------------------

class TestDataclasses:
    def test_plan_to_dict(self):
        plan = CollectionPlan(
            concept="gdp_growth", country="AZ", period_start=2020,
            period_end=2024, unit="%",
            candidates=[PlanCandidate(
                source_id="world_bank", indicator_code="NY.GDP.MKTP.KD.ZG",
                dataset_id="WDI", priority_tier=4, confidence=0.95,
                trust_level="official",
            )],
        )
        d = plan.to_dict()
        assert d["concept"] == "gdp_growth"
        assert d["country"] == "AZ"
        assert d["period_start"] == 2020
        assert d["period_end"] == 2024
        assert d["unit"] == "%"
        assert len(d["candidates"]) == 1
        assert d["candidates"][0]["confidence"] == 0.95

    def test_plan_empty_candidates(self):
        plan = CollectionPlan(concept="gdp_growth", country="AZ")
        d = plan.to_dict()
        assert d["candidates"] == []
        assert d["period_start"] is None
        assert d["unit"] is None