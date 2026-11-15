"""HTTP client for the Kassalapp API."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.kupp.config import ENV_PATH


BASE_URL = "https://kassal.app/api/v1"


def load_dotenv(path: Path = ENV_PATH) -> None:
    """Load KEY=VALUE lines without replacing existing environment values."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if separator and name.strip() and name.strip() not in os.environ:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[name.strip()] = value


def get_api_key() -> str:
    load_dotenv()
    key = os.environ.get("KASSALAPP_API_KEY")
    if not key:
        raise RuntimeError("Missing KASSALAPP_API_KEY in environment or .env")
    return key


def fetch_history(api_key: str, eans: list[str], days: int = 30, aggregation: str = "min") -> dict:
    request = Request(
        f"{BASE_URL}/products/prices-bulk",
        data=json.dumps({"eans": eans, "days": days, "aggregation": aggregation}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("Kassalapp rate limit reached (HTTP 429).") from exc
        if exc.code in (401, 403):
            raise RuntimeError(f"Kassalapp rejected the API key (HTTP {exc.code}).") from exc
        raise RuntimeError(f"Kassalapp returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Kassalapp: {exc.reason}") from exc
