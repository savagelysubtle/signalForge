import { useState } from 'react';
import type { PipelineResult, FundamentalData } from '../../types';
import { OverviewTab } from './OverviewTab';
import { ChartTab } from './ChartTab';
import { SentimentTab } from './SentimentTab';
import { SynthesisTab } from './SynthesisTab';
import { FeedbackTab } from './FeedbackTab';
import { RawTab } from './RawTab';
import { motion, AnimatePresence } from 'motion/react';
import clsx from 'clsx';

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
  const sentiment = fullResult.sentiment_analyses.find(s => s.ticker === tickerData.ticker) ?? null;
  const chartAnalyses = fullResult.chart_analyses.filter(c => c.ticker === tickerData.ticker);
  const chartErrors = (fullResult.chart_errors ?? []).filter(e => e.ticker === tickerData.ticker);
  const recommendation = fullResult.recommendations.find(r => r.ticker === tickerData.ticker) ?? null;
  const actionCfg = recommendation ? (ACTION_HEADER_CONFIG[recommendation.action] ?? null) : null;
  const modeCfg = MODE_CONFIG[fullResult.mode] ?? MODE_CONFIG.discovery;

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
      </div>

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
            {activeTab === 'synthesis' && <SynthesisTab recommendation={recommendation} />}
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
              title={fullResult.screening?.screening_summary ?? undefined}
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
