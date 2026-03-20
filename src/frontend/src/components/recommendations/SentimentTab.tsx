import type { SentimentAnalysis, NewsCatalyst } from '../../types';
import clsx from 'clsx';

interface SentimentTabProps {
  sentiment: SentimentAnalysis | null;
}

const LABEL_CONFIG: Record<string, { text: string; color: string; bg: string }> = {
  strongly_bullish: { text: 'Strongly Bullish', color: 'text-accent-green', bg: 'bg-accent-green/15' },
  bullish: { text: 'Bullish', color: 'text-accent-green', bg: 'bg-accent-green/10' },
  neutral: { text: 'Neutral', color: 'text-accent-yellow', bg: 'bg-accent-yellow/10' },
  bearish: { text: 'Bearish', color: 'text-accent-red', bg: 'bg-accent-red/10' },
  strongly_bearish: { text: 'Strongly Bearish', color: 'text-accent-red', bg: 'bg-accent-red/15' },
};

const IMPACT_COLORS: Record<string, string> = {
  positive: 'text-accent-green',
  negative: 'text-accent-red',
  neutral: 'text-accent-yellow',
};

const SIGNIFICANCE_STYLES: Record<string, string> = {
  high: 'bg-accent-blue/15 text-accent-blue',
  medium: 'bg-bg-tertiary text-text-secondary',
  low: 'bg-bg-tertiary text-text-secondary opacity-70',
};

function scoreToPercent(score: number): number {
  return Math.round(((score + 1) / 2) * 100);
}

function scoreBarColor(score: number): string {
  if (score >= 0.6) return 'bg-accent-green';
  if (score >= 0.2) return 'bg-accent-green/60';
  if (score > -0.2) return 'bg-accent-yellow';
  if (score > -0.6) return 'bg-accent-red/60';
  return 'bg-accent-red';
}

function CatalystRow({ catalyst }: { catalyst: NewsCatalyst }) {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-border last:border-0">
      <div className={clsx('mt-1 w-2 h-2 rounded-full shrink-0', {
        'bg-accent-green': catalyst.impact === 'positive',
        'bg-accent-red': catalyst.impact === 'negative',
        'bg-accent-yellow': catalyst.impact === 'neutral',
      })} />
      <div className="flex-1 min-w-0">
        {catalyst.url ? (
          <a
            href={catalyst.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-accent-blue hover:underline leading-snug"
          >
            {catalyst.headline}
          </a>
        ) : (
          <p className="text-sm text-text-primary leading-snug">{catalyst.headline}</p>
        )}
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-xs text-text-secondary truncate max-w-[200px]">{catalyst.source}</span>
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

export function SentimentTab({ sentiment }: SentimentTabProps) {
  if (!sentiment) {
    return (
      <div className="flex items-center justify-center h-full text-text-secondary">
        <div className="text-center">
          <h3 className="text-lg font-semibold mb-2">No Sentiment Data</h3>
          <p>Gemini news analysis was not available for this ticker.</p>
        </div>
      </div>
    );
  }

  const label = LABEL_CONFIG[sentiment.sentiment_label] ?? LABEL_CONFIG.neutral;
  const percent = scoreToPercent(sentiment.sentiment_score);

  return (
    <div className="p-6 overflow-y-auto h-full">
      {/* Score Header */}
      <div className="bg-bg-tertiary rounded-lg border border-border p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-xs text-text-secondary mb-1">Sentiment Score</div>
            <div className={clsx('text-4xl font-bold tabular-nums', label.color)}>
              {sentiment.sentiment_score > 0 ? '+' : ''}{sentiment.sentiment_score.toFixed(2)}
            </div>
          </div>
          <div className={clsx('px-4 py-2 rounded-lg text-sm font-semibold', label.bg, label.color)}>
            {label.text}
          </div>
        </div>
        {/* Score bar */}
        <div className="w-full h-2 bg-bg-primary rounded-full overflow-hidden">
          <div
            className={clsx('h-full rounded-full transition-all', scoreBarColor(sentiment.sentiment_score))}
            style={{ width: `${percent}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-text-secondary mt-1">
          <span>-1.0 Bearish</span>
          <span>0 Neutral</span>
          <span>+1.0 Bullish</span>
        </div>
      </div>

      {/* Summary */}
      <div className="mb-6">
        <h3 className="text-sm font-semibold text-text-secondary mb-2">Analysis Summary</h3>
        <p className="text-sm text-text-primary leading-relaxed">{sentiment.summary}</p>
      </div>

      {/* Key Catalysts */}
      <div className="mb-6">
        <h3 className="text-sm font-semibold text-text-secondary mb-3">
          Key Catalysts
          <span className="ml-2 text-xs font-normal text-text-secondary">
            ({sentiment.key_catalysts.length})
          </span>
        </h3>
        {sentiment.key_catalysts.length > 0 ? (
          <div className="bg-bg-tertiary rounded-lg border border-border px-4">
            {sentiment.key_catalysts.map((c, i) => (
              <CatalystRow key={i} catalyst={c} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-text-secondary">No catalysts identified.</p>
        )}
      </div>

      {/* Sector Sentiment + Recency */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2">Sector Sentiment</h3>
          <p className="text-sm text-text-primary leading-relaxed">{sentiment.sector_sentiment || 'N/A'}</p>
        </div>
        <div>
          <h3 className="text-sm font-semibold text-text-secondary mb-2">News Window</h3>
          <span className="text-sm bg-bg-tertiary px-3 py-1.5 rounded border border-border text-text-primary">
            {sentiment.news_recency || 'N/A'}
          </span>
        </div>
      </div>
    </div>
  );
}
