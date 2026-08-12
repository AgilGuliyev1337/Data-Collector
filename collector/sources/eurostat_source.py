"""
Eurostat REST API (JSON-stat formatı).
Avropa Komissiyasının rəsmi statistika mənbəyi - açar/qeydiyyat lazım deyil.

Sənəd: https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-introduction
Query builder (dataset kodlarını tapmaq üçün): https://ec.europa.eu/eurostat/web/query-builder

QEYD: Eurostat-da hər göstərici üçün konkret "dataset code" var (məs. "une_rt_a"
işsizlik üçün). Bu kodları config.yaml-da özün query builder ilə yoxlayıb
təsdiqləməlisən - Eurostat kod adlandırması vaxtaşırı dəyişə bilir.
"""

import json
import logging
import urllib.request
from urllib.parse import urlencode

from collector.sources.base import DataSource

logger = logging.getLogger("collector.eurostat")

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"


class EurostatSource(DataSource):
    def __init__(self, source_cfg: dict = None):
        self.id = "eurostat"

    # ---------- DataSource ABC ----------
    def validate_connection(self) -> bool:
        raw = self._get("une_rt_a", {"geo": ["DE"], "sinceTimePeriod": 2020})
        return bool(raw and "value" in raw)

    def fetch(self, **kwargs):
        return self.get_indicator(
            kwargs["dataset"], kwargs["geo_codes"],
            kwargs["start_year"], kwargs["end_year"],
        )

    def _get(self, dataset: str, params: dict) -> dict:
        params = dict(params)
        params["format"] = "JSON"
        params["lang"] = "EN"
        url = f"{BASE_URL}/{dataset}?" + urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"User-Agent": "data-collector/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.error("Eurostat sorğu xətası (%s): %s", url, e)
            return {}

    def get_indicator(self, dataset: str, geo_codes: list, start_year: int, end_year: int) -> list:
        """
        dataset: Eurostat dataset kodu (məs. "une_rt_a" - illik işsizlik)
        geo_codes: ölkə kodları (["DE", "FR", "TR"])
        Qaytarır: [{country, year, value, dataset}, ...]

        Bu, JSON-stat formatını (dimension + flat value array) parse edir.
        """
        raw = self._get(dataset, {"geo": geo_codes, "sinceTimePeriod": start_year})
        if not raw or "value" not in raw:
            logger.warning("Eurostat: '%s' üçün data tapılmadı (dataset kodu düzgündürmü?)", dataset)
            return []

        dims = raw.get("dimension", {})
        geo_dim = dims.get("geo", {}).get("category", {}).get("index", {})
        time_dim = dims.get("time", {}).get("category", {}).get("index", {})

        # index -> label əks xəritəsi
        geo_by_pos = {v: k for k, v in geo_dim.items()}
        time_by_pos = {v: k for k, v in time_dim.items()}

        size = raw.get("size", [])
        # JSON-stat: dəyərlər flat dict {"pos": value} şəklindədir,
        # pos = geo_index * len(time) + time_index (dimension sırasına görə)
        n_time = len(time_dim)
        values = raw.get("value", {})

        rows = []
        for key_str, value in values.items():
            pos = int(key_str)
            geo_idx = pos // n_time
            time_idx = pos % n_time
            geo_code = geo_by_pos.get(geo_idx)
            year = time_by_pos.get(time_idx)
            if geo_code is None or year is None:
                continue
            try:
                year_int = int(year)
            except ValueError:
                year_int = year
            if isinstance(year_int, int) and not (start_year <= year_int <= end_year):
                continue
            rows.append({
                "country": geo_code,
                "iso3": geo_code,
                "indicator": dataset,
                "year": year,
                "value": value,
                "source": "eurostat",
            })
        return rows
