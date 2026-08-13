"""
Internet Search — Web-based data retrieval fallback.

When all database sources fail (no candidates, empty results, connection errors),
this module searches the internet for the requested concept and extracts
structured year-value pairs from web pages.

Flow:
  concept_id -> build multi-language queries -> DuckDuckGo search ->
  fetch top N pages -> extract text -> parse (year, value, unit) tuples ->
  validate & deduplicate -> return rows in facts-table format

Uses only free APIs (DuckDuckGo + BeautifulSoup), no API keys required.
Trust level for returned data: 'unverified_web', confidence ~0.5-0.7.

All HTTP calls use stdlib urllib.request to match existing project patterns.
No new dependencies needed beyond what's already in .venv (requests is present).
"""

import logging
import re
import urllib.request
import urllib.parse
from typing import Optional

from collector.semantic_resolver import _normalize

logger = logging.getLogger("collector.internet_search")

# Azerbaijani synonyms grouped by concept (extracted from semantic_resolver.SYNONYM_DICT)
CONCEPT_INFO: dict[str, dict] = {
    "gdp_growth": {
        "display_en": "GDP Growth Rate",
        "display_az": "ÜDM artım",
        "synonyms": ["gross domestic product growth", "gdp growth rate", "üdm artım", "gdp böyümə"],
        "keywords": ["gdp", "growth", "artım", "boyume"],
    },
    "gdp": {
        "display_en": "Gross Domestic Product",
        "display_az": "ÜDM",
        "synonyms": ["gross domestic product", "gdp", "üdm"],
        "keywords": ["gdp", "gross", "domestic", "product", "udm"],
    },
    "unemployment": {
        "display_en": "Unemployment Rate",
        "display_az": "İşsizlik səviyyəsi",
        "synonyms": ["unemployment rate", "jobless rate", "işsizlik", "işsizlik səviyyəsi"],
        "keywords": ["unemployment", "jobless", "işsiz"],
    },
    "inflation": {
        "display_en": "Inflation Rate",
        "display_az": "İnflasiya səviyyəsi",
        "synonyms": ["inflation rate", "consumer price index", "inflasiya", "inflasiya səviyyəsi"],
        "keywords": ["inflation", "cpi", "price index", "inflasiya"],
    },
    "population": {
        "display_en": "Total Population",
        "display_az": "Əhali sayı",
        "synonyms": ["total population", "population count", "əhali", "əhali sayı"],
        "keywords": ["population", "people", "əhali", "say"],
    },
    "internet_users": {
        "display_en": "Internet Users",
        "display_az": "İnternet istifadəçiləri",
        "synonyms": ["internet users", "internet penetration", "internet istifadəçiləri"],
        "keywords": ["internet", "users", "istifadəçi"],
    },
    "exports": {
        "display_en": "Total Exports",
        "display_az": "İxracat",
        "synonyms": ["total exports", "goods export", "ixracat", "məhsul ixracı"],
        "keywords": ["exports", "export", "ixracat"],
    },
    "imports": {
        "display_en": "Total Imports",
        "display_az": "İdxalat",
        "synonyms": ["total imports", "goods import", "idxracat", "məhsul idxrası"],
        "keywords": ["imports", "import", "idxracat"],
    },
    "fdi_inflow": {
        "display_en": "Foreign Direct Investment Inflow",
        "display_az": "Xarici birbaşa investisiya",
        "synonyms": ["foreign direct investment", "fdi inflow", "birbaşa investisiya"],
        "keywords": ["fdi", "investment", "investisiya"],
    },
    "life_expectancy": {
        "display_en": "Life Expectancy",
        "display_az": "Yaşama müddəti",
        "synonyms": ["life expectancy at birth", "orta ömür müddəti"],
        "keywords": ["life expectancy", "ömrün"],
    },
    "co2_emissions": {
        "display_en": "CO2 Emissions Per Capita",
        "display_az": "CO2 emissiya",
        "synonyms": ["carbon dioxide emissions", "carbon emissions", "co2 emissiya"],
        "keywords": ["co2", "emissions", "emissiya"],
    },
    "urban_population_pct": {
        "display_en": "Urban Population Percentage",
        "display_az": "Şəhər əhalisi faizi",
        "synonyms": ["urban population", "urbanization", "şəhər payı"],
        "keywords": ["urban", "population", "şəhər"],
    },
    "mobile_subscriptions": {
        "display_en": "Mobile Subscriptions",
        "display_az": "Mobil abunəliklər",
        "synonyms": ["mobile subscriptions", "cellular subscriptions", "mobil abunə"],
        "keywords": ["mobile", "subscriptions", "mobil"],
    },
    "researchers_per_million": {
        "display_en": "Researchers Per Million",
        "display_az": "Alimlər per milyon",
        "synonyms": ["researchers per million", "rd personnel", "elmi işçi"],
        "keywords": ["researchers", "scientists", "tədqiqatçı"],
    },
    "ease_of_business": {
        "display_en": "Ease of Doing Business",
        "display_az": "Biznes üçün asanlıq",
        "synonyms": ["ease of doing business", "business environment"],
        "keywords": ["ease of business", "doing business"],
    },
    "maas": {
        "display_en": "Average Monthly Salary",
        "display_az": "Orta aylıq əmək haqqı",
        "synonyms": ["average salary", "monthly salary", "maaş", "əmək haqqı", "məvacib"],
        "keywords": ["salary", "wage", "maaş", "haqqı"],
    },
    "ev_qiymeti": {
        "display_en": "Housing Price Per Square Meter",
        "display_az": "Ev qiyməti",
        "synonyms": ["housing price per square meter", "apartment price", "ev qiyməti", "mənzil qiyməti", "əmlak qiyməti"],
        "keywords": ["housing price", "real estate", "apartment", "qiymət", "manzil", "menzil"],
    },
    "ev_almaq": {
        "display_en": "Housing Affordability",
        "display_az": "Ev almaq",
        "synonyms": ["housing affordability", "mortgage", "home buying", "ipoteka"],
        "keywords": ["affordable", "mortgage", "ipoteka"],
    },
}

# Known country codes mapping
COUNTRY_MAP: dict[str, str] = {
    "AZE": "Azerbaijan",
    "AZ": "Azerbaijan",
    "TUR": "Turkey",
    "TR": "Turkey",
    "RUS": "Russia",
    "RU": "Russia",
    "USA": "United States",
    "US": "United States",
    "KAZ": "Kazakhstan",
    "KZ": "Kazakhstan",
    "GEO": "Georgia",
    "GE": "Georgia",
}


def _get_concept_info(concept_id: str) -> dict | None:
    """Get display names and synonyms for a concept ID."""
    return CONCEPT_INFO.get(concept_id)


def summarize_query(text: str) -> str:
    """Reduce a raw free-text user query to its meaningful keywords.

    Strips stopwords, bare years (period is handled separately) and short
    tokens, so a messy natural-language sentence turns into a compact
    phrase suitable as a web search query. Falls back to the stripped
    original text if nothing meaningful survives the filtering.
    """
    if not text:
        return ""

    from collector.nl_parser import AZ_STOP_WORDS_NORM

    norm = _normalize(text)
    tokens = re.findall(r"[a-z]+", norm)
    keywords = [t for t in tokens if t not in AZ_STOP_WORDS_NORM and len(t) > 2]

    return " ".join(keywords) if keywords else text.strip()


def _build_search_queries(
    concept_id: str,
    countries: list[str],
    period_start: int | None,
    period_end: int | None,
    raw_query: str | None = None,
) -> list[str]:
    """Build multi-language search queries for DuckDuckGo.

    Creates queries in both English and Azerbaijani with country context
    and optional time period. When the concept isn't in CONCEPT_INFO (or
    at all — e.g. the NL parser couldn't resolve one), `raw_query` — the
    user's original free-text — is summarized into keywords and used to
    build the search query instead.

    Examples:
        "Azerbaijan housing price per square meter 2024 2025"
        "Azərbaycan ev qiyməti ilik dəyər 2024"
    """
    info = _get_concept_info(concept_id)

    country_names = []
    for code in countries:
        name = COUNTRY_MAP.get(code, "")
        if name:
            country_names.append(name)
        elif code != "global" and code != "AZE":
            country_names.append(code)

    country_str = " ".join(country_names) if country_names else "Azerbaijan"
    period_parts = []
    if period_start and period_end:
        if period_start == period_end:
            period_parts.append(str(period_start))
        else:
            period_parts = [str(period_start), str(period_end)]
    elif period_end:
        period_parts.append(str(period_end))

    period_str = " ".join(period_parts)
    queries = []

    if not info:
        # Concept unresolved — summarize the user's raw query into keywords
        keywords = summarize_query(raw_query) if raw_query else concept_id
        if not keywords:
            keywords = concept_id or ""
        queries.append(f"{country_str} {keywords} {period_str}".strip() if period_str else f"{country_str} {keywords}".strip())
        if raw_query:
            # Also add a keyword-only variant (drops the country bias) for freeform queries
            queries.append(f"{keywords} {period_str}".strip() if period_str else keywords)
        return [q for q in queries if q]

    # EN queries
    display_en = info["display_en"]
    queries.append(f"{country_str} {display_en} {period_str}" if period_str else f"{country_str} {display_en}")

    # Try synonyms too
    for syn in info.get("synonyms", [])[:3]:
        q = f"{country_str} {syn}"
        if period_str:
            q += f" {period_str}"
        queries.append(q)

    # AZ queries
    display_az = info["display_az"]
    queries.append(f"{country_str.replace('Azerbaijan', 'Azərbaycan')} {display_az}")
    if period_str:
        queries.append(f"{country_str.replace('Azerbaijan', 'Azərbaycan')} {display_az} {period_str}")

    # Keyword-based queries
    kw_query = " ".join(info["keywords"])[:4]
    queries.append(f"{country_str} {kw_query} statistics data values")

    # Also fold in the user's own words (deduped by set logic downstream) —
    # ensures search reflects the actual phrasing, not just the matched concept.
    if raw_query:
        summarized = summarize_query(raw_query)
        if summarized and summarized.lower() not in (q.lower() for q in queries):
            queries.append(f"{country_str} {summarized} {period_str}".strip() if period_str else f"{country_str} {summarized}".strip())

    return queries


# ---------------------------------------------------------------------------
# DuckDuckGo search via DDGS Python package
# ---------------------------------------------------------------------------

def _search_ddg(queries: list[str]) -> list[dict]:
    """Search DuckDuckGo for relevant URLs.

    Args:
        queries: List of search query strings.

    Returns:
        List of dicts with keys: title, url, snippet, source.
        Deduplicated by URL.
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.error("duckduckgo-search not installed. Run: pip install duckduckgo-search")
        return []

    results: dict[str, dict] = {}  # dedup by URL

    for i, query in enumerate(queries[:5]):  # limit to first 5 queries
        try:
            logger.debug("Searching DDG: %s", query[:80])
            with DDGS() as ddgs:
                hits = list(ddgs.text(query, max_results=10))
                for h in hits:
                    url = h.get("href", "")
                    if url and url not in results:
                        results[url] = {
                            "title": h.get("title", ""),
                            "url": url,
                            "snippet": h.get("body", ""),
                            "source": f"ddg_query_{i+1}",
                        }
            if len(results) >= 20:
                break
        except Exception as e:
            logger.warning("DDG search failed for query %d: %s", i, e)

    return list(results.values())[:30]  # top 30 unique URLs


# ---------------------------------------------------------------------------
# Page fetching and HTML parsing
# ---------------------------------------------------------------------------

def _fetch_page_text(url: str, timeout: int = 10) -> str | None:
    """Fetch a webpage and return cleaned text content.

    Strips scripts, styles, and navigation elements to leave
    only readable body text and tables.

    Args:
        url: Full URL to fetch.
        timeout: Seconds before giving up.

    Returns:
        Cleaned text content, or None on failure.
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DataCollector/1.0)"}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode(resp.headers.get_content_charset() or "utf-8")
    except Exception as e:
        logger.debug("Failed to fetch %s: %s", url, e)
        return None

    # Use BeautifulSoup if available, otherwise basic cleaning
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "html.parser")

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
            tag.decompose()

        # If table found, also get table text
        table_texts = ""
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if cells:
                    table_texts += " " + " ".join(c.get_text(strip=True) for c in cells)

        body_text = soup.get_text(separator=" ", strip=True)
        return body_text + "\n" + table_texts

    except ImportError:
        # Fallback: basic regex cleanup
        import re as _re
        text = raw
        text = _re.sub(r"<[^>]+>", " ", text)
        text = _re.sub(r"\s+", " ", text)
        return text.strip()


# ---------------------------------------------------------------------------
# Year-value pair extraction from text
# ---------------------------------------------------------------------------

# Patterns for year-value pairs in various formats
_YEAR_VALUE_PATTERNS: list[tuple[str, str]] = [
    # "2020: 1450", "2020 - 1450", "2020: 1,450", "2020 — 1450"
    (r'\b(20\d{2}|19\d{2})\b\s*[-–—:]\s*(\d+(?:[,.]\d+)?)', "col"),
    # "in 2020, 1450", "during 2020 1450"
    (r'(?:in|during)\s+(20\d{2}|19\d{2})[\s,.]+\s*(\d+(?:[,.]\d+)?)', "prepos"),
    # Table-like: "2020\t1450" or "2020|1450"
    (r'\b(20\d{2}|19\d{2})\b[\t|\,;\s]{1,3}(\d+(?:[,.]\d+)?)', "tabular"),
    # "Year 2020: Value 1450"
    (r'[(yY)ear]\s+(20\d{2}|19\d{2})\s*[-:]\s*(\d+(?:[,.]\d+)?)', "year_kw"),
]


def _parse_year_value_pairs(text: str) -> list[tuple[int, float]]:
    """Extract (year, value) pairs from text.

    Handles many common formats:
      "2020: 1450"
      "2020 - 1,450"
      "in 2020, 1450"
      Table rows: "2020\t1450"

    Args:
        text: Extracted text from a web page.

    Returns:
        Sorted list of (year, value_float) tuples.
    """
    pairs: list[tuple[int, float]] = []

    for pattern, _fmt in _YEAR_VALUE_PATTERNS:
        try:
            matches = re.findall(pattern, text)
            for match in matches:
                year_str = match[0]
                value_str = match[1].replace(",", "").replace(".", "", 1) if "." not in match[1] else match[1].replace(",", "")

                try:
                    year = int(year_str)
                    value = float(value_str)

                    # Sanity checks
                    if 1990 <= year <= 2030 and value > 0:
                        pairs.append((year, value))
                except (ValueError, TypeError):
                    pass
        except re.error:
            pass

    # Deduplicate: keep highest value per year
    seen: dict[int, float] = {}
    for year, value in pairs:
        if year not in seen or value > seen[year]:
            seen[year] = value

    return sorted(seen.items())


def _classify_unit_from_text(text: str) -> str:
    """Heuristically determine the unit from surrounding text.

    Searches for currency symbols, percentage signs, units like 'm²',
    'AZN', 'USD', '%', 'people', etc.
    """
    text_lower = text.lower()

    if any(w in text_lower for w in ["percent", "%", "faiz", "pct"]):
        return "percent"
    if any(w in text_lower for w in ["azn", "manat", "₼", "az"]):
        return "AZN"
    if any(w in text_lower for w in ["usd", "dollar", "$", " USD "]):
        return "USD"
    if any(w in text_lower for w in ["per sq", "sqm", "m2", "kv.m", " kv/m"]):
        return "AZN/m²"
    if any(w in text_lower for w in ["million", "mil", "milyon"]):
        return "millions"
    if any(w in text_lower for w in ["people", "population", "əhali", "nəfər"]):
        return "people"

    return "unknown"


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

def search_internet(
    concept_id: str,
    countries: list[str],
    period_start: int | None = None,
    period_end: int | None = None,
    raw_query: str | None = None,
) -> list[dict]:
    """Search the internet for data about a concept.

    This is the main entry point called from orchestrator.py when
    all database sources have failed.

    Args:
        concept_id: Concept identifier (e.g., "ev_qiymeti", "maas"). May be
            empty when the NL parser couldn't resolve a known concept.
        countries: ISO3 country codes (e.g., ["AZE"]).
        period_start: Starting year (inclusive).
        period_end: Ending year (inclusive).
        raw_query: The user's original free-text query. Used to build search
            queries (via `summarize_query`) when `concept_id` doesn't match
            a known concept, so unresolved queries still get searched.

    Returns:
        List of rows in facts-table format:
        [{
            "source_id": "internet_search",
            "indicator_code": "...",
            "country": "AZE",
            "iso3": "AZE",
            "period": "2024",
            "value": 2200.0,
            "unit": "AZN/m²",
            "_source_url": "https://example.com/source",
            "_source_title": "Page Title",
        }, ...]

        Returns empty list if no meaningful data found.
    """
    info = _get_concept_info(concept_id)
    freeform_keywords = summarize_query(raw_query) if (not info and raw_query) else ""
    indicator_code = concept_id or (freeform_keywords.replace(" ", "_")[:40] if freeform_keywords else "")

    if not info and not freeform_keywords:
        logger.info("Nə concept, nə də mənalı raw_query var — internet axtarışı keçilir.")
        return []

    logger.info("Searching internet for concept '%s' (%s)", concept_id, indicator_code)

    # Step 1: Build queries
    queries = _build_search_queries(concept_id, countries, period_start, period_end, raw_query=raw_query)
    logger.info("Built %d queries", len(queries))
    for q in queries[:3]:
        logger.debug("Query: %s", q[:100])

    # Step 2: Search DuckDuckGo
    search_results = _search_ddg(queries)
    if not search_results:
        logger.warning("No DuckDuckGo results found")
        return []

    logger.info("Got %d unique URLs from DDG", len(search_results))

    # Step 3: Fetch and parse each page
    all_pairs: dict[int, tuple[float, str, str, str]] = {}  # year -> (value, url, title, snippet)
    country_name = COUNTRY_MAP.get(countries[0], "Azerbaijan") if countries else "Azerbaijan"

    for result in search_results:
        url = result["url"]
        title = result.get("title", "")
        snippet = result.get("snippet", "")

        # Quick relevance check: does the page mention our topic?
        combined = (title + " " + snippet).lower()
        if info:
            topic_terms = [w.lower() for w in info["keywords"]][:3]
            if not any(t in combined for t in topic_terms):
                logger.debug("Skipping %s — low relevance", url)
                continue
        elif freeform_keywords:
            # freeform_keywords is AZ-char-normalized (ə→e, ı→i, ...) via summarize_query,
            # so normalize the page text the same way before comparing — otherwise a raw
            # Azerbaijani snippet ("Bakıda") never matches the normalized keyword ("bakida").
            combined_norm = _normalize(combined)
            topic_terms = freeform_keywords.split()[:4]
            if topic_terms and not any(t in combined_norm for t in topic_terms):
                logger.debug("Skipping %s — low relevance (freeform)", url)
                continue

        # Fetch page text
        page_text = _fetch_page_text(url)
        if not page_text:
            continue

        # Extract year-value pairs
        pairs = _parse_year_value_pairs(page_text)
        if not pairs:
            continue

        unit = _classify_unit_from_text(page_text)

        for year, value in pairs:
            if year not in all_pairs or value > all_pairs[year][0]:
                all_pairs[year] = (value, url, title, unit)

    if not all_pairs:
        logger.warning("No year-value pairs extracted from any page")
        return []

    # Sort by year and filter: need at least 2 consecutive years OR recent data
    sorted_years = sorted(all_pairs.keys())

    # Filter: keep years within requested range
    if period_start:
        sorted_years = [y for y in sorted_years if y >= period_start]
    if period_end:
        sorted_years = [y for y in sorted_years if y <= period_end]

    if not sorted_years:
        logger.warning("No pairs within requested period range")
        return []

    # Validate: must have at least 1 data point
    if len(sorted_years) < 1:
        return []

    # Also require: either multiple years, or a single recent year (last 5 years)
    if len(sorted_years) == 1:
        recent_cutoff = (period_end or 2025) - 5
        if sorted_years[0] < recent_cutoff:
            logger.info("Single data point too old (%d), skipping", sorted_years[0])
            return []

    # Step 4: Convert to row format
    iso3 = countries[0] if countries and countries[0] in ("AZE", "TUR", "RUS", "USA", "KAZ", "GEO") else "AZE"
    rows = []
    confidence = 0.55 if info else 0.45

    for year in sorted_years:
        value, url, title, unit = all_pairs[year]
        row = {
            "source_id": "internet_search",
            "indicator_code": indicator_code,
            "country": iso3,
            "iso3": iso3,
            "period": str(year),
            "value": round(value, 2),
            "unit": unit if unit != "unknown" else None,
            "_source_url": url,
            "_source_title": title,
            "_source_type": "web",
            "_confidence": confidence,
        }
        rows.append(row)

    logger.info("Extracted %d valid data points from internet", len(rows))
    return rows
