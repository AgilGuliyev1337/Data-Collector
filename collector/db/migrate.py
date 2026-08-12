"""
Yüngül, sürünən (re-runnable) migration runner.

Ağır ORM/migration framework (Alembic və s.) əvəzinə: `migrations/`
qovluğundakı nömrələnmiş `.sql` faylları sırayla oxuyur, hər birinin
adını `schema_migrations` cədvəlində saxlayır və yalnız hələ tətbiq
olunmamış faylları icra edir. İkinci çağırış heç nə dəyişmir (idempotent).
"""

import logging
import os

from collector.db.connection import get_connection

logger = logging.getLogger("collector.db.migrate")

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "migrations",
)


def _bootstrap(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def _applied_versions(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def _migration_files() -> list:
    return sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))


def run_migrations(conn=None) -> list:
    """Tətbiq olunmamış bütün migration-ları icra edir.

    Yeni tətbiq olunan versiyaların siyahısını qaytarır (heç nə tətbiq
    olunmayıbsa boş siyahı — bu, idempotency yoxlaması üçün istifadə olunur).
    """
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        _bootstrap(conn)
        applied = _applied_versions(conn)
        newly_applied = []
        for filename in _migration_files():
            if filename in applied:
                continue
            path = os.path.join(MIGRATIONS_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                sql = f.read()
            logger.info("Migration tətbiq olunur: %s", filename)
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (filename,),
                )
            conn.commit()
            newly_applied.append(filename)
        return newly_applied
    finally:
        if own_conn:
            conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    applied = run_migrations()
    if applied:
        print(f"Tətbiq olundu: {', '.join(applied)}")
    else:
        print("Bütün migration-lar artıq tətbiq olunub (dəyişiklik yoxdur).")
