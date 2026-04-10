"""Centralized LLM model configuration.

All model identifiers live here so they can be overridden via env vars
for A/B testing, cost optimization, or failover without code changes.
Each stage imports from this module instead of hardcoding model strings.
"""

from __future__ import annotations

import os

GPT_MODEL: str = os.getenv("SF_GPT_MODEL", "gpt-5.4")
GEMINI_MODEL: str = os.getenv("SF_GEMINI_MODEL", "gemini-2.5-pro")
CLAUDE_MODEL: str = os.getenv("SF_CLAUDE_MODEL", "claude-opus-4-6")
CLAUDE_MAX_TOKENS: int = int(os.getenv("SF_CLAUDE_MAX_TOKENS", "16000"))
PERPLEXITY_MODEL: str = os.getenv("SF_PERPLEXITY_MODEL", "openai/gpt-5.4")
REGIME_MODEL: str = os.getenv("SF_REGIME_MODEL", "perplexity/sonar")
REFLECTION_MODEL: str = os.getenv("SF_REFLECTION_MODEL", "gpt-4o-mini")
