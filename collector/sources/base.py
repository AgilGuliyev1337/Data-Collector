"""
Bütün data mənbələri üçün ümumi interfeys (DataSource ABC).

Qat xəritəsi (yalnız bu sinif indi mövcuddur, qalanları gələcək
mərhələlərə aiddir — burada sadəcə niyyət qeyd olunur):

  SourceAdapter    -> bu ABC-nin özü (CKANSource, WorldBankSource, ...).
  DataCatalogue    -> gələcək `catalogue_entries`/`concepts` qatı (indi yoxdur).
  SourceRegistry   -> gələcəkdə `sources` cədvəli üzərində nazik idarəetmə
                      qatı; tanınan (static) və aşkar edilmiş (discovered)
                      adapter-ləri idarə edəcək.
  SourceDiscovery  -> gələcəkdə fallback zəncirini (catalogue -> tanınan
                      adapter -> digər open-data mənbələri -> web) icra edib
                      tapılan mənbələri `sources`-a `discovery_method=
                      'discovered'`, `trust_level='unverified_web'` ilə
                      yazacaq komponent.

`sources` cədvəlindəki `discovery_method`/`priority_tier`/`trust_level`
sütunları bu gələcək qat üçün saxlanılan yerdir (bax: migrations/0001_init.sql).
Bu mərhələdə yalnız `discovery_method='static'` sətirlər yazılır.
"""

from abc import ABC, abstractmethod


class DataSource(ABC):
    """Bütün adapter-lərin uyğunlaşdığı minimal ortaq interfeys.

    Hər adapterin öz domenində fundamental fərqli parametrləri olduğu üçün
    `fetch()` qəsdən `**kwargs` alır — məcburi vahid signature qoyulmur.
    """

    id: str

    @abstractmethod
    def validate_connection(self) -> bool:
        """Mənbəyə əlaqənin işlək olduğunu yoxlayır (yüngül bir sorğu ilə)."""
        raise NotImplementedError

    @abstractmethod
    def fetch(self, **kwargs):
        """Mənbədən data çəkir. Qaytarılan şəkil adapterdən asılıdır."""
        raise NotImplementedError

    def discover_catalogue(self) -> list[dict]:
        """Gənc DataCatalogue/SourceDiscovery qatı üçün yer saxlanılır.

        Override et: adapter catalogue discovery icra etməyibsə, boş siyahı qaytar.
        """
        return []

    def metadata(self) -> dict:
        """Mənbə haqqında statik metadata (id, növ və s.)."""
        return {"id": self.id}

    def rate_limit(self):
        """Adapterin sorğu tezliyi limiti (default: limit yoxdur)."""
        return None
