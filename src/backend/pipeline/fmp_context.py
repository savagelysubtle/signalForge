"""FMP data formatting helpers for downstream pipeline stages.

Formats ``FmpEnrichedStock`` data into concise text blocks for injection
into Gemini, Claude, and GPT prompts. Each formatter includes only the
fields most relevant to that stage's task.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.fmp_service import FmpEnrichedStock


def format_fmp_for_gemini(stock: FmpEnrichedStock) -> str:
    """Format FMP data relevant to sentiment analysis.

    Includes company identity, upcoming earnings, insider activity,
    and analyst consensus — signals that help Gemini assess the
    significance of news catalysts.

    Args:
        stock: Enriched stock data from FMP pre-screening.

    Returns:
        Multi-line text block for prompt injection.
    """
    parts = [f"Company: {stock.company_name} ({stock.symbol})"]
    if stock.sector:
        parts.append(f"Sector: {stock.sector}")
    if stock.market_cap:
        parts.append(f"Market cap: ${stock.market_cap:,.0f}")
    if stock.earnings_date:
        parts.append(f"Upcoming earnings: {stock.earnings_date}")
    if stock.insider_net_buys is not None:
        direction = "NET BUYING" if stock.insider_net_buys > 0 else "NET SELLING"
        parts.append(f"Insider activity: {direction} ({stock.insider_net_buys:+d} transactions)")
    if stock.analyst_consensus:
        parts.append(f"Analyst consensus: {stock.analyst_consensus}")
    if stock.analyst_target_upside is not None:
        parts.append(f"Price target upside: {stock.analyst_target_upside:+.1f}%")
    return "\n".join(parts)


def format_fmp_for_claude(stock: FmpEnrichedStock) -> str:
    """Format FMP data relevant to chart analysis context.

    Includes earnings dates, insider activity, quality scores, and
    momentum signals that help Claude contextualise technical patterns.

    Args:
        stock: Enriched stock data from FMP pre-screening.

    Returns:
        Multi-line text block for prompt injection.
    """
    parts = [f"Company: {stock.company_name} ({stock.symbol})"]
    if stock.sector:
        parts.append(f"Sector: {stock.sector}")
    if stock.earnings_date:
        parts.append(f"UPCOMING EARNINGS: {stock.earnings_date} — expect increased volatility")
    if stock.insider_net_buys is not None and stock.insider_net_buys > 0:
        parts.append(
            f"Insider buying: {stock.insider_net_buys:+d} net transactions (bullish signal)"
        )
    if stock.piotroski_score is not None:
        if stock.piotroski_score >= 7:
            quality = "strong"
        elif stock.piotroski_score >= 5:
            quality = "moderate"
        else:
            quality = "weak"
        parts.append(f"Piotroski score: {stock.piotroski_score}/9 ({quality} fundamentals)")
    if stock.analyst_target_upside is not None:
        parts.append(f"Analyst target upside: {stock.analyst_target_upside:+.1f}%")
    if stock.relative_volume is not None:
        parts.append(f"Relative volume: {stock.relative_volume:.1f}x average")
    if stock.composite_score is not None:
        parts.append(f"Composite quality score: {stock.composite_score:.0f}/100")
    return "\n".join(parts)


def format_fmp_for_gpt(
    fmp_context: dict[str, FmpEnrichedStock],
    tickers: list[str],
) -> str:
    """Format structured FMP data for GPT bull/bear/judge prompts.

    Includes the full quantitative profile: composite scores with
    dimension breakdown, insider activity, analyst targets, momentum,
    quality metrics, and earnings data.

    Args:
        fmp_context: Map of ticker symbol -> enriched stock.
        tickers: Ordered list of tickers to format.

    Returns:
        Multi-line text block with per-ticker sections.
    """
    if not fmp_context:
        return "No FMP pre-screening data available."

    parts: list[str] = []
    for ticker in tickers:
        stock = fmp_context.get(ticker)
        if not stock:
            parts.append(f"\n### {ticker}\nNo FMP data available.")
            continue

        lines = [f"\n### {stock.symbol} — {stock.company_name}"]
        if stock.composite_score is not None:
            f_score = stock.score_fundamental or 0
            m_score = stock.score_momentum or 0
            s_score = stock.score_sentiment or 0
            q_score = stock.score_quality or 0
            lines.append(
                f"Composite Score: {stock.composite_score:.0f}/100 "
                f"(F:{f_score:.0f} M:{m_score:.0f} S:{s_score:.0f} Q:{q_score:.0f})"
            )
        if stock.sector:
            lines.append(f"Sector: {stock.sector}")
        if stock.pe_ratio is not None:
            lines.append(f"P/E: {stock.pe_ratio:.1f}")
        if stock.roe is not None:
            lines.append(f"ROE: {stock.roe:.1f}%")
        if stock.piotroski_score is not None:
            lines.append(f"Piotroski: {stock.piotroski_score}/9")
        if stock.altman_z_score is not None:
            lines.append(f"Altman Z: {stock.altman_z_score:.2f}")
        if stock.insider_net_buys is not None:
            direction = "NET BUYING" if stock.insider_net_buys > 0 else "NET SELLING"
            lines.append(f"Insider: {direction} ({stock.insider_net_buys:+d})")
        if stock.analyst_consensus:
            consensus_parts = [f"Analyst: {stock.analyst_consensus}"]
            if stock.analyst_target_upside is not None:
                consensus_parts.append(f"target upside {stock.analyst_target_upside:+.1f}%")
            lines.append(", ".join(consensus_parts))
        if stock.relative_volume is not None:
            lines.append(f"RVOL: {stock.relative_volume:.1f}x")
        momentum_parts: list[str] = []
        if stock.price_change_1d is not None:
            momentum_parts.append(f"1D:{stock.price_change_1d:+.1f}%")
        if stock.price_change_1m is not None:
            momentum_parts.append(f"1M:{stock.price_change_1m:+.1f}%")
        if stock.price_change_3m is not None:
            momentum_parts.append(f"3M:{stock.price_change_3m:+.1f}%")
        if momentum_parts:
            lines.append(f"Price momentum: {' '.join(momentum_parts)}")
        if stock.earnings_date:
            earn_line = f"Earnings: {stock.earnings_date}"
            if stock.earnings_beat_rate is not None:
                earn_line += f" (beat rate: {stock.earnings_beat_rate:.0f}%)"
            lines.append(earn_line)

        parts.append("\n".join(lines))

    return "\n".join(parts)
