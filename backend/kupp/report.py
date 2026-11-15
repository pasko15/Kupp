"""Compute a deterministic current-price snapshot from kupp.db."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from backend.kupp.config import DB_PATH, REPORT_PATH, load_thresholds
from backend.kupp.pricing import (
    discount_percent,
    nonpromo_baseline,
    unit_price,
    verify_deal,
)


def money(price_minor: int | float | None) -> float | None:
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
            observations.sort(key=lambda p: p["observed_at"])
            latest = observations[-1]
            values = [point["price_minor"] for point in observations]
            all_prices.extend(values)
            observed_median = Decimal(str(sorted(values)[len(values) // 2]))
            if len(values) % 2 == 0:
                observed_median = (
                    Decimal(str(sorted(values)[len(values) // 2 - 1])) + observed_median
                ) / 2
            baseline = nonpromo_baseline(
                observations,
                min_observations=thresholds["minimum_nonpromo_observations"],
                min_days=thresholds["minimum_nonpromo_days"],
            )
            deal = verify_deal(
                baseline,
                latest["price_minor"],
                min_discount_percent=thresholds["minimum_verified_discount_percent"],
            )
            drop_vs_observed_median = discount_percent(observed_median, latest["price_minor"])
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
                "history_days": len({p["observed_at"] for p in observations}),
                "history_observations": len(observations),
                "historical_min": money(min(values)),
                "historical_max": money(max(values)),
                "observed_median": money(observed_median),
                "nonpromo_baseline": money(baseline["baseline_price_minor"]),
                "nonpromo_observations": baseline["observations"],
                "nonpromo_distinct_days": baseline["distinct_days"],
                "drop_percent_vs_observed_median": (
                    round(float(drop_vs_observed_median), 2)
                    if drop_vs_observed_median is not None
                    else None
                ),
                "verified_deal": deal["verified"],
                "verified_discount_percent": (
                    round(float(deal["discount_percent"]), 2)
                    if deal["discount_percent"] is not None
                    else None
                ),
            }
            store_reports.append(store_report)
            if fresh is True:
                current_options.append(store_report)

        pack_size, pack_unit = match["pack_size"], match["pack_unit"]
        if pack_size and pack_unit:
            current_options = [x for x in current_options if x["unit_price"] is not None]
            cheapest = min(current_options, key=lambda x: x["unit_price"]["amount"]) if current_options else None
        else:
            cheapest = min(current_options, key=lambda x: x["current_price"]) if current_options else None

        match["stores"] = store_reports
        match["cheapest_fresh_store"] = cheapest["store_id"] if cheapest else None
        match["cheapest_fresh_unit_price"] = cheapest["unit_price"] if cheapest else None
        match["history_points_all_stores"] = sum(s["history_observations"] for s in store_reports)
        match["history_min_all_stores"] = money(min(all_prices)) if all_prices else None
        match["history_max_all_stores"] = money(max(all_prices)) if all_prices else None
        item_reports.append(match)

    return {
        "generated_at": now.isoformat(),
        "source": "Kassalapp",
        "import_aggregation": "daily minimum price",
        "thresholds": {
            "stale_after_days": thresholds["freshness_days"],
            "verified_baseline_min_nonpromo_observations": thresholds["minimum_nonpromo_observations"],
            "verified_baseline_min_distinct_days": thresholds["minimum_nonpromo_days"],
            "verified_discount_percent": thresholds["minimum_verified_discount_percent"],
        },
        "source_limitations": {
            "promo_status": "not supplied; imported price_type is unknown and is_promo is null",
            "member_prices": "not supplied by Kassalapp",
            "verified_deals": "cannot be verified until enough observations are explicitly classified as non-promo",
            "suspicious_price_up_then_campaign": "cannot be evaluated without promotion labels",
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
