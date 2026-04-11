"""GPT debate and synthesis stage.

Stage 4: Processes all tickers in batch through a bull/bear/judge debate
(or single synthesis call when debate is disabled). Bull runs first, then bear
(with bull arguments injected so bear can challenge specific points); the judge
runs after both complete.

Uses the ``openai`` SDK with ``AsyncOpenAI`` for async API calls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel

from ml.schemas import GateResult
from pipeline.http_retry import with_transient_retry
from pipeline.model_config import GPT_MODEL
from pipeline.prompts.gpt_debate import (
    BEAR_SYSTEM_PROMPT,
    BULL_SYSTEM_PROMPT,
    JUDGE_SYSTEM_PROMPT,
    build_bear_prompt,
    build_bull_prompt,
    build_judge_prompt,
    get_bear_hash,
    get_bull_hash,
    get_judge_hash,
)
from pipeline.schemas import (
    ChartAnalysis,
    DebateCase,
    DebateCaseList,
    GptJudgeRecommendationList,
    MultiTimeframeTechnical,
    Recommendation,
    RiskAssessment,
    ScreeningResult,
    SentimentAnalysis,
    StrategyConfig,
)
from pipeline.token_budget import enforce_token_budget
from pipeline.validation import with_validation_retry
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(3)
_GPT_REASONING_EFFORT = "high"
_GPT_MAX_COMPLETION_TOKENS = 16_384


def _openai_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Build a fully inlined OpenAI strict JSON schema for structured outputs."""
    raw = model.model_json_schema()
    defs: dict[str, Any] = raw.pop("$defs", {})

    def _resolve(node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            ref_name = node["$ref"].rsplit("/", 1)[-1]
            if ref_name in defs:
                return _resolve(dict(defs[ref_name]))
            return node

        out: dict[str, Any] = {}
        for key, val in node.items():
            if key in ("title", "default", "$defs"):
                continue
            if key == "properties" and isinstance(val, dict):
                out["properties"] = {k: _resolve(v) for k, v in val.items()}
            elif key == "items" and isinstance(val, dict):
                out[key] = _resolve(val)
            elif key in ("allOf", "anyOf", "oneOf") and isinstance(val, list):
                out[key] = [_resolve(v) if isinstance(v, dict) else v for v in val]
            else:
                out[key] = val

        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
            if "properties" in out:
                out["required"] = sorted(out["properties"].keys())

        return out

    return _resolve(raw)


_DEBATE_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "DebateCaseList",
        "strict": True,
        "schema": _openai_strict_schema(DebateCaseList),
    },
}

_RECOMMENDATION_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "GptJudgeRecommendationList",
        "strict": True,
        "schema": _openai_strict_schema(GptJudgeRecommendationList),
    },
}


def _get_client() -> AsyncOpenAI:
    """Build an async OpenAI client using the configured API key."""
    api_key = get_api_key("openai")
    if not api_key:
        raise RuntimeError(
            "OpenAI API key not configured. Set OPENAI_API_KEY in .env (see .env.example)."
        )
    return AsyncOpenAI(api_key=api_key, timeout=300.0)


@with_validation_retry(schema=DebateCaseList, max_retries=2, provider="openai")
async def _call_gpt_bull(
    system_prompt: str,
    user_prompt: str,
    *,
    error_context: str = "",
) -> str:
    """Make a GPT call for the bull case.

    Args:
        system_prompt: Bull analyst system instruction.
        user_prompt: All upstream data formatted for bull analysis.
        error_context: Appended on retries for self-correction.

    Returns:
        Raw response text from the API.
    """
    return await _call_gpt(
        system_prompt,
        user_prompt,
        error_context=error_context,
        response_format=_DEBATE_RESPONSE_FORMAT,
    )


@with_validation_retry(schema=DebateCaseList, max_retries=2, provider="openai")
async def _call_gpt_bear(
    system_prompt: str,
    user_prompt: str,
    *,
    error_context: str = "",
) -> str:
    """Make a GPT call for the bear case.

    Args:
        system_prompt: Bear analyst system instruction.
        user_prompt: All upstream data formatted for bear analysis.
        error_context: Appended on retries for self-correction.

    Returns:
        Raw response text from the API.
    """
    return await _call_gpt(
        system_prompt,
        user_prompt,
        error_context=error_context,
        response_format=_DEBATE_RESPONSE_FORMAT,
    )


@with_validation_retry(schema=GptJudgeRecommendationList, max_retries=2, provider="openai")
async def _call_gpt_judge(
    system_prompt: str,
    user_prompt: str,
    *,
    error_context: str = "",
) -> str:
    """Make a GPT call for the judge synthesis.

    Args:
        system_prompt: Judge system instruction.
        user_prompt: All data including debate cases formatted for judgment.
        error_context: Appended on retries for self-correction.

    Returns:
        Raw response text from the API.
    """
    return await _call_gpt(
        system_prompt,
        user_prompt,
        error_context=error_context,
        response_format=_RECOMMENDATION_RESPONSE_FORMAT,
    )


@with_transient_retry(max_retries=3)
async def _call_gpt(
    system_prompt: str,
    user_prompt: str,
    *,
    error_context: str = "",
    response_format: dict[str, Any] | None = None,
) -> str:
    """Make a single GPT API call.

    Args:
        system_prompt: System instruction for the role.
        user_prompt: User message with all data.
        error_context: Appended on retries for self-correction.
        response_format: Optional strict JSON schema for structured outputs.

    Returns:
        Raw response text from the API.
    """
    client = _get_client()

    full_user_prompt = user_prompt
    if error_context:
        full_user_prompt = f"{user_prompt}\n\n---\nCORRECTION: {error_context}"

    api_kwargs: dict[str, Any] = {
        "model": GPT_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_user_prompt},
        ],
        "reasoning_effort": _GPT_REASONING_EFFORT,
        "max_completion_tokens": _GPT_MAX_COMPLETION_TOKENS,
    }
    if response_format:
        api_kwargs["response_format"] = response_format

    async with _semaphore:
        response = await client.chat.completions.create(**api_kwargs)

    return response.choices[0].message.content or ""


async def run_debate(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
    reflection_context: str,
    run_id: str,
    ta_snapshots: list[MultiTimeframeTechnical] | None = None,
    risk_assessments: list[RiskAssessment] | None = None,
    fmp_context: dict | None = None,
    regime_context: str = "",
    sector_consensus: str = "",
    live_quotes: dict | None = None,
    track_conflicts: str = "",
    force_ml_debate: bool = False,
    pre_gpt_ml: dict[str, GateResult] | None = None,
    ml_escalation: bool = False,
) -> tuple[list[Recommendation], list[dict]]:
    """Run the GPT debate/synthesis with track-aware conflict resolution.

    Uses system prompts that frame inputs as three independent tracks
    (A: Perplexity fundamentals, B: Gemini sentiment, C: Claude technicals).
    Bull argues the most optimistic cross-track reading, Bear argues the most
    pessimistic, and the Judge must explicitly address track disagreements.

    Also passes raw numerical TA data so GPT can verify Claude's interpretation,
    and deterministic risk assessments so GPT can factor structural risk into
    its NO_TRADE/WATCH decisions.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (may be None).
        charts: List of ChartAnalysis from Claude (may be empty).
        sentiments: List of SentimentAnalysis from Gemini (may be empty).
        config: Strategy configuration with risk params and debate toggle.
        reflection_context: Historical performance injection prompt.
        run_id: Pipeline run UUID for metadata tracking.
        ta_snapshots: Numerical TA data from Phase 1 (may be None).
        risk_assessments: Deterministic risk flags per ticker (may be None).
        fmp_context: FMP enriched stock data keyed by ticker (may be None).
        regime_context: Pre-formatted market regime header, or empty.
        sector_consensus: Pre-formatted sector sentiment consensus, or empty.
        live_quotes: Real-time FMP quotes keyed by ticker (may be None).
        track_conflicts: Pre-formatted Gemini vs Claude directional conflicts.
        force_ml_debate: When True, run bull/bear even if ``config.enable_debate`` is False.
        pre_gpt_ml: Independent ML gate outputs injected into GPT prompts (Track D).
        ml_escalation: Add stronger reconciliation instructions for uncertain ML.

    Returns:
        Tuple of (list of Recommendation results,
        list of per-call metadata dicts).
    """
    all_metadata: list[dict] = []
    bull_cases: list[DebateCase] | None = None
    bear_cases: list[DebateCase] | None = None

    # Single-pass synthesis: debate disabled in favour of balanced one-shot analysis.
    # Debate code retained below for potential future re-enablement.
    run_debate_track = False

    if run_debate_track:
        bull_cases, bear_cases, debate_metadata = await _run_debate_phase(
            tickers,
            screening,
            charts,
            sentiments,
            config,
            ta_snapshots=ta_snapshots,
            risk_assessments=risk_assessments,
            fmp_context=fmp_context,
            live_quotes=live_quotes,
            pre_gpt_ml=pre_gpt_ml,
            ml_escalation=ml_escalation,
        )
        all_metadata.extend(debate_metadata)

    recommendations, judge_metadata = await _run_judge_phase(
        tickers,
        screening,
        charts,
        sentiments,
        bull_cases,
        bear_cases,
        reflection_context,
        config,
        ta_snapshots=ta_snapshots,
        risk_assessments=risk_assessments,
        fmp_context=fmp_context,
        regime_context=regime_context,
        sector_consensus=sector_consensus,
        live_quotes=live_quotes,
        track_conflicts=track_conflicts,
        pre_gpt_ml=pre_gpt_ml,
        ml_escalation=ml_escalation,
    )
    all_metadata.append(judge_metadata)

    for rec in recommendations:
        if rec.action in ("BUY", "SHORT"):
            missing = []
            if rec.entry_price is None:
                missing.append("entry_price")
            if rec.stop_loss is None:
                missing.append("stop_loss")
            if rec.take_profit is None:
                missing.append("take_profit")
            if missing:
                logger.warning(
                    "GPT judge returned %s for %s but missing: %s",
                    rec.action,
                    rec.ticker,
                    ", ".join(missing),
                )

    # Backfill any tickers GPT skipped with NO_TRADE
    returned_tickers = {rec.ticker for rec in recommendations}
    for ticker in tickers:
        if ticker not in returned_tickers:
            logger.warning("GPT skipped %s — backfilling as NO_TRADE", ticker)
            recommendations.append(
                Recommendation(
                    ticker=ticker,
                    action="NO_TRADE",
                    confidence=0.10,
                    judge_reasoning="GPT did not produce a recommendation for this ticker.",
                    key_factors=["Skipped by GPT synthesis"],
                )
            )

    logger.info(
        "GPT debate: %d recommendations for %d tickers (debate=%s, ml_escalation=%s)",
        len(recommendations),
        len(tickers),
        run_debate_track,
        ml_escalation,
    )
    return recommendations, all_metadata


async def _run_debate_phase(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
    ta_snapshots: list[MultiTimeframeTechnical] | None = None,
    risk_assessments: list[RiskAssessment] | None = None,
    fmp_context: dict | None = None,
    live_quotes: dict | None = None,
    pre_gpt_ml: dict[str, GateResult] | None = None,
    ml_escalation: bool = False,
) -> tuple[list[DebateCase] | None, list[DebateCase] | None, list[dict]]:
    """Run bull then bear sequentially with track-aware prompts.

    Bear receives a summary of the bull's cases so it can challenge specific points.

    Returns:
        Tuple of (bull_cases or None, bear_cases or None, metadata list).
    """
    bull_prompt = build_bull_prompt(
        tickers,
        screening,
        charts,
        sentiments,
        config,
        ta_snapshots=ta_snapshots,
        risk_assessments=risk_assessments,
        fmp_context=fmp_context,
        live_quotes=live_quotes,
        pre_gpt_ml=pre_gpt_ml,
        ml_escalation=ml_escalation,
    )
    bear_prompt = build_bear_prompt(
        tickers,
        screening,
        charts,
        sentiments,
        config,
        ta_snapshots=ta_snapshots,
        risk_assessments=risk_assessments,
        fmp_context=fmp_context,
        live_quotes=live_quotes,
        pre_gpt_ml=pre_gpt_ml,
        ml_escalation=ml_escalation,
    )

    bull_metadata: dict = {
        "stage": "gpt_bull",
        "model": GPT_MODEL,
        "prompt_hash": get_bull_hash(),
        "prompt_text": f"{BULL_SYSTEM_PROMPT}\n---\n{bull_prompt}",
    }
    bear_metadata: dict = {
        "stage": "gpt_bear",
        "model": GPT_MODEL,
        "prompt_hash": get_bear_hash(),
        "prompt_text": f"{BEAR_SYSTEM_PROMPT}\n---\n{bear_prompt}",
    }

    start = time.perf_counter()

    # Run bull first
    try:
        bull_result = await _call_gpt_bull(BULL_SYSTEM_PROMPT, bull_prompt)
    except Exception as exc:
        bull_result = exc

    # Inject bull's arguments into bear prompt so bear can challenge specific points
    bull_cases_for_bear: list[DebateCase] | None = None
    if (isinstance(bull_result, DebateCaseList) and bull_result is not None) or (
        not isinstance(bull_result, Exception) and bull_result is not None
    ):
        bull_cases_for_bear = bull_result.cases

    if bull_cases_for_bear:
        bull_summary_lines = []
        for bc in bull_cases_for_bear:
            args = "; ".join(bc.key_arguments[:3])
            bull_summary_lines.append(f"- {bc.ticker}: {bc.strongest_signal} (args: {args})")
        bull_challenge_section = (
            "\n\n## BULL CASE TO CHALLENGE\n"
            "The bull analyst made these specific arguments. You MUST directly "
            "counter each one with specific evidence:\n" + "\n".join(bull_summary_lines)
        )
        bear_prompt = bear_prompt + bull_challenge_section
        bear_metadata["prompt_text"] = f"{BEAR_SYSTEM_PROMPT}\n---\n{bear_prompt}"

    # Run bear with bull context
    try:
        bear_result = await _call_gpt_bear(BEAR_SYSTEM_PROMPT, bear_prompt)
    except Exception as exc:
        bear_result = exc

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    bull_cases: list[DebateCase] | None = None
    bear_cases: list[DebateCase] | None = None

    if isinstance(bull_result, Exception):
        logger.error("GPT bull case failed: %s", bull_result)
        bull_metadata["status"] = "api_error"
        bull_metadata["error"] = str(bull_result)
    elif bull_result is not None:
        bull_cases = bull_result.cases
        bull_metadata["status"] = "success"
        bull_metadata["raw_response"] = bull_result.model_dump_json()
        if hasattr(bull_result, "cases"):
            bull_metadata["retry_count"] = getattr(bull_result, "_retry_count", 0)
    else:
        bull_metadata["status"] = "validation_failed"

    if isinstance(bear_result, Exception):
        logger.error("GPT bear case failed: %s", bear_result)
        bear_metadata["status"] = "api_error"
        bear_metadata["error"] = str(bear_result)
    elif bear_result is not None:
        bear_cases = bear_result.cases
        bear_metadata["status"] = "success"
        bear_metadata["raw_response"] = bear_result.model_dump_json()
        if hasattr(bear_result, "cases"):
            bear_metadata["retry_count"] = getattr(bear_result, "_retry_count", 0)
    else:
        bear_metadata["status"] = "validation_failed"

    bull_metadata["duration_ms"] = elapsed_ms
    bear_metadata["duration_ms"] = elapsed_ms

    return bull_cases, bear_cases, [bull_metadata, bear_metadata]


async def _run_judge_phase(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    bull_cases: list[DebateCase] | None,
    bear_cases: list[DebateCase] | None,
    reflection_context: str,
    config: StrategyConfig,
    ta_snapshots: list[MultiTimeframeTechnical] | None = None,
    risk_assessments: list[RiskAssessment] | None = None,
    fmp_context: dict | None = None,
    regime_context: str = "",
    sector_consensus: str = "",
    live_quotes: dict | None = None,
    track_conflicts: str = "",
    pre_gpt_ml: dict[str, GateResult] | None = None,
    ml_escalation: bool = False,
) -> tuple[list[Recommendation], dict]:
    """Run the judge with track-aware conflict resolution.

    Returns:
        Tuple of (list of Recommendations, metadata dict).
    """
    judge_prompt = build_judge_prompt(
        tickers,
        screening,
        charts,
        sentiments,
        bull_cases,
        bear_cases,
        reflection_context,
        config,
        ta_snapshots=ta_snapshots,
        risk_assessments=risk_assessments,
        fmp_context=fmp_context,
        regime_context=regime_context,
        sector_consensus=sector_consensus,
        live_quotes=live_quotes,
        track_conflicts=track_conflicts,
        pre_gpt_ml=pre_gpt_ml,
        ml_escalation=ml_escalation,
    )

    judge_prompt = enforce_token_budget(JUDGE_SYSTEM_PROMPT, judge_prompt, model=GPT_MODEL)

    metadata: dict = {
        "stage": "gpt_judge",
        "model": GPT_MODEL,
        "prompt_hash": get_judge_hash(),
        "prompt_text": f"{JUDGE_SYSTEM_PROMPT}\n---\n{judge_prompt}",
    }

    start = time.perf_counter()
    try:
        result = await _call_gpt_judge(JUDGE_SYSTEM_PROMPT, judge_prompt)
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)

        if result is not None:
            metadata["status"] = "success"
            metadata["raw_response"] = result.model_dump_json()
            metadata["retry_count"] = getattr(result, "_retry_count", 0)
            recommendations = [
                Recommendation(**gpt_rec.model_dump()) for gpt_rec in result.recommendations
            ]
            return recommendations, metadata

        metadata["status"] = "validation_failed"
        return [], metadata
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("GPT judge failed")
        return [], metadata
