from __future__ import annotations

import logging
from typing import Any

from hyperliquid.client import HyperliquidClient
from hyperliquid.responses import L2Book, Meta, SpotMeta
from hyperliquid.symbol import HyperliquidSymbol

logger = logging.getLogger(__name__)


class HyperliquidMarket:
    """
    Public market data — prices, order books, trade history.
    No authentication required for any method in this class.

    Args:
        client:     HyperliquidClient instance (auth not needed)
        symbol_map: Loaded HyperliquidSymbol instance for coin lookups
    """

    def __init__(
        self,
        client: HyperliquidClient,
        symbol_map: HyperliquidSymbol,
    ) -> None:
        self._client = client
        self._symbol_map = symbol_map

    def get_price(self, symbol: str) -> str:
        """
        Returns the current mid price for a symbol as a string.

        Fetches all mid prices and filters to the requested symbol.
        Mid price = (best bid + best ask) / 2

        Args:
            symbol: e.g. "BTC", "ETH", "SOL"

        Returns:
            Mid price as string e.g. "50123.5"

        Raises:
            SymbolNotFoundError: if symbol not in universe
            KeyError: if symbol not in allMids response
        """
        # Validate symbol exists in universe first
        self._symbol_map.get_perp_asset_id(symbol)

        raw: dict[str, str] = self._client.info({"type": "allMids"})
        price = raw.get(symbol)
        if price is None:
            raise KeyError(f"Symbol '{symbol}' not found in allMids response.")
        logger.debug("Price for %s: %s", symbol, price)
        return price

    def get_all_mids(self) -> dict[str, str]:
        """
        Returns mid prices for all assets as a dict.

        Returns:
            {"BTC": "50123.5", "ETH": "3001.2", ...}
        """
        raw: dict[str, str] = self._client.info({"type": "allMids"})
        logger.debug("Fetched %d mid prices", len(raw))
        return raw

    def get_orderbook(self, symbol: str, depth: int = 20) -> L2Book:
        """
        Returns the L2 order book for a symbol.

        levels[0] = bids (sorted descending by price — highest bid first)
        levels[1] = asks (sorted ascending by price — lowest ask first)

        Args:
            symbol: e.g. "BTC"
            depth:  number of price levels to return (default 20)

        Returns:
            L2Book Pydantic model

        Raises:
            SymbolNotFoundError: if symbol not in universe
        """
        self._symbol_map.get_perp_asset_id(symbol)
        raw = self._client.info(
            {
                "type": "l2Book",
                "coin": symbol,
                "nSigFigs": depth,
            }
        )
        logger.debug(
            "Orderbook for %s: %d bid levels, %d ask levels",
            symbol,
            len(raw.get("levels", [[]])[0]),
            len(raw.get("levels", [[], []])[1]),
        )
        return L2Book(**raw)

    def get_trades(self, symbol: str) -> list[dict[str, Any]]:
        """
        Returns recent trades for a symbol.

        Args:
            symbol: e.g. "BTC"

        Returns:
            List of recent trade dicts from the API.
            Each trade has: coin, side, px, sz, time, hash
        """
        self._symbol_map.get_perp_asset_id(symbol)
        raw = self._client.info(
            {
                "type": "recentTrades",
                "coin": symbol,
            }
        )
        logger.debug("Fetched %d recent trades for %s", len(raw), symbol)
        return raw

    def get_funding_rate(self, symbol: str) -> dict[str, Any]:
        """
        Returns current funding rate info for a symbol.

        Returns a dict with funding, openInterest, premium, and oracle price.
        """
        self._symbol_map.get_perp_asset_id(symbol)
        raw = self._client.info(
            {
                "type": "metaAndAssetCtxs",
            }
        )
        # raw is [meta, [assetCtx1, assetCtx2, ...]]
        asset_id = self._symbol_map.get_perp_asset_id(symbol)
        asset_ctxs = raw[1] if len(raw) > 1 else []

        if asset_id >= len(asset_ctxs):
            raise KeyError(f"No asset context for {symbol} (id={asset_id})")

        ctx = asset_ctxs[asset_id]
        logger.debug("Funding rate for %s: %s", symbol, ctx.get("funding"))
        return {
            "symbol": symbol,
            "funding": ctx.get("funding"),
            "openInterest": ctx.get("openInterest"),
            "premium": ctx.get("premium"),
            "oraclePx": ctx.get("oraclePx"),
            "markPx": ctx.get("markPx"),
        }

    def get_meta(self) -> Meta:
        """Returns the full perpetuals universe metadata."""
        raw = self._client.info({"type": "meta"})
        return Meta(**raw)

    def get_spot_meta(self) -> SpotMeta:
        """Returns the full spot universe metadata."""
        raw = self._client.info({"type": "spotMeta"})
        return SpotMeta(**raw)
