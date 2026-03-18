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

  const allStrategies = [...templates, ...strategies];

  const { kind: inputKind, tickers: parsedTickers } = useMemo(
    () => classifyInput(inputText),
    [inputText],
  );

  const runMode: RunMode = useMemo(() => {
    const hasStrategy = selectedStrategy.length > 0;

    if (inputKind === 'prompt') return 'prompt';
    if (hasStrategy && inputKind === 'tickers') return 'combined';
    if (hasStrategy && inputKind === 'empty') return 'discovery';
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
    discovery: 'text-accent-green',
    analysis: 'text-accent-blue',
    combined: 'text-accent-yellow',
    prompt: 'text-purple-400',
  };

  const placeholderText = selectedStrategy
    ? 'Tickers (AAPL, NVDA) or prompt ("oil stocks under $50") or leave empty'
    : 'Tickers (AAPL, NVDA) or prompt ("find undervalued tech stocks")';

  const runningLabel = (() => {
    if (runMode === 'prompt') return 'Searching with prompt...';
    if (selectedStrategyName) return `Discovering via ${selectedStrategyName}...`;
    return `Analyzing ${parsedTickers.join(', ')}...`;
  })();

  return (
    <div className="h-16 border-b border-border bg-bg-secondary flex items-center px-4 gap-4 shrink-0">
      <div className="flex-1 flex items-center gap-3">
        <select
          value={selectedStrategy}
          onChange={(e) => setSelectedStrategy(e.target.value)}
          disabled={isRunning}
          className="bg-bg-tertiary border border-border rounded px-3 py-1.5 text-sm text-text-primary focus:outline-none focus:border-accent-blue min-w-[180px]"
        >
          <option value="">No Strategy</option>
          {allStrategies.map(s => (
            <option key={s.id} value={s.id}>
              {s.is_template ? `📋 ${s.name}` : s.name}
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
          className="bg-bg-tertiary border border-border rounded px-3 py-1.5 text-sm text-text-primary placeholder:text-text-secondary/50 focus:outline-none focus:border-accent-blue flex-1 max-w-lg"
        />

        <button
          onClick={handleRun}
          disabled={isRunning || runMode === 'none'}
          className="flex items-center gap-2 bg-accent-blue text-bg-primary px-4 py-1.5 rounded text-sm font-medium hover:bg-opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
        >
          {isRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          {isRunning ? 'Analyzing...' : 'Run'}
        </button>
      </div>

      <div className="flex items-center gap-3 text-sm shrink-0">
        {runMode !== 'none' && !isRunning && (
          <span className={`flex items-center gap-1.5 ${modeColors[runMode]}`}>
            {modeIcon[runMode]}
            {modeLabel[runMode]}
          </span>
        )}

        {isRunning && (
          <span className="flex items-center gap-2 text-accent-blue">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-blue opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-accent-blue"></span>
            </span>
            {runningLabel}
          </span>
        )}
        {!isRunning && !error && runMode === 'none' && (
          <span className="flex items-center gap-2 text-text-secondary">
            <div className="w-2 h-2 rounded-full bg-text-secondary" />
            Select a strategy or enter tickers
          </span>
        )}
        {!isRunning && error && (
          <span className="flex items-center gap-2 text-accent-red" title={error}>
            <XCircle className="w-4 h-4" />
            Error
          </span>
        )}
      </div>
    </div>
  );
}
