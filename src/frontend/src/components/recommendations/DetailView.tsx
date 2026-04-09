import { useEffect, useState } from 'react';
import type { PipelineResult, FundamentalData, StageError } from '../../types';
import { OverviewTab } from './OverviewTab';
import { ChartTab } from './ChartTab';
import { SentimentTab } from './SentimentTab';
import { SynthesisTab } from './SynthesisTab';
import { FeedbackTab } from './FeedbackTab';
import { RawTab } from './RawTab';
import { motion, AnimatePresence } from 'motion/react';
import clsx from 'clsx';
import { AlertTriangle, X } from 'lucide-react';

const STAGE_DISPLAY: Record<string, string> = {
  fmp: 'FMP',
  regime: 'Regime',
  perplexity: 'Perplexity',
  numerical_ta: 'Numerical TA',
  gemini: 'Gemini',
  claude: 'Claude',
  risk_post_filter: 'Risk post-filter',
  gpt: 'GPT',
  risk_validation: 'Risk validation',
  calibration: 'Calibration',
  save_recommendations: 'Save recommendations',
};

function formatStageDisplayName(stage: string): string {
  if (STAGE_DISPLAY[stage]) return STAGE_DISPLAY[stage];
  return stage
    .split('_')
    .map(part => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ');
}

function uniqueStageLabels(errors: StageError[]): string[] {
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const e of errors) {
    if (!seen.has(e.stage)) {
      seen.add(e.stage);
      labels.push(formatStageDisplayName(e.stage));
    }
  }
  return labels;
}

interface DetailViewProps {
  tickerData: FundamentalData;
  fullResult: PipelineResult;
  initialTab?: TabType;
}

type TabType = 'overview' | 'chart' | 'sentiment' | 'synthesis' | 'feedback' | 'raw';

const MODE_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  discovery: { label: 'Discovery', color: 'text-accent-electric', bg: 'bg-accent-electric/15' },
  analysis: { label: 'Analysis', color: 'text-accent-signal', bg: 'bg-accent-signal/15' },
  combined: { label: 'Combined', color: 'text-accent-profit', bg: 'bg-accent-profit/15' },
  prompt: { label: 'Prompt', color: 'text-accent-alert', bg: 'bg-accent-alert/15' },
};

const ACTION_HEADER_CONFIG: Record<string, { color: string; bg: string; border: string }> = {
  BUY: { color: 'text-accent-profit', bg: 'bg-accent-profit/20', border: 'border-accent-profit/35' },
  SHORT: { color: 'text-accent-loss', bg: 'bg-accent-loss/20', border: 'border-accent-loss/35' },
  HOLD: { color: 'text-accent-alert', bg: 'bg-accent-alert/20', border: 'border-accent-alert/35' },
};

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function DetailView({ tickerData, fullResult, initialTab = 'overview' }: DetailViewProps) {
  const [activeTab, setActiveTab] = useState<TabType>(initialTab);
  const [stageErrorBannerDismissed, setStageErrorBannerDismissed] = useState(false);

  useEffect(() => {
    setStageErrorBannerDismissed(false);
  }, [fullResult.run_id]);

  const sentiment = fullResult.sentiment_analyses.find(s => s.ticker === tickerData.ticker) ?? null;
  const chartAnalyses = fullResult.chart_analyses.filter(c => c.ticker === tickerData.ticker);
  const chartErrors = (fullResult.chart_errors ?? []).filter(e => e.ticker === tickerData.ticker);
  const recommendation = fullResult.recommendations.find(r => r.ticker === tickerData.ticker) ?? null;
  const actionCfg = recommendation ? (ACTION_HEADER_CONFIG[recommendation.action] ?? null) : null;
  const modeCfg = MODE_CONFIG[fullResult.mode] ?? MODE_CONFIG.discovery;
  const screeningSummary = fullResult.screening?.screening_summary?.trim();
  const stageErrorLabels = uniqueStageLabels(fullResult.stage_errors);
  const showStageErrorBanner = fullResult.stage_errors.length > 0 && !stageErrorBannerDismissed;

  const tabs: { id: TabType; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'chart', label: 'Chart' },
    { id: 'sentiment', label: 'Sentiment' },
    { id: 'synthesis', label: 'Synthesis' },
    { id: 'feedback', label: 'Feedback' },
    { id: 'raw', label: 'Evidence Trail' },
  ];

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border-gutter bg-bg-asphalt/70 backdrop-blur-sm shrink-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="text-[28px] font-display font-bold text-text-primary tracking-tight leading-none">
                {tickerData.ticker}
              </h2>
              {recommendation && actionCfg && (
                <span
                  className={clsx(
                    'text-xs font-display font-bold px-2.5 py-1 rounded-md border',
                    actionCfg.bg,
                    actionCfg.color,
                    actionCfg.border,
                  )}
                >
                  {recommendation.action}
                </span>
              )}
            </div>
            <p className="text-xs text-text-muted font-body mt-1">{tickerData.company_name}</p>
            {tickerData.sector && (
              <p className="text-[11px] text-text-muted/60 font-body mt-0.5">{tickerData.sector}</p>
            )}
          </div>
          {fullResult.timestamp && (
            <div
              className="text-right shrink-0"
              title={formatTimestamp(fullResult.timestamp)}
            >
              <span className="text-[11px] text-text-muted font-display">
                {relativeTime(fullResult.timestamp)}
              </span>
            </div>
          )}
        </div>
        {screeningSummary && (
          <p className="text-xs text-text-secondary font-body leading-relaxed mt-3 max-w-4xl">
            {screeningSummary}
          </p>
        )}
      </div>

      {showStageErrorBanner && (
        <div
          className="px-6 py-2.5 flex items-start gap-3 border-b border-border-gutter shrink-0 bg-accent-alert-dim"
          role="alert"
        >
          <AlertTriangle
            className="w-4 h-4 shrink-0 mt-0.5 text-accent-alert"
            aria-hidden
          />
          <p className="text-sm text-text-primary font-body flex-1 min-w-0 leading-snug">
            Pipeline completed with errors in: {stageErrorLabels.join(', ')}
          </p>
          <button
            type="button"
            onClick={() => setStageErrorBannerDismissed(true)}
            className="shrink-0 p-1 rounded-md text-text-muted hover:text-text-primary hover:bg-bg-concrete/80 transition-colors"
            aria-label="Dismiss pipeline error notice"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="overflow-x-auto border-b border-border-gutter shrink-0 bg-bg-asphalt">
        <div className="flex px-4 min-w-max">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={clsx(
                "px-3 sm:px-4 py-3 text-sm font-medium border-b-2 transition-colors font-body whitespace-nowrap",
                activeTab === tab.id
                  ? "border-accent-signal text-accent-signal"
                  : "border-transparent text-text-muted hover:text-text-primary"
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden relative">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="h-full"
          >
            {activeTab === 'overview' && <OverviewTab data={tickerData} />}
            {activeTab === 'chart' && (
              <ChartTab
                ticker={tickerData.ticker}
                chartAnalyses={chartAnalyses}
                chartErrors={chartErrors}
                chartIndicators={fullResult.chart_indicators ?? []}
                recommendation={recommendation}
              />
            )}
            {activeTab === 'sentiment' && <SentimentTab sentiment={sentiment} />}
            {activeTab === 'feedback' && <FeedbackTab recommendation={recommendation} />}
            {activeTab === 'raw' && <RawTab data={fullResult} />}
            {activeTab === 'synthesis' && (
              <SynthesisTab recommendation={recommendation} tickerData={tickerData} />
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Footer Metadata */}
      <div className="border-t border-border-gutter px-4 py-2.5 bg-bg-asphalt shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          {/* Left: timestamp + strategy */}
          <div className="flex items-center gap-3 text-xs text-text-muted font-display">
            {fullResult.timestamp && (
              <span title={formatTimestamp(fullResult.timestamp)}>
                {formatTimestamp(fullResult.timestamp)}
              </span>
            )}
            {fullResult.strategy_name && (
              <>
                <span className="text-border-gutter">·</span>
                <span className="text-text-secondary">{fullResult.strategy_name}</span>
              </>
            )}
          </div>
          {/* Right: mode pill + duration */}
          <div className="flex items-center gap-2 shrink-0">
            <span
              className={clsx('text-[10px] font-display font-semibold px-2 py-0.5 rounded', modeCfg.bg, modeCfg.color)}
            >
              {modeCfg.label}
            </span>
            <span className="text-xs text-text-muted font-display tabular-nums">
              {formatDuration(fullResult.total_duration_seconds)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
