"""CSV export köməkçiləri (əvvəllər storage.py-də idi)."""

import csv
import os


def save_comparison_csv(rows: list, out_path: str):
    """--compare nəticələrini CSV-yə yazır."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["country", "iso3", "indicator", "year", "value"])
        for r in rows:
            writer.writerow([r["country"], r["iso3"], r["indicator"], r["year"], r["value"]])


def save_cross_check_csv(rows: list, out_path: str):
    """--cross-check nəticələrini CSV-yə yazır."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "country", "iso3", "indicator", "year", "value"])
        for r in rows:
            writer.writerow([r.get("source"), r.get("country"), r.get("iso3"),
                              r.get("indicator"), r.get("year"), r.get("value")])


def save_cbr_csv(rows: list, out_path: str):
    """--cbr-snapshot nəticələrini CSV-yə yazır."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["currency", "name", "nominal", "value_rub", "date"])
        for r in rows:
            writer.writerow([r["currency"], r["name"], r["nominal"], r["value_rub"], r["date"]])
