from __future__ import annotations

import logging
from typing import Any

from hyperliquid.client import HyperliquidClient
from hyperliquid.responses import ClearinghouseState, Fill, OpenOrder

logger = logging.getLogger(__name__)


class HyperliquidAccount:
    """
    Reads account state from Hyperliquid.

    All methods are read-only — they use /info (no signing).
    Pass the master account address, NOT the API wallet address.
    Using the API wallet address returns empty results (common pitfall).

    Args:
        client:          HyperliquidClient instance
        account_address: Master wallet address (42-char hex, e.g. "0x...")
    """

    def __init__(
        self,
        client: HyperliquidClient,
        account_address: str,
    ) -> None:
        self._client = client
        self._account_address = account_address.lower()

    def get_balances(self) -> ClearinghouseState:
        """
        Returns full perp account state — positions, balances, margin.

        Includes:
        - marginSummary: accountValue, totalMarginUsed, totalNtlPos
        - withdrawable: amount available to withdraw
        - assetPositions: all open perpetual positions

        Returns:
            ClearinghouseState Pydantic model

        Note:
            Under unified account or portfolio margin, use
            get_spot_balances() instead for total account balance.
        """
        raw = self._client.info(
            {
                "type": "clearinghouseState",
                "user": self._account_address,
            }
        )
        state = ClearinghouseState(**raw)
        logger.debug(
            "Account value: %s, margin used: %s",
            state.marginSummary.accountValue,
            state.marginSummary.totalMarginUsed,
        )
        return state

    def get_spot_balances(self) -> dict[str, Any]:
        """
        Returns spot account balances.

        Returns:
            Raw dict with balances for each spot token.
        """
        raw = self._client.info(
            {
                "type": "spotClearinghouseState",
                "user": self._account_address,
            }
        )
        logger.debug("Fetched spot balances")
        return raw

    def get_positions(self) -> list[dict[str, Any]]:
        """
        Returns all open perpetual positions.

        Convenience wrapper around get_balances() that returns
        just the positions list, already filtered to non-zero sizes.

        Returns:
            List of position dicts with coin, size, entry price, PnL, etc.
        """
        state = self.get_balances()
        positions = [
            ap.position.model_dump()
            for ap in state.assetPositions
            if ap.position.szi != "0"
        ]
        logger.debug("Open positions: %d", len(positions))
        return positions

    def get_open_orders(self) -> list[OpenOrder]:
        """
        Returns all open orders for the account.

        Returns:
            List of OpenOrder Pydantic models.
            Empty list if no open orders.
        """
        raw = self._client.info(
            {
                "type": "openOrders",
                "user": self._account_address,
            }
        )
        orders = [OpenOrder(**o) for o in raw]
        logger.debug("Open orders: %d", len(orders))
        return orders

    def get_order_status(self, oid: int) -> dict[str, Any]:
        """
        Returns status of a specific order by order ID.

        Args:
            oid: Order ID integer returned when placing an order

        Returns:
            Dict with order details and status string.
            Status is one of: "open", "filled", "canceled",
            "triggered", "rejected", "marginCanceled"
        """
        raw = self._client.info(
            {
                "type": "orderStatus",
                "user": self._account_address,
                "oid": oid,
            }
        )
        logger.debug("Order %d status: %s", oid, raw.get("status"))
        return raw

    def get_fills(
        self,
        start_time: int | None = None,
    ) -> list[Fill]:
        """
        Returns trade history (filled orders) for the account.

        Args:
            start_time: Optional start timestamp in milliseconds.
                        Returns fills from this time onwards.
                        If None, returns most recent fills (up to 500).

        Returns:
            List of Fill Pydantic models, newest first.

        Note:
            API returns max 500 fills per call. For full history,
            paginate using the timestamp of the last returned fill
            as the next start_time.
        """
        payload: dict[str, Any] = {
            "type": "userFills",
            "user": self._account_address,
        }
        if start_time is not None:
            payload["startTime"] = start_time

        raw = self._client.info(payload)
        fills = [Fill(**f) for f in raw]
        logger.debug("Fetched %d fills", len(fills))
        return fills

    def get_funding_history(
        self,
        start_time: int,
        end_time: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Returns funding payments received/paid for the account.

        Args:
            start_time: Start timestamp in milliseconds (required)
            end_time:   End timestamp in milliseconds (optional)

        Returns:
            List of funding payment dicts.
        """
        payload: dict[str, Any] = {
            "type": "userFunding",
            "user": self._account_address,
            "startTime": start_time,
        }
        if end_time is not None:
            payload["endTime"] = end_time

        raw = self._client.info(payload)
        logger.debug("Fetched %d funding records", len(raw))
        return raw
