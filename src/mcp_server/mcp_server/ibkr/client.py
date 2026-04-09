"""IBKR connection manager with lazy connect and auto-reconnect."""

from __future__ import annotations

import asyncio
import logging

from ib_async import IB

from mcp_server.config import settings

logger = logging.getLogger(__name__)


class IBKRClient:
    """Singleton wrapper around ib_async.IB with lazy connection management.

    Connects on first use and automatically reconnects if the connection drops.
    Paper vs live is controlled entirely by the port setting.

    Attributes:
        _ib: The underlying ib_async IB instance.
    """

    def __init__(self) -> None:
        self._ib = IB()
        self._connect_lock = asyncio.Lock()

    async def ensure_connected(self) -> IB:
        """Return a connected IB instance, reconnecting if needed.

        Returns:
            The connected IB instance.

        Raises:
            ConnectionError: If connection to TWS/Gateway fails.
        """
        if self._ib.isConnected():
            return self._ib

        async with self._connect_lock:
            if self._ib.isConnected():
                return self._ib

            mode = "paper" if settings.ibkr_paper else "LIVE"
            logger.info(
                "Connecting to IBKR %s at %s:%s (clientId=%s)",
                mode,
                settings.ibkr_host,
                settings.ibkr_port,
                settings.ibkr_client_id,
            )

            try:
                await self._ib.connectAsync(
                    host=settings.ibkr_host,
                    port=settings.ibkr_port,
                    clientId=settings.ibkr_client_id,
                    timeout=10,
                    readonly=False,
                )
            except Exception as exc:
                msg = (
                    f"Failed to connect to IBKR at {settings.ibkr_host}:{settings.ibkr_port}. "
                    f"Is TWS/Gateway running? Error: {exc}"
                )
                logger.error(msg)
                raise ConnectionError(msg) from exc

            logger.info("Connected to IBKR %s account", mode)
            return self._ib

    def disconnect(self) -> None:
        """Disconnect from IBKR if connected."""
        if self._ib.isConnected():
            self._ib.disconnect()
            logger.info("Disconnected from IBKR")


_client: IBKRClient | None = None


def get_ibkr_client() -> IBKRClient:
    """Get or create the singleton IBKR client.

    Returns:
        The shared IBKRClient instance.
    """
    global _client
    if _client is None:
        _client = IBKRClient()
    return _client
