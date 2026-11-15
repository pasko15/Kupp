"""Import configured Kassalapp EAN history for manually approved matches."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from backend.kupp.config import DB_PATH, load_thresholds
from backend.kupp.sources.kassalapp import fetch_history, get_api_key

def is_fresh(last_checked: str | None, now: datetime, freshness_days: int) -> str:
    if not last_checked:
        return "unknown"
    checked = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
    age_days = (now - checked.astimezone(timezone.utc)).total_seconds() / 86400
    return "fresh" if 0 <= age_days <= freshness_days else "stale"


def as_minor_units(price: object) -> int:
    amount = Decimal(str(price)) * 100
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def import_history() -> tuple[int, int, int, int]:
    api_key = get_api_key()
    thresholds = load_thresholds()
    freshness_days = int(thresholds["freshness_days"])
    history_window_days = int(thresholds["history_window_days"])

    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    try:
        matches = db.execute(
            """SELECT id, source_ean FROM product_matches
               WHERE source = 'Kassalapp' AND source_ean IS NOT NULL
               ORDER BY item_id"""
        ).fetchall()
        if not matches:
            raise RuntimeError("No Kassalapp matches found. Add approved EANs to matches.csv first.")
        if len(matches) > 100:
            raise RuntimeError("Kassalapp bulk history accepts at most 100 EANs per request.")

        match_by_ean = {str(ean): int(match_id) for match_id, ean in matches}
        started_at = datetime.now(timezone.utc)
        run_id = db.execute(
            "INSERT INTO import_runs(source, started_at, status) VALUES (?, ?, 'running')",
            ("Kassalapp", started_at.isoformat()),
        ).lastrowid
        db.commit()

        try:
            result = fetch_history(api_key, list(match_by_ean), days=history_window_days)
            records_seen = 0
            records_added = 0
            skipped_products = []
            for product in result.get("data", []):
                ean = str(product.get("ean", ""))
                match_id = match_by_ean.get(ean)
                if match_id is None:
                    continue

                last_checked_by_store: dict[str, str | None] = {}
                store_names: dict[str, str] = {}
                for store in product.get("stores", []):
                    code = store.get("store")
                    if not code:
                        continue
                    last_checked_by_store[code] = store.get("last_checked")
                    store_names[code] = store.get("name") or code
                    db.execute(
                        """INSERT INTO stores(store_id, name, country, currency)
                           VALUES (?, ?, 'NO', 'NOK')
                           ON CONFLICT(store_id) DO UPDATE SET name=excluded.name""",
                        (code, store_names[code]),
                    )

                points = product.get("price_history", [])
                if not points:
                    skipped_products.append(ean)
                for point in points:
                    records_seen += 1
                    store_code = point.get("store")
                    if not store_code or point.get("price") is None or not point.get("date"):
                        continue
                    if store_code not in store_names:
                        store_names[store_code] = store_code
                        last_checked_by_store[store_code] = None
                        db.execute(
                            """INSERT INTO stores(store_id, name, country, currency)
                               VALUES (?, ?, 'NO', 'NOK') ON CONFLICT(store_id) DO NOTHING""",
                            (store_code, store_code),
                        )

                    price_minor = as_minor_units(point["price"])
                    checked_at = last_checked_by_store.get(store_code)
                    freshness = is_fresh(checked_at, started_at, freshness_days)
                    fingerprint = "|".join(
                        ("Kassalapp", ean, store_code, point["date"], str(price_minor), "min")
                    )
                    content_hash = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
                    cursor = db.execute(
                        """INSERT OR IGNORE INTO price_observations (
                               product_match_id, store_id, price_minor, currency,
                               observed_at, retrieved_at, source_checked_at, source,
                               price_type, is_promo, content_hash, freshness, import_run_id
                           ) VALUES (?, ?, ?, 'NOK', ?, ?, ?, 'Kassalapp',
                                     'unknown', NULL, ?, ?, ?)""",
                        (
                            match_id,
                            store_code,
                            price_minor,
                            point["date"],
                            started_at.isoformat(),
                            checked_at,
                            content_hash,
                            freshness,
                            run_id,
                        ),
                    )
                    records_added += max(cursor.rowcount, 0)

            found = len(result.get("data", []))
            requested = len(match_by_ean)
            status = "succeeded" if found == requested and not skipped_products else "partial"
            db.execute(
                """UPDATE import_runs SET finished_at=?, status=?, records_seen=?,
                          records_added=?, error_summary=? WHERE id=?""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    status,
                    records_seen,
                    records_added,
                    (f"No history points for EANs: {', '.join(skipped_products)}" if skipped_products else None),
                    run_id,
                ),
            )
            db.commit()
            days_included = int(result.get("meta", {}).get("days_included", history_window_days))
            return requested, records_seen, records_added, days_included
        except Exception as exc:
            db.rollback()
            db.execute(
                """UPDATE import_runs SET finished_at=?, status='failed', error_summary=?
                   WHERE id=?""",
                (datetime.now(timezone.utc).isoformat(), str(exc)[:500], run_id),
            )
            db.commit()
            raise
    finally:
        db.close()


if __name__ == "__main__":
    try:
        requested, seen, added, days_included = import_history()
        print(f"Requested history for {requested} matches; Kassalapp included {days_included} days; saw {seen} points; added {added} new observations.")
        print("Kassalapp does not label promotions; imported rows retain unknown price_type.")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)\n