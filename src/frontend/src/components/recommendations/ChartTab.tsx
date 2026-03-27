import { useState, useCallback } from 'react';
import type { ChartAnalysis, ChartError, Recommendation, TechnicalLevel, IndicatorReading } from '../../types';
import { PriceLevelMap } from './PriceLevelMap';
import { Maximize2, X, AlertTriangle, Loader2, ChevronDown, ChevronUp } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import clsx from 'clsx';
import { api } from '../../api/client';

interface ChartTabProps {
  ticker: string;
  chartAnalyses: ChartAnalysis[];
  chartErrors: ChartError[];
  chartIndicators: string[];
  recommendation: Recommendation | null;
}

const BIAS_CONFIG: Record<string, { text: string; color: string; bg: string }> = {
  strongly_bullish: { text: 'Strongly Bullish', color: 'text-accent-profit', bg: 'bg-accent-profit/15' },
  bullish: { text: 'Bullish', color: 'text-accent-profit', bg: 'bg-accent-profit/10' },
  neutral: { text: 'Neutral', color: 'text-accent-alert', bg: 'bg-accent-alert/10' },
  bearish: { text: 'Bearish', color: 'text-accent-loss', bg: 'bg-accent-loss/10' },
  strongly_bearish: { text: 'Strongly Bearish', color: 'text-accent-loss', bg: 'bg-accent-loss/15' },
};

const TREND_COLORS: Record<string, string> = {
  bullish: 'text-accent-profit',
  bearish: 'text-accent-loss',
  neutral: 'text-accent-alert',
  transitioning: 'text-accent-signal',
};

const SIGNAL_COLORS: Record<string, string> = {
  bullish: 'text-accent-profit',
  bearish: 'text-accent-loss',
  neutral: 'text-text-secondary',
};

const CONFIDENCE_STYLES: Record<string, { text: string; color: string; bg: string }> = {
  high: { text: 'High', color: 'text-accent-profit', bg: 'bg-accent-profit/10' },
  medium: { text: 'Medium', color: 'text-accent-alert', bg: 'bg-accent-alert/10' },
  low: { text: 'Low', color: 'text-accent-loss', bg: 'bg-accent-loss/10' },
};

const STRENGTH_BADGE: Record<string, string> = {
  strong: 'bg-accent-signal/15 text-accent-signal',
  moderate: 'bg-bg-concrete text-text-secondary',
  weak: 'bg-bg-concrete text-text-muted',
};

function LevelRow({ level }: { level: TechnicalLevel }) {
  const typeColor = level.level_type === 'support' ? 'text-accent-profit' : 'text-accent-loss';
  return (
    <tr className="border-b border-border-subtle last:border-0">
      <td className="py-2 pr-4 text-sm font-display tabular-nums text-text-primary">${level.price.toFixed(2)}</td>
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
    <div className="flex items-start gap-3 py-2.5 border-b border-border-subtle last:border-0">
      <div className={clsx('mt-0.5 w-2 h-2 rounded-full shrink-0', {
        'bg-accent-profit': reading.signal === 'bullish',
        'bg-accent-loss': reading.signal === 'bearish',
        'bg-accent-alert': reading.signal === 'neutral',
      })} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-text-primary">{reading.indicator}</span>
          <span className="text-xs text-text-secondary font-display">{reading.value}</span>
          <span className={clsx('text-xs capitalize', SIGNAL_COLORS[reading.signal])}>
            {reading.signal}
          </span>
        </div>
        {reading.notes && (
          <p className="text-xs text-text-muted mt-0.5">{reading.notes}</p>
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
      <div className="relative rounded-lg border border-border-gutter overflow-hidden bg-bg-concrete group">
        <img src={src} alt={alt} className="w-full h-auto" />
        <button
          onClick={() => setExpanded(true)}
          className="absolute top-2 right-2 p-1.5 rounded-md bg-bg-void/80 border border-border-gutter text-text-muted opacity-0 group-hover:opacity-100 transition-opacity hover:text-text-primary hover:bg-bg-void"
          title="Expand chart"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md"
            onClick={close}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
              className="relative w-[90vw] max-h-[92vh] rounded-xl border border-border-gutter bg-bg-asphalt shadow-2xl overflow-hidden"
              onClick={e => e.stopPropagation()}
            >
              <button
                onClick={close}
                className="absolute top-3 right-3 z-10 p-1.5 rounded-md bg-bg-concrete border border-border-gutter text-text-muted hover:text-text-primary hover:bg-bg-steel transition-colors"
                title="Close"
              >
                <X className="w-4 h-4" />
              </button>
              <img src={src} alt={alt} className="w-full h-auto" />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

function AnalysisDetails({ analysis }: { analysis: ChartAnalysis }) {
  const bias = BIAS_CONFIG[analysis.overall_bias] ?? BIAS_CONFIG.neutral;
  const confidence = CONFIDENCE_STYLES[analysis.confidence] ?? CONFIDENCE_STYLES.medium;
  const trendColor = TREND_COLORS[analysis.trend_direction] ?? 'text-text-primary';

  return (
    <div className="space-y-4">
      {/* Trend + Bias Header */}
      <div className="bg-bg-concrete rounded-lg border border-border-gutter p-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-text-muted mb-1 font-body">Trend Direction</div>
            <div className={clsx('text-lg font-display font-bold capitalize', trendColor)}>
              {analysis.trend_direction}
            </div>
            <span className={clsx('text-xs px-2 py-0.5 rounded mt-1 inline-block', STRENGTH_BADGE[analysis.trend_strength])}>
              {analysis.trend_strength} trend
            </span>
          </div>
          <div>
            <div className="text-xs text-text-muted mb-1 font-body">Overall Bias</div>
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
        <div className="text-xs text-text-muted mt-3 font-body">
          Timeframe: <span className="text-text-primary font-display">{analysis.timeframe}</span>
        </div>
      </div>

      {/* Summary */}
      <div>
        <h3 className="text-sm font-semibold text-text-secondary mb-2 font-body">Analysis Summary</h3>
        <p className="text-sm text-text-primary leading-relaxed">{analysis.summary}</p>
      </div>

      {/* Key Levels */}
      {analysis.key_levels.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2 font-body">
            Key Levels
            <span className="ml-2 text-xs font-normal text-text-muted">({analysis.key_levels.length})</span>
          </h3>
          <div className="bg-bg-concrete rounded-lg border border-border-gutter overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border-gutter text-xs text-text-muted">
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
          <h3 className="text-sm font-semibold text-text-secondary mb-2 font-body">Patterns Detected</h3>
          <div className="flex flex-wrap gap-2">
            {analysis.patterns_detected.map((pattern, i) => (
              <span
                key={i}
                className="text-xs px-3 py-1.5 rounded-lg bg-accent-signal-dim text-accent-signal border border-accent-signal/20 font-display"
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
          <h3 className="text-sm font-semibold text-text-secondary mb-2 font-body">
            Indicator Readings
            <span className="ml-2 text-xs font-normal text-text-muted">({analysis.indicator_readings.length})</span>
          </h3>
          <div className="bg-bg-concrete rounded-lg border border-border-gutter px-4">
            {analysis.indicator_readings.map((reading, i) => (
              <IndicatorRow key={i} reading={reading} />
            ))}
          </div>
        </div>
      )}

      {/* Volume Analysis */}
      {analysis.volume_analysis && (
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2 font-body">Volume Analysis</h3>
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
  "15m": "15 Min",
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
    items.push({ label: 'Entry', price: recommendation.entry_price, color: 'text-accent-signal' });
  if (recommendation?.stop_loss != null)
    items.push({ label: 'Stop', price: recommendation.stop_loss, color: 'text-accent-loss' });
  if (recommendation?.take_profit != null)
    items.push({ label: 'Target', price: recommendation.take_profit, color: 'text-accent-profit' });

  for (const lv of analysis.key_levels.slice(0, 4)) {
    const color = lv.level_type === 'support' ? 'text-accent-profit' : 'text-accent-loss';
    items.push({ label: `${lv.level_type} (${lv.strength[0]})`, price: lv.price, color });
  }

  if (items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2 border-t border-border-gutter text-[11px] shrink-0">
      {items.map((item, i) => (
        <span key={i} className="flex items-center gap-1">
          <span className={clsx('font-medium capitalize', item.color)}>{item.label}</span>
          <span className="text-text-secondary font-display">${item.price.toFixed(2)}</span>
        </span>
      ))}
      {recommendation?.risk_reward_ratio != null && (
        <span className="text-text-secondary font-display ml-auto">
          R:R {recommendation.risk_reward_ratio.toFixed(1)}:1
        </span>
      )}
    </div>
  );
}

const ERROR_STATUS_LABELS: Record<string, string> = {
  chart_fetch_error: 'Chart image fetch failed',
  validation_failed: 'Claude response validation failed',
  api_error: 'Claude API error',
};

function ChartErrorPanel({ errors }: { errors: ChartError[] }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-text-secondary gap-3 px-6">
      <AlertTriangle className="w-6 h-6 text-accent-alert" />
      <span className="text-sm font-medium font-body">Chart Analysis Failed</span>
      <div className="space-y-2 w-full max-w-sm">
        {errors.map((err, i) => (
          <div key={i} className="rounded-lg bg-accent-loss-dim border border-accent-loss/20 px-3 py-2">
            <div className="text-xs font-medium text-accent-loss">
              {ERROR_STATUS_LABELS[err.status] ?? err.status}
            </div>
            {err.error && (
              <p className="text-xs text-text-muted mt-1 wrap-break-word line-clamp-3">{err.error}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

const AVAILABLE_TIMEFRAMES = ["15m", "1H", "4H", "D", "W"] as const;

export function ChartTab({ ticker, chartAnalyses, chartErrors, chartIndicators, recommendation }: ChartTabProps) {
  const [activeTimeframe, setActiveTimeframe] = useState(0);
  const [adHocChartUrl, setAdHocChartUrl] = useState<string | null>(null);
  const [adHocTimeframe, setAdHocTimeframe] = useState<string | null>(null);
  const [adHocLoading, setAdHocLoading] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const activeAnalysis = chartAnalyses[activeTimeframe] ?? null;
  const hasErrors = chartErrors.length > 0;

  const analysisTimeframes = new Set(chartAnalyses.map(c => c.timeframe));

  const handleTimeframeClick = useCallback(async (tf: string) => {
    const idx = chartAnalyses.findIndex(c => c.timeframe === tf);
    if (idx !== -1) {
      setActiveTimeframe(idx);
      setAdHocChartUrl(null);
      setAdHocTimeframe(null);
      return;
    }
    setAdHocLoading(true);
    setAdHocTimeframe(tf);
    try {
      const resp = await api.fetchChart({ ticker, timeframe: tf, indicators: chartIndicators });
      setAdHocChartUrl(resp.image_url);
      setActiveTimeframe(-1);
    } catch (err) {
      console.error("Ad-hoc chart fetch failed:", err);
      setAdHocChartUrl(null);
    } finally {
      setAdHocLoading(false);
    }
  }, [chartAnalyses, ticker, chartIndicators]);

  const selectedTf = adHocTimeframe ?? activeAnalysis?.timeframe ?? null;
  const chartImageUrl = activeAnalysis?.chart_image_path || null;
  const annotatedChartUrl = activeAnalysis?.annotated_chart_path || null;

  return (
    <div className="flex flex-col h-full w-full overflow-auto">
      {/* Timeframe selector bar */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-border-gutter bg-bg-asphalt shrink-0">
        <span className="text-xs text-text-muted mr-2 font-body">Timeframe:</span>
        {AVAILABLE_TIMEFRAMES.map(tf => (
          <button
            key={tf}
            onClick={() => handleTimeframeClick(tf)}
            className={clsx(
              "px-2.5 py-1 text-xs font-display font-medium rounded transition-colors",
              selectedTf === tf
                ? "bg-accent-signal-dim text-accent-signal"
                : analysisTimeframes.has(tf)
                  ? "bg-bg-concrete text-text-primary hover:bg-bg-steel"
                  : "text-text-muted hover:text-text-primary hover:bg-bg-steel"
            )}
          >
            {getTimeframeLabel(tf)}
          </button>
        ))}
        {adHocLoading && <Loader2 className="w-3.5 h-3.5 animate-spin text-accent-signal ml-2" />}
      </div>

      {/* Main content — single column, charts prominent */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {/* Primary chart image — full width */}
        {activeAnalysis ? (
          <>
            {chartImageUrl && (
              <ExpandableChartImage src={chartImageUrl} alt={`${ticker} ${activeAnalysis.timeframe} chart`} />
            )}

            {/* Annotated chart — full width below primary */}
            {annotatedChartUrl && (
              <div>
                <h3 className="text-xs font-display text-text-muted mb-2 uppercase tracking-wider">Annotated Chart</h3>
                <ExpandableChartImage
                  src={annotatedChartUrl}
                  alt={`${ticker} ${activeAnalysis.timeframe} annotated`}
                />
                <CompactLevelLegend analysis={activeAnalysis} recommendation={recommendation} />
              </div>
            )}

            {/* PriceLevelMap when no annotated chart */}
            {!annotatedChartUrl && (
              <div className="border border-border-gutter rounded-lg overflow-hidden bg-bg-asphalt">
                <PriceLevelMap analysis={activeAnalysis} recommendation={recommendation} />
              </div>
            )}

            {/* Collapsible analysis details */}
            <div className="border border-border-gutter rounded-lg bg-bg-asphalt overflow-hidden">
              <button
                onClick={() => setDetailsOpen(prev => !prev)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-text-secondary hover:text-text-primary hover:bg-bg-steel/30 transition-colors"
              >
                <span className="font-body">Analysis Details</span>
                {detailsOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
              {detailsOpen && (
                <div className="px-4 pb-4">
                  <AnalysisDetails analysis={activeAnalysis} />
                </div>
              )}
            </div>
          </>
        ) : adHocChartUrl ? (
          <>
            <ExpandableChartImage src={adHocChartUrl} alt={`${ticker} ${adHocTimeframe} chart`} />
            <div className="text-xs text-text-muted text-center font-body">
              Chart-only view — no Claude analysis for this timeframe
            </div>
          </>
        ) : hasErrors ? (
          <ChartErrorPanel errors={chartErrors} />
        ) : (
          <div className="flex flex-col items-center justify-center h-64 text-text-muted gap-2">
            <span className="text-sm font-body">No chart analysis available for this ticker</span>
            <span className="text-xs">Select a timeframe above to fetch a chart</span>
          </div>
        )}
      </div>
    </div>
  );
}
