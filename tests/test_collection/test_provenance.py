"""
Phase 12 — Provenance Tracking tests.
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from collector.collection import DataPoint
from collector.provenance import (
    ProvenanceRecord,
    ProvenanceTracker,
    AuditLog,
    apply_normalization_trace,
    validate_with_trace,
    extract_with_trace,
)


# ---------------------------------------------------------------------------
# ProvenanceRecord
# ---------------------------------------------------------------------------

class TestProvenanceRecord:
    def test_creation(self):
        rec = ProvenanceRecord(
            transform_type="extraction",
            source_run_id=1,
            source_indicator="NY.GDP.MKTP.CD",
            input_value=42.0,
            output_value=42.0,
            transformation_details={"step": "raw"},
        )
        assert rec.transform_type == "extraction"
        assert rec.source_run_id == 1
        assert rec.timestamp != ""

    def test_to_dict(self):
        rec = ProvenanceRecord(
            transform_type="normalization",
            source_run_id=1,
            source_indicator="X",
            input_value=5.2,
            output_value=0.052,
            transformation_details={"step": "percentage"},
        )
        d = rec.to_dict()
        assert d["transform_type"] == "normalization"
        assert d["input_value"] == 5.2
        assert d["output_value"] == 0.052

    def test_to_json(self):
        rec = ProvenanceRecord(
            transform_type="extraction",
            source_run_id=1,
            source_indicator="X",
            input_value={"raw": "data"},
            output_value={"country": "AZ"},
        )
        d = json.loads(rec.to_json())
        assert d["transform_type"] == "extraction"
        assert d["input_value"] == {"raw": "data"}


# ---------------------------------------------------------------------------
# ProvenanceTracker
# ---------------------------------------------------------------------------

class TestProvenanceTracker:
    def test_init(self):
        tracker = ProvenanceTracker(run_id=42, source_id="world_bank")
        assert tracker.run_id == 42
        assert tracker.source_id == "world_bank"
        assert len(tracker.get_history()) == 0

    def test_record(self):
        tracker = ProvenanceTracker(run_id=1, source_id="wb")
        rec = tracker.record("extraction", 42, 42, {"step": "raw"}, "X")
        assert rec.transform_type == "extraction"
        assert len(tracker.get_history()) == 1

    def test_history(self):
        tracker = ProvenanceTracker(run_id=1, source_id="wb")
        tracker.record("extraction", 1, 1, indicator="X")
        tracker.record("normalization", 1, 0.5, indicator="X")
        history = tracker.get_history()
        assert len(history) == 2
        assert history[0].transform_type == "extraction"
        assert history[1].transform_type == "normalization"

    def test_filter_by_type(self):
        tracker = ProvenanceTracker(run_id=1, source_id="wb")
        tracker.record("extraction", 1, 1, indicator="X")
        tracker.record("normalization", 1, 0.5, indicator="X")
        tracker.record("extraction", 2, 2, indicator="Y")
        extractions = tracker.get_by_type("extraction")
        assert len(extractions) == 2

    def test_to_audit_log(self):
        tracker = ProvenanceTracker(run_id=1, source_id="wb")
        tracker.record("extraction", 42, 42, {"step": "raw"}, "X")
        log = tracker.to_audit_log()
        assert len(log) == 1
        assert log[0]["transform_type"] == "extraction"

    def test_to_json(self):
        tracker = ProvenanceTracker(run_id=1, source_id="wb")
        tracker.record("extraction", 42, 42, indicator="X")
        data = json.loads(tracker.to_json())
        assert data["run_id"] == 1
        assert data["source_id"] == "wb"
        assert len(data["entries"]) == 1

    def test_summary(self):
        tracker = ProvenanceTracker(run_id=1, source_id="wb")
        tracker.record("extraction", 1, 1, indicator="X")
        tracker.record("extraction", 2, 2, indicator="Y")
        tracker.record("normalization", 1, 0.5, indicator="X")
        summary = tracker.summary
        assert summary["total_records"] == 3
        assert summary["transforms_by_type"]["extraction"] == 2
        assert summary["transforms_by_type"]["normalization"] == 1


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_summary_counts(self):
        entries = [
            ProvenanceRecord("extraction", 1, "X", 1, 1),
            ProvenanceRecord("extraction", 1, "X", 2, 2),
            ProvenanceRecord("normalization", 1, "X", 2, 1),
        ]
        log = AuditLog(run_id=1, source_id="wb", entries=entries)
        s = log.summary
        assert s["total_records"] == 3
        assert s["transforms_by_type"]["extraction"] == 2

    def test_to_audit_log(self):
        entries = [
            ProvenanceRecord("extraction", 1, "X", 42, 42),
        ]
        log = AuditLog(run_id=1, source_id="wb", entries=entries)
        log_dicts = log.to_audit_log()
        assert len(log_dicts) == 1
        assert log_dicts[0]["input_value"] == 42

    def test_to_json(self):
        entries = [
            ProvenanceRecord("extraction", 1, "X", 42, 42),
        ]
        log = AuditLog(run_id=1, source_id="wb", entries=entries)
        data = json.loads(log.to_json())
        assert data["run_id"] == 1
        assert "entries" in data


# ---------------------------------------------------------------------------
# Pipeline wrappers
# ---------------------------------------------------------------------------

class TestPipelineTraces:
    def test_apply_normalization_trace(self):
        tracker = ProvenanceTracker(run_id=1, source_id="test")
        points = [
            DataPoint(country="AZ", value=5.2, unit="%", indicator_code="X"),
        ]
        result = apply_normalization_trace(points, tracker)
        assert result[0].value == pytest.approx(0.052, abs=0.001)
        history = tracker.get_history()
        assert len(history) >= 1
        assert history[0].transform_type == "normalization"

    def test_validate_with_trace(self):
        tracker = ProvenanceTracker(run_id=1, source_id="test")
        points = [
            DataPoint(country="AZ", value=10_000_000, indicator_code="SP.POP.TOTL"),
        ]
        result = validate_with_trace(points, tracker)
        history = tracker.get_history()
        assert len(history) == 1
        assert history[0].transform_type == "validation"
        assert result[0].metadata["_validation"]["status"] == "valid"

    def test_extract_with_trace(self):
        tracker = ProvenanceTracker(run_id=1, source_id="test")
        raw = [{"country": "AZ", "year": "2022", "value": 42.0, "indicator": "X"}]
        points = extract_with_trace(raw, "test_source", "X", tracker)
        assert len(points) == 1
        assert points[0].value == 42.0
        history = tracker.get_history()
        assert len(history) == 1
        assert history[0].transform_type == "extraction"

    def test_full_pipeline_trace(self):
        """Test extraction → normalization → validation trace chain."""
        tracker = ProvenanceTracker(run_id=1, source_id="test")

        # Raw data
        raw = [{"country": "AZ", "year": "2022", "value": 5.2, "unit": "%"}]

        # Extract
        points = extract_with_trace(raw, "test", "X", tracker)
        # Normalize
        points = apply_normalization_trace(points, tracker)
        # Validate
        points = validate_with_trace(points, tracker)

        # Check provenance in metadata
        assert "_provenance" in points[0].metadata
        assert len(points[0].metadata["_provenance"]) >= 1

        # Check history covers all steps
        history = tracker.get_history()
        types = {r.transform_type for r in history}
        assert "extraction" in types
        assert "normalization" in types
        assert "validation" in types