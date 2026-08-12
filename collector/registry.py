"""
SourceRegistry — `sources` cədvəlini idarə edən nazik qat.

Məqsəd:
- `priority_tier` üzrə sıralı source siyahısı (Phase 2A fallback runner üçün əsas).
- Tekil source sorgusu.
- `discovered` mənbələrin təhlükəsiz şəkildə əlavə edilməsi
  (web discovery üçün: avtomatik `official` trust_level qəbuledilmir).

Yeni Cədvəl / Migration: YOX. Mövcud `sources` sxemindən istifadə edir.
Commit məsuliyyəti: Çağıranda aiddir — bu funksiyalar `conn.commit()` ÇAĞIRMIIR.
"""

import psycopg2.extras


def list_by_tier(conn, enabled_only=True):
    """Bütün source-ları `priority_tier` üzrə artan sırada qaytar.

    Eyni tier daxilində `base_url` üzrə stabil sıralama (ASCII).
    Sıralama: priority_tier ASC → base_url ASC (NULL-son).

    Args:
        conn: psycopg2 connection (commit etmir).
        enabled_only: Yalnız `enabled=True` olan source-ları qaytarsın.

    Returns:
        Siyahı: [{id, type, base_url, discovery_method, priority_tier,
                 trust_level, enabled, metadata, created_at, updated_at}, ...]
        Hər dict PostgreSQL sətirinin dict-üslubunda açarları ilə.
    """
    query = """
        SELECT id, type, base_url, discovery_method, priority_tier, trust_level,
               enabled, metadata, created_at, updated_at
        FROM sources
        WHERE %s = FALSE OR enabled = %s
        ORDER BY priority_tier ASC NULLS LAST, base_url ASC NULLS LAST
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, (enabled_only, True))
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def get_source(conn, source_id):
    """Bir source-u `id` üzrə qaytar.

    Args:
        conn: psycopg2 connection (commit etmir).
        source_id: source-un `id` sahəsi.

    Returns:
        Dict — və ya `None` (tapılmadıqda).
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, type, base_url, discovery_method, priority_tier, trust_level,
                   enabled, metadata, created_at, updated_at
            FROM sources
            WHERE id = %s
            """,
            (source_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def register_discovered(conn, source_id, source_type, base_url,
                        priority_tier=6, trust_level="unverified_web",
                        metadata=None):
    """Yeni mənbəni `sources` cədvəlinə əlavə et (discovered).

    Təhlükəsizlik:
    - `trust_level` avtomatik `official` qəbul edilmir —
      default `unverified_web`. Çağırıcı yüksək trust istəyirsə
      onu **əks etdirmədən** özü ödəməlidir.
    - duplicate source (CONFLICT) — `updated_at` yenilənir,
      digər sahələr dəyişmir (cəsur override yoxdur).

    Args:
        conn: psycopg2 connection (commit etmir).
        source_id: source-un unikal `id`-i.
        source_type: source növü (məs. "web_crawler", "api_endpoint").
        base_url: source-un əsas URL-i.
        priority_tier: prioritet dərəcəsi (1-6, default 6 — web discovery).
        trust_level: etibarlılıq səviyyəsi. **Default `unverified_web`.**
            Tələb olunan: hər kəsim `official`-a qalxa bilməz,
            yalnız kataloq administratoru təsdiqləyə bilər.
        metadata: əlavə JSONB məlumat (default {}).

    Returns:
        None.

    Raises:
        psycopg2.errors.CheckViolation: trust_level sxem CHECK-ə uyğun deyilsə.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sources
                (id, type, base_url, discovery_method, priority_tier,
                 trust_level, enabled, metadata, created_at, updated_at)
            VALUES (%s, %s, %s, 'discovered', %s, %s, %s, %s, now(), now())
            ON CONFLICT (id) DO UPDATE SET
                updated_at = now()
            """,
            (
                source_id,
                source_type,
                base_url,
                priority_tier,
                trust_level,
                True,
                psycopg2.extras.Json(metadata or {}),
            ),
        )


def list_concepts(conn):
    """Bütün konseptləri qaytar.

    Args:
        conn: psycopg2 connection (commit etmir).

    Returns:
        Siyahı: [{concept_id, display_name}, ...] — concept_id üzrə sıralı.
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT concept_id, display_name FROM concepts ORDER BY concept_id"
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def get_candidate_indicators(conn, concept_id):
    """Verilmiş konseptin BÜTÜN candidate indicator-lərini qaytar.

    Sıralama:
    1. source `priority_tier` ASC (daha yüksək prioritet əvvəldə)
    2. `confidence` DESC (daha etibarlı mapping əvvəldə)
    3. `entry_id` — stabil tie-breaker

    Nəticə:
    [{entry_id, source_id, indicator_code, dataset_id, title,
      confidence, match_type, priority_tier, trust_level, unit,
      frequency, country_coverage, time_coverage_start, time_coverage_end}, ...]

    Args:
        conn: psycopg2 connection (commit etmir).
        concept_id: konseptin `concept_id` sahəsi.

    Returns:
        Siyahı (boş ola bilər — mapping yoxdursa).
    """
    query = """
        SELECT
            ce.entry_id, ce.source_id, ce.indicator_code, ce.dataset_id,
            ce.title, ce.description, ce.unit, ce.frequency,
            ce.country_coverage, ce.time_coverage_start, ce.time_coverage_end,
            cim.confidence, cim.match_type,
            s.priority_tier, s.trust_level
        FROM catalogue_entries ce
        JOIN concept_indicator_map cim ON cim.entry_id = ce.entry_id
        JOIN sources s ON s.id = ce.source_id
        WHERE cim.concept_id = %s
        ORDER BY s.priority_tier ASC NULLS LAST,
                 cim.confidence DESC,
                 ce.entry_id ASC
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, (concept_id,))
        rows = cur.fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------
# Phase 3: Azerbaijan Static Sources Seed
# ---------------------------------------------------------------

# StatKom (Dövlət Statistika Komitəsi) — real source, amma public API yoxdur.
# Məlumat yalnız Excel/CSV download və ya data request ilə əldə edilir.
# Bu entry gələcəkdə web extraction üçün əlavə olunub.
AZERBAIJAN_SOURCES = {
    "stat_gov_az": {
        "type": "azstat",
        "base_url": "https://stat.gov.az",
        "priority_tier": 1,
        "trust_level": "official",
        "metadata": {
            "name": "Dövlət Statistika Komitəsi",
            "has_api": False,
            "access_method": "web_download",
            "description": "Statistical data available via web download (Excel/CSV). No public REST API.",
        },
    },
    "cbar_az": {
        "type": "central_bank_az",
        "base_url": "https://www.cbar.az",
        "priority_tier": 3,
        "trust_level": "official",
        "metadata": {
            "name": "Mərkəzi Bank (Azərbaycan)",
            "has_api": False,
            "access_method": "web_download",
            "description": "Economic statistics available as PDF/Excel files. Open Banking API exists but is for financial institutions, not public stats.",
        },
    },
    "opendata_az": {
        "type": "ckan",
        "base_url": "https://admin.opendata.az",
        "priority_tier": 2,
        "trust_level": "official",
        "metadata": {
            "name": "Azərbaycan Open Data Portalı",
            "has_api": True,
            "api_type": "ckan",
            "dataset_count": 728,
            "contributor_count": 25,
            "description": "Official state open data platform. CKAN-based API available. 246 datasets from State Statistics Committee.",
        },
    },
}


def ensure_azerbaijan_sources(conn):
    """Azərbaycana aid static source-ları `sources` cədvəlinə əlavə et.

    Hər source idempotent şəkildə əlavə olunur (ON CONFLICT skip).
    Commit etmir.
    """
    from collector.db.repository import upsert_source
    for source_id, source_cfg in AZERBAIJAN_SOURCES.items():
        upsert_source(
            conn,
            id=source_id,
            type=source_cfg["type"],
            base_url=source_cfg.get("base_url", ""),
            priority_tier=source_cfg.get("priority_tier"),
            trust_level=source_cfg.get("trust_level", "unverified_web"),
            enabled=source_cfg.get("enabled", True),
            metadata=source_cfg.get("metadata", {}),
        )