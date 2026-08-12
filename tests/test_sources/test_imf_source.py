from unittest.mock import patch

from collector.sources.imf_source import IMFSource


def test_get_series_parses_sdmx_json(fake_response, load_fixture):
    src = IMFSource()
    payload = load_fixture("imf_response.json")
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response(payload)
        rows = src.get_series("IFS", "A.AZ.NGDP_R_XDC", 2020, 2021)

    assert len(rows) == 2
    assert rows[0]["country"] == "AZ"
    assert rows[0]["year"] == "2020"
    assert rows[0]["value"] == "100"
    assert rows[1]["year"] == "2021"


def test_list_dataflows_parses_structure(fake_response):
    src = IMFSource()
    payload = {
        "Structure": {"Dataflows": {"Dataflow": [
            {"KeyFamilyRef": {"KeyFamilyID": "IFS"}, "Name": {"#text": "International Financial Statistics"}},
        ]}},
    }
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response(payload)
        flows = src.list_dataflows()

    assert flows == [{"id": "IFS", "name": "International Financial Statistics"}]


def test_get_series_returns_empty_on_bad_key(fake_response):
    src = IMFSource()
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response({"CompactData": {}})
        assert src.get_series("IFS", "bad.key", 2020, 2021) == []


def test_validate_connection_false_on_request_error():
    src = IMFSource()
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        assert src.validate_connection() is False
