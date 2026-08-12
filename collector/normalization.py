"""
Phase 10 — Normalization Engine.

Normalizes DataPoint values while preserving originals for auditability.

Normalizations:
- Currency: USD→AZN, EUR→USD, etc. using a rate table
- Percentage: "5.2%" or unit="%" → 0.052
- Scale: "billion"→*1e9, "million"→*1e6, "thousand"→*1e3

Original value is always preserved in metadata["_original_value"].
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from collector.collection import DataPoint, _to_float

logger = logging.getLogger("collector.normalization")

# ---------------------------------------------------------------------------
# Currency conversion rates (base = USD = 1.0)
# ---------------------------------------------------------------------------

CURRENCY_RATES: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.08,
    "AZN": 1.70,
    "RUB": 90.0,
    "GBP": 1.27,
    "TRY": 32.0,
    "JPY": 149.0,
    "CNY": 7.24,
    "KZT": 450.0,
    "AED": 3.67,
}

# Currency code → full name (for display)
CURRENCY_NAMES: dict[str, str] = {
    "USD": "US Dollar",
    "EUR": "Euro",
    "AZN": "Azerbaijani Manat",
    "RUB": "Russian Ruble",
    "GBP": "British Pound",
    "TRY": "Turkish Lira",
    "JPY": "Japanese Yen",
    "CNY": "Chinese Yuan",
    "KZT": "Kazakhstani Tenge",
    "AED": "UAE Dirham",
}

# ---------------------------------------------------------------------------
# Scale suffixes (for converting between magnitude units)
# ---------------------------------------------------------------------------

SCALE_MULTIPLIERS: dict[str, float] = {
    "billion": 1e9,
    "billion": 1e9,
    "trillion": 1e12,
    "million": 1e6,
    "thousand": 1e3,
    "k": 1e3,
    "m": 1e6,
    "bn": 1e9,
}

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class NormalizeStep:
    """Records a single normalization operation."""
    step: str  # "currency", "percentage", "scale"
    original: float
    normalized: float
    detail: str
    unit_from: Optional[str] = None
    unit_to: Optional[str] = None


@dataclass
class NormalizeResult:
    """Result of normalizing a batch of data points."""
    data_points: list[DataPoint]
    normalizations: list[NormalizeStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual normalization functions
# ---------------------------------------------------------------------------


def normalize_currency(value: Optional[float], from_currency: str,
                       to_currency: str = "USD") -> tuple[Optional[float], str]:
    """Convert a value from one currency to another using rate table.

    Args:
        value: The original amount.
        from_currency: Source currency code (USD, EUR, AZN, etc.).
        to_currency: Target currency code (default "USD").

    Returns:
        (converted_value, detail_message).
        Returns (None, "") if conversion is not possible.
    """
    if value is None:
        return None, ""

    from_code = from_currency.upper().strip() if from_currency else "USD"
    to_code = to_currency.upper().strip()

    if from_code == to_code:
        return value, f"No conversion needed ({from_code}→{to_code})"

    from_rate = CURRENCY_RATES.get(from_code)
    to_rate = CURRENCY_RATES.get(to_code)

    if from_rate is None:
        msg = f"Unknown currency: {from_code}"
        logger.warning(msg)
        return value, msg

    if to_rate is None:
        msg = f"Unknown target currency: {to_code}"
        logger.warning(msg)
        return value, msg

    # Convert: value_in_base * to_rate = converted_value
    converted = value / from_rate * to_rate
    detail = f"{from_code}({value}) → {to_code}({converted:.2f})"
    return converted, detail


def normalize_percentage(value: Optional[float], unit: Optional[str]) -> tuple[Optional[float], str]:
    """Convert percentage representation to decimal.

    Args:
        value: The original numeric value.
        unit: The unit field (e.g. "%").

    Returns:
        (decimal_value, detail_message).
    """
    if value is None:
        return None, ""

    # Check if value looks like a percentage (e.g. 5.2 represents 5.2%)
    # We detect this by checking the unit field
    is_percentage = False
    if unit:
        unit_upper = unit.upper().strip()
        if unit_upper == "%" or unit_upper == "PCT" or unit_upper == "PERCENT":
            is_percentage = True

    # Also detect by value range: if value > 1 and unit suggests %, normalize
    if unit and "%" in str(unit):
        is_percentage = True

    if is_percentage:
        decimal = value / 100.0
        detail = f"Percentage: {value}% → {decimal:.4f}"
        return decimal, detail

    return value, "Already decimal or not percentage"


def normalize_scale(value: Optional[float], unit: Optional[str],
                    indicator_code: str = "") -> tuple[Optional[float], str]:
    """Apply scale normalization based on unit or indicator hints.

    Detects scale suffixes and normalizes to base unit.

    Args:
        value: The original numeric value.
        unit: The unit field (e.g. "Billion USD").
        indicator_code: The indicator code (may contain scale hints).

    Returns:
        (normalized_value, detail_message).
    """
    if value is None:
        return None, ""

    # Check unit for scale hints
    unit_str = (unit or "").lower()
    indicator_str = (indicator_code or "").lower()

    combined = f" {unit_str} {indicator_str} "

    for suffix, multiplier in [
        ("billion", 1e9),
        ("trillion", 1e12),
        ("million", 1e6),
        ("thousand", 1e3),
        (" billion", 1e9),
        (" million", 1e6),
        (" thousand", 1e3),
        (" bn", 1e9),
        (" mn", 1e6),
        (" k ", 1e3),
    ]:
        if suffix in combined:
            # Value is in "billion USD" format — multiply to get base
            normalized = value * multiplier
            detail = f"Scale: {value} ({suffix.strip()}) → {normalized:.2f}"
            return normalized, detail

    return value, "No scale adjustment needed"


def normalize_value(value: Optional[float], unit: Optional[str],
                    indicator_code: str = "",
                    target_currency: str = "USD") -> tuple[Optional[float], list[str]]:
    """Apply all normalizations to a single value.

    Order: percentage first, then scale, then currency.

    Args:
        value: The original numeric value.
        unit: The unit field.
        indicator_code: The indicator code.
        target_currency: Target currency for conversion.

    Returns:
        (normalized_value, list of detail messages).
    """
    if value is None:
        return None, []

    details = []

    # Step 1: Percentage normalization
    if unit:
        pct_val, pct_detail = normalize_percentage(value, unit)
        if pct_val != value and pct_detail != "Already decimal or not percentage":
            value = pct_val
            details.append(pct_detail)

    # Step 2: Scale normalization
    scaled_val, scale_detail = normalize_scale(value, unit, indicator_code)
    if scaled_val != value:
        value = scaled_val
        details.append(scale_detail)

    # Step 3: Currency normalization (only if unit is a currency code)
    if unit:
        unit_clean = unit.upper().strip()
        if unit_clean in CURRENCY_RATES:
            curr_val, curr_detail = normalize_currency(value, unit_clean, target_currency)
            if curr_val is not None and curr_detail != f"No conversion needed ({unit_clean}→{target_currency})":
                value = curr_val
                details.append(curr_detail)

    return value, details


# ---------------------------------------------------------------------------
# Batch normalization
# ---------------------------------------------------------------------------


def normalize_all(points: list[DataPoint],
                  target_currency: str = "USD") -> NormalizeResult:
    """Normalize a batch of DataPoints.

    Applies all normalization steps, preserves original values in metadata.

    Args:
        points: List of DataPoints to normalize.
        target_currency: Target currency for conversion (default "USD").

    Returns:
        NormalizeResult with normalized points, steps, and warnings.
    """
    normalizations: list[NormalizeStep] = []
    warnings: list[str] = []
    normalized_points = []

    for dp in points:
        original_value = dp.value

        # Store original value in metadata
        dp.metadata["_original_value"] = original_value
        dp.metadata["_normalizations"] = dp.metadata.get("_normalizations", [])

        if original_value is None:
            normalized_points.append(dp)
            continue

        normalized_val, details = normalize_value(
            original_value, dp.unit, dp.indicator_code, target_currency
        )

        # Record each normalization step
        for detail in details:
            step_type = "currency"
            if "Percentage" in detail:
                step_type = "percentage"
            elif "Scale" in detail:
                step_type = "scale"

            normalizations.append(NormalizeStep(
                step=step_type,
                original=original_value,
                normalized=normalized_val,
                detail=detail,
            ))
            dp.metadata["_normalizations"].append({
                "step": step_type,
                "original": original_value,
                "normalized": normalized_val,
                "detail": detail,
            })

        # Update value
        dp.value = normalized_val

        normalized_points.append(dp)

    return NormalizeResult(
        data_points=normalized_points,
        normalizations=normalizations,
        warnings=warnings,
    )