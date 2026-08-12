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