import { useState } from 'react';
import type { PipelineResult, FundamentalData } from '../../types';
import { OverviewTab } from './OverviewTab';
import { ChartTab } from './ChartTab';
import { SentimentTab } from './SentimentTab';
import { SynthesisTab } from './SynthesisTab';
import { RawTab } from './RawTab';
import clsx from 'clsx';

interface DetailViewProps {
  tickerData: FundamentalData;
  fullResult: PipelineResult;
}

type TabType = 'overview' | 'chart' | 'sentiment' | 'synthesis' | 'raw';

export function DetailView({ tickerData, fullResult }: DetailViewProps) {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const sentiment = fullResult.sentiment_analyses.find(s => s.ticker === tickerData.ticker) ?? null;
  const chartAnalyses = fullResult.chart_analyses.filter(c => c.ticker === tickerData.ticker);
  const recommendation = fullResult.recommendations.find(r => r.ticker === tickerData.ticker) ?? null;

  const tabs: { id: TabType; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'chart', label: 'Chart' },
    { id: 'sentiment', label: 'Sentiment' },
    { id: 'synthesis', label: 'Synthesis' },
    { id: 'raw', label: 'Raw Data' },
  ];

  return (
    <div className="flex-1 flex flex-col h-full bg-bg-primary overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-border bg-bg-secondary shrink-0">
        <h2 className="text-2xl font-bold text-text-primary">{tickerData.ticker}</h2>
        <p className="text-sm text-text-secondary">{tickerData.company_name}</p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border px-4 shrink-0 bg-bg-secondary">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={clsx(
              "px-4 py-3 text-sm font-medium border-b-2 transition-colors",
              activeTab === tab.id 
                ? "border-accent-blue text-accent-blue" 
                : "border-transparent text-text-secondary hover:text-text-primary"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden relative">
        {activeTab === 'overview' && <OverviewTab data={tickerData} />}
        {activeTab === 'chart' && (
          <ChartTab
            ticker={tickerData.ticker}
            chartAnalyses={chartAnalyses}
            chartIndicators={fullResult.chart_indicators ?? []}
            recommendation={recommendation}
          />
        )}
        {activeTab === 'sentiment' && <SentimentTab sentiment={sentiment} />}
        {activeTab === 'raw' && <RawTab data={fullResult} />}
        
        {activeTab === 'synthesis' && <SynthesisTab recommendation={recommendation} />}
      </div>

      {/* Footer Metadata */}
      <div className="border-t border-border p-4 bg-bg-secondary shrink-0 text-xs text-text-secondary flex justify-between items-center">
        <div className="truncate max-w-3xl" title={fullResult.screening?.screening_summary}>
          <span className="font-semibold text-text-primary mr-2">Summary:</span>
          {fullResult.screening?.screening_summary || 'No summary available.'}
        </div>
        <div className="flex gap-4 ml-4 shrink-0">
          <span>Mode: {fullResult.mode}</span>
          <span>Duration: {fullResult.total_duration_seconds.toFixed(1)}s</span>
        </div>
      </div>
    </div>
  );
}
