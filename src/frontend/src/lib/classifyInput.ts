export type RunMode = 'none' | 'discovery' | 'analysis' | 'combined' | 'prompt';
export type InputKind = 'empty' | 'tickers' | 'prompt';

const TICKER_RE = /^[A-Z0-9]{1,5}(-[A-Z0-9]{1,5})?(\.[A-Z]{1,2})?$/;

export function classifyInput(raw: string): { kind: InputKind; tickers: string[] } {
  const trimmed = raw.trim();
  if (!trimmed) return { kind: 'empty', tickers: [] };

  const tokens = trimmed.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);
  const allTickers = tokens.length > 0 && tokens.every(t => TICKER_RE.test(t));

  if (allTickers) return { kind: 'tickers', tickers: tokens };
  return { kind: 'prompt', tickers: [] };
}

export function deriveRunMode(selectedStrategy: string, inputKind: InputKind): RunMode {
  const hasStrategy = selectedStrategy.length > 0;

  if (inputKind === 'prompt') return 'prompt';
  if (hasStrategy && inputKind === 'tickers') return 'combined';
  if (inputKind === 'empty') return 'discovery';
  if (inputKind === 'tickers') return 'analysis';
  return 'none';
}
