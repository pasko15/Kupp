"""Database-backed read-only API operations."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

from backend.kupp.api.database import connect_readonly
from backend.kupp.api.models import (
    BasketItem,
    BasketResponse,
    Deal,
    DealsResponse,
    HealthResponse,
    ItemHistoryResponse,
    LastImport,
    PriceObservation,
    StoreHistory,
    UnitPrice,
)
from backend.kupp.config import load_thresholds
from backend.kupp.pricing import is_fresh, money, price_drop_vs_history, unit_price


class ItemNotFoundError(Exception):
    pass


def _money(price_minor: int | Decimal | None) -> float | None:
    return None if price_minor is None else float(money(price_minor))


def _unit_value(price_minor: int | None, pack_size: float | None, pack_unit: str | None) -> UnitPrice | None:
    if price_minor is None:
        return None
    result = unit_price(price_minor, pack_size, pack_unit)
    if result is None:
        return None
    normalized_unit, amount = result
    return UnitPrice(amount=round(float(amount), 2), currency_per=normalized_unit)


def _history_rows(db: sqlite3.Connection, item_id: str | None = None) -> list[sqlite3.Row]:
    sql = """SELECT p.item_id, p.product_name, p.is_active,
                    pm.id AS match_id, pm.source, pm.matched_name, pm.match_type,
                    pm.confidence, pm.pack_size AS match_pack_size, pm.pack_unit AS match_pack_unit,
                    po.store_id, s.name AS store_name, po.price_minor, po.currency,
                    po.observed_at, po.retrieved_at, po.source_checked_at
             FROM products p
             LEFT JOIN product_matches pm ON pm.item_id = p.item_id AND pm.source = 'Kassalapp'
             LEFT JOIN price_observations po ON po.product_match_id = pm.id
             LEFT JOIN stores s ON s.store_id = po.store_id
             WHERE p.is_active = 1"""
    params: tuple[str, ...] = ()
    if item_id is not None:
        sql += " AND p.item_id = ?"
        params = (item_id,)
    sql += " ORDER BY p.item_id, po.store_id, po.observed_at"
    return db.execute(sql, params).fetchall()


def _group_rows(rows: list[sqlite3.Row]) -> dict[str, dict]:
    products: dict[str, dict] = {}
    for row in rows:
        item_id = row["item_id"]
        product = products.setdefault(
            item_id,
            {"item_id": item_id, "item": row["product_name"], "matches": {}, "matched": False},
        )
        if row["match_id"] is None:
            continue
        product["matched"] = True
        match_id = row["match_id"]
        match = product["matches"].setdefault(
            match_id,
            {
                "matched_product": row["matched_name"],
                "match_type": row["match_type"],
                "pack_size": row["match_pack_size"],
                "pack_unit": row["match_pack_unit"],
                "stores": defaultdict(list),
            },
        )
        if row["store_id"] is not None:
            match["stores"][row["store_id"]].append(
                {
                    "store_id": row["store_id"],
                    "store_name": row["store_name"] or row["store_id"],
                    "price_minor": row["price_minor"],
                    "currency": row["currency"],
                    "observed_at": row["observed_at"],
                    "retrieved_at": row["retrieved_at"],
                    "source_checked_at": row["source_checked_at"],
                }
            )
    return products


def _classify(observations: list[dict], current_minor: int | None, thresholds: dict, as_of: date) -> dict:
    return price_drop_vs_history(
        observations,
        current_minor,
        percentile=thresholds["regular_price_percentile"],
        min_observations=thresholds["minimum_price_observations"],
        min_days=thresholds["minimum_price_distinct_days"],
        window_days=thresholds["history_window_days"],
        min_drop_percent=thresholds["minimum_price_drop_percent"],
        as_of=as_of,
    )


def _store_observations(product: dict) -> list[tuple[dict, list[dict]]]:
    stores: list[tuple[dict, list[dict]]] = []
    for match in product["matches"].values():
        for store in match["stores"].values():
            store.sort(key=lambda point: point["observed_at"])
            stores.append((match, store))
    return stores


def get_basket() -> BasketResponse:
    now = datetime.now(timezone.utc)
    thresholds = load_thresholds()
    with connect_readonly() as db:
        products = _group_rows(_history_rows(db))

    items: list[BasketItem] = []
    for product in products.values():
        current_options = []
        matched_product = None
        match_type = None
        for match, observations in _store_observations(product):
            matched_product = matched_product or match["matched_product"]
            match_type = match_type or match["match_type"]
            latest = observations[-1]
            fresh = is_fresh(latest["source_checked_at"], now, thresholds["freshness_days"])
            if fresh is not True:
                continue
            unit = _unit_value(latest["price_minor"], match["pack_size"], match["pack_unit"])
            current_options.append((latest, unit))
        cheapest = min(
            current_options,
            key=lambda option: option[1].amount if option[1] is not None else _money(option[0]["price_minor"]),
            default=None,
        )
        items.append(
            BasketItem(
                item_id=product["item_id"],
                item=product["item"],
                match_status="matched" if product["matched"] else "unmatched",
                matched_product=matched_product,
                match_type=match_type,
                cheapest_fresh_store=cheapest[0]["store_name"] if cheapest else None,
                current_price=_money(cheapest[0]["price_minor"]) if cheapest else None,
                currency=cheapest[0]["currency"] if cheapest else None,
                unit_price=cheapest[1] if cheapest else None,
                freshness="fresh" if cheapest else ("unknown" if not product["matched"] else "stale"),
            )
        )
    return BasketResponse(generated_at=now.isoformat(), items=items)


def get_item_history(item_id: str) -> ItemHistoryResponse:
    now = datetime.now(timezone.utc)
    thresholds = load_thresholds()
    with connect_readonly() as db:
        rows = _history_rows(db, item_id)
    if not rows:
        raise ItemNotFoundError(item_id)
    product = _group_rows(rows)[item_id]
    stores: list[StoreHistory] = []
    for match, observations in _store_observations(product):
        latest = observations[-1]
        estimate = _classify(observations, latest["price_minor"], thresholds, now.date())
        stores.append(
            StoreHistory(
                store_id=latest["store_id"],
                store_name=latest["store_name"],
                observations=[
                    PriceObservation(
                        observed_at=str(point["observed_at"]),
                        price=_money(point["price_minor"]),
                        currency=point["currency"],
                    )
                    for point in observations
                ],
                freshness=(
                    "unknown"
                    if is_fresh(latest["source_checked_at"], now, thresholds["freshness_days"]) is None
                    else (
                        "fresh"
                        if is_fresh(latest["source_checked_at"], now, thresholds["freshness_days"])
                        else "stale"
                    )
                ),
                inferred_regular_price=_money(estimate["regular_price_minor"]),
                regular_price_status=(
                    "insufficient data" if estimate["status"] == "insufficient data" else "available"
                ),
                percentile=float(thresholds["regular_price_percentile"]),
                observation_count=estimate["observations"],
                distinct_days=estimate["distinct_days"],
            )
        )
    return ItemHistoryResponse(item_id=item_id, item=product["item"], stores=stores)


def get_deals() -> DealsResponse:
    now = datetime.now(timezone.utc)
    thresholds = load_thresholds()
    with connect_readonly() as db:
        products = _group_rows(_history_rows(db))
    deals: list[Deal] = []
    for product in products.values():
        for match, observations in _store_observations(product):
            if not observations:
                continue
            latest = observations[-1]
            if is_fresh(latest["source_checked_at"], now, thresholds["freshness_days"]) is not True:
                continue
            result = _classify(observations, latest["price_minor"], thresholds, now.date())
            if not result["is_price_drop"]:
                continue
            regular = _money(result["regular_price_minor"])
            drop_percent = float(result["price_drop_percent"])
            deals.append(
                Deal(
                    item_id=product["item_id"],
                    item=product["item"],
                    store_id=latest["store_id"],
                    store_name=latest["store_name"],
                    current_price=_money(latest["price_minor"]),
                    currency=latest["currency"],
                    inferred_regular_price=regular,
                    price_drop_percent=round(drop_percent, 2),
                    label="price drop vs history",
                    observed_at=latest["observed_at"],
                )
            )
    return DealsResponse(generated_at=now.isoformat(), deals=deals)


def get_health() -> HealthResponse:
    with connect_readonly() as db:
        products = _group_rows(_history_rows(db))
        latest_import_row = db.execute(
            """SELECT started_at, finished_at, status, records_seen, records_added
               FROM import_runs ORDER BY started_at DESC, id DESC LIMIT 1"""
        ).fetchone()
        oldest, newest = db.execute(
            "SELECT MIN(substr(observed_at,1,10)), MAX(substr(observed_at,1,10)) FROM price_observations"
        ).fetchone()

    thresholds = load_thresholds()
    now = datetime.now(timezone.utc)
    stale_count = 0
    unmatched = []
    dates = []
    for product in products.values():
        if not product["matched"]:
            unmatched.append(product["item"])
        for _, observations in _store_observations(product):
            if observations:
                latest = observations[-1]
                if is_fresh(latest["source_checked_at"], now, thresholds["freshness_days"]) is not True:
                    stale_count += 1
    days_of_history = (
        (date.fromisoformat(newest) - date.fromisoformat(oldest)).days + 1 if oldest and newest else 0
    )
    last_import = (
        LastImport(**dict(latest_import_row)) if latest_import_row is not None else None
    )
    return HealthResponse(
        last_import=last_import,
        stale_count=stale_count,
        unmatched_items=unmatched,
        days_of_history=days_of_history,
    )
