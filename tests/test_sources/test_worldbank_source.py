from unittest.mock import patch

from collector.sources.worldbank_source import WorldBankSource


def test_compare_normalizes_rows(fake_response, load_fixture):
    src = WorldBankSource()
    payload = load_fixture("worldbank_response.json")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response(payload)
        rows = src.compare(["AZE"], "gdp_per_capita", 2020, 2021)

    assert len(rows) == 2
    assert rows[0]["iso3"] == "AZE"
    assert rows[0]["country"] == "Azerbaijan"
    assert rows[0]["value"] == 5408.04535175023


def test_resolve_indicator_maps_short_name_to_code():
    src = WorldBankSource()
    assert src.resolve_indicator("gdp_per_capita") == "NY.GDP.PCAP.CD"
    assert src.resolve_indicator("NY.GDP.MKTP.CD") == "NY.GDP.MKTP.CD"


def test_compare_returns_empty_list_on_request_error():
    src = WorldBankSource()
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        assert src.compare(["AZE"], "gdp", 2020, 2021) == []


def test_validate_connection_false_on_empty_response(fake_response):
    src = WorldBankSource()
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response([{"page": 1}, []])
        assert src.validate_connection() is False
