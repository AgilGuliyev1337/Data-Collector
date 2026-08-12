"""
Phase 12 — Provenance Tracking.

Full lineage audit trail for all data transformations.

Tracks:
- Extraction: raw API → DataPoint
- Normalization: original → normalized values
- Validation: each check result
- Derived metrics: formula → computed value

Provenance data is stored:
- In DataPoint.metadata["_provenance"] per-point
- In ProvenanceTracker for batch-level history
- Serializable as JSON for DB storage
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from collector.collection import DataPoint

logger = logging.getLogger("collector.provenance")

# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


@dataclass
class ProvenanceRecord:
    """A single provenance record tracking one transformation."""
    transform_type: str  # "extraction", "normalization", "validation", "derived"
    source_run_id: Optional[int]
    source_indicator: str
    input_value: Any
    output_value: Any
    transformation_details: dict = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "transform_type": self.transform_type,
            "source_run_id": self.source_run_id,
            "source_indicator": self.source_indicator,
            "input_value": self.input_value,
            "output_value": self.output_value,
            "transformation_details": self.transformation_details,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class AuditLog:
    """Complete audit log for a collection run."""
    run_id: int
    source_id: str
    entries: list[ProvenanceRecord] = field(default_factory=list)

    def add(self, record: ProvenanceRecord):
        self.entries.append(record)

    @property
    def summary(self) -> dict:
        """Count transforms by type."""
        by_type: dict[str, int] = {}
        for e in self.entries:
            by_type[e.transform_type] = by_type.get(e.transform_type, 0) + 1
        return {
            "total_records": len(self.entries),
            "transforms_by_type": by_type,
        }

    def to_audit_log(self) -> list[dict]:
        """Serialize to list of dicts for DB storage."""
        return [e.to_dict() for e in self.entries]

    def to_json(self) -> str:
        return json.dumps({
            "run_id": self.run_id,
            "source_id": self.source_id,
            "summary": self.summary,
            "entries": self.to_audit_log(),
        }, default=str, indent=2)


# ---------------------------------------------------------------------------
# ProvenanceTracker
# ---------------------------------------------------------------------------


class ProvenanceTracker:
    """Tracks provenance records for a single data pipeline run."""

    def __init__(self, run_id: int, source_id: str):
        self.run_id = run_id
        self.source_id = source_id
        self._records: list[ProvenanceRecord] = []

    def record(
        self,
        transform_type: str,
        input_val: Any,
        output_val: Any,
        details: dict | None = None,
        indicator: str = "",
    ) -> ProvenanceRecord:
        """Record a transformation and return the ProvenanceRecord."""
        record = ProvenanceRecord(
            transform_type=transform_type,
            source_run_id=self.run_id,
            source_indicator=indicator,
            input_value=input_val,
            output_value=output_val,
            transformation_details=details or {},
        )
        self._records.append(record)
        return record

    def get_history(self) -> list[ProvenanceRecord]:
        """Return all recorded transformations."""
        return list(self._records)

    def get_by_type(self, transform_type: str) -> list[ProvenanceRecord]:
        """Return records filtered by type."""
        return [r for r in self._records if r.transform_type == transform_type]

    def to_audit_log(self) -> list[dict]:
        """Serialize to list of dicts."""
        return [r.to_dict() for r in self._records]

    def to_json(self) -> str:
        return AuditLog(
            run_id=self.run_id,
            source_id=self.source_id,
            entries=self._records,
        ).to_json()

    @property
    def summary(self) -> dict:
        return AuditLog(
            run_id=self.run_id,
            source_id=self.source_id,
            entries=self._records,
        ).summary


# ---------------------------------------------------------------------------
# Pipeline wrapper functions
# ---------------------------------------------------------------------------


def apply_normalization_trace(
    points: list[DataPoint],
    tracker: ProvenanceTracker,
) -> list[DataPoint]:
    """Normalize DataPoints and record each transformation.

    Args:
        points: DataPoints to normalize.
        tracker: ProvenanceTracker for recording.

    Returns:
        Normalized DataPoints with provenance in metadata.
    """
    from collector.normalization import normalize_all

    result = normalize_all(points)

    # Record each normalization step
    for step in result.normalizations:
        tracker.record(
            transform_type="normalization",
            input_val=step.original,
            output_val=step.normalized,
            details={"step": step.step, "detail": step.detail},
            indicator="",
        )

    # Store provenance in each point's metadata
    for dp in result.data_points:
        dp.metadata["_provenance"] = dp.metadata.get("_provenance", [])

        # Collect relevant records for this point
        point_provenance = []
        for rec in tracker._records:
            if rec.source_indicator == dp.indicator_code or not rec.source_indicator:
                point_provenance.append(rec.to_dict())

        dp.metadata["_provenance"].extend(point_provenance[-10:])  # Keep last 10

    return result.data_points


def validate_with_trace(
    points: list[DataPoint],
    tracker: ProvenanceTracker,
) -> list[DataPoint]:
    """Validate DataPoints and record each check.

    Args:
        points: DataPoints to validate (must be already normalized).
        tracker: ProvenanceTracker for recording.

    Returns:
        Same DataPoints with provenance in metadata.
    """
    from collector.validation import validate_batch

    results = validate_batch(points)

    # Record validation summary for each point
    for res in results:
        tracker.record(
            transform_type="validation",
            input_val=res.point.value,
            output_val=res.status,
            details={
                "messages": res.messages,
                "checks": [
                    {"name": c.name, "passed": c.passed, "detail": c.detail}
                    for c in res.checks
                ],
            },
            indicator=res.point.indicator_code,
        )

    # Store provenance in metadata
    for dp in points:
        if "_validation" in dp.metadata:
            dp.metadata["_provenance"] = dp.metadata.get("_provenance", [])
            dp.metadata["_provenance"].append({
                "transform_type": "validation",
                "result": dp.metadata["_validation"],
            })

    return points


def extract_with_trace(
    raw_rows: list[dict],
    source_id: str,
    indicator_code: str,
    tracker: ProvenanceTracker,
) -> list[DataPoint]:
    """Extract DataPoints from raw rows and record the transformation.

    Args:
        raw_rows: Raw adapter output.
        source_id: Source identifier.
        indicator_code: Indicator code.
        tracker: ProvenanceTracker for recording.

    Returns:
        Extracted DataPoints with provenance in metadata.
    """
    from collector.collection import extract_data

    points = extract_data(raw_rows, source_id, indicator_code)

    # Record extraction for each point
    for dp in points:
        tracker.record(
            transform_type="extraction",
            input_val=dp.metadata.get("_raw"),
            output_val={
                "country": dp.country,
                "year": dp.year,
                "value": dp.value,
                "indicator": dp.indicator_code,
            },
            details={
                "raw_keys": list(dp.metadata.get("_raw", {}).keys()),
            },
            indicator=indicator_code,
        )

    return points