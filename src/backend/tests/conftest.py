"""Shared test fixtures for SignalForge backend tests."""

from __future__ import annotations

import pytest
from pydantic import BaseModel


class SimpleSchema(BaseModel):
    """Minimal Pydantic model for validation tests."""

    ticker: str
    score: int


class NestedChild(BaseModel):
    """Child model for nested-schema tests."""

    value: float
    label: str = "default"


class NestedParent(BaseModel):
    """Parent model containing a nested child for schema_text tests."""

    name: str
    child: NestedChild
    tags: list[str] = []


@pytest.fixture
def simple_schema() -> type[SimpleSchema]:
    return SimpleSchema


@pytest.fixture
def nested_parent_schema() -> type[NestedParent]:
    return NestedParent
