import type { StrategyConfig } from '../types';

/**
 * Maps prescanner rule keys (backend `strategy_scanner.STRATEGY_RULES`) to a unique
 * substring of the corresponding template name in `templates/strategies.json`.
 */
const SCANNER_RULE_TO_NAME_HINT: Record<string, string> = {
  swing: 'Momentum Breakout',
  momentum_breakout: 'Momentum Breakout',
  bollinger_band_squeeze_breakout: 'Bollinger Band Squeeze',
  ema_21_pullback: 'EMA 21 Pullback',
  ema_50_200_golden_cross: 'EMA 50/200',
  mean_reversion: 'Mean Reversion',
  value_accumulation: 'Value Accumulation',
  earnings_play: 'Earnings Play',
  ema_stack_momentum: 'EMA Stack Momentum',
  intraday_scalp: 'Intraday Scalp',
  opening_range_breakout: 'Opening Range Breakout',
  vwap_reversal_scalp: 'VWAP Reversal',
  crypto_swing: 'Crypto Swing',
  crypto_intraday: 'Crypto Intraday',
};

/**
 * Resolve a scanner rule key to the user's strategy template (or clone) in `configs`.
 */
export function resolveStrategyConfigForScannerRule(
  ruleKey: string,
  configs: StrategyConfig[],
): StrategyConfig | undefined {
  const hint = SCANNER_RULE_TO_NAME_HINT[ruleKey];
  if (hint) {
    const byHint = configs.find((c) => c.name.includes(hint));
    if (byHint) return byHint;
  }
  const fuzzy = ruleKey.replace(/_/g, ' ');
  return configs.find(
    (c) =>
      (c.strategy_type != null && c.strategy_type === ruleKey) ||
      c.name.toLowerCase().includes(fuzzy),
  );
}
