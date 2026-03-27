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
}

type TabType = 'overview' | 'chart' | 'sentiment' | 'synthesis' | 'feedback' | 'raw';

export function DetailView({ tickerData, fullResult }: DetailViewProps) {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const sentiment = fullResult.sentiment_analyses.find(s => s.ticker === tickerData.ticker) ?? null;
  const chartAnalyses = fullResult.chart_analyses.filter(c => c.ticker === tickerData.ticker);
  const chartErrors = (fullResult.chart_errors ?? []).filter(e => e.ticker === tickerData.ticker);
  const recommendation = fullResult.recommendations.find(r => r.ticker === tickerData.ticker) ?? null;

  const tabs: { id: TabType; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'chart', label: 'Chart' },
    { id: 'sentiment', label: 'Sentiment' },
    { id: 'synthesis', label: 'Synthesis' },
    { id: 'feedback', label: 'Feedback' },
    { id: 'raw', label: 'Raw Data' },
  ];

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border-gutter bg-bg-asphalt/70 backdrop-blur-sm shrink-0">
        <h2 className="text-2xl font-display font-bold text-text-primary">{tickerData.ticker}</h2>
        <p className="text-sm text-text-secondary font-body">{tickerData.company_name}</p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border-gutter px-4 shrink-0 bg-bg-asphalt">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={clsx(
              "px-4 py-3 text-sm font-medium border-b-2 transition-colors font-body",
              activeTab === tab.id
                ? "border-accent-signal text-accent-signal"
                : "border-transparent text-text-muted hover:text-text-primary"
            )}
          >
            {tab.label}
          </button>
        ))}
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
      <div className="border-t border-border-gutter p-4 bg-bg-asphalt shrink-0 text-xs text-text-muted flex justify-between items-center">
        <div className="truncate max-w-3xl" title={fullResult.screening?.screening_summary}>
          <span className="font-semibold text-text-secondary mr-2">Summary:</span>
          <span className="text-text-secondary">{fullResult.screening?.screening_summary || 'No summary available.'}</span>
        </div>
        <div className="flex gap-4 ml-4 shrink-0 font-display">
          <span>Mode: <span className="text-text-secondary">{fullResult.mode}</span></span>
          <span>Duration: <span className="text-text-secondary">{fullResult.total_duration_seconds.toFixed(1)}s</span></span>
        </div>
      </div>
    </div>
  );
}
