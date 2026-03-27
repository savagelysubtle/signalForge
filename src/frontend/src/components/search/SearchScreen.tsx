import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Play, Loader2, XCircle,
  Search, Crosshair, Layers, MessageSquare,
} from 'lucide-react';
import { motion } from 'motion/react';
import clsx from 'clsx';
import { useStrategies } from '../../hooks/useStrategies';
import { usePipeline } from '../../hooks/usePipeline';
import { classifyInput, deriveRunMode } from '../../lib/classifyInput';
import type { RunMode } from '../../lib/classifyInput';
import logoIcon from '../../assets/signalforge-logo-icon.svg';

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

  const handleRun = async () => {
    if (runMode === 'none') return;

    const strategyId = selectedStrategy || undefined;
    const tickers = parsedTickers.length > 0 ? parsedTickers : undefined;
    const userPrompt = inputKind === 'prompt' ? inputText.trim() : undefined;

    try {
      const result = await runPipeline(strategyId, tickers, userPrompt);
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
    <div className="h-full flex flex-col items-center justify-center relative overflow-y-auto px-6 py-12">
      {/* Background decorations */}
      <div className="absolute inset-0 bg-candle-motif opacity-[0.04] pointer-events-none" />
      <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] glow-signal rounded-full opacity-30 pointer-events-none" />

      <div className="relative z-10 w-full max-w-3xl flex flex-col items-center">
        {/* Hero */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
          className="flex flex-col items-center mb-10"
        >
          <div className="relative mb-4">
            <div className="absolute -inset-4 glow-signal rounded-full opacity-50" />
            <img src={logoIcon} alt="" className="w-14 h-14 relative" />
          </div>
          <h1 className="text-3xl font-display font-bold text-text-primary mb-2">
            What would you like to analyze?
          </h1>
          <p className="text-text-secondary font-body text-sm">
            Enter tickers, a prompt, or choose a strategy below
          </p>
        </motion.div>

        {/* Search input */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1, ease: 'easeOut' }}
          className="w-full mb-6"
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
              className="w-full bg-bg-concrete border border-border-gutter rounded-xl px-5 py-4 text-base text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal transition-colors font-body"
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

        {/* Strategy cards */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2, ease: 'easeOut' }}
          className="w-full mb-8"
        >
          <h2 className="text-xs font-display text-text-muted uppercase tracking-wider mb-3">
            Strategy
          </h2>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            {/* No strategy card */}
            <button
              onClick={() => setSelectedStrategy('')}
              disabled={isRunning}
              className={clsx(
                "text-left rounded-xl p-4 border transition-all duration-200",
                !selectedStrategy
                  ? "bg-bg-concrete border-accent-signal/40 ring-1 ring-accent-signal/20"
                  : "bg-bg-concrete border-border-gutter hover:border-accent-signal"
              )}
            >
              <div className="font-display font-bold text-sm text-text-primary mb-1">No Strategy</div>
              <p className="text-xs text-text-muted font-body line-clamp-2">
                Analyze tickers directly or use a prompt
              </p>
            </button>

            {allStrategies.map((strategy) => (
              <button
                key={strategy.id}
                onClick={() => setSelectedStrategy(strategy.id)}
                disabled={isRunning}
                className={clsx(
                  "text-left rounded-xl p-4 border transition-all duration-200",
                  selectedStrategy === strategy.id
                    ? "bg-bg-concrete border-accent-signal/40 ring-1 ring-accent-signal/20"
                    : "bg-bg-concrete border-border-gutter hover:border-accent-signal"
                )}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-display font-bold text-sm text-text-primary truncate">
                    {strategy.name}
                  </span>
                  {strategy.is_template && (
                    <span className="text-[10px] font-display text-text-muted bg-bg-steel px-1.5 py-0.5 rounded shrink-0">
                      TPL
                    </span>
                  )}
                </div>
                <p className="text-xs text-text-muted font-body line-clamp-2">
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
            className="flex items-center gap-2.5 bg-accent-signal text-bg-void px-8 py-3 rounded-xl text-base font-bold hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200 font-display"
          >
            {isRunning ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5" />}
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
