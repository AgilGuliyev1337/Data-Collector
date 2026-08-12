"""
Phase 6 — Natural Language Requirement Parser.

Parses user queries in Azerbaijani and English to extract:
- concept: statistical concept (GDP, unemployment, etc.) via synonym dict
- countries: list of country codes (AZ, global, etc.)
- periods: year/month ranges
- frequency: annual, monthly, quarterly
- extra: free-form extracted text

Deterministic extraction first; LLM ONLY for ambiguity.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from collector.semantic_resolver import (
    SYNONYM_DICT,
    _normalize,
)


# ---------------------------------------------------------------------------
# Country lists
# ---------------------------------------------------------------------------

# Multi-word patterns to check in normalized text
_COUNTRY_MULTIWORD = [
    ("global", ["dunya", "dünya", "world", "global", "international"]),
    ("AZ", ["azerbaijan", "azerbaycan", "baki", "bakı", "naxçıvan", "naxcivan"]),
    ("TR", ["turkiye", "türkiye", "istanbul", "ankara", "turkish", "türk"]),
    ("RU", ["russia", "rusiya", "moscow", "moskva", "russian"]),
    ("US", ["america", "amerika", "united states", "washington", "usa", "abş"]),
    ("EU", ["european union", "avropa birliyi", "uk", "britain", "germany", "france", "italy", "spain", "avropa", "eu"]),
    ("CN", ["china", "beijing", "çin", "cin"]),
    ("KZ", ["kazakhstan", "qazaxistan", "qazaxıstan", "almata", "astana"]),
    ("GE", ["georgia", "gürcüstan", "gürcistan", "tbilisi"]),
]

# Single-word token → country mapping (checked after normalization)
# Includes both EN and AZ normalized forms
_COUNTRY_TOKENS: dict[str, str] = {
    # AZ
    "az": "AZ", "azerbaijan": "AZ", "azerbaycan": "AZ",
    "baku": "AZ", "naxcivan": "AZ",
    # TR
    "turkey": "TR", "turkiye": "TR", "istanbul": "TR",
    "ankara": "TR", "turkish": "TR",
    # RU
    "russia": "RU", "russian": "RU", "moscow": "RU",
    "rusiya": "RU", "moskva": "RU",
    # US
    "usa": "US", "america": "US", "amerika": "US", "washington": "US",
    # EU
    "europe": "EU", "britain": "EU", "germany": "EU",
    "france": "EU", "italy": "EU", "spain": "EU",
    # CN
    "china": "CN", "beijing": "CN", "cin": "CN",
    # KZ
    "kazakhstan": "KZ", "qazaxistan": "KZ", "qazaq": "KZ",
    "almata": "KZ", "astana": "KZ",
    # GE
    "georgia": "GE", "gurcu": "GE", "gurcustan": "GE",
    "tbilisi": "GE",
}


# ---------------------------------------------------------------------------
# Period patterns (order matters: more specific patterns first)
# ---------------------------------------------------------------------------

_YEAR_PATTERNS = [
    # Range (most specific — must come before single)
    (re.compile(r"(\d{4})\s*[-–—]\s*(\d{4})"), "range"),
    # AZ single year
    (re.compile(r"(\d{4})\s*-ci\s*il"), "single"),
    (re.compile(r"(\d{4})\s*ci\s*il"), "single"),
    # Relative year
    (re.compile(r"son\s+(\d+)\s+il"), "from_years_ago"),
    (re.compile(r"son\s+il"), "last_year"),
    (re.compile(r"son\s+(\d+)\s+ay"), "from_months_ago"),
    # EN patterns
    (re.compile(r"last\s+(\d+)\s+(?:year|yrs?)"), "from_years_ago"),
    (re.compile(r"last\s+year"), "last_year"),
    (re.compile(r"past\s+(\d+)\s+(?:year|yrs?)"), "from_years_ago"),
    (re.compile(r"since\s+(\d{4})"), "since_year"),
    (re.compile(r"(\d{4})\s*ago"), "ago"),
    (re.compile(r"recent(?:ly)?"), "recent"),
    (re.compile(r"\b(\d{4})\b"), "single"),
]


# ---------------------------------------------------------------------------
# Frequency patterns (normalized forms — AZ chars already converted)
# ---------------------------------------------------------------------------

# Check multi-word patterns first, then single-word tokens
# All patterns use normalized (ASCII) forms since the input text is also normalized
_RAW_FREQUENCY_PATTERNS: list[tuple[str, str]] = [
    # AZ — multi-word
    ("uc ayliq", "quarterly"),
    ("ayliq melumat", "monthly"),
    ("illik melumat", "annual"),
    ("ilk melumat", "annual"),
    ("illlerle", "annual"),
    ("iller", "annual"),
    # EN — multi-word
    ("per annum", "annual"),
    ("per quarter", "quarterly"),
    ("per month", "monthly"),
    ("per year", "annual"),
    # EN — single words
    ("quarterly", "quarterly"),
    ("monthly", "monthly"),
    ("yearly", "annual"),
    ("annual", "annual"),
    ("weekly", "weekly"),
    ("daily", "daily"),
    ("recent", "annual"),
    ("latest", "annual"),
    ("current", "annual"),
    # AZ — single words
    ("ayliq", "monthly"),
    ("illik", "annual"),
    # EN — single words (ambiguous tokens)
    ("year", "annual"),
    ("month", "monthly"),
    ("quarter", "quarterly"),
]

# Sort by length descending so longer patterns match first
FREQUENCY_PATTERNS: list[tuple[str, str]] = sorted(
    _RAW_FREQUENCY_PATTERNS, key=lambda x: -len(x[0]),
)


# ---------------------------------------------------------------------------
# Stop words for concept matching
# ---------------------------------------------------------------------------

AZ_STOP_WORDS: set[str] = {
    # AZ function words
    "ki", "da", "de", "la", "le", "ve", "ise", "ile",
    "ucun", "barade", "ne", "kim", "har", "nece", "niye",
    "bele", "daha", "bir", "bu",
    # AZ common nouns
    "melumat", "verilir", "verdi", "gosterir",
    "teskilat", "statistika", "statistiki", "hesabat",
    "menbe", "qaynaq", "seviyye", "faiz", "deyer",
    "nisbet", "artim", "azalma", "deyisiklik",
    "plan", "proqram", "layihe", "faliyyet",
    "hereket", "qerar", "sual", "cavab",
    "serait", "istifade", "teti", "nezaret",
    "teli", "yoxlama", "sinaq", "hell",
    "merhele", "sebeb", "tesir", "netice",
    # EN stop words
    "the", "and", "of", "in", "for", "on", "with", "from", "to", "at",
    "by", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can",
    "not", "no", "nor", "so", "if", "then", "than",
    "too", "very", "just", "about", "above", "after",
    "again", "against", "all", "am", "an", "any", "as",
    "away", "back", "because", "before", "below", "between",
    "both", "but", "each", "else", "even", "every",
    "get", "got", "go", "gone", "here", "how",
    "into", "its", "it", "my", "new", "now",
    "off", "only", "other", "our", "out", "over",
    "own", "same", "some", "such", "take", "taken",
    "that", "there", "they", "this", "through",
    "under", "up", "us", "use", "used", "using",
    "what", "when", "where", "which", "while",
    "who", "whom", "why", "you", "your",
    "data", "statistics", "report", "indicator",
    "index", "level", "change", "growth",
}

AZ_STOP_WORDS_NORM = {_normalize(w) for w in AZ_STOP_WORDS}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class NLParseResult:
    """Result of parsing a natural language requirement."""

    text: str = ""
    concepts: list[str] = field(default_factory=list)
    """List of matched concept_ids (from SYNONYM_DICT keys)."""

    confidence: float = 0.0
    """Overall confidence of concept matching."""

    countries: list[str] = field(default_factory=list)
    """List of country codes (ISO 3166-1 alpha-2 or 'global')."""

    period_start: Optional[int] = None
    """Start year of the requested period."""

    period_end: Optional[int] = None
    """End year of the requested period."""

    period_type: Optional[str] = None
    """One of: range, single, from_years_ago, last_year, recent, since_year, ago."""

    frequency: Optional[str] = None
    """annual, monthly, quarterly, weekly, daily, or None."""

    raw: dict = field(default_factory=dict)
    """Raw extracted tokens for debugging."""


# ---------------------------------------------------------------------------
# Country extraction
# ---------------------------------------------------------------------------


def _extract_countries(text: str) -> list[str]:
    """Extract country codes from text.

    1. Check multi-word patterns in normalized text
    2. Tokenize with regex and check single-word matches
    Returns list of unique country codes. Defaults to ['global'].
    """
    norm = _normalize(text)
    found: list[str] = []

    # Check multi-word patterns
    for country, patterns in _COUNTRY_MULTIWORD:
        if any(p in norm for p in patterns):
            if country not in found:
                found.append(country)
        # Global is a fallback — only use if nothing else found
        if country == "global" and found:
            found = [c for c in found if c != "global"]

    # Single-word token matching
    tokens = re.findall(r"[a-z]+", norm)
    tokens = [t for t in tokens if t not in AZ_STOP_WORDS_NORM]

    for token in tokens:
        country = _COUNTRY_TOKENS.get(token)
        if country and country not in found:
            found.append(country)

    return found if found else ["global"]


# ---------------------------------------------------------------------------
# Period extraction
# ---------------------------------------------------------------------------


def _extract_period(text: str, year_offset: int = 0) -> dict:
    """Extract period info from text.

    Args:
        text: Normalized query text.
        year_offset: Current year offset for relative periods.

    Returns:
        Dict with keys: start, end, type
    """
    for pattern, ptype in _YEAR_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        if ptype == "range":
            start = int(match.group(1))
            end = int(match.group(2))
            return {"start": start, "end": end, "type": "range"}

        if ptype == "single":
            start = int(match.group(1))
            return {"start": start, "end": start, "type": "single"}

        if ptype == "from_years_ago":
            years = int(match.group(1))
            return {
                "start": year_offset - years,
                "end": year_offset - 1,
                "type": "from_years_ago",
            }

        if ptype == "last_year":
            return {
                "start": year_offset - 1,
                "end": year_offset - 1,
                "type": "last_year",
            }

        if ptype == "from_months_ago":
            months = int(match.group(1))
            years = months // 12
            return {
                "start": year_offset - years - (1 if months % 12 else 0),
                "end": year_offset,
                "type": "from_months_ago",
            }

        if ptype == "since_year":
            start = int(match.group(1))
            return {"start": start, "end": year_offset, "type": "since_year"}

        if ptype == "recent":
            return {"start": year_offset - 2, "end": year_offset, "type": "recent"}

        if ptype == "ago":
            years = (
                int(match.group(1))
                if match.lastindex and match.lastindex >= 1
                else 1
            )
            return {
                "start": year_offset - years,
                "end": year_offset - 1,
                "type": "ago",
            }

    return {"start": None, "end": None, "type": None}


# ---------------------------------------------------------------------------
# Frequency extraction
# ---------------------------------------------------------------------------


def _extract_frequency(text: str) -> Optional[str]:
    """Extract frequency from text using normalized matching."""
    norm = _normalize(text)

    # Check multi-word patterns first (sorted by length descending)
    for pattern, freq in sorted(FREQUENCY_PATTERNS, key=lambda x: -len(x[0])):
        if pattern in norm:
            return freq

    return None


# ---------------------------------------------------------------------------
# Concept extraction (uses semantic resolver)
# ---------------------------------------------------------------------------


def _extract_concepts(text: str) -> tuple[list[str], float]:
    """Extract concept IDs from text using the semantic resolver.

    Returns (concept_ids, confidence).
    """
    from collector.semantic_resolver import resolve_catalogue_entry

    result = resolve_catalogue_entry({
        "entry_id": "nl",
        "title": text,
        "description": "",
        "indicator_code": "",
        "source_id": "nl",
    })

    concept_ids = []
    confidence = 0.0

    for candidate in result.candidates:
        concept_ids.append(candidate.concept_id)
        if candidate.confidence > confidence:
            confidence = candidate.confidence

    return concept_ids, confidence


# ---------------------------------------------------------------------------
# Stop word check for remaining text
# ---------------------------------------------------------------------------


def _count_meaningful_tokens(text: str) -> int:
    """Count tokens that are not stop words."""
    norm = _normalize(text)
    tokens = re.findall(r"[a-z]+", norm)
    return sum(1 for t in tokens if t not in AZ_STOP_WORDS_NORM)


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_requirement(text: str, current_year: int = 2025) -> NLParseResult:
    """Parse a natural language requirement into structured fields.

    Extracts concepts, countries, periods, and frequency from the query.
    Uses deterministic extraction first. LLM gate triggers when:
    - Multiple concepts match (ambiguous request)
    - Very low confidence (<0.60) with meaningful text

    Args:
        text: The user's query string (AZ or EN).
        current_year: Reference year for relative periods. Defaults to 2025.

    Returns:
        NLParseResult with extracted fields.
    """
    if not text or not text.strip():
        return NLParseResult(text="")

    result = NLParseResult(text=text.strip())

    # Extract countries
    result.countries = _extract_countries(text)

    # Extract period (use raw text to preserve hyphens in year ranges)
    period_info = _extract_period(text, year_offset=current_year)
    norm_text = _normalize(text)
    result.period_start = period_info["start"]
    result.period_end = period_info["end"]
    result.period_type = period_info["type"]

    # Extract frequency
    result.frequency = _extract_frequency(text)

    # Extract concepts via semantic resolver
    meaningful_tokens = _count_meaningful_tokens(text)
    result.concepts, result.confidence = _extract_concepts(text)

    # Raw extraction info for debugging
    result.raw = {
        "normalized": norm_text,
        "period": period_info,
        "meaningful_tokens": meaningful_tokens,
    }

    return result


# ---------------------------------------------------------------------------
# LLM gate — determines if LLM is needed
# ---------------------------------------------------------------------------


def needs_llm(result: NLParseResult) -> bool:
    """Determine if LLM disambiguation is needed.

    Triggers when:
    1. Confidence is 0.60–0.79 (ambiguous tier) — LLM to confirm
    2. Meaningful tokens > 0 but NO concept matched — LLM to identify

    Returns False for strong matches (≥0.80) or empty/no meaningful text.
    """
    if result.confidence >= 0.80:
        return False

    # Ambiguous tier — LLM should confirm
    if 0.60 <= result.confidence < 0.80:
        return True

    # No concept matched but user wrote something meaningful
    if result.raw.get("meaningful_tokens", 0) > 0 and not result.concepts:
        return True

    return False


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def parse_and_check(text: str, current_year: int = 2025) -> dict:
    """Parse + LLM check, return serializable dict.

    Convenience function for CLI / API endpoints.
    """
    result = parse_requirement(text, current_year)
    return {
        "text": result.text,
        "concepts": result.concepts,
        "confidence": round(result.confidence, 4),
        "countries": result.countries,
        "period_start": result.period_start,
        "period_end": result.period_end,
        "period_type": result.period_type,
        "frequency": result.frequency,
        "needs_llm": needs_llm(result),
        "raw": result.raw,
    }