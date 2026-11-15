"""Central project paths and runtime settings.

Run Kupp commands from the project root, or set KUPP_PROJECT_ROOT explicitly.
KUPP_DB_PATH may be absolute or relative to the project root.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


PROJECT_ROOT = Path(
    os.environ.get("KUPP_PROJECT_ROOT", Path(__file__).resolve().parents[2])
).resolve()
DATA_DIR = PROJECT_ROOT / "data"
ENV_PATH = PROJECT_ROOT / ".env"
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
THRESHOLDS_PATH = PROJECT_ROOT / "config" / "thresholds.yaml"


def project_path(value: str | None, default: Path) -> Path:
    if not value:
        return default.resolve()
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


DB_PATH = project_path(os.environ.get("KUPP_DB_PATH"), DATA_DIR / "kupp.db")
BASKET_PATH = project_path(os.environ.get("KUPP_BASKET_PATH"), DATA_DIR / "basket.csv")
MATCHES_PATH = project_path(os.environ.get("KUPP_MATCHES_PATH"), DATA_DIR / "matches.csv")
SPIKE_SAMPLE_PATH = project_path(None, PROJECT_ROOT / "scratch" / "kassalapp-sample.json")
REPORT_PATH = project_path(None, DATA_DIR / "price-report.json")


def load_thresholds() -> dict[str, int | float]:
    with THRESHOLDS_PATH.open(encoding="utf-8") as file:
        values = yaml.safe_load(file)
    if not isinstance(values, dict):
        raise ValueError(f"Threshold config must be a YAML mapping: {THRESHOLDS_PATH}")
    return values
