# Optimizing Sonar Pro Prompts for a Stock Finder & News Aggregator

## Executive Summary

Sonar Pro's architecture is fundamentally different from standard LLMs — it combines a **web search component** and a **language generation component** that operate independently. The web search component is triggered by the user prompt and responds to real search queries; the language model then processes the retrieved content. This means most prompt optimization must happen at the **API parameter level**, not inside the prompt text itself. For a stock finder and news aggregator, the highest leverage comes from: using `search_domain_filter` for reliable financial sources, `search_mode: "sec"` for fundamentals, structured JSON outputs via Pydantic, and anti-hallucination clauses to prevent fabricated data.[^1][^2][^3]

***

## The Core Architecture: System vs. User Prompts

Sonar Pro uses a two-role prompt structure with distinct responsibilities:[^2]

- **System Prompt (`role: "system"`)**: Controls style, tone, output format, persona, and anti-hallucination rules. This does NOT trigger a web search.
- **User Prompt (`role: "user"`)**: Contains the actual query. This IS what kicks off the real-time web search — so it must be written like a high-quality search query.

```python
from perplexity import Perplexity

client = Perplexity()

completion = client.chat.completions.create(
    model="sonar-pro",
    messages=[
        {
            "role": "system",
            "content": "You are a financial research assistant. Return structured JSON only. If data is unavailable, state that explicitly rather than estimating."
        },
        {
            "role": "user",
            "content": "NVDA Nvidia Q1 2026 earnings revenue EPS analyst expectations"
        }
    ]
)
```

A critical rule: **never ask for URLs inside the user prompt**. The language model cannot see the actual URLs from the search. They are automatically returned in the `search_results` field of the API response — parse them from there.[^2]

***

## Use API Parameters, Not Prompt Instructions

The single biggest optimization mistake developers make is trying to control search behavior through prompts (e.g., "only search Reuters and Bloomberg"). The search component ignores those instructions — it processes built-in parameters directly.[^1]

### Key Parameters for Financial Applications

| Parameter | Purpose | Recommended Value for Finance |
|-----------|---------|-------------------------------|
| `search_domain_filter` | Restrict to trusted sources | `["finance.yahoo.com", "reuters.com", "bloomberg.com", "sec.gov", "marketwatch.com"]` |
| `search_context_size` | Control retrieval depth | `"high"` for analysis, `"medium"` for quick news |
| `search_recency_filter` | Control news freshness | `"day"` for live feed, `"week"` for trend analysis |
| `search_mode` | Switch to SEC filings search | `"sec"` for fundamentals/10-K/10-Q/8-K |
| `response_format` | Enforce JSON output | `json_schema` with Pydantic model |

```python
# Stock news aggregator — correct approach
completion = client.chat.completions.create(
    model="sonar-pro",
    messages=[{"role": "user", "content": "TSLA Tesla stock news analyst upgrades downgrades past 48 hours"}],
    search_domain_filter=["reuters.com", "bloomberg.com", "finance.yahoo.com", "marketwatch.com"],
    web_search_options={"search_context_size": "high"},
    search_recency_filter="day"
)
```

***

## SEC Filing Integration (Launched July 2025)

Perplexity added native SEC/EDGAR search, letting you set `search_mode: "sec"` to search directly within 10-K annual reports, 10-Q quarterly filings, and 8-K current event filings. This is a game changer for fundamentals research in a stock finder.[^3][^4]

**Limitations to know:**
- Covers only the **last 1 year** of filings; historical trend data may be limited[^5]
- Best for risk factors, revenue breakdowns, and management guidance — not real-time pricing

```python
# Fundamental research via SEC
completion = client.chat.completions.create(
    model="sonar-pro",
    messages=[{
        "role": "user",
        "content": "AAPL Apple 10-K 2025 revenue segments operating income risk factors"
    }],
    search_mode="sec",
    web_search_options={"search_context_size": "high"}
)
```

***

## Structured JSON Output with Pydantic

For a stock finder app, you need machine-readable, consistent output. Sonar Pro supports `json_schema` structured outputs enforced via Pydantic models. The first request with a new schema incurs a 10-30 second compilation delay — subsequent requests are fast.[^6][^2]

```python
from pydantic import BaseModel
from typing import List, Optional

class StockResult(BaseModel):
    symbol: str
    company_name: str
    current_price: Optional[float] = None
    pe_ratio: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    analyst_rating: Optional[str] = None
    sentiment: str  # Bullish / Bearish / Neutral
    key_highlights: List[str]

class NewsItem(BaseModel):
    headline: str
    impact: str  # High / Medium / Low
    summary: str
    affected_sectors: List[str]

class StockFinderResponse(BaseModel):
    query_topic: str
    market_sentiment: str
    stocks: List[StockResult]
    news_items: List[NewsItem]
    investment_risks: List[str]

completion = client.chat.completions.create(
    model="sonar-pro",
    messages=[{
        "role": "system",
        "content": "You are a financial data extraction assistant. Return only structured JSON."
    }, {
        "role": "user",
        "content": "Identify top 5 semiconductor stocks with strong Q1 2026 earnings momentum"
    }],
    response_format={
        "type": "json_schema",
        "json_schema": {"schema": StockFinderResponse.model_json_schema()}
    },
    search_domain_filter=["reuters.com", "bloomberg.com", "finance.yahoo.com"],
    web_search_options={"search_context_size": "high"}
)

result = StockFinderResponse.model_validate_json(completion.choices.message.content)
```

The `instructor` library from `python.useinstructor.com` also integrates with Perplexity for cleaner Pydantic-enforced structured outputs.[^7]

***

## Prompt Templates by Use Case

### 1. Stock Discovery / Screener

**System Prompt:**
```
You are a quantitative equity research assistant. Return results as structured JSON.
For any data you cannot confirm from search results, set the value to null.
Do not estimate or fabricate financial metrics.
```

**User Prompt (Good):**
```
Identify 5 undervalued S&P 500 healthcare stocks with P/E below 20, 
positive YoY revenue growth Q4 2025, and analyst buy ratings
```

**User Prompt (Avoid):**
```
Tell me about good stocks to buy  ← too vague, scattered search results
```

**Parameters:**
```python
search_domain_filter=["finance.yahoo.com", "marketwatch.com", "reuters.com"]
web_search_options={"search_context_size": "high"}
search_recency_filter="month"
```

***

### 2. Real-Time News Aggregation

**System Prompt:**
```
You are a financial news analyst. For each news item:
- Assign impact: High (direct price catalyst), Medium (sector-wide), Low (background)
- Classify sentiment: Bullish / Bearish / Neutral
- List affected tickers
Do not include URLs in your response — only text summaries.
```

**User Prompt (Good):**
```
Top market-moving news for NVDA Nvidia past 24 hours earnings guidance AI chips
```

**Parameters:**
```python
search_recency_filter="day"
web_search_options={"search_context_size": "medium"}
search_domain_filter=["reuters.com", "bloomberg.com", "cnbc.com", "marketwatch.com"]
```

***

### 3. Sentiment Analysis + Catalysts

**User Prompt:**
```
Analyze investor sentiment for TSLA Tesla stock based on news and analyst reports 
past 2 weeks. Identify 3 bullish catalysts and 3 bearish risks.
```

**Anti-hallucination clause to add in system prompt:**
```
If you cannot find reliable sources for a specific claim, 
state that clearly rather than providing speculative information.
```


***

### 4. SEC Fundamentals Extraction

**User Prompt:**
```
Extract from Apple AAPL latest 10-K annual report: 
total revenue by segment, gross margin, long-term debt, 
key risk factors, and management forward guidance
```

**Parameters:**
```python
search_mode="sec"
web_search_options={"search_context_size": "high"}
```

***

### 5. Comparative Stock Analysis

**User Prompt:**
```
Compare MSFT Microsoft vs GOOGL Alphabet vs META across:
market cap, forward P/E, YTD return 2026, revenue growth Q4 2025,
analyst consensus rating. Format as structured table data.
```

**Critical:** Keep comparisons to a single topic area per query. Avoid: "Compare these 3 stocks AND give me crypto news AND explain Fed policy" — this fragments the search component.[^1]

***

## Anti-Hallucination System

Financial data hallucinations are a known risk with Sonar — the model may fabricate stock prices or earnings numbers when search results are insufficient. Implement all three layers:[^8]

### Layer 1: Fail-Fast Clause (in system prompt)
```
Cite every financial claim from your search results.
If you cannot verify a specific metric, return null for that field.
Never estimate, interpolate, or generate plausible-sounding financial data.
```


### Layer 2: Conditional Query Framing (in user prompt)
```
Based on publicly available sources from the past [timeframe], [your query].
If no recent information is found, indicate that no recent updates were discovered.
```


### Layer 3: Source Verification via API Response
Always parse the `search_results` field from the API response to show source URLs to users — never ask the model to generate URLs. The `search_results` field contains:[^2]
- `title`: Source page title
- `url`: Actual source URL
- `date`: Publication date

```python
# Extract sources from response
sources = response.search_results  # List of {title, url, date}
```

***

## Multi-Query Batching for News Aggregators

For aggregating news across multiple tickers, use the Search API's multi-query feature (up to 5 queries per request) instead of sequential calls:[^9]

```python
from perplexity import AsyncPerplexity
import asyncio

async def batch_stock_news(tickers: list[str]):
    async with AsyncPerplexity() as client:
        tasks = [
            client.search.create(
                query=f"{ticker} stock news earnings catalyst past 48 hours",
                max_results=5
            )
            for ticker in tickers[:5]  # max 5 per request
        ]
        results = await asyncio.gather(*tasks)
    return results
```

For larger watchlists, implement a `SearchManager` with semaphore-based rate limiting to stay within API quotas.[^9]

***

## Caching Strategy

Not all stock queries need real-time search — cache strategically to reduce costs and latency:[^9]

| Data Type | Cache TTL | Notes |
|-----------|-----------|-------|
| Company profile / description | 7 days | Rarely changes |
| Sector overview / macro context | 24 hours | Daily refresh sufficient |
| Analyst ratings & price targets | 6 hours | Update on market hours |
| Live stock news | 15 minutes | Near real-time for feed |
| Intraday price catalysts | No cache | Always live |
| SEC filing data | 90 days | Quarterly cadence |

```python
class SearchCache:
    def __init__(self, ttl_seconds=3600):
        self.cache = {}
        self.ttl = ttl_seconds

    def get(self, query: str):
        if query in self.cache:
            result, timestamp = self.cache[query]
            if time.time() - timestamp < self.ttl:
                return result
        return None
```


***

## Common Pitfalls Summary

| Mistake | Why It Fails | Fix |
|---------|-------------|-----|
| Asking for URLs in prompt | Language model can't see search URLs | Parse `search_results` field instead[^2] |
| "Search only Bloomberg" in prompt | Search component ignores text instructions | Use `search_domain_filter` parameter[^1] |
| "Only show results from last week" in prompt | Recency not enforced via text | Use `search_recency_filter` parameter[^1] |
| Few-shot examples in user prompt | Triggers searches for your examples | Remove examples, use system prompt for format[^1] |
| Multi-topic user prompt | Fragments the search component | One topic per user message[^1] |
| Vague queries ("show me good stocks") | Scattered, low-relevance results | Include ticker symbols, timeframes, specific metrics[^10] |
| No anti-hallucination clause | Model fabricates missing financial data | Add explicit null-return instructions[^8][^10] |
| Not using Pydantic for output | Inconsistent JSON parsing | Use `json_schema` + Pydantic models[^6] |

***

## Recommended Production Stack

For a TypeScript/Python full-stack app (aligned with your SafeAppeals architecture), the recommended integration pattern is:

1. **FastAPI backend** — handle Perplexity API calls, caching, and Pydantic validation
2. **LiteLLM proxy** — already in your stack, routes to Sonar Pro with unified interface
3. **AsyncPerplexity client** — concurrent watchlist queries
4. **Redis/in-memory cache** — TTL-based caching by query type
5. **`search_results` field** — pass source URLs to frontend for citation display
6. **Pydantic models** — enforce typed responses before sending to frontend

This gives you reliable, structured, source-grounded financial data without manual JSON parsing or hallucinated metrics.

---

## References

1. [Prompt Guide](https://docs.perplexity.ai/docs/agent-api/prompt-guide) - Parameter Optimization. Adjust model parameters based on your specific needs: Search Domain Filter: ...

2. [Core Features - Perplexity API Platform](https://docs.perplexity.ai/docs/sonar/features) - This guide covers three core capabilities: streaming responses for real-time experiences, structured...

3. [Changelog - Perplexity API Platform](https://docs.perplexity.ai/docs/resources/changelog) - July 2025. SearchFinancial. New: SEC Filings Filter for Financial ResearchWe're excited to announce ...

4. [Answers for Every Investor - Perplexity](https://www.perplexity.ai/hub/blog/answers-for-every-investor) - Perplexity is providing answers leveraging SEC data for all investors. Our new SEC/EDGAR integration...

5. [Perplexity AI Integrates SEC data : r/ValueInvesting - Reddit](https://www.reddit.com/r/ValueInvesting/comments/1l8sm3j/perplexity_ai_integrates_sec_data/) - Currently, they search only over the past year of filings, so any trends or historical numbers are l...

6. [Output Control](https://docs.perplexity.ai/docs/agent-api/output-control) - Streaming and structured outputs for the Agent API. ... from perplexity import Perplexity from typin...

7. [Structured Outputs with Perplexity AI and Pydantic - Instructor](https://python.useinstructor.com/integrations/perplexity/) - This guide demonstrates how to use Perplexity AI with Instructor to generate structured outputs. You...

8. [Financial Data Hallucinations - Perplexity API Platform Forum](https://community.perplexity.ai/t/financial-data-hallucinations/145) - The Perplexity API on the sonar-reasoning-pro model is hallucinating the price of stock price. Retur...

9. [Best Practices - Perplexity](https://docs.perplexity.ai/docs/search/best-practices) - Overview. This guide covers essential best practices for getting the most out of Perplexity's Search...

10. [Perplexity AI prompt engineering: techniques for more accurate ...](https://www.datastudios.org/post/perplexity-ai-prompt-engineering-techniques-for-more-accurate-responses-in-2025) - This September 2025 update explores the latest prompt-engineering strategies, accuracy-improving tec...

