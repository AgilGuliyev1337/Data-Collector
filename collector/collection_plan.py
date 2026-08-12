"""
Phase 7 — Collection Plan Engine.

Takes a parsed NL requirement (from Phase 6) and catalogue/concept metadata,
then builds a ranked CollectionPlan: which source→dataset to query first,
second, etc.

Plan JSON shape:
{
  "concept": str,
  "country": str,
  "period_start": int,
  "period_end": int,
  "unit": str | None,
  "candidates": [
    {
      "source_id": str,
      "indicator_code": str,
      "dataset_id": str,
      "priority_tier": int,
      "confidence": float,
      "trust_level": str,
    },
    ...
  ]
}

Sort order: priority_tier ASC, confidence DESC (stable tie-breaker per Phase 2B rule).
Deterministic — no LLM in plan construction.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from collector.registry import get_candidate_indicators
from collector.db import repository as repo

logger = logging.getLogger("collector.plan")


@dataclass
class PlanCandidate:
    """A single candidate in the ranked plan."""
    source_id: str
    indicator_code: str
    dataset_id: str
    priority_tier: int
    confidence: float
    trust_level: str
    title: str = ""
    description: str = ""


@dataclass
class CollectionPlan:
    """A ranked plan for data collection."""
    concept: str
    country: str
    period_start: Optional[int] = None
    period_end: Optional[int] = None
    unit: Optional[str] = None
    candidates: list[PlanCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "concept": self.concept,
            "country": self.country,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "unit": self.unit,
            "candidates": [
                {
                    "source_id": c.source_id,
                    "indicator_code": c.indicator_code,
                    "dataset_id": c.dataset_id,
                    "priority_tier": c.priority_tier,
                    "confidence": round(c.confidence, 4),
                    "trust_level": c.trust_level,
                }
                for c in self.candidates
            ],
        }


# ---------------------------------------------------------------------------
# Schema for validation
# ---------------------------------------------------------------------------

PLAN_SCHEMA = {
    "required": ["concept", "country", "candidates"],
    "candidate_required": [
        "source_id", "indicator_code", "dataset_id",
        "priority_tier", "confidence", "trust_level",
    ],
}


def validate_plan(plan_dict: dict) -> tuple[bool, list[str]]:
    """Validate a plan dict against the mandated schema.

    Returns (is_valid, list_of_errors).
    """
    errors: list[str] = []

    if not isinstance(plan_dict, dict):
        return False, ["Plan must be a dict"]

    for key in PLAN_SCHEMA["required"]:
        if key not in plan_dict:
            errors.append(f"Missing required field: {key}")

    if errors:
        return False, errors

    if not isinstance(plan_dict.get("candidates"), list):
        errors.append("'candidates' must be a list")
    elif plan_dict["candidates"]:
        for i, c in enumerate(plan_dict["candidates"]):
            for req in PLAN_SCHEMA["candidate_required"]:
                if req not in c:
                    errors.append(
                        f"Candidate[{i}] missing '{req}'"
                    )

    # Validate confidence range
    for i, c in enumerate(plan_dict.get("candidates", [])):
        conf = c.get("confidence", 0)
        if not (0 <= conf <= 1):
            errors.append(
                f"Candidate[{i}] confidence {conf} out of [0,1]"
            )

    # Validate priority_tier is positive int
    for i, c in enumerate(plan_dict.get("candidates", [])):
        tier = c.get("priority_tier")
        if not isinstance(tier, int) or tier < 1:
            errors.append(
                f"Candidate[{i}] priority_tier must be a positive int"
            )

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------


def build_plan(
    conn,
    concept: str,
    country: str,
    period_start: Optional[int] = None,
    period_end: Optional[int] = None,
    unit: Optional[str] = None,
) -> CollectionPlan:
    """Build a ranked CollectionPlan from parsed requirement + DB catalogue.

    Args:
        conn: DB connection.
        concept: concept_id (e.g. 'gdp_growth', 'unemployment').
        country: ISO country code (e.g. 'AZ').
        period_start: optional start year.
        period_end: optional end year.
        unit: optional expected unit.

    Returns:
        CollectionPlan with candidates sorted by (priority_tier ASC,
        confidence DESC).
    """
    # Query DB for candidate indicators (already sorted by the registry query)
    candidates_raw = get_candidate_indicators(conn, concept)

    # Also filter by country if specified (country_coverage check)
    # NULL/empty coverage → accepts all countries (global scope)
    # Explicit countries → only match if requested country is in coverage
    filtered: list[dict] = []
    for c in candidates_raw:
        coverage = c.get("country_coverage") or []
        if coverage and country not in coverage:
            # Explicitly has country coverage that doesn't include requested country
            continue
        filtered.append(c)

    if not filtered:
        logger.info(
            "Concept '%s' üçün %s ölkəsində heç bir candidate tapılmadı.",
            concept, country,
        )

    plan_candidates = []
    for c in filtered:
        plan_candidates.append(
            PlanCandidate(
                source_id=c["source_id"],
                indicator_code=c["indicator_code"],
                dataset_id=c.get("dataset_id", c["indicator_code"]),
                priority_tier=c["priority_tier"] or 99,
                confidence=c["confidence"],
                trust_level=c.get("trust_level", "unknown"),
                title=c.get("title", ""),
                description=c.get("description", ""),
            )
        )

    # Sort: priority_tier ASC, then confidence DESC (stable)
    plan_candidates.sort(key=lambda pc: (pc.priority_tier, -pc.confidence))

    plan = CollectionPlan(
        concept=concept,
        country=country,
        period_start=period_start,
        period_end=period_end,
        unit=unit,
        candidates=plan_candidates,
    )

    logger.info(
        "Plan constructed: concept=%s country=%s %d candidates",
        concept, country, len(plan.candidates),
    )

    return plan


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def build_plan_from_parsed(parsed_result: dict, conn) -> CollectionPlan:
    """Build a CollectionPlan from a parse_and_check() result dict.

    Convenience wrapper that extracts fields from the NL parser output
    and passes them to build_plan().
    """
    return build_plan(
        conn=conn,
        concept=parsed_result.get("concepts", [None])[0] or "",
        country=parsed_result.get("countries", ["global"])[0] or "global",
        period_start=parsed_result.get("period_start"),
        period_end=parsed_result.get("period_end"),
    )