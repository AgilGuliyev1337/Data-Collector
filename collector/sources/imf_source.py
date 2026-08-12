"""
IMF (Beynəlxalq Valyuta Fondu) SDMX-JSON API.
World Bank-a alternativ, MÜSTƏQİL metodologiyalı beynəlxalq mənbə -
ona görə eyni göstərici üçün World Bank ilə IMF-i müqayisə etmək
məhz "bir mənbəyə güvənməmək" prinsipinə xidmət edir.

Açar/qeydiyyat lazım deyil.
Sənəd: https://datahelp.imf.org/knowledgebase/articles/1952905

QEYD: IMF-in dataset/key strukturu (məs. "IFS" dataset-i, "Q.AZ.NGDP_R_XDC"
kimi key-lər) mürəkkəbdir. Konkret key-i tapmaq üçün əvvəlcə Dataflow və
DataStructure endpoint-lərinə baxıb doğru kodu müəyyən etmək lazımdır.
"""

import json
import logging
import urllib.request
from urllib.parse import urlencode

from collector.sources.base import DataSource

logger = logging.getLogger("collector.imf")

BASE_URL = "http://dataservices.imf.org/REST/SDMX_JSON.svc"


class IMFSource(DataSource):
    def __init__(self, source_cfg: dict = None):
        self.id = "imf"

    # ---------- DataSource ABC ----------
    def validate_connection(self) -> bool:
        return bool(self.list_dataflows())

    def fetch(self, **kwargs):
        return self.get_series(
            kwargs["dataset"], kwargs["key"],
            kwargs["start_year"], kwargs["end_year"],
        )

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{BASE_URL}/{path}"
        if params:
            url += "?" + urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "data-collector/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.error("IMF sorğu xətası (%s): %s", url, e)
            return {}

    def list_dataflows(self) -> list:
        """Mövcud IMF dataset-lərinin (dataflow) siyahısı."""
        raw = self._get("Dataflow")
        try:
            flows = raw["Structure"]["Dataflows"]["Dataflow"]
            return [{"id": f["KeyFamilyRef"]["KeyFamilyID"], "name": f["Name"].get("#text", f["Name"])}
                    for f in flows]
        except (KeyError, TypeError):
            logger.warning("IMF Dataflow cavabı gözlənilən formatda deyil")
            return []

    def get_series(self, dataset: str, key: str, start_year: int, end_year: int) -> list:
        """
        dataset: məs. "IFS" (International Financial Statistics)
        key: SDMX key, məs. "A.AZ.NGDP_R_XDC" (Annual.Azerbaijan.Real GDP)
        Qaytarır: [{country_code, year, value, dataset}, ...]
        """
        raw = self._get(
            f"CompactData/{dataset}/{key}",
            {"startPeriod": start_year, "endPeriod": end_year},
        )
        try:
            series = raw["CompactData"]["DataSet"]["Series"]
        except (KeyError, TypeError):
            logger.warning("IMF: '%s/%s' üçün data tapılmadı (key düzgündürmü?)", dataset, key)
            return []

        if isinstance(series, dict):
            series = [series]

        rows = []
        for s in series:
            ref_area = s.get("@REF_AREA", "")
            obs = s.get("Obs", [])
            if isinstance(obs, dict):
                obs = [obs]
            for o in obs:
                rows.append({
                    "country": ref_area,
                    "iso3": ref_area,
                    "indicator": key,
                    "year": o.get("@TIME_PERIOD"),
                    "value": o.get("@OBS_VALUE"),
                    "source": "imf",
                })
        return rows
