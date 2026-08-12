"""
Toplanan dataset metadatasını saxlamaq üçün storage qatı.
Hazırda SQLite dəstəklənir (default), CSV export də mümkündür.
"""

import sqlite3
import json
import os
import csv
import logging

logger = logging.getLogger("collector.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    source_id TEXT,
    dataset_id TEXT,
    name TEXT,
    title TEXT,
    org TEXT,
    license TEXT,
    license_id TEXT,
    modified TEXT,
    tags TEXT,
    groups_ TEXT,
    resources TEXT,
    collected_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_id, dataset_id)
);
"""


class SQLiteStorage:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def save(self, record: dict):
        self.conn.execute(
            """
            INSERT INTO datasets
                (source_id, dataset_id, name, title, org, license, license_id,
                 modified, tags, groups_, resources)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, dataset_id) DO UPDATE SET
                title=excluded.title,
                modified=excluded.modified,
                resources=excluded.resources,
                collected_at=CURRENT_TIMESTAMP
            """,
            (
                record["source_id"],
                record["dataset_id"],
                record["name"],
                record["title"],
                record["org"],
                record["license"],
                record["license_id"],
                record["modified"],
                json.dumps(record["tags"], ensure_ascii=False),
                json.dumps(record["groups"], ensure_ascii=False),
                json.dumps(record["resources"], ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM datasets")
        return cur.fetchone()[0]

    def close(self):
        self.conn.close()


class CSVStorage:
    def __init__(self, csv_dir: str):
        os.makedirs(csv_dir, exist_ok=True)
        self.path = os.path.join(csv_dir, "datasets.csv")
        self._init_file()

    def _init_file(self):
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["source_id", "dataset_id", "name", "title", "org",
                     "license", "license_id", "modified", "tags", "groups",
                     "resources"]
                )

    def save(self, record: dict):
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                record["source_id"], record["dataset_id"], record["name"],
                record["title"], record["org"], record["license"],
                record["license_id"], record["modified"],
                json.dumps(record["tags"], ensure_ascii=False),
                json.dumps(record["groups"], ensure_ascii=False),
                json.dumps(record["resources"], ensure_ascii=False),
            ])

    def close(self):
        pass


def save_comparison_csv(rows: list, out_path: str):
    """World Bank müqayisə nəticələrini CSV-yə yazır."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["country", "iso3", "indicator", "year", "value"])
        for r in rows:
            writer.writerow([r["country"], r["iso3"], r["indicator"], r["year"], r["value"]])


def get_storage(cfg: dict):
    backend = cfg.get("backend", "sqlite")
    if backend == "csv":
        return CSVStorage(cfg.get("csv_dir", "data/csv"))
    return SQLiteStorage(cfg.get("sqlite_path", "data/collector.db"))
