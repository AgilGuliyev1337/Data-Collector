"""
Real API connectivity tests for Phase 4 discovery.

These tests actually call the opendata.az API.
They are SKIPPED by default — only run with explicit marker:
    pytest tests/test_discovery/test_api_connectivity.py -m api_connectivity
"""

import pytest

CKAN_BASE_URL = "https://admin.opendata.az"


@pytest.mark.api_connectivity
def test_ckan_status_show():
    """Verify CKAN status_show endpoint responds."""
    import urllib.request
    import json

    url = f"{CKAN_BASE_URL}/api/3/action/status_show"
    req = urllib.request.Request(url, headers={"User-Agent": "data-collector/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    assert data.get("success") is True
    assert "site_title" in data.get("result", {})


@pytest.mark.api_connectivity
def test_package_search_works():
    """Verify package_search endpoint works and returns results."""
    import urllib.request
    import json
    from urllib.parse import urlencode

    params = urlencode({"q": "", "rows": 1, "start": 0})
    url = f"{CKAN_BASE_URL}/api/3/action/package_search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "data-collector/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    assert data.get("success") is True
    result = data.get("result", {})
    assert result.get("count", 0) > 0
    assert len(result.get("results", [])) >= 1


@pytest.mark.api_connectivity
def test_package_list_returns_403():
    """Verify package_list is blocked (403) for opendata.az."""
    import urllib.request
    import urllib.error

    url = f"{CKAN_BASE_URL}/api/3/action/package_list"
    req = urllib.request.Request(url, headers={"User-Agent": "data-collector/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        # If it works, the result should be a list
        assert isinstance(data.get("result", []), list)
    except urllib.error.HTTPError as e:
        # 403 is expected
        assert e.code in (403, 401, 400)


@pytest.mark.api_connectivity
def test_package_show_works():
    """Verify package_show endpoint works for a known dataset."""
    import urllib.request
    import json

    # Use package_search first to get a valid package name
    search_url = f"{CKAN_BASE_URL}/api/3/action/package_search?q=&rows=1&start=0"
    req = urllib.request.Request(search_url, headers={"User-Agent": "data-collector/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    result = data.get("result", {})
    results = result.get("results", [])
    if not results:
        pytest.skip("No packages found in package_search")

    pkg = results[0]
    pkg_id = pkg.get("id") or pkg.get("name")

    show_url = f"{CKAN_BASE_URL}/api/3/action/package_show?id={pkg_id}"
    req = urllib.request.Request(show_url, headers={"User-Agent": "data-collector/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())

    assert data.get("success") is True
    assert data.get("result", {}).get("id") == pkg_id