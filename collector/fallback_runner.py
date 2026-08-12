"""
Deterministic Fallback Runner — Phase 2C.

Concept üçün candidate indicator-ləri prioritet sırala ilə yoxlayır.
İlk uğurlu cavabda dayanır.

Flow:
  concept_id
    → get_candidate_indicators() → sıralı siyahı
    → hər candidate üçün:
        - source uyğunluğu (priority_tier, trust_level)
        - adapter → fetch(data)
        - data varsa → success
        - data yoxdursa → növbəti candidate
    → hamısı bitdi → failure

Audit:
  Hər addım collection_runs-ə yazılır
  (niyə növbətiyə keçdiyi qeydi ilə).

Adapter dispatch:
  source_id → adapter sinifinin instansiyası → fetch()
  Hər adapterin fetch() fərqli **kwargs imzası var.
  Bu modul hər source üçün uyğun kwargs-ı catalogue_entry-dən çıxarır.

Commit prinsip: conn.commit() ÇaĞIRMIIR.
"""

import logging
from datetime import datetime

from collector.registry import get_candidate_indicators, get_source
from collector.sources.worldbank_source import WorldBankSource
from collector.sources.eurostat_source import EurostatSource
from collector.sources.imf_source import IMFSource
from collector.sources.cbr_source import CBRSource
from collector.db import repository

logger = logging.getLogger("collector.fallback")

# source_id → (adapter_class, kwargs_transform_func)
# Kwargs transform: (catalogue_entry, params) → adapter.fetch(**kwargs)
ADAPTER_DISPATCH = {
    "world_bank": (WorldBankSource, lambda entry, params: {
        "country_codes": params["countries"],
        "indicator": entry["indicator_code"],
        "start_year": params["period_start"],
        "end_year": params["period_end"],
    }),
    "eurostat": (EurostatSource, lambda entry, params: {
        "dataset": entry.get("dataset_id", entry["indicator_code"]),
        "geo_codes": params["countries"],
        "start_year": params["period_start"],
        "end_year": params["period_end"],
    }),
    "imf": (IMFSource, lambda entry, params: {
        "dataset": entry.get("dataset_id", "IFS"),
        "key": entry.get("indicator_code", "A.{country}.NGDP_R_XDC"),
        "start_year": params["period_start"],
        "end_year": params["period_end"],
    }),
    "cbr_russia": (CBRSource, lambda entry, params: {}),
    # CKAN və digərləri: əlavə ediləcək
}


def run_fallback(conn, concept_id, countries, period_start, period_end):
    """Concept üçün fallback runner-ı icra et.

    Candidate indicator-ləri (priority_tier ASC, confidence DESC)
    ardıcıllıqla yoxlayır. İlk uğurlu cavabda dayanır.

    Args:
        conn: psycopg2 connection (commit etmir).
        concept_id: konsept ID.
        countries: ISO3 ölkə kodları siyahısı.
        period_start: başlanğıc il.
        period_end: bitiş il.

    Returns:
        {
            "success": bool,
            "records": list,        # uğurlu fetch-dən gələn data
            "attempts": [           # hər cəhdin auditi
                {
                    "source_id": str,
                    "indicator_code": str,
                    "confidence": float,
                    "priority_tier": int,
                    "status": "success" | "empty" | "error",
                    "error_message": str | None,
                    "records_count": int,
                },
                ...
            ],
            "selected_source": str | None,   # uğurlu olan source (yoxdursa None)
            "selected_indicator": str | None,
        }
    """
    candidates = get_candidate_indicators(conn, concept_id)

    if not candidates:
        logger.warning("Concept '%s' üçün heç bir candidate indicator tapılmadı.", concept_id)
        return {
            "success": False,
            "records": [],
            "attempts": [],
            "selected_source": None,
            "selected_indicator": None,
            "reason": "no_candidates",
        }

    # collection_run yarad (audit əsası)
    run_id = repository.start_collection_run(
        conn,
        "fallback_runner",
        {"concept_id": concept_id, "countries": countries,
         "period_start": period_start, "period_end": period_end},
    )

    attempts = []
    last_error = None

    for i, candidate in enumerate(candidates):
        source_id = candidate["source_id"]
        indicator_code = candidate["indicator_code"]
        confidence = candidate["confidence"]
        priority_tier = candidate["priority_tier"]
        trust_level = candidate["trust_level"]

        attempt = {
            "source_id": source_id,
            "indicator_code": indicator_code,
            "confidence": confidence,
            "priority_tier": priority_tier,
            "status": None,
            "error_message": None,
            "records_count": 0,
        }

        # Source enabled/mövjud yoxlanışı
        source_info = get_source(conn, source_id)
        if source_info is None:
            attempt["status"] = "skipped"
            attempt["error_message"] = f"Source '{source_id}' sources cədvəlində tapılmadı"
            attempts.append(attempt)
            logger.warning("Source '%s' tapılmadı — keçilir.", source_id)
            continue

        if not source_info.get("enabled", True):
            attempt["status"] = "skipped"
            attempt["error_message"] = f"Source '{source_id}' disabled"
            attempts.append(attempt)
            logger.warning("Source '%s' disabled — keçilir.", source_id)
            continue

        # Adapter tap
        dispatch = ADAPTER_DISPATCH.get(source_id)
        if dispatch is None:
            attempt["status"] = "skipped"
            attempt["error_message"] = f"Adapter '{source_id}' üçün mapper tapılmadı"
            attempts.append(attempt)
            logger.warning("Source '%s' üçün adapter mapper yoxdur — keçilir.", source_id)
            continue

        adapter_class, kwargs_fn = dispatch

        # Adapter instansiyala
        try:
            # source config-dən öyrənməyə çalış (başqa yerdən yoxdursa default)
            source_cfg = source_info.get("metadata", {})
            adapter = adapter_class(source_cfg if source_cfg else None)
        except Exception as e:
            attempt["status"] = "error"
            attempt["error_message"] = f"Adapter instansiasiya xətası: {e}"
            attempts.append(attempt)
            logger.error("Source '%s' adapter yaradılarkən xəta: %s", source_id, e)
            continue

        # Kwargs hazırla
        try:
            kwargs = kwargs_fn(candidate, {
                "countries": countries,
                "period_start": period_start,
                "period_end": period_end,
            })
        except Exception as e:
            attempt["status"] = "error"
            attempt["error_message"] = f"Kwargs transform xətası: {e}"
            attempts.append(attempt)
            logger.error("Source '%s' kwargs transform xətası: %s", source_id, e)
            continue

        # Fetch
        try:
            result = adapter.fetch(**kwargs)
            records_count = len(result) if result else 0

            if records_count > 0:
                attempt["status"] = "success"
                attempt["records_count"] = records_count
                attempts.append(attempt)

                # Uğur: facts-a yaz
                normalized = _normalize_result(result, source_id, run_id, concept_id, indicator_code)
                repository.insert_facts(conn, normalized)
                repository.finish_collection_run(conn, run_id, "success", records_count)

                logger.info(
                    "Concept '%s' → source '%s' uğurlu (%d sətir)",
                    concept_id, source_id, records_count,
                )
                return {
                    "success": True,
                    "records": result,
                    "attempts": attempts,
                    "selected_source": source_id,
                    "selected_indicator": indicator_code,
                    "run_id": run_id,
                }
            else:
                attempt["status"] = "empty"
                attempt["error_message"] = "Data boş qaytdı"
                attempts.append(attempt)
                logger.info(
                    "Concept '%s' → source '%s' boş cavab, növbətiyə keçir.",
                    concept_id, source_id,
                )

        except Exception as e:
            attempt["status"] = "error"
            attempt["error_message"] = str(e)
            attempts.append(attempt)
            last_error = str(e)
            logger.warning(
                "Concept '%s' → source '%s' xəta: %s",
                concept_id, source_id, e,
            )

    # Bütün candidate-lər bitdi — uğursuz
    repository.finish_collection_run(
        conn, run_id, "failed", 0,
        error_message=f"Hamısı uğursuz: {last_error}",
    )

    logger.warning(
        "Concept '%s' — bütün candidate-lər uğursuz.", concept_id,
    )
    return {
        "success": False,
        "records": [],
        "attempts": attempts,
        "selected_source": None,
        "selected_indicator": None,
        "run_id": run_id,
        "reason": "all_candidates_failed",
    }


def _normalize_result(raw_rows, source_id, run_id, concept_id, indicator_code):
    """Adapter-dən gələn raw data-ya facts formatında sətirlər yarat.

    Hər adapterin output formatı fərqlidir — uyğunlaşdırma:
    - WorldBank: {country, iso3, year, value, indicator}
    - Eurostat: {country, iso3, year, value, source}
    - IMF: {iso3, year, value, indicator}

    Args:
        raw_rows: adapter.fetch()-dan gələn siyahı.
        source_id: mənbə ID.
        run_id: collection_run ID (provenance üçün).
        concept_id: konsept ID.
        indicator_code: konkret indikator kodu.

    Returns:
        insert_facts() formatında [{source_id, run_id, concept, ...}, ...]
    """
    rows = []
    for r in raw_rows:
        rows.append({
            "source_id": source_id,
            "run_id": run_id,
            "concept": concept_id,
            "indicator_code": indicator_code,
            "country": r.get("country") or r.get("iso3"),
            "iso3": r.get("iso3") or r.get("country"),
            "period": str(r.get("year") or r.get("period")),
            "value": r.get("value"),
            "unit": r.get("unit"),
        })
    return rows