"""Async HTTP client for the SignalForge FastAPI backend."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from mcp_server.config import settings

logger = logging.getLogger(__name__)


class BackendClient:
    """HTTP client wrapping the SignalForge backend API.

    All pipeline, strategy, and recommendation data flows through the existing
    FastAPI backend. This client handles authentication and request/response
    serialization.

    Attributes:
        base_url: Backend base URL (e.g. http://localhost:8420).
    """

    def __init__(self) -> None:
        self.base_url = settings.backend_url.rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if settings.auth_token:
            headers["Authorization"] = f"Bearer {settings.auth_token}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(300.0, connect=10.0),
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    async def trigger_pipeline(
        self,
        strategy_id: str | None = None,
        manual_tickers: list[str] | None = None,
        user_prompt: str | None = None,
        screener_overrides: dict[str, Any] | None = None,
    ) -> str:
        """Trigger a pipeline run. Returns the run_id.

        Args:
            strategy_id: Strategy ID to use for the run.
            manual_tickers: Explicit tickers to analyze.
            user_prompt: Free-form prompt for discovery mode.
            screener_overrides: FMP screener overrides (sector, industry, exchange, etc.).

        Returns:
            The run_id string for polling progress.

        Raises:
            httpx.HTTPStatusError: If the backend returns a non-2xx response.
        """
        body: dict[str, Any] = {}
        if strategy_id:
            body["strategy_id"] = strategy_id
        if manual_tickers:
            body["manual_tickers"] = manual_tickers
        if user_prompt:
            body["user_prompt"] = user_prompt
        if screener_overrides:
            body["screener_overrides"] = screener_overrides

        resp = await self._client.post("/api/pipeline/run", json=body)
        resp.raise_for_status()
        return resp.json()["run_id"]

    async def get_pipeline_progress(self, run_id: str) -> dict[str, Any]:
        """Get live stage-by-stage progress for a pipeline run.

        Args:
            run_id: The pipeline run ID.

        Returns:
            Progress dict with run_status, elapsed_seconds, and stages list.
        """
        resp = await self._client.get(f"/api/pipeline/progress/{run_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_pipeline_result(self, run_id: str) -> dict[str, Any]:
        """Get the full result of a completed pipeline run.

        Args:
            run_id: The pipeline run ID.

        Returns:
            Full PipelineResult dict including recommendations.
        """
        resp = await self._client.get(f"/api/pipeline/status/{run_id}")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    async def list_strategies(self) -> list[dict[str, Any]]:
        """List all saved strategies.

        Returns:
            List of strategy config dicts.
        """
        resp = await self._client.get("/api/strategies")
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def list_pipeline_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent pipeline runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of run summary dicts.
        """
        resp = await self._client.get("/api/pipeline/runs")
        resp.raise_for_status()
        runs: list[dict[str, Any]] = resp.json()
        return runs[:limit]

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    async def get_recommendation(self, rec_id: str) -> dict[str, Any]:
        """Get a single recommendation by ID.

        Args:
            rec_id: The recommendation ID.

        Returns:
            Recommendation dict with all fields.
        """
        resp = await self._client.get(f"/api/recommendations/{rec_id}")
        resp.raise_for_status()
        return resp.json()

    async def post_sector_concentration(
        self,
        open_symbols: list[str],
        proposed_symbol: str,
        max_positions_per_sector: int,
    ) -> dict[str, Any]:
        """Check GICS sector concentration via backend + FMP."""
        resp = await self._client.post(
            "/api/execution/sector-concentration",
            json={
                "open_position_symbols": open_symbols,
                "proposed_symbol": proposed_symbol,
                "max_positions_per_sector": max_positions_per_sector,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def post_brokerage_open(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record an open position after IBKR execution."""
        resp = await self._client.post("/api/outcomes/brokerage-open", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_daily_outcome_summary(self) -> dict[str, Any]:
        """Aggregated Supabase outcomes for the current US Eastern trading day."""
        resp = await self._client.get("/api/outcomes/daily-summary")
        resp.raise_for_status()
        return resp.json()


_client: BackendClient | None = None


def get_backend_client() -> BackendClient:
    """Get or create the singleton backend client.

    Returns:
        The shared BackendClient instance.
    """
    global _client
    if _client is None:
        _client = BackendClient()
    return _client
