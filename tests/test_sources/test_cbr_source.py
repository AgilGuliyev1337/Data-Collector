from unittest.mock import patch

from collector.sources.cbr_source import CBRSource


def test_get_daily_rates_parses_response(fake_response, load_fixture):
    src = CBRSource()
    payload = load_fixture("cbr_response.json")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response(payload)
        rows = src.get_daily_rates()

    assert len(rows) == 2
    by_currency = {r["currency"]: r for r in rows}
    assert by_currency["USD"]["value_rub"] == 90.0
    assert by_currency["USD"]["source"] == "cbr_russia"
    assert by_currency["USD"]["date"] == "2024-01-15T11:30:00+03:00"


def test_get_daily_rates_returns_empty_on_error():
    src = CBRSource()
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        assert src.get_daily_rates() == []


def test_fetch_delegates_to_get_daily_rates(fake_response, load_fixture):
    src = CBRSource()
    payload = load_fixture("cbr_response.json")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response(payload)
        rows = src.fetch()

    assert len(rows) == 2
    assert {r["currency"] for r in rows} == {"USD", "EUR"}
