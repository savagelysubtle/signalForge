import type { SentimentAnalysis, NewsCatalyst, SentimentBucket, SectorSentiment } from '../../types';
import clsx from 'clsx';

interface SentimentTabProps {
  sentiment: SentimentAnalysis | null;
}

const LABEL_CONFIG: Record<string, { text: string; color: string; bg: string }> = {
  strongly_bullish: { text: 'Strongly Bullish', color: 'text-accent-profit', bg: 'bg-accent-profit/15' },
  bullish: { text: 'Bullish', color: 'text-accent-profit', bg: 'bg-accent-profit/10' },
  neutral: { text: 'Neutral', color: 'text-accent-alert', bg: 'bg-accent-alert/10' },
  bearish: { text: 'Bearish', color: 'text-accent-loss', bg: 'bg-accent-loss/10' },
  strongly_bearish: { text: 'Strongly Bearish', color: 'text-accent-loss', bg: 'bg-accent-loss/15' },
};

const BUCKET_CONFIG: Record<SentimentBucket, { text: string; color: string; bg: string }> = {
  strongly_bullish: { text: 'Strongly Bullish', color: 'text-accent-profit', bg: 'bg-accent-profit/15' },
  bullish: { text: 'Bullish', color: 'text-accent-profit', bg: 'bg-accent-profit/10' },
  mildly_bullish: { text: 'Mildly Bullish', color: 'text-accent-profit/80', bg: 'bg-accent-profit/8' },
  neutral: { text: 'Neutral', color: 'text-accent-alert', bg: 'bg-accent-alert/10' },
  mildly_bearish: { text: 'Mildly Bearish', color: 'text-accent-loss/80', bg: 'bg-accent-loss/8' },
  bearish: { text: 'Bearish', color: 'text-accent-loss', bg: 'bg-accent-loss/10' },
  strongly_bearish: { text: 'Strongly Bearish', color: 'text-accent-loss', bg: 'bg-accent-loss/15' },
};

const IMPACT_COLORS: Record<string, string> = {
  positive: 'text-accent-profit',
  negative: 'text-accent-loss',
  neutral: 'text-accent-alert',
};

const SIGNIFICANCE_STYLES: Record<string, string> = {
  high: 'bg-accent-signal-dim text-accent-signal',
  medium: 'bg-bg-concrete text-text-secondary',
  low: 'bg-bg-concrete text-text-muted',
};

function scoreToPercent(score: number): number {
  return Math.round(((score + 1) / 2) * 100);
}

function scoreBarColor(score: number): string {
  if (score >= 0.6) return 'bg-accent-profit';
  if (score >= 0.2) return 'bg-accent-profit/60';
  if (score > -0.2) return 'bg-accent-alert';
  if (score > -0.6) return 'bg-accent-loss/60';
  return 'bg-accent-loss';
}

function formatRecency(hoursAgo: number | null | undefined): string | null {
  if (hoursAgo == null) return null;
  if (hoursAgo < 1) return 'just now';
  if (hoursAgo < 24) return `${hoursAgo}h ago`;
  const days = Math.floor(hoursAgo / 24);
  return `${days}d ago`;
}

function CatalystRow({ catalyst }: { catalyst: NewsCatalyst }) {
  const recency = formatRecency(catalyst.hours_ago);

  return (
    <div className="flex items-start gap-3 py-3 border-b border-border-subtle last:border-0">
      <div className={clsx('mt-1 w-2 h-2 rounded-full shrink-0', {
        'bg-accent-profit': catalyst.impact === 'positive',
        'bg-accent-loss': catalyst.impact === 'negative',
        'bg-accent-alert': catalyst.impact === 'neutral',
      })} />
      <div className="flex-1 min-w-0">
        {catalyst.url ? (
          <a
            href={catalyst.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-accent-signal hover:underline leading-snug"
          >
            {catalyst.headline}
          </a>
        ) : (
          <p className="text-sm text-text-primary leading-snug">{catalyst.headline}</p>
        )}
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-xs text-text-muted truncate max-w-[200px]">{catalyst.source}</span>
          {recency && (
            <span className="text-xs text-text-muted font-display">{recency}</span>
          )}
          <span className={clsx('text-xs capitalize', IMPACT_COLORS[catalyst.impact])}>
            {catalyst.impact}
          </span>
          <span className={clsx('text-xs px-1.5 py-0.5 rounded', SIGNIFICANCE_STYLES[catalyst.significance])}>
            {catalyst.significance}
          </span>
        </div>
      </div>
    </div>
  );
}

function SectorSentimentCard({ sector }: { sector: SectorSentiment }) {
  const sectorLabel = LABEL_CONFIG[sector.label] ?? LABEL_CONFIG.neutral;
  const sectorPercent = scoreToPercent(sector.score);

  return (
    <div className="bg-bg-concrete rounded-lg border border-border-gutter p-4">
      <h3 className="text-sm font-semibold text-text-secondary mb-3 font-body">Sector Sentiment</h3>
      <div className="flex items-center justify-between mb-2">
        <span className={clsx('text-xl font-display font-bold tabular-nums', sectorLabel.color)}>
          {sector.score > 0 ? '+' : ''}{sector.score.toFixed(2)}
        </span>
        <span className={clsx('px-2.5 py-1 rounded text-xs font-semibold', sectorLabel.bg, sectorLabel.color)}>
          {sectorLabel.text}
        </span>
      </div>
      <div className="w-full h-1.5 bg-bg-void rounded-full overflow-hidden mb-2">
        <div
          className={clsx('h-full rounded-full transition-all', scoreBarColor(sector.score))}
          style={{ width: `${sectorPercent}%` }}
        />
      </div>
      {sector.key_driver && (
        <p className="text-xs text-text-secondary leading-relaxed mt-2">{sector.key_driver}</p>
      )}
    </div>
  );
}

export function SentimentTab({ sentiment }: SentimentTabProps) {
  if (!sentiment) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted">
        <div className="text-center">
          <h3 className="text-lg font-semibold mb-2 font-body">No Sentiment Data</h3>
          <p className="text-sm">Gemini news analysis was not available for this ticker.</p>
        </div>
      </div>
    );
  }

  const label = LABEL_CONFIG[sentiment.sentiment_label] ?? LABEL_CONFIG.neutral;
  const bucket = sentiment.sentiment_bucket
    ? (BUCKET_CONFIG[sentiment.sentiment_bucket] ?? BUCKET_CONFIG.neutral)
    : null;
  const percent = scoreToPercent(sentiment.sentiment_score);

  return (
    <div className="p-6 overflow-y-auto h-full">
      {/* Score Header */}
      <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <div className="text-xs text-text-muted mb-1 font-body">Sentiment Score</div>
            <div className={clsx('text-4xl font-display font-bold tabular-nums', label.color)}>
              {sentiment.sentiment_score > 0 ? '+' : ''}{sentiment.sentiment_score.toFixed(2)}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {bucket && bucket.text !== label.text && (
              <div className={clsx('px-3 py-1.5 rounded-lg text-xs font-semibold', bucket.bg, bucket.color)}>
                {bucket.text}
              </div>
            )}
            <div className={clsx('px-4 py-2 rounded-lg text-sm font-semibold', label.bg, label.color)}>
              {label.text}
            </div>
          </div>
        </div>
        {/* Score bar */}
        <div className="w-full h-2 bg-bg-void rounded-full overflow-hidden">
          <div
            className={clsx('h-full rounded-full transition-all', scoreBarColor(sentiment.sentiment_score))}
            style={{ width: `${percent}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-text-muted mt-1 font-display">
          <span>-1.0 Bearish</span>
          <span>0 Neutral</span>
          <span>+1.0 Bullish</span>
        </div>
      </div>

      {/* Summary */}
      <div className="bg-bg-concrete rounded-lg border border-border-gutter p-6 mb-6">
        <h3 className="text-sm font-semibold text-text-secondary mb-2 font-body">Analysis Summary</h3>
        <p className="text-sm text-text-primary leading-relaxed">{sentiment.summary}</p>
      </div>

      {/* Key Catalysts */}
      <div className="mb-6">
        <h3 className="text-sm font-semibold text-text-secondary mb-3 font-body">
          Key Catalysts
          <span className="ml-2 text-xs font-normal text-text-secondary">
            ({sentiment.key_catalysts.length})
          </span>
        </h3>
        {sentiment.key_catalysts.length > 0 ? (
          <div className="bg-bg-concrete rounded-lg border border-border-gutter px-4">
            {sentiment.key_catalysts.map((c, i) => (
              <CatalystRow key={i} catalyst={c} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-text-muted">No catalysts identified.</p>
        )}
      </div>

      {/* Sector Sentiment + Recency */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <SectorSentimentCard sector={sentiment.sector_sentiment} />
        <div className="bg-bg-concrete rounded-lg border border-border-gutter p-4 flex flex-col justify-center">
          <h3 className="text-sm font-semibold text-text-secondary mb-3 font-body">News Window</h3>
          <span className="text-sm bg-bg-void px-3 py-1.5 rounded border border-border-subtle text-text-primary font-display inline-block w-fit">
            {sentiment.news_recency || 'N/A'}
          </span>
        </div>
      </div>
    </div>
  );
}
