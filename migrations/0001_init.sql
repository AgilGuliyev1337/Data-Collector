-- Mərhələ 1: PostgreSQL təməli.

-- Mənbələrin kataloqu (əvvəlcədən tanınan "static" + gələcək
-- SourceDiscovery tərəfindən tapılacaq "discovered" sətirlər üçün ortaq yer).
CREATE TABLE sources (
    id                TEXT PRIMARY KEY,
    type              TEXT NOT NULL,
    base_url          TEXT,
    discovery_method  TEXT NOT NULL DEFAULT 'static'
                      CHECK (discovery_method IN ('static', 'discovered')),
    priority_tier     INT,
    trust_level       TEXT NOT NULL DEFAULT 'official'
                      CHECK (trust_level IN ('official', 'aggregated', 'community', 'unverified_web')),
    enabled           BOOLEAN NOT NULL DEFAULT true,
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- CKAN portallarından toplanan dataset metadata-sı (köhnə SQLite sxemanın portu).
CREATE TABLE datasets (
    source_id     TEXT NOT NULL REFERENCES sources(id),
    dataset_id    TEXT NOT NULL,
    name          TEXT,
    title         TEXT,
    org           TEXT,
    license       TEXT,
    license_id    TEXT,
    modified      TEXT,
    tags          JSONB NOT NULL DEFAULT '[]'::jsonb,
    groups_       JSONB NOT NULL DEFAULT '[]'::jsonb,
    resources     JSONB NOT NULL DEFAULT '[]'::jsonb,
    collected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, dataset_id)
);

-- Hər CLI çağırışının audit izi (provenance əsası: "bu rəqəm hansı
-- run-dan gəldi" sualı buna FK ilə cavablanır).
CREATE TABLE collection_runs (
    id               BIGSERIAL PRIMARY KEY,
    command          TEXT NOT NULL,
    params           JSONB NOT NULL DEFAULT '{}'::jsonb,
    status           TEXT NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'success', 'failed')),
    records_collected INT NOT NULL DEFAULT 0,
    error_message    TEXT,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ
);

-- Makro göstərici sətirləri (World Bank / Eurostat / IMF və s.).
-- Append-only: eyni (concept, country, period) üçün yeni sətir revizə
-- kimi əlavə olunur, üzərinə yazılmır (tarixçə saxlanılır).
CREATE TABLE facts (
    id              BIGSERIAL PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES sources(id),
    run_id          BIGINT REFERENCES collection_runs(id),
    concept         TEXT NOT NULL,
    indicator_code  TEXT,
    country         TEXT,
    iso3            TEXT,
    period          TEXT NOT NULL,
    period_year     INT,
    value           NUMERIC,
    unit            TEXT,
    collected_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_facts_concept_iso3_year ON facts (concept, iso3, period_year);
CREATE INDEX idx_facts_run ON facts (run_id);

-- CBR-ın gündəlik FX snapshot-u. `facts`-a sığmır, çünki burada
-- indicator/country oxu yoxdur və dəyər "revisə" olunmur - hər gün üçün
-- bir dəfəlik snapshot-dur, ona görə (currency, date) üzrə upsert edilir.
CREATE TABLE fx_rates (
    id             BIGSERIAL PRIMARY KEY,
    source_id      TEXT NOT NULL REFERENCES sources(id),
    run_id         BIGINT REFERENCES collection_runs(id),
    currency_code  TEXT NOT NULL,
    currency_name  TEXT,
    nominal        INT,
    value_rub      NUMERIC NOT NULL,
    rate_date      DATE NOT NULL,
    collected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (currency_code, rate_date)
);
