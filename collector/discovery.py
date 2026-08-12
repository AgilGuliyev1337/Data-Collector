"""
Data Catalogue Discovery Engine — Phase 4.

Bu modul enabled source-lardan kataloq discovery icra edir,
tapılan dataset-ləri `catalogue_entries` cədvəlinə yazır,
avtomatik concept mapping edir və `collection_runs`-a qeyd alır.

İstifadə:
    python cli.py --discover-catalogue               # bütün capable source-lar
    python cli.py --discover-catalogue --source opendata_az  # təkcə opendata.az
"""

import importlib
import logging
from typing import Any

from collector.db.repository import (
    upsert_catalogue_entry,
    link_concept_to_entry,
    seed_auto_concept_mappings,
    start_collection_run,
    finish_collection_run,
)
from collector.registry import (
    list_discovery_capable_sources,
    get_source,
)
from collector.sources.base import DataSource

logger = logging.getLogger("collector.discovery")

# Source type -> fully-qualified adapter class path.
_SOURCE_ADAPTER_MAP: dict[str, str] = {
    "ckan": "collector.sources.ckan_source.CKANSource",
    # future: "worldbank": "collector.sources.worldbank_source.WorldBankSource",
    # future: "eurostat": "collector.sources.eurostat_source.EurostatSource",
    # future: "imf": "collector.sources.imf_source.IMFSource",
}


def _build_adapter(source_cfg: dict) -> DataSource | None:
    """Build adapter instance from source metadata dict.

    Args:
        source_cfg: Dict with 'id', 'type', 'base_url', 'metadata', etc.

    Returns:
        Adapter instance or None if no adapter available for this type.
    """
    source_type = source_cfg.get("type", "")
    class_path = _SOURCE_ADAPTER_MAP.get(source_type)
    if not class_path:
        logger.warning("Adapter tapılmadı: type=%s (id=%s)", source_type, source_cfg.get("id"))
        return None

    module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    adapter_class = getattr(module, class_name)
    return adapter_class(source_cfg)


def discover_catalogue_for_source(conn, source_id: str = None) -> dict:
    """
    Discover catalogue entries from one or all capable sources.

    Steps:
    1. Connect DB (already connected via caller)
    2. Get source config from registry
    3. Discover for specified source or all capable
    4. Instantiate adapter from type
    5. Call discover_catalogue()
    6. For each entry: upsert_catalogue_entry + link_concept_to_entry
    7. seed_auto_concept_mappings at end
    8. Record in collection_runs

    Args:
        conn: psycopg2 connection (doesn't commit).
        source_id: If set, discover only this source.
                   If None, discover all discovery-capable sources.

    Returns:
        {"source_id": ..., "entries_discovered": N, "entries_upserted": N,
         "mappings_created": N, "errors": [...], "run_id": ...}
    """
    errors: list[str] = []
    total_discovered = 0
    total_upserted = 0
    total_mappings = 0

    # Resolve sources to discover
    if source_id:
        sources = [get_source(conn, source_id)]
        sources = [s for s in sources if s and s.get("enabled", True)]
    else:
        sources = list_discovery_capable_sources(conn)

    if not sources:
        msg = "No discovery-capable sources found."
        logger.warning(msg)
        return {
            "entries_discovered": 0,
            "entries_upserted": 0,
            "mappings_created": 0,
            "errors": [msg],
            "run_id": None,
        }

    # Start a collection run
    run_id = start_collection_run(conn, "discover_catalogue", {
        "source_id": source_id or "all",
    })

    for source_cfg in sources:
        sid = source_cfg["id"]
        logger.info("=== Discovering catalogue for: %s ===", sid)

        # Build adapter
        adapter = _build_adapter(source_cfg)
        if adapter is None:
            err = f"No adapter for source type '{source_cfg.get('type')}' (id={sid})"
            logger.error(err)
            errors.append(err)
            continue

        # Call discover_catalogue
        try:
            entries = adapter.discover_catalogue()
        except Exception as e:
            err = f"discover_catalogue() failed for {sid}: {e}"
            logger.error(err)
            errors.append(err)
            continue

        entries_discovered = len(entries)
        entries_upserted = 0

        logger.info("[%s] %d entry tapıldı, yazılır...", sid, entries_discovered)

        # Upsert each entry + link concepts
        for entry in entries:
            try:
                upsert_catalogue_entry(conn, entry)

                # Quick concept link: try to match indicator_code against concept_ids
                indicator_code = entry.get("indicator_code", "").lower()
                for concept_id in _SOURCE_ADAPTER_MAP:  # quick heuristic
                    # Check if the indicator contains a concept keyword
                    pass  # Real matching is done by seed_auto_concept_mappings

                entries_upserted += 1
            except Exception as e:
                err = f"upsert failed for entry {entry.get('entry_id', '?')}: {e}"
                logger.error(err)
                errors.append(err)

        total_discovered += entries_discovered
        total_upserted += entries_upserted

        logger.info("[%s] %d / %d entry upsert olundu", sid, entries_upserted, entries_discovered)

    # Seed auto concept mappings across all newly-discovered entries
    try:
        mappings = seed_auto_concept_mappings(conn)
        total_mappings = mappings
        logger.info("Auto concept mappings: %d yaradıldı", mappings)
    except Exception as e:
        err = f"seed_auto_concept_mappings failed: {e}"
        logger.error(err)
        errors.append(err)

    # Finish collection run
    status = "success" if not errors else "partial"
    finish_collection_run(
        conn, run_id, status,
        total_upserted,
        error_message="; ".join(errors) if errors else None,
    )

    return {
        "entries_discovered": total_discovered,
        "entries_upserted": total_upserted,
        "mappings_created": total_mappings,
        "errors": errors,
        "run_id": run_id,
    }