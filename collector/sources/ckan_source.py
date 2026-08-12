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

logger = logging.getLogger("collector.ckan")


class CKANSource:
    def __init__(self, source_cfg: dict):
        self.id = source_cfg["id"]
        self.base_url = source_cfg["base_url"].rstrip("/")
        self.filter = source_cfg.get("filter", {}) or {}
        self.require_open_license = source_cfg.get("require_open_license", True)
        self.rate_limit = source_cfg.get("rate_limit_per_sec", 2)
        self._last_call = 0.0

    # ---------- aşağı səviyyəli HTTP köməkçisi ----------
    def _throttle(self):
        elapsed = time.time() - self._last_call
        min_gap = 1.0 / max(self.rate_limit, 0.1)
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)
        self._last_call = time.time()

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
        """Portaldakı bütün dataset (package) adlarını gətirir."""
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
