# Data Collector

Natural-dil sorğu ilə iqtisadi/statistik göstəriciləri (ÜDM, maaş, ev qiyməti,
işsizlik və s.) toplayan Streamlit tətbiqi. World Bank, Eurostat, IMF, CBR,
STAT.GOV.AZ, Manzil.az kimi rəsmi mənbələrdən axtarır; heç biri tapmasa
DuckDuckGo ilə internetdən axtarıb tapdığı rəqəmləri mənbə linki və
etibarlılıq balı ilə göstərir. Bütün nəticələr PostgreSQL-də saxlanılır.

## Quraşdırma və işə salma

Tələb olunur: Python 3.10+, PostgreSQL 13+ (və ya Docker).

### 1. Postgres — Docker ilə (ən asan yol)

```bash
docker compose up -d
```

Bu, `collector` istifadəçisi və `data_collector` + `data_collector_test`
bazaları ilə hazır Postgres konteyneri qaldırır — heç bir əlavə addım lazım
deyil, aşağıdaki `.env` faylı bununla birbaşa uyğundur.

**Docker yoxdursa** — öz Postgres serverində əl ilə yarat:

```bash
sudo -u postgres createuser collector -P   # parol soruşacaq
sudo -u postgres createdb data_collector -O collector
sudo -u postgres createdb data_collector_test -O collector
```

### 2. Python asılılıqları

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. `.env` faylı

```bash
cp .env.example .env
```

Docker yolu ilə getmisənsə `.env.example`-dəki dəyərlər dəyişmədən işləyir.
Əl ilə Postgres qurmusansa, `.env`-dəki `CHANGE_ME`-ni öz parolunla əvəz et.

### 4. Sxemi qur (migration-lar)

```bash
.venv/bin/python -m collector.db.migrate
```

İkinci dəfə çağırsan heç nə dəyişmir (idempotent) — təhlükəsiz təkrar
işlədilə bilər.

### 5. Tətbiqi işə sal

```bash
.venv/bin/streamlit run app.py --server.port 8501
```

Brauzerdə `http://localhost:8501` açılacaq. Sorğu qutusuna məs.
`"Azərbaycanda orta maaş 2023"` yaz və "Sorghu islet" düyməsinə bas.

### Testlərin işlədilməsi

```bash
.venv/bin/python -m pytest tests/ -q
```

(`@pytest.mark.api_connectivity` işarəli testlər canlı internet çağırışı
edir — şəbəkə/sandbox məhdudiyyəti olan mühitlərdə uğursuz ola bilər, bu
kodun problemi deyil.)

---

## Əlavə: köhnə CLI alətləri (legacy)

Aşağıdaki `cli.py` + `config.yaml` əsaslı alətlər layihənin ilkin
fazasından qalıb — CKAN portallarından statik dataset toplamaq üçündür.
Əsas məhsul yuxarıdaki Streamlit tətbiqidir, amma bu alətlər də işləyir.

## İstifadə

```bash
# Config-dəki source-ları göstər
python3 cli.py --list-sources

# Bir portaldakı dataset adlarına baxmaq (yükləmədən, sadəcə siyahı)
python3 cli.py --list-packages opendata_az

# Bütün enabled source-ları işlət (data SQLite-a yazılır)
python3 cli.py --run

# Yalnız bir source-u işlət
python3 cli.py --run --source opendata_az
```

Nəticə `data/collector.db` (SQLite) və ya `data/csv/datasets.csv`-də
saxlanılır (config.yaml → storage.backend ilə seçilir).

## Çoxmənbəli müqayisə (bir mənbəyə güvənmə)

Tool 4 MÜSTƏQİL mənbə növündən istifadə edir ki, eyni göstərici üçün
nəticələri çarpaz-yoxlaya biləsən:

| Mənbə | Tipi | Əhatə | Açar lazımdır? |
|---|---|---|---|
| **World Bank** | Beynəlxalq aqreqat statistika | Bütün ölkələr | Xeyr |
| **IMF** | Beynəlxalq (fərqli metodologiya) | Bütün ölkələr | Xeyr |
| **Eurostat** | Regional rəsmi statistika | Yalnız Avropa | Xeyr |
| **Bank of Russia (CBR)** | Sektoral/maliyyə (mərkəzi bank) | Rusiya/MDB | Xeyr |
| **CKAN portalları** (opendata.az və s.) | Milli rəsmi open-data | Ölkə-spesifik | Xeyr |

### Çarpaz-yoxlama nümunəsi

```bash
# GDP artım tempini HƏM World Bank, HƏM Eurostat, HƏM IMF-dən çək,
# nəticələri yan-yana göstər (fərq varsa özün görəcəksən)
python3 cli.py --cross-check --concept gdp_growth --regions europe azerbaijan

# İşsizlik səviyyəsini World Bank + Eurostat üzrə müqayisə et
python3 cli.py --cross-check --concept unemployment --regions europe --out-csv data/unemployment_crosscheck.csv

# MDB üçün sektoral mənbə: Bank of Russia-nın günün valyuta məzənnələri
python3 cli.py --cbr-snapshot --out-csv data/cbr_rates.csv
```

**VACIB QEYD:** `config.yaml -> concepts` bölməsindəki Eurostat/IMF dataset
kodları **ilkin təxmindir**. İstifadə etməzdən əvvəl:
- Eurostat: https://ec.europa.eu/eurostat/web/query-builder ilə dataset kodunu təsdiqlə
- IMF: `python3 -c "from collector.imf_source import IMFSource; print(IMFSource().list_dataflows())"` ilə mövcud dataset-lərə bax

Bu, real dünyada hər data mühəndisinin etdiyi addımdır — API-lar öz
dataset kodlarını dəyişə bilir, ona görə production-a keçməzdən əvvəl
mütləq canlı yoxlama lazımdır.

## Regionlar üzrə müqayisə (Avropa / Amerika / Azərbaycan / MDB)

Bu funksiya **World Bank Open Data API**-dən istifadə edir — açar/qeydiyyat
lazım deyil, minlərlə göstərici (GDP, əhali, işsizlik, internet istifadəçiləri,
inflyasiya və s.) üzrə istənilən ölkələri birbaşa müqayisə edir.

```bash
# Mövcud göstəricilərə bax
python3 cli.py --list-indicators

# 4 regionu adambaşı ÜDM üzrə müqayisə et (default regionlar: azerbaijan, europe, america, cis)
python3 cli.py --compare --indicator gdp_per_capita

# İşsizlik səviyyəsini son 5 il üzrə müqayisə et, CSV-yə yaz
python3 cli.py --compare --indicator unemployment --start-year 2019 --end-year 2024 --out-csv data/unemployment_comparison.csv

# Yalnız Azərbaycan və MDB-ni müqayisə et
python3 cli.py --compare --indicator internet_users --regions azerbaijan cis

# Birbaşa World Bank göstərici kodu ilə (qısa ad siyahıda yoxdursa)
python3 cli.py --compare --indicator SH.XPD.CHEX.GD.ZS --regions europe cis
```

**Region tərkibini dəyişmək** — `config.yaml` → `regions:` bölməsində
ölkə kodlarını (ISO3) əlavə et/çıxar. Məs. Avropaya İtaliyanı əlavə etmək
üçün `europe:` siyahısına `ITA` əlavə et.

**Maraqlı araşdırma ideyaları (tool ilə birbaşa yoxlana bilər):**
- Azərbaycan ilə MDB ölkələri arasında internet/mobil istifadəsi fərqi
- Avropa vs Amerika: tədqiqat/inkişaf xərcləri (`researchers_per_million`)
- 4 regionun son 10 ildə GDP artım tempi müqayisəsi (`gdp_growth`)
- Ease of business reytinqi üzrə Azərbaycanın MDB-dəki yeri

## Yeni mənbə əlavə etmək

`config.yaml`-da `sources:` altına yeni blok əlavə et:

```yaml
  - id: data_gov_us
    type: ckan
    base_url: https://catalog.data.gov
    filter:
      groups: []
      tags: ["economy"]
    require_open_license: true
    rate_limit_per_sec: 2
    enabled: true
```

Bu qədər — kod dəyişmə lazım deyil, çünki bütün CKAN portalları eyni
API strukturuna malikdir.

## Avtomatik (cron) işə salmaq

```bash
# hər gün saat 03:00-da işə salmaq üçün crontab-a əlavə et:
0 3 * * * cd /path/to/data-collector && /path/to/venv/bin/python3 cli.py --run >> data/cron.log 2>&1
```

## Vacib qeydlər (hüquqi/etik)

- Tool default olaraq YALNIZ açıq lisenziyalı (`cc-zero`, `cc-by`, `odc-odbl`
  və s.) datasetləri toplayır — `config.yaml`-da `require_open_license: true`.
  Bunu `false`-a çevirmə, əks halda lisenziyası qeyri-müəyyən/qapalı
  datasetlər də toplanar.
- Hər mənbə üçün `rate_limit_per_sec` təyin olunub ki, portala həddindən
  artıq yük vermə (məsuliyyətli data toplama).
- Tool yalnız CKAN-ın rəsmi, sənədləşdirilmiş API-larından istifadə edir —
  heç bir robots.txt/ToS pozuntusu yoxdur.
- Yeni mənbə (xüsusilə CKAN olmayan saytlar) əlavə etməzdən əvvəl həmin
  saytın robots.txt və ToS-unu mütləq yoxla.

## Növbəti addımlar (genişləndirmə)

- `collector/rss_source.py`, `collector/html_source.py` əlavə edərək
  RSS/sitemap və ya robots.txt-ə uyğun HTML mənbələri dəstəklə
- Prometheus metrics endpoint (`/metrics`) əlavə et — sən artıq
  Prometheus/Grafana ilə işlədiyin üçün bu asan olacaq
- Faktiki resurs fayllarını (CSV/XLSX) da avtomatik yükləyib
  `data/downloads/` qovluğuna saxlamaq üçün `download_resources()`
  metodunu `ckan_source.py`-a əlavə et
