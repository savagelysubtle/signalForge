import { useState, useCallback } from 'react';
import type { ChartAnalysis, Recommendation, TechnicalLevel, IndicatorReading } from '../../types';
import { PriceLevelMap } from './PriceLevelMap';
import { Maximize2, X } from 'lucide-react';
import clsx from 'clsx';

interface ChartTabProps {
  ticker: string;
  chartAnalyses: ChartAnalysis[];
  chartIndicators: string[];
  recommendation: Recommendation | null;
}

const BIAS_CONFIG: Record<string, { text: string; color: string; bg: string }> = {
  strongly_bullish: { text: 'Strongly Bullish', color: 'text-accent-green', bg: 'bg-accent-green/15' },
  bullish: { text: 'Bullish', color: 'text-accent-green', bg: 'bg-accent-green/10' },
  neutral: { text: 'Neutral', color: 'text-accent-yellow', bg: 'bg-accent-yellow/10' },
  bearish: { text: 'Bearish', color: 'text-accent-red', bg: 'bg-accent-red/10' },
  strongly_bearish: { text: 'Strongly Bearish', color: 'text-accent-red', bg: 'bg-accent-red/15' },
};

const TREND_COLORS: Record<string, string> = {
  bullish: 'text-accent-green',
  bearish: 'text-accent-red',
  neutral: 'text-accent-yellow',
  transitioning: 'text-accent-blue',
};

const SIGNAL_COLORS: Record<string, string> = {
  bullish: 'text-accent-green',
  bearish: 'text-accent-red',
  neutral: 'text-text-secondary',
};

const CONFIDENCE_STYLES: Record<string, { text: string; color: string; bg: string }> = {
  high: { text: 'High', color: 'text-accent-green', bg: 'bg-accent-green/10' },
  medium: { text: 'Medium', color: 'text-accent-yellow', bg: 'bg-accent-yellow/10' },
  low: { text: 'Low', color: 'text-accent-red', bg: 'bg-accent-red/10' },
};

const STRENGTH_BADGE: Record<string, string> = {
  strong: 'bg-accent-blue/15 text-accent-blue',
  moderate: 'bg-bg-tertiary text-text-secondary',
  weak: 'bg-bg-tertiary text-text-secondary opacity-70',
};

function LevelRow({ level }: { level: TechnicalLevel }) {
  const typeColor = level.level_type === 'support' ? 'text-accent-green' : 'text-accent-red';
  return (
    <tr className="border-b border-border last:border-0">
      <td className="py-2 pr-4 text-sm tabular-nums text-text-primary">${level.price.toFixed(2)}</td>
      <td className={clsx('py-2 pr-4 text-sm capitalize', typeColor)}>{level.level_type}</td>
      <td className="py-2">
        <span className={clsx('text-xs px-2 py-0.5 rounded', STRENGTH_BADGE[level.strength])}>
          {level.strength}
        </span>
      </td>
    </tr>
  );
}

function IndicatorRow({ reading }: { reading: IndicatorReading }) {
  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-border last:border-0">
      <div className={clsx('mt-0.5 w-2 h-2 rounded-full shrink-0', {
        'bg-accent-green': reading.signal === 'bullish',
        'bg-accent-red': reading.signal === 'bearish',
        'bg-accent-yellow': reading.signal === 'neutral',
      })} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-text-primary">{reading.indicator}</span>
          <span className="text-xs text-text-secondary">{reading.value}</span>
          <span className={clsx('text-xs capitalize', SIGNAL_COLORS[reading.signal])}>
            {reading.signal}
          </span>
        </div>
        {reading.notes && (
          <p className="text-xs text-text-secondary mt-0.5">{reading.notes}</p>
        )}
      </div>
    </div>
  );
}

function ExpandableChartImage({ src, alt }: { src: string; alt: string }) {
  const [expanded, setExpanded] = useState(false);

  const close = useCallback(() => setExpanded(false), []);

  return (
    <>
      <div className="relative rounded-lg border border-border overflow-hidden bg-bg-tertiary group">
        <img src={src} alt={alt} className="w-full h-auto" />
        <button
          onClick={() => setExpanded(true)}
          className="absolute top-2 right-2 p-1.5 rounded-md bg-bg-primary/80 border border-border text-text-secondary opacity-0 group-hover:opacity-100 transition-opacity hover:text-text-primary hover:bg-bg-primary"
          title="Expand chart"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={close}
        >
          <div
            className="relative w-[80vw] max-h-[90vh] rounded-xl border border-border bg-bg-secondary shadow-2xl overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <button
              onClick={close}
              className="absolute top-3 right-3 z-10 p-1.5 rounded-md bg-bg-primary/80 border border-border text-text-secondary hover:text-text-primary hover:bg-bg-primary transition-colors"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
            <img src={src} alt={alt} className="w-full h-auto" />
          </div>
        </div>
      )}
    </>
  );
}

function AnalysisPanel({ analysis }: { analysis: ChartAnalysis }) {
  const bias = BIAS_CONFIG[analysis.overall_bias] ?? BIAS_CONFIG.neutral;
  const confidence = CONFIDENCE_STYLES[analysis.confidence] ?? CONFIDENCE_STYLES.medium;
  const trendColor = TREND_COLORS[analysis.trend_direction] ?? 'text-text-primary';

  const chartImageUrl = analysis.chart_image_path || null;

  return (
    <div className="p-4 overflow-y-auto h-full space-y-5">
      {/* Chart Image */}
      {chartImageUrl && (
        <ExpandableChartImage src={chartImageUrl} alt={`${analysis.ticker} chart`} />
      )}

      {/* Trend + Bias Header */}
      <div className="bg-bg-tertiary rounded-lg border border-border p-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-text-secondary mb-1">Trend Direction</div>
            <div className={clsx('text-lg font-bold capitalize', trendColor)}>
              {analysis.trend_direction}
            </div>
            <span className={clsx('text-xs px-2 py-0.5 rounded mt-1 inline-block', STRENGTH_BADGE[analysis.trend_strength])}>
              {analysis.trend_strength} trend
            </span>
          </div>
          <div>
            <div className="text-xs text-text-secondary mb-1">Overall Bias</div>
            <div className={clsx('px-3 py-1.5 rounded-lg text-sm font-semibold inline-block', bias.bg, bias.color)}>
              {bias.text}
            </div>
            <div className="mt-2">
              <span className={clsx('text-xs px-2 py-0.5 rounded', confidence.bg, confidence.color)}>
                {confidence.text} confidence
              </span>
            </div>
          </div>
        </div>
        <div className="text-xs text-text-secondary mt-3">
          Timeframe: <span className="text-text-primary">{analysis.timeframe}</span>
        </div>
      </div>

      {/* Summary */}
      <div>
        <h3 className="text-sm font-semibold text-text-secondary mb-2">Analysis Summary</h3>
        <p className="text-sm text-text-primary leading-relaxed">{analysis.summary}</p>
      </div>

      {/* Key Levels */}
      {analysis.key_levels.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2">
            Key Levels
            <span className="ml-2 text-xs font-normal">({analysis.key_levels.length})</span>
          </h3>
          <div className="bg-bg-tertiary rounded-lg border border-border overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border text-xs text-text-secondary">
                  <th className="py-2 px-4 text-left font-medium">Price</th>
                  <th className="py-2 px-4 text-left font-medium">Type</th>
                  <th className="py-2 px-4 text-left font-medium">Strength</th>
                </tr>
              </thead>
              <tbody className="px-4">
                {analysis.key_levels.map((level, i) => (
                  <LevelRow key={i} level={level} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Patterns Detected */}
      {analysis.patterns_detected.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2">Patterns Detected</h3>
          <div className="flex flex-wrap gap-2">
            {analysis.patterns_detected.map((pattern, i) => (
              <span
                key={i}
                className="text-xs px-3 py-1.5 rounded-lg bg-accent-blue/10 text-accent-blue border border-accent-blue/20"
              >
                {pattern}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Indicator Readings */}
      {analysis.indicator_readings.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2">
            Indicator Readings
            <span className="ml-2 text-xs font-normal">({analysis.indicator_readings.length})</span>
          </h3>
          <div className="bg-bg-tertiary rounded-lg border border-border px-4">
            {analysis.indicator_readings.map((reading, i) => (
              <IndicatorRow key={i} reading={reading} />
            ))}
          </div>
        </div>
      )}

      {/* Volume Analysis */}
      {analysis.volume_analysis && (
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2">Volume Analysis</h3>
          <p className="text-sm text-text-primary leading-relaxed">{analysis.volume_analysis}</p>
        </div>
      )}
    </div>
  );
}

const TIMEFRAME_LABELS: Record<string, string> = {
  "D": "Daily",
  "1D": "Daily",
  "W": "Weekly",
  "1W": "Weekly",
  "M": "Monthly",
  "1M": "Monthly",
  "4H": "4 Hour",
  "4h": "4 Hour",
  "1H": "1 Hour",
  "1h": "1 Hour",
  "2H": "2 Hour",
  "2h": "2 Hour",
};

function getTimeframeLabel(tf: string): string {
  return TIMEFRAME_LABELS[tf] ?? tf;
}

function CompactLevelLegend({
  analysis,
  recommendation,
}: {
  analysis: ChartAnalysis;
  recommendation: Recommendation | null;
}) {
  const items: { label: string; price: number; color: string }[] = [];

  if (recommendation?.entry_price != null)
    items.push({ label: 'Entry', price: recommendation.entry_price, color: 'text-accent-blue' });
  if (recommendation?.stop_loss != null)
    items.push({ label: 'Stop', price: recommendation.stop_loss, color: 'text-accent-red' });
  if (recommendation?.take_profit != null)
    items.push({ label: 'Target', price: recommendation.take_profit, color: 'text-accent-green' });

  for (const lv of analysis.key_levels.slice(0, 4)) {
    const color = lv.level_type === 'support' ? 'text-accent-green' : 'text-accent-red';
    items.push({ label: `${lv.level_type} (${lv.strength[0]})`, price: lv.price, color });
  }

  if (items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2 border-t border-border text-[11px] shrink-0">
      {items.map((item, i) => (
        <span key={i} className="flex items-center gap-1">
          <span className={clsx('font-medium capitalize', item.color)}>{item.label}</span>
          <span className="text-text-secondary font-mono">${item.price.toFixed(2)}</span>
        </span>
      ))}
      {recommendation?.risk_reward_ratio != null && (
        <span className="text-text-secondary font-mono ml-auto">
          R:R {recommendation.risk_reward_ratio.toFixed(1)}:1
        </span>
      )}
    </div>
  );
}

export function ChartTab({ ticker, chartAnalyses, chartIndicators, recommendation }: ChartTabProps) {
  const [activeTimeframe, setActiveTimeframe] = useState(0);
  const activeAnalysis = chartAnalyses[activeTimeframe] ?? null;

  return (
    <div className="flex h-full w-full gap-4 p-4">
      {/* Left: Claude Analysis */}
      <div className="w-1/2 overflow-hidden border border-border rounded-lg bg-bg-secondary flex flex-col">
        {chartAnalyses.length > 1 && (
          <div className="flex border-b border-border px-3 shrink-0">
            {chartAnalyses.map((analysis, i) => (
              <button
                key={`${analysis.timeframe}-${i}`}
                onClick={() => setActiveTimeframe(i)}
                className={clsx(
                  "px-3 py-2.5 text-xs font-medium border-b-2 transition-colors",
                  activeTimeframe === i
                    ? "border-accent-blue text-accent-blue"
                    : "border-transparent text-text-secondary hover:text-text-primary"
                )}
              >
                {getTimeframeLabel(analysis.timeframe)}
              </button>
            ))}
          </div>
        )}

        {activeAnalysis ? (
          <div className="flex-1 overflow-hidden">
            <AnalysisPanel analysis={activeAnalysis} />
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-text-secondary flex-col gap-2">
            <span className="text-sm">Claude Vision Analysis</span>
            <span className="text-xs opacity-50">No chart analysis available for this ticker</span>
          </div>
        )}
      </div>

      {/* Right: Annotated Chart / Price Level Map */}
      <div className="w-1/2 border border-border rounded-lg overflow-hidden bg-bg-secondary flex flex-col">
        {activeAnalysis?.annotated_chart_path ? (
          <>
            <div className="flex-1 overflow-auto">
              <ExpandableChartImage
                src={activeAnalysis.annotated_chart_path}
                alt={`${activeAnalysis.ticker} ${activeAnalysis.timeframe} annotated`}
              />
            </div>
            <CompactLevelLegend analysis={activeAnalysis} recommendation={recommendation} />
          </>
        ) : activeAnalysis ? (
          <PriceLevelMap analysis={activeAnalysis} recommendation={recommendation} />
        ) : (
          <div className="flex items-center justify-center h-full text-text-secondary flex-col gap-2">
            <span className="text-sm">Price Level Map</span>
            <span className="text-xs opacity-50">No analysis data available</span>
          </div>
        )}
      </div>
    </div>
  );
}
