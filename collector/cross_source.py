"""
Phase 14 — Cross-Source Validation.

Compare same indicator across different sources to detect anomalies.

For each (indicator_code, country, period) group:
- If 2+ sources have data → compare values
- Compute consensus (median for robustness)
- Flag values outside tolerance as anomalies
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from collector.collection import DataPoint

logger = logging.getLogger("collector.cross_source")

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CrossSourceResult:
    """Result of cross-source comparison for one indicator group."""
    indicator_code: str
    country: str
    period: str
    sources: list[dict] = field(default_factory=list)  # [{source_id, value, unit}]
    consensus_value: Optional[float] = None
    anomaly_detected: bool = False
    anomalies: list[str] = field(default_factory=list)


@dataclass
class Discrepancy:
    """A detected discrepancy between sources."""
    indicator_code: str
    country: str
    period: str
    sources: list[str]
    max_deviation_pct: float
    severity: str  # "low", "medium", "high"


# ---------------------------------------------------------------------------
# Core comparison logic
# ---------------------------------------------------------------------------


def _median(values: list[float]) -> Optional[float]:
    """Compute median of a list of numbers."""
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return sorted_vals[mid]


def compare_values(
    values_per_source: list[dict],
    tolerance_multiplier: float = 2.0,
) -> CrossSourceResult:
    """Compare values from multiple sources for the same data point.

    Uses median as consensus (robust to outliers).

    Args:
        values_per_source: [{source_id, value, unit}].
        tolerance_multiplier: Values outside this × median are flagged.

    Returns:
        CrossSourceResult with consensus and anomalies.
    """
    sources = []
    valid_values = []

    for v in values_per_source:
        sid = v.get("source_id", "unknown")
        val = v.get("value")
        unit = v.get("unit")

        if val is not None:
            valid_values.append(float(val))

        sources.append({
            "source_id": sid,
            "value": val,
            "unit": unit,
        })

    # Compute consensus (median)
    consensus = _median(valid_values) if valid_values else None
    anomaly_detected = False
    anomalies = []

    if consensus is not None:
        for s in sources:
            if s["value"] is None:
                continue
            sv = float(s["value"])
            if consensus == 0:
                if sv != 0:
                    anomaly_detected = True
                    anomalies.append(
                        f"{s['source_id']}: {sv} differs from consensus 0"
                    )
                continue

            ratio = abs(sv - consensus) / abs(consensus)
            if ratio > tolerance_multiplier:
                anomaly_detected = True
                deviation_pct = round(ratio * 100, 1)
                anomalies.append(
                    f"{s['source_id']}: {sv} is {deviation_pct}% from consensus ({consensus:.2f})"
                )

    return CrossSourceResult(
        indicator_code="",  # Set by caller
        country="",
        period="",
        sources=sources,
        consensus_value=consensus,
        anomaly_detected=anomaly_detected,
        anomalies=anomalies,
    )


def validate_cross_source(
    points: list[DataPoint],
    tolerance_pct: float = 25.0,
) -> list[CrossSourceResult]:
    """Group points by (indicator, country, period) and compare.

    Args:
        points: DataPoints to compare (should be normalized first).
        tolerance_pct: Values within this % of median are OK.

    Returns:
        List of CrossSourceResult, one per group with 2+ sources.
    """
    # Group by (indicator_code, country, period)
    groups: dict[tuple, list[DataPoint]] = {}
    for dp in points:
        key = (dp.indicator_code, dp.country, dp.period)
        if key not in groups:
            groups[key] = []
        groups[key].append(dp)

    results = []
    for (indicator, country, period), group_points in groups.items():
        if len(group_points) < 2:
            continue  # Need at least 2 sources to compare

        values_per_source = []
        for dp in group_points:
            values_per_source.append({
                "source_id": dp.source_id,
                "value": dp.value,
                "unit": dp.unit,
            })

        result = compare_values(values_per_source, tolerance_multiplier=tolerance_pct / 100.0)
        result.indicator_code = indicator
        result.country = country
        result.period = period
        results.append(result)

    return results


def find_discrepancies(
    points: list[DataPoint],
    tolerance_pct: float = 25.0,
) -> list[dict]:
    """Find discrepancies between sources.

    Args:
        points: DataPoints to analyze.
        tolerance_pct: Percentage tolerance for agreement.

    Returns:
        List of discrepancy reports.
    """
    cross_results = validate_cross_source(points, tolerance_pct)
    discrepancies = []

    for cr in cross_results:
        valid_values = [
            float(s["value"])
            for s in cr.sources
            if s["value"] is not None
        ]
        if len(valid_values) < 2:
            continue

        med = _median(valid_values)
        if med is None or med == 0:
            continue

        max_dev = max(
            abs(float(s["value"]) - med) / abs(med) * 100
            for s in cr.sources
            if s["value"] is not None
        )

        if max_dev > tolerance_pct:
            discrepancies.append({
                "indicator_code": cr.indicator_code,
                "country": cr.country,
                "period": cr.period,
                "sources": [s["source_id"] for s in cr.sources],
                "max_deviation_pct": round(max_dev, 1),
                "severity": "high" if max_dev > 100 else "medium" if max_dev > 50 else "low",
            })

    return discrepancies


def report_anomalies(result: CrossSourceResult) -> list[str]:
    """Human-readable anomaly descriptions.

    Args:
        result: A CrossSourceResult from compare_values/validate_cross_source.

    Returns:
        List of human-readable strings.
    """
    if not result.anomaly_detected:
        return [f"OK: {result.indicator_code} for {result.country}({result.period}) — all sources agree"]

    lines = [f"ANOMALY: {result.indicator_code} for {result.country}({result.period})"]
    if result.consensus_value is not None:
        lines.append(f"  Consensus (median): {result.consensus_value:.2f}")
    for s in result.sources:
        if s["value"] is not None:
            lines.append(f"  {s['source_id']}: {s['value']}")
    for a in result.anomalies:
        lines.append(f"  ⚠ {a}")

    return lines


def cross_source_quality_score(
    points: list[DataPoint],
    tolerance_pct: float = 25.0,
) -> dict:
    """Compute overall cross-source quality for a batch.

    Args:
        points: DataPoints to evaluate.
        tolerance_pct: Tolerance for agreement.

    Returns:
        {
            "total_comparisons": int,
            "agreed": int,
            "warnings": int,
            "conflicts": int,
            "quality": "high" | "medium" | "low",
        }
    """
    results = validate_cross_source(points, tolerance_pct)

    total = len(results)
    agreed = 0
    warnings = 0
    conflicts = 0

    for r in results:
        if not r.anomaly_detected:
            agreed += 1
        elif len(r.anomalies) <= 1:
            warnings += 1
        else:
            conflicts += 1

    if total == 0:
        quality = "high"
    elif conflicts == 0 and warnings == 0:
        quality = "high"
    elif conflicts == 0:
        quality = "medium"
    else:
        quality = "low"

    return {
        "total_comparisons": total,
        "agreed": agreed,
        "warnings": warnings,
        "conflicts": conflicts,
        "quality": quality,
    }