"""
Phase 15 — Query Orchestrator.

Wires the full data collection pipeline:
  NL parser → semantic resolver → collection plan → fallback runner →
  extract_data → normalization → validation → provenance →
  derived metrics → cross-source → final JSON

Also adds `--query` CLI entry point.
"""

import json
import logging
from typing import Any

from collector.collection import DataPoint
from collector.collection_plan import build_plan_from_parsed
from collector.fallback_runner import run_fallback
from collector.provenance import ProvenanceTracker, extract_with_trace
from collector.derived_metrics import apply_recipes

logger = logging.getLogger("collector.orchestrator")


def run_query(
    conn,
    query_text: str,
    current_year: int = 2025,
) -> dict:
    """Execute a full data query pipeline.

    Args:
        conn: Database connection.
        query_text: Natural language query string.
        current_year: Reference year for period parsing.

    Returns:
        Full response dict with query, plan, results, cross-source quality, metadata.
    """
    # Step 1: Parse natural language
    from collector.nl_parser import parse_and_check
    parsed = parse_and_check(query_text, current_year)

    # Step 2: Resolve semantic concepts
    from collector.semantic_resolver import seed_concepts, seed_concept_mappings_from_synonyms
    try:
        concepts = seed_concepts(conn)
        seed_concept_mappings_from_synonyms(conn, concepts)
    except Exception as e:
        logger.warning("Semantic seeding failed: %s", e)
        concepts = []

    # Step 3: Build collection plan
    countries = parsed.get("countries", ["global"])
    concept = parsed.get("concepts", [{}])[0] if parsed.get("concepts") else {}
    concept_id = concept.get("concept_id", "")
    period_start = parsed.get("period_start")
    period_end = parsed.get("period_end")

    try:
        plan = build_plan_from_parsed(parsed, conn)
        plan_dict = plan.to_dict() if plan else {}
    except Exception as e:
        logger.error("Plan building failed: %s", e)
        plan_dict = {}

    # Step 4: Run fallback for each candidate
    all_data_points: list[DataPoint] = []
    attempts_summary: list[dict] = []
    run_id = None

    if concept_id:
        candidates = plan_dict.get("candidates", []) if plan_dict else []

        if candidates:
            result = run_fallback(
                conn,
                concept_id=concept_id,
                countries=countries,
                period_start=period_start,
                period_end=period_end,
            )

            run_id = result.get("run_id")
            attempts_summary = result.get("attempts", [])

            if result.get("success") and result.get("records"):
                # Step 5: Extract DataPoints
                tracker = ProvenanceTracker(run_id=run_id, source_id=result.get("selected_source", ""))
                points = extract_with_trace(
                    result["records"],
                    result.get("selected_source", ""),
                    concept_id,
                    tracker,
                )
                all_data_points.extend(points)

    # Step 6: Normalize
    from collector.normalization import normalize_all
    if all_data_points:
        norm_result = normalize_all(all_data_points)
        all_data_points = norm_result.data_points

    # Step 7: Validate
    from collector.validation import validate_batch, filter_valid
    if all_data_points:
        validate_batch(all_data_points)
        all_data_points = filter_valid(all_data_points)

    # Step 8: Apply derived metrics
    from collector.derived_metrics import apply_recipes
    if all_data_points:
        ctx = {}
        if len(all_data_points) > 1:
            ctx["previous"] = all_data_points[-2].value if all_data_points[-2].value else 0
        apply_recipes(all_data_points, context=ctx)

    # Step 9: Cross-source validation
    from collector.cross_source import cross_source_quality_score
    quality = cross_source_quality_score(all_data_points)

    # Step 10: Build response
    results = []
    for dp in all_data_points:
        validation = dp.metadata.get("_validation", {})
        derived = dp.metadata.get("_derived", {})
        provenance = dp.metadata.get("_provenance", [])

        results.append({
            "indicator_code": dp.indicator_code,
            "source_id": dp.source_id,
            "country": dp.country,
            "period": dp.period,
            "year": dp.year,
            "value": dp.value,
            "original_value": dp.metadata.get("_original_value"),
            "status": validation.get("status", "unknown"),
            "normalized_value": dp.value,
            "derived": derived,
            "provenance": provenance[-3:],  # Last 3 transformations
            "cross_source_consensus": None,  # Set below
        })

    return {
        "query": query_text,
        "parsed": {
            "concepts": concepts,
            "countries": countries,
            "period_start": period_start,
            "period_end": period_end,
        },
        "plan": plan_dict,
        "results": results,
        "cross_source_quality": quality,
        "metadata": {
            "total_points": len(all_data_points),
            "valid_points": sum(
                1 for r in results if r["status"] == "valid"
            ),
            "run_id": run_id,
            "attempts": len(attempts_summary),
        },
    }


class Orchestrator:
    """Object-oriented wrapper for the query pipeline."""

    def __init__(self, conn, current_year: int = 2025):
        self.conn = conn
        self.current_year = current_year

    def query(self, query_text: str) -> dict:
        """Execute a natural language query."""
        return run_query(
            self.conn, query_text, current_year=self.current_year
        )

    def query_parsed(self, parsed_result: dict) -> dict:
        """Execute with already-parsed input (skip NL parsing)."""
        from collector.collection_plan import build_plan_from_parsed

        countries = parsed_result.get("countries", ["global"])
        concept = parsed_result.get("concepts", [{}])[0] if parsed_result.get("concepts") else {}
        concept_id = concept.get("concept_id", "")
        period_start = parsed_result.get("period_start")
        period_end = parsed_result.get("period_end")

        try:
            plan = build_plan_from_parsed(parsed_result, self.conn)
            plan_dict = plan.to_dict() if plan else {}
        except Exception:
            plan_dict = {}

        # Run fallback
        all_data_points = []
        run_id = None
        attempts_summary = []

        if concept_id:
            candidates = plan_dict.get("candidates", [])
            if candidates:
                result = run_fallback(
                    self.conn,
                    concept_id=concept_id,
                    countries=countries,
                    period_start=period_start,
                    period_end=period_end,
                )
                run_id = result.get("run_id")
                attempts_summary = result.get("attempts", [])

                if result.get("success") and result.get("records"):
                    tracker = ProvenanceTracker(
                        run_id=run_id,
                        source_id=result.get("selected_source", ""),
                    )
                    points = extract_with_trace(
                        result["records"],
                        result.get("selected_source", ""),
                        concept_id,
                        tracker,
                    )
                    all_data_points.extend(points)

        # Normalize
        from collector.normalization import normalize_all
        if all_data_points:
            all_data_points = normalize_all(all_data_points).data_points

        # Validate
        from collector.validation import validate_batch, filter_valid
        if all_data_points:
            validate_batch(all_data_points)
            all_data_points = filter_valid(all_data_points)

        # Derived metrics
        from collector.derived_metrics import apply_recipes
        if all_data_points:
            ctx = {}
            if len(all_data_points) > 1:
                ctx["previous"] = all_data_points[-2].value if all_data_points[-2].value else 0
            apply_recipes(all_data_points, context=ctx)

        # Cross-source quality
        from collector.cross_source import cross_source_quality_score
        quality = cross_source_quality_score(all_data_points)

        # Build response
        results = []
        for dp in all_data_points:
            validation = dp.metadata.get("_validation", {})
            derived = dp.metadata.get("_derived", {})
            provenance = dp.metadata.get("_provenance", [])
            results.append({
                "indicator_code": dp.indicator_code,
                "source_id": dp.source_id,
                "country": dp.country,
                "period": dp.period,
                "value": dp.value,
                "original_value": dp.metadata.get("_original_value"),
                "status": validation.get("status", "unknown"),
                "normalized_value": dp.value,
                "derived": derived,
                "provenance": provenance[-3:],
                "cross_source_consensus": None,
            })

        return {
            "query": "",
            "parsed": parsed_result,
            "plan": plan_dict,
            "results": results,
            "cross_source_quality": quality,
            "metadata": {
                "total_points": len(all_data_points),
                "valid_points": sum(1 for r in results if r["status"] == "valid"),
                "run_id": run_id,
                "attempts": len(attempts_summary),
            },
        }

    def get_raw_results(self, concept_id: str, country: str,
                        start_year: int, end_year: int) -> list[dict]:
        """Get raw results without processing (for debugging)."""
        result = run_fallback(
            self.conn,
            concept_id=concept_id,
            countries=[country],
            period_start=start_year,
            period_end=end_year,
        )
        return {
            "success": result.get("success"),
            "records": result.get("records", []),
            "attempts": result.get("attempts", []),
            "selected_source": result.get("selected_source"),
            "selected_indicator": result.get("selected_indicator"),
            "run_id": result.get("run_id"),
        }