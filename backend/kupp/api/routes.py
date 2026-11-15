"""FastAPI routes for read-only Kupp data."""

from fastapi import APIRouter

from backend.kupp.api import service
from backend.kupp.api.models import BasketResponse, DealsResponse, HealthResponse, ItemHistoryResponse

router = APIRouter()


@router.get("/basket", response_model=BasketResponse, tags=["basket"])
def basket() -> BasketResponse:
    return service.get_basket()


@router.get("/items/{item_id}/history", response_model=ItemHistoryResponse, tags=["items"])
def item_history(item_id: str) -> ItemHistoryResponse:
    return service.get_item_history(item_id)


@router.get("/deals", response_model=DealsResponse, tags=["deals"])
def deals() -> DealsResponse:
    return service.get_deals()


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return service.get_health()
