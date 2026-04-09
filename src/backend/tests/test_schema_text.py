"""Tests for pipeline/schema_text.py — Pydantic model → prompt schema text."""

from __future__ import annotations

from pydantic import BaseModel, Field

from pipeline.schema_text import schema_example_block, schema_to_prompt_text


class _SimpleModel(BaseModel):
    ticker: str
    score: int


class _Child(BaseModel):
    value: float = Field(description="A numeric value")
    label: str = "default"


class _Parent(BaseModel):
    name: str = Field(description="Entity name")
    child: _Child
    tags: list[str] = []


class _WithOptional(BaseModel):
    required_field: str
    optional_field: str | None = None


# ---------------------------------------------------------------------------
# schema_to_prompt_text
# ---------------------------------------------------------------------------


class TestSchemaToPromptText:
    def test_simple_model(self):
        result = schema_to_prompt_text(_SimpleModel)
        assert '"ticker"' in result
        assert '"score"' in result
        assert "string" in result
        assert "integer" in result

    def test_nested_model(self):
        result = schema_to_prompt_text(_Parent)
        assert '"name"' in result
        assert '"child"' in result
        assert '"value"' in result
        assert '"tags"' in result

    def test_exclude_fields(self):
        result = schema_to_prompt_text(_SimpleModel, exclude_fields={"score"})
        assert '"ticker"' in result
        assert '"score"' not in result

    def test_includes_descriptions(self):
        result = schema_to_prompt_text(_Parent, include_descriptions=True)
        assert "Entity name" in result
        assert "A numeric value" in result

    def test_excludes_descriptions(self):
        result = schema_to_prompt_text(_Parent, include_descriptions=False)
        assert "Entity name" not in result
        assert "A numeric value" not in result

    def test_optional_field_marked(self):
        result = schema_to_prompt_text(_WithOptional)
        assert "(optional)" in result


# ---------------------------------------------------------------------------
# schema_example_block
# ---------------------------------------------------------------------------


class TestSchemaExampleBlock:
    def test_wraps_with_fences(self):
        result = schema_example_block(_SimpleModel)
        assert result.startswith("Expected JSON structure:\n```\n")
        assert result.endswith("\n```")

    def test_contains_schema(self):
        result = schema_example_block(_SimpleModel)
        assert '"ticker"' in result
        assert '"score"' in result

    def test_respects_exclude_fields(self):
        result = schema_example_block(_SimpleModel, exclude_fields={"ticker"})
        assert '"ticker"' not in result
        assert '"score"' in result
