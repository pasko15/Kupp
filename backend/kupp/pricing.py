"""Pure deterministic price calculations for Kupp."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable


def unit_price(price_minor: int, pack_size: float | None, pack_unit: str | None) -> tuple[str, Decimal] | None:
    """Return (normalized unit, price in major currency units per normalized unit)."""
    if not pack_size or not pack_unit:
        return None
    price = Decimal(price_minor) / 100
    size = Decimal(str(pack_size))
    unit = pack_unit.strip().lower()
    if unit in {"g", "gram", "grams"}:
        return "kg", price / (size / 1000)
    if unit in {"kg", "kilogram", "kilograms"}:
        return "kg", price / size
    if unit in {"ml", "millilitre", "milliliter", "millilitres", "milliliters"}:
        return "l", price / (size / 1000)
    if unit in {"l", "litre", "liter", "litres", "liters"}:
        return "l", price / size
    if unit in {"piece", "pieces", "pcs", "stk", "unit", "units"}:
        return "unit", price / size
    return None


def _observation_date(point: dict) -> date:
    return date.fromisoformat(str(point["observed_at"])[:10])


def regular_price_estimate(
    observations: Iterable[dict],
    *,
    percentile: int | float,
    min_observations: int,
    min_days: int,
    window_days: int,
    as_of: date,
) -> dict:
    """Estimate regular price from the percentile of observed prices in a date window."""
    percentile = Decimal(str(percentile))
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be between 0 and 100")
    if window_days < 1:
        raise ValueError("window_days must be positive")

    start_date = as_of - timedelta(days=window_days - 1)
    points = [
        point
        for point in observations
        if start_date <= _observation_date(point) <= as_of
    ]
    dates = sorted({_observation_date(point) for point in points})
    result = {
        "observations": len(points),
        "distinct_days": len(dates),
        "oldest_observation": dates[0].isoformat() if dates else None,
        "newest_observation": dates[-1].isoformat() if dates else None,
    }
    if len(points) < min_observations or len(dates) < min_days:
        return {**result, "status": "insufficient data", "regular_price_minor": None}

    prices = sorted(Decimal(str(point["price_minor"])) for point in points)
    rank = percentile * Decimal(len(prices) - 1) / Decimal(100)
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(prices) - 1)
    fraction = rank - lower_index
    regular_price = prices[lower_index] + (prices[upper_index] - prices[lower_index]) * fraction
    return {**result, "status": "available", "regular_price_minor": regular_price}


def discount_percent(baseline_minor: int | float | Decimal | None, current_minor: int | None) -> Decimal | None:
    if baseline_minor is None or current_minor is None or baseline_minor <= 0:
        return None
    return (Decimal(str(baseline_minor)) - Decimal(current_minor)) * 100 / Decimal(str(baseline_minor))


def price_drop_vs_history(
    observations: Iterable[dict],
    current_minor: int | None,
    *,
    percentile: int | float,
    min_observations: int,
    min_days: int,
    window_days: int,
    min_drop_percent: Decimal | int | float,
    as_of: date,
) -> dict:
    """Classify a current price against its inferred historical regular price."""
    estimate = regular_price_estimate(
        observations,
        percentile=percentile,
        min_observations=min_observations,
        min_days=min_days,
        window_days=window_days,
        as_of=as_of,
    )
    if estimate["status"] == "insufficient data" or current_minor is None:
        return {
            **estimate,
            "status": "insufficient data",
            "price_drop_percent": None,
            "is_price_drop": False,
        }

    drop = discount_percent(estimate["regular_price_minor"], current_minor)
    is_drop = drop is not None and drop >= Decimal(str(min_drop_percent))
    return {
        **estimate,
        "status": "price drop vs history" if is_drop else "no price drop",
        "price_drop_percent": drop,
        "is_price_drop": is_drop,
    }
