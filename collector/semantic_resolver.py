"""
Phase 5 — Semantic Concept Resolution.

Məqsəd: catalogue_entries → concepts uyğunluğu yaratmaq.
Deterministik (LLM yox, sinonim lüğəti + keyword match).
LLM yalnız ambiguous (0.60-0.79 confidence) namizədlər üçün.

AZ-EN synonym dictionary, multiple match strategies, confidence scoring.

Usage:
    from collector.semantic_resolver import (
        resolve_catalogue_entry,
        resolve_all_catalogue_entries,
        seed_concepts,
        seed_concept_mappings_from_synonyms,
        generate_resolver_report,
    )
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# AZ-EN Synonym Dictionary
# ---------------------------------------------------------------------------
# Hər konsept üçün:
#   - display_name: ingiliscə göstərici adı (CONCEPT_DISPLAY_NAMES ilə eyni)
#   - az: Azərbaycan dilində sinonimlər/abreviaturalar
#   - en: İngiliscə sinonimlər/abreviaturalar
#   - keywords: əsas açar sözlər (hər hansı birinin olması zəif uyğunluq)

SYNONYM_DICT: dict[str, dict] = {
    "gdp_growth": {
        "display_name": "GDP Growth Rate",
        "az": {
            "üdm artım",
            "üdm-artım",
            "gdp artım",
            "gdp böyümə",
            "gdp-böyümə",
            "gdp böyümə sürəti",
            "gross domestic product growth",
        },
        "en": {
            "gdp growth",
            "gdp growth rate",
            "gross domestic product growth",
            "economic growth rate",
            "real gdp growth",
            "gdp annual growth",
        },
        # _normalize("üdm")="udm", _normalize("böyümə")="boyume"
        "keywords": {
            "gdp", "gdm", "udm", "gross", "domestic", "product",
            "growth", "artim", "artım", "boyume", "boyu", "böyü",
        },
    },
    "gdp": {
        "display_name": "Gross Domestic Product",
        "az": {"üdm", "gdp", "gdm", "gross domestic product", "dövlət məhsulu"},
        "en": {"gdp", "gross domestic product"},
        # "üdm" → "udm" after normalize
        "keywords": {"gdp", "gdm", "udm", "gross", "domestic", "product"},
    },
    "gdp_per_capita": {
        "display_name": "GDP Per Capita",
        "az": {
            "əhalinin hər nəfərinə düşən üdm",
            "əhalı başına üdm",
            "nəfər üzrə üdm",
            "gdp başına",
            "gdp-nəfər başına",
        },
        "en": {
            "gdp per capita",
            "gdp per person",
            "gdp per head",
            "gross domestic product per capita",
            "gdp income",
            "wage",
            "salaries",
            "salary",
            "income per capita",
        },
        # "nəfər"→"nefer", "başına"→"basina", "üdm"→"udm"
        "keywords": {"gdp", "gdm", "udm", "per capita", "nefer", "nfe", "capita", "basina", "başına", "wage", "salari", "income", "gəlir"},
    },
    "unemployment": {
        "display_name": "Unemployment Rate",
        "az": {"işsizlik", "işsizlik səviyyəsi", "ihsizlik", "unemployment", "jobless rate"},
        "en": {
            "unemployment",
            "unemployment rate",
            "jobless rate",
            "jobless",
            "labour market",
            "labour",
            "employment rate",
        },
        # "unemployment" INDICATOR CODE-da da ola bilər → keyword-ə də əlavə et
        "keywords": {"ihsiz", "ihsizlik", "işsiz", "işsizlik", "unemploy", "jobless", "unemployment"},
    },
    "inflation": {
        "display_name": "Inflation Rate",
        "az": {"inflasiya", "inflyasiya", "inflasiya səviyyəsi", "inflation"},
        "en": {
            "inflation",
            "inflation rate",
            "consumer price",
            "cpi",
            "price level",
            "cost of living",
        },
        "keywords": {"inflasiya", "inflyasiya", "inflat", "price", "cpi", "hicp", "inflation"},
    },
    "population": {
        "display_name": "Total Population",
        "az": {"nəfər", "ehali", "ehalin", "ehalinin", "ehalini", "populyasiya", "population", "total population"},
        "en": {
            "population",
            "total population",
            "people",
            "inhabitants",
            "pop",
            "population count",
            "number of people",
        },
        "keywords": {"nefer", "nfe", "ehali", "ehalin", "ehalinin", "ehal", "ehalini", "populat", "population", "people", "inhabitant", "pop", "say", "sayi", "sayın"},
    },
    "internet_users": {
        "display_name": "Internet Users",
        "az": {
            "internet istifadəçiləri",
            "internet istifadəçi",
            "internet istifadə",
            "internet user",
        },
        "en": {
            "internet users",
            "internet user",
            "internet usage",
            "internet penetration",
        },
        "keywords": {"internet", "net", "user", "istifadə", "istifade"},
    },
    "exports": {
        "display_name": "Total Exports",
        "az": {"ixrac", "ixracat", "export", "exports", "məhsul ixracı", "məhsul ixra"},
        "en": {"exports", "export", "total exports", "goods export", "merchandise export"},
        # "məhsul"→"mesul" (not used much but safe), "ixracı"→"ixraci"
        "keywords": {"ixrac", "ixra", "ixr", "export", "mesul"},
    },
    "imports": {
        "display_name": "Total Imports",
        "az": {"idxrac", "idxracat", "idxr", "import", "imports"},
        "en": {"imports", "import", "total imports", "goods import", "merchandise import"},
        # "idxrac" is the normalized form of "idxrac" (Azerbaijani chars in import titles)
        "keywords": {"idxr", "import", "idxrac"},
    },
    "fdi_inflow": {
        "display_name": "Foreign Direct Investment Inflow",
        "az": {
            "xarici birbaşa investisiya",
            "xarici investisiya",
            "foreign direct investment",
        },
        "en": {"foreign direct investment", "fdi", "fdi inflow", "foreign investment", "direct investment"},
        # "xarici" çox yaygındır, yalnız "fdi" və "invest" istifadə et
        "keywords": {"fdi", "invest", "birbasa", "birbaşa", "investisiya"},
    },
    "life_expectancy": {
        "display_name": "Life Expectancy",
        "az": {
            "yaşama müddəti",
            "ömrün ortaca uzunluğu",
            "orta ömür müddəti",
            "yaşama müddətinin ortaca göstəricisi",
            "life expectancy",
        },
        "en": {"life expectancy", "life expectancy at birth", "average life expectancy"},
        "keywords": {"life", "expectancy", "ömr", "yaşam", "müddət"},
    },
    "co2_emissions": {
        "display_name": "CO2 Emissions Per Capita",
        "az": {"co2 emissiya", "karbon qazı emissiya", "co2", "emiya", "emissiya", "karbon", "karbon dioksit"},
        "en": {"co2 emissions", "carbon dioxide emissions", "carbon emissions", "co2 per capita", "greenhouse gas"},
        "keywords": {"co2", "carbon", "emiss", "karbon", "dioksit"},
    },
    "urban_population_pct": {
        "display_name": "Urban Population Percentage",
        "az": {"şəhər payı", "şəhər faizi", "urban population", "urbanization", "urban"},
        "en": {"urban population", "urbanization", "urban percentage", "city population"},
        "keywords": {"urban", "populat", "population"},
    },
    "mobile_subscriptions": {
        "display_name": "Mobile Subscriptions",
        "az": {"mobil abunə", "mobil rabitə", "mobil telefon", "mobil", "telefon abunə"},
        "en": {"mobile subscriptions", "mobile cellular", "cellular subscriptions", "mobile phone"},
        "keywords": {"mobile", "cellular", "mobil", "abun", "telefon"},
    },
    "researchers_per_million": {
        "display_name": "Researchers Per Million",
        "az": {"alimlər", "tədqiqatçılar", "alim", "elmi işçi", "tədqiqatçı", "researcher"},
        "en": {"researchers", "researcher per million", "scientists", "rd personnel"},
        "keywords": {"research", "alim", "tədqiq", "rd person"},
    },
    "maas": {
        "display_name": "Average Monthly Salary",
        "az": {"maaş", "maas", "əmək haqqı", "əmək haqq", "məvacib", "məvacib", "gəlir"},
        "en": {"salary", "wage", "average salary", "monthly salary", "income", "earnings"},
        "keywords": {"maas", "maaş", "mavacib", "maaj", "maaj", "wage", "salary", "gelir", "gəlir", "maas"},
    },
    "ev_qiymeti": {
        "display_name": "Housing Price Per Square Meter",
        "az": {"ev qiyməti", "ev qiymet", "mənzil qiyməti", "mənzil qiymet", "əmlak qiyməti", "əmlak qiymet"},
        "en": {"housing price", "apartment price", "home price", "property price", "real estate price", "house price per sqm"},
        "keywords": {"ev", "menzil", "manzil", "emlak", "emlak", "qiymet", "qiymet", "price", "apartment", "real estate"},
    },
    "ev_almaq": {
        "display_name": "Housing Affordability (30% rule)",
        "az": {"ev almaq", "ev alın", "mənzil almaq", "mənzil alın", "ipoteka", "credit", "30% yığım"},
        "en": {"buy a house", "buy apartment", "mortgage", "home buying", "30% savings", "housing savings", "affordable housing"},
        "keywords": {"ev", "menzil", "manzil", "ipoteka", "mortgage", "credit", "save", "yigim", "yigimi", "30", "save", "afford"},
    },
}


# ---------------------------------------------------------------------------
# Confidence tiers
# ---------------------------------------------------------------------------
CONFIDENCE_THRESHOLDS = {
    "very_strong": 0.95,  # exact indicator_code match, exact synonym
    "strong": 0.80,       # title/description contains display_name or synonym
    "ambiguous": 0.60,    # keyword match (partial)
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    """Bir namizəd konsept + onun confidence/reason."""
    concept_id: str
    confidence: float
    reason: str
    matched_text: str = ""


@dataclass
class ResolutionResult:
    """Bir catalogue_entry üçün tam nəticə."""
    entry_id: str
    title: str
    candidates: list[Candidate] = field(default_factory=list)
    best_concept: Optional[str] = None
    best_confidence: float = 0.0
    needs_llm: bool = False


# ---------------------------------------------------------------------------
# Matching strategies (in priority order)
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase + normalize Azerbaijani characters + strip punctuation.

    Handles Turkish/Istanbul Turkish: İ→i (not i+combining_dot),
    and all AZ chars: ə→e, ı→i, ö→o, ü→u, ş→s, ç→c, ğ→g.
    """
    if text is None:
        return ""
    # Decompose to NFKD and strip combining marks (fixes İ→i̇ issue)
    import unicodedata
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.lower().strip()
    # Azerbaijani character normalization
    text = text.replace("ə", "e").replace("ı", "i").replace("ö", "o")
    text = text.replace("ü", "u").replace("ş", "s").replace("ç", "c")
    text = text.replace("ğ", "g")
    # Strip punctuation, collapse whitespace
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _match_indicator_code(title: str, indicator_code: str) -> Optional[Candidate]:
    """Strategy 1: Keyword match on indicator_code.

    E.g. 'gdp-growth-rate-compared-to...' → 'gdp_growth'
    E.g. 'une_rt_a' → 'unemployment'
    E.g. 'sp.pop.totl' → 'population'
    E.g. 'ny.gdp.mktp.kd.zg' → 'gdp_growth'

    Must match at least 2 significant keywords (unless very specific).
    """
    code = (indicator_code or "").lower()

    # Common English stop words to filter out noise
    # NOTE: NEVER include concept keywords here (population, internet, etc.)
    stop_words = {
        "the", "and", "of", "in", "for", "by", "to", "with", "from",
        "is", "on", "at", "an", "or", "not", "via",
        "about", "into", "over", "after", "between", "under",
        "based", "using", "through", "during", "before",
        "main", "sources", "data", "statistics",
        "information", "services", "provide", "provided", "year",
        "annual", "monthly", "quarterly",
        "including", "such", "type", "types", "according",
        "comparing", "compared", "previous", "current",
        "present", "like", "within", "without", "each",
        "capital", "fixed", "investments", "investment",
        "expenditure", "paid", "sector", "sectors",
        "area", "areas", "country", "rate", "rates",
    }

    # Concept-specific keywords that are distinctive enough for single-match
    distinctive_keywords = {
        "unemployment", "ihsiz", "ihsizlik", "işsiz", "işsizlik",
        "jobless", "inflat", "inflasiya", "inflyasiya", "qiymet",
        "gdp", "gdm", "udm", "gdm",
        "fdi", "co2", "carbon", "emiss",
        "household", "meiset", "meiset",
        "population", "populat", "pop", "people", "inhabitant",
        "internet", "net", "user", "istifade",
        "export", "import", "idxr", "ixrac",
        "mobil", "mobile", "cellular",
        "urban", "seher",
    }

    best: Optional[Candidate] = None

    for concept_id, syn_info in SYNONYM_DICT.items():
        searchable = set()
        for kw in syn_info["keywords"]:
            if len(kw) > 2:
                searchable.add(kw.lower())

        if not searchable:
            continue

        # Tokenize by splitting on common separators (including dots for WB codes)
        tokens = set(re.split(r"[-_\s.]+", code))
        tokens = {t for t in tokens if t not in stop_words}

        matched = searchable & tokens
        if not matched:
            continue

        # Check if we have at least 2 matches, or 1 distinctive match
        distinctive_hits = matched & distinctive_keywords
        if len(matched) >= 2 or distinctive_hits:
            if len(matched) >= 3:
                conf = 0.95
            elif len(matched) == 2:
                conf = 0.85
            elif distinctive_hits:
                conf = 0.80
            else:
                conf = 0.70

            if best is None or conf > best.confidence:
                best = Candidate(
                    concept_id, conf,
                    f"indicator_code keywords: {', '.join(matched)}",
                )

    return best


def _match_display_name(title: str, description: str) -> Optional[Candidate]:
    """Strategy 2: Title/description contains exact display_name. Returns 0.92."""
    title_norm = _normalize(title or "")
    desc_norm = _normalize(description or "")
    combined = title_norm + " " + desc_norm

    for concept_id, syn_info in SYNONYM_DICT.items():
        display = _normalize(syn_info["display_name"])
        if len(display) > 5 and display in combined:
            return Candidate(concept_id, 0.92, f"display_name '{syn_info['display_name']}' found")

    return None


def _match_synonyms(title: str, description: str) -> list[Candidate]:
    """Strategy 3: Title/description contains any synonym (AZ or EN). Returns 0.85.

    Uses TOKEN matching (not substring) to avoid false positives like
    'mobil' matching 'avtomobil'. Splits on word boundaries.
    """
    title_norm = _normalize(title or "")
    desc_norm = _normalize(description or "")
    combined = title_norm + " " + desc_norm

    # Tokenize — split on any non-alphanumeric character
    tokens = set(re.split(r"[^a-z0-9]+", combined))

    candidates: list[Candidate] = []

    for concept_id, syn_info in SYNONYM_DICT.items():
        all_synonyms = set(list(syn_info["az"]) + list(syn_info["en"]))
        for syn in all_synonyms:
            syn_norm = _normalize(syn)
            # Must match as a whole token (not substring)
            if len(syn_norm) > 3 and syn_norm in tokens:
                candidates.append(Candidate(concept_id, 0.85, f"synonym '{syn}' found", matched_text=syn))

    return candidates


def _match_keywords(title: str, description: str) -> list[Candidate]:
    """Strategy 4: Token keyword match. Multiple keywords → stronger confidence (0.60-0.79)."""
    title_norm = _normalize(title or "")
    desc_norm = _normalize(description or "")
    combined = title_norm + " " + desc_norm

    # Tokenize
    tokens = set(re.split(r"[^a-z0-9]+", combined))

    candidates: list[Candidate] = []

    for concept_id, syn_info in SYNONYM_DICT.items():
        keywords = syn_info["keywords"]
        matched = [kw for kw in keywords if len(kw) > 2 and kw in tokens]
        if not matched:
            continue
        if len(matched) >= 3:
            conf = 0.79
        elif len(matched) == 2:
            conf = 0.70
        else:
            conf = 0.60

        candidates.append(Candidate(
            concept_id, conf, f"keywords match: {', '.join(matched)}",
            matched_text=", ".join(matched),
        ))

    return candidates


# ---------------------------------------------------------------------------
# Core resolution function
# ---------------------------------------------------------------------------

def resolve_catalogue_entry(
    entry: dict,
    concepts: dict[str, str] = None,
) -> ResolutionResult:
    """Resolve a single catalogue_entry to concept candidates.

    Args:
        entry: dict with keys: entry_id, title, description, indicator_code,
               dataset_id, source_id
        concepts: optional dict of concept_id → display_name to consider.

    Returns:
        ResolutionResult with candidates sorted by confidence (descending).
    """
    entry_id = entry.get("entry_id", "")
    title = entry.get("title") or ""
    description = entry.get("description") or ""

    result = ResolutionResult(entry_id=entry_id, title=title)
    all_candidates: list[Candidate] = []

    # Strategy 1: indicator_code match (highest priority)
    code_match = _match_indicator_code(title, entry.get("indicator_code", ""))
    if code_match:
        all_candidates.append(code_match)

    # Strategy 2: display_name match
    display_match = _match_display_name(title, description)
    if display_match:
        all_candidates.append(display_match)

    # Strategy 3: synonym match
    all_candidates.extend(_match_synonyms(title, description))

    # Strategy 4: keyword match (lowest confidence)
    all_candidates.extend(_match_keywords(title, description))

    # Deduplicate: keep highest confidence per concept
    best_per_concept: dict[str, Candidate] = {}
    for cand in all_candidates:
        if cand.concept_id not in best_per_concept or cand.confidence > best_per_concept[cand.concept_id].confidence:
            best_per_concept[cand.concept_id] = cand

    result.candidates = sorted(best_per_concept.values(), key=lambda c: -c.confidence)

    if result.candidates:
        best = result.candidates[0]
        result.best_concept = best.concept_id
        result.best_confidence = best.confidence
        # LLM gate: ambiguous range
        result.needs_llm = 0.60 <= best.confidence < CONFIDENCE_THRESHOLDS["strong"]

    return result


def resolve_catalogue_entries(
    entries: list[dict],
    concepts: dict[str, str] = None,
) -> list[ResolutionResult]:
    """Resolve a list of catalogue entries."""
    return [resolve_catalogue_entry(e, concepts) for e in entries]


# ---------------------------------------------------------------------------
# DB functions — seed concepts and write mappings
# ---------------------------------------------------------------------------

def seed_concepts(conn) -> int:
    """Seed CONCEPT_DISPLAY_NAMES into concepts table.

    Idempotent via ON CONFLICT. Does NOT write to concept_indicator_map.
    Does NOT call conn.commit(). Returns count of concepts inserted/updated.
    """
    from collector.db.repository import CONCEPT_DISPLAY_NAMES

    with conn.cursor() as cur:
        for concept_id, display_name in CONCEPT_DISPLAY_NAMES.items():
            cur.execute(
                """
                INSERT INTO concepts (concept_id, display_name)
                VALUES (%s, %s)
                ON CONFLICT (concept_id) DO UPDATE
                    SET display_name = EXCLUDED.display_name
                """,
                (concept_id, display_name),
            )
    return len(CONCEPT_DISPLAY_NAMES)


def seed_concept_mappings_from_synonyms(conn, confidence_threshold: float = 0.80) -> int:
    """Use synonym resolution to map catalogue entries → concepts.

    Writes mappings with confidence >= confidence_threshold.
    Does NOT overwrite existing higher-confidence mappings.
    Does NOT call conn.commit().
    Returns count of new mappings created.
    """
    import psycopg2.extras
    from collector.db.repository import link_concept_to_entry

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT entry_id, source_id, title, description, indicator_code, dataset_id "
            "FROM catalogue_entries ORDER BY entry_id"
        )
        entries = [dict(r) for r in cur.fetchall()]

    # Pre-filter: only entries not yet mapped
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT entry_id FROM concept_indicator_map")
        already_mapped = {row[0] for row in cur.fetchall()}

    new_mappings = 0

    for entry_dict in entries:
        if entry_dict["entry_id"] in already_mapped:
            continue

        result = resolve_catalogue_entry(entry_dict)
        for cand in result.candidates:
            if cand.confidence >= confidence_threshold:
                link_concept_to_entry(
                    conn, cand.concept_id, entry_dict["entry_id"],
                    cand.confidence, "rule_based",
                )
                new_mappings += 1
                break  # one mapping per entry is enough

    return new_mappings


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_resolver_report(
    conn,
    confidence_threshold: float = 0.80,
) -> dict:
    """Generate a comprehensive report of resolution results.

    Returns dict with stats suitable for logging/CLI output.
    """
    import psycopg2.extras
    from collector.db.repository import CONCEPT_DISPLAY_NAMES

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT entry_id, source_id, title, description, indicator_code, dataset_id "
            "FROM catalogue_entries ORDER BY entry_id"
        )
        entries = [dict(r) for r in cur.fetchall()]

    # Already mapped entries
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT entry_id FROM concept_indicator_map")
        already_mapped = {row[0] for row in cur.fetchall()}

    # Resolve all entries
    results = resolve_catalogue_entries(entries)

    total = len(results)
    mapped = 0
    unresolved = 0
    needs_llm = 0
    by_confidence = {"very_strong": 0, "strong": 0, "ambiguous": 0, "none": 0}
    by_concept = {}
    resolved_count = 0

    for r in results:
        if r.entry_id in already_mapped:
            mapped += 1

        if r.candidates:
            resolved_count += 1
            best = r.candidates[0]
            conf = best.confidence
            if conf >= 0.95:
                by_confidence["very_strong"] += 1
            elif conf >= 0.80:
                by_confidence["strong"] += 1
            elif conf >= 0.60:
                by_confidence["ambiguous"] += 1
                needs_llm += 1

            by_concept[best.concept_id] = by_concept.get(best.concept_id, 0) + 1
        else:
            unresolved += 1

    return {
        "total_entries": total,
        "already_mapped": mapped,
        "newly_resolved": resolved_count,
        "unresolved": unresolved,
        "needs_llm": needs_llm,
        "by_confidence": by_confidence,
        "by_concept": dict(sorted(by_concept.items(), key=lambda x: -x[1])),
        "concepts_in_dict": len(SYNONYM_DICT),
        "concepts_in_db": len(CONCEPT_DISPLAY_NAMES),
    }