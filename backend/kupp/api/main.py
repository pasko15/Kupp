"""Kupp read-only FastAPI application."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.kupp.api.routes import router
from backend.kupp.api.service import ItemNotFoundError

app = FastAPI(title="Kupp API", description="Read-only grocery price tracker API", version="1.0.0")
app.include_router(router)


@app.exception_handler(ItemNotFoundError)
def item_not_found(_: Request, exc: ItemNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": f"Item not found: {exc.args[0]}"})
