"""Compute a deterministic current-price snapshot from kupp.db."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from statistics import median

from backend.kupp.config import DB_PATH, REPORT_PATH, load_thresholds
from backend.kupp.pricing import price_drop_vs_history, unit_price


def money(price_minor: int | float | Decimal | None) -> float | None:
    if price_minor is None:
        return None
    return round(float(Decimal(str(price_minor)) / 100), 2)


def unit_value(price_minor: int | None, size: float | None, unit: str | None) -> dict | None:
    result = unit_price(price_minor, size, unit) if price_minor is not None else None
    if result is None:
        return None
    normalized_unit, amount = result
    return {"amount": round(float(amount), 2), "currency_per": normalized_unit}


def is_fresh(check_time: str | None, now: datetime, freshness_days: int) -> bool | None:
    if not check_time:
        return None
    parsed = datetime.fromisoformat(check_time.replace("Z", "+00:00")).astimezone(timezone.utc)
    age = (now - parsed).total_seconds() / 86400
    return 0 <= age <= freshness_days


def build_report() -> dict:
    now = datetime.now(timezone.utc)
    thresholds = load_thresholds()
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """SELECT pm.id AS match_id, pm.item_id, p.product_name AS basket_name,
                      p.brand AS preferred_brand, p.variant AS basket_variant,
                      pm.source_product_id, pm.source_ean, pm.matched_name,
                      pm.pack_size, pm.pack_unit, pm.match_type, pm.confidence,
                      po.store_id, s.name AS store_name, po.price_minor, po.currency,
                      po.observed_at, po.retrieved_at, po.source_checked_at,
                      po.price_type, po.is_promo, po.freshness, po.content_hash
               FROM product_matches pm
               JOIN products p ON p.item_id = pm.item_id
               LEFT JOIN price_observations po ON po.product_match_id = pm.id
               LEFT JOIN stores s ON s.store_id = po.store_id
               WHERE pm.source = 'Kassalapp'
               ORDER BY pm.item_id, po.store_id, po.observed_at"""
        ).fetchall()
        unmatched_rows = db.execute(
            """SELECT p.item_id, p.product_name
               FROM products p
               WHERE p.is_active = 1 AND NOT EXISTS (
                   SELECT 1 FROM product_matches pm
                   WHERE pm.item_id = p.item_id AND pm.source = 'Kassalapp'
               )
               ORDER BY p.item_id"""
        ).fetchall()

    matches: dict[int, dict] = {}
    for row in rows:
        match_id = row["match_id"]
        if match_id not in matches:
            matches[match_id] = {
                "item_id": row["item_id"],
                "basket_item": row["basket_name"],
                "preferred_brand": row["preferred_brand"],
                "matched_product": row["matched_name"],
                "ean": row["source_ean"],
                "match_type": row["match_type"],
                "confidence": row["confidence"],
                "pack_size": row["pack_size"],
                "pack_unit": row["pack_unit"],
                "stores": defaultdict(list),
            }
        if row["store_id"] is None:
            continue
        matches[match_id]["stores"][row["store_id"]].append(
            {
                "price_minor": row["price_minor"],
                "currency": row["currency"],
                "observed_at": row["observed_at"],
                "retrieved_at": row["retrieved_at"],
                "source_checked_at": row["source_checked_at"],
                "price_type": row["price_type"],
                "is_promo": row["is_promo"],
                "freshness": row["freshness"],
            }
        )

    item_reports = []
    for match in matches.values():
        store_reports = []
        current_options = []
        all_prices = []
        for store_id, observations in match["stores"].items():
            observations.sort(key=lambda point: point["observed_at"])
            latest = observations[-1]
            values = [point["price_minor"] for point in observations]
            all_prices.extend(values)
            dates = [date.fromisoformat(str(point["observed_at"])[:10]) for point in observations]
            history_start = min(dates).isoformat()
            history_end = max(dates).isoformat()
            history_span_days = (max(dates) - min(dates)).days + 1
            price_drop = price_drop_vs_history(
                observations,
                latest["price_minor"],
                percentile=thresholds["regular_price_percentile"],
                min_observations=thresholds["minimum_price_observations"],
                min_days=thresholds["minimum_price_distinct_days"],
                window_days=thresholds["history_window_days"],
                min_drop_percent=thresholds["minimum_price_drop_percent"],
                as_of=now.date(),
            )
            unit = unit_value(latest["price_minor"], match["pack_size"], match["pack_unit"])
            fresh = is_fresh(latest["source_checked_at"], now, thresholds["freshness_days"])
            store_report = {
                "store_id": store_id,
                "store_name": store_id,
                "current_price": money(latest["price_minor"]),
                "currency": latest["currency"],
                "observed_at": latest["observed_at"],
                "source_checked_at": latest["source_checked_at"],
                "freshness": "unknown" if fresh is None else ("fresh" if fresh else "stale"),
                "unit_price": unit,
                "available_history_days": history_span_days,
                "oldest_observation": history_start,
                "newest_observation": history_end,
                "history_observations": len(observations),
                "historical_min": money(min(values)),
                "historical_max": money(max(values)),
                "observed_median": money(median(values)),
                "regular_price_estimate": money(price_drop["regular_price_minor"]),
                "regular_price_percentile": thresholds["regular_price_percentile"],
                "price_drop_status": price_drop["status"],
                "is_price_drop": price_drop["is_price_drop"],
                "price_drop_percent": (
                    round(float(price_drop["price_drop_percent"]), 2)
                    if price_drop["price_drop_percent"] is not None
                    else None
                ),
                "price_window_observations": price_drop["observations"],
                "price_window_distinct_days": price_drop["distinct_days"],
                "price_window_oldest_observation": price_drop["oldest_observation"],
                "price_window_newest_observation": price_drop["newest_observation"],
            }
            store_reports.append(store_report)
            if fresh is True:
                current_options.append(store_report)

        if match["pack_size"] and match["pack_unit"]:
            current_options = [option for option in current_options if option["unit_price"] is not None]
            cheapest = min(current_options, key=lambda option: option["unit_price"]["amount"]) if current_options else None
        else:
            cheapest = min(current_options, key=lambda option: option["current_price"]) if current_options else None

        match["stores"] = store_reports
        match["cheapest_fresh_store"] = cheapest["store_id"] if cheapest else None
        match["cheapest_fresh_unit_price"] = cheapest["unit_price"] if cheapest else None
        match["history_points_all_stores"] = sum(store["history_observations"] for store in store_reports)
        match["history_min_all_stores"] = money(min(all_prices)) if all_prices else None
        match["history_max_all_stores"] = money(max(all_prices)) if all_prices else None
        item_reports.append(match)

    return {
        "generated_at": now.isoformat(),
        "source": "Kassalapp",
        "import_aggregation": "daily minimum price",
        "thresholds": {
            "stale_after_days": thresholds["freshness_days"],
            "history_window_days": thresholds["history_window_days"],
            "regular_price_percentile": thresholds["regular_price_percentile"],
            "minimum_price_observations": thresholds["minimum_price_observations"],
            "minimum_price_distinct_days": thresholds["minimum_price_distinct_days"],
            "minimum_price_drop_percent": thresholds["minimum_price_drop_percent"],
        },
        "source_limitations": {
            "price_drop_status": "history comparison only; Kassalapp does not label promotions",
            "member_prices": "not supplied by Kassalapp",
            "prices_are_chain_level": True,
        },
        "matched_items": item_reports,
        "unmatched_items": [dict(row) for row in unmatched_rows],
    }


if __name__ == "__main__":
    report = build_report()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    matched = len(report["matched_items"])
    unmatched = len(report["unmatched_items"])
    print(f"Wrote {matched} matched items and {unmatched} unmatched items to {REPORT_PATH.name}.")
