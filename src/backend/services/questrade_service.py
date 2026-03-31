"""Questrade API client for brokerage trade import.

Provides async access to Questrade's read-only account API for importing
trade executions into the SignalForge journal. Uses OAuth2 with single-use
rotating refresh tokens stored in Supabase.

Supports two connection methods:
  1. **OAuth Authorization Code** — user signs in via Questrade's login page
     (requires ``QUESTRADE_CLIENT_ID`` env var).
  2. **Manual refresh token** — dev/fallback: paste a token from the API hub.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import UTC
from typing import Any

import httpx

from database.connection import get_db

logger = logging.getLogger(__name__)

PRODUCTION_AUTHORIZE_URL = "https://login.questrade.com/oauth2/authorize"
PRACTICE_AUTHORIZE_URL = "https://practicelogin.questrade.com/oauth2/authorize"
PRODUCTION_TOKEN_URL = "https://login.questrade.com/oauth2/token"
PRACTICE_TOKEN_URL = "https://practicelogin.questrade.com/oauth2/token"

QUESTRADE_CLIENT_ID = os.environ.get("QUESTRADE_CLIENT_ID", "")

# Questrade suffix → TradingView exchange prefix
_QT_SUFFIX_TO_TV: dict[str, str] = {
    ".TO": "TSX",
    ".V": "TSXV",
    ".L": "LSE",
    ".AX": "ASX",
    ".HK": "HKEX",
    ".T": "TSE",
    ".DE": "XETR",
    ".PA": "EURONEXT",
    ".AS": "EURONEXT",
    ".MI": "MIL",
    ".SW": "SIX",
    ".SA": "BMFBOVESPA",
    ".NS": "NSE",
    ".BO": "BSE",
    ".SS": "SSE",
    ".SZ": "SZSE",
}

# Questrade listingExchange value → TradingView prefix
_QT_EXCHANGE_TO_TV: dict[str, str] = {
    "TSX": "TSX",
    "TSXV": "TSXV",
    "CNSX": "CSE",
    "NYSE": "NYSE",
    "NASDAQ": "NASDAQ",
    "NYSEAM": "AMEX",
    "ARCA": "AMEX",
}


class QuestradeService:
    """Async client for Questrade's read-only account and execution APIs.

    Manages OAuth2 token lifecycle (single-use refresh tokens) and provides
    methods for fetching accounts, positions, and trade executions.
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=30.0)
        self._refresh_lock = asyncio.Lock()

    @staticmethod
    def get_authorize_url(
        redirect_uri: str,
        *,
        is_practice: bool = False,
        state: str = "",
    ) -> str | None:
        """Build the Questrade OAuth authorize URL for the Authorization Code flow.

        Args:
            redirect_uri: Where Questrade redirects after user authorizes.
            is_practice: Whether to use the practice login portal.
            state: CSRF state token to round-trip through the OAuth flow.

        Returns:
            Full authorize URL, or ``None`` if ``QUESTRADE_CLIENT_ID`` is not set.
        """
        if not QUESTRADE_CLIENT_ID:
            return None

        base = PRACTICE_AUTHORIZE_URL if is_practice else PRODUCTION_AUTHORIZE_URL
        params = httpx.QueryParams(
            {
                "client_id": QUESTRADE_CLIENT_ID,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                **({"state": state} if state else {}),
            }
        )
        return f"{base}?{params}"

    async def connect_with_code(
        self,
        user_id: str,
        code: str,
        redirect_uri: str,
        *,
        is_practice: bool = False,
    ) -> dict[str, Any]:
        """Exchange an OAuth authorization code for tokens and persist the connection.

        Args:
            user_id: Authenticated user ID.
            code: Authorization code from the Questrade OAuth callback.
            redirect_uri: Must match the redirect_uri used in the authorize request.
            is_practice: Whether to use the practice login endpoint.

        Returns:
            Dict with ``connected`` flag and ``accounts`` list.

        Raises:
            httpx.HTTPStatusError: If the token exchange fails.
        """
        token_data = await self._exchange_auth_code(code, redirect_uri, is_practice)
        return await self._persist_and_fetch(user_id, token_data, is_practice=is_practice)

    async def connect(
        self,
        user_id: str,
        refresh_token: str,
        *,
        is_practice: bool = False,
    ) -> dict[str, Any]:
        """Exchange a manual refresh token and persist the connection (fallback).

        Args:
            user_id: Authenticated user ID.
            refresh_token: Initial Questrade refresh token from the app hub.
            is_practice: Whether to use the practice login endpoint.

        Returns:
            Dict with ``connected`` flag and ``accounts`` list.

        Raises:
            httpx.HTTPStatusError: If the token exchange fails.
        """
        token_data = await self._exchange_token(refresh_token, is_practice)
        return await self._persist_and_fetch(user_id, token_data, is_practice=is_practice)

    async def _persist_and_fetch(
        self,
        user_id: str,
        token_data: dict[str, Any],
        *,
        is_practice: bool = False,
    ) -> dict[str, Any]:
        """Store tokens in the DB and return the connected accounts.

        Args:
            user_id: Authenticated user ID.
            token_data: Token response dict from Questrade.
            is_practice: Whether this is a practice connection.

        Returns:
            Dict with ``connected`` flag and ``accounts`` list.
        """
        client = await get_db()
        row = {
            "id": uuid.uuid4().hex,
            "user_id": user_id,
            "refresh_token": token_data["refresh_token"],
            "access_token": token_data["access_token"],
            "api_server": token_data["api_server"],
            "expires_at": _expires_at_iso(token_data["expires_in"]),
            "is_practice": is_practice,
        }

        existing = (
            await client.table("questrade_tokens")
            .select("id")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if existing and existing.data:
            await (
                client.table("questrade_tokens")
                .update({k: v for k, v in row.items() if k != "id"})
                .eq("user_id", user_id)
                .execute()
            )
        else:
            await client.table("questrade_tokens").insert(row).execute()

        accounts = await self._fetch_accounts(token_data["api_server"], token_data["access_token"])
        return {"connected": True, "accounts": accounts}

    async def disconnect(self, user_id: str) -> None:
        """Remove stored Questrade connection for a user.

        Args:
            user_id: Authenticated user ID.
        """
        client = await get_db()
        await client.table("questrade_tokens").delete().eq("user_id", user_id).execute()
        logger.info("Questrade disconnected for user %s", user_id)

    async def get_status(self, user_id: str) -> dict[str, Any] | None:
        """Return the current Questrade connection status.

        Args:
            user_id: Authenticated user ID.

        Returns:
            Status dict or ``None`` if not connected.
        """
        client = await get_db()
        resp = (
            await client.table("questrade_tokens")
            .select("account_id, account_type, is_practice, connected_at, updated_at")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if not resp or not resp.data:
            return None
        row = resp.data
        return {
            "connected": True,
            "account_id": row.get("account_id"),
            "account_type": row.get("account_type"),
            "is_practice": row.get("is_practice", False),
            "connected_at": row.get("connected_at"),
            "updated_at": row.get("updated_at"),
        }

    async def select_account(self, user_id: str, account_id: str, account_type: str) -> None:
        """Persist the user's selected Questrade account.

        Args:
            user_id: Authenticated user ID.
            account_id: Questrade account number.
            account_type: Account type string (e.g. "Margin", "TFSA").
        """
        client = await get_db()
        await (
            client.table("questrade_tokens")
            .update({"account_id": account_id, "account_type": account_type})
            .eq("user_id", user_id)
            .execute()
        )

    async def get_accounts(self, user_id: str) -> list[dict[str, Any]]:
        """Fetch the list of accounts from Questrade.

        Args:
            user_id: Authenticated user ID.

        Returns:
            List of account dicts from the Questrade API.
        """
        token = await self._ensure_valid_token(user_id)
        return await self._fetch_accounts(token["api_server"], token["access_token"])

    async def get_executions(
        self, user_id: str, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """Fetch trade executions for the selected account.

        Args:
            user_id: Authenticated user ID.
            start_date: ISO date string for range start (e.g. "2025-03-01T00:00:00-05:00").
            end_date: ISO date string for range end.

        Returns:
            List of execution dicts from the Questrade API.

        Raises:
            ValueError: If no account is selected.
        """
        token = await self._ensure_valid_token(user_id)
        account_id = token.get("account_id")
        if not account_id:
            raise ValueError("No Questrade account selected. Call select_account first.")

        data = await self._request(
            user_id,
            "GET",
            f"accounts/{account_id}/executions",
            params={"startTime": start_date, "endTime": end_date},
        )
        return data.get("executions", [])

    async def get_positions(self, user_id: str) -> list[dict[str, Any]]:
        """Fetch current positions for the selected account.

        Args:
            user_id: Authenticated user ID.

        Returns:
            List of position dicts from the Questrade API.

        Raises:
            ValueError: If no account is selected.
        """
        token = await self._ensure_valid_token(user_id)
        account_id = token.get("account_id")
        if not account_id:
            raise ValueError("No Questrade account selected. Call select_account first.")

        data = await self._request(user_id, "GET", f"accounts/{account_id}/positions")
        return data.get("positions", [])

    async def verify_connection(self, user_id: str) -> bool:
        """Check connectivity by hitting the Questrade /v1/time endpoint.

        Args:
            user_id: Authenticated user ID.

        Returns:
            ``True`` if the API responds successfully.
        """
        try:
            await self._request(user_id, "GET", "time")
            return True
        except Exception:
            logger.warning("Questrade connection verification failed for user %s", user_id)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_token(self, user_id: str) -> dict[str, Any]:
        """Load the stored token row from the database.

        Args:
            user_id: Authenticated user ID.

        Returns:
            The token row dict.

        Raises:
            ValueError: If no token is stored for this user.
        """
        client = await get_db()
        resp = (
            await client.table("questrade_tokens")
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if not resp or not resp.data:
            raise ValueError(f"No Questrade connection found for user {user_id}")
        return resp.data

    async def _exchange_auth_code(
        self, code: str, redirect_uri: str, is_practice: bool
    ) -> dict[str, Any]:
        """Exchange an OAuth authorization code for an access/refresh token pair.

        Args:
            code: Authorization code from the Questrade callback.
            redirect_uri: Must match the authorize request exactly.
            is_practice: Whether to use the practice endpoint.

        Returns:
            Dict with ``access_token``, ``refresh_token``, ``api_server``,
            and ``expires_in``.

        Raises:
            httpx.HTTPStatusError: If the exchange request fails.
        """
        url = PRACTICE_TOKEN_URL if is_practice else PRODUCTION_TOKEN_URL
        resp = await self._http.post(
            url,
            params={
                "client_id": QUESTRADE_CLIENT_ID,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return self._parse_token_response(resp.json())

    async def _exchange_token(self, refresh_token: str, is_practice: bool) -> dict[str, Any]:
        """Exchange a refresh token for a new access/refresh pair.

        Args:
            refresh_token: The single-use Questrade refresh token.
            is_practice: Whether to use the practice endpoint.

        Returns:
            Dict with ``access_token``, ``refresh_token``, ``api_server``,
            and ``expires_in``.

        Raises:
            httpx.HTTPStatusError: If the exchange request fails.
        """
        url = PRACTICE_TOKEN_URL if is_practice else PRODUCTION_TOKEN_URL
        resp = await self._http.get(
            url,
            params={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        resp.raise_for_status()
        return self._parse_token_response(resp.json())

    @staticmethod
    def _parse_token_response(data: dict[str, Any]) -> dict[str, Any]:
        """Extract the standard token fields from a Questrade token response.

        Args:
            data: Raw JSON response from Questrade's token endpoint.

        Returns:
            Normalized dict with ``access_token``, ``refresh_token``,
            ``api_server``, and ``expires_in``.
        """
        return {
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "api_server": data["api_server"],
            "expires_in": data["expires_in"],
        }

    async def _ensure_valid_token(self, user_id: str) -> dict[str, Any]:
        """Return a valid token, refreshing if expired.

        Uses an asyncio.Lock to prevent concurrent refresh races. If the
        token expires within 60 seconds, it is proactively refreshed.

        Args:
            user_id: Authenticated user ID.

        Returns:
            The token row dict with a valid ``access_token`` and ``api_server``.
        """
        async with self._refresh_lock:
            token_row = await self._load_token(user_id)

            expires_at = token_row.get("expires_at", "")
            if expires_at and not _is_expired(expires_at):
                return token_row

            logger.info("Refreshing Questrade token for user %s", user_id)
            new_data = await self._exchange_token(
                token_row["refresh_token"],
                token_row.get("is_practice", False),
            )

            client = await get_db()
            await (
                client.table("questrade_tokens")
                .update(
                    {
                        "refresh_token": new_data["refresh_token"],
                        "access_token": new_data["access_token"],
                        "api_server": new_data["api_server"],
                        "expires_at": _expires_at_iso(new_data["expires_in"]),
                        "updated_at": "now()",
                    }
                )
                .eq("user_id", user_id)
                .execute()
            )

            token_row.update(
                {
                    "refresh_token": new_data["refresh_token"],
                    "access_token": new_data["access_token"],
                    "api_server": new_data["api_server"],
                }
            )
            return token_row

    async def _request(
        self,
        user_id: str,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated Questrade API request with auto-refresh.

        Args:
            user_id: Authenticated user ID.
            method: HTTP method ("GET", "POST", etc.).
            endpoint: API path relative to ``/v1/`` (e.g. ``"accounts"``).
            params: Optional query parameters.

        Returns:
            Parsed JSON response body.

        Raises:
            httpx.HTTPStatusError: On non-retryable HTTP errors.
        """
        token = await self._ensure_valid_token(user_id)
        url = f"{token['api_server']}v1/{endpoint}"
        headers = {"Authorization": f"Bearer {token['access_token']}"}

        resp = await self._http.request(method, url, headers=headers, params=params)

        if resp.status_code == 401:
            logger.info("Got 401, forcing token refresh for user %s", user_id)
            token = await self._force_refresh(user_id)
            headers = {"Authorization": f"Bearer {token['access_token']}"}
            url = f"{token['api_server']}v1/{endpoint}"
            resp = await self._http.request(method, url, headers=headers, params=params)

        resp.raise_for_status()
        return resp.json()

    async def _force_refresh(self, user_id: str) -> dict[str, Any]:
        """Invalidate the current token's expiry and refresh immediately.

        Args:
            user_id: Authenticated user ID.

        Returns:
            Updated token row dict.
        """
        client = await get_db()
        await (
            client.table("questrade_tokens")
            .update({"expires_at": "2000-01-01T00:00:00Z"})
            .eq("user_id", user_id)
            .execute()
        )
        return await self._ensure_valid_token(user_id)

    async def _fetch_accounts(self, api_server: str, access_token: str) -> list[dict[str, Any]]:
        """Fetch accounts directly using provided credentials (no DB lookup).

        Args:
            api_server: Questrade API server URL.
            access_token: Valid bearer token.

        Returns:
            List of account dicts.
        """
        url = f"{api_server}v1/accounts"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = await self._http.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("accounts", [])

    @staticmethod
    def map_symbol_to_tradingview(qt_symbol: str, listing_exchange: str = "") -> str:
        """Convert a Questrade symbol to TradingView format.

        Tries suffix-based mapping first (e.g. ``ENB.TO`` → ``TSX:ENB``),
        then falls back to listingExchange lookup, then returns the bare
        symbol for US equities.

        Args:
            qt_symbol: Symbol as returned by Questrade (e.g. "ENB.TO", "AAPL").
            listing_exchange: Optional listingExchange value from Questrade.

        Returns:
            TradingView-formatted ticker string (e.g. "TSX:ENB", "NASDAQ:AAPL").
        """
        for suffix, prefix in _QT_SUFFIX_TO_TV.items():
            if qt_symbol.endswith(suffix):
                bare = qt_symbol[: -len(suffix)]
                return f"{prefix}:{bare}"

        if listing_exchange:
            tv_prefix = _QT_EXCHANGE_TO_TV.get(listing_exchange)
            if tv_prefix:
                return f"{tv_prefix}:{qt_symbol}"

        return qt_symbol


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _expires_at_iso(expires_in: int) -> str:
    """Compute an ISO 8601 expiry timestamp from a TTL in seconds.

    Subtracts a 60-second buffer so tokens are refreshed proactively.

    Args:
        expires_in: Token TTL in seconds from the OAuth response.

    Returns:
        ISO 8601 timestamp string.
    """
    from datetime import datetime

    ts = time.time() + expires_in - 60
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def _is_expired(expires_at_str: str) -> bool:
    """Check whether an ISO 8601 timestamp is in the past.

    Args:
        expires_at_str: ISO 8601 timestamp string.

    Returns:
        ``True`` if the timestamp is in the past.
    """
    from datetime import datetime

    try:
        expires = datetime.fromisoformat(expires_at_str)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return datetime.now(tz=UTC) >= expires
    except ValueError, TypeError:
        return True
