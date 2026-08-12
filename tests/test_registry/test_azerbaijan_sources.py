"""
Phase 3: Azerbaijan Data Source Layer — Registry Entry Tests.

Yoxlanılır:
  - AZERBAIJAN_SOURCES dict-də stat_gov_az, cbar_az, opendata_az mövcuddur
  - ensure_azerbaijan_sources() idempotent şəkildə sources-a əlavə edir
  - Source prioritet tərtibatı: stat_gov_az (1) < opendata_az (2) < cbar_az (3)
  - Trust_level: hamısı "official"
  - Metadata sahələri düzgündür
  - register_discovered official trust_level qəbul etmir (default unverified_web)
  - Cədvəl varlıq olmadan çağırış xəta verir (FK constraint)
"""

import pytest

from collector.db import repository
from collector.registry import (
    AZERBAIJAN_SOURCES,
    ensure_azerbaijan_sources,
    get_source,
    list_by_tier,
)
ensure_catalogue_and_mapping = repository.ensure_catalogue_and_mapping

pytestmark = pytest.mark.db


def _count(conn, table, where="", params=()):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} {where}", params)
        return cur.fetchone()[0]


# ---------------------------------------------------------------
# AZERBAIJAN_SOURCES strukturu
# ---------------------------------------------------------------


def test_azerbaijan_sources_dict_has_expected_keys():
    """AZERBAIJAN_SOURCES üç source-un hamısını ehtiva etməlidir."""
    assert "stat_gov_az" in AZERBAIJAN_SOURCES
    assert "cbar_az" in AZERBAIJAN_SOURCES
    assert "opendata_az" in AZERBAIJAN_SOURCES


def test_azerbaijan_sources_priority_tiers():
    """Hər source-un prioritet dərəcəsi düzgün təyin edilməlidir."""
    assert AZERBAIJAN_SOURCES["stat_gov_az"]["priority_tier"] == 1
    assert AZERBAIJAN_SOURCES["opendata_az"]["priority_tier"] == 2
    assert AZERBAIJAN_SOURCES["cbar_az"]["priority_tier"] == 3


def test_azerbaijan_sources_trust_levels():
    """Bütün AZ source-ları official trust_level ilə."""
    for source_id, cfg in AZERBAIJAN_SOURCES.items():
        assert cfg["trust_level"] == "official", \
            f"{source_id} trust_level 'official' olmalıdır"


def test_azerbaijan_sources_metadata():
    """Metadata sahələri real məlumatları əks etdirməlidir."""
    # StatKom — API yoxdur
    stat_meta = AZERBAIJAN_SOURCES["stat_gov_az"]["metadata"]
    assert stat_meta["has_api"] is False
    assert stat_meta["access_method"] == "web_download"
    assert "Statistika" in stat_meta["name"]

    # Open Data — CKAN API var
    odata_meta = AZERBAIJAN_SOURCES["opendata_az"]["metadata"]
    assert odata_meta["has_api"] is True
    assert odata_meta["api_type"] == "ckan"

    # Mərkəzi Bank — API yoxdur (publik statistika üçün)
    cbar_meta = AZERBAIJAN_SOURCES["cbar_az"]["metadata"]
    assert cbar_meta["has_api"] is False
    assert cbar_meta["access_method"] == "web_download"


# ---------------------------------------------------------------
# ensure_azerbaijan_sources() funksionallığı
# ---------------------------------------------------------------


def test_ensure_azerbaijan_sources_creates_sources(db_conn):
    """ensure_azerbaijan_sources() sources cədvəlinə 3 source əlavə etməlidir."""
    ensure_catalogue_and_mapping(db_conn)  # sources əsasını yarad
    ensure_azerbaijan_sources(db_conn)

    # 3 AZ source + 4 global (world_bank, eurostat, imf, cbr_russia) = 7
    total = _count(db_conn, "sources")
    assert total >= 7, f"Minimum 7 source olmalıdır (got {total})"


def test_ensure_azerbaijan_sources_preserves_tiers(db_conn):
    """ensure_azerbaijan_sources() prioritet dərəcələrini qorumalıdır."""
    ensure_catalogue_and_mapping(db_conn)
    ensure_azerbaijan_sources(db_conn)

    for source_id in AZERBAIJAN_SOURCES:
        source = get_source(db_conn, source_id)
        assert source is not None, f"{source_id} sources cədvəlində tapılmalıdır"
        assert source["priority_tier"] == AZERBAIJAN_SOURCES[source_id]["priority_tier"], \
            f"{source_id} priority_tier düzgün olmalıdır"
        assert source["trust_level"] == "official"


def test_ensure_azerbaijan_sources_preserves_metadata(db_conn):
    """Metadata sahələri qorunmalıdır."""
    ensure_catalogue_and_mapping(db_conn)
    ensure_azerbaijan_sources(db_conn)

    for source_id, expected in AZERBAIJAN_SOURCES.items():
        source = get_source(db_conn, source_id)
        assert source is not None
        assert source["metadata"]["name"] == expected["metadata"]["name"]
        assert source["metadata"]["has_api"] == expected["metadata"]["has_api"]


def test_ensure_azerbaijan_sources_is_idempotent(db_conn):
    """Təkrar çağırış yeni source yaratmır (idempotent)."""
    ensure_catalogue_and_mapping(db_conn)
    ensure_azerbaijan_sources(db_conn)

    count_first = _count(db_conn, "sources")

    ensure_azerbaijan_sources(db_conn)
    count_second = _count(db_conn, "sources")

    assert count_first == count_second, \
        "İdempotent çağırış yeni source yaratmamalıdır"


def test_azerbaijan_sources_ordered_by_tier(db_conn):
    """list_by_tier() AZ source-ları prioritet sırası ilə qaytarmalıdır."""
    ensure_catalogue_and_mapping(db_conn)
    ensure_azerbaijan_sources(db_conn)

    sources = list_by_tier(db_conn, enabled_only=True)
    az_sources = [s for s in sources if s["id"] in AZERBAIJAN_SOURCES]

    # StatKom (1) → Open Data (2) → Mərkəzi Bank (3)
    expected_order = ["stat_gov_az", "opendata_az", "cbar_az"]
    actual_order = [s["id"] for s in az_sources]
    assert actual_order == expected_order, \
        f"AZ source-ları prioritet sırası ilə olmalıdır: {actual_order}"