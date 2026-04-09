/**
 * Canonical ticker keys for UI joins when the backend may use ``AAPL`` or ``NASDAQ:AAPL``.
 * Must stay aligned with ``utils.ticker.canonical_ticker_match_key`` in the backend (US list).
 */

const US_STOCK_TV_EXCHANGES = new Set([
  'AMEX',
  'BATS',
  'GREY',
  'NASDAQ',
  'NASDAQCM',
  'NASDAQGM',
  'NASDAQGS',
  'NYSE',
  'NYSEAMERICAN',
  'OTC',
  'OTCMKTS',
  'PINK',
  'US',
]);

/**
 * Uppercase match key: US ``EXCHANGE:SYMBOL`` collapses to ``SYMBOL``; intl. keeps full id.
 */
export function canonicalTickerMatchKey(ticker: string): string {
  const t = ticker.trim().toUpperCase();
  const colon = t.indexOf(':');
  if (colon === -1) return t;
  const exchange = t.slice(0, colon);
  const symbol = t.slice(colon + 1);
  if (US_STOCK_TV_EXCHANGES.has(exchange)) return symbol;
  return t;
}

export function tickersAliasEqual(a: string, b: string): boolean {
  return canonicalTickerMatchKey(a) === canonicalTickerMatchKey(b);
}
