"""Generate JSON schema text from Pydantic models for prompt injection.

Prevents schema drift between the JSON output format described in LLM
prompts and the Pydantic models used for validation. Prompt builders
should call ``schema_to_prompt_text()`` instead of maintaining inline
JSON schema strings that can fall out of sync with ``schemas.py``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def schema_to_prompt_text(
    model: type[BaseModel],
    *,
    indent: int = 2,
    include_descriptions: bool = True,
    exclude_fields: set[str] | None = None,
) -> str:
    """Generate a human-readable JSON schema block from a Pydantic model.

    Produces a compact schema representation suitable for injection into
    LLM prompts. Resolves ``$ref`` pointers so the output is self-contained.

    Args:
        model: Pydantic model class to generate schema for.
        indent: JSON indentation level.
        include_descriptions: Whether to include field descriptions as
            inline comments in the output.
        exclude_fields: Field names to omit from the schema (e.g. internal
            fields set by the orchestrator, not by the LLM).

    Returns:
        A formatted string showing the expected JSON structure with types
        and optional descriptions.
    """
    raw_schema = model.model_json_schema()
    defs = raw_schema.pop("$defs", {})
    exclude = exclude_fields or set()

    def _resolve_ref(node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            ref_name = node["$ref"].rsplit("/", 1)[-1]
            if ref_name in defs:
                return _resolve_ref(dict(defs[ref_name]))
        return node

    def _type_hint(prop: dict[str, Any]) -> str:
        prop = _resolve_ref(prop)

        if "anyOf" in prop:
            types = []
            for variant in prop["anyOf"]:
                variant = _resolve_ref(variant)
                types.append(_type_hint(variant))
            return " | ".join(types)

        if "enum" in prop:
            return " | ".join(f'"{v}"' for v in prop["enum"])

        t = prop.get("type", "any")
        if t == "array":
            items = prop.get("items", {})
            items = _resolve_ref(items)
            return f"[{_type_hint(items)}, ...]"
        if t == "object":
            if "properties" in prop:
                inner = _build_object(prop)
                return inner
            return "{...}"
        if t == "string":
            return "string"
        if t == "number" or t == "integer":
            fmt = ""
            if "ge" in prop or "le" in prop:
                bounds = []
                if "ge" in prop:
                    bounds.append(f">={prop['ge']}")
                if "le" in prop:
                    bounds.append(f"<={prop['le']}")
                fmt = f" ({', '.join(bounds)})"
            return f"{t}{fmt}"
        if t == "boolean":
            return "boolean"
        if t == "null":
            return "null"
        return t

    def _build_object(schema: dict[str, Any]) -> str:
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        lines = ["{"]
        for name, prop in props.items():
            if name in exclude:
                continue
            prop = _resolve_ref(prop)
            hint = _type_hint(prop)
            opt = "" if name in required else " (optional)"
            desc = ""
            if include_descriptions and "description" in prop:
                desc = f"  // {prop['description']}"
            lines.append(f'  "{name}": <{hint}>{opt},{desc}')
        lines.append("}")
        return "\n".join(lines)

    return _build_object(raw_schema)


def schema_example_block(
    model: type[BaseModel],
    *,
    exclude_fields: set[str] | None = None,
) -> str:
    """Generate a prompt-ready schema block with header and fence.

    Args:
        model: Pydantic model class.
        exclude_fields: Fields to omit.

    Returns:
        Fenced schema block ready for prompt injection.
    """
    schema_text = schema_to_prompt_text(model, exclude_fields=exclude_fields)
    return f"Expected JSON structure:\n```\n{schema_text}\n```"
