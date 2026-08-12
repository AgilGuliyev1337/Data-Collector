"""
Web Discovery — Phase 9.

Məlumu açıq data portallarını (data.gov, data.gov.az, data.europa.eu)
scan edir, tapılan CKAN portal-larını `sources` cədvəlinə əlavə edir.

Flow:
  KNOWN_PORTALS → HTTP HEAD/GET → status_show → CKAN deyil → skip
                                  ↓ yes
                              sources upsert (priority_tier 6, discovery_method "web")

Haradda connection ilə işləyir, commit etmir.
"""

import logging
import urllib.request
import json

from collector.db import repository

logger = logging.getLogger("collector.web_discovery")

# Məlumu açıq data portal URL-ləri
KNOWN_PORTALS = [
    {"url": "https://data.gov.az", "name": "Azerbaijan Open Data"},
    {"url": "https://data.gov", "name": "US Data.gov"},
    {"url": "https://data.europa.eu", "name": "EU Data Portal"},
    {"url": "https://data.worldbank.org", "name": "World Bank Open Data"},
    {"url": "https://data.un.org", "name": "UN Data Portal"},
]


def _is_ckan_portal(url: str, timeout: int = 10) -> bool:
    """Portaldan CKAN status_show endpoint-i ilə yoxla."""
    api_url = f"{url.rstrip('/')}/api/3/action/status_show"
    req = urllib.request.Request(api_url, headers={"User-Agent": "data-collector/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            return bool(data.get("success"))
    except Exception as e:
        logger.debug("%s — CKAN deyil: %s", url, e)
        return False


def _http_alive(url: str, timeout: int = 5) -> bool:
    """Basit HTTP HEAD ilə canlılığı yoxla."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400
    except Exception:
        return False


def discover_web_portals(conn) -> dict:
    """Bütün KNOWN_PORTAL-ları scan et, CKAN olanları sources-a yaz.

    Args:
        conn: psycopg2 connection (commit etmir).

    Returns:
        {
            "discovered": int,
            "ckan_found": int,
            "sources_upserted": int,
            "errors": [str, ...],
            "run_id": int,
        }
    """
    run_id = repository.start_collection_run(conn, "discover_web", {})

    discovered = 0
    ckan_found = 0
    sources_upserted = 0
    errors: list[str] = []

    for portal in KNOWN_PORTALS:
        url = portal["url"]
        name = portal["name"]
        discovered += 1

        # 1. HTTP canlılığı yoxla
        if not _http_alive(url):
            logger.info("Portal offline: %s", name)
            continue

        # 2. CKAN yoxlaması
        if not _is_ckan_portal(url):
            logger.info("Portal CKAN deyil: %s", name)
            continue

        ckan_found += 1
        source_id = url.replace("https://", "").replace("http://", "").rstrip("/").replace(".", "_")

        try:
            repository.upsert_source(
                conn,
                id=source_id,
                type="ckan",
                base_url=url,
                discovery_method="web",
                priority_tier=6,
                trust_level="public",
                enabled=True,
                metadata={"name": name, "has_api": True, "api_type": "ckan"},
            )
            sources_upserted += 1
            logger.info("CKAN portal sources-a yazıldı: %s → %s", name, source_id)
        except Exception as e:
            err = f"upsert_source uğursuz ({name}): {e}"
            logger.error(err)
            errors.append(err)

    status = "success" if not errors else "partial"
    repository.finish_collection_run(
        conn, run_id, status, records_collected=sources_upserted,
        error_message="; ".join(errors) if errors else None,
    )

    return {
        "discovered": discovered,
        "ckan_found": ckan_found,
        "sources_upserted": sources_upserted,
        "errors": errors,
        "run_id": run_id,
    }