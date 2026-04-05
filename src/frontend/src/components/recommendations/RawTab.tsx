import { useState } from 'react';
import type { PipelineResult } from '../../types';
import { ChevronDown, ChevronUp, Copy, Check } from 'lucide-react';

interface RawTabProps {
  data: PipelineResult;
}

interface SectionProps {
  title: string;
  subtitle?: string;
  data: unknown;
  defaultOpen?: boolean;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 text-[10px] text-text-muted hover:text-accent-signal transition-colors font-display"
      title="Copy JSON"
    >
      {copied ? (
        <>
          <Check className="w-3 h-3 text-accent-profit" />
          <span className="text-accent-profit">Copied</span>
        </>
      ) : (
        <>
          <Copy className="w-3 h-3" />
          Copy
        </>
      )}
    </button>
  );
}

function Section({ title, subtitle, data, defaultOpen = false }: SectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const json = JSON.stringify(data, null, 2);

  return (
    <div className="border border-border-gutter rounded-lg overflow-hidden">
      <button
        onClick={() => setIsOpen(prev => !prev)}
        className="w-full flex items-center justify-between px-4 py-3 bg-bg-concrete hover:bg-bg-steel/40 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-display font-semibold text-text-primary">{title}</span>
          {subtitle && (
            <span className="text-[10px] text-text-muted font-body">{subtitle}</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {isOpen && <CopyButton text={json} />}
          {isOpen ? (
            <ChevronUp className="w-4 h-4 text-text-muted" />
          ) : (
            <ChevronDown className="w-4 h-4 text-text-muted" />
          )}
        </div>
      </button>

      {isOpen && (
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <pre className="text-xs font-display p-4 bg-bg-void text-text-secondary leading-relaxed whitespace-pre-wrap break-all">
            <JsonHighlight json={json} />
          </pre>
        </div>
      )}
    </div>
  );
}

function JsonHighlight({ json }: { json: string }) {
  // Simple token-based colorization
  const tokenized = json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let cls = 'text-accent-profit'; // number
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? 'text-accent-signal' : 'text-accent-alert/90'; // key vs string
      } else if (/true|false/.test(match)) {
        cls = 'text-accent-electric';
      } else if (/null/.test(match)) {
        cls = 'text-text-muted';
      }
      return `<span class="${cls}">${match}</span>`;
    },
  );

  return <span dangerouslySetInnerHTML={{ __html: tokenized }} />;
}

export function RawTab({ data }: RawTabProps) {
  const promptVersionEntries = Object.entries(data.prompt_versions ?? {});

  return (
    <div className="p-4 h-full overflow-auto space-y-3">
      {/* Run Identity */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-bg-concrete rounded-lg border border-border-gutter">
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-[11px] font-display text-text-muted">
          <span>
            <span className="text-text-secondary">Run</span>{' '}
            <span className="text-accent-signal/80">{data.run_id}</span>
          </span>
          <span>
            <span className="text-text-secondary">Mode</span>{' '}
            {data.mode}
          </span>
          {data.strategy_name && (
            <span>
              <span className="text-text-secondary">Strategy</span>{' '}
              {data.strategy_name}
            </span>
          )}
          {data.timestamp && (
            <span>
              <span className="text-text-secondary">Ran at</span>{' '}
              {new Date(data.timestamp).toLocaleString()}
            </span>
          )}
        </div>
        {promptVersionEntries.length > 0 && (
          <div className="flex flex-wrap gap-2 ml-4">
            {promptVersionEntries.map(([stage, hash]) => (
              <span
                key={stage}
                className="text-[9px] font-display px-1.5 py-0.5 rounded bg-bg-void border border-border-subtle text-text-muted"
                title={`${stage} prompt hash`}
              >
                {stage}: {hash}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Stage sections */}
      {data.screening && (
        <Section
          title="Stage 1 — Perplexity Screening"
          subtitle={`${data.screening.tickers.length} tickers`}
          data={data.screening}
        />
      )}

      {data.sentiment_analyses.length > 0 && (
        <Section
          title="Stage 2 — Gemini Sentiment"
          subtitle={`${data.sentiment_analyses.length} tickers`}
          data={data.sentiment_analyses}
        />
      )}

      {data.chart_analyses.length > 0 && (
        <Section
          title="Stage 3 — Claude Chart Analysis"
          subtitle={`${data.chart_analyses.length} analyses`}
          data={data.chart_analyses}
        />
      )}

      {data.recommendations.length > 0 && (
        <Section
          title="Stage 4 — GPT Synthesis"
          subtitle={`${data.recommendations.length} recommendations`}
          data={data.recommendations}
        />
      )}

      {data.recommendations.some(r => r.ml_probability != null) && (
        <Section
          title="Stage 4.8 — LightGBM Gate"
          subtitle={`${data.recommendations.filter(r => r.ml_probability != null).length} scored · ${data.recommendations.filter(r => r.ml_blocked).length} blocked`}
          data={data.recommendations
            .filter(r => r.ml_probability != null)
            .map(r => ({
              ticker: r.ticker,
              ml_probability: r.ml_probability,
              ml_size_multiplier: r.ml_size_multiplier,
              ml_blocked: r.ml_blocked,
              ml_model_version: r.ml_model_version,
              ml_conformal_set: r.ml_conformal_set,
              raw_gpt_position_size_pct: r.raw_gpt_position_size_pct,
              adjusted_position_size_pct: r.position_size_pct,
            }))}
        />
      )}

      {(data.stage_errors ?? []).length > 0 && (
        <Section
          title="Stage Errors"
          subtitle={`${data.stage_errors.length} error${data.stage_errors.length !== 1 ? 's' : ''}`}
          data={data.stage_errors}
        />
      )}

      {/* Full dump */}
      <Section
        title="Full Pipeline Result"
        subtitle="raw JSON"
        data={data}
      />
    </div>
  );
}
