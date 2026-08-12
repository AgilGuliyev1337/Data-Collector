"""
Phase 2B: Concept → Candidate Indicator Mapping testləri.

Yoxlanılır:
  - Migration (0002) cədvəlləri yaradır
  - Seed → concepts, catalogue_entries, concept_indicator_map
  - İdempotent seed (təkrar çağırış yeni sətir yaratmır)
  - list_concepts() funksiyası
  - get_candidate_indicators() sıralama
  - naməlum konsept → boş nəticə
  - cbr_russia mapping-lərinə qarışmır
"""

import pytest

from collector.db import repository

pytestmark = pytest.mark.db


def _count(conn, table, where="", params=()):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} {where}", params)
        return cur.fetchone()[0]


def test_migration_creates_all_tables(db_conn):
    """0002 migration üç yeni cədvəl yaradır: concepts, catalogue_entries, concept_indicator_map."""
    for table in ("concepts", "catalogue_entries", "concept_indicator_map"):
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables "
                "WHERE table_name = %s)",
                (table,),
            )
            assert cur.fetchone()[0], f"Cədvəl '{table}' mövcud olmalıdır"


def test_seed_creates_concepts(db_conn):
    """Seed bütün konseptləri yaradır — config.yaml və WB COMMON_INDICATORS."""
    repository.ensure_catalogue_and_mapping(db_conn)

    # 16 unique concept: 15 WB COMMON_INDICATORS + ease_of_business (WB-də yoxdur)
    assert _count(db_conn, "concepts") >= 15
    with db_conn.cursor() as cur:
        cur.execute("SELECT concept_id FROM concepts ORDER BY concept_id")
        ids = [r[0] for r in cur.fetchall()]
    # Config.yaml konseptləri
    assert "gdp_growth" in ids
    assert "unemployment" in ids
    assert "inflation" in ids
    # WB-only konseptlər
    assert "gdp_per_capita" in ids
    assert "population" in ids
    assert "internet_users" in ids
    assert "ease_of_business" in ids


def test_seed_creates_catalogue_entries(db_conn):
    """Seed yalnız world_bank və eurostat üçün catalogue_entries yaradır."""
    repository.ensure_catalogue_and_mapping(db_conn)

    total = _count(db_conn, "catalogue_entries")
    # Minimum: 15 WB unique codes + 3 Eurostat unique codes = 18
    assert total >= 18, f"Bəzi catalogue entries itirilib (got {total})"

    # Sadece world_bank və eurostat, cbr_russia YOX
    with db_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source_id FROM catalogue_entries ORDER BY source_id")
        sources = [r[0] for r in cur.fetchall()]
    assert sources == ["eurostat", "world_bank"]
    assert "cbr_russia" not in sources


def test_seed_creates_mappings(db_conn):
    """Seed hər entry üçün bir mapping yaradır — PK pozulmur."""
    repository.ensure_catalogue_and_mapping(db_conn)

    mappings = _count(db_conn, "concept_indicator_map")
    assert mappings >= 15, "Bəzi mapping-lər itirilib"

    # Hər mapping üçün uyğun entry mövcuddur
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM concept_indicator_map m
            JOIN catalogue_entries e ON e.entry_id = m.entry_id
            JOIN concepts c ON c.concept_id = m.concept_id
            """
        )
        assert cur.fetchone()[0] == mappings


def test_seed_is_idempotent(db_conn):
    """Təkrar seed çağırışı yeni sətir yaratmır (count dəyişmir)."""
    repository.ensure_catalogue_and_mapping(db_conn)
    before_concepts = _count(db_conn, "concepts")
    before_entries = _count(db_conn, "catalogue_entries")
    before_mappings = _count(db_conn, "concept_indicator_map")

    repository.ensure_catalogue_and_mapping(db_conn)

    assert _count(db_conn, "concepts") == before_concepts
    assert _count(db_conn, "catalogue_entries") == before_entries
    assert _count(db_conn, "concept_indicator_map") == before_mappings


def test_list_concepts_returns_all(db_conn):
    """list_concepts() bütün konseptləri qaytarmalıdır."""
    repository.ensure_catalogue_and_mapping(db_conn)

    from collector.registry import list_concepts
    result = list_concepts(db_conn)

    assert len(result) >= 15
    ids = [r["concept_id"] for r in result]
    assert ids == sorted(ids), "Nəticə concept_id üzrə sıralı olmalıdır"


def test_list_concepts_empty_when_no_concepts(db_conn):
    """Konsept cədvəli boşdursa boş siyahı qaytarmalıdır."""
    from collector.registry import list_concepts
    result = list_concepts(db_conn)
    assert result == []


def test_get_candidate_indicators_returns_sorted(db_conn):
    """get_candidate_indicators priority_tier ASC → confidence DESC qaytarmalıdır."""
    repository.ensure_catalogue_and_mapping(db_conn)

    from collector.registry import get_candidate_indicators
    result = get_candidate_indicators(db_conn, "gdp_growth")

    # eurostat + world_bank hər ikisi mövcud olmalıdır
    assert len(result) >= 2
    tiers = [r["priority_tier"] for r in result]
    assert tiers == sorted(tiers), "Sıralama priority_tier ASC olmalıdır"
    source_ids = {r["source_id"] for r in result}
    assert "world_bank" in source_ids
    assert "eurostat" in source_ids


def test_get_candidate_indicators_empty_for_unknown_concept(db_conn):
    """Mövcud olmayan konsept üçün boş siyahı qaytarmalıdır."""
    from collector.registry import get_candidate_indicators
    result = get_candidate_indicators(db_conn, "nonexistent_concept_xyz")
    assert result == []


def test_cbr_russia_not_in_any_mapping(db_conn):
    """cbr_russia heç bir konsept mapping-inə daxil edilməməlidir."""
    repository.ensure_catalogue_and_mapping(db_conn)

    from collector.registry import get_candidate_indicators
    for concept_id in ["gdp_per_capita", "gdp_growth", "unemployment", "inflation", "population"]:
        result = get_candidate_indicators(db_conn, concept_id)
        source_ids = {r["source_id"] for r in result}
        assert "cbr_russia" not in source_ids, \
            f"cbr_russia {concept_id} mapping-lərinə qarışmamalıdır"


def test_mapping_confidence_values(db_conn):
    """Eurostat mapping 0.95, WB-only (WB COMMON_INDICATORS) 0.90 confidence ilə."""
    repository.ensure_catalogue_and_mapping(db_conn)

    from collector.registry import get_candidate_indicators
    result = get_candidate_indicators(db_conn, "gdp_growth")

    # Config.yaml-dan — 0.95 confidence (WB + Eurostat)
    config_high = [r for r in result if r["confidence"] == 0.95]
    assert len(config_high) >= 2  # world_bank + eurostat

    # WB-only konsept (gdp) → yalnız WB, 0.90 confidence
    wb_only = get_candidate_indicators(db_conn, "gdp")
    assert len(wb_only) >= 1
    assert all(r["confidence"] == 0.90 for r in wb_only)
    assert all(r["source_id"] == "world_bank" for r in wb_only)


def test_match_type_is_rule_based(db_conn):
    """Bütün seed mapping-lər match_type='rule_based' olmalıdır."""
    repository.ensure_catalogue_and_mapping(db_conn)

    with db_conn.cursor() as cur:
        cur.execute("SELECT DISTINCT match_type FROM concept_indicator_map")
        types = [r[0] for r in cur.fetchall()]
    assert types == ["rule_based"], "Seed mapping-lər yalnız 'rule_based' olmalıdır"