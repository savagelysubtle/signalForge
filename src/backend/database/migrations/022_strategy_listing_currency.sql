-- 022: Listing currency for strategy templates (USD vs CAD equity markets).

ALTER TABLE strategies ADD COLUMN IF NOT EXISTS listing_currency TEXT DEFAULT 'CAD';

COMMENT ON COLUMN strategies.listing_currency IS
    'USD = US-listed equities (FMP country US); CAD = Canada / TSX bias. Ignored for crypto strategies.';
