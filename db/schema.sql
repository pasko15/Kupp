PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    item_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    brand TEXT,
    variant TEXT,
    pack_size REAL CHECK (pack_size IS NULL OR pack_size > 0),
    pack_unit TEXT,
    ean TEXT,
    sweden_match_preference TEXT
        CHECK (sweden_match_preference IS NULL OR sweden_match_preference IN ('identical_only', 'equivalent_ok')),
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stores (
    store_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'NO',
    currency TEXT NOT NULL DEFAULT 'NOK'
);

CREATE TABLE IF NOT EXISTS product_matches (
    id INTEGER PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES products(item_id),
    source TEXT NOT NULL,
    source_product_id TEXT NOT NULL,
    source_ean TEXT,
    matched_name TEXT,
    pack_size REAL CHECK (pack_size IS NULL OR pack_size > 0),
    pack_unit TEXT,
    match_type TEXT NOT NULL CHECK (match_type IN ('identical', 'equivalent')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    notes TEXT,
    UNIQUE (item_id, source, source_product_id)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
    records_seen INTEGER NOT NULL DEFAULT 0 CHECK (records_seen >= 0),
    records_added INTEGER NOT NULL DEFAULT 0 CHECK (records_added >= 0),
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY,
    product_match_id INTEGER NOT NULL REFERENCES product_matches(id),
    store_id TEXT NOT NULL REFERENCES stores(store_id),
    price_minor INTEGER NOT NULL CHECK (price_minor >= 0),
    currency TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    source_checked_at TEXT,
    source TEXT NOT NULL,
    price_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK (price_type IN ('regular', 'promo', 'member', 'loyalty', 'unknown')),
    is_promo INTEGER CHECK (is_promo IS NULL OR is_promo IN (0, 1)),
    content_hash TEXT NOT NULL UNIQUE,
    freshness TEXT NOT NULL DEFAULT 'unknown'
        CHECK (freshness IN ('fresh', 'stale', 'unknown')),
    import_run_id INTEGER REFERENCES import_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_observations_match_store_date
    ON price_observations(product_match_id, store_id, observed_at);

CREATE TRIGGER IF NOT EXISTS price_observations_no_update
BEFORE UPDATE ON price_observations
BEGIN
    SELECT RAISE(ABORT, 'price_observations is append-only');
END;

CREATE TRIGGER IF NOT EXISTS price_observations_no_delete
BEFORE DELETE ON price_observations
BEGIN
    SELECT RAISE(ABORT, 'price_observations is append-only');
END;
