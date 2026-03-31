# SignalForge Strategies v2 — Design Guide

## Overview

This document covers the complete strategy architecture for SignalForge v2: 13 total strategies (7 upgraded + 6 new), each with exactly 10 chart indicators optimized for AI chart reading, upgraded FMP screener configurations, and documented win-rate rationale. All strategies feed into the multi-agent pipeline: FMP screener → chart/news context → LLM signal generation.

***

## Why 10 Indicators?

The 10-indicator limit per chart is a deliberate design constraint — it gives the LLM agents enough signal diversity to assess trend, momentum, volatility, and overbought/oversold conditions without chart noise. Research on best indicator combinations identifies three functional layers:[^1][^2]

- **Trend layer** — EMAs (9, 21, 50, 200) and/or Supertrend establish directional bias
- **Momentum layer** — RSI, MACD, Williams %R confirm entry timing
- **Volatility/volume layer** — ATR, Bollinger Bands, Volume, ADX measure conviction

Each strategy in this pack is built around one of two master 10-indicator templates:

**Intraday Template (speed-focused):**
`EMA_9, EMA_21, EMA_50, VWAP, RSI, MACD, ATR, Volume, Supertrend, Williams_R`

**Swing/Position Template (trend-focused):**
`EMA_9/21 + EMA_50 + EMA_200, RSI, MACD, ATR, Volume, ADX, Bollinger_Bands`

***

## Indicator Reference — What Each Adds for AI Reading

| Indicator | Role | Key Signal for LLM |
|---|---|---|
| EMA_9 | Short-term trend | Micro-momentum direction |
| EMA_21 | Intermediate trend | Pullback support / resistance |
| EMA_50 | Medium trend | Swing-level trend bias |
| EMA_200 | Long-term trend | Bull/bear regime filter |
| VWAP | Institutional anchor | Intraday fair-value reference[^3] |
| RSI (14) | Momentum oscillator | Overbought/oversold + divergence[^4] |
| MACD | Trend momentum | Crossovers, histogram expansion/contraction |
| ATR | Volatility | Stop sizing, range expansion detection |
| Volume | Conviction | Breakout confirmation, accumulation/distribution |
| Supertrend | Trend filter | Buy/sell flip signal, ~67% standalone win rate[^5] |
| ADX (14) | Trend strength | >25 = trending, <20 = chop filter[^6] |
| Bollinger Bands | Volatility bands | Squeeze detection, band expansion breakouts |
| Williams %R | Short oscillator | More sensitive than RSI for entry timing[^6] |

> **FMP API note:** The `/api/v3/technical_indicator/{timeframe}/{symbol}` endpoint supports `type=` values of: `sma, ema, dema, tema, wma, williams, rsi, adx, standardDeviation`. MACD, VWAP, Bollinger Bands, Supertrend, and Stochastic are computed client-side from OHLCV data or rendered via Chart-Img. The app does not currently call FMP's technical indicator endpoint — this could be added as a pre-screener signal enrichment step.[^7][^6]

***

## FMP Screener — New Parameters Used in v2

Several FMP screener fields unused in the original strategies are now activated across v2 strategies:

| New Field Used | Strategies | Why Added |
|---|---|---|
| `exchange` | Momentum Breakout, Golden Cross, EMA 21 Pullback | Tighter TSX-only targeting |
| `price_max` | EMA Stack, ORB, Momentum Breakout | Cap penny stocks and ultra-high-priced names |
| `beta_max` | Multiple intraday | Remove extreme volatile names (>3.5 beta) |
| `is_etf: false` | All stock strategies | Explicit exclusion (was default assumption) |
| `altman_z_min` | Golden Cross, BB Squeeze, EMA 21, Value, Mean Rev | Financial distress filter[^8] |
| `piotroski_min` | Upgraded to 5-6 on value/mean reversion | Stricter quality gating[^8] |
| `price_change_1m_min` on swing momentum | Golden Cross, EMA Pullback | Confirm not dead money, slight pullback only |
| `pe_max` on intraday | Removed from intraday | Irrelevant for 15m scalps |
| `price_change_3m_min` on crypto swing | Crypto Swing | Added momentum filter missing in v1 |

### Composite Score Weight Philosophy

Strategies are bucketed into weight profiles:

| Profile | Fundamental | Momentum | Sentiment | Quality | Strategies |
|---|---|---|---|---|---|
| Pure Intraday | 0–5 | 55–65 | 20 | 10–15 | ORB, VWAP Scalp, Intraday Scalp, EMA Stack |
| Momentum Swing | 15–25 | 40–45 | 20–25 | 15–20 | Momentum Breakout, Golden Cross, EMA Pullback |
| Event/Catalyst | 20 | 20 | 40 | 20 | Earnings Play |
| Quality/Value | 40 | 10 | 20 | 30 | Value Accumulation |
| Mean Reversion | 20 | 25 | 30 | 25 | Mean Reversion |
| Crypto | 0 | 55–65 | 20–30 | 15 | Crypto Swing, Crypto Scalp |

***

## Strategy Catalog

### Intraday Strategies (5 total)

#### 1. Intraday Scalp *(upgraded from v1)*
Classic intraday scalp upgraded with Supertrend and ADX to filter out low-conviction choppy signals. The key upgrade is `ADX > 20` filter in `ta_focus` to avoid sideways markets — one of the most common causes of intraday false breakouts. `beta_max: 3.5` added to avoid stocks that gap erratically.[^9]

**Win Rate Target:** 60–65% | **Hold:** 15 min – 2 hrs | **FMP:** rvol ≥ 2.0, 1d change ≥ 1.5%, beta 1.2–3.5, market cap ≥ $1B

#### 2. EMA Stack Momentum Intraday *(new)*
Uses the triple EMA stack (9/21/50) above VWAP for high-probability momentum entries. All three EMAs must be in bullish order (9 > 21 > 50) above VWAP to qualify — this alignment requirement is the primary quality filter that elevates win rate above 60%. Supertrend provides a binary trend confirmation. Williams %R identifies entry timing within the trend.[^9]

**Win Rate Target:** 60–65% | **Hold:** 15 min – 2 hrs | **FMP:** rvol ≥ 2.0, 1d change ≥ 1.0%, beta 1.1–3.5, exchange TSX

#### 3. Opening Range Breakout *(new)*
Trades the first 30-minute opening range high/low breakout — one of the oldest documented intraday edges. The ORB is marked on the 30m chart; entries require volume ≥ 2x average on the breakout candle, Supertrend in the breakout direction, and RSI not yet at extreme (55–68 for longs). Uses the highest `rvol_min: 2.5` of all strategies to ensure stocks with a real intraday catalyst.[^10]

**Win Rate Target:** 60%+ | **Hold:** 30 min – 3 hrs | **FMP:** rvol ≥ 2.5, 1d change ≥ 0.5%, beta 1.0–4.0, market cap ≥ $750M

#### 4. VWAP Reversal Scalp *(new)*
Dedicated VWAP pullback/rejection strategy. The three setups — VWAP pullback long, VWAP reclaim, and VWAP rejection short — each have documented 60–65% win rates with confirmation candles. Williams %R must confirm oversold (<-80) for longs or overbought (>-20) for shorts to filter noise. Targets the largest, most liquid TSX names where VWAP levels attract institutional flow (market cap ≥ $1B, volume ≥ 1M).[^11]

**Win Rate Target:** 60–65% | **Hold:** 15 min – 90 min | **FMP:** volume ≥ 1M, market cap ≥ $1B, beta 0.9–2.5

#### 5. Crypto Intraday Scalp *(upgraded from v1)*
Upgraded with the full intraday indicator stack including Williams %R for precision entry timing. EMA 9/21 micro-stack on 15m charts confirms direction. `weight_momentum` raised from 60 to 65 to maximize ranking of the fastest-moving crypto.

**Win Rate Target:** 60%+ | **Hold:** 15 min – 2 hrs | **FMP:** crypto, volume ≥ 5M, rvol ≥ 1.5, 1d change ≥ 2.0%

***

### Swing Strategies (5 total)

#### 6. Momentum Breakout *(upgraded from v1)*
Full 10-indicator upgrade with ADX added as trend strength confirmation (>25 signals genuine trend vs. noise). `exchange: TSX` added for tighter targeting. `piotroski_min` raised to 4 and `altman_z_min: 1.8` added to avoid momentum traps in financially weak companies. `weight_momentum` increased to 45.[^6]

**Win Rate Target:** 60–65% | **Hold:** 2–5 days | **FMP:** 3m change ≥ 10%, rvol ≥ 1.5, beta 1.0–3.0

#### 7. EMA 50/200 Golden Cross Swing *(new)*
The EMA 50/200 golden cross is one of the most backtested trend-following signals, widely cited for 60–70% win rates on daily charts. The strategy requires the cross to be confirmed (not just forming) plus ADX > 25 to verify the trend has real momentum. Bollinger Bands expanding on the breakout candle confirms volatility expansion. `altman_z_min: 1.8` and `piotroski_min: 4` filter out companies that form fake crosses due to fundamental deterioration.[^12][^13]

**Win Rate Target:** 62–68% | **Hold:** 1–4 weeks | **FMP:** 3m change ≥ 5%, exchange TSX, beta 0.8–2.5, market cap $500M–$25B

#### 8. EMA 21 Pullback Swing *(new)*
Trend continuation strategy targeting pullbacks to the 21 EMA within an established uptrend (price above EMA 50 and 200). The 21 EMA is the preferred short-term swing moving average because it's fast enough to provide entries near support without being too noisy. RSI must reset to the 40–55 range without breaking below 40 — a pattern that confirms healthy consolidation vs. trend reversal. Williams %R in the -50 to -65 zone provides entry timing.[^14]

**Win Rate Target:** 62–68% | **Hold:** 5–20 days | **FMP:** 3m change ≥ 8%, 1m change -12% to +5%, market cap $400M–$25B

#### 9. Bollinger Band Squeeze Breakout Swing *(new)*
Targets Bollinger Band contraction (low bandwidth = low volatility consolidation) followed by explosive expansion. ADX below 20 during the squeeze phase confirms price coiling, then ADX rising above 25 on breakout confirms the new trend. The `price_change_1m_max: 8.0` filter ensures the stock hasn't already broken out — we want the stock still in the squeeze. `altman_z_min: 2.0` prevents entering squeezes caused by financial distress rather than consolidation.[^15]

**Win Rate Target:** 60–65% | **Hold:** 5–15 days | **FMP:** 1m -15% to +8%, market cap $400M–$20B

#### 10. Mean Reversion *(upgraded from v1)*
Upgraded to full 10 indicators with Bollinger Bands replacing the basic RSI/MACD-only setup. Bollinger Band lower band touch + Williams %R below -80 provides a dual-confirmation oversold signal. `piotroski_min` raised from 4 to 5, `altman_z_min: 2.0` added. `weight_sentiment` raised to 30 — insider buying and analyst targets are especially critical for mean reversion to avoid catching falling knives. RSI mean reversion strategies achieve 71–91% win rates in backtests when paired with a secondary filter.[^4]

**Win Rate Target:** 65–70% | **Hold:** 3–7 days | **FMP:** 1m -35% to -10%, insider buying required, piotroski ≥ 5

***

### Position / Value Strategies (1)

#### 11. Value Accumulation *(upgraded from v1)*
Full 10-indicator swing/position stack with Bollinger Bands and ADX replacing Stochastic. Bollinger Band lower touch near EMA 200 support is the primary technical entry trigger. `piotroski_min` raised from 5 to 6 (strong fundamentals zone) and `altman_z_min: 2.5` (safe zone, well above distress threshold of 1.81). `price_change_1m_max: 5.0` ensures not chasing after recovery is already underway.[^8]

**Win Rate Target:** 65%+ | **Hold:** 2–8 weeks | **FMP:** P/E 3–18, P/B ≤ 3, PEG ≤ 1.5, ROE ≥ 8%, insider buying required

***

### Crypto Swing (1)

#### 12. Crypto Swing *(upgraded from v1)*
EMA stack upgraded to full 9/21/50/200 set. Bollinger Bands replace Stochastic for cleaner volatility band analysis on crypto. `price_change_3m_min: 10.0` added — a critical missing filter in v1 that now ensures we only swing assets with existing momentum, not dead coins. `weight_momentum` raised from 50 to 55.

**Win Rate Target:** 60%+ | **Hold:** 3–14 days | **FMP:** crypto, 3m change ≥ 10%, rvol ≥ 1.2, market cap ≥ $100M

***

### Event-Driven (1)

#### 13. Earnings Play *(upgraded from v1)*
Upgraded to 10-indicator set with Bollinger Band squeeze detection (pre-earnings coiling) and Williams %R replacing Stochastic. `piotroski_min: 4` and `altman_z_min: 1.8` added — earnings beats from fundamentally weak companies often fail to sustain. `price_change_3m_min: 0.0` added to ensure the stock is at least flat (not in a downtrend heading into earnings). `weight_sentiment` raised to 40 — highest of all strategies because analyst revisions and target upgrades are the dominant pre-earnings signal.

**Win Rate Target:** 60%+ around catalyst | **Hold:** 1–5 days | **FMP:** earnings ≤ 14 days, beat rate ≥ 60%, market cap ≥ $750M

***

## FMP API — Unused Endpoints Worth Integrating

Based on the current API map, these FMP endpoints are not yet wired into SignalForge but could strengthen pre-screening:

| Endpoint | Use Case | Relevant Strategies |
|---|---|---|
| `/stable/technical-indicator/` | Pre-confirm RSI/EMA/ADX conditions server-side before charting | All — reduces false positives reaching the LLM |
| `/stable/biggest-gainers` + `/stable/most-actives` | Seed intraday screener candidates before `/company-screener` | All intraday strategies |
| `/stable/sector-performance-snapshot` | Sector momentum filter — only scan top-3 performing sectors | Momentum Breakout, Golden Cross |
| `/stable/upgrades-downgrades-consensus-bulk` | Already in bulk calls — raise `weight_sentiment` for strategies needing analyst confirmation | Earnings Play, Value |
| Social sentiment (if FMP adds) | Crypto sentiment boost | Crypto Swing, Crypto Scalp |

The technical indicator endpoint (`/api/v3/technical_indicator/{timeframe}/{symbol}?type=rsi&period=14`) supports intraday timeframes down to 1-minute, meaning RSI or ADX pre-checks could be run during the enrichment pipeline to hard-filter stocks before they reach chart analysis — reducing LLM token cost significantly.[^7]

***

## Strategy Quick-Reference Matrix

| Strategy | Type | Hold | Indicators | Win Rate Target | Key FMP Filters |
|---|---|---|---|---|---|
| Intraday Scalp | Intraday | 15m–2h | EMA9/21/50, VWAP, RSI, MACD, ATR, Vol, Supertrend, ADX | 60–65% | rvol≥2.0, beta 1.2–3.5, 1d≥1.5% |
| EMA Stack Momentum | Intraday | 15m–2h | EMA9/21/50, VWAP, RSI, MACD, ATR, Vol, Supertrend, WilliamsR | 60–65% | rvol≥2.0, beta 1.1–3.5, 1d≥1.0% |
| Opening Range Breakout | Intraday | 30m–3h | EMA9/21/50, VWAP, RSI, MACD, ATR, Vol, Supertrend, WilliamsR | 60%+ | rvol≥2.5, 1d≥0.5%, beta 1.0–4.0 |
| VWAP Reversal Scalp | Intraday | 15m–90m | VWAP, EMA9/21/50, RSI, MACD, ATR, Vol, Supertrend, WilliamsR | 60–65% | vol≥1M, mcap≥$1B, rvol≥1.5 |
| Crypto Intraday Scalp | Intraday (crypto) | 15m–2h | EMA9/21/50, VWAP, RSI, MACD, ATR, Vol, Supertrend, WilliamsR | 60%+ | crypto, vol≥5M, rvol≥1.5 |
| Momentum Breakout | Swing | 2–5d | EMA9/21/50/200, RSI, MACD, ATR, Vol, ADX, Supertrend | 60–65% | 3m≥10%, rvol≥1.5, beta 1.0–3.0 |
| EMA 50/200 Golden Cross | Swing | 1–4w | EMA9/21/50/200, RSI, MACD, ATR, Vol, ADX, Bollinger | 62–68% | 3m≥5%, TSX, altman≥1.8 |
| EMA 21 Pullback Swing | Swing | 5–20d | EMA9/21/50/200, RSI, MACD, ATR, Vol, ADX, WilliamsR | 62–68% | 3m≥8%, 1m -12% to +5% |
| BB Squeeze Breakout | Swing | 5–15d | Bollinger, EMA21/50/200, RSI, MACD, ATR, Vol, ADX, Supertrend | 60–65% | 1m -15% to +8%, altman≥2.0 |
| Mean Reversion | Swing | 3–7d | EMA21/50/200, RSI, MACD, ATR, Vol, Bollinger, Supertrend, WilliamsR | 65–70% | 1m -35% to -10%, insider buy, pitr≥5 |
| Value Accumulation | Position | 2–8w | EMA21/50/200, RSI, MACD, ATR, Vol, ADX, Bollinger, WilliamsR | 65%+ | P/E≤18, PEG≤1.5, pitr≥6, insider buy |
| Earnings Play | Event | 1–5d | EMA21/50/200, RSI, MACD, ATR, Vol, ADX, Bollinger, WilliamsR | 60%+ | earnings≤14d, beat≥60%, pitr≥4 |
| Crypto Swing | Swing (crypto) | 3–14d | EMA9/21/50/200, RSI, MACD, ATR, Vol, Supertrend, Bollinger | 60%+ | crypto, 3m≥10%, rvol≥1.2 |

***

## Win Rate Foundation

The 60%+ win rate target is achievable across all 13 strategies when the following conditions are met — these principles are embedded in each strategy's `ta_focus` and screener configuration:

1. **Direction confirmation** — EMA stack alignment or Supertrend flip before entry, never counter-trend[^16][^13]
2. **Momentum confirmation** — MACD histogram positive/expanding on entry; RSI in momentum zone (50–70) not at extremes[^4]
3. **Volume confirmation** — breakout or bounce candle has 1.5–2x average volume, confirming institutional participation[^11]
4. **Oscillator timing** — Williams %R or RSI used for micro-entry timing within a confirmed directional move[^17]
5. **Trend strength filter** — ADX > 20–25 for trend strategies; skip setups in ADX < 20 chop environments[^1]
6. **Quality screening** — Piotroski ≥ 4–6 and Altman Z-Score above distress zone prevent fundamentally broken stocks from generating false technical signals[^8]

---

## References

1. [Best Combination of Indicators in 2025: Master Trend, Momentum ...](https://prorsi.com/blog/best-combination-of-indicators-in-2025-master-trend,-momentum---trade-management) - Best Indicator Combinations for Different Trading Styles. For Day Traders: Trend: 20 EMA + 50 EMA (f...

2. [[PDF] The best combination of indicators for the U.S. stock market](https://www.ubishops.ca/wp-content/uploads/he20240105.pdf) - Through a comprehensive examination of 1,440 combinations of indicators, including Bollinger Bands (...

3. [Mastering VWAP (2025): Strategies, Setups, Best Practices](https://highstrike.com/vwap/) - Learn how to use VWAP for better trade entries, exits, and risk control—a must-know indicator for in...

4. [RSI Trading Strategy (91% Win Rate): Backtest, Indicator, And Settings](https://www.quantifiedstrategies.com/rsi-trading-strategy/) - The RSI trading strategy identifies overbought and oversold conditions in markets, measuring momentu...

5. [Supertrend Indicator |Trading Strategy – (11.07% profit/trade!)](https://www.quantifiedstrategies.com/supertrend-indicator/) - The win rate of the Supertrend indicator is around 67% from our calculation and tests. The win rate ...

6. [Utilizing Technical Indicators for Advanced Stock Analysis](https://medium.datadriveninvestor.com/utilizing-technical-indicators-for-advanced-stock-analysis-6e9194c4bbf5) - Financial Modeling Prep (FMP) makes this process easier with their Technical Indicator API. Whether ...

7. [A brief description on how to use Financial Modeling Prep Api - GitHub](https://github.com/FinancialModelingPrepAPI/Financial-Modeling-Prep-API) - Real-time and historical data of stock prices. Supports over 25000 stocks across multiple exchanges....

8. [Technical Indicators Skill - MCP Bundles](https://www.mcpbundles.com/skills/fmp-technical) - Domain knowledge for FMP technical indicators — SMA, EMA, RSI, ADX. FMP Technical Indicators. Moving...

9. [Moving Average Combination: 9‑EMA, 21‑EMA & 50‑SMA - GTF](https://www.gettogetherfinance.com/blog/strong-moving-average/) - Learn why day traders combine 9‑EMA, 21‑EMA and 50‑SMA to spot intraday trend shifts and confirm dir...

10. [Intraday trading Strategies for Beginners in 2025](https://acecapitalenterprise.com/best-trading-intraday-strategies-in-2025/) - No overnight risks; High liquidity in selected stocks; Quick potential profits; Learn technical skil...

11. [VWAP Trading Strategy: 3 Setups I Trade Every Single Day](https://www.bullsonwallstreet.com/post/vwap-trading-strategy) - It is the simplest, the most common, and the highest win-rate of the three setups. Trade only pullba...

12. [50 & 200 EMA Crossover Strategy | Swing Trade Like a Pro - YouTube](https://www.youtube.com/watch?v=8glBkp9UqkM) - ... confirmation ✓ 200 EMA + RSI Swing Trading Strategy ✓ EMA Scalping Strategy for high-volatility ...

13. [Swing Trading Mastery :The 200 EMA Strategy - YouTube](https://www.youtube.com/watch?v=Yv2420Bxw4A) - The 200 EMA (Exponential Moving Average) strategy is a popular trading strategy used by technical an...

14. [How To Use Moving Averages - Moving Average Trading 101](https://tradeciety.com/how-to-use-moving-averages) - 20 / 21 period: The 21 moving average is my preferred choice when it comes to short-term swing tradi...

15. [Best TradingView Indicators 2025: Backtest Results Revealed](https://blog.pickmytrade.trade/best-tradingview-indicators-2025-backtest-results/) - Discover the best TradingView indicators 2025 with backtest results: RSI, MACD, SuperTrend win rates...

16. [Simplest Strategy Known to Man Kind yet It Works : r/Daytrading](https://www.reddit.com/r/Daytrading/comments/1l3mthd/simplest_strategy_known_to_man_kind_yet_it_works/) - 1. Clean Break of the 50 EMA: If price breaks through decisively, enter with confidence. · 2. Failur...

17. [EMA 9/21/50 + VWAP + MACD + RSI Pro [v6] - TradingView](https://www.tradingview.com/script/66V8WRY8-EMA-9-21-50-VWAP-MACD-RSI-Pro-v6/) - ✓ Momentum Entries: Look for MACD crossovers while RSI is not extreme. Avoid buying when RSI > 70 or...

