from unittest.mock import patch

from collector.sources.eurostat_source import EurostatSource


def test_get_indicator_parses_json_stat(fake_response, load_fixture):
    src = EurostatSource()
    payload = load_fixture("eurostat_response.json")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response(payload)
        rows = src.get_indicator("une_rt_a", ["DE", "FR"], 2020, 2021)

    by_geo_year = {(r["country"], r["year"]): r["value"] for r in rows}
    assert len(rows) == 4
    assert by_geo_year[("DE", "2020")] == 5.0
    assert by_geo_year[("DE", "2021")] == 5.5
    assert by_geo_year[("FR", "2020")] == 8.0
    assert by_geo_year[("FR", "2021")] == 7.5


def test_get_indicator_returns_empty_when_dataset_missing(fake_response):
    src = EurostatSource()
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response({"error": "not found"})
        assert src.get_indicator("bad_code", ["DE"], 2020, 2021) == []


def test_get_indicator_returns_empty_on_request_error():
    src = EurostatSource()
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        assert src.get_indicator("une_rt_a", ["DE"], 2020, 2021) == []
