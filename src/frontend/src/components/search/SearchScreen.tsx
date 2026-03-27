import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Play, Loader2, XCircle,
  Search, Crosshair, Layers, MessageSquare,
  SlidersHorizontal,
} from 'lucide-react';
import { motion } from 'motion/react';
import clsx from 'clsx';
import { useStrategies } from '../../hooks/useStrategies';
import { usePipeline } from '../../hooks/usePipeline';
import { classifyInput, deriveRunMode } from '../../lib/classifyInput';
import type { RunMode } from '../../lib/classifyInput';
import type { ScreenerOverrides } from '../../types';
import logoIcon from '../../assets/signalforge-logo-icon.svg';

const COUNTRY_OPTIONS = [
  { value: '', label: 'Any Country' },
  { value: 'CA', label: 'Canada' },
  { value: 'US', label: 'United States' },
  { value: 'GB', label: 'United Kingdom' },
  { value: 'DE', label: 'Germany' },
  { value: 'AU', label: 'Australia' },
] as const;

const EXCHANGE_OPTIONS = [
  { value: '', label: 'Any Exchange' },
  { value: 'TSX', label: 'TSX' },
  { value: 'TSXV', label: 'TSXV' },
  { value: 'NYSE', label: 'NYSE' },
  { value: 'NASDAQ', label: 'NASDAQ' },
  { value: 'AMEX', label: 'AMEX' },
  { value: 'LSE', label: 'LSE' },
  { value: 'ASX', label: 'ASX' },
  { value: 'XETR', label: 'XETR' },
] as const;

const SECTOR_OPTIONS = [
  { value: '', label: 'Any Sector' },
  { value: 'Technology', label: 'Technology' },
  { value: 'Healthcare', label: 'Healthcare' },
  { value: 'Financial Services', label: 'Financials' },
  { value: 'Energy', label: 'Energy' },
  { value: 'Consumer Cyclical', label: 'Consumer Cyclical' },
  { value: 'Consumer Defensive', label: 'Consumer Defensive' },
  { value: 'Industrials', label: 'Industrials' },
  { value: 'Basic Materials', label: 'Basic Materials' },
  { value: 'Communication Services', label: 'Communication' },
  { value: 'Utilities', label: 'Utilities' },
  { value: 'Real Estate', label: 'Real Estate' },
] as const;

const MARKET_CAP_OPTIONS = [
  { value: '', label: 'Any Cap', min: null, max: null },
  { value: 'micro', label: 'Micro (<$300M)', min: null, max: 300_000_000 },
  { value: 'small', label: 'Small ($300M-$2B)', min: 300_000_000, max: 2_000_000_000 },
  { value: 'mid', label: 'Mid ($2B-$10B)', min: 2_000_000_000, max: 10_000_000_000 },
  { value: 'large', label: 'Large ($10B-$100B)', min: 10_000_000_000, max: 100_000_000_000 },
  { value: 'mega', label: 'Mega (>$100B)', min: 100_000_000_000, max: null },
] as const;

const MODE_CONFIG: Record<RunMode, { label: string; color: string; icon: React.ReactNode }> = {
  none: { label: '', color: '', icon: null },
  discovery: { label: 'Discovery', color: 'text-accent-profit', icon: <Search className="w-4 h-4" /> },
  analysis: { label: 'Analysis', color: 'text-accent-signal', icon: <Crosshair className="w-4 h-4" /> },
  combined: { label: 'Combined', color: 'text-accent-alert', icon: <Layers className="w-4 h-4" /> },
  prompt: { label: 'Prompt', color: 'text-accent-electric', icon: <MessageSquare className="w-4 h-4" /> },
};

const MODE_BG: Record<RunMode, string> = {
  none: '',
  discovery: 'bg-accent-profit-dim border-accent-profit/20',
  analysis: 'bg-accent-signal-dim border-accent-signal/20',
  combined: 'bg-accent-alert-dim border-accent-alert/20',
  prompt: 'bg-accent-electric-dim border-accent-electric/20',
};

export function SearchScreen() {
  const navigate = useNavigate();
  const { templates, strategies } = useStrategies();
  const { runPipeline, isRunning, error } = usePipeline();

  const [selectedStrategy, setSelectedStrategy] = useState<string>('');
  const [inputText, setInputText] = useState<string>('');
  const [showFilters, setShowFilters] = useState(false);
  const [filterCountry, setFilterCountry] = useState('');
  const [filterExchange, setFilterExchange] = useState('');
  const [filterSector, setFilterSector] = useState('');
  const [filterMarketCap, setFilterMarketCap] = useState('');

  const allStrategies = [...templates, ...strategies].filter(
    (s, i, arr) => arr.findIndex((t) => t.id === s.id) === i,
  );

  const { kind: inputKind, tickers: parsedTickers } = useMemo(
    () => classifyInput(inputText),
    [inputText],
  );

  const runMode = useMemo(
    () => deriveRunMode(selectedStrategy, inputKind),
    [selectedStrategy, inputKind],
  );

  const modeConfig = MODE_CONFIG[runMode];

  const buildOverrides = (): ScreenerOverrides | undefined => {
    const capOption = MARKET_CAP_OPTIONS.find(o => o.value === filterMarketCap);
    const overrides: ScreenerOverrides = {};
    if (filterCountry) overrides.country = filterCountry;
    if (filterExchange) overrides.exchange = filterExchange;
    if (filterSector) overrides.sector = filterSector;
    if (capOption && capOption.min !== null) overrides.market_cap_min = capOption.min;
    if (capOption && capOption.max !== null) overrides.market_cap_max = capOption.max;
    return Object.keys(overrides).length > 0 ? overrides : undefined;
  };

  const activeFilterCount = [filterCountry, filterExchange, filterSector, filterMarketCap].filter(Boolean).length;

  const handleRun = async () => {
    if (runMode === 'none') return;

    const strategyId = selectedStrategy || undefined;
    const tickers = parsedTickers.length > 0 ? parsedTickers : undefined;
    const userPrompt = inputKind === 'prompt' ? inputText.trim() : undefined;
    const overrides = buildOverrides();

    try {
      const result = await runPipeline(strategyId, tickers, userPrompt, overrides);
      navigate(`/?run=${result.run_id}`);
    } catch (err) {
      console.error(err);
    }
  };

  const runningLabel = (() => {
    if (runMode === 'prompt') return 'Searching with prompt...';
    const stratName = allStrategies.find(s => s.id === selectedStrategy)?.name;
    if (stratName) return `Running ${stratName}...`;
    if (parsedTickers.length > 0) return `Analyzing ${parsedTickers.join(', ')}...`;
    return 'Discovering market movers...';
  })();

  return (
    <div className="min-h-full flex flex-col items-center relative overflow-y-auto px-6 py-6">
      {/* Background decorations */}
      <div className="absolute inset-0 bg-candle-motif opacity-[0.04] pointer-events-none" />
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] glow-signal rounded-full opacity-30 pointer-events-none" />

      <div className="relative z-10 w-full max-w-3xl flex flex-col items-center my-auto">
        {/* Hero */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
          className="flex flex-col items-center mb-6"
        >
          <div className="relative mb-3">
            <div className="absolute -inset-3 glow-signal rounded-full opacity-50" />
            <img src={logoIcon} alt="" className="w-11 h-11 relative" />
          </div>
          <h1 className="text-2xl font-display font-bold text-text-primary mb-1.5">
            What would you like to analyze?
          </h1>
          <p className="text-text-secondary font-body text-xs">
            Enter tickers, a prompt, or choose a strategy below
          </p>
        </motion.div>

        {/* Search input */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1, ease: 'easeOut' }}
          className="w-full mb-5"
        >
          <div className="relative">
            <input
              type="text"
              placeholder={
                selectedStrategy
                  ? 'Tickers (AAPL, NVDA) or prompt or leave empty for discovery'
                  : 'Tickers (AAPL, NVDA) or prompt ("find undervalued tech stocks")'
              }
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              disabled={isRunning}
              onKeyDown={(e) => { if (e.key === 'Enter' && runMode !== 'none') handleRun(); }}
              className="w-full bg-bg-concrete border border-border-gutter rounded-lg px-4 py-3 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal transition-colors font-body"
            />
            {runMode !== 'none' && !isRunning && (
              <span className={clsx(
                'absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-1.5 text-xs font-display px-2.5 py-1 rounded-md border',
                MODE_BG[runMode],
                modeConfig.color,
              )}>
                {modeConfig.icon}
                {modeConfig.label}
              </span>
            )}
          </div>
        </motion.div>

        {/* Screener filter overrides */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.15, ease: 'easeOut' }}
          className="w-full mb-4"
        >
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="flex items-center gap-1.5 text-[11px] font-display text-text-muted uppercase tracking-wider mb-2 hover:text-text-secondary transition-colors"
          >
            <SlidersHorizontal className="w-3 h-3" />
            Screener Filters
            {activeFilterCount > 0 && (
              <span className="bg-accent-signal/20 text-accent-signal text-[9px] px-1.5 py-0.5 rounded-full font-bold">
                {activeFilterCount}
              </span>
            )}
          </button>

          {showFilters && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2, ease: 'easeOut' }}
              className="grid grid-cols-2 lg:grid-cols-4 gap-2 mb-2"
            >
              <select
                value={filterCountry}
                onChange={(e) => setFilterCountry(e.target.value)}
                disabled={isRunning}
                className="bg-bg-concrete border border-border-gutter rounded-md px-2.5 py-2 text-xs text-text-primary font-body focus:outline-none focus:border-accent-signal transition-colors appearance-none cursor-pointer"
              >
                {COUNTRY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>

              <select
                value={filterExchange}
                onChange={(e) => setFilterExchange(e.target.value)}
                disabled={isRunning}
                className="bg-bg-concrete border border-border-gutter rounded-md px-2.5 py-2 text-xs text-text-primary font-body focus:outline-none focus:border-accent-signal transition-colors appearance-none cursor-pointer"
              >
                {EXCHANGE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>

              <select
                value={filterSector}
                onChange={(e) => setFilterSector(e.target.value)}
                disabled={isRunning}
                className="bg-bg-concrete border border-border-gutter rounded-md px-2.5 py-2 text-xs text-text-primary font-body focus:outline-none focus:border-accent-signal transition-colors appearance-none cursor-pointer"
              >
                {SECTOR_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>

              <select
                value={filterMarketCap}
                onChange={(e) => setFilterMarketCap(e.target.value)}
                disabled={isRunning}
                className="bg-bg-concrete border border-border-gutter rounded-md px-2.5 py-2 text-xs text-text-primary font-body focus:outline-none focus:border-accent-signal transition-colors appearance-none cursor-pointer"
              >
                {MARKET_CAP_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </motion.div>
          )}
        </motion.div>

        {/* Strategy cards */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2, ease: 'easeOut' }}
          className="w-full mb-6"
        >
          <h2 className="text-[11px] font-display text-text-muted uppercase tracking-wider mb-2">
            Strategy
          </h2>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
            {/* No strategy card */}
            <button
              onClick={() => setSelectedStrategy('')}
              disabled={isRunning}
              className={clsx(
                "text-left rounded-lg p-3 border transition-all duration-200",
                !selectedStrategy
                  ? "bg-bg-concrete border-accent-signal/40 ring-1 ring-accent-signal/20"
                  : "bg-bg-concrete border-border-gutter hover:border-accent-signal"
              )}
            >
              <div className="font-display font-bold text-xs text-text-primary mb-0.5">No Strategy</div>
              <p className="text-[11px] text-text-muted font-body line-clamp-2">
                Analyze tickers directly or use a prompt
              </p>
            </button>

            {allStrategies.map((strategy) => (
              <button
                key={strategy.id}
                onClick={() => setSelectedStrategy(strategy.id)}
                disabled={isRunning}
                className={clsx(
                  "text-left rounded-lg p-3 border transition-all duration-200",
                  selectedStrategy === strategy.id
                    ? "bg-bg-concrete border-accent-signal/40 ring-1 ring-accent-signal/20"
                    : "bg-bg-concrete border-border-gutter hover:border-accent-signal"
                )}
              >
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="font-display font-bold text-xs text-text-primary truncate">
                    {strategy.name}
                  </span>
                  {strategy.is_template && (
                    <span className="text-[9px] font-display text-text-muted bg-bg-steel px-1.5 py-0.5 rounded shrink-0">
                      TPL
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-text-muted font-body line-clamp-1">
                  {strategy.description}
                </p>
              </button>
            ))}
          </div>
        </motion.div>

        {/* Run button + status */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.3, ease: 'easeOut' }}
          className="flex flex-col items-center gap-3"
        >
          <button
            onClick={handleRun}
            disabled={isRunning || runMode === 'none'}
            className="flex items-center gap-2 bg-accent-signal text-bg-void px-6 py-2.5 rounded-lg text-sm font-bold hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200 font-display"
          >
            {isRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {isRunning ? 'Analyzing...' : 'Run Analysis'}
          </button>

          {isRunning && (
            <span className="flex items-center gap-2 text-accent-signal font-display text-xs">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-signal opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-accent-signal" />
              </span>
              {runningLabel}
            </span>
          )}

          {!isRunning && error && (
            <span className="flex items-center gap-2 text-accent-loss text-xs font-body" title={error}>
              <XCircle className="w-4 h-4" />
              {error}
            </span>
          )}
        </motion.div>
      </div>
    </div>
  );
}
