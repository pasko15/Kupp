"""Deterministic price and deal calculations for Kupp."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from statistics import median
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


def nonpromo_baseline(
    observations: Iterable[dict],
    *,
    min_observations: int,
    min_days: int,
) -> dict:
    """Compute a median baseline only from observations explicitly marked non-promo."""
    points = [point for point in observations if point.get("is_promo") == 0]
    dates = sorted({date.fromisoformat(str(point["observed_at"])[:10]) for point in points})
    enough = len(points) >= min_observations and len(dates) >= min_days
    if not enough:
        return {
            "baseline_price_minor": None,
            "observations": len(points),
            "distinct_days": len(dates),
            "eligible": False,
        }
    return {
        "baseline_price_minor": median(point["price_minor"] for point in points),
        "observations": len(points),
        "distinct_days": len(dates),
        "eligible": True,
    }


def discount_percent(baseline_minor: int | float | None, current_minor: int | None) -> Decimal | None:
    if baseline_minor is None or current_minor is None or baseline_minor <= 0:
        return None
    return (Decimal(str(baseline_minor)) - Decimal(current_minor)) * 100 / Decimal(str(baseline_minor))


def verify_deal(
    baseline: dict,
    current_minor: int | None,
    *,
    min_discount_percent: Decimal | int | float,
) -> dict:
    pct = discount_percent(baseline["baseline_price_minor"], current_minor)
    threshold = Decimal(str(min_discount_percent))
    verified = bool(
        baseline["eligible"]
        and pct is not None
        and pct >= threshold
    )
    return {
        "discount_percent": pct,
        "verified": verified,
        "reason": None if verified else "insufficient explicitly non-promo history or discount below threshold",
    }
