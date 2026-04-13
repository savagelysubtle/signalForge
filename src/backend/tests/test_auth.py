"""Tests for backend auth middleware."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from middleware import auth


@pytest.mark.asyncio
async def test_get_current_user_allows_dev_bypass(monkeypatch):
    monkeypatch.setattr(auth.settings, "dev_auth_bypass", True)
    monkeypatch.setattr(auth.settings, "environment", "development")
    monkeypatch.setattr(auth.settings, "supabase_url", "https://example.supabase.co")

    user_id = await auth.get_current_user()

    assert user_id == "dev-user-local"


@pytest.mark.asyncio
async def test_get_current_user_requires_header_when_bypass_disabled(monkeypatch):
    monkeypatch.setattr(auth.settings, "dev_auth_bypass", False)
    monkeypatch.setattr(auth.settings, "environment", "development")
    monkeypatch.setattr(auth.settings, "supabase_url", "https://example.supabase.co")

    with pytest.raises(HTTPException) as excinfo:
        await auth.get_current_user()

    assert excinfo.value.status_code == 401
