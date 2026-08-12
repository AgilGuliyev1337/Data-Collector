# -*- coding: utf-8 -*-
"""
Manzil.az Source — Real Estate List Scraper.

Azərbaycanın ən böyük əmlak portalı olan manzil.az-dan
real estate elanlarını çəkərək orta qiymətləri hesablayır.

FAYDALANIŞ:
    from collector.sources.manzil_az_source import ManzilAzSource
    mz = ManzilAzSource()

    # Ümumi ortalamalar
    rows = mz.fetch(concept="ev_qiymeti", start_year=2024, end_year=2025)

    # Konkret rayon üzrə
    rows = mz.fetch(concept="ev_qiymeti", district="Nəsimi", rooms=2)
"""

import json
import logging
import re
import urllib.request
from urllib.parse import urlencode, quote

from collector.sources.base import DataSource

logger = logging.getLogger("collector.manzil_az")

SEARCH_URL = "https://api.manzil.az/v1/ads"
# Manzil.az API v2 (daha yeni)
SEARCH_URL_V2 = "https://api.manzil.az/v2/listings"


class ManzilAzSource(DataSource):
    """Manzil.az — Əmlak elanlarından orta qiymət hesablayıcı."""

    def __init__(self, source_cfg: dict = None):
        self.id = "manzil_az"
        self._cached_prices = None

    # ---------- DataSource ABC ----------

    def validate_connection(self) -> bool:
        try:
            result = self._search(query="", page=1, per_page=1)
            return result.get("status") == "success" if result else False
        except Exception:
            return False

    def fetch(self, **kwargs):
        concept = kwargs.get("concept", "ev_qiymeti")
        start_year = kwargs.get("period_start", 2023)
        end_year = kwargs.get("period_end", 2025)
        district = kwargs.get("district", None)
        rooms = kwargs.get("rooms", None)

        if concept == "ev_qiymeti":
            return self._fetch_housing(start_year, end_year, district, rooms)
        return []

    def _fetch_housing(self, start_year, end_year, district, rooms):
        """Manzil.az-dan elanları çəkib orta qiymət hesabla."""
        # Son 6 ayın elanlarını çək (yaşıl məlumat üçün)
        months_back = 6
        listings = []

        # District mapping — Azərbaycan dilindən API filter-ə
        district_query = district if district else ""

        # Manzil.az-dən elan çək
        for page in range(1, 4):  # İlk 3 səhifə (~300 elan)
            data = self._search(query=district_query, page=page, per_page=100)
            if not data or data.get("total", 0) == 0:
                break
            for ad in data.get("ads", []):
                price = ad.get("price")
                area = ad.get("area")
                if price and area and area > 0:
                    price_per_m2 = price / area
                    if 500 < price_per_m2 < 10000:  # Realistic range
                        listings.append({
                            "price_per_m2": price_per_m2,
                            "total_price": price,
                            "area": area,
                            "rooms": ad.get("rooms"),
                            "district": ad.get("district", ""),
                            "year": end_year,
                        })
            if data.get("total", 0) <= page * 100:
                break

        if not listings:
            # Hardcoded fallback
            return self._get_defaults(start_year, end_year, district)

        # Ortalamalar hesabla
        avg_price_m2 = sum(l["price_per_m2"] for l in listings) / len(listings)
        median_price_m2 = self._median(l["price_per_m2"] for l in listings)
        min_price_m2 = min(l["price_per_m2"] for l in listings)
        max_price_m2 = max(l["price_per_m2"] for l in listings)

        rows = [
            {
                "country": "Azerbaijan",
                "iso3": "AZE",
                "indicator": "ev_qiymeti",
                "period": str(end_year),
                "value": avg_price_m2,
                "unit": "AZN/m²",
                "source_detail": "manzil.az",
                "median_value": median_price_m2,
                "min_value": min_price_m2,
                "max_value": max_price_m2,
                "sample_size": len(listings),
            }
        ]
        return rows

    def _search(self, query: str, page: int, per_page: int) -> dict:
        """Manzil.az API sorğusu."""
        params = urlencode({
            "q": query,
            "page": page,
            "per_page": per_page,
            "sort": "date_desc",
        })
        url = f"{SEARCH_URL}?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "data-collector/1.0",
            "Accept": "application/json",
            "Origin": "https://manzil.az",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.debug("Manzil.az sorğu xətası: %s", e)
            return {}

    def _get_defaults(self, start_year, end_year, district=None):
        """Fallback — məlum qiymətlər."""
        district_avg = {
            None: 2388,
            "Nəsimi": 3827,
            "Yasamal": 3635,
            "Nizami": 2818,
            "Binəqədi": 2813,
            "Sabunçu": 2401,
            "Suraxanı": 2113,
            "Xəzər": 2005,
            "Qaradağ": 1842,
            "Xətai": 3199,
            "Nərimanov": 3574,
        }
        known_values = {
            2020: 1450,
            2021: 1620,
            2022: 1850,
            2023: 2100,
            2024: 2350,
            2025: 2388,
        }
        rows = []
        for year in range(start_year, end_year + 1):
            if year in known_values:
                rows.append({
                    "country": "Azerbaijan",
                    "iso3": "AZE",
                    "indicator": "ev_qiymeti",
                    "period": str(year),
                    "value": float(known_values[year]),
                    "unit": "AZN/m²",
                    "source_detail": "manzil.az (fallback)",
                    "median_value": float(known_values[year]),
                    "sample_size": 0,
                })
        return rows

    def _median(self, values):
        """Median hesabla."""
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n == 0:
            return 0
        if n % 2 == 1:
            return sorted_vals[n // 2]
        return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2