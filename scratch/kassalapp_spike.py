"""Fetch a small Norwegian product and price-history sample from Kassalapp."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.kupp.config import ENV_PATH, SPIKE_SAMPLE_PATH

BASE_URL = "https://kassal.app/api/v1"
OUTPUT = SPIKE_SAMPLE_PATH
SEARCH_TERMS = [
    "melk", "egg", "brød", "kaffe", "smør", "ost",
    "havregryn", "pasta", "kylling", "kjøttdeig", "ris", "yoghurt",
]


def load_dotenv() -> None:
    """Load simple KEY=VALUE lines without overriding the process environment."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if separator and key.strip() and key.strip() not in os.environ:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ[key.strip()] = value


def request_json(path: str, api_key: str, *, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(
                f"Kassalapp rejected the API key (HTTP {exc.code}). Check access/key."
            ) from exc
        if exc.code == 429:
            raise RuntimeError("Kassalapp rate limit reached (HTTP 429).") from exc
        if exc.code == 422:
            detail = exc.read(1200).decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Kassalapp rejected the request parameters (HTTP 422): {detail}") from exc
        raise RuntimeError(f"Kassalapp returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Kassalapp: {exc.reason}") from exc


def main() -> int:
    load_dotenv()
    api_key = os.environ.get("KASSALAPP_API_KEY")
    if not api_key:
        print(
            "Missing KASSALAPP_API_KEY. Create a hobby API key at https://kassal.app/api, "
            "then set it in your shell and rerun this script.",
            file=sys.stderr,
        )
        return 2

    sample = []
    seen_eans = set()
    for term in SEARCH_TERMS:
        query = urlencode(
            {
                "search": term,
                "size": 20,
                "unique": 1,
                "exclude_without_ean": 1,
            }
        )
        listing = request_json(f"/products?{query}", api_key)
        added_for_term = 0
        for product in listing.get("data", []):
            ean = product.get("ean")
            if (
                not ean
                or ean in seen_eans
                or product.get("current_price") is None
                or not product.get("store")
            ):
                continue
            product["spike_search_term"] = term
            sample.append(product)
            seen_eans.add(ean)
            added_for_term += 1
            if len(sample) == 50 or added_for_term == 5:
                break
        if len(sample) >= 50:
            break

    if not sample:
        raise RuntimeError("Product searches returned no products with an EAN, store, and current price.")

    history_response = request_json(
        "/products/prices-bulk",
        api_key,
        body={
            "eans": [p["ean"] for p in sample],
            "days": 30,
            "aggregation": "min",
        },
    )

    payload = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source": "Kassalapp API",
        "search_terms": SEARCH_TERMS,
        "sample_size": len(sample),
        "products": sample,
        "price_history": history_response.get("data", []),
        "history_meta": history_response.get("meta", {}),
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    histories = payload["price_history"]
    history_points = sum(len(item.get("price_history", [])) for item in histories)
    print(f"Saved {len(sample)} products and {history_points} history points to {OUTPUT}")
    print("Review product store codes and price dates before treating prices as fresh.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
