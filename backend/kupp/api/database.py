"""Read-only SQLite connection helpers for the API."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from backend.kupp.config import DB_PATH


@contextmanager
def connect_readonly() -> Iterator[sqlite3.Connection]:
    """Open the configured database with SQLite's read-only URI mode."""
    uri = f"{DB_PATH.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()
