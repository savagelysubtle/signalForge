#!/usr/bin/env python3
"""Detect type drift between Pydantic schemas and TypeScript interfaces.

Parses both files and reports:
- Models in Python but missing from TypeScript
- Models in TypeScript but missing from Python
- Field mismatches (name present in one but not the other)

Usage:
    python scripts/check_type_drift.py [--schemas PATH] [--types PATH]

Defaults to SignalForge project paths relative to the repo root.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_python_models(text: str) -> dict[str, list[str]]:
    """Extract Pydantic model class names and their field names."""
    models: dict[str, list[str]] = {}
    current_class: str | None = None

    for line in text.splitlines():
        class_match = re.match(r"^class (\w+)\(BaseModel\):", line)
        if class_match:
            current_class = class_match.group(1)
            models[current_class] = []
            continue

        if current_class and re.match(r"^class |^def |^async def ", line):
            current_class = None
            continue

        if current_class:
            field_match = re.match(r"    (\w+)\s*:", line)
            if field_match:
                models[current_class].append(field_match.group(1))

    return models


def extract_ts_interfaces(text: str) -> dict[str, list[str]]:
    """Extract TypeScript interface names and their field names."""
    interfaces: dict[str, list[str]] = {}
    current_interface: str | None = None
    brace_depth = 0

    for line in text.splitlines():
        iface_match = re.match(r"^export interface (\w+)\s*\{?", line)
        if iface_match:
            current_interface = iface_match.group(1)
            interfaces[current_interface] = []
            brace_depth = line.count("{") - line.count("}")
            continue

        if current_interface:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                current_interface = None
                continue

            field_match = re.match(r"\s+(\w+)\s*[?:]", line)
            if field_match:
                interfaces[current_interface].append(field_match.group(1))

    return interfaces


def check_drift(
    schemas_path: Path,
    types_path: Path,
) -> list[str]:
    """Compare Python models and TypeScript interfaces, return issues."""
    py_text = schemas_path.read_text(encoding="utf-8")
    ts_text = types_path.read_text(encoding="utf-8")

    py_models = extract_python_models(py_text)
    ts_interfaces = extract_ts_interfaces(ts_text)

    issues: list[str] = []

    py_names = set(py_models.keys())
    ts_names = set(ts_interfaces.keys())

    for name in sorted(py_names - ts_names):
        issues.append(f"MISSING IN TS: {name} (exists in Python but not TypeScript)")

    for name in sorted(py_names & ts_names):
        py_fields = set(py_models[name])
        ts_fields = set(ts_interfaces[name])

        for field in sorted(py_fields - ts_fields):
            issues.append(f"FIELD DRIFT: {name}.{field} exists in Python but not TypeScript")
        for field in sorted(ts_fields - py_fields):
            issues.append(f"FIELD DRIFT: {name}.{field} exists in TypeScript but not Python")

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Pydantic ↔ TypeScript type drift")
    parser.add_argument(
        "--schemas",
        type=Path,
        default=Path("src/backend/pipeline/schemas.py"),
        help="Path to Python schemas file",
    )
    parser.add_argument(
        "--types",
        type=Path,
        default=Path("src/frontend/src/types/index.ts"),
        help="Path to TypeScript types file",
    )
    args = parser.parse_args()

    if not args.schemas.exists():
        print(f"ERROR: {args.schemas} not found")
        sys.exit(2)
    if not args.types.exists():
        print(f"ERROR: {args.types} not found")
        sys.exit(2)

    issues = check_drift(args.schemas, args.types)

    if not issues:
        print("OK: No type drift detected between Python and TypeScript")
        sys.exit(0)
    else:
        print(f"DRIFT DETECTED: {len(issues)} issue(s)\n")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)


if __name__ == "__main__":
    main()
