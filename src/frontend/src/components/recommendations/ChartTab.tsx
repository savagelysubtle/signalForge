import type { ChartAnalysis, TechnicalLevel, IndicatorReading } from '../../types';
import { TradingViewWidget } from '../shared/TradingViewWidget';
import clsx from 'clsx';

interface ChartTabProps {
  ticker: string;
  chartAnalysis: ChartAnalysis | null;
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

function AnalysisPanel({ analysis }: { analysis: ChartAnalysis }) {
  const bias = BIAS_CONFIG[analysis.overall_bias] ?? BIAS_CONFIG.neutral;
  const confidence = CONFIDENCE_STYLES[analysis.confidence] ?? CONFIDENCE_STYLES.medium;
  const trendColor = TREND_COLORS[analysis.trend_direction] ?? 'text-text-primary';

  const chartImageUrl = analysis.chart_image_path
    ? `http://localhost:8420/api/charts/${analysis.chart_image_path}`
    : null;

  return (
    <div className="p-4 overflow-y-auto h-full space-y-5">
      {/* Chart Image */}
      {chartImageUrl && (
        <div className="rounded-lg border border-border overflow-hidden bg-bg-tertiary">
          <img
            src={chartImageUrl}
            alt={`${analysis.ticker} chart`}
            className="w-full h-auto"
          />
        </div>
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

export function ChartTab({ ticker, chartAnalysis }: ChartTabProps) {
  return (
    <div className="flex h-full w-full gap-4 p-4">
      {/* Left: Claude Analysis */}
      <div className="w-1/2 overflow-hidden border border-border rounded-lg bg-bg-secondary">
        {chartAnalysis ? (
          <AnalysisPanel analysis={chartAnalysis} />
        ) : (
          <div className="flex items-center justify-center h-full text-text-secondary flex-col gap-2">
            <span className="text-sm">Claude Vision Analysis</span>
            <span className="text-xs opacity-50">No chart analysis available for this ticker</span>
          </div>
        )}
      </div>

      {/* Right: TradingView Live Widget */}
      <div className="w-1/2 border border-border rounded-lg overflow-hidden bg-bg-secondary">
        <TradingViewWidget symbol={ticker} />
      </div>
    </div>
  );
}
