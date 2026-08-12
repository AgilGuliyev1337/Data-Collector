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
    # Phase 3: Azerbaijan official sources
    {"id": "stat_gov_az", "type": "azstat", "base_url": "https://stat.gov.az",
     "priority_tier": 1, "trust_level": "official",
     "metadata": {"name": "Dövlət Statistika Komitəsi", "has_api": False,
                  "access_method": "web_download"}},
    {"id": "cbar_az", "type": "central_bank_az", "base_url": "https://www.cbar.az",
     "priority_tier": 3, "trust_level": "official",
     "metadata": {"name": "Mərkəzi Bank (Azərbaycan)", "has_api": False,
                  "access_method": "web_download"}},
    {"id": "opendata_az", "type": "ckan", "base_url": "https://admin.opendata.az",
     "priority_tier": 2, "trust_level": "official",
     "metadata": {"name": "Azərbaycan Open Data Portalı", "has_api": True,
                  "api_type": "ckan"}},
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
    """world_bank/eurostat/imf/cbr_russia + Phase 3 Azerbaijan static source-ları.
    Config.yaml-da 'sources:' altında olmayan, kod-daxili tanınan mənbələr.
    FK bütövlüyü üçün lazımdır."""
    for s in STATIC_SOURCES:
        upsert_source(conn, s["id"], s["type"], base_url=s["base_url"],
                      discovery_method="static", priority_tier=s["priority_tier"],
                      trust_level=s["trust_level"],
                      metadata=s.get("metadata"))


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


# ---------------------------------------------------------------------------
# Phase 2B: Concept → Indicator Mapping — Seed Data & Functions
# ---------------------------------------------------------------------------

# Konsept adları (insan üçün göstərilən, sabit)
CONCEPT_DISPLAY_NAMES = {
    "gdp_growth": "GDP Growth Rate",
    "unemployment": "Unemployment Rate",
    "inflation": "Inflation Rate",
    "gdp": "Gross Domestic Product",
    "gdp_per_capita": "GDP Per Capita",
    "population": "Total Population",
    "internet_users": "Internet Users",
    "mobile_subscriptions": "Mobile Subscriptions",
    "exports": "Total Exports",
    "imports": "Total Imports",
    "fdi_inflow": "Foreign Direct Investment Inflow",
    "life_expectancy": "Life Expectancy",
    "co2_emissions": "CO2 Emissions Per Capita",
    "urban_population_pct": "Urban Population Percentage",
    "researchers_per_million": "Researchers Per Million",
    "ease_of_business": "Ease of Doing Business",
}

# Config.yaml → concepts bölməsindəki REAL kodlar.
# Eurostat kodları "yoxla!" qeydi ilə — real sistemdə təsdiq edilməlidir.
CONFIG_YAML_CONCEPTS = {
    "gdp_growth": {
        "world_bank": {"indicator_code": "NY.GDP.MKTP.KD.ZG"},
        "eurostat":   {"indicator_code": "sdg_08_10", "dataset_id": "sdg_08_10"},
    },
    "unemployment": {
        "world_bank": {"indicator_code": "SL.UEM.TOTL.ZS"},
        "eurostat":   {"indicator_code": "une_rt_a", "dataset_id": "une_rt_a"},
    },
    "inflation": {
        "world_bank": {"indicator_code": "FP.CPI.TOTL.ZG"},
        "eurostat":   {"indicator_code": "prc_hicp_manr", "dataset_id": "prc_hicp_manr"},
    },
}

# World Bank COMMON_INDICATORS (WorldBankSource.Common_INDICATORS-dan).
# Bu göstəricilərin hamısı World Bank Open Data API-də REAL mövcuddur.
WB_COMMON_INDICATORS = {
    "gdp":                    {"indicator_code": "NY.GDP.MKTP.CD",
                                "unit": "USD", "frequency": "annual"},
    "gdp_per_capita":         {"indicator_code": "NY.GDP.PCAP.CD",
                                "unit": "USD", "frequency": "annual"},
    "gdp_growth":             {"indicator_code": "NY.GDP.MKTP.KD.ZG",
                                "unit": "percent", "frequency": "annual"},
    "population":             {"indicator_code": "SP.POP.TOTL",
                                "unit": "people", "frequency": "annual"},
    "unemployment":           {"indicator_code": "SL.UEM.TOTL.ZS",
                                "unit": "percent", "frequency": "annual"},
    "inflation":              {"indicator_code": "FP.CPI.TOTL.ZG",
                                "unit": "percent", "frequency": "annual"},
    "internet_users":         {"indicator_code": "IT.NET.USER.ZS",
                                "unit": "percent", "frequency": "annual"},
    "mobile_subscriptions":   {"indicator_code": "IT.CEL.SETS.P2",
                                "unit": "per 100 people", "frequency": "annual"},
    "exports":                {"indicator_code": "NE.EXP.GNFS.CD",
                                "unit": "USD", "frequency": "annual"},
    "imports":                {"indicator_code": "NE.IMP.GNFS.CD",
                                "unit": "USD", "frequency": "annual"},
    "fdi_inflow":             {"indicator_code": "BX.KLT.DINV.CD.WD",
                                "unit": "USD", "frequency": "annual"},
    "life_expectancy":        {"indicator_code": "SP.DYN.LE00.IN",
                                "unit": "years", "frequency": "annual"},
    "co2_emissions":          {"indicator_code": "EN.ATM.CO2E.PC",
                                "unit": "tonnes per capita", "frequency": "annual"},
    "urban_population_pct":   {"indicator_code": "SP.URB.TOTL.IN.ZS",
                                "unit": "percent", "frequency": "annual"},
    "researchers_per_million": {"indicator_code": "SP.POP.SCIE.RD.P6",
                                "unit": "per million people", "frequency": "annual"},
    "ease_of_business":       {"indicator_code": "IC.BUS.EASE.XQ",
                                "unit": "score", "frequency": "annual"},
}


def _catalogue_entry_id(source_id: str, indicator_code: str) -> str:
    """Deterministik entry_id: 'source_id:indicator_code'."""
    return f"{source_id}:{indicator_code}"


def ensure_catalogue_and_mapping(conn):
    """Concepts, catalogue_entries və concept_indicator_map əldə et.

    Mənbə:
    1. Config.yaml-dan 3 konsept → world_bank + eurostat mapping-ləri
    2. World Bank COMMON_INDICATORS-dan 15 konsept → world_bank mapping-ləri
       (config.yaml-dakı 3 konsept WB ilə üst-üstə düşür → idempotent)
    3. Phase 3: Azərbaycan statik source-ları (FK asılılığı üçün)

    İDEMPOTENT: ON CONFLICT DO UPDATE ilə təhlükəsiz təkrar çağırış.
    sources cədvəlinə world_bank/eurostat + AZ statik sətirlərini də yaradır
    (FK asılılığı üçün — mövcuddursa skip).

    Hər addım AYRI cursor-da işlənir: PostgreSQL-də bir INSERT xəta versə belə
    transaction 'aborted' olmur — növbəti addımlar davam edir.
    Commit etmir.
    """
    # Öncə sources cədvəlini doldur (FK asılılığı üçün)
    ensure_static_sources(conn)

    # Addım 1: Concepts
    with conn.cursor() as cur:
        for concept_id, display_name in CONCEPT_DISPLAY_NAMES.items():
            cur.execute(
                """
                INSERT INTO concepts (concept_id, display_name)
                VALUES (%s, %s)
                ON CONFLICT (concept_id) DO UPDATE
                    SET display_name = EXCLUDED.display_name
                """,
                (concept_id, display_name),
            )

    # Addım 2: Catalogue entries (config.yaml WB)
    with conn.cursor() as cur:
        for concept_id, sources in CONFIG_YAML_CONCEPTS.items():
            wb_data = sources.get("world_bank")
            if not wb_data:
                continue
            code = wb_data["indicator_code"]
            entry_id = _catalogue_entry_id("world_bank", code)
            display = CONCEPT_DISPLAY_NAMES.get(concept_id, "")
            cur.execute(
                """
                INSERT INTO catalogue_entries
                    (entry_id, source_id, dataset_id, indicator_code, title,
                     description, unit, frequency)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id, indicator_code) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    unit = EXCLUDED.unit,
                    frequency = EXCLUDED.frequency,
                    updated_at = now()
                """,
                (entry_id, "world_bank", None, code,
                 display, f"World Bank indicator: {code}",
                 WB_COMMON_INDICATORS.get(concept_id, {}).get("unit"),
                 WB_COMMON_INDICATORS.get(concept_id, {}).get("frequency")),
            )

    # Addım 3: Catalogue entries (config.yaml Eurostat)
    with conn.cursor() as cur:
        for concept_id, sources in CONFIG_YAML_CONCEPTS.items():
            es_data = sources.get("eurostat")
            if not es_data:
                continue
            code = es_data["indicator_code"]
            dataset_id = es_data.get("dataset_id", code)
            entry_id = _catalogue_entry_id("eurostat", code)
            display = CONCEPT_DISPLAY_NAMES.get(concept_id, "")
            cur.execute(
                """
                INSERT INTO catalogue_entries
                    (entry_id, source_id, dataset_id, indicator_code, title,
                     description)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id, indicator_code) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    updated_at = now()
                """,
                (entry_id, "eurostat", dataset_id, code,
                 display, f"Eurostat dataset: {code}"),
            )

    # Addım 4: Catalogue entries (WB COMMON_INDICATORS — qalan 12 konsept)
    with conn.cursor() as cur:
        for concept_id, wb_info in WB_COMMON_INDICATORS.items():
            code = wb_info["indicator_code"]
            entry_id = _catalogue_entry_id("world_bank", code)
            display = CONCEPT_DISPLAY_NAMES.get(concept_id, "")
            cur.execute(
                """
                INSERT INTO catalogue_entries
                    (entry_id, source_id, dataset_id, indicator_code, title,
                     description, unit, frequency)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id, indicator_code) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    unit = EXCLUDED.unit,
                    frequency = EXCLUDED.frequency,
                    updated_at = now()
                """,
                (entry_id, "world_bank", None, code,
                 display, f"World Bank indicator: {code}",
                 wb_info.get("unit"), wb_info.get("frequency")),
            )

    # Addım 5: concept_indicator_map (WB COMMON_INDICATORS — 0.90)
    with conn.cursor() as cur:
        for concept_id, wb_info in WB_COMMON_INDICATORS.items():
            code = wb_info["indicator_code"]
            entry_id = _catalogue_entry_id("world_bank", code)
            cur.execute(
                """
                INSERT INTO concept_indicator_map
                    (concept_id, entry_id, confidence, match_type)
                VALUES (%s, %s, %s, 'rule_based')
                ON CONFLICT (concept_id, entry_id) DO UPDATE SET
                    confidence = EXCLUDED.confidence,
                    match_type = EXCLUDED.match_type
                """,
                (concept_id, entry_id, 0.90),
            )

    # Addım 6: concept_indicator_map (config.yaml — 0.95, üst yazır)
    with conn.cursor() as cur:
        for concept_id, sources in CONFIG_YAML_CONCEPTS.items():
            for source_id, src_data in sources.items():
                code = src_data["indicator_code"]
                entry_id = _catalogue_entry_id(source_id, code)
                cur.execute(
                    """
                    INSERT INTO concept_indicator_map
                        (concept_id, entry_id, confidence, match_type)
                    VALUES (%s, %s, %s, 'rule_based')
                    ON CONFLICT (concept_id, entry_id) DO UPDATE SET
                        confidence = EXCLUDED.confidence,
                        match_type = EXCLUDED.match_type
                    """,
                    (concept_id, entry_id, 0.95),
                )


# ---------------------------------------------------------------------------
# Phase 4: Catalogue Discovery Functions
# ---------------------------------------------------------------------------


def upsert_catalogue_entry(conn, entry: dict):
    """Upsert into catalogue_entries. ON CONFLICT (source_id, indicator_code) → UPDATE."""
    country = entry.get("country_coverage")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO catalogue_entries
                (entry_id, source_id, dataset_id, indicator_code, title,
                 description, unit, frequency, country_coverage,
                 time_coverage_start, time_coverage_end, methodology_note)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, indicator_code) DO UPDATE SET
                entry_id = EXCLUDED.entry_id,
                dataset_id = EXCLUDED.dataset_id,
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                unit = EXCLUDED.unit,
                frequency = EXCLUDED.frequency,
                country_coverage = EXCLUDED.country_coverage,
                time_coverage_start = EXCLUDED.time_coverage_start,
                time_coverage_end = EXCLUDED.time_coverage_end,
                methodology_note = EXCLUDED.methodology_note,
                updated_at = now()
            """,
            (
                entry.get("entry_id"),
                entry.get("source_id"),
                entry.get("dataset_id"),
                entry.get("indicator_code"),
                entry.get("title"),
                entry.get("description"),
                entry.get("unit"),
                entry.get("frequency"),
                country if country else None,  # TEXT[]: pass list or NULL
                entry.get("time_coverage_start"),
                entry.get("time_coverage_end"),
                entry.get("methodology_note"),
            ),
        )


def get_catalogue_entries_by_source(conn, source_id) -> list[dict]:
    """SELECT * FROM catalogue_entries WHERE source_id=%s ORDER BY entry_id."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM catalogue_entries WHERE source_id = %s ORDER BY entry_id",
            (source_id,),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_catalogue_entry_by_id(conn, entry_id) -> dict | None:
    """SELECT * FROM catalogue_entries WHERE entry_id=%s."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM catalogue_entries WHERE entry_id = %s",
            (entry_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def get_catalogue_entries_by_indicator(conn, indicator_code) -> list[dict]:
    """SELECT * FROM catalogue_entries WHERE indicator_code=%s ORDER BY entry_id."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM catalogue_entries WHERE indicator_code = %s ORDER BY entry_id",
            (indicator_code,),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def link_concept_to_entry(conn, concept_id, entry_id, confidence, match_type="rule_based"):
    """INSERT INTO concept_indicator_map ON CONFLICT → skip if new confidence < existing.

    ON CONFLICT (concept_id, entry_id) DO UPDATE SET
        confidence and match_type ONLY when EXCLUDED.confidence > existing.
        This prevents downgrades from both confidence and match_type.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO concept_indicator_map
                (concept_id, entry_id, confidence, match_type)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (concept_id, entry_id) DO UPDATE SET
                confidence = CASE WHEN EXCLUDED.confidence > concept_indicator_map.confidence
                                  THEN EXCLUDED.confidence
                                  ELSE concept_indicator_map.confidence END,
                match_type = CASE WHEN EXCLUDED.confidence > concept_indicator_map.confidence
                                  THEN EXCLUDED.match_type
                                  ELSE concept_indicator_map.match_type END
            """,
            (concept_id, entry_id, confidence, match_type),
        )


def seed_auto_concept_mappings(conn) -> int:
    """
    For all catalogue entries without ANY concept mapping,
    attempt heuristic matching against CONCEPT_DISPLAY_NAMES.

    Heuristic: title/description contains display_name (case-insensitive).
    Returns count of new mappings created.
    Confidence = 0.70 (below seeded 0.90/0.95).
    Does NOT overwrite existing mappings.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # 1. Find entries without any mapping
        cur.execute(
            """
            SELECT ce.entry_id, ce.title, ce.description
            FROM catalogue_entries ce
            WHERE ce.entry_id NOT IN (
                SELECT DISTINCT cim.entry_id FROM concept_indicator_map cim
            )
            """
        )
        unmapped = cur.fetchall()

    if not unmapped:
        return 0

    mappings_created = 0

    # 2. For each entry, try to match against concept display names
    for row in unmapped:
        entry_id = row["entry_id"]
        text = ((row.get("title") or "") + " " + (row.get("description") or "")).lower()

        for concept_id, display_name in CONCEPT_DISPLAY_NAMES.items():
            if display_name.lower() in text:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO concept_indicator_map
                            (concept_id, entry_id, confidence, match_type)
                        VALUES (%s, %s, %s, 'manual')
                        ON CONFLICT (concept_id, entry_id) DO NOTHING
                        """,
                        (concept_id, entry_id, 0.70),
                    )
                    if cur.rowcount > 0:
                        mappings_created += 1

    return mappings_created


# ---------------------------------------------------------------------------
# Helper: list_sources — sidebar-da göstərmək üçün
# ---------------------------------------------------------------------------

def list_sources(conn) -> list[dict]:
    """SELECT id, type, base_url, priority_tier, trust_level, enabled FROM sources ORDER BY priority_tier, id."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, type, base_url, priority_tier, trust_level, enabled "
            "FROM sources ORDER BY priority_tier, id"
        )
        return [dict(r) for r in cur.fetchall()]