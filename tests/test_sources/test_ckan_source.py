from unittest.mock import patch

from collector.sources.ckan_source import CKANSource


def make_source():
    return CKANSource({
        "id": "test_ckan",
        "base_url": "https://example.test",
        "require_open_license": True,
        "rate_limit_per_sec": 1000,
    })


def test_collect_yields_only_open_license_datasets(fake_response, load_fixture):
    src = make_source()
    package_list = load_fixture("ckan_package_list.json")
    show_one = load_fixture("ckan_package_show_dataset_one.json")
    show_two = load_fixture("ckan_package_show_dataset_two.json")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = [
            fake_response(package_list),
            fake_response(show_one),
            fake_response(show_two),
        ]
        records = list(src.collect())

    assert len(records) == 1
    assert records[0]["source_id"] == "test_ckan"
    assert records[0]["dataset_id"] == "abc123"
    assert records[0]["tags"] == ["trade"]
    assert records[0]["resources"][0]["format"] == "CSV"


def test_validate_connection_true_on_success_response(fake_response):
    src = make_source()
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = fake_response({"success": True, "result": {"version": "2.10"}})
        assert src.validate_connection() is True


def test_validate_connection_false_on_network_error():
    src = make_source()
    with patch("urllib.request.urlopen", side_effect=OSError("boom")):
        assert src.validate_connection() is False


def test_fetch_delegates_to_collect(fake_response, load_fixture):
    src = make_source()
    package_list = load_fixture("ckan_package_list.json")
    show_one = load_fixture("ckan_package_show_dataset_one.json")
    show_two = load_fixture("ckan_package_show_dataset_two.json")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = [
            fake_response(package_list),
            fake_response(show_one),
            fake_response(show_two),
        ]
        records = src.fetch()

    assert isinstance(records, list)
    assert len(records) == 1
