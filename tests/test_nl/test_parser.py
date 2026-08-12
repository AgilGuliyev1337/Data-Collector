"""
Phase 6 — Natural Language Requirement Parser tests.

Tests concept/country/period/frequency extraction from AZ and EN queries.
No LLM calls — deterministic extraction only.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from collector.nl_parser import (
    parse_requirement,
    parse_and_check,
    needs_llm,
    _extract_countries,
    _extract_period,
    _extract_frequency,
    _extract_concepts,
    _count_meaningful_tokens,
)


# ---------------------------------------------------------------------------
# Country extraction tests
# ---------------------------------------------------------------------------

class TestExtractCountries:
    def test_azerbaijan(self):
        result = _extract_countries("Azerbaijan GDP data")
        assert "AZ" in result

    def test_dunya_global(self):
        result = _extract_countries("Dünya üzrə göstəricilər")
        assert "global" in result

    def test_turkiye(self):
        result = _extract_countries("Türkiyə iqtisadiyyat")
        assert "TR" in result

    def test_multiple_countries(self):
        result = _extract_countries("Azerbaijan and Turkey trade")
        assert "AZ" in result
        assert "TR" in result

    def test_default_global(self):
        """No country mentioned → defaults to ['global']."""
        result = _extract_countries("GDP growth data")
        assert result == ["global"]

    def test_eu(self):
        result = _extract_countries("Avropa Birliyi statistikası")
        assert "EU" in result

    def test_us(self):
        result = _extract_countries("Amerika Birləşmiş Ştatları")
        assert "US" in result

    def test_georgia(self):
        result = _extract_countries("Gürcüstan haqqında")
        assert "GE" in result

    def test_kazakhstan(self):
        result = _extract_countries("Qazaxıstan iqtisadiyyat")
        assert "KZ" in result


# ---------------------------------------------------------------------------
# Period extraction tests
# ---------------------------------------------------------------------------

class TestExtractPeriod:
    def test_year_range(self):
        result = _extract_period("2020-2024", year_offset=2025)
        assert result["start"] == 2020
        assert result["end"] == 2024
        assert result["type"] == "range"

    def test_single_year_az(self):
        result = _extract_period("2023-cü il", year_offset=2025)
        assert result["start"] == 2023
        assert result["end"] == 2023

    def test_single_year_en(self):
        result = _extract_period("last year in 2024", year_offset=2025)
        # Should find the single year 2024
        assert result["start"] == 2024
        assert result["end"] == 2024

    def test_from_years_ago_az(self):
        result = _extract_period("son 5 il", year_offset=2025)
        assert result["start"] == 2020
        assert result["end"] == 2024
        assert result["type"] == "from_years_ago"

    def test_last_year_az(self):
        result = _extract_period("son il", year_offset=2025)
        assert result["start"] == 2024
        assert result["end"] == 2024

    def test_last_year_en(self):
        result = _extract_period("last year", year_offset=2025)
        assert result["start"] == 2024
        assert result["end"] == 2024
        assert result["type"] == "last_year"

    def test_since_year(self):
        result = _extract_period("since 2020", year_offset=2025)
        assert result["start"] == 2020
        assert result["end"] == 2025
        assert result["type"] == "since_year"

    def test_recent(self):
        result = _extract_period("recent", year_offset=2025)
        assert result["start"] == 2023
        assert result["end"] == 2025

    def test_no_period(self):
        result = _extract_period("no period mentioned", year_offset=2025)
        assert result["start"] is None
        assert result["end"] is None

    def test_range_with_en_dash(self):
        result = _extract_period("2018–2022", year_offset=2025)
        assert result["start"] == 2018
        assert result["end"] == 2022

    def test_range_with_em_dash(self):
        result = _extract_period("2018—2022", year_offset=2025)
        assert result["start"] == 2018
        assert result["end"] == 2022


# ---------------------------------------------------------------------------
# Frequency extraction tests
# ---------------------------------------------------------------------------

class TestExtractFrequency:
    def test_annual_az(self):
        assert _extract_frequency("illik məlumat") == "annual"

    def test_annual_en(self):
        assert _extract_frequency("annual data") == "annual"

    def test_monthly_az(self):
        assert _extract_frequency("aylıq statistika") == "monthly"

    def test_monthly_en(self):
        assert _extract_frequency("monthly report") == "monthly"

    def test_quarterly_az(self):
        assert _extract_frequency("üç aylıq") == "quarterly"

    def test_quarterly_en(self):
        assert _extract_frequency("quarterly data") == "quarterly"

    def test_no_frequency(self):
        assert _extract_frequency("no frequency mentioned") is None


# ---------------------------------------------------------------------------
# Concept extraction tests
# ---------------------------------------------------------------------------

class TestExtractConcepts:
    def test_gdp_growth(self):
        concepts, confidence = _extract_concepts("ÜDM artımı")
        assert "gdp_growth" in concepts
        assert confidence > 0

    def test_population(self):
        concepts, confidence = _extract_concepts("Əhali")
        assert "population" in concepts
        assert confidence > 0

    def test_unemployment(self):
        concepts, confidence = _extract_concepts("İşsizlik")
        assert "unemployment" in concepts
        assert confidence > 0

    def test_inflation(self):
        concepts, confidence = _extract_concepts("İnflyasiya")
        assert "inflation" in concepts
        assert confidence > 0

    def test_exports(self):
        concepts, confidence = _extract_concepts("İxrac")
        assert "exports" in concepts
        assert confidence > 0

    def test_no_concept(self):
        concepts, confidence = _extract_concepts("Hotel revenue data")
        assert "gdp_growth" not in concepts
        assert "population" not in concepts


# ---------------------------------------------------------------------------
# Full parse_requirement tests
# ---------------------------------------------------------------------------

class TestParseRequirement:
    def test_full_az_query(self):
        """AZ query with concept + country + period."""
        result = parse_requirement("2020-2024 illik ÜDM artımı Azərbaycanda")
        assert "gdp_growth" in result.concepts
        assert "AZ" in result.countries
        assert result.period_start == 2020
        assert result.period_end == 2024
        assert result.frequency == "annual"

    def test_full_en_query(self):
        """EN query with concept + country + period."""
        result = parse_requirement("GDP growth in Azerbaijan last year")
        assert "gdp_growth" in result.concepts
        assert "AZ" in result.countries
        assert result.period_start == 2024
        assert result.period_end == 2024

    def test_empty_query(self):
        result = parse_requirement("")
        assert result.text == ""
        assert result.concepts == []

    def test_only_country(self):
        """Query with only country, no concept."""
        result = parse_requirement("Azerbaijan statistics")
        assert "AZ" in result.countries

    def test_only_period(self):
        result = parse_requirement("son 5 il məlumat")
        assert result.period_start == 2020
        assert result.period_end == 2024

    def test_empty_whitespace(self):
        result = parse_requirement("   ")
        assert result.text == ""

    def test_raw_field(self):
        result = parse_requirement("ÜDM artımı 2020-2024")
        assert "normalized" in result.raw
        assert "period" in result.raw
        assert "meaningful_tokens" in result.raw


# ---------------------------------------------------------------------------
# needs_llm tests
# ---------------------------------------------------------------------------

class TestNeedsLLM:
    def test_strong_match_no_llm(self):
        """Strong concept match (≥0.80) → no LLM."""
        # Use a title with both display_name and keyword match for strong confidence
        result = parse_requirement("GDP Growth Rate of Azerbaijan")
        assert needs_llm(result) is False

    def test_single_keyword_needs_llm(self):
        """Single keyword match → ambiguous (LLM gate)."""
        result = parse_requirement("ÜDM artımı 2020")
        assert result.confidence < 0.80
        assert needs_llm(result) is True

    def test_no_concept_low_conf(self):
        """No concept, but meaningful tokens → LLM needed."""
        result = parse_requirement("Mehmanxana gəliri")
        assert result.confidence < 0.60
        assert needs_llm(result) is True

    def test_empty_result(self):
        result = parse_requirement("")
        assert needs_llm(result) is False


# ---------------------------------------------------------------------------
# parse_and_check (convenience) tests
# ---------------------------------------------------------------------------

class TestParseAndCheck:
    def test_returns_dict(self):
        result = parse_and_check("ÜDM artımı 2020-2024")
        assert isinstance(result, dict)
        assert "text" in result
        assert "concepts" in result
        assert "confidence" in result
        assert "countries" in result
        assert "period_start" in result
        assert "period_end" in result
        assert "period_type" in result
        assert "frequency" in result
        assert "needs_llm" in result

    def test_serializable(self):
        import json
        result = parse_and_check("Dünya üzrə əhali")
        json.dumps(result)  # Should not raise


# ---------------------------------------------------------------------------
# Stop words / tokenization tests
# ---------------------------------------------------------------------------

class TestTokenCount:
    def test_meaningful_tokens_gdp(self):
        count = _count_meaningful_tokens("ÜDM artımı")
        assert count >= 1

    def test_meaningful_tokens_stopwords_only(self):
        """All stop words → zero meaningful tokens."""
        count = _count_meaningful_tokens("və da də bu")
        assert count == 0

    def test_meaningful_tokens_empty(self):
        count = _count_meaningful_tokens("")
        assert count == 0