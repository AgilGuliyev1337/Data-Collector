"""
Phase 8 — Real Data Collection / Extraction Pipeline.

Wraps existing adapters (WorldBank, Eurostat, IMF, CBR, CKAN) and normalizes
their outputs to a unified internal result format.

Unified result shape:
{
  "country": str,
  "iso3": str | None,
  "period": str,
  "year": int | None,
  "value": float | None,
  "unit": str | None,
  "indicator_code": str,
  "source_id": str,
  "metadata": dict,
}

Each adapter already returns a slightly different shape. This module:
1. Calls the adapter via the EXTRACTORS dispatch table
2. Transforms raw adapter output into the unified format
3. Preserves raw API response in `metadata["_raw"]` for provenance
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("collector.collection")

# ---------------------------------------------------------------------------
# Unified result shape
# ---------------------------------------------------------------------------


@dataclass
class DataPoint:
    """A single normalized data point from any source."""
    country: str
    iso3: Optional[str] = None
    period: str = ""
    year: Optional[int] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    indicator_code: str = ""
    source_id: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "country": self.country,
            "iso3": self.iso3,
            "period": self.period,
            "year": self.year,
            "value": self.value,
            "unit": self.unit,
            "indicator_code": self.indicator_code,
            "source_id": self.source_id,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Adapter extraction functions
# ---------------------------------------------------------------------------


def extract_worldbank(raw: dict, source_id: str = "world_bank") -> DataPoint:
    """Extract a unified DataPoint from World Bank adapter output.

    Handles both raw API format (nested country/indicator dicts) and
    adapter-transformed format (flat strings).
    """
    # Raw API format: country is {"id": "AZ", "value": "Azerbaijan"}
    if isinstance(raw.get("country"), dict):
        country = raw["country"].get("value", "")
    else:
        country = raw.get("country", "")

    if isinstance(raw.get("indicator"), dict):
        indicator = raw["indicator"].get("value", "")
    else:
        indicator = raw.get("indicator", "")

    # Raw API has date, adapter-transformed has year
    date_val = raw.get("date") or raw.get("year")

    # KD check only applies to raw format indicator strings
    unit = None
    if indicator:
        if "GDP" in indicator and "KD" not in indicator:
            unit = "USD"

    return DataPoint(
        country=country,
        iso3=raw.get("countryiso3code") or raw.get("iso3"),
        period=str(date_val) if date_val else "",
        year=_to_int(date_val),
        value=_to_float(raw.get("value")),
        unit=unit,
        indicator_code=indicator,
        source_id=source_id,
        metadata={"_raw": raw},
    )


def extract_eurostat(raw: dict, source_id: str = "eurostat") -> DataPoint:
    """Extract a unified DataPoint from Eurostat adapter output."""
    return DataPoint(
        country=raw.get("country") or raw.get("geo"),
        iso3=raw.get("iso3") or raw.get("geo"),
        period=str(raw.get("year") or raw.get("time") or ""),
        year=_parse_year_from_time(raw.get("year") or raw.get("time")),
        value=_to_float(raw.get("value")),
        unit=raw.get("unit"),
        indicator_code=raw.get("indicator") or raw.get("dataset"),
        source_id=source_id,
        metadata={"_raw": raw},
    )


def extract_imf(raw: dict, source_id: str = "imf") -> DataPoint:
    """Extract a unified DataPoint from IMF adapter output.

    Handles both raw SDMX-JSON format and adapter-transformed format.
    """
    # Raw API format: has @REF_AREA, @TIME_PERIOD, @OBS_VALUE
    if raw.get("@REF_AREA"):
        country = raw["@REF_AREA"]
        year = raw["@TIME_PERIOD"]
        value = raw["@OBS_VALUE"]
    else:
        country = raw.get("country") or raw.get("REF_AREA", "")
        year = raw.get("year") or raw.get("TIME_PERIOD", "")
        value = raw.get("value") or raw.get("OBS_VALUE")

    return DataPoint(
        country=country,
        iso3=country,
        period=str(year) if year else "",
        year=_parse_year_from_time(year),
        value=_to_float(value),
        unit=raw.get("unit") or raw.get("UNIT"),
        indicator_code=raw.get("indicator") or raw.get("INDICATOR", ""),
        source_id=source_id,
        metadata={"_raw": raw},
    )


def extract_cbr(raw: dict, source_id: str = "cbr_russia") -> DataPoint:
    """Extract a unified DataPoint from CBR adapter output."""
    # CBR adapter returns: {currency, name, nominal, value_rub, date, source}
    nominal = raw.get("nominal", 1)
    value_rub = raw.get("value_rub")
    rate = _to_float(value_rub)
    if rate is not None and nominal is not None:
        rate = rate / float(nominal)

    return DataPoint(
        country="RU",
        iso3="RUS",
        period=str(raw.get("date") or raw.get("Date", "")),
        year=_parse_year_from_time(raw.get("date") or raw.get("Date")),
        value=rate,
        unit=raw.get("currency") or raw.get("Currency"),
        indicator_code=raw.get("currency") or raw.get("Currency"),
        source_id=source_id,
        metadata={"_raw": raw},
    )


def extract_ckan(raw: dict, source_id: str = "ckan") -> DataPoint:
    """Extract a unified DataPoint from a CKAN resource row."""
    return DataPoint(
        country=raw.get("country", "global"),
        iso3=None,
        period=str(raw.get("year", raw.get("period", ""))),
        year=_to_int(raw.get("year")),
        value=_to_float(raw.get("value")),
        unit=raw.get("unit"),
        indicator_code=raw.get("indicator_code", ""),
        source_id=source_id,
        metadata={"_raw": raw},
    )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

EXTRACTORS = {
    "world_bank": extract_worldbank,
    "eurostat": extract_eurostat,
    "imf": extract_imf,
    "cbr_russia": extract_cbr,
    "ckan": extract_ckan,
}


def extract_data(raw_rows: list[dict], source_id: str, indicator_code: str) -> list[DataPoint]:
    """Transform raw adapter rows into unified DataPoints.

    Uses the EXTRACTORS dispatch table. Falls back to generic extraction
    if the source is unknown.
    """
    extractor = EXTRACTORS.get(source_id, _extract_generic)
    points = []
    for raw in raw_rows:
        dp = extractor(raw, source_id)
        dp.indicator_code = indicator_code or dp.indicator_code
        dp.source_id = source_id
        points.append(dp)
    return points


def _extract_generic(raw: dict, source_id: str) -> DataPoint:
    """Generic extractor for unknown adapter formats."""
    return DataPoint(
        country=raw.get("country", raw.get("Country", "")),
        iso3=raw.get("iso3", raw.get("ISO3")),
        period=str(raw.get("period", raw.get("year", raw.get("date", raw.get("Year", raw.get("Date", "")))))),
        year=_to_int(raw.get("year", raw.get("date", raw.get("Year", raw.get("Date"))))),
        value=_to_float(raw.get("value", raw.get("Value"))),
        unit=raw.get("unit", raw.get("Unit")),
        indicator_code=raw.get("indicator_code", raw.get("indicator", "")),
        source_id=source_id,
        metadata={"_raw": raw},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f == float("inf") or f == float("-inf") else f
    except (TypeError, ValueError):
        return None


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_year_from_time(time_val) -> Optional[int]:
    """Extract year from various time formats."""
    if time_val is None:
        return None
    s = str(time_val).strip()
    if len(s) == 4 and s.isdigit():
        return int(s)
    # Q1, Q2, Q3, Q4 → return start year
    m = re.match(r"(\d{4})\s*[Qq]\d?", s)
    if m:
        return int(m.group(1))
    # YYYY-MM → return year
    m = re.match(r"(\d{4})-\d{2}", s)
    if m:
        return int(m.group(1))
    return None