"""
Phase 11 — Validation Engine.

Domain-specific validation rules for data quality.

Status values:
  "valid"   → value passes all checks
  "warning" → value is plausible but unusual (e.g., extreme GDP growth)
  "invalid" → value violates domain rules (e.g., negative population)
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from collector.collection import DataPoint

logger = logging.getLogger("collector.validation")

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ValidationCheck:
    """A single validation check result."""
    name: str
    passed: bool
    detail: str


@dataclass
class ValidationResult:
    """Validation result for a single DataPoint."""
    point: DataPoint
    status: str  # "valid", "warning", "invalid"
    messages: list[str] = field(default_factory=list)
    checks: list[ValidationCheck] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Domain-specific validators
# ---------------------------------------------------------------------------


def validate_population(value: Optional[float]) -> list[ValidationCheck]:
    """Validate population-like values.

    Population must be positive, < 10 billion (Earth population ~8B),
    and ideally an integer.
    """
    checks = []

    if value is None:
        checks.append(ValidationCheck("not_none", False, "Value is None"))
        return checks

    if value < 0:
        checks.append(ValidationCheck("positive", False, f"Negative population: {value}"))
    else:
        checks.append(ValidationCheck("positive", True, f"Positive: {value}"))

    if value > 10_000_000_000:
        checks.append(ValidationCheck("reasonable_range", False,
                                       f"Population exceeds Earth total: {value}"))
    elif value > 1_000_000_000:
        checks.append(ValidationCheck("reasonable_range", True,
                                       f"Large population (>{1e9}): {value}"))
    else:
        checks.append(ValidationCheck("reasonable_range", True,
                                       f"Within expected range: {value}"))

    if value != int(value) and value > 0:
        checks.append(ValidationCheck("integer", False,
                                       f"Population should be integer: {value}"))
    else:
        checks.append(ValidationCheck("integer", True, "Integer value"))

    return checks


def validate_gdp_growth(value: Optional[float]) -> list[ValidationCheck]:
    """Validate GDP growth rate.

    Typical range: -50% to +50% for most countries.
    Extreme values are flagged but not rejected outright.
    """
    checks = []

    if value is None:
        checks.append(ValidationCheck("not_none", False, "Value is None"))
        return checks

    checks.append(ValidationCheck("has_value", True, f"Growth rate: {value}%"))

    if value < -100 or value > 100:
        checks.append(ValidationCheck("reasonable_range", False,
                                       f"Extreme GDP growth: {value}%"))
    elif value < -50 or value > 50:
        checks.append(ValidationCheck("reasonable_range", False,
                                       f"Unusual GDP growth: {value}%"))
    else:
        checks.append(ValidationCheck("reasonable_range", True,
                                       f"Normal GDP growth: {value}%"))

    return checks


def validate_unemployment(value: Optional[float]) -> list[ValidationCheck]:
    """Validate unemployment rate.

    Must be 0-100%, percentage.
    """
    checks = []

    if value is None:
        checks.append(ValidationCheck("not_none", False, "Value is None"))
        return checks

    if value < 0:
        checks.append(ValidationCheck("non_negative", False,
                                       f"Negative unemployment: {value}%"))
    else:
        checks.append(ValidationCheck("non_negative", True, "Non-negative"))

    if value < 0 or value > 100:
        checks.append(ValidationCheck("reasonable_range", False,
                                       f"Unemployment outside 0-100%: {value}%"))
    else:
        checks.append(ValidationCheck("reasonable_range", True,
                                       f"Within 0-100% range: {value}%"))

    return checks


def validate_exchange_rate(value: Optional[float]) -> list[ValidationCheck]:
    """Validate exchange rate.

    Must be positive.
    """
    checks = []

    if value is None:
        checks.append(ValidationCheck("not_none", False, "Value is None"))
        return checks

    if value <= 0:
        checks.append(ValidationCheck("positive", False,
                                       f"Exchange rate must be positive: {value}"))
    else:
        checks.append(ValidationCheck("positive", True, f"Positive rate: {value}"))

    return checks


def validate_generic(value: Optional[float]) -> list[ValidationCheck]:
    """Generic validation for unknown indicators.

    Basic checks: not None, not NaN, not extreme.
    """
    checks = []

    if value is None:
        checks.append(ValidationCheck("not_none", False, "Value is None"))
        return checks

    checks.append(ValidationCheck("has_value", True, f"Value: {value}"))

    if value != value:  # NaN check
        checks.append(ValidationCheck("not_nan", False, "Value is NaN"))
    else:
        checks.append(ValidationCheck("not_nan", True, "Not NaN"))

    # Flag extreme values (> 1e15 or < -1e15)
    if abs(value) > 1e15:
        checks.append(ValidationCheck("reasonable_range", False,
                                       f"Extreme value: {value}"))
    else:
        checks.append(ValidationCheck("reasonable_range", True,
                                       f"Reasonable magnitude: {value}"))

    return checks


# ---------------------------------------------------------------------------
# Rules mapping (prefix → validator)
# ---------------------------------------------------------------------------

VALIDATION_RULES = {
    # Population: SP.POP.*
    "SP.POP": validate_population,
    "population": validate_population,

    # GDP growth: NY.GDP.MKTP.KD.ZG
    "NY.GDP.MKTP.KD.ZG": validate_gdp_growth,
    "NY.GDP.MKTP": validate_gdp_growth,
    "gdp_growth": validate_gdp_growth,

    # Unemployment: SL.UEM.*
    "SL.UEM": validate_unemployment,
    "unemployment": validate_unemployment,

    # Exchange rates
    "exchange_rate": validate_exchange_rate,
    "FX": validate_exchange_rate,
}

# Default fallback validator
_DEFAULT_VALIDATOR = validate_generic


def _get_validator(indicator_code: str) -> callable:
    """Get the appropriate validator for an indicator code."""
    if not indicator_code:
        return _DEFAULT_VALIDATOR

    code_upper = indicator_code.upper()

    # Check exact match first
    if indicator_code in VALIDATION_RULES:
        return VALIDATION_RULES[indicator_code]

    # Check prefix matches
    for prefix, validator in VALIDATION_RULES.items():
        if prefix in code_upper or prefix in indicator_code.lower():
            return validator

    return _DEFAULT_VALIDATOR


# ---------------------------------------------------------------------------
# Main validation functions
# ---------------------------------------------------------------------------


def validate_value(value: Optional[float], indicator_code: str = "",
                   unit: Optional[str] = None) -> tuple[str, list[str], list[ValidationCheck]]:
    """Validate a single value with domain-specific rules.

    Args:
        value: The numeric value to validate.
        indicator_code: The indicator code (determines validator).
        unit: The unit field (for additional context).

    Returns:
        (status, messages, checks).
    """
    validator = _get_validator(indicator_code)
    checks = validator(value)

    # Determine status based on check results
    has_failure = any(not c.passed for c in checks)
    has_warning = any("reasonable_range" in c.name.lower() and not c.passed for c in checks)

    messages = []
    for c in checks:
        messages.append(f"{c.name}: {'PASS' if c.passed else 'FAIL'} - {c.detail}")

    if has_failure and "reasonable_range" not in [c.name for c in checks if not c.passed]:
        status = "invalid"
    elif has_warning:
        status = "warning"
    elif has_failure:
        status = "invalid"
    else:
        status = "valid"

    return status, messages, checks


def validate_batch(points: list[DataPoint]) -> list[ValidationResult]:
    """Validate a batch of DataPoints.

    Args:
        points: List of DataPoints to validate.

    Returns:
        List of ValidationResult objects.
    """
    results = []

    for dp in points:
        status, messages, checks = validate_value(
            dp.value, dp.indicator_code, dp.unit
        )

        # Store validation result in metadata
        dp.metadata["_validation"] = {
            "status": status,
            "messages": messages,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                        for c in checks],
        }

        results.append(ValidationResult(
            point=dp,
            status=status,
            messages=messages,
            checks=checks,
        ))

    return results


def filter_valid(points: list[DataPoint]) -> list[DataPoint]:
    """Filter out invalid DataPoints, keeping only valid ones.

    WARNING: This modifies DataPoint metadata. Use filter_valid_with_result
    if you need the ValidationResult objects.

    Args:
        points: List of DataPoints (already validated).

    Returns:
        Only DataPoints with status "valid".
    """
    return [
        dp for dp in points
        if dp.metadata.get("_validation", {}).get("status") == "valid"
    ]


def filter_valid_with_result(points: list[DataPoint],
                              include_warnings: bool = False) -> list[DataPoint]:
    """Filter DataPoints with optional warning inclusion.

    Args:
        points: List of DataPoints (already validated).
        include_warnings: If True, also include "warning" status points.

    Returns:
        DataPoints with status "valid" (and optionally "warning").
    """
    allowed = {"valid"}
    if include_warnings:
        allowed.add("warning")

    return [
        dp for dp in points
        if dp.metadata.get("_validation", {}).get("status") in allowed
    ]


def get_validation_summary(results: list[ValidationResult]) -> dict:
    """Get a summary of validation results.

    Args:
        results: List of ValidationResult objects.

    Returns:
        {total, valid, warning, invalid, pass_rate}.
    """
    total = len(results)
    valid = sum(1 for r in results if r.status == "valid")
    warning = sum(1 for r in results if r.status == "warning")
    invalid = sum(1 for r in results if r.status == "invalid")

    return {
        "total": total,
        "valid": valid,
        "warning": warning,
        "invalid": invalid,
        "pass_rate": round(valid / total, 4) if total > 0 else 0.0,
    }