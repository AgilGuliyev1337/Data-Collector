"""
SourceRegistry funksiyalarının testləri:
  - list_by_tier sıralaması
  - enabled_only filter
  - get_source
  - register_discovered (əlavə etmə)
  - duplicate handling (ON CONFLICT)
  - trust_level / discovery_method dəyərlərinin qorunması
"""

import pytest

import psycopg2.extras

from collector.db import repository

pytestmark = pytest.mark.db


def _source_rows(conn, where="", params=()):
    """sources cədvəlindən sətirlər qaytar (siyahı of dict)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, type, base_url, discovery_method, priority_tier, "
            "trust_level, enabled, metadata FROM sources "
            f"WHERE {where} ORDER BY id",
            params,
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def test_list_by_tier_sorted_by_priority_tier(db_conn):
    """Müxtəlif priority_tier dəyərləri artan sıraya düşməlidir."""
    repository.ensure_static_sources(db_conn)
    repository.upsert_source(db_conn, "test_t1", "ckan", base_url="https://t1.example",
                             priority_tier=1, enabled=True)
    repository.upsert_source(db_conn, "test_t4", "ckan", base_url="https://t4.example",
                             priority_tier=4, enabled=True)
    repository.upsert_source(db_conn, "test_t3", "ckan", base_url="https://t3.example",
                             priority_tier=3, enabled=True)

    from collector.registry import list_by_tier
    result = list_by_tier(db_conn, enabled_only=False)

    tiers = [r["priority_tier"] for r in result]
    assert tiers == sorted(tiers), "Sətirlər priority_tier üzrə artan sırada olmalıdır"
    assert tiers.index(1) < tiers.index(3) < tiers.index(4)


def test_list_by_tier_same_tier_stable_order_by_base_url(db_conn):
    """Eyni tier daxilində base_url üzrə stabil sıralama olmalıdır."""
    repository.upsert_source(db_conn, "s_z", "ckan", base_url="https://z.example",
                             priority_tier=2, enabled=True)
    repository.upsert_source(db_conn, "s_a", "ckan", base_url="https://a.example",
                             priority_tier=2, enabled=True)
    repository.upsert_source(db_conn, "s_m", "ckan", base_url="https://m.example",
                             priority_tier=2, enabled=True)

    from collector.registry import list_by_tier
    result = list_by_tier(db_conn, enabled_only=False)

    tier2 = [r["base_url"] for r in result if r["priority_tier"] == 2]
    assert tier2 == ["https://a.example", "https://m.example", "https://z.example"]


def test_list_by_tier_enabled_only_filters_out_disabled(db_conn):
    """enabled_only=True olduqda disabled source-lar siyahıda olmamalıdır."""
    repository.upsert_source(db_conn, "enabled_src", "ckan", base_url="https://enabled.example",
                             priority_tier=1, enabled=True)
    repository.upsert_source(db_conn, "disabled_src", "ckan", base_url="https://disabled.example",
                             priority_tier=1, enabled=False)

    from collector.registry import list_by_tier
    result_all = list_by_tier(db_conn, enabled_only=False)
    result_enabled = list_by_tier(db_conn, enabled_only=True)

    enabled_ids = {r["id"] for r in result_enabled}
    assert "disabled_src" not in enabled_ids
    assert "enabled_src" in enabled_ids
    assert len(result_enabled) == len(result_all) - 1


def test_get_source_finds_existing_source(db_conn):
    """Mövcud source_id ilə get_source dict qaytarmalıdır."""
    repository.upsert_source(db_conn, "find_me", "ckan", base_url="https://found.example",
                             priority_tier=2, trust_level="official")

    from collector.registry import get_source
    result = get_source(db_conn, "find_me")

    assert result is not None
    assert result["id"] == "find_me"
    assert result["type"] == "ckan"
    assert result["base_url"] == "https://found.example"
    assert result["trust_level"] == "official"


def test_get_source_returns_none_for_missing(db_conn):
    """Yox olan source_id üçün None qaytarmalıdır."""
    from collector.registry import get_source
    result = get_source(db_conn, "no_such_id_12345")
    assert result is None


def test_register_discovered_inserts_source(db_conn):
    """Yeni discovered source sources cədvəlinə əlavə edilməlidir."""
    from collector.registry import register_discovered
    register_discovered(
        db_conn,
        source_id="discovered_new",
        source_type="web_crawler",
        base_url="https://discovered.example",
        priority_tier=5,
        trust_level="unverified_web",
    )

    row = _source_rows(db_conn, "id = %s", ("discovered_new",))
    assert len(row) == 1
    src = row[0]
    assert src["id"] == "discovered_new"
    assert src["discovery_method"] == "discovered"
    assert src["type"] == "web_crawler"
    assert src["priority_tier"] == 5
    assert src["trust_level"] == "unverified_web"
    assert src["enabled"] is True


def test_register_discovered_trust_level_defaults_to_unverified(db_conn):
    """trust_level göstərilmədikdə default 'unverified_web' olmalıdır."""
    from collector.registry import register_discovered
    register_discovered(
        db_conn,
        source_id="default_trust",
        source_type="web_crawler",
        base_url="https://default.example",
    )

    row = _source_rows(db_conn, "id = %s", ("default_trust",))
    assert row[0]["trust_level"] == "unverified_web"


def test_register_discovered_duplicate_is_safe(db_conn):
    """Duplicate source_id üçün cəsur override edilmir — updated_at yenilənir."""
    from collector.registry import register_discovered

    # İlk register
    register_discovered(
        db_conn,
        source_id="dup_test",
        source_type="web_crawler",
        base_url="https://first.example",
        priority_tier=5,
        trust_level="unverified_web",
    )

    # Duplicate register — fərqli parametrlərlə
    register_discovered(
        db_conn,
        source_id="dup_test",
        source_type="different_type",
        base_url="https://second.example",
        priority_tier=3,
        trust_level="official",
    )

    row = _source_rows(db_conn, "id = %s", ("dup_test",))
    assert len(row) == 1
    # Birinci dəyərlər qorunmalıdır (ON CONFLICT DO UPDATE SET updated_at only)
    assert row[0]["type"] == "web_crawler"
    assert row[0]["base_url"] == "https://first.example"
    assert row[0]["priority_tier"] == 5
    assert row[0]["trust_level"] == "unverified_web"


def test_register_discovered_preserves_custom_fields(db_conn):
    """Fərqli priority_tier və trust_level dəyərləri dəqiqliklə saxlanmalıdır."""
    from collector.registry import register_discovered
    register_discovered(
        db_conn,
        source_id="custom_fields",
        source_type="api_endpoint",
        base_url="https://custom.example",
        priority_tier=2,
        trust_level="aggregated",
        metadata={"region": "eu", "notes": "xüsusi mənbə"},
    )

    row = _source_rows(db_conn, "id = %s", ("custom_fields",))
    assert row[0]["priority_tier"] == 2
    assert row[0]["trust_level"] == "aggregated"
    assert row[0]["discovery_method"] == "discovered"


def test_register_discovered_not_in_list_by_tier_when_disabled(db_conn):
    """disabled discovered source enabled_only=True olduqda görünmür."""
    from collector.registry import register_discovered, list_by_tier
    register_discovered(
        db_conn,
        source_id="hidden_discovered",
        source_type="web_crawler",
        base_url="https://hidden.example",
        priority_tier=1,
        trust_level="unverified_web",
    )

    # default enabled=True ilə yazılıb
    all_sources = list_by_tier(db_conn, enabled_only=False)
    assert any(r["id"] == "hidden_discovered" for r in all_sources)

    # disabled edirik
    with db_conn.cursor() as cur:
        cur.execute("UPDATE sources SET enabled = false WHERE id = %s", ("hidden_discovered",))

    enabled_sources = list_by_tier(db_conn, enabled_only=True)
    assert not any(r["id"] == "hidden_discovered" for r in enabled_sources)


def test_list_by_tier_returns_nothing_when_empty(db_conn):
    """Sources cədvəli boşdursa boş siyahı qaytarmalıdır."""
    from collector.registry import list_by_tier
    result = list_by_tier(db_conn, enabled_only=False)
    assert result == []