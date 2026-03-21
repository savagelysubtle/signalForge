---
name: prompt-engineering
description: >
  Manage LLM prompt versioning and construction in SignalForge. Use when editing files in
  pipeline/prompts/, changing system or user prompts, adding prompt parameters, or when a
  prompt hash needs updating. Enforces version bumping, hash regeneration, and the
  build_*_prompt() construction pattern.
---

# Prompt Engineering

## Prompt File Structure

Each prompt module in `src/backend/pipeline/prompts/` follows this pattern:

```python
PROMPT_VERSION = "v1"  # bump on every change

SYSTEM_PROMPT = """..."""

def get_prompt_hash() -> str:
    from utils.hashing import prompt_hash
    return prompt_hash(SYSTEM_PROMPT)

def build_<stage>_prompt(ticker: str, config: StrategyConfig, ...) -> str:
    """Construct the user prompt from strategy config and upstream data."""
    ...
```

## Current Prompt Files

| File                       | Version | Hashed Prompt         |
|----------------------------|---------|-----------------------|
| `perplexity_discovery.py`  | v4      | System prompt         |
| `perplexity_analysis.py`   | v3      | System prompt         |
| `gemini_sentiment.py`      | v2      | System prompt         |
| `claude_chart.py`          | v3      | System prompt         |
| `gpt_debate.py`            | Bull v1, Bear v1, Judge v2 | 3 separate hashes |

## Checklist When Changing a Prompt

1. Edit the prompt constant (`SYSTEM_PROMPT`, `BULL_SYSTEM_PROMPT`, etc.)
2. **Bump `PROMPT_VERSION`** — increment the version number (e.g. v2 → v3)
3. Verify `get_prompt_hash()` references the correct prompt constant
4. The hash auto-updates (SHA-256 of prompt text, first 8 hex chars)
5. Check that `orchestrator.py` imports and stores the hash in `result.prompt_versions`
6. If adding a new prompt, add its hash to the `prompt_versions` dict in the orchestrator

## Prompt Construction Rules

- `build_*_prompt()` takes `StrategyConfig` + upstream stage data
- Use f-strings for interpolation
- Include explicit JSON schema in the prompt for structured output
- Tell the LLM which data is unavailable when upstream stages failed (degraded mode)
- GPT prompts accept `reflection_context: str | None` for self-learning injection

## Hash Storage Flow

```
prompt text → prompt_hash() → 8-char hex
  → stored in stage_outputs.prompt_hash (per-call)
  → stored in pipeline_runs.prompt_versions (per-run, all stages)
```

## Style

- System prompts are module-level string constants (not in functions)
- User prompts are constructed by `build_*` functions
- Prompts must specify the exact JSON schema the LLM should return
- Include examples of expected output format when the schema is complex
