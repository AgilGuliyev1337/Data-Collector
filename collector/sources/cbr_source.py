"""
Bank of Russia (CBR) - sektoral/maliyyə mənbəyi (mərkəzi bank statistikası).
World Bank/IMF kimi "aqreqat statistika" deyil, birbaşa mərkəzi bankın
özündən gündəlik valyuta məzənnələri - real vaxt maliyyə datası nümunəsi.

Açar/qeydiyyat lazım deyil, JSON.
Rəsmi (cbr.ru) həm XML, həm JSON dəstəkləyir; sadəlik üçün ictimai
JSON proxy-dən (cbr-xml-daily.ru) istifadə edirik - əsas mənbə cbr.ru-dur,
bu sadəcə eyni datanın JSON export formasıdır.

Sənəd: https://www.cbr.ru/development/sxml/ (rəsmi), https://www.cbr-xml-daily.ru/
"""

import json
import logging
import urllib.request

from collector.sources.base import DataSource

logger = logging.getLogger("collector.cbr")

DAILY_URL = "https://www.cbr-xml-daily.ru/daily_json.js"


class CBRSource(DataSource):
    """
    QEYD: bu adapter digərlərindən (WorldBank/Eurostat/IMF) fərqli formadadır.
    Digərləri {country, indicator, year, value} formalı ÇOX İLLİK göstərici
    sıraları qaytarır; CBR isə indicator/country oxu OLMAYAN, bir günün FX
    "snapshot"-unu qaytarır (currency, nominal, value_rub, date). Ona görə
    bu adapterin nəticələri `facts` cədvəlinə YOX, ayrıca `fx_rates`
    cədvəlinə yazılır (bax: migrations/0001_init.sql, collector/db/repository.py).
    """

    def __init__(self, source_cfg: dict = None):
        self.id = "cbr_russia"

    # ---------- DataSource ABC ----------
    def validate_connection(self) -> bool:
        return bool(self.get_daily_rates())

    def fetch(self, **kwargs):
        return self.get_daily_rates()

    def get_daily_rates(self) -> list:
        """
        Günün valyuta məzənnələrini qaytarır (RUB-a qarşı).
        Qaytarır: [{currency, value, nominal, date, source}, ...]
        """
        req = urllib.request.Request(DAILY_URL, headers={"User-Agent": "data-collector/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            logger.error("CBR sorğu xətası: %s", e)
            return []

        date = data.get("Date")
        rows = []
        for code, info in (data.get("Valute") or {}).items():
            rows.append({
                "currency": code,
                "name": info.get("Name"),
                "nominal": info.get("Nominal"),
                "value_rub": info.get("Value"),
                "date": date,
                "source": "cbr_russia",
            })
        return rows
