# Stage Implementation Workflow

Complete checklist for adding a new LLM pipeline stage to SignalForge.

## 1. Define Pydantic Schema

File: `src/backend/pipeline/schemas.py`

```python
class MyStageOutput(BaseModel):
    """Output from the new stage."""
    ticker: str
    # fields matching the LLM's expected JSON output

class MyStageOutputList(BaseModel):
    """Wrapper for batch output."""
    results: list[MyStageOutput]
```

Rules:
- All fields must have type hints
- Use `Literal` for constrained string values
- Use `Field(default_factory=list)` for list defaults
- Use `X | None` for optional fields with `None` default
- Google-style docstrings required

## 2. Create Prompt Module

File: `src/backend/pipeline/prompts/my_stage.py`

```python
from __future__ import annotations
from pipeline.schemas import StrategyConfig
from utils.hashing import prompt_hash

PROMPT_VERSION = "v1"

MY_STAGE_SYSTEM_PROMPT = """You are a ..."""

def get_prompt_hash() -> str:
    return prompt_hash(MY_STAGE_SYSTEM_PROMPT)

def build_my_stage_prompt(
    ticker: str,
    config: StrategyConfig,
    upstream_data: ...,
) -> str:
    sections = [f"Analyze {ticker}..."]
    # Add upstream data sections conditionally
    if upstream_data:
        sections.append(f"Context: {upstream_data}")
    else:
        sections.append("Note: upstream data unavailable.")
    return "\n\n".join(sections)
```

## 3. Create Stage Module

File: `src/backend/pipeline/stages/my_stage.py`

```python
from __future__ import annotations
import asyncio
import logging
import time
from pipeline.prompts.my_stage import (
    MY_STAGE_SYSTEM_PROMPT,
    build_my_stage_prompt,
    get_prompt_hash,
)
from pipeline.schemas import MyStageOutput, StrategyConfig
from pipeline.validation import with_validation_retry
from services.keyring_service import get_api_key

logger = logging.getLogger(__name__)

@with_validation_retry(schema=MyStageOutput, max_retries=2)
async def _call_my_llm(
    prompt: str,
    *,
    error_context: str = "",
) -> str:
    api_key = get_api_key("provider")
    # Make the API call, return raw response string
    ...

async def run_my_stage(
    tickers: list[str],
    config: StrategyConfig,
) -> tuple[list[MyStageOutput], list[dict]]:
    semaphore = asyncio.Semaphore(3)
    results: list[MyStageOutput] = []
    metadata_list: list[dict] = []

    async def _process(ticker: str) -> None:
        async with semaphore:
            prompt = build_my_stage_prompt(ticker, config)
            start = time.perf_counter()
            output = await _call_my_llm(prompt)
            elapsed = int((time.perf_counter() - start) * 1000)

            meta = {
                "stage": "my_stage",
                "ticker": ticker,
                "model": "model-name",
                "prompt_hash": get_prompt_hash(),
                "prompt_text": prompt,
                "duration_ms": elapsed,
                "status": "success" if output else "failed",
                "raw_response": "...",
            }
            metadata_list.append(meta)
            if output:
                results.append(output)

    await asyncio.gather(*(_process(t) for t in tickers))
    return results, metadata_list
```

## 4. Wire into Orchestrator

File: `src/backend/pipeline/orchestrator.py`

1. Import the stage function and prompt hash at the top
2. Add the stage call in sequence (after appropriate predecessor)
3. Wrap in try/except, append errors to `result.stage_errors`
4. Save metadata via `_save_stage_output(run_id, meta)`
5. Add hash to `result.prompt_versions`

```python
# In run_pipeline(), after previous stage:
try:
    my_results, my_metadata_list = await run_my_stage(ticker_symbols, effective_config)
    result.my_stage_results = my_results
    for mm in my_metadata_list:
        await _save_stage_output(run_id, mm)
except Exception as exc:
    result.stage_errors.append({
        "stage": "my_stage",
        "error": str(exc),
        "type": type(exc).__name__,
    })
    logger.exception("Pipeline my_stage failed")
```

## 5. Sync TypeScript Types

File: `src/frontend/src/types/index.ts`

Add matching TypeScript interface using type mapping:
- `str` → `string`, `float` → `number`, `bool` → `boolean`
- `list[X]` → `X[]`, `X | None` → `X | null`
- `Literal["a", "b"]` → `"a" | "b"`
- `datetime` → `string` with `// ISO 8601` comment

## 6. Add Frontend Display

File: `src/frontend/src/components/recommendations/MyTab.tsx`

1. Create the tab component receiving data via props
2. Add tab button and panel in `DetailView.tsx`
3. Use dark theme CSS variables and `clsx` for conditional classes

## 7. Quality Checks

```bash
cd src/backend
uv run ruff format
uv run ruff check --fix
uv run ty check
```
