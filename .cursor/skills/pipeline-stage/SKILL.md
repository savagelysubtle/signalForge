---
name: pipeline-stage
description: >
  Create or modify LLM pipeline stages in SignalForge. Use when adding a new AI model stage,
  modifying an existing stage (perplexity, gemini, claude, gpt), updating stage wiring in
  the orchestrator, or implementing the validation retry pattern. Covers the full lifecycle:
  schema, prompt, stage function, orchestrator integration, and degraded fallback.
---

# Pipeline Stage

## File Locations

| Concern         | Path                                      |
|-----------------|-------------------------------------------|
| Schemas         | `src/backend/pipeline/schemas.py`         |
| Prompts         | `src/backend/pipeline/prompts/{stage}.py` |
| Stage logic     | `src/backend/pipeline/stages/{stage}.py`  |
| Orchestrator    | `src/backend/pipeline/orchestrator.py`    |
| Validation      | `src/backend/pipeline/validation.py`      |
| Prompt hashing  | `src/backend/utils/hashing.py`            |

## Creating a New Stage

For the complete step-by-step checklist with full code templates, see
[references/stage-workflow.md](references/stage-workflow.md).

### 1. Define Pydantic schema (`schemas.py`)

```python
class MyStageOutput(BaseModel):
    """Output from the new stage."""
    ticker: str
    # ... fields matching expected LLM JSON output
```

If the LLM returns a list, add a wrapper:

```python
class MyStageOutputList(BaseModel):
    results: list[MyStageOutput]
```

### 2. Create prompt file (`prompts/my_stage.py`)

```python
PROMPT_VERSION = "v1"

MY_STAGE_SYSTEM_PROMPT = """..."""

def get_prompt_hash() -> str:
    from utils.hashing import prompt_hash
    return prompt_hash(MY_STAGE_SYSTEM_PROMPT)

def build_my_stage_prompt(ticker: str, config: StrategyConfig, ...) -> str:
    return f"Analyze {ticker}..."
```

### 3. Create stage file (`stages/my_stage.py`)

```python
@with_validation_retry(schema=MyStageOutput, max_retries=2)
async def _call_llm(prompt: str, *, error_context: str = "") -> str:
    # Make API call, return raw response string
    ...

async def run_my_stage(
    tickers: list[str],
    config: StrategyConfig,
) -> tuple[list[MyStageOutput], list[dict]]:
    semaphore = asyncio.Semaphore(3)
    results = []
    metadata_list = []

    async def _process(ticker: str) -> None:
        async with semaphore:
            prompt = build_my_stage_prompt(ticker, config)
            start = time.perf_counter()
            output = await _call_llm(prompt)
            elapsed = int((time.perf_counter() - start) * 1000)
            meta = {
                "stage": "my_stage", "ticker": ticker,
                "model": "model-name", "prompt_hash": get_prompt_hash(),
                "prompt_text": prompt, "duration_ms": elapsed,
                "status": "success" if output else "failed",
                "raw_response": "...",
            }
            metadata_list.append(meta)
            if output:
                results.append(output)

    await asyncio.gather(*(_process(t) for t in tickers))
    return results, metadata_list
```

### 4. Wire into orchestrator (`orchestrator.py`)

- Import the stage function and prompt hash
- Add the stage call after the appropriate predecessor
- Wrap in `try/except` and append errors to `result.stage_errors`
- Save metadata via `_save_stage_output(run_id, meta)`
- Add prompt hash to `result.prompt_versions`

### 5. Sync TypeScript types

Follow the `schema-sync` skill to add matching TypeScript interfaces.

## Validation Retry Pattern

Every LLM call uses `@with_validation_retry(schema=T, max_retries=2)`:

- Decorated function must be `async` and return `str` (raw LLM response)
- Must accept `error_context: str = ""` kwarg
- On validation failure, retries with schema + error injected into prompt
- Returns `T | None` — `None` means all retries exhausted

## Degraded Pipeline Rules

- Stage failure must NOT kill the pipeline
- Append error to `result.stage_errors` with `{stage, error, type}`
- Downstream stages receive partial data and adapt prompts accordingly
- GPT judge prompt should note which data is unavailable

## Metadata Dict Shape

Every stage returns `(result, metadata)` where metadata is:

```python
{
    "stage": str,
    "ticker": str,
    "model": str,
    "prompt_hash": str,
    "prompt_text": str,
    "duration_ms": int,
    "status": "success" | "failed",
    "raw_response": str,
    "error": str | None,
}
```

## Concurrency Defaults

| Stage      | Semaphore |
|------------|-----------|
| Perplexity | 3         |
| Gemini     | 5         |
| Claude     | 3         |
| GPT        | bull+bear parallel, judge sequential |
