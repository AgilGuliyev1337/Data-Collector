# Data Discovery + Collection Platforması — Tam Arxitektura Təhlili

*Mövcud layihənin (`last_data_.zip`) analizi əsasında hazırlanıb*

---

## 1. Mövcud Layihənin Analizi

### Nə var?

Layihə 9 fayldan ibarətdir və indiki vəziyyətdə **iki paralel alt-sistem** kimi işləyir:

1. **CKAN collector** (`ckan_source.py` + `storage.py` + `cli.py --run`) — açıq-data portallarından (opendata.az, data.gov) dataset **metadata**sını (title, license, tags, resources siyahısı) toplayıb SQLite/CSV-ə yazır. Faktiki data faylını (CSV/XLSX) yükləmir, yalnız kataloqu indeksləyir.
2. **Makro-müqayisə modulları** (`worldbank_source.py`, `eurostat_source.py`, `imf_source.py`, `cbr_source.py`) — bunlar `collect()` axınına deyil, birbaşa `cli.py --compare` / `--cross-check` / `--cbr-snapshot` komandalarına bağlıdır və nəticəni ekrana/CSV-yə çap edir, saxlamır.

Bu iki hissə **eyni storage-ı, eyni data modelini, eyni "indicator" konsepsiyasını paylaşmır**. Bu, sizin tələb etdiyiniz "requirement → catalogue → source discovery → collection → normalization" zəncirinin **hələ mövcud olmadığı** deməkdir — indiki tool discovery yox, **iki ayrı əl ilə işlədilən data-çəkmə skripti** toplusudur.

### Nə yaxşıdır (saxlanmalıdır)

- **`CKANSource` abstraksiyası** (`search/metadata/fetch/validate`-ə çox yaxın forma) doğru istiqamətdədir — bir kodla bir neçə CKAN portalı üçün işləyir (opendata.az, data.gov). Bu, sizin "universal source adapter" ideyasının artıq işləyən bir nümunəsidir.
- **Rate-limiting, license-filtering, User-Agent** kimi "məsuliyyətli data toplama" detalları real production təcrübəsini göstərir — atılmamalıdır.
- **Konsept-səviyyəli mapping** (`config.yaml → concepts: gdp_growth → {world_bank, eurostat, imf}`) — bu, sizin "Semantic Matching" istəyinizin **primitiv, statik versiyasıdır**. Fikir doğrudur, icra hardcoded-dır.
- **README-də açıq etiraf**: Eurostat/IMF kodlarının "ilkin təxmin" olduğu, əl ilə yoxlanmalı olduğu qeyd olunub. Bu, sizin problemi (hardcode edilmiş indicator-lərin kövrək olması) artıq öz-özünə sənədləşdirib — layihə müəllifi problemi hiss edib, sadəcə həllini hələ qurmayıb.
- **Source müxtəlifliyi**: 4 fərqli API strukturu (REST+JSON, CKAN action API, SDMX-JSON, JSON-stat) artıq işlənib — bu, gələcək adapter dizaynı üçün faydalı "real-dünya nümunələri" bazasıdır.

### Nə zəifdir

| Problem | Təfərrüat |
|---|---|
| **Import path bugı** | `cli.py` `from collector.ckan_source import ...` yazır, amma zip-də `collector/` qovluğu yoxdur — bütün fayllar kök qovluqdadır. Hazırkı halda `cli.py` işə düşməyəcək (ya qovluq strukturu düzəldilməli, ya import-lar). |
| **Hardcoded indicator-lər** | `COMMON_INDICATORS` (15 göstərici) və `concepts:` bölməsi əl ilə yazılıb. Sizin əsas tələbiniz — "yüzlərlə mövzu üçün miqyaslana bilməmək" — məhz budur. |
| **Discovery yoxdur** | Sistem "house affordability" kimi sərbəst mətni heç bir indicator-ə bağlaya bilmir. Yalnız əvvəlcədən tanınan qısa ad və ya dəqiq kod qəbul edir. |
| **Vahid data modeli yoxdur** | CKAN axını `datasets` cədvəlinə (kataloq metadata), makro-müqayisə isə ayrıca CSV-lərə yazır. Ortaq "fact table" (ölkə, indicator, il, dəyər, source, provenance) yoxdur. |
| **Provenance yoxdur** | Hesab nəticələri (`--compare`) heç bir yerdə saxlanmır, yalnız ekrana çap olunur. Hansı API sorğusunun nəticəsi olduğu izlənmir. |
| **Validation demək olar yoxdur** | `value is None` yoxlamasından başqa heç bir data-keyfiyyət yoxlaması yoxdur (vahid/valyuta qarışması, anomaliya, duplikat və s. — sizin tələb etdiyiniz heç biri icra olunmayıb). |
| **Derived metrics yoxdur** | House affordability kimi formula-based hesablama modulu yoxdur. |
| **Source ranking yoxdur** | Eyni konsept bir neçə mənbədən gələndə (`cross_check`) sadəcə yan-yana göstərilir, hansının "daha etibarlı" olduğu qərarlaşdırılmır. |

### Nəyi saxlamaq, nəyi dəyişmək

**Saxla:** `CKANSource`-un adapter forması, rate-limit/license fəlsəfəsi, `WorldBankSource`, `EurostatSource`, `IMFSource`, `CBRSource`-un HTTP/parsing məntiqi (bunlar "Collector" qatının konkret implementasiyaları kimi olduğu kimi yeni arxitekturaya köçürülə bilər).

**Dəyişdir:** `config.yaml`-dakı statik `concepts:` bölməsini **Data Catalogue**-a (aşağıda), storage-ı vahid **fact-based schema**-ya, `compare`/`cross_check` funksiyalarını **Collection Plan → Collector → Validator → Recipe Engine** zəncirinə.

---

## 2. AI-siz Avtomatlaşdırma Analizi — Variant A / B / C Müqayisəsi

Bu, bütün arxitekturanın açarıdır, ona görə konkret olacağam.

### Tapşırığı 4 alt-mərhələyə bölək

| Alt-mərhələ | Nə edir | AI-siz mümkündürmü? |
|---|---|---|
| **(a) Requirement → konsept siyahısı** | "House affordability" → `[income, house_price, rent, mortgage_rate]` | ⚠️ Qismən — sabit fikir xəritəsi (concept ontology) ilə 70-80% hallarda AI-siz mümkündür, amma **yeni, əvvəllər görülməmiş mövzu** üçün AI lazımdır |
| **(b) Konsept → candidate indicator-lər** | "income" → World Bank-də 6, Eurostat-da 4 uyğun indicator tap | ✅ Tam deterministic — metadata index + full-text/vektor axtarış |
| **(c) Candidate-lər arasından seçim** | 10 candidate arasından ən uyğun 1-2-ni seç | ⚠️ Qarışıq — rule-based scoring çoxunu həll edir, amma **ambiguous/ziddiyyətli hallarda** insan səviyyəli mühakimə lazımdır |
| **(d) Collection → normalization → validation → derived metrics** | API çağırışı, vahid çevirmə, hesablama | ✅ Tam deterministic — bunu AI-ya HEÇ VAXT vermək olmaz (rəqəm uydurma riski) |

### Variant A — Tam AI Agent

**Nə edir:** LLM hər addımı (requirement parsing-dən API seçiminə qədər) sərbəst reasoning ilə edir.

**Üstünlük:** Tətbiq sürəti sürətlidir (POC üçün), yeni/qəribə mövzularda çevikdir.

**Çatışmazlıq:**
- Hər sorğu üçün böyük model çağırışı → **xərc xətti sayına görə xətti artır** (100 source, 500 indicator ilə açıq-uçuq olur)
- **Reproducibility yoxdur** — eyni sual iki dəfə soruşulanda fərqli indicator seçilə bilər
- **Explainability zəifdir** — "niyə Eurostat seçildi" sualına LLM-in cavabı hallüsinasiya ola bilər
- Sizin öz tələbiniz ("AI rəqəm uydurmasın, hesablamasın") ilə ziddiyyət təşkil edir, çünki Variant A-da adətən AI həm seçir, həm interpretasiya edir

**Qiymətləndirmə: sizin use-case üçün YARARSIZDIR** — provenance/reproducibility tələbiniz ilə uyuşmur.

### Variant B — Tam AI-siz (deterministic)

**Komponentlər:**
- **Metadata catalogue** — struktur cədvəl (bax bölmə 4)
- **Full-text search** (Postgres `tsvector` və ya Elasticsearch) — açar sözlərlə uyğunlaşdırma
- **Taxonomy/ontology** — əl ilə qurulmuş konsept ağacı: `living_standards → income → {gross_income, net_income, disposable_income, median_wage}`
- **Synonym dictionary** — "salary" = "wage" = "earnings" (çoxdilli: AZ/EN/RU/DE)
- **Rule-based matching** — unit uyğunluğu (USD/EUR/AZN), frequency uyğunluğu (annual/monthly), country coverage yoxlaması
- **Source priority table** — sabit sıra (National Stats > Eurostat > OECD > WB > IMF)

**Nə qədər avtomatlaşdırıla bilər?**

Real təcrübəyə əsaslanaraq (oxşar sistemlər: DBpedia Spotlight-sız entity linking, klassik data-catalogue axtarış motorları):
- **Sabit, əvvəlcədən tanınan konseptlər üçün (siz artıq 50-100 konsept təyin etsəniz) — ~85-90% avtomatlaşdırıla bilər.** Sinonim lüğəti + taxonomy + rule-based scoring kifayət qədər yaxşı işləyir, xüsusən makro-iqtisadi göstəricilər kimi nisbətən "qapalı dünya" mövzularda.
- **Tamamilə yeni, gözlənilməz sorğular üçün (məs. "purchasing power of a barista in 2030 scenarios") — 30-50%** uğur nisbəti, çünki taxonomy-də olmayan konsept dekompozisiyası tələb olunur.

**Çatışmazlıq:** Sinonim lüğəti və taxonomy-ni əl ilə saxlamaq **linqvistik miqyaslanma problemi**dir — 3 dil (AZ/EN/RU, bəlkə DE/FR) və yüzlərlə konsept üçün bu, faktiki olaraq kiçik bir NLP layihəsinə çevrilir. Bu da "AI-siz" olsa da, mühəndislik xərci baxımından ucuz deyil.

**Qiymətləndirmə: MVP və "well-known concepts" üçün əla, amma "istənilən yeni mövzu"nu iddia edən sizin uzunmüddətli məqsədiniz üçün tək başına kifayət deyil.**

### Variant C — Hybrid (tövsiyə olunan)

Sizin öz təklifiniz doğrudur və mən onu **təsdiqləyirəm**, konkret sərhədlərlə:

```
Cheap deterministic layer (HƏR SORĞUDA işləyir, $0 AI xərci):
  1. Requirement-dəki açar sözləri çıxar (keyword extraction — spaCy/regex, AI-siz)
  2. Taxonomy-dən candidate konseptləri tap (exact/fuzzy match)
  3. Metadata catalogue-da BM25/full-text axtarış
  4. pgvector ilə semantic search (embeddings — bu, LLM CHAT DEYİL, ucuz embed
     modeldir, "AI" sayılsa da xərci 1000x ucuzdur)
  5. Rule-based filtering: unit, frequency, country coverage, source priority

  ↓ Nəticə: hər konsept üçün top-3-5 candidate indicator, confidence score ilə

Yalnız bu şərtlərdən biri olduqda LLM işə düşür:
  - Top candidate-in confidence score-u threshold-dan aşağıdırsa (məs. <0.75)
  - Bir neçə candidate arasında score fərqi çox kiçikdirsə (ambiguity)
  - Taxonomy-də konsept ümumiyyətlə tapılmayıbsa (yeni mövzu → concept decomposition lazımdır)
  - Mənbələr arası ziddiyyət varsa (məs. WB deyir 5.2%, Eurostat deyir 3.1% — hansı
    metodologiya fərqindən, hansı səhvdən)
```

**Niyə bu düzgündür:** Sizin 3 əsas tələbiniz (aşağı xərc, explainability, AI-nin rəqəm hesablamaması) yalnız bu modeldə eyni anda ödənilir. Deterministic layer sorğuların əksəriyyətini (təxmini 70-85%, konsept artdıqca artır) heç bir AI çağırışı olmadan həll edir; LLM yalnız "insan da tərəddüd edəcək" hallarda işə düşür — bu da onun cavabını **daha etibarlı** edir, çünki dar, konkret sual üzərində işləyir ("bu 3 candidate-dan hansı 'average salary'-ə daha yaxındır" — geniş açıq sual deyil).

**Konkret faiz təxmini** (analoji sistemlərə əsasən — dəqiq rəqəm deyil, ssenari):

| Mərhələ | Deterministic-lə həll % |
|---|---|
| Well-known makro-iqtisadi konseptlər (GDP, income, unemployment və s. — sizin ilk 50-100 use-case) | ~90% |
| Az tanınan/niş konseptlər | ~50-60% |
| Tamamilə yeni domain (məs. gələcəkdə "təhsil keyfiyyəti" mövzusuna keçsəniz) | ~30% (ilk dəfə) → taxonomy genişləndikcə artır |

---

## 3. Tövsiyə Edilən Arxitektura

Sizin təklif etdiyiniz axın düzgün istiqamətdədir, mən onu bir neçə yerdə **ayırıram və sərtləşdirirəm** ki, deterministic/AI sərhədi kod səviyyəsində də aydın olsun:

```
┌─────────────────────────────────────────────────────────────────┐
│  1. USER REQUIREMENT (təbii dil sorğusu)                         │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. REQUIREMENT PARSER  [DETERMINISTIC + opsional LLM]           │
│     - Keyword/entity extraction                                  │
│     - Ölkə/region tanıma (regex + gazetteer)                     │
│     - Zaman aralığı tanıma                                       │
│     - Əgər aydın deyilsə → LLM concept decomposition             │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. CONCEPT RESOLVER  [DETERMINISTIC: taxonomy + synonym lookup]  │
│     "house affordability" → [income, house_price, rent, ...]     │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. DATA CATALOGUE SEARCH  [DETERMINISTIC: full-text + vector]    │
│     Hər konsept üçün → candidate indicator-lər (source, dataset, │
│     unit, coverage, confidence score)                            │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
                    ┌────────┴────────┐
                    ▼                 ▼
        confidence YÜKSƏK      confidence AŞAĞI / ambiguous
                    │                 │
                    ▼                 ▼
        ┌───────────────────┐  ┌─────────────────────────────┐
        │ 5a. RULE-BASED     │  │ 5b. LLM DISAMBIGUATION       │
        │  RANKING           │  │  (kiçik, dar sorğu — yalnız  │
        │  (source priority, │  │  top-N candidate arasından   │
        │  unit match)       │  │  seçim, YENİ data uydurmur)  │
        └─────────┬──────────┘  └───────────────┬───────────────┘
                   └────────────┬─────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. COLLECTION PLAN GENERATOR  [DETERMINISTIC]                   │
│     Seçilmiş indicator-lərdən JSON plan (bax bölmə 9)             │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  7. DATA COLLECTOR  [DETERMINISTIC: Source Adapter-lər]           │
│     WorldBankSource / EurostatSource / IMFSource / CKANSource /   │
│     ... (mövcud kod bura köçür)                                  │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  8. NORMALIZATION  [DETERMINISTIC]                                │
│     Vahid/valyuta çevirmə, tarix formatı, ISO kod unifikasiyası   │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  9. VALIDATION ENGINE  [DETERMINISTIC]                            │
│     Missing/duplicate/anomaly/unit-mismatch yoxlamaları           │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  10. METRIC / RECIPE ENGINE  [DETERMINISTIC: Python formula]      │
│      house_affordability = house_price / annual_net_income       │
│      (AI YALNIZ formula TÖVSİYƏ edir, hesablamır)                 │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  11. FINAL DATASET + PROVENANCE LOG  [DETERMINISTIC storage]      │
└───────────────────────────┬───────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  12. VISUALIZATION / LinkedIn Export  [DETERMINISTIC + opsional AI│
│      copywriting köməyi mətn üçün]                                │
└─────────────────────────────────────────────────────────────────┘
```

**Sizin təklifinizdən əsas fərq:** Mən "Semantic Search" və "Source Ranking"i **iki ayrı, ardıcıl mərhələ** kimi saxlayıram, amma aralarına **explicit bir "confidence gate"** əlavə edirəm — bu, AI-nin nə vaxt işə düşəcəyini kodun özündə (if/else, LLM prompt-unda deyil) qərarlaşdırır. Bu, xərci və reproducibility-ni idarə edən əsas mexanizmdir.

---

## 4. Data Catalogue Dizaynı

### Verilənlər bazası seçimi

| Seçim | Qiymətləndirmə |
|---|---|
| **PostgreSQL + pgvector** | ✅ **Tövsiyə olunur.** Struktur metadata (unit, frequency, coverage) üçün relational cədvəllər + embedding sütunu eyni bazada. Ayrıca infrastruktur lazım deyil. `tsvector` ilə full-text axtarış da pulsuz gəlir (Elasticsearch-ə ehtiyac qalmır). |
| Elasticsearch/OpenSearch | Yalnız yüz minlərlə dataset və mürəkkəb faceted-search UI lazım olanda haqlanır. Sizin MVP-də (100-larla source, minlərlə indicator) overkill və əlavə operativ yükdür. |
| Qdrant (təkcə vector DB) | Yalnız vector axtarış üçün əladır, amma struktur metadata üçün ayrıca DB tələb edir — iki sistem sinxronlaşdırmaq lazım gəlir. pgvector bunu tək bazada həll edir. |
| SQLite (mövcud) | MVP-nin ilk 1-2 həftəsi üçün kifayətdir, amma vector axtarış və concurrent yazma ilə tez məhdudlaşır. |

**Nəticə:** MVP-də hətta SQLite ilə başlaya bilərsiniz (kod dəyişməz qalır), amma **V2-yə keçəndə Postgres+pgvector-a köçmək** tövsiyə olunur — bu, həm struktur, həm semantic axtarışı tək yerdə saxlayır və sizin "sadə və ucuz" tələbinizi ödəyir (Supabase/Neon kimi pulsuz-tier Postgres+pgvector hosting mövcuddur).

### Schema (əsas cədvəllər)

```sql
-- Mənbələr (World Bank, Eurostat, opendata.az və s.)
CREATE TABLE sources (
    source_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,          -- 'worldbank_api' | 'ckan' | 'sdmx' | 'jsonstat' | ...
    base_url        TEXT,
    priority_tier   INT,                     -- 1=national stats, 2=eurostat, 3=oecd, 4=wb, 5=imf, 6=other
    requires_key    BOOLEAN DEFAULT FALSE,
    reliability     TEXT,                    -- 'official' | 'aggregated' | 'community'
    license_note    TEXT
);

-- Data kataloqu — hər indicator/dataset üçün bir sətir
CREATE TABLE catalogue_entries (
    entry_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id           TEXT REFERENCES sources(source_id),
    dataset_id          TEXT,               -- source-daxili ID (məs. "une_rt_a")
    indicator_code       TEXT,               -- (məs. "SL.UEM.TOTL.ZS")
    name                 TEXT NOT NULL,
    description          TEXT,
    unit                 TEXT,               -- 'USD', 'percent', 'people', ...
    frequency            TEXT,               -- 'annual' | 'quarterly' | 'monthly' | 'daily'
    country_coverage      TEXT[],             -- ISO3 kodlar massivi
    time_coverage_start   INT,
    time_coverage_end     INT,
    dimensions            JSONB,              -- əlavə ölçülər (sektor, yaş qrupu və s.)
    api_endpoint_template TEXT,
    methodology_note      TEXT,
    last_indexed_at        TIMESTAMPTZ,
    reliability_score      REAL,               -- 0-1, source_priority + freshness-dən hesablanır
    license                TEXT,

    -- semantic search üçün
    embedding             VECTOR(1536),        -- name+description-dan hesablanmış embedding
    search_text            TSVECTOR             -- full-text axtarış üçün
);

CREATE INDEX ON catalogue_entries USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX ON catalogue_entries USING GIN (search_text);

-- Konsept taxonomy (əl ilə/yarı-avtomatik qurulur)
CREATE TABLE concepts (
    concept_id      TEXT PRIMARY KEY,        -- 'net_income', 'house_price', ...
    parent_concept  TEXT REFERENCES concepts(concept_id),
    display_name    TEXT,
    synonyms        TEXT[],                  -- ['salary', 'wage', 'earnings']
    synonyms_az     TEXT[],
    synonyms_ru     TEXT[]
);

-- Konsept ↔ catalogue əlaqəsi (bir konsept bir neçə indicator-ə uyğun ola bilər)
CREATE TABLE concept_indicator_map (
    concept_id      TEXT REFERENCES concepts(concept_id),
    entry_id        UUID REFERENCES catalogue_entries(entry_id),
    match_type      TEXT,     -- 'exact' | 'rule_based' | 'llm_confirmed'
    confidence      REAL,
    PRIMARY KEY (concept_id, entry_id)
);
```

Bu schema, mövcud `worldbank_source.py`-dakı `COMMON_INDICATORS` lüğətini və `config.yaml`-dakı `concepts:` bölməsini **kod-daxili sabitdən verilənlər bazası sətirlərinə** çevirir — yəni yeni indicator əlavə etmək artıq kod deploy etmək deyil, kataloqu yeniləmək (indexer job-u işlətmək) olur.

---

## 5. Source Adapter Sistemi

Sizin təklif etdiyiniz interfeys düzgündür, mən onu bir az genişləndirirəm ki, catalogue indexləmə də daxil olsun:

```python
from abc import ABC, abstractmethod

class DataSource(ABC):
    source_id: str

    @abstractmethod
    def discover_catalogue(self) -> list[dict]:
        """
        Bu mənbədəki BÜTÜN mövcud dataset/indicator-lərin metadatasını
        qaytarır (fetch etmədən) — catalogue_entries cədvəlinə yazılır.
        Bu, 'search()'dən fərqlidir: search live sorğu, bu isə
        pre-indexing üçündür (adətən cron ilə gecə işləyir).
        """

    @abstractmethod
    def fetch(self, indicator_code: str, countries: list[str],
              start: int, end: int) -> list[dict]:
        """Konkret data çəkir. Qaytarılan format Normalization qatının
        gözlədiyi ortaq 'raw record' formatına uyğun olmalıdır."""

    @abstractmethod
    def validate_connection(self) -> bool:
        """Health-check — API əlçatandırmı, rate-limit statusu."""

    def rate_limit_per_sec(self) -> float:
        return 2.0  # default, hər adapter override edə bilər
```

Mövcud `WorldBankSource`, `EurostatSource`, `IMFSource`, `CBRSource`, `CKANSource` bu interfeysə **minimal dəyişikliklə** uyğunlaşdırıla bilər — onların HTTP/parsing məntiqi artıq yazılıb, sadəcə `discover_catalogue()` metodu əlavə olunmalıdır (məs. `WorldBankSource.discover_catalogue()` → `/v2/indicator?per_page=20000` endpoint-inə sorğu göndərib bütün indicator-ləri qaytarır — bu API artıq mövcuddur, sadəcə istifadə olunmayıb).

**Qiymətləndirmə sizin sualınıza:** Bəli, bu abstraksiya düzgündür, amma `search()` termini qeyri-müəyyəndir — mən onu **iki fərqli metoda ayırmağı** tövsiyə edirəm (`discover_catalogue` — bulk/offline, `fetch` — targeted/online), çünki bunlar fərqli tezlikdə (birincisi gündə/həftədə bir, ikincisi hər sorğuda) və fərqli xərc profilində işləyir.

---

## 6. Indicator Discovery — Konkret Axın

Nümunə: user "average salary" yazır.

1. **Concept Resolver**: `synonyms` cədvəlində "average salary" → tam uyğunluq yoxdur, amma "salary" → `synonyms` massivində olan `net_income` konseptinə fuzzy-match olunur (Levenshtein/trigram, `pg_trgm` extension).
2. **Catalogue Search**: `concept_indicator_map`-də `net_income`-ə bağlı sətirlər var? Varsa — birbaşa candidate siyahısı. Yoxdursa, `catalogue_entries`-də hibrid axtarış:
   - `search_text @@ to_tsquery('salary | wage | earnings')` (full-text)
   - `embedding <-> query_embedding` (vector, cosine distance) — "average salary" ifadəsinin embedding-i ilə bütün catalogue embedding-ləri arasında
   - Nəticələr birləşdirilir (reciprocal rank fusion və ya sadə weighted sum)
3. **Rule filtering**: Nəticələr arasından `unit` sahəsi "percent" olanlar (məs. səhvən "unemployment rate" gəlibsə) kənarlaşdırılır, çünki "salary" konsepti üçün gözlənilən unit-lər `{USD, EUR, AZN, local_currency}`-dir, `percent` deyil. Bu, sizin qeyd etdiyiniz "GDP per capita-nı salary kimi seçməsin" tələbini məhz bu addım həll edir.
4. **Confidence score hesablanır**: `0.4×text_match + 0.4×vector_similarity + 0.2×unit_match`.
5. **Threshold yoxlanır**: Top candidate `confidence >= 0.75`-dirsə → avtomatik seçilir, source priority ilə sıralanır. Aşağıdırsa → top-5 candidate LLM-ə göndərilir: *"Bu 5 indicator arasından 'average salary' tələbinə ən uyğun olanı seç və niyə seçdiyini izah et."* — bu, LLM-in **açıq sual** yox, **qapalı seçim** sualı olması səbəbindən daha etibarlıdır.

---

## 7. Semantic Search — Lazımdırmı?

**Bəli, lazımdır, amma "AI agent" mənasında yox.**

Embedding-lər (məs. `text-embedding-3-small` və ya açıq mənbəli `bge-small`) **LLM chat çağırışı deyil** — onlar bir dəfə hesablanır (indexləmə zamanı) və axtarış zamanı sadəcə vektor məsafəsi hesablanır (DB daxilində, $0 marginal xərc). Bunu "AI" adlandırmaq bir az çaşdırıcıdır — daha doğrusu **statistik NLP alətidir**, sizin "AI agent hər sorğuda düşünsün" narahatlığınıza aid deyil.

**Niyə full-text kifayət etmir:** "house affordability" sorğusu üçün catalogue-da "housing cost burden" adlı indicator ola bilər — heç bir ortaq söz yoxdur, amma semantik cəhətdən eynidir. Yalnız keyword-based axtarış bunu tapmaz, embedding tapar.

**Texnologiya:** `pgvector` (Postgres extension) + ucuz embedding modeli (embedding çağırışı LLM chat çağırışından ~50-100x ucuzdur, həm də cache-lənə bilər, çünki catalogue nadir dəyişir).

---

## 8. AI Layer — Model Səviyyələri

| Tapşırıq | Nə vaxt işə düşür | Tövsiyə olunan model səviyyəsi |
|---|---|---|
| Requirement-də konsept tapılmayıb (yeni domain) | Nadir (aylıq bir neçə dəfə, yeni mövzu əlavə edəndə) | Böyük/güclü model (dəqiqlik vacibdir, xərc əhəmiyyətsizdir, çünki nadir işləyir) |
| Top-N candidate arasından seçim (ambiguity) | Hər "aşağı confidence" halında | Kiçik/ucuz model kifayətdir — qapalı, strukturlaşdırılmış seçim tapşırığıdır (JSON output, "A/B/C/D-dən birini seç") |
| Source-lar arası ziddiyyət izahı | Nadir, yalnız cross-check zamanı fərq aşkarlananda | Orta model, izahat mətn keyfiyyəti üçün bir az daha yaxşı olmalıdır |
| LinkedIn üçün mətn/başlıq yazma | User tələb edəndə | Orta/böyük model (yaradıcılıq tələb olunur) |

**Böyük model hər request-də İŞLƏMƏMƏLİDİR.** Yalnız "ambiguity gate"dən keçən hallarda çağırılmalıdır. Bu, sizin Variant C təklifinizin dəqiq icrasıdır — arxitektura səviyyəsində bunu **kodda if/else şərti** kimi qoymaq lazımdır, LLM-in özünə "əgər əminsənsə cavab ver, deyilsə soruş" deməklə yox (bu etibarsızdır, çünki LLM öz confidence-ni səhv qiymətləndirə bilər).

---

## 9. Collection Plan — JSON Schema

```json
{
  "plan_id": "uuid",
  "created_at": "2026-08-12T10:00:00Z",
  "requirement_text": "Avropa, ABŞ, Azərbaycan və MDB-də yaşayış səviyyəsi müqayisəsi",
  "resolution_method": "hybrid",
  "items": [
    {
      "concept_id": "net_income",
      "selected_entry_id": "uuid-of-catalogue-entry",
      "source_id": "eurostat",
      "dataset_id": "sdg_08_10",
      "indicator_code": "sdg_08_10",
      "unit": "EUR",
      "countries": ["DE", "FR", "AZ", "US", "KZ"],
      "time_range": [2019, 2026],
      "selection_reason": {
        "method": "rule_based",
        "confidence": 0.91,
        "explanation": "definition uyğunluğu 96%, country coverage tam, annual frequency uyğun, official source"
      }
    }
  ],
  "derived_metrics_requested": ["house_affordability", "years_to_buy"],
  "status": "pending_collection"
}
```

Bu plan **Collector**-ə göndərilməzdən əvvəl user/log tərəfindən review edilə bilər — bu sizin "explainable" tələbinizi arxitektur səviyyəsində təmin edir, çünki collection başlamazdan əvvəl artıq "niyə bu indicator seçildi" cavabı mövcuddur.

---

## 10. Validation Engine

Deterministic, qayda-əsaslı, Python-da yazılan yoxlama zənciri:

```python
class ValidationRule(ABC):
    def check(self, record: dict) -> ValidationResult: ...

# Nümunə qaydalar:
class UnitConsistencyRule(ValidationRule): ...      # USD/EUR qarışmasın
class RangeSanityRule(ValidationRule): ...           # unemployment 0-100% aralığında olmalı
class DuplicateRule(ValidationRule): ...             # (source, indicator, country, year) unikal
class CountryCodeRule(ValidationRule): ...           # ISO3 kodun mövcud olduğunu yoxla
class AnomalyRule(ValidationRule): ...               # əvvəlki ilə görə >N std-dev fərq → flag
class SchemaChangeRule(ValidationRule): ...          # API cavab strukturu gözlənilənlə uyğundurmu
```

Hər qayda `PASS / WARN / FAIL` qaytarır; nəticələr `validation_log` cədvəlinə yazılır (provenance-ın bir hissəsi kimi). **AI bu mərhələdə iştirak etmir** — bu, sizin ən aydın tələbinizdir və arxitektur olaraq tam təcrid olunmalıdır.

---

## 11. Metric / Recipe Engine

```yaml
# recipes.yaml
house_affordability:
  formula: "house_price / annual_net_income"
  inputs:
    house_price: {concept: house_price, unit: local_currency}
    annual_net_income: {concept: net_income, unit: local_currency, annualize: true}
  output_unit: "years"

years_to_buy:
  formula: "house_price / annual_savings"
  inputs:
    house_price: {concept: house_price}
    annual_savings: {concept: net_income, transform: "value * savings_rate"}
```

Python engine bu YAML-ı oxuyur, tələb olunan inputların Collection Plan-da mövcud olduğunu yoxlayır, `eval`-siz təhlükəsiz formula-parser (məs. `asteval` və ya öz məhdud AST-based parser) ilə hesablayır. **AI yalnız yeni formula TƏKLİF edə bilər** (`"house affordability üçün hansı formula uyğun ola bilər?"` sualına cavab olaraq YAML qaraltısı təklif edir), amma bu təklif **insan tərəfindən təsdiqlənməmiş halda `recipes.yaml`-a avtomatik yazılmır** — bu, sizin "AI hesablamasın" tələbinin təbii davamıdır.

---

## 12. Cost — Ucuz MVP

MVP üçün minimum stack:
- **Storage:** SQLite (mövcud kod işə yarayır) → sonra Postgres+pgvector (pulsuz tier: Supabase/Neon)
- **Full-text:** Postgres `tsvector` (əlavə xərc yoxdur)
- **Embeddings:** kiçik açıq-mənbəli model (self-hosted, $0) və ya ucuz API (min. xərc, çünki bir dəfə indexlənir)
- **LLM:** yalnız ambiguity halında, kiçik/ucuz model, ayda bəlkə bir neçə yüz çağırış (praktiki olaraq bir neçə dollar)
- **Hosting:** kiçik VPS və ya hətta lokal cron + GitHub Actions (planlaşdırılmış işlər üçün)

**Real xərc mərkəzi AI deyil, API rate-limit-lərinə uyğunlaşmaq və yeni source adapter yazmaq üçün lazım olan mühəndis vaxtıdır** — arxitektura bunu minimuma endirmək üçün qurulmalıdır (adapter-lər standart interfeysə uysun deyə).

---

## 13. Scaling: 10 → 100 → 1000 source

| Səviyyə | Nə dəyişir |
|---|---|
| **10 source** | SQLite/kiçik Postgres kifayət edir, catalogue indexləmə əl ilə/tək cron job |
| **100 source** | Postgres+pgvector mütləq lazımdır, indexləmə paralelləşdirilməli (queue: Celery/RQ), source health-monitoring lazım olur (bəzi API-lar dəyişir/pozulur) |
| **1000 source** | Catalogue indexləmə özü də incremental/diff-based olmalıdır (hər gün 1000 source-u tam yenidən oxumaq baha başa gəlir), source-lar arası prioritetləndirmə üçün reytinq sistemi avtomatik feedback-lə (istifadəçi hansı indicator-i seçdi → gələcək ranking-ə təsir) əlavə oluna bilər |

---

## 14. Security

- **API keys/secrets:** `.env` + secret manager (Vault, ya sadə encrypted `.env` + `.gitignore`); heç vaxt `config.yaml`-da plain-text saxlanmasın
- **Rate limiting:** mövcud `_throttle()` mexanizmi hər adapter üçün icbari olmalıdır (artıq var, saxlanmalıdır)
- **SSRF:** yeni source əlavə edilərkən `base_url` yalnız allow-list-dəki domenlərdən qəbul edilməli, istifadəçi-təqdim edilmiş URL-lər avtomatik fetch edilməməli
- **Malicious metadata:** CKAN/open-data mənbələrindən gələn `title`/`description` sahələri SQL-injection-a qarşı parametrized query ilə (mövcud kodda artıq belədir), XSS-ə qarşı isə frontend-də escape edilməlidir
- **LLM prompt injection:** əgər dataset description-ları LLM promptuna daxil edilirsə (semantic matching-də), bu mətnlər "instruction" kimi deyil, yalnız "data" kimi işlənməlidir (system prompt-da aydın ayrılmalı)

---

## 15. Data Provenance

Hər final rəqəm üçün ayrıca `provenance` cədvəli:

```sql
CREATE TABLE provenance (
    fact_id           UUID PRIMARY KEY,
    source_id         TEXT,
    dataset_id        TEXT,
    indicator_code    TEXT,
    country            TEXT,
    year               INT,
    raw_value           NUMERIC,
    final_value          NUMERIC,
    transformation_log   JSONB,      -- [{step: 'currency_convert', from: 'local', to: 'USD', rate: ...}, ...]
    collected_at          TIMESTAMPTZ,
    api_request_url        TEXT,
    collection_plan_id      UUID REFERENCES collection_plans(plan_id),
    validation_status        TEXT
);
```

Bu, sizin LinkedIn-paylaşım tələbinizi tam ödəyir — hər rəqəmin yanında "Mənbə: Eurostat, dataset sdg_08_10, 2024-cü il, 12 Avqust 2026-da toplanıb" kimi qeyd avtomatik generasiya oluna bilər.

---

## 16. Final Recommendation

### AI agent lazımdır, lazım deyil, yoxsa hybrid?

**Hybrid — və məhz sizin təklif etdiyiniz formada, kiçik dəqiqləşdirmələrlə (bax bölmə 2 və 3).**

Səbəb: Tam AI-siz variant sizin "istənilən yeni mövzuda genişlənmə" arzunuzu 1-2 il ərzində məhdudlaşdıracaq (hər yeni domain üçün taxonomy-ni əl ilə genişləndirmək lazım gələcək). Tam AI-agent variant isə sizin explicit tələb etdiyiniz explainability/reproducibility/aşağı-xərc prinsiplərinə ziddir. Hybrid, deterministic layer-i "default yol", LLM-i "yalnız qeyri-müəyyənlik zamanı ehtiyat" kimi işlədərək hər iki tərəfin ən yaxşısını verir.

**Minimum AI istifadəsi ilə necə qurmaq:**
1. Əvvəlcə taxonomy+catalogue+rule-based matching-i tam qurun (bölmə 2, Variant B-nin komponentləri) — bu, artıq işin 70-90%-ni görür.
2. LLM-i yalnız **son addım kimi**, dar/strukturlaşdırılmış prompt-larla (JSON output, top-5 candidate-dan seçim) əlavə edin — açıq-uçuq "planla bunu" tapşırıqları vermək əvəzinə.
3. Hər LLM cavabını loglayın və vaxtaşırı nəzərdən keçirin — bu feedback taxonomy/sinonim lüğətini get-gedə zənginləşdirir və LLM ehtiyacını zamanla **azaldır** (self-improving deterministic layer).

---

## Development Roadmap

### MVP (2-4 həftə)
- Mövcud kodu düzəlt (import path bugı) və **vahid `facts` cədvəlinə** (bölmə 15-in sadələşdirilmiş forması) yazacaq şəkildə storage-ı yenidən qur
- `catalogue_entries` cədvəlini qur, mövcud `COMMON_INDICATORS` + `concepts:` datasını ora köçür (əl ilə, 50-100 sətir)
- Sadə full-text axtarış (Postgres `tsvector`, ya da hətta SQLite `LIKE` ilə başlana bilər)
- `--compare`/`--cross-check`-i Collection Plan formatına keçir, nəticələri provenance ilə saxla
- Sadə Validation Engine: unit/duplicate/range yoxlamaları (AI yoxdur)

### V2 (4-8 həftə)
- Postgres+pgvector-a keçid, embedding-based semantic search
- `discover_catalogue()` metodlarını hər adapterə əlavə et (avtomatik indexləmə, əl ilə deyil)
- Confidence scoring + "ambiguity gate" məntiqi
- LLM inteqrasiyası **yalnız** ambiguity halları üçün (kiçik model, strukturlaşdırılmış prompt)
- Metric/Recipe Engine (YAML-based derived indicators)

### V3 (8-16 həftə)
- Yeni source-lar əlavə et (OECD, FRED, BLS, national stats offices)
- Source ranking-i feedback-lə təkmilləşdir (istifadəçi seçimlərindən öyrənən sadə heuristika, hələ ML modeli yox)
- Anomaly detection (statistik, AI yox)
- LinkedIn export moduluna keçid (chart/table generasiya)

### Production
- Monitoring/alerting (source-lar sınanda)
- Incremental/diff-based catalogue indexləmə (1000+ source üçün)
- Tam audit-trail UI (hər rəqəmin provenance-ni vizual göstərmək)
- Rate-limit/health-check dashboard
- Opsional: LLM-selection accuracy-ni izləyən metrikalar, taxonomy-ni avtomatik təkmilləşdirən feedback loop

---

*Qeyd: bu sənəd yalnız təhlil və arxitektur planlamadır — heç bir kod dəyişikliyi edilməyib. İmplementasiyaya keçmək istədiyiniz zaman, MVP mərhələsindən (import bugının düzəldilməsi və vahid storage schema-sı) başlamağı tövsiyə edirəm.*
