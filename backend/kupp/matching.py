"""Read and persist manually reviewed basket-to-source product matches."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


MATCH_COLUMNS = {
    "item_id",
    "source",
    "source_product_id",
    "source_ean",
    "matched_name",
    "pack_size",
    "pack_unit",
    "match_type",
    "confidence",
    "notes",
}


def _optional(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def read_matches(path: Path, item_ids: set[str]) -> list[dict[str, object]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])
        missing = MATCH_COLUMNS - columns
        if missing:
            raise ValueError(f"matches.csv is missing columns: {', '.join(sorted(missing))}")

        matches: list[dict[str, object]] = []
        seen: set[tuple[str, str, str]] = set()
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"matches.csv line {line_number} has extra comma-separated fields")
            item_id = (row.get("item_id") or "").strip()
            source = (row.get("source") or "").strip()
            product_id = (row.get("source_product_id") or "").strip()
            if not item_id or not source or not product_id:
                raise ValueError(f"matches.csv line {line_number} needs item_id, source, and source_product_id")
            if item_id not in item_ids:
                raise ValueError(f"matches.csv line {line_number} references unknown basket item '{item_id}'")
            key = (item_id, source, product_id)
            if key in seen:
                raise ValueError(f"matches.csv line {line_number} duplicates match {key}")
            seen.add(key)

            match_type = (row.get("match_type") or "").strip()
            if match_type not in ("identical", "equivalent"):
                raise ValueError(f"matches.csv line {line_number} match_type must be identical or equivalent")
            try:
                confidence = float((row.get("confidence") or "").strip())
            except ValueError as exc:
                raise ValueError(f"matches.csv line {line_number} has invalid confidence") from exc
            if not 0 <= confidence <= 1:
                raise ValueError(f"matches.csv line {line_number} confidence must be between 0 and 1")

            size_text = (row.get("pack_size") or "").strip()
            try:
                size = float(size_text) if size_text else None
            except ValueError as exc:
                raise ValueError(f"matches.csv line {line_number} has invalid pack_size") from exc

            matches.append(
                {
                    "item_id": item_id,
                    "source": source,
                    "source_product_id": product_id,
                    "source_ean": _optional(row.get("source_ean")),
                    "matched_name": _optional(row.get("matched_name")),
                    "pack_size": size,
                    "pack_unit": _optional(row.get("pack_unit")),
                    "match_type": match_type,
                    "confidence": confidence,
                    "notes": _optional(row.get("notes")),
                }
            )
        return matches


def sync_matches(db: sqlite3.Connection, matches: list[dict[str, object]]) -> None:
    db.executemany(
        """
        INSERT INTO product_matches (
            item_id, source, source_product_id, source_ean, matched_name,
            pack_size, pack_unit, match_type, confidence, notes
        ) VALUES (
            :item_id, :source, :source_product_id, :source_ean, :matched_name,
            :pack_size, :pack_unit, :match_type, :confidence, :notes
        )
        ON CONFLICT(item_id, source, source_product_id) DO UPDATE SET
            source_ean = excluded.source_ean,
            matched_name = excluded.matched_name,
            pack_size = excluded.pack_size,
            pack_unit = excluded.pack_unit,
            match_type = excluded.match_type,
            confidence = excluded.confidence,
            notes = excluded.notes
        """,
        matches,
    )
