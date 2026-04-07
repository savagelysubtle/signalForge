import { useState } from 'react';
import { Radar, Loader2, Activity, TrendingUp, TrendingDown, AlertTriangle, Filter } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import clsx from 'clsx';
import { useScanner } from '../../hooks/useScanner';
import { ScannerResultsGrid } from './ScannerResultsGrid';
import type { ScannerFilters } from '../../types';

const REGIME_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  trending_bull: { label: 'Bull Trend', color: 'text-accent-profit', icon: <TrendingUp className="w-3 h-3" /> },
  trending_bear: { label: 'Bear Trend', color: 'text-accent-loss', icon: <TrendingDown className="w-3 h-3" /> },
  high_volatility: { label: 'High Vol', color: 'text-accent-alert', icon: <AlertTriangle className="w-3 h-3" /> },
  range_bound: { label: 'Range', color: 'text-text-secondary', icon: <Activity className="w-3 h-3" /> },
  risk_off: { label: 'Risk Off', color: 'text-accent-loss', icon: <AlertTriangle className="w-3 h-3" /> },
  sector_rotation: { label: 'Rotation', color: 'text-accent-electric', icon: <Activity className="w-3 h-3" /> },
};

interface PrescreenerPanelProps {
  onRunScannerStrategy: (strategyType: string, tickers: string[]) => void | Promise<void>;
  disabled?: boolean;
  filters?: ScannerFilters;
  activeFilterCount?: number;
}

export function PrescreenerPanel({ onRunScannerStrategy, disabled, filters, activeFilterCount = 0 }: PrescreenerPanelProps) {
  const {
    isScanning, scanStatus, latestResults, marketState, error, runScan, fetchLatest,
  } = useScanner();
  const [actionableOnly, setActionableOnly] = useState(() => {
    try { return localStorage.getItem('scanner_actionable_only') === 'true'; } catch { return false; }
  });

  const regime = marketState?.regime_type ?? 'trending_bull';
  const regimeInfo = REGIME_CONFIG[regime] ?? REGIME_CONFIG.trending_bull;
  const totalSetups = latestResults?.total_setups ?? 0;
  const lastScan = latestResults?.last_scan_at;

  const handleRunScan = () => {
    const scanFilters: ScannerFilters = {};
    if (filters?.country) scanFilters.country = filters.country;
    if (filters?.exchange) scanFilters.exchange = filters.exchange;
    if (filters?.sector) scanFilters.sector = filters.sector;
    if (filters?.market_cap_min) scanFilters.market_cap_min = filters.market_cap_min;
    if (filters?.market_cap_max) scanFilters.market_cap_max = filters.market_cap_max;
    runScan(Object.keys(scanFilters).length > 0 ? scanFilters : undefined);
  };

  const toggleActionable = () => {
    const next = !actionableOnly;
    setActionableOnly(next);
    try { localStorage.setItem('scanner_actionable_only', String(next)); } catch { /* noop */ }
    fetchLatest(next);
  };

  const formatTime = (iso: string | null | undefined) => {
    if (!iso) return 'Never';
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch { return 'Unknown'; }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className="w-full mb-5"
    >
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Radar className="w-4 h-4 text-accent-electric" />
          <span className="text-[11px] font-display text-text-secondary uppercase tracking-wider">
            Prescreener
          </span>
          {activeFilterCount > 0 && (
            <span className="flex items-center gap-1 text-[9px] font-display text-accent-electric bg-accent-electric/10 border border-accent-electric/20 px-1.5 py-0.5 rounded-full">
              <Filter className="w-2.5 h-2.5" />
              {activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''}
            </span>
          )}
          {totalSetups > 0 && (
            <span className="text-[10px] font-display text-accent-profit bg-accent-profit/10 border border-accent-profit/20 px-1.5 py-0.5 rounded-full">
              {totalSetups} setups
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Actionable toggle */}
          <button
            onClick={toggleActionable}
            className={clsx(
              'flex items-center gap-1 text-[10px] font-display px-2 py-0.5 rounded-full border transition-colors',
              actionableOnly
                ? 'text-accent-profit bg-accent-profit/15 border-accent-profit/30'
                : 'text-text-muted bg-bg-steel border-border-gutter hover:border-text-muted',
            )}
          >
            Actionable Only
          </button>

          {/* Regime badge */}
          {marketState && (
            <div className={clsx(
              'flex items-center gap-1 text-[10px] font-display px-2 py-0.5 rounded-full border bg-bg-concrete',
              regimeInfo.color,
              `border-current/20`,
            )}>
              {regimeInfo.icon}
              {regimeInfo.label}
              {marketState.vix_spot != null && (
                <span className="text-text-muted ml-1">VIX {marketState.vix_spot.toFixed(1)}</span>
              )}
            </div>
          )}

          {/* Last scan time */}
          <span className="text-[10px] text-text-muted font-body">
            Last: {formatTime(lastScan)}
          </span>

          {/* Run button */}
          <button
            onClick={handleRunScan}
            disabled={isScanning || disabled}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-display font-bold transition-all duration-200',
              isScanning
                ? 'bg-accent-electric text-white cursor-wait'
                : 'bg-accent-electric text-white hover:brightness-110 border border-accent-electric',
              (disabled) && 'opacity-40 cursor-not-allowed',
            )}
          >
            {isScanning ? (
              <>
                <Loader2 className="w-3 h-3 animate-spin" />
                Scanning...
              </>
            ) : (
              <>
                <Radar className="w-3 h-3" />
                Run Prescreener
              </>
            )}
          </button>
        </div>
      </div>

      {/* Scan progress */}
      <AnimatePresence>
        {isScanning && scanStatus && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-3"
          >
            <div className="bg-bg-concrete border border-border-gutter rounded-lg px-3 py-2 flex items-center gap-3">
              <Loader2 className="w-3.5 h-3.5 text-accent-electric animate-spin shrink-0" />
              <div className="flex-1">
                <div className="text-[11px] font-display text-text-primary">
                  Scanning {scanStatus.universe_size ?? '...'} tickers
                </div>
                {scanStatus.setups_found != null && scanStatus.setups_found > 0 && (
                  <div className="text-[10px] text-accent-profit font-body">
                    {scanStatus.setups_found} setups found so far
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Error */}
      {error && (
        <div className="text-[11px] text-accent-loss font-body mb-2">{error}</div>
      )}

      {/* Results grid */}
      {latestResults && totalSetups > 0 && (
        <ScannerResultsGrid
          results={latestResults}
          onRunScannerStrategy={onRunScannerStrategy}
          disabled={disabled || isScanning}
        />
      )}
    </motion.div>
  );
}
