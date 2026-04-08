"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

_env_candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
for _env_path in _env_candidates:
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
        break


class Settings(BaseModel):
    """MCP server settings.

    Attributes:
        backend_url: SignalForge FastAPI backend base URL.
        auth_token: Supabase JWT for backend API calls (empty for dev mode).
        ibkr_host: IBKR TWS/Gateway hostname.
        ibkr_port: IBKR port (7497=TWS paper, 7496=TWS live, 4002=GW paper, 4001=GW live).
        ibkr_client_id: IBKR client connection ID.
        ibkr_paper: Whether connected to a paper trading account.
        daily_loss_limit_pct: Max daily loss as percent of equity before blocking trades.
        max_position_size_pct: Hard cap on position size percent.
        max_portfolio_exposure_pct: Max total portfolio exposure percent.
        min_confidence: Minimum recommendation confidence to allow execution.
        max_orders_per_hour: Rate limit on order placement.
        require_market_hours: Only allow orders during regular US market hours.
    """

    backend_url: str = "http://localhost:8420"
    auth_token: str = ""

    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1
    ibkr_paper: bool = True

    daily_loss_limit_pct: float = 2.0
    max_position_size_pct: float = 5.0
    max_portfolio_exposure_pct: float = 25.0
    min_confidence: float = 0.60
    max_orders_per_hour: int = 10
    require_market_hours: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from environment variables.

        Returns:
            Settings instance populated from os.environ.
        """
        return cls(
            backend_url=os.environ.get("SIGNALFORGE_BACKEND_URL", "http://localhost:8420"),
            auth_token=os.environ.get("SIGNALFORGE_AUTH_TOKEN", ""),
            ibkr_host=os.environ.get("IBKR_HOST", "127.0.0.1"),
            ibkr_port=int(os.environ.get("IBKR_PORT", "7497")),
            ibkr_client_id=int(os.environ.get("IBKR_CLIENT_ID", "1")),
            ibkr_paper=os.environ.get("IBKR_PAPER", "true").lower() == "true",
            daily_loss_limit_pct=float(os.environ.get("DAILY_LOSS_LIMIT_PCT", "2.0")),
            max_position_size_pct=float(os.environ.get("MAX_POSITION_SIZE_PCT", "5.0")),
            max_portfolio_exposure_pct=float(os.environ.get("MAX_PORTFOLIO_EXPOSURE_PCT", "25.0")),
            min_confidence=float(os.environ.get("MIN_CONFIDENCE", "0.60")),
            max_orders_per_hour=int(os.environ.get("MAX_ORDERS_PER_HOUR", "10")),
            require_market_hours=os.environ.get("REQUIRE_MARKET_HOURS", "true").lower() == "true",
        )


settings = Settings.from_env()
