import { useMemo } from 'react';
import type { ChartAnalysis, Recommendation } from '../../types';
import clsx from 'clsx';

interface PriceLevelMapProps {
  analysis: ChartAnalysis;
  recommendation: Recommendation | null;
}

interface PriceLine {
  price: number;
  label: string;
  type: 'support' | 'resistance' | 'current' | 'entry' | 'stop' | 'target';
  strength?: 'strong' | 'moderate' | 'weak';
}

const LINE_STYLES: Record<PriceLine['type'], { stroke: string; opacity: number; dashArray?: string }> = {
  support: { stroke: '#00e59b', opacity: 1 },
  resistance: { stroke: '#ff3b5c', opacity: 1 },
  current: { stroke: '#e8ecf4', opacity: 1 },
  entry: { stroke: '#4d8dff', opacity: 0.9, dashArray: '6 4' },
  stop: { stroke: '#ff3b5c', opacity: 0.9, dashArray: '6 4' },
  target: { stroke: '#00e59b', opacity: 0.9, dashArray: '6 4' },
};

const STRENGTH_OPACITY: Record<string, number> = {
  strong: 1.0,
  moderate: 0.55,
  weak: 0.3,
};

const TREND_ARROWS: Record<string, string> = {
  bullish: '\u25B2',
  bearish: '\u25BC',
  neutral: '\u25B6',
  transitioning: '\u27F3',
};

const TREND_COLORS: Record<string, string> = {
  bullish: 'text-accent-profit',
  bearish: 'text-accent-loss',
  neutral: 'text-accent-alert',
  transitioning: 'text-accent-signal',
};

function buildPriceLines(analysis: ChartAnalysis, recommendation: Recommendation | null): PriceLine[] {
  const lines: PriceLine[] = [];

  for (const level of analysis.key_levels) {
    lines.push({
      price: level.price,
      label: `${level.level_type === 'support' ? 'Support' : 'Resistance'} (${level.strength})`,
      type: level.level_type,
      strength: level.strength,
    });
  }

  if (analysis.current_price != null) {
    lines.push({ price: analysis.current_price, label: 'Current Price', type: 'current' });
  }

  if (recommendation) {
    if (recommendation.entry_price != null) {
      lines.push({ price: recommendation.entry_price, label: 'Entry', type: 'entry' });
    }
    if (recommendation.stop_loss != null) {
      lines.push({ price: recommendation.stop_loss, label: 'Stop Loss', type: 'stop' });
    }
    if (recommendation.take_profit != null) {
      lines.push({ price: recommendation.take_profit, label: 'Take Profit', type: 'target' });
    }
  }

  return lines;
}

function PriceLineRow({
  line,
  y,
  width,
}: {
  line: PriceLine;
  y: number;
  width: number;
}) {
  const style = LINE_STYLES[line.type];
  const isCurrent = line.type === 'current';
  const strengthOpacity = line.strength ? STRENGTH_OPACITY[line.strength] ?? 1 : 1;
  const effectiveOpacity = (line.type === 'support' || line.type === 'resistance')
    ? style.opacity * strengthOpacity
    : style.opacity;

  const labelX = 8;
  const priceX = width - 8;

  return (
    <g>
      <line
        x1={0}
        y1={y}
        x2={width}
        y2={y}
        stroke={style.stroke}
        strokeWidth={isCurrent ? 2.5 : 1.5}
        strokeDasharray={style.dashArray}
        opacity={effectiveOpacity}
      />
      {/* Label background + text (left side) */}
      <rect
        x={labelX}
        y={y - 11}
        width={line.label.length * 6.5 + 12}
        height={18}
        rx={4}
        fill="rgba(8, 9, 13, 0.9)"
        stroke={style.stroke}
        strokeWidth={0.5}
        opacity={effectiveOpacity}
      />
      <text
        x={labelX + 6}
        y={y + 3}
        fill={style.stroke}
        fontSize={10}
        fontWeight={isCurrent ? 700 : 500}
        opacity={effectiveOpacity}
        fontFamily="'JetBrains Mono Variable', 'JetBrains Mono', monospace"
      >
        {line.label}
      </text>
      {/* Price value (right side) */}
      <rect
        x={priceX - (line.price.toFixed(2).length * 7 + 14)}
        y={y - 11}
        width={line.price.toFixed(2).length * 7 + 12}
        height={18}
        rx={4}
        fill="rgba(8, 9, 13, 0.9)"
        stroke={style.stroke}
        strokeWidth={0.5}
        opacity={effectiveOpacity}
      />
      <text
        x={priceX - 6}
        y={y + 3}
        fill={style.stroke}
        fontSize={11}
        fontWeight={700}
        textAnchor="end"
        opacity={effectiveOpacity}
        fontFamily="'JetBrains Mono Variable', 'JetBrains Mono', monospace"
      >
        ${line.price.toFixed(2)}
      </text>
    </g>
  );
}

export function PriceLevelMap({ analysis, recommendation }: PriceLevelMapProps) {
  const lines = useMemo(() => buildPriceLines(analysis, recommendation), [analysis, recommendation]);

  const { minPrice, maxPrice } = useMemo(() => {
    if (lines.length === 0) return { minPrice: 0, maxPrice: 100, priceRange: 100 };
    const prices = lines.map(l => l.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const range = max - min || max * 0.1 || 10;
    const padding = range * 0.12;
    return { minPrice: min - padding, maxPrice: max + padding, priceRange: range + padding * 2 };
  }, [lines]);

  const svgWidth = 420;
  const topMargin = 50;
  const bottomMargin = 60;
  const svgHeight = Math.max(300, lines.length * 50 + topMargin + bottomMargin);
  const chartHeight = svgHeight - topMargin - bottomMargin;

  const priceToY = (price: number): number => {
    const ratio = (price - minPrice) / (maxPrice - minPrice);
    return topMargin + chartHeight * (1 - ratio);
  };

  const sortedLines = useMemo(
    () => [...lines].sort((a, b) => b.price - a.price),
    [lines],
  );

  const rrRatio = recommendation?.risk_reward_ratio;
  const action = recommendation?.action;

  if (lines.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted flex-col gap-2">
        <span className="text-sm font-body">Price Level Map</span>
        <span className="text-xs opacity-50">No price data available</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header badges */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-gutter shrink-0">
        <div className="flex items-center gap-2">
          <span className={clsx('text-lg', TREND_COLORS[analysis.trend_direction])}>
            {TREND_ARROWS[analysis.trend_direction]}
          </span>
          <span className="text-xs text-text-secondary font-body">
            {analysis.trend_direction} / {analysis.trend_strength}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {action && (
            <span className={clsx(
              'text-xs font-display font-bold px-2.5 py-1 rounded',
              action === 'BUY' && 'bg-accent-profit/15 text-accent-profit',
              action === 'SELL' && 'bg-accent-loss/15 text-accent-loss',
              action === 'HOLD' && 'bg-accent-alert/15 text-accent-alert',
            )}>
              {action}
            </span>
          )}
          {rrRatio != null && (
            <span className="text-xs font-display text-text-secondary bg-bg-concrete px-2 py-1 rounded">
              R:R {rrRatio.toFixed(1)}:1
            </span>
          )}
        </div>
      </div>

      {/* Patterns */}
      {analysis.patterns_detected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 py-2 border-b border-border-gutter shrink-0">
          {analysis.patterns_detected.map((pattern, i) => (
            <span
              key={i}
              className="text-[10px] font-display px-2 py-0.5 rounded bg-accent-signal-dim text-accent-signal border border-accent-signal/20"
            >
              {pattern}
            </span>
          ))}
        </div>
      )}

      {/* SVG price map */}
      <div className="flex-1 overflow-hidden p-3">
        <svg
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          width="100%"
          height="100%"
          preserveAspectRatio="xMidYMid meet"
          className="select-none"
        >
          {/* Gradient background zones */}
          <defs>
            <linearGradient id="bgGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ff3b5c" stopOpacity="0.04" />
              <stop offset="50%" stopColor="#181c27" stopOpacity="0.02" />
              <stop offset="100%" stopColor="#00e59b" stopOpacity="0.04" />
            </linearGradient>
          </defs>
          <rect
            x={0}
            y={topMargin}
            width={svgWidth}
            height={chartHeight}
            fill="url(#bgGradient)"
            rx={6}
          />

          {/* Grid lines (subtle) */}
          {Array.from({ length: 5 }, (_, i) => {
            const y = topMargin + (chartHeight / 4) * i;
            return (
              <line
                key={i}
                x1={0}
                y1={y}
                x2={svgWidth}
                y2={y}
                stroke="currentColor"
                strokeWidth={0.3}
                opacity={0.15}
              />
            );
          })}

          {/* Price lines */}
          {sortedLines.map((line, i) => (
            <PriceLineRow
              key={`${line.type}-${line.price}-${i}`}
              line={line}
              y={priceToY(line.price)}
              width={svgWidth}
            />
          ))}

          {/* Risk zone shading between entry and stop */}
          {recommendation?.entry_price != null && recommendation?.stop_loss != null && (
            <rect
              x={0}
              y={Math.min(priceToY(recommendation.entry_price), priceToY(recommendation.stop_loss))}
              width={svgWidth}
              height={Math.abs(priceToY(recommendation.entry_price) - priceToY(recommendation.stop_loss))}
              fill="#ff3b5c"
              opacity={0.06}
              rx={2}
            />
          )}

          {/* Reward zone shading between entry and target */}
          {recommendation?.entry_price != null && recommendation?.take_profit != null && (
            <rect
              x={0}
              y={Math.min(priceToY(recommendation.entry_price), priceToY(recommendation.take_profit))}
              width={svgWidth}
              height={Math.abs(priceToY(recommendation.entry_price) - priceToY(recommendation.take_profit))}
              fill="#00e59b"
              opacity={0.06}
              rx={2}
            />
          )}
        </svg>
      </div>

      {/* Footer legend */}
      <div className="flex items-center justify-center gap-4 px-4 py-2 border-t border-border-gutter shrink-0 text-[10px] text-text-muted">
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-[#00e59b] inline-block rounded" /> Support
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-[#ff3b5c] inline-block rounded" /> Resistance
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 bg-[#e8ecf4] inline-block rounded" /> Current
        </span>
        <span className="flex items-center gap-1">
          <span className="w-3 h-0.5 border-t border-dashed border-[#4d8dff] inline-block" /> Trade
        </span>
      </div>
    </div>
  );
}
