"""
World Bank Open Data API üzərindən ölkələr/regionlar arası müqayisə.

Üstünlüyü: qeydiyyat/API-key lazım deyil, minlərlə göstərici (indicator)
var (GDP, əhali, işsizlik, inflyasiya, internet istifadəçiləri və s.),
və bir sorğu ilə istənilən sayda ölkəni birbaşa müqayisə edə bilirsən.

Sənəd: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392
"""

import json
import logging
import urllib.request
from urllib.parse import urlencode

from collector.sources.base import DataSource

logger = logging.getLogger("collector.worldbank")

BASE_URL = "https://api.worldbank.org/v2"

# Tez-tez lazım olan göstəricilər üçün rahat adlar.
# Tam siyahı: https://api.worldbank.org/v2/indicator?format=json&per_page=20000
COMMON_INDICATORS = {
    "gdp": "NY.GDP.MKTP.CD",                # ÜDM (cari USD)
    "gdp_per_capita": "NY.GDP.PCAP.CD",      # Adambaşı ÜDM
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",       # ÜDM artım tempi (%)
    "population": "SP.POP.TOTL",             # Əhali
    "unemployment": "SL.UEM.TOTL.ZS",        # İşsizlik (%)
    "inflation": "FP.CPI.TOTL.ZG",           # İnflyasiya (%)
    "internet_users": "IT.NET.USER.ZS",      # İnternet istifadəçiləri (%)
    "mobile_subscriptions": "IT.CEL.SETS.P2",# Mobil abunəçilər (100 nəfərə)
    "exports": "NE.EXP.GNFS.CD",             # İxrac (USD)
    "imports": "NE.IMP.GNFS.CD",             # İdxal (USD)
    "fdi_inflow": "BX.KLT.DINV.CD.WD",       # Xarici investisiya axını
    "life_expectancy": "SP.DYN.LE00.IN",     # Ömür gözləntisi
    "co2_emissions": "EN.ATM.CO2E.PC",       # Adambaşı CO2 (ton)
    "urban_population_pct": "SP.URB.TOTL.IN.ZS",
    "researchers_per_million": "SP.POP.SCIE.RD.P6",
    "ease_of_business": "IC.BUS.EASE.XQ",
}


class WorldBankSource(DataSource):
    def __init__(self, source_cfg: dict = None):
        # ayrıca konfiqurasiya tələb etmir, amma digər source-larla
        # eyni interfeysə uyğun olsun deyə source_cfg qəbul edir
        self.id = "world_bank"

    # ---------- DataSource ABC ----------
    def validate_connection(self) -> bool:
        rows = self._get("country/AZE/indicator/NY.GDP.MKTP.CD", {"per_page": 1})
        return bool(rows)

    def fetch(self, **kwargs):
        return self.compare(
            kwargs["country_codes"], kwargs["indicator"],
            kwargs["start_year"], kwargs["end_year"],
        )

    def _get(self, path: str, params: dict) -> list:
        params = dict(params)
        params["format"] = "json"
        url = f"{BASE_URL}/{path}?" + urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "data-collector/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
                # World Bank cavabı: [meta, [data...]] formatındadır
                if isinstance(data, list) and len(data) > 1:
                    return data[1] or []
                return []
        except Exception as e:
            logger.error("World Bank sorğu xətası (%s): %s", url, e)
            return []

    def resolve_indicator(self, name_or_code: str) -> str:
        return COMMON_INDICATORS.get(name_or_code.lower(), name_or_code)

    def compare(self, country_codes: list, indicator: str, start_year: int, end_year: int) -> list:
        """
        country_codes: ISO3 kodlar (["AZE", "USA", "DEU", "RUS"])
        indicator: rahat ad ("gdp_per_capita") və ya WB kodu ("NY.GDP.PCAP.CD")
        Qaytarır: [{country, iso3, year, value}, ...]
        """
        code = self.resolve_indicator(indicator)
        countries = ";".join(country_codes)
        raw = self._get(
            f"country/{countries}/indicator/{code}",
            {"date": f"{start_year}:{end_year}", "per_page": 2000},
        )

        rows = []
        for item in raw:
            if item is None:
                continue
            rows.append({
                "country": (item.get("country") or {}).get("value"),
                "iso3": item.get("countryiso3code"),
                "indicator": (item.get("indicator") or {}).get("value"),
                "year": item.get("date"),
                "value": item.get("value"),
            })
        return rows
