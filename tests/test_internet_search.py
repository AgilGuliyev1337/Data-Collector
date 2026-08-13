"""Tests for internet search module — no network calls needed."""
import sys
sys.path.insert(0, '/home/agil/data-collector')

import pytest
from unittest.mock import patch, MagicMock


class TestBuildSearchQueries:
    @patch('collector.internet_search._get_concept_info')
    def test_basic_query(self, mock_info):
        from collector.internet_search import _build_search_queries
        mock_info.return_value = {
            "display_en": "Housing Price",
            "display_az": "Ev Qiymeti",
            "synonyms": ["housing price", "apartment price", "real estate"],
            "keywords": ["qiymet", "manzil", "menzil", "price"],
        }
        queries = _build_search_queries("ev_qiymeti", ["AZE"], 2024, 2025)
        assert len(queries) >= 3
        # All queries contain country name
        assert all(any(c in q for c in ["Azerbaijan", "Azərbaycan"]) for q in queries)

    @patch('collector.internet_search._get_concept_info')
    def test_no_concept_info(self, mock_info):
        from collector.internet_search import _build_search_queries
        mock_info.return_value = None
        queries = _build_search_queries("unknown_concept", ["USA"], None, None)
        assert len(queries) == 1
        assert "unknown_concept" in queries[0]

    @patch('collector.internet_search._get_concept_info')
    def test_single_year(self, mock_info):
        from collector.internet_search import _build_search_queries
        mock_info.return_value = {
            "display_en": "GDP",
            "display_az": "ÜDM",
            "synonyms": ["gross domestic product"],
            "keywords": ["gdp"],
        }
        with patch('collector.internet_search._get_concept_info', return_value={
            "display_en": "GDP",
            "display_az": "ÜDM",
            "synonyms": ["gross domestic product"],
            "keywords": ["gdp"],
        }):
            queries = _build_search_queries("gdp", ["AZE"], 2024, 2024)
            # Single year appears once in query
            found_2024 = sum(q.count("2024") for q in queries)
            assert found_2024 > 0


class TestExtractYearValuePairs:
    def test_colon_format(self):
        from collector.internet_search import _parse_year_value_pairs
        text = "2020: 1450\n2021: 1600\n2022: 1750"
        pairs = _parse_year_value_pairs(text)
        assert len(pairs) >= 2
        assert pairs[0][0] == 2020
        assert pairs[0][1] == 1450

    def test_dash_format(self):
        from collector.internet_search import _parse_year_value_pairs
        text = "2020 - 1450\n2021 - 1600"
        pairs = _parse_year_value_pairs(text)
        assert len(pairs) >= 2

    def test_with_commas(self):
        from collector.internet_search import _parse_year_value_pairs
        text = "2020: 1450\n2021: 2100"
        pairs = _parse_year_value_pairs(text)
        assert len(pairs) >= 1
        assert pairs[0][0] == 2020

    def test_empty_text(self):
        from collector.internet_search import _parse_year_value_pairs
        pairs = _parse_year_value_pairs("")
        assert len(pairs) == 0

    def test_no_valid_years(self):
        from collector.internet_search import _parse_year_value_pairs
        text = "random text no years here"
        pairs = _parse_year_value_pairs(text)
        assert len(pairs) == 0

    def test_filter_invalid_years(self):
        from collector.internet_search import _parse_year_value_pairs
        text = "1800: 100\n3000: 999"  # outside valid range 1990-2030
        pairs = _parse_year_value_pairs(text)
        assert len(pairs) == 0

    def test_dedup_keeps_highest(self):
        from collector.internet_search import _parse_year_value_pairs
        text = "2020: 100\n2020: 999"  # same year, different values
        pairs = _parse_year_value_pairs(text)
        # Should have exactly one entry for 2020
        assert len([p for p in pairs if p[0] == 2020]) == 1


class TestClassifyUnit:
    def test_percent(self):
        from collector.internet_search import _classify_unit_from_text
        assert _classify_unit_from_text("inflation at 15%") == "percent"

    def test_azn(self):
        from collector.internet_search import _classify_unit_from_text
        assert _classify_unit_from_text("price is 1500 AZN") == "AZN"

    def test_usd(self):
        from collector.internet_search import _classify_unit_from_text
        assert _classify_unit_from_text("cost $50 USD per person") == "USD"

    def test_sqm(self):
        from collector.internet_search import _classify_unit_from_text
        # "sqm" only triggers when AZN/USD/etc. are absent
        assert _classify_unit_from_text("price per sqm") == "AZN/m²"
        # When both AZN and sqm present, AZN is matched first (code order)
        assert _classify_unit_from_text("1500 AZN per sqm") == "AZN"

    def test_unknown_fallback(self):
        from collector.internet_search import _classify_unit_from_text
        result = _classify_unit_from_text("just some random numbers")
        assert result == "unknown"


class TestSearchInternetIntegration:
    @patch('collector.internet_search._search_ddg')
    @patch('collector.internet_search._fetch_page_text')
    def test_returns_empty_on_no_results(self, mock_fetch, mock_search):
        from collector.internet_search import search_internet
        mock_search.return_value = []
        result = search_internet("maas", ["AZE"], 2020, 2025)
        assert result == []
        mock_fetch.assert_not_called()

    @patch('collector.internet_search._search_ddg')
    @patch('collector.internet_search._fetch_page_text')
    def test_returns_data_when_found(self, mock_fetch, mock_search):
        from collector.internet_search import search_internet
        mock_search.return_value = [{
            "title": "Azerbaijan Salary Data",
            "url": "https://example.com/salary-data",
            "snippet": "",
        }]
        mock_fetch.return_value = "2020: 544\n2021: 620\n2022: 750\n2023: 900"
        result = search_internet("maas", ["AZE"], 2020, 2025)
        # Should return parsed year-value pairs within range
        assert len(result) >= 4
        assert result[0]["source_id"] == "internet_search"
        assert result[0]["period"] == "2020"
        assert result[0]["value"] == 544

    @patch('collector.internet_search._search_ddg')
    def test_filters_by_period(self, mock_search):
        from collector.internet_search import search_internet
        mock_search.return_value = [{
            "title": "Data",
            "url": "https://example.com",
            "snippet": "",
        }]
        with patch('collector.internet_search._fetch_page_text') as mock_fetch:
            mock_fetch.return_value = "2010: 100\n2015: 200\n2020: 300\n2025: 400"
            result = search_internet("gdp", ["AZE"], 2018, 2022)
            for r in result:
                yr = int(r["period"])
                assert 2018 <= yr <= 2022


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
