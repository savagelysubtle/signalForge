import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Play, Loader2, XCircle,
  Search, Crosshair, Layers, MessageSquare,
} from 'lucide-react';
import { useStrategies } from '../../hooks/useStrategies';
import { usePipeline } from '../../hooks/usePipeline';

type RunMode = 'none' | 'discovery' | 'analysis' | 'combined' | 'prompt';

type InputKind = 'empty' | 'tickers' | 'prompt';

const TICKER_RE = /^[A-Z0-9]{1,5}(\.[A-Z]{1,2})?$/;

function classifyInput(raw: string): { kind: InputKind; tickers: string[] } {
  const trimmed = raw.trim();
  if (!trimmed) return { kind: 'empty', tickers: [] };

  const tokens = trimmed.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);
  const allTickers = tokens.length > 0 && tokens.every(t => TICKER_RE.test(t));

  if (allTickers) return { kind: 'tickers', tickers: tokens };
  return { kind: 'prompt', tickers: [] };
}

export function CommandBar() {
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

  const runMode: RunMode = useMemo(() => {
    const hasStrategy = selectedStrategy.length > 0;

    if (inputKind === 'prompt') return 'prompt';
    if (hasStrategy && inputKind === 'tickers') return 'combined';
    if (inputKind === 'empty') return 'discovery';
    if (inputKind === 'tickers') return 'analysis';
    return 'none';
  }, [selectedStrategy, inputKind]);

  const selectedStrategyName = allStrategies.find(s => s.id === selectedStrategy)?.name;

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

  const modeLabel: Record<RunMode, string> = {
    none: '',
    discovery: 'Discovery',
    analysis: 'Analysis',
    combined: 'Combined',
    prompt: 'Prompt',
  };

  const modeIcon: Record<RunMode, React.ReactNode> = {
    none: null,
    discovery: <Search className="w-3.5 h-3.5" />,
    analysis: <Crosshair className="w-3.5 h-3.5" />,
    combined: <Layers className="w-3.5 h-3.5" />,
    prompt: <MessageSquare className="w-3.5 h-3.5" />,
  };

  const modeColors: Record<RunMode, string> = {
    none: '',
    discovery: 'text-accent-profit',
    analysis: 'text-accent-signal',
    combined: 'text-accent-alert',
    prompt: 'text-accent-electric',
  };

  const placeholderText = selectedStrategy
    ? 'Tickers (AAPL, NVDA) or prompt ("oil stocks under $50") or leave empty'
    : 'Tickers (AAPL, NVDA) or prompt ("find undervalued tech stocks") or leave empty';

  const runningLabel = (() => {
    if (runMode === 'prompt') return 'Searching with prompt...';
    if (selectedStrategyName) return `Discovering via ${selectedStrategyName}...`;
    if (parsedTickers.length > 0) return `Analyzing ${parsedTickers.join(', ')}...`;
    return 'Discovering market movers...';
  })();

  return (
    <div className="h-16 border-b border-border-gutter bg-bg-asphalt flex items-center px-4 gap-4 shrink-0">
      <div className="flex-1 flex items-center gap-3">
        <select
          value={selectedStrategy}
          onChange={(e) => setSelectedStrategy(e.target.value)}
          disabled={isRunning}
          className="bg-bg-concrete border border-border-gutter rounded-md px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-accent-signal transition-colors min-w-[180px]"
        >
          <option value="">No Strategy</option>
          {allStrategies.map(s => (
            <option key={s.id} value={s.id}>
              {s.is_template ? `// ${s.name}` : s.name}
            </option>
          ))}
        </select>

        <input
          type="text"
          placeholder={placeholderText}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          disabled={isRunning}
          onKeyDown={(e) => { if (e.key === 'Enter' && runMode !== 'none') handleRun(); }}
          className="bg-bg-concrete border border-border-gutter rounded-md px-3 py-1.5 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-signal transition-colors flex-1 max-w-lg"
        />

        <button
          onClick={handleRun}
          disabled={isRunning || runMode === 'none'}
          className="flex items-center gap-2 bg-accent-signal text-bg-void px-4 py-1.5 rounded-md text-sm font-medium hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200 font-display"
        >
          {isRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          {isRunning ? 'Analyzing...' : 'Run'}
        </button>
      </div>

      <div className="flex items-center gap-3 text-sm shrink-0">
        {runMode !== 'none' && !isRunning && (
          <span className={`flex items-center gap-1.5 font-display text-xs ${modeColors[runMode]}`}>
            {modeIcon[runMode]}
            {modeLabel[runMode]}
          </span>
        )}

        {isRunning && (
          <span className="flex items-center gap-2 text-accent-signal font-display text-xs">
            <span className="relative flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-signal opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-accent-signal"></span>
            </span>
            {runningLabel}
          </span>
        )}
        {!isRunning && !error && runMode === 'none' && (
          <span className="flex items-center gap-2 text-text-muted text-xs">
            <div className="w-1.5 h-1.5 rounded-full bg-text-muted" />
            Select a strategy or enter tickers
          </span>
        )}
        {!isRunning && error && (
          <span className="flex items-center gap-2 text-accent-loss text-xs" title={error}>
            <XCircle className="w-4 h-4" />
            Error
          </span>
        )}
      </div>
    </div>
  );
}
