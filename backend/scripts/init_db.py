"""Create the local SQLite database and load basket.csv."""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.kupp.config import BASKET_PATH, DB_PATH, MATCHES_PATH, SCHEMA_PATH
from backend.kupp.matching import read_matches, sync_matches


REQUIRED_COLUMNS = {
    "item_id",
    "product_name",
    "brand",
    "variant",
    "pack_size",
    "pack_unit",
    "ean",
    "sweden_match_preference",
    "notes",
}
def read_basket(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"basket.csv is missing columns: {', '.join(sorted(missing))}")

        items: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"basket.csv line {line_number} has extra comma-separated fields")
            item_id = (row.get("item_id") or "").strip()
            name = (row.get("product_name") or "").strip()
            if not item_id or not name:
                raise ValueError(f"basket.csv line {line_number} needs item_id and product_name")
            if item_id in seen_ids:
                raise ValueError(f"basket.csv has duplicate item_id '{item_id}'")
            seen_ids.add(item_id)

            size_text = (row.get("pack_size") or "").strip()
            try:
                size = float(size_text) if size_text else None
            except ValueError as exc:
                raise ValueError(
                    f"basket.csv line {line_number} has invalid pack_size '{size_text}'"
                ) from exc

            sweden_preference = _optional(row.get("sweden_match_preference"))
            if sweden_preference not in (None, "identical_only", "equivalent_ok"):
                raise ValueError(
                    f"basket.csv line {line_number} has invalid sweden_match_preference "
                    f"'{sweden_preference}' (use identical_only or equivalent_ok)"
                )

            items.append(
                {
                    "item_id": item_id,
                    "product_name": name,
                    "brand": _optional(row.get("brand")),
                    "variant": _optional(row.get("variant")),
                    "pack_size": size,
                    "pack_unit": _optional(row.get("pack_unit")),
                    "ean": _optional(row.get("ean")),
                    "sweden_match_preference": sweden_preference,
                    "notes": _optional(row.get("notes")),
                }
            )
        return items


def _optional(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def initialize() -> tuple[int, int, int, int]:
    items = read_basket(BASKET_PATH)
    matches = read_matches(MATCHES_PATH, {str(item["item_id"]) for item in items})
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    db = sqlite3.connect(DB_PATH)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(schema)

        # Migrate databases created before this preference was added to the basket.
        columns = {row[1] for row in db.execute("PRAGMA table_info(products)")}
        if "sweden_match_preference" not in columns:
            db.execute(
                "ALTER TABLE products ADD COLUMN sweden_match_preference TEXT "
                "CHECK (sweden_match_preference IS NULL "
                "OR sweden_match_preference IN ('identical_only', 'equivalent_ok'))"
            )
        match_columns = {row[1] for row in db.execute("PRAGMA table_info(product_matches)")}
        if "pack_size" not in match_columns:
            db.execute(
                "ALTER TABLE product_matches ADD COLUMN pack_size REAL "
                "CHECK (pack_size IS NULL OR pack_size > 0)"
            )
        if "pack_unit" not in match_columns:
            db.execute("ALTER TABLE product_matches ADD COLUMN pack_unit TEXT")
        observation_columns = {row[1] for row in db.execute("PRAGMA table_info(price_observations)")}
        if "source_checked_at" not in observation_columns:
            db.execute("ALTER TABLE price_observations ADD COLUMN source_checked_at TEXT")

        db.executemany(
            """
            INSERT INTO products (
                item_id, product_name, brand, variant, pack_size,
                pack_unit, ean, sweden_match_preference, notes, created_at
            ) VALUES (
                :item_id, :product_name, :brand, :variant, :pack_size,
                :pack_unit, :ean, :sweden_match_preference, :notes, :created_at
            )
            ON CONFLICT(item_id) DO UPDATE SET
                product_name = excluded.product_name,
                brand = excluded.brand,
                variant = excluded.variant,
                pack_size = excluded.pack_size,
                pack_unit = excluded.pack_unit,
                ean = excluded.ean,
                sweden_match_preference = excluded.sweden_match_preference,
                notes = excluded.notes
            """,
            [{**item, "created_at": now} for item in items],
        )
        sync_matches(db, matches)
        total = db.execute("SELECT COUNT(*) FROM products WHERE is_active = 1").fetchone()[0]
        match_total = db.execute("SELECT COUNT(*) FROM product_matches").fetchone()[0]
        db.commit()
    finally:
        db.close()
    return len(items), total, len(matches), match_total


if __name__ == "__main__":
    count, total, match_count, match_total = initialize()
    print(f"Loaded {count} basket items into {DB_PATH.name}; {total} active items in the database.")
    print(f"Loaded {match_count} product matches; {match_total} matches in the database.")
