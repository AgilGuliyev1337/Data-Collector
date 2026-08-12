#!/usr/bin/env python3
"""
Universal Open-Data Collector CLI

İstifadə:
    python cli.py --migrate            # DB migration-larını tətbiq et (ilk dəfə tələb olunur)
    python cli.py --run                # config.yaml-dakı bütün enabled source-ları işlət
    python cli.py --run --source opendata_az   # yalnız bir source
    python cli.py --list-sources        # config-dəki source-ları göstər
    python cli.py --list-packages opendata_az  # bir portaldakı dataset adlarını göstər (yükləmədən)
"""

import argparse
import logging
import sys
import os
import yaml

from collector.sources.ckan_source import CKANSource
from collector.sources.worldbank_source import WorldBankSource, COMMON_INDICATORS
from collector.sources.eurostat_source import EurostatSource
from collector.sources.imf_source import IMFSource
from collector.sources.cbr_source import CBRSource
from collector.db.connection import get_connection
from collector.db import repository
from collector import csv_export

SOURCE_TYPES = {
    "ckan": CKANSource,
}


def load_config(path="config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(cfg: dict):
    log_cfg = cfg.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO"))
    handlers = [logging.StreamHandler()]
    if log_cfg.get("file"):
        os.makedirs("data", exist_ok=True)
        handlers.append(logging.FileHandler(log_cfg["file"], encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def _connect():
    try:
        return get_connection()
    except Exception as e:
        print(f"DB bağlantı xətası: {e}")
        print("Migration-ların tətbiq olunduğunu yoxla: python cli.py --migrate")
        sys.exit(1)


def build_sources(cfg: dict, only_id: str = None):
    built = []
    for s in cfg.get("sources", []):
        if not s.get("enabled", True):
            continue
        if only_id and s["id"] != only_id:
            continue
        cls = SOURCE_TYPES.get(s["type"])
        if not cls:
            logging.warning("Naməlum source type: %s (id=%s) - keçilir", s["type"], s["id"])
            continue
        built.append(cls(s))
    return built


def run(cfg: dict, only_id: str = None):
    sources = build_sources(cfg, only_id)

    if not sources:
        print("İşlədiləcək source tapılmadı (config.yaml-ı yoxla).")
        return

    conn = _connect()
    repository.ensure_static_sources(conn)
    conn.commit()
    run_id = repository.start_collection_run(conn, "run", {"source": only_id})
    conn.commit()

    total_saved = 0
    try:
        for src in sources:
            print(f"\n=== Source: {src.id} ===")
            repository.upsert_source(
                conn, src.id, "ckan", base_url=src.base_url,
                priority_tier=src.priority_tier, trust_level=src.trust_level,
            )
            conn.commit()
            n = 0
            for record in src.collect():
                repository.upsert_dataset(conn, record)
                conn.commit()
                n += 1
                if n % 20 == 0:
                    print(f"  ... {n} dataset toplandı")
            print(f"[{src.id}] cəmi {n} dataset saxlanıldı (filtrdən keçən)")
            total_saved += n
        repository.finish_collection_run(conn, run_id, "success", total_saved)
        conn.commit()
    except Exception as e:
        conn.rollback()
        repository.finish_collection_run(conn, run_id, "failed", total_saved, error_message=str(e))
        conn.commit()
        raise
    finally:
        conn.close()

    print(f"\nBİTDİ. Cəmi {total_saved} dataset bazaya yazıldı.")


def list_sources(cfg: dict):
    for s in cfg.get("sources", []):
        status = "✅ enabled" if s.get("enabled", True) else "⛔ disabled"
        print(f"- {s['id']} [{s['type']}] {s['base_url']}  ({status})")


def list_packages(cfg: dict, source_id: str):
    for s in cfg.get("sources", []):
        if s["id"] == source_id:
            src = CKANSource(s)
            names = src.list_package_names()
            print(f"{source_id}: {len(names)} dataset tapıldı\n")
            for n in names[:50]:
                print(" -", n)
            if len(names) > 50:
                print(f" ... və {len(names) - 50} dataset daha")
            return
    print(f"Source tapılmadı: {source_id}")


def list_indicators():
    print("Mövcud qısa göstərici adları (--indicator ilə istifadə et):\n")
    for k, v in COMMON_INDICATORS.items():
        print(f"  {k:<26} -> {v}")
    print("\nİstənilən digər World Bank göstərici kodunu da birbaşa verə bilərsən")
    print("(tam siyahı: https://api.worldbank.org/v2/indicator?format=json&per_page=20000)")


def compare(cfg: dict, indicator: str, regions: list, start_year: int, end_year: int, out_csv: str = None):
    wb = WorldBankSource()
    region_map = cfg.get("regions", {})

    all_rows = []
    for region_name in regions:
        codes = region_map.get(region_name)
        if not codes:
            print(f"Diqqət: '{region_name}' regionu config.yaml-da tapılmadı, keçilir.")
            continue
        print(f"[{region_name}] {codes} üçün sorğu göndərilir...")
        rows = wb.compare(codes, indicator, start_year, end_year)
        for r in rows:
            r["region"] = region_name
        all_rows.extend(rows)

    if not all_rows:
        print("Nəticə tapılmadı. Göstərici kodunu/ölkə siyahısını yoxla.")
        return

    # konsola qısa xülasə: hər ölkə üçün ən son mövcud dəyər
    latest = {}
    for r in all_rows:
        if r["value"] is None:
            continue
        key = r["iso3"]
        if key not in latest or r["year"] > latest[key]["year"]:
            latest[key] = r

    print(f"\n=== Nəticə: {indicator} (ən son mövcud il üzrə) ===")
    for iso3, r in sorted(latest.items(), key=lambda x: (x[1]["region"], x[1]["country"])):
        print(f"  [{r['region']:<12}] {r['country']:<20} ({r['year']}): {r['value']}")

    conn = _connect()
    repository.ensure_static_sources(conn)
    conn.commit()
    run_id = repository.start_collection_run(
        conn, "compare",
        {"indicator": indicator, "regions": regions, "start_year": start_year, "end_year": end_year},
    )
    conn.commit()
    indicator_code = wb.resolve_indicator(indicator)
    fact_rows = [
        {
            "source_id": "world_bank", "run_id": run_id, "concept": indicator,
            "indicator_code": indicator_code, "country": r["country"], "iso3": r["iso3"],
            "period": r["year"], "value": r["value"], "unit": None,
        }
        for r in all_rows if r["value"] is not None
    ]
    repository.insert_facts(conn, fact_rows)
    repository.finish_collection_run(conn, run_id, "success", len(fact_rows))
    conn.commit()
    conn.close()

    if out_csv:
        csv_export.save_comparison_csv(all_rows, out_csv)
        print(f"\nBütün illər üzrə tam data CSV-yə yazıldı: {out_csv}")


def cross_check(cfg: dict, concept: str, regions: list, start_year: int, end_year: int, out_csv: str = None):
    """
    Eyni konsepti (məs. gdp_growth) BİRDƏN ARTIQ mənbədən çəkib yan-yana qoyur.
    Bu, "bir mənbəyə güvənməmək" məqsədi üçün əsas funksiyadır.
    """
    concept_cfg = (cfg.get("concepts") or {}).get(concept)
    if not concept_cfg:
        print(f"'{concept}' konsepti config.yaml -> concepts bölməsində tapılmadı.")
        print(f"Mövcud konseptlər: {list((cfg.get('concepts') or {}).keys())}")
        return

    region_map = cfg.get("regions", {})
    all_country_codes = []
    for region_name in regions:
        all_country_codes.extend(region_map.get(region_name, []))

    all_rows = []

    # --- World Bank ---
    if "world_bank" in concept_cfg:
        wb = WorldBankSource()
        rows = wb.compare(all_country_codes, concept_cfg["world_bank"], start_year, end_year)
        for r in rows:
            r["source"] = "world_bank"
        all_rows.extend(rows)
        print(f"[world_bank] {len(rows)} qeyd alındı")

    # --- Eurostat (yalnız Avropa ölkə kodları üçün mənalıdır) ---
    if "eurostat" in concept_cfg:
        eu = EurostatSource()
        # Eurostat 2-hərfli ISO kod istifadə edir (DE, FR...), ISO3 deyil -
        # sadə çevirmə üçün ilk 2 hərf kifayət etmir, ona görə yalnız
        # 'europe' regionundakı kodları converts etmək lazımdır (əl ilə map).
        iso2_map = {"DEU": "DE", "FRA": "FR", "GBR": "UK", "NLD": "NL", "POL": "PL", "TUR": "TR"}
        eu_codes = [iso2_map[c] for c in all_country_codes if c in iso2_map]
        if eu_codes:
            rows = eu.get_indicator(concept_cfg["eurostat"], eu_codes, start_year, end_year)
            all_rows.extend(rows)
            print(f"[eurostat] {len(rows)} qeyd alındı")

    # --- IMF ---
    if "imf" in concept_cfg:
        imf = IMFSource()
        imf_cfg = concept_cfg["imf"]
        for country in all_country_codes:
            key = imf_cfg["key_template"].format(country=country)
            rows = imf.get_series(imf_cfg["dataset"], key, start_year, end_year)
            all_rows.extend(rows)
        print(f"[imf] cəmi qeydlər əlavə olundu")

    if not all_rows:
        print("Heç bir mənbədən nəticə alınmadı.")
        return

    print(f"\n=== Çarpaz-müqayisə: {concept} ({start_year}-{end_year}) ===")
    print(f"{'Mənbə':<12} {'Ölkə':<8} {'İl':<6} {'Dəyər'}")
    for r in sorted(all_rows, key=lambda x: (x.get("iso3") or x.get("country") or "", x.get("year") or "", x.get("source") or "")):
        if r.get("value") is None:
            continue
        print(f"{r.get('source', ''):<12} {r.get('iso3') or r.get('country'):<8} {r.get('year'):<6} {r.get('value')}")

    conn = _connect()
    repository.ensure_static_sources(conn)
    conn.commit()
    run_id = repository.start_collection_run(
        conn, "cross_check",
        {"concept": concept, "regions": regions, "start_year": start_year, "end_year": end_year},
    )
    conn.commit()
    fact_rows = [
        {
            "source_id": r.get("source"), "run_id": run_id, "concept": concept,
            "indicator_code": r.get("indicator"), "country": r.get("country"), "iso3": r.get("iso3"),
            "period": r.get("year"), "value": r.get("value"), "unit": None,
        }
        for r in all_rows if r.get("value") is not None
    ]
    repository.insert_facts(conn, fact_rows)
    repository.finish_collection_run(conn, run_id, "success", len(fact_rows))
    conn.commit()
    conn.close()

    if out_csv:
        csv_export.save_cross_check_csv(all_rows, out_csv)
        print(f"\nTam data CSV-yə yazıldı: {out_csv}")


def cbr_snapshot(out_csv: str = None):
    cbr = CBRSource()
    rows = cbr.get_daily_rates()
    if not rows:
        print("CBR-dan data alınmadı.")
        return
    print(f"=== Bank of Russia - günün valyuta məzənnələri ({rows[0]['date']}) ===")
    for r in sorted(rows, key=lambda x: x["currency"]):
        print(f"  {r['currency']}: {r['value_rub']} RUB (nominal={r['nominal']}) - {r['name']}")

    conn = _connect()
    repository.ensure_static_sources(conn)
    conn.commit()
    run_id = repository.start_collection_run(conn, "cbr_snapshot", {})
    conn.commit()
    fx_rows = [
        {
            "source_id": "cbr_russia", "run_id": run_id, "currency_code": r["currency"],
            "currency_name": r["name"], "nominal": r["nominal"], "value_rub": r["value_rub"],
            "rate_date": r["date"][:10] if r.get("date") else None,
        }
        for r in rows
    ]
    repository.upsert_fx_rates(conn, fx_rows)
    repository.finish_collection_run(conn, run_id, "success", len(fx_rows))
    conn.commit()
    conn.close()

    if out_csv:
        csv_export.save_cbr_csv(rows, out_csv)
        print(f"\nCSV-yə yazıldı: {out_csv}")


def main():
    parser = argparse.ArgumentParser(description="Universal Open-Data Collector")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--migrate", action="store_true", help="DB migration-larını tətbiq et")
    parser.add_argument("--run", action="store_true", help="Data toplamağı işə sal")
    parser.add_argument("--source", help="Yalnız bu source id-ni işlət")
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--list-packages", metavar="SOURCE_ID")

    parser.add_argument("--compare", action="store_true", help="Regionlar üzrə müqayisə et")
    parser.add_argument("--indicator", help="Göstərici (qısa ad və ya WB kodu, məs. gdp_per_capita)")
    parser.add_argument("--regions", nargs="+", default=["azerbaijan", "europe", "america", "cis"],
                         help="Müqayisə ediləcək regionlar (config.yaml-dakı adlarla)")
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--out-csv", help="Nəticəni CSV-yə yaz (opsional)")
    parser.add_argument("--list-indicators", action="store_true")

    parser.add_argument("--cross-check", action="store_true",
                         help="Bir konsepti (config.yaml -> concepts) BİRDƏN ARTIQ mənbədən çəkib müqayisə et")
    parser.add_argument("--concept", help="Konsept adı (məs. gdp_growth, unemployment, inflation)")

    parser.add_argument("--cbr-snapshot", action="store_true",
                         help="Bank of Russia-nın günün valyuta məzənnələrini göstər (MDB sektoral mənbə)")

    args = parser.parse_args()

    if args.migrate:
        from collector.db.migrate import run_migrations
        applied = run_migrations()
        if applied:
            print(f"Tətbiq olundu: {', '.join(applied)}")
        else:
            print("Bütün migration-lar artıq tətbiq olunub (dəyişiklik yoxdur).")
        return

    cfg = load_config(args.config)
    setup_logging(cfg)

    if args.list_indicators:
        list_indicators()
    elif args.cbr_snapshot:
        cbr_snapshot(args.out_csv)
    elif args.cross_check:
        if not args.concept:
            print("--concept tələb olunur (məs: --concept gdp_growth)")
            sys.exit(1)
        cross_check(cfg, args.concept, args.regions, args.start_year, args.end_year, args.out_csv)
    elif args.list_sources:
        list_sources(cfg)
    elif args.list_packages:
        list_packages(cfg, args.list_packages)
    elif args.compare:
        if not args.indicator:
            print("--indicator tələb olunur (məs: --indicator gdp_per_capita)")
            sys.exit(1)
        compare(cfg, args.indicator, args.regions, args.start_year, args.end_year, args.out_csv)
    elif args.run:
        run(cfg, only_id=args.source)
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
