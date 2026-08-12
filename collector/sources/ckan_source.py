"""
CKAN əsaslı open-data portallar üçün universal collector.

CKAN dünyada ən çox yayılmış açıq-data platformasıdır (opendata.az,
data.gov, opendata.swiss, EU portallari və s. hamısı CKAN üzərindədir).
Ona görə bir dəfə yazılan bu modul, config.yaml-a yeni "base_url"
əlavə etməklə istənilən CKAN portalında işləyir.
"""

import time
import logging
import urllib.request
import json
from urllib.parse import urlencode

from collector.sources.base import DataSource

logger = logging.getLogger("collector.ckan")


class CKANSource(DataSource):
    PAGE_SIZE = 100

    def __init__(self, source_cfg: dict):
        self.id = source_cfg["id"]
        self.base_url = source_cfg["base_url"].rstrip("/")
        self.filter = source_cfg.get("filter", {}) or {}
        self.require_open_license = source_cfg.get("require_open_license", True)
        self.rate_limit_per_sec = source_cfg.get("rate_limit_per_sec", 2)
        self.priority_tier = source_cfg.get("priority_tier")
        self.trust_level = source_cfg.get("trust_level", "official")
        self._last_call = 0.0

    # ---------- aşağı səviyyəli HTTP köməkçisi ----------
    def _throttle(self):
        elapsed = time.time() - self._last_call
        min_gap = 1.0 / max(self.rate_limit_per_sec, 0.1)
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)
        self._last_call = time.time()

    # ---------- DataSource ABC ----------
    def validate_connection(self) -> bool:
        return bool(self._api_get("status_show"))

    def fetch(self, **kwargs):
        return list(self.collect())

    def metadata(self) -> dict:
        return {"id": self.id, "type": "ckan", "base_url": self.base_url}

    def rate_limit(self):
        return self.rate_limit_per_sec

    def _api_get(self, action: str, params: dict = None) -> dict:
        self._throttle()
        url = f"{self.base_url}/api/3/action/{action}"
        if params:
            url += "?" + urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "data-collector/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                if not data.get("success"):
                    logger.warning("API uğursuz cavab: %s -> %s", url, data)
                    return {}
                return data.get("result", {})
        except Exception as e:
            logger.error("Sorğu xətası (%s): %s", url, e)
            return {}

    # ---------- əsas metodlar ----------
    def list_package_names(self) -> list:
        """Portaldakı bütün dataset (package) adlarını gətirir.

        Qeyd: opendata.az üçün bu endpoint 403 qaytarır.
        Əvəzində list_package_names_via_search() işlədir.
        """
        result = self._api_get("package_list")
        return result if isinstance(result, list) else []

    def get_package(self, name: str) -> dict:
        """Bir dataset üçün tam metadata (resurslar daxil)."""
        return self._api_get("package_show", {"id": name})

    def _passes_filter(self, pkg: dict) -> bool:
        # lisenziya yoxlaması
        if self.require_open_license:
            license_id = (pkg.get("license_id") or "").lower()
            open_licenses = {"cc-zero", "cc-by", "cc-by-sa", "odc-odbl", "odc-by", "other-open"}
            if license_id not in open_licenses:
                return False

        groups_filter = set(self.filter.get("groups") or [])
        if groups_filter:
            pkg_groups = {g.get("name") for g in pkg.get("groups", [])}
            if not (pkg_groups & groups_filter):
                return False

        tags_filter = set(self.filter.get("tags") or [])
        if tags_filter:
            pkg_tags = {t.get("name") for t in pkg.get("tags", [])}
            if not (pkg_tags & tags_filter):
                return False

        return True

    def list_package_names_via_search(self, query: str = "", rows: int = None, start: int = 0) -> list:
        """Use package_search API (works when package_list is blocked).

        Paginated: returns all matching package names by iterating
        through pages until no more results.
        """
        rows = rows or self.PAGE_SIZE
        all_names: list[str] = []
        current_start = start

        while True:
            result = self._api_get(
                "package_search",
                {"q": query, "rows": rows, "start": current_start},
            )
            results_list = result.get("results", [])
            if not results_list:
                break

            all_names.extend(pkg["name"] for pkg in results_list if "name" in pkg)

            total = result.get("count", 0)
            if current_start + len(results_list) >= total:
                break
            current_start += len(results_list)

        logger.info(
            "[%s] package_search: %d / %d paket tapıldı",
            self.id, len(all_names), total if "total" in dir() else len(all_names),
        )
        return all_names

    def discover_catalogue(self) -> list[dict]:
        """
        Discover all datasets from this CKAN portal.

        Uses package_search (paginated) since package_list may return 403.
        Returns catalogue_entry-compatible dicts, one per dataset.
        """
        # Try package_list first (fast, no pagination). If 403 falls through
        # to _api_get returning {}, fall back to package_search.
        names = self.list_package_names()
        if not names:
            logger.info("[%s] package_list boş/403, package_search-a keçir", self.id)
            names = self.list_package_names_via_search()

        logger.info("[%s] Kataloqda %d dataset tapıldı (discover)", self.id, len(names))

        entries: list[dict] = []
        for name in names:
            pkg = self.get_package(name)
            if not pkg:
                continue

            # Filter if configured
            if not self._passes_filter(pkg):
                continue

            # Extract resources info for methodology_note
            resources = pkg.get("resources", [])
            resource_urls = [r.get("url") for r in resources if r.get("url")]
            methodology_note = "; ".join(resource_urls) if resource_urls else None

            # Extract time coverage from metadata fields if available
            time_start = pkg.get("temporal_start") or None
            time_end = pkg.get("temporal_end") or None

            # Extract country coverage from tags or metadata
            country_coverage = []
            for tag in (pkg.get("tags") or []):
                tag_name = (tag.get("name") or "").lower()
                if "azerbaijan" in tag_name or "az" in tag_name:
                    country_coverage.append("AZ")
                    break  # only add AZ once

            entry = {
                "entry_id": f"{self.id}:{pkg.get('id', name)}",
                "source_id": self.id,
                "dataset_id": pkg.get("id"),
                "indicator_code": pkg.get("name", name),
                "title": pkg.get("title") or name,
                "description": pkg.get("notes") or pkg.get("description") or "",
                "unit": None,
                "frequency": None,
                "country_coverage": country_coverage,
                "time_coverage_start": time_start,
                "time_coverage_end": time_end,
                "methodology_note": methodology_note,
            }
            entries.append(entry)

        return entries

    def collect(self):
        """
        Generator: uyğun gələn hər dataset üçün normalize edilmiş dict qaytarır.
        """
        names = self.list_package_names()
        logger.info("[%s] Kataloqda %d dataset tapıldı", self.id, len(names))

        for name in names:
            pkg = self.get_package(name)
            if not pkg:
                continue
            if not self._passes_filter(pkg):
                continue

            resources = [
                {
                    "name": r.get("name"),
                    "format": r.get("format"),
                    "url": r.get("url"),
                    "size": r.get("size"),
                }
                for r in pkg.get("resources", [])
            ]

            yield {
                "source_id": self.id,
                "dataset_id": pkg.get("id"),
                "name": pkg.get("name"),
                "title": pkg.get("title"),
                "org": (pkg.get("organization") or {}).get("title"),
                "license": pkg.get("license_title"),
                "license_id": pkg.get("license_id"),
                "modified": pkg.get("metadata_modified"),
                "tags": [t.get("name") for t in pkg.get("tags", [])],
                "groups": [g.get("name") for g in pkg.get("groups", [])],
                "resources": resources,
            }
