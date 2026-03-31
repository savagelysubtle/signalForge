# SignalForge Research Team — Architecture Review & Upgrade Recommendations

## Overview

The SignalForge pipeline is a sophisticated 5-stage multi-agent system that mirrors the organizational structure of a real trading firm — a quantitative screener, a market analyst, a news researcher, a chart technician, and a signal synthesizer working in concert. Research into state-of-the-art LLM trading frameworks confirms this architecture closely matches what produces the best risk-adjusted returns in production systems. This document identifies every gap in the current research team (Stages 0–2) and provides concrete, implementable upgrades to make it the most accurate stock-sector research pipeline achievable with these tools.[^1][^2]

***

## Stage 0: FMP Pre-Screener — Current Gaps & Upgrades

### What It Does Well

The 9-step pipeline (screen → bulk fetch → merge → enrichment → post-filter → earnings → composite score → sort → sector cap) is structurally sound. Using bulk endpoints for the first five calls is the right performance choice — a single `ratios-ttm-bulk` call is orders of magnitude faster than per-ticker fetches. The four-dimension composite scoring (F/M/S/Q) with per-strategy weight vectors is the correct design — a momentum strategy at 45% momentum weight and a value strategy at 40% fundamental weight genuinely surface different stock universes.

### Gap 1: No FMP Technical Indicator Pre-Confirmation

The app does not call FMP's `/api/v3/technical_indicator/{timeframe}/{symbol}` endpoint at all, yet this endpoint supports RSI, EMA, ADX, Williams %R, and standard deviation natively at timeframes down to 1-minute. Currently, a stock can pass all 19 screener post-filters and still reach the chart analysis stage with an RSI of 78 (overbought) or an EMA stack in full bearish order. These are stocks the strategy's `ta_focus` would reject — but they consumed Perplexity and Gemini API credits to get there.[^3]

**Recommendation:** Add a lightweight technical pre-confirmation step after composite scoring, before the sector cap. For swing strategies, call `/api/v3/technical_indicator/daily/{symbol}?type=rsi&period=14` on the top 20 candidates. Reject any that fail the strategy's RSI zone. For intraday strategies, add the same check on the 1-hour timeframe. This costs ~20 additional FMP calls but eliminates technically invalid candidates before any expensive LLM stage runs.

```python
# Pseudo-code for technical pre-filter
async def fmp_technical_prefilter(candidates: list, strategy: StrategyConfig) -> list:
    if strategy.chart_indicators contains "RSI":
        rsi_tasks = [fetch_rsi(s.symbol, "daily", 14) for s in candidates[:20]]
        rsi_values = await asyncio.gather(*rsi_tasks)
        # Reject overbought (>75) for momentum-entry strategies
        # Reject >30 for mean-reversion strategies
    return filtered_candidates
```

### Gap 2: Composite Score Transparency Is Underweighted in Downstream Prompts

The composite score dimensional breakdown (F/M/S/Q individual scores) is passed to GPT but the raw percentile drivers aren't surfaced. Knowing a stock has `score_momentum: 91` is useful; knowing it's because `price_change_3m: +47%` and `rvol: 2.8` is significantly more actionable for the LLM. Structured reasoning in financial LLM systems benefits substantially from specific quantitative anchors rather than aggregate scores.[^1]

**Recommendation:** In `format_fmp_for_claude()` and `format_fmp_for_gpt()`, add the raw values that drove each dimensional score, not just the score itself. Example format:

```
Composite: 87/100 | Momentum: 91 (3m: +47%, rvol: 2.8x) | Fundamental: 72 (ROE: 18%, PE: 14) | Quality: 68 (Piotroski: 7, Altman: 3.2) | Sentiment: 65 (insider: NET BUY, analyst: Buy, upside: +14%)
```

### Gap 3: No Macro-Level FMP Context in Stage 0

FMP's `/stable/sector-performance-snapshot` is listed as available but not injected into the pipeline. The regime classifier (Stage 0.5) uses Perplexity to estimate sector performance — but FMP has the actual, real-time sector performance data for free. This is a category error: using an LLM to estimate something that a structured data endpoint provides exactly.

**Recommendation:** Fetch `/stable/sector-performance-snapshot` at Stage 0 start. Inject the top-3 and bottom-3 performing sectors directly into the regime classifier prompt and Perplexity's system prompt. This replaces LLM estimation with ground truth data and makes `dominant_sectors` in the `RegimeOutput` factual rather than inferred.

***

## Stage 0.5: Regime Classifier — Current Gaps & Upgrades

### Gap 4: Regime Is a Single LLM Call With No Grounding

The regime classifier currently makes one ungrounded Perplexity call to estimate VIX, breadth, and sector rotation. The VIX estimate (`calm/normal/elevated/fear`) is a qualitative guess — the actual VIX level is publicly available and FMP has it. Market breadth (% of S&P 500 above 200 MA) is similarly estimable from FMP bulk data already fetched in Stage 0.

**Recommendation:** Pre-populate the regime prompt with structured data before the LLM call:

| Field | Replace LLM Estimation With |
|---|---|
| `vix_estimate` | FMP `/stable/quote/^VIX` — actual VIX level → map to calm/normal/elevated/fear bands |
| `breadth_estimate` | Count stocks above 200 EMA in the Stage 0 bulk fetch → compute % in-house |
| `dominant_sectors` | FMP `/stable/sector-performance-snapshot` top performers |
| `defensive_rotation` | Compare utilities/staples/healthcare vs tech/discretionary in sector snapshot |

The LLM's role then shifts from estimating these values to interpreting them and writing the `implications` field — a task it's well-suited for. This change turns the regime output from "LLM opinion" to "LLM interpretation of verified data," which is architecturally the same upgrade made by providing FMP context to Perplexity's discovery stage.

### Gap 5: Regime Output Doesn't Feed Strategy Weight Adjustment

The regime context is injected as a text header into downstream prompts, but it doesn't dynamically modify the FMP composite scoring weights. In a `risk_off` or `trending_bear` regime, the `weight_quality` dimension (Piotroski, Altman Z) should automatically increase — investors flee to quality in downturns. In `trending_bull`, `weight_momentum` should increase. This is a missed opportunity to make the screener regime-adaptive without user intervention.

**Recommendation:** Add a `regime_weight_override` function that applies a small delta to FMP weights based on regime type:

```python
REGIME_WEIGHT_DELTAS = {
    "trending_bull":   {"momentum": +10, "fundamental": -5,  "quality": -5,  "sentiment": 0},
    "trending_bear":   {"momentum": -10, "fundamental": +5,  "quality": +10, "sentiment": -5},
    "range_bound":     {"momentum": -5,  "fundamental": +5,  "quality": +5,  "sentiment": -5},
    "high_volatility": {"momentum": -10, "fundamental": 0,   "quality": +15, "sentiment": -5},
    "risk_off":        {"momentum": -15, "fundamental": +5,  "quality": +15, "sentiment": -5},
    "sector_rotation": {"momentum": 0,   "fundamental": 0,   "quality": 0,   "sentiment": +10},
}
```

Cap any single dimension at 70 to prevent degenerate configurations.

***

## Stage 1: Perplexity Agent — Current Gaps & Upgrades

### What It Does Well

The domain-filtered web search (Canadian sources for TSX strategies, crypto sources for crypto strategies) is the right approach — confirmed by official Perplexity API documentation. Using API-level `search_domain_filter` parameters rather than prompt-level instructions for domain filtering is documented best practice. The FMP pre-screening context injection (treating FMP data as ground truth that Perplexity shouldn't re-verify numerically) is an excellent design — it correctly separates quantitative facts from qualitative research.[^4][^5]

The session context injection (`_get_session_context()` producing pre-market/market hours/after hours labels) is a non-obvious but high-value feature. Perplexity's models calibrate search result freshness expectations based on this context.[^5]

### Gap 6: Still Using `sonar` When `sonar-pro` or `sonar-deep-research` Would Be Better

The pipeline uses `perplexity/sonar` for discovery. As of March 2026, Perplexity has three distinct tiers:[^6][^7]

| Model | Cost | Search Depth | Best For |
|---|---|---|---|
| `sonar` | $1/M input | Single-step search | Simple factual lookups |
| `sonar-pro` | $3/M input | Multi-step, 2x citations | Complex multi-company research |
| `sonar-deep-research` | $2/M input + per-search | Exhaustive, dozens of searches | Comprehensive sector reports |

For stock discovery across multiple tickers with earnings data, insider activity, and analyst consensus all needing verification, `sonar-pro` is the correct model. It conducts multi-step searches, returns approximately 2x more citations, and surpasses even expensive competitor models on factual accuracy benchmarks. The cost delta ($3 vs $1 per million input tokens) is negligible relative to the FMP API costs already incurred.[^8][^7]

**Recommendation:** Upgrade the discovery and analysis modes to `sonar-pro`. Reserve `sonar-deep-research` for a new optional "deep mode" on high-conviction strategies (e.g., Earnings Play, Value Accumulation) where exhaustive research is worth the extra latency and cost.[^9]

### Gap 7: User Prompt Structure Violates Perplexity Best Practices

The current `build_discovery_prompt()` function builds a search-query-like string like: *"Find Canadian TSX stocks showing strong momentum... as of March 30, 2026 2:30 PM ET top 10 picks"*. This is nearly identical to the anti-pattern explicitly documented in Perplexity's official prompt guide:[^5]

> **Avoid**: "Act as an expert and give me [x]. Start by explaining [y], then list [z]..."
> **Instead**: Direct, specific search-optimized queries without role framing

The current prompt works but is sub-optimal because the LLM-facing part and the search-facing part are competing. The search component triggers on words like "Find Canadian TSX stocks showing" while the language generation component needs to produce a JSON schema.

**Recommendation:** Restructure the prompt into two distinct functional layers per official docs:[^4][^5]

- **Input (search-optimized):** `"Canadian TSX momentum breakout stocks high relative volume analyst upgrades {today} sector leaders"`
- **Instructions (generation-focused):** The JSON schema, anti-hallucination rules, market constraints, FMP trust block

This separates the two components that process these fields independently, improving both search result relevance and output quality.

### Gap 8: URL Extraction Is Prompt-Based, Not `search_results`-Field-Based

The current pipeline extracts citation URLs from the LLM's text response and from the `search_results` output items. Perplexity's official documentation explicitly warns that asking the LLM to include URLs in its generated text will produce hallucinated URLs because "the language model doesn't have access to the original URLs — always use the `search_results` field for accurate source information".[^5]

The current `_distribute_citations()` function partially mitigates this by using `SearchResultsOutputItem` from the agent API response, which is the correct source. However, if the JSON response body also contains URL fields filled by the LLM (rather than extracted from `search_results`), those URLs may be fabricated patterns rather than real links.

**Recommendation:** Audit `news_urls` in the `FundamentalData` schema. Ensure they are populated exclusively from `SearchResultsOutputItem` content (the API response's search results list), never from the LLM's generated JSON text. If `tickers[].sources[]` is populated by the LLM, treat those as contextual references only — never as navigable links.

### Gap 9: FMP Tool Definition Missing Key New Parameters

The Perplexity tool definition (`FMP_TOOL_DEFINITION`) exposes 17 parameters, but the v2 strategies introduced several fields that aren't in the tool: `altman_z_min`, `piotroski_min` with the upgraded values, `price_max`, `beta_max`, and `is_etf`. If Perplexity dynamically calls `screen_stocks` during its conversation, it cannot express `altman_z_min: 2.5` or `is_etf: false` — it can only work with the 17 original parameters.

**Recommendation:** Add these fields to `FMP_TOOL_DEFINITION`:

```json
{
  "name": "altman_z_min",
  "type": "number",
  "description": "Minimum Altman Z-Score. >2.99 = safe zone, <1.81 = financial distress. Recommended: 1.8 for swing, 2.5 for value strategies."
},
{
  "name": "beta_max",
  "type": "number",
  "description": "Maximum beta (volatility vs market). Use 3.5 for intraday, 2.5 for swing to exclude hyper-volatile names."
},
{
  "name": "is_etf",
  "type": "boolean",
  "description": "Include ETFs. Default false for all stock strategies."
},
{
  "name": "price_max",
  "type": "number",
  "description": "Maximum stock price. Use 200 for most strategies, 150 for intraday to avoid thin markets."
}
```

### Gap 10: No Per-Strategy `search_recency_filter` Parameter

Perplexity's API supports a `search_recency_filter` parameter (`"hour"`, `"day"`, `"week"`, `"month"`) that controls the maximum age of web search results. Currently, the strategies have `news_recency` fields (`"today"`, `"week"`, `"month"`) that map to prose in the Gemini prompt — but this field is never used to set the `search_recency_filter` API parameter for the Perplexity call.[^4]

For the **Intraday Scalp**, **EMA Stack Momentum**, **ORB**, and **VWAP Reversal** strategies with `news_recency: "today"`, the Perplexity search should be restricted to the last 24 hours at the API level. Without this, Perplexity may surface 3-week-old articles as the "latest" news for a same-day intraday trade.

**Recommendation:** Map `news_recency` to Perplexity's `search_recency_filter` parameter in `_call_agent_api()`:

```python
RECENCY_MAP = {
    "today": "day",
    "week":  "week",
    "month": "month"
}
search_recency_filter = RECENCY_MAP.get(config.news_recency, "week")
```

***

## Stage 2: Gemini + Google Search — Current Gaps & Upgrades

### What It Does Well

Running all tickers concurrently via `asyncio.gather` with `Semaphore(5)` is the correct pattern for Gemini rate limits. Reading Perplexity's pre-researched URLs before performing an additional targeted search is additive rather than duplicative — this is architecturally validated by academic research on multi-agent financial systems. The FMP context injection (company name, sector, earnings date, insider activity, analyst consensus) into each Gemini prompt is a best practice that significantly reduces hallucination by grounding Gemini's interpretation of news in verified facts.[^10][^11][^1]

The `sector_sentiment` as a separate, structured object (independent from company sentiment) is a sophisticated design that few trading pipelines implement — it allows the downstream signal generators to correctly weight systemic vs. idiosyncratic factors.

### Gap 11: Gemini Over-Relies on Grounding When URLs Are Provided

Gemini 2.5 Pro has a known behavior issue: when given URLs in the prompt, it over-relies on Google Search grounding rather than reading the pre-provided content, reducing output quality on structured tasks. This means the pre-researched Perplexity URLs in the user prompt may not actually be read — Gemini may instead perform its own independent search and ignore them.[^12]

**Recommendation:** Restructure the Gemini prompt to make URL reading an explicit, ordered instruction before the search instruction:

```
STEP 1 — Read provided sources (mandatory, do this first):
For each URL below, use Google Search to access and extract the full article content.
Report the headline, date, and key financial facts from each article.

STEP 2 — Perform ONE additional search only after reading all provided URLs:
Search: "{ticker} {key_highlight} {date}"

STEP 3 — Synthesize into the JSON schema below.
```

This sequencing exploits Gemini's instruction-following strength while counteracting its tendency to short-circuit to search.[^10]

### Gap 12: `sentiment_score` Lacks Confidence Weighting

The current `SentimentAnalysis` schema returns a flat `-1.0 to 1.0` score with no confidence indicator. A sentiment score of `+0.6` derived from three corroborating Reuters articles is meaningfully different from a `+0.6` derived from one mid-tier blog. Academic research on multi-agent LLM financial systems shows that confidence-weighted sentiment scoring — where high-significance catalysts from high-authority sources receive higher weights — improves signal quality measurably.[^13][^1]

**Recommendation:** Add a `confidence` field (0.0–1.0) to `SentimentAnalysis`:

```python
class SentimentAnalysis(BaseModel):
    sentiment_score: float          # -1.0 to 1.0
    confidence: float               # 0.0 to 1.0 (how many high-quality sources confirm the sentiment)
    sentiment_label: str
    key_catalysts: list[Catalyst]
    sector_sentiment: SectorSentiment
    summary: str
```

Populate `confidence` by having Gemini assess: number of unique sources, source authority tier (Reuters/Bloomberg = high, unknown blog = low), recency of sources, and consistency of sentiment across sources.

The GPT judge then receives both `sentiment_score` and `confidence` and can express this as: *"Sentiment is bullish (0.7) but low-confidence (0.3) — only one low-authority source found."*

### Gap 13: Sector Sentiment Is Not Aggregated Across Tickers Before GPT

Each Gemini call produces an independent `sector_sentiment` for a ticker. If 6 out of 8 Energy stocks all return `sector_sentiment.label = "bullish"` with `key_driver = "pipeline expansion tailwinds"`, this convergence is highly significant. Currently this pattern is invisible — GPT sees individual tickers in sequence, not the aggregated sector picture.

**Recommendation:** In the orchestrator, after `run_sentiment()` completes, aggregate `sector_sentiment` across tickers grouped by sector. Compute a median `sector_sentiment_score` per sector and identify the most common `key_driver`. Inject this sector-level consensus block into the GPT Stage 4 prompt as a pre-header:

```
## SECTOR SENTIMENT CONSENSUS
Energy: 6/8 tickers BULLISH (avg: +0.72) — Driver: "pipeline expansion regulatory approval"
Technology: 2/8 tickers BULLISH (avg: +0.41) — mixed signals
```

This gives GPT the emergent pattern that no individual ticker prompt contains.

### Gap 14: No Validation That Gemini Actually Read the Provided URLs

The `@with_validation_retry` decorator validates JSON schema compliance but doesn't verify that Gemini cited the provided URLs in its catalyst list. If all `key_catalysts[].url` fields are from Gemini's own search rather than Perplexity's pre-researched articles, the two-search-engine handoff has broken down silently.

**Recommendation:** Add a post-validation check in the orchestrator: compare `key_catalysts[].url` against the `ticker_news` URLs provided to that Gemini call. Log a metric `provided_url_hit_rate` = (catalysts citing provided URLs) / (total catalysts). If this metric drops below 30% consistently, it signals that Gemini is ignoring Perplexity's research — the prompt needs restructuring per Gap 11 above.

***

## Cross-Cutting: Strategy Fields That Are Underutilized

Several strategy config fields either don't flow into any prompt or are used less effectively than they could be:

| Field | Current Usage | Recommended Enhancement |
|---|---|---|
| `ta_focus` | Fed to Claude for chart analysis | Also inject into Perplexity's system prompt — tells Perplexity to search for stocks exhibiting *specific* technical conditions (e.g., "Bollinger Band squeeze") rather than generic momentum |
| `trading_style` | Not injected into any prompt | Inject into GPT Stage 4 as a hold-period constraint: "Signals must be actionable within the hold period of this strategy (5–20 days)" |
| `risk_params.min_risk_reward` | Not injected into any prompt | Inject into Claude and GPT: "Only flag as BUY if you can identify a price structure with R:R ≥ {min_risk_reward}. If not identifiable, output HOLD." |
| `constraint_style` | Used for loose/tight screening | Map to Perplexity's `search_context_size`: `tight` → `"high"` (more sources, more confident), `loose` → `"medium"` |
| `news_scope` | Only used in Gemini | Also use in Perplexity system prompt to adjust diversity of sources — `"macro"` scope should add macro news domains (federalreserve.gov, statscan.gc.ca) to the domain filter |

***

## New Agent Roles — What the Research Team Is Missing

Comparison with the TradingAgents framework (UCLA/MIT) and the P1GPT framework reveals two agent roles in leading research that SignalForge's pipeline currently lacks:[^2][^14][^1]

### Missing: Bull/Bear Debate Agent

TradingAgents' highest-impact design decision is the Bull/Bear researcher pair — two agents that independently research the same ticker from opposing perspectives, then debate before a decision is made. The `enable_debate` flag already exists in the strategy schema, which means this architecture was anticipated. However, the debate currently appears to be a single-LLM debate prompt rather than two truly independent research paths.[^15][^2]

**Recommendation:** When `enable_debate: true`, run two Perplexity calls in parallel for the discovery stage:
- **Bull call**: Same `screening_prompt` + `"positive catalysts analyst upgrades earnings beats insider buying"`
- **Bear call**: Same `screening_prompt` + `"risks headwinds regulatory concerns analyst downgrades insider selling"`

Both lists go to Stage 2 Gemini. The overlap (stocks in both lists) represents high-conviction candidates; stocks only in the bull list are speculative; stocks only in the bear list get explicit risk flagging in the GPT prompt. Research confirms debate-based architectures improve calibration under signal ambiguity, though they incur overhead that justifies the `enable_debate` flag being false for intraday scalp strategies where execution speed matters.[^16]

### Missing: Risk Management Agent

P1GPT's "Integration Reasoning Layer" and TradingAgents' "risk management team" both operate as a separate agent that reviews proposed signals against portfolio exposure, current drawdown, and regime context before finalization. Currently in SignalForge, risk management is embedded as parameters (`max_position_pct`, `min_risk_reward`) rather than as an active reasoning step.[^2][^1]

**Recommendation:** Add a lightweight Stage 2.5 between Gemini and Claude: a fast GPT-4o-mini (or Claude Haiku) call that takes the Gemini sentiment output and applies the strategy's `risk_params` as hard constraints, outputting a `risk_adjusted_score` per ticker. Tickers below threshold are demoted to HOLD before reaching the expensive Claude chart analysis stage. This prevents Claude from generating detailed BUY analysis for a ticker that a simple risk check would have eliminated.

***

## Priority Implementation Order

Given the cost/impact tradeoff, the recommended implementation order is:

| Priority | Change | Impact | Effort |
|---|---|---|---|
| 1 | Gap 10: `search_recency_filter` API parameter | High — prevents stale news for intraday | Very low (3 lines) |
| 2 | Gap 6: Upgrade to `sonar-pro` | High — better multi-company research accuracy[^7] | Very low (config change) |
| 3 | Gap 3 + Gap 4: FMP sector snapshot → regime classifier | High — replaces LLM estimation with real data | Low |
| 4 | Gap 8: Audit URL extraction source | High — prevents hallucinated links silently entering the pipeline[^5] | Low-medium |
| 5 | Gap 5: Regime → weight adjustment | Medium — adaptive screener weights | Medium |
| 6 | Gap 7: Restructure Perplexity prompt (input vs instructions split) | Medium — better search relevance[^5] | Medium |
| 7 | Gap 1: FMP technical pre-filter | Medium — reduces LLM spend on technically invalid candidates | Medium |
| 8 | Gap 11: Gemini prompt sequencing (URL-first) | Medium — counteracts Gemini over-grounding[^12] | Low |
| 9 | Gap 9: FMP tool definition updates | Medium — enables dynamic tool calls with v2 strategy params | Low |
| 10 | Gap 13: Sector sentiment aggregation | Medium — surfaces emergent patterns invisible to individual prompts | Medium |
| 11 | Gap 12: Sentiment confidence field | Medium — improves GPT signal calibration[^13] | Medium |
| 12 | Cross-cutting: `ta_focus` → Perplexity injection | Medium — better technical candidates surface | Low |
| 13 | Cross-cutting: `risk_params.min_risk_reward` injection | Medium — eliminates structurally poor R:R setups | Low |
| 14 | Bull/Bear debate (parallel Perplexity calls) | High — architecture proven in academic research[^2][^15] | High |
| 15 | Stage 2.5 risk management agent | High — prevents expensive analysis of ineligible tickers | High |

---

## References

1. [P1GPT: A Multi-Agent LLM Workflow Module for Multi-Modal ... - arXiv](https://arxiv.org/html/2510.23032v1) - We introduce P1GPT, a layered multi-agent LLM framework for multi-modal financial information analys...

2. [TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138) - by Y Xiao · 2024 · Cited by 166 — The framework includes Bull and Bear researcher agents assessing m...

3. [A brief description on how to use Financial Modeling Prep Api - GitHub](https://github.com/FinancialModelingPrepAPI/Financial-Modeling-Prep-API) - Real-time and historical data of stock prices. Supports over 25000 stocks across multiple exchanges....

4. [Best Practices - Perplexity API Platform](https://docs.perplexity.ai/docs/search/best-practices) - This guide covers essential best practices for getting the most out of Perplexity's Search API, incl...

5. [Prompt Guide - Perplexity API Platform](https://docs.perplexity.ai/docs/agent-api/prompt-guide) - ​. Best Practices for Prompting Web Search Models · Be Specific and Contextual · Avoid Few-Shot Prom...

6. [5 Best Perplexity Alternatives for AI Developers Building Research ...](https://www.firecrawl.dev/blog/perplexity-alternatives) - Perplexity works for conversational search, but developers building AI agents and RAG systems need s...

7. [Improved Sonar Models: Industry Leading Performance at Lower ...](https://www.perplexity.ai/hub/blog/new-sonar-search-modes-outperform-openai-in-cost-and-performance) - Sonar excels at providing fast and accurate answers, making it a great model for everyday use. Perpl...

8. [Sonar Deep Research vs Sonar Pro - Price Per Token](https://pricepertoken.com/compare/perplexity-sonar-deep-research-vs-perplexity-sonar-pro) - Compare Sonar Deep Research and Sonar Pro API pricing, benchmarks, and capabilities. Sonar Deep Rese...

9. [Introducing Perplexity Deep Research](https://www.perplexity.ai/hub/blog/introducing-perplexity-deep-research) - Today we're launching Deep Research to save you hours of time by conducting in-depth research and an...

10. [How Google grounds its LLM, Gemini. - Dejan.ai](https://dejan.ai/blog/gemini-grounding/) - We uncovered key aspects of how Google's Gemini large language model verifies its responses through ...

11. [LLM Hallucinations: What Are the Implications for Financial ...](https://biztechmagazine.com/article/2025/08/llm-hallucinations-what-are-implications-financial-institutions) - Best Practices To Mitigate LLM Hallucinations in Financial Services · Small language models: Train m...

12. [Gemini 2.5 pro over relies on grounding google search when asked ...](https://www.reddit.com/r/Bard/comments/1m4hy6y/gemini_25_pro_over_relies_on_grounding_google/) - I've been experimenting with 2.5 Pro in AI Studio lately, Google grounding should only be used when ...

13. [[PDF] Adaptive LLM-based multi-agent systems to enhance quantitative ...](https://peerj.com/articles/cs-3630.pdf) - The Sentiment Analysis Agent contributes 8.90 pps (16.5% improvement) by processing news flows and q...

14. [TradingAgents: Multi-Agents LLM Financial Trading Framework - arXiv](https://arxiv.org/html/2412.20138v5) - The framework includes Bull and Bear researcher agents assessing market conditions, a risk managemen...

15. [Multi-Agents LLM Financial Trading Framework | Bernd Wuebben](https://www.linkedin.com/posts/berndwuebben_tradingagents-multi-agents-llm-financial-activity-7280969340844138496-iXH_) - ... bull" and "bear" researchers who debate different market perspectives! What's particularly inter...

16. [Toward Reliable Evaluation of LLM-Based Financial Multi-Agent ...](https://arxiv.org/html/2603.27539v1) - Debate-based architectures improve calibration under signal ambiguity but incur overhead costly when...

