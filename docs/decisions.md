# Project decisions

- Use SQLite for this single-user, local price tracker.
- Store prices as append-only observations and deduplicate imports with a content hash.
- Use Kassalapp as the current Norwegian source. Its bulk endpoint returns daily prices with a configurable aggregation, and does not label promotions or member prices, so those fields remain unknown.
- Infer a store-specific regular price from the 75th percentile of daily minimum prices over the last 90 days. Require at least 60 observations on 60 distinct days; shorter histories are insufficient data.
- Label a current price at least 10% below that estimate as a price drop vs history, not as a confirmed promotion.
- The 75th percentile assumes a product is discounted on fewer than roughly 25% of observed days. If discounts are more common, or a real price increase occurred during the 90-day window, the estimate may not represent today's regular price. This is acceptable for a personal comparison tool, not proof of a promotion.
- Kassalapp's daily aggregation gives at most one selected price per product, store and date, so observations are day-weighted rather than price-change-weighted. Missing dates are not imputed; they can reduce the effective history length.
- Keep freshness, history-window, percentile, minimum-history, and price-drop thresholds in `config/thresholds.yaml` rather than application code.
- Keep the active database at `data/kupp.db`; configure all project paths in `backend/kupp/config.py`.
- Keep product matching separate from price calculations. Pricing functions have no database or HTTP access.
