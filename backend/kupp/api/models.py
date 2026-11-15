"""Pydantic response contracts for Kupp's read-only API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class UnitPrice(BaseModel):
    amount: float
    currency_per: str


class BasketItem(BaseModel):
    item_id: str
    item: str
    match_status: Literal["matched", "unmatched"]
    matched_product: str | None
    match_type: str | None
    cheapest_fresh_store: str | None
    current_price: float | None
    currency: str | None
    unit_price: UnitPrice | None
    freshness: Literal["fresh", "stale", "unknown"]


class BasketResponse(BaseModel):
    generated_at: str
    items: list[BasketItem]


class PriceObservation(BaseModel):
    observed_at: str
    price: float
    currency: str


class StoreHistory(BaseModel):
    store_id: str
    store_name: str
    observations: list[PriceObservation]
    freshness: Literal["fresh", "stale", "unknown"]
    inferred_regular_price: float | None
    regular_price_status: Literal["available", "insufficient data"]
    percentile: float
    observation_count: int
    distinct_days: int


class ItemHistoryResponse(BaseModel):
    item_id: str
    item: str
    stores: list[StoreHistory]


class Deal(BaseModel):
    item_id: str
    item: str
    store_id: str
    store_name: str
    current_price: float
    currency: str
    inferred_regular_price: float
    price_drop_percent: float
    label: Literal["price drop vs history"]
    observed_at: str


class DealsResponse(BaseModel):
    generated_at: str
    deals: list[Deal]


class LastImport(BaseModel):
    started_at: str
    finished_at: str | None
    status: str
    records_seen: int
    records_added: int


class HealthResponse(BaseModel):
    last_import: LastImport | None
    stale_count: int
    unmatched_items: list[str]
    days_of_history: int
