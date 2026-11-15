# Project decisions

- Use SQLite for this single-user, local price tracker.
- Store prices as append-only observations and deduplicate imports with a content hash.
- Use Kassalapp as the current Norwegian source. Its bulk endpoint returns daily minimum prices and does not label promotions or member prices, so those fields remain unknown.
- Keep freshness, history-window, percentile, and price-drop thresholds in `config/thresholds.yaml` rather than application code.
- Keep the active database at `data/kupp.db`; configure all project paths in `backend/kupp/config.py`.
- Keep product matching separate from price calculations. Pricing functions have no database or HTTP access.\n