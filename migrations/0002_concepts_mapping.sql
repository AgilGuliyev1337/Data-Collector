-- Mərhələ 2B: Concepts, Catalogue, Concept→Indicator Mapping.
--
-- concepts        — abstrakt göstərici anlayışı (məs. "gdp_per_capita")
-- catalogue_entries — hər source-da real indicator/dataset (metadata ilə)
-- concept_indicator_map — konsept ↔ catalogue_entry (N:N, confidence ilə)

-- Konseptlər (abstrakt göstərici anlayışları)
CREATE TABLE concepts (
    concept_id    TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL
);

-- Data Catalogue: hər source-da hər indikator üçün bir sətir
CREATE TABLE catalogue_entries (
    entry_id          TEXT PRIMARY KEY,
    source_id         TEXT NOT NULL REFERENCES sources(id),
    dataset_id        TEXT,
    indicator_code    TEXT NOT NULL,
    title             TEXT,
    description       TEXT,
    unit              TEXT,
    frequency         TEXT,
    country_coverage  TEXT[] DEFAULT '{}',
    time_coverage_start INT,
    time_coverage_end   INT,
    methodology_note  TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_id, indicator_code)
);

-- Konsept ↔ Catalogue mapping (bir konseptin bir source-da birdən çox
-- candidate indicator-ı ola bilər; confidence ilə seçim edilir)
CREATE TABLE concept_indicator_map (
    concept_id      TEXT NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    entry_id        TEXT NOT NULL REFERENCES catalogue_entries(entry_id) ON DELETE CASCADE,
    confidence      REAL NOT NULL DEFAULT 0.8
                    CHECK (confidence >= 0 AND confidence <= 1),
    match_type      TEXT NOT NULL DEFAULT 'rule_based'
                    CHECK (match_type IN ('rule_based', 'llm_confirmed', 'manual')),
    PRIMARY KEY (concept_id, entry_id)
);

CREATE INDEX idx_cim_concept ON concept_indicator_map (concept_id);
CREATE INDEX idx_cim_source ON catalogue_entries (source_id);