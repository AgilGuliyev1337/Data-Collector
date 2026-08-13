"""
InternetSource — DataSource adapter for web-based data retrieval.

Uses DuckDuckGo search + BeautifulSoup to find and extract
year-value pairs from the open web when database sources fail.

Integration:
    from collector.sources.internet_source import InternetSource

    source = InternetSource()
    results = source.fetch(
        concept="ev_qiymeti",
        countries=["AZE"],
        period_start=2020,
        period_end=2025,
    )
    # Returns list[dict] matching facts-table format
"""

import logging
from typing import Any

from .base import DataSource

logger = logging.getLogger("collector.internet_source")


class InternetSource(DataSource):
    """Adapter that searches the internet for economic/statistical data."""

    id = "internet_search"

    def validate_connection(self) -> bool:
        """Check if internet search works by doing a quick probe."""
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                hits = list(ddgs.text("test", max_results=1))
                return len(hits) >= 1
        except Exception as e:
            logger.debug("DDGS validation failed: %s", e)
            return False

    def fetch(self, **kwargs: Any) -> list[dict]:
        """Search the internet for data on the given concept.

        Args:
            **kwargs:
                concept: concept_id (e.g., "ev_qiymeti", "maas")
                countries: list of ISO3 country codes
                period_start: start year
                period_end: end year

        Returns:
            List of dicts matching facts-table row format.
            Each row includes _source_url, _source_title, _confidence metadata.
        """
        from collector.internet_search import search_internet

        concept = kwargs.get("concept") or kwargs.get("indicator_code", "")
        countries = kwargs.get("countries", ["AZE"])
        period_start = kwargs.get("period_start")
        period_end = kwargs.get("period_end")

        if not concept:
            logger.warning("No concept provided for InternetSource.fetch()")
            return []

        logger.info(
            "InternetSource fetching: concept=%s, countries=%s, years=%s-%s",
            concept, countries, period_start, period_end,
        )

        try:
            results = search_internet(
                concept_id=concept,
                countries=countries,
                period_start=period_start,
                period_end=period_end,
            )
            logger.info("InternetSource found %d data points", len(results))
            return results
        except Exception as e:
            logger.error("InternetSource fetch failed: %s", e)
            return []
