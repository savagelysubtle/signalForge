"""GPT debate and synthesis stage.

Stage 4: Processes all tickers in batch through a bull/bear/judge debate
(or single synthesis call when debate is disabled). Bull and bear analysts
run in parallel; the judge runs sequentially after both complete.

Uses the ``openai`` SDK with ``AsyncOpenAI`` for async API calls.
"""

from __future__ import annotations

import asyncio
import logging
import time

from openai import AsyncOpenAI

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
    Recommendation,
    RecommendationList,
    ScreeningResult,
    SentimentAnalysis,
    StrategyConfig,
)
from pipeline.validation import with_validation_retry
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

GPT_MODEL = "gpt-4.1"


def _get_client() -> AsyncOpenAI:
    """Build an async OpenAI client using the configured API key."""
    api_key = get_api_key("openai")
    if not api_key:
        raise RuntimeError(
            "OpenAI API key not configured. Set OPENAI_API_KEY in .env (see .env.example)."
        )
    return AsyncOpenAI(api_key=api_key)


@with_validation_retry(schema=DebateCaseList, max_retries=2)
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
    return await _call_gpt(system_prompt, user_prompt, error_context=error_context)


@with_validation_retry(schema=DebateCaseList, max_retries=2)
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
    return await _call_gpt(system_prompt, user_prompt, error_context=error_context)


@with_validation_retry(schema=RecommendationList, max_retries=2)
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
    return await _call_gpt(system_prompt, user_prompt, error_context=error_context)


async def _call_gpt(
    system_prompt: str,
    user_prompt: str,
    *,
    error_context: str = "",
) -> str:
    """Make a single GPT API call.

    Args:
        system_prompt: System instruction for the role.
        user_prompt: User message with all data.
        error_context: Appended on retries for self-correction.

    Returns:
        Raw response text from the API.
    """
    client = _get_client()

    full_user_prompt = user_prompt
    if error_context:
        full_user_prompt = f"{user_prompt}\n\n---\nCORRECTION: {error_context}"

    response = await client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_user_prompt},
        ],
        temperature=0.7,
        max_tokens=8192,
    )

    return response.choices[0].message.content or ""


async def run_debate(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
    reflection_context: str,
    run_id: str,
) -> tuple[list[Recommendation], list[dict]]:
    """Run the GPT debate/synthesis stage for all tickers.

    When ``config.enable_debate`` is True, runs bull and bear analysts
    in parallel, then feeds their arguments to the judge. When False,
    runs a single judge call without debate arguments.

    Args:
        tickers: List of ticker symbols to analyze.
        screening: Perplexity screening result (may be None).
        charts: List of ChartAnalysis from Claude (may be empty).
        sentiments: List of SentimentAnalysis from Gemini (may be empty).
        config: Strategy configuration with risk params and debate toggle.
        reflection_context: Historical performance injection prompt.
        run_id: Pipeline run UUID for metadata tracking.

    Returns:
        Tuple of (list of Recommendation results,
        list of per-call metadata dicts).
    """
    all_metadata: list[dict] = []
    bull_cases: list[DebateCase] | None = None
    bear_cases: list[DebateCase] | None = None

    if config.enable_debate:
        bull_cases, bear_cases, debate_metadata = await _run_debate_phase(
            tickers,
            screening,
            charts,
            sentiments,
            config,
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
    )
    all_metadata.append(judge_metadata)

    logger.info(
        "GPT debate: %d recommendations for %d tickers (debate=%s)",
        len(recommendations),
        len(tickers),
        config.enable_debate,
    )
    return recommendations, all_metadata


async def _run_debate_phase(
    tickers: list[str],
    screening: ScreeningResult | None,
    charts: list[ChartAnalysis],
    sentiments: list[SentimentAnalysis],
    config: StrategyConfig,
) -> tuple[list[DebateCase] | None, list[DebateCase] | None, list[dict]]:
    """Run bull and bear analysts in parallel.

    Returns:
        Tuple of (bull_cases or None, bear_cases or None, metadata list).
    """
    bull_prompt = build_bull_prompt(tickers, screening, charts, sentiments, config)
    bear_prompt = build_bear_prompt(tickers, screening, charts, sentiments, config)

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

    bull_task = _call_gpt_bull(BULL_SYSTEM_PROMPT, bull_prompt)
    bear_task = _call_gpt_bear(BEAR_SYSTEM_PROMPT, bear_prompt)

    results = await asyncio.gather(bull_task, bear_task, return_exceptions=True)

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    bull_result = results[0]
    bear_result = results[1]

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
) -> tuple[list[Recommendation], dict]:
    """Run the judge to produce final recommendations.

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
    )

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
            return result.recommendations, metadata

        metadata["status"] = "validation_failed"
        return [], metadata
    except Exception as exc:
        metadata["duration_ms"] = int((time.perf_counter() - start) * 1000)
        metadata["status"] = "api_error"
        metadata["error"] = str(exc)
        logger.exception("GPT judge failed")
        return [], metadata
