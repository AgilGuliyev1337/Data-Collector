"""
Bütün raw SQL bu modulda cəmlənib — tətbiqin qalan hissəsi (cli.py,
adapter-lər) birbaşa SQL yazmır, yalnız bu funksiyaları çağırır.
"""

import json
import re

import psycopg2.extras

# priority_tier: 1=AZ rəsmi dövlət, 2=AZ Open Data, 3=digər milli statistika,
# 4=beynəlxalq təşkilatlar, 5=digər public API, 6=web discovery.
STATIC_SOURCES = [
    {"id": "world_bank", "type": "worldbank", "base_url": "https://api.worldbank.org/v2",
     "priority_tier": 4, "trust_level": "official"},
    {"id": "eurostat", "type": "eurostat", "base_url": "https://ec.europa.eu/eurostat/api",
     "priority_tier": 4, "trust_level": "official"},
    {"id": "imf", "type": "imf", "base_url": "http://dataservices.imf.org/REST/SDMX_JSON.svc",
     "priority_tier": 4, "trust_level": "official"},
    {"id": "cbr_russia", "type": "cbr", "base_url": "https://www.cbr-xml-daily.ru",
     "priority_tier": 3, "trust_level": "official"},
]


def _period_year(period) -> int:
    if period is None:
        return None
    match = re.match(r"^(\d{4})", str(period))
    return int(match.group(1)) if match else None


def upsert_source(conn, id, type, base_url=None, discovery_method="static",
                   priority_tier=None, trust_level="official", enabled=True, metadata=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sources (id, type, base_url, discovery_method, priority_tier, trust_level, enabled, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                type = EXCLUDED.type,
                base_url = EXCLUDED.base_url,
                enabled = EXCLUDED.enabled,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            """,
            (id, type, base_url, discovery_method, priority_tier, trust_level, enabled,
             psycopg2.extras.Json(metadata or {})),
        )


def ensure_static_sources(conn):
    """world_bank/eurostat/imf/cbr_russia - config.yaml-da 'sources:' altında
    olmayan, kod-daxili tanınan 4 makro mənbə. FK bütövlüyü üçün lazımdır."""
    for s in STATIC_SOURCES:
        upsert_source(conn, s["id"], s["type"], base_url=s["base_url"],
                      discovery_method="static", priority_tier=s["priority_tier"],
                      trust_level=s["trust_level"])


def upsert_dataset(conn, record: dict):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO datasets
                (source_id, dataset_id, name, title, org, license, license_id,
                 modified, tags, groups_, resources)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, dataset_id) DO UPDATE SET
                title = EXCLUDED.title,
                modified = EXCLUDED.modified,
                resources = EXCLUDED.resources,
                collected_at = now()
            """,
            (
                record["source_id"], record["dataset_id"], record.get("name"),
                record.get("title"), record.get("org"), record.get("license"),
                record.get("license_id"), record.get("modified"),
                psycopg2.extras.Json(record.get("tags") or []),
                psycopg2.extras.Json(record.get("groups") or []),
                psycopg2.extras.Json(record.get("resources") or []),
            ),
        )


def start_collection_run(conn, command: str, params: dict) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO collection_runs (command, params) VALUES (%s, %s) RETURNING id",
            (command, psycopg2.extras.Json(params or {})),
        )
        run_id = cur.fetchone()[0]
    return run_id


def finish_collection_run(conn, run_id: int, status: str, records_collected: int, error_message: str = None):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE collection_runs
            SET status = %s, records_collected = %s, error_message = %s, finished_at = now()
            WHERE id = %s
            """,
            (status, records_collected, error_message, run_id),
        )


def insert_facts(conn, rows: list):
    """rows: [{source_id, run_id, concept, indicator_code, country, iso3, period, value, unit}, ...]
    Append-only - eyni (concept, country, period) üçün yeni sətir tarixçə kimi əlavə olunur."""
    if not rows:
        return
    values = [
        (
            r["source_id"], r.get("run_id"), r["concept"], r.get("indicator_code"),
            r.get("country"), r.get("iso3"), r.get("period"), _period_year(r.get("period")),
            r.get("value"), r.get("unit"),
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO facts (source_id, run_id, concept, indicator_code, country, iso3, period, period_year, value, unit)
            VALUES %s
            """,
            values,
        )


def upsert_fx_rates(conn, rows: list):
    """rows: [{source_id, run_id, currency_code, currency_name, nominal, value_rub, rate_date}, ...]
    (currency_code, rate_date) üzrə upsert - günün snapshot-u revisə olunmur, üzərinə yazılır."""
    if not rows:
        return
    values = [
        (
            r["source_id"], r.get("run_id"), r["currency_code"], r.get("currency_name"),
            r.get("nominal"), r["value_rub"], r["rate_date"],
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO fx_rates (source_id, run_id, currency_code, currency_name, nominal, value_rub, rate_date)
            VALUES %s
            ON CONFLICT (currency_code, rate_date) DO UPDATE SET
                value_rub = EXCLUDED.value_rub,
                nominal = EXCLUDED.nominal,
                run_id = EXCLUDED.run_id,
                collected_at = now()
            """,
            values,
        )
