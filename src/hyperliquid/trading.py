from __future__ import annotations

import logging
from typing import Any

from hyperliquid.client import HyperliquidClient
from hyperliquid.symbol import HyperliquidSymbol

logger = logging.getLogger(__name__)


def _round_price(price: float, sz_decimals: int) -> str:
    """
    Rounds a price to Hyperliquid's precision rules for perpetuals:
    at most 5 significant figures, AND at most (6 - szDecimals)
    decimal places — whichever is stricter. Prices that violate either
    rule are rejected by the exchange with "Order has invalid price."

    Example: BTC (szDecimals=5) at mid=64966.5 with 5% slippage gives
    a raw price of 68214.825 (8 significant figures) — invalid.
    Rounding to 5 sig figs gives 68215, then to (6-5)=1 decimal place
    (already satisfied) gives a valid "68215".
    """
    if price <= 0:
        return "0"

    # Step 1: round to 5 significant figures.
    sig_fig_price = float(f"{price:.5g}")

    # Step 2: cap decimal places at (6 - szDecimals), never negative.
    max_decimals = max(6 - sz_decimals, 0)
    rounded = round(sig_fig_price, max_decimals)

    if max_decimals == 0:
        return str(int(rounded))
    return f"{rounded:.{max_decimals}f}".rstrip("0").rstrip(".")


class HyperliquidTrading:
    """
    Order execution and management on Hyperliquid.

    All methods send signed requests to /exchange.
    Requires a HyperliquidClient with auth attached.

    Args:
        client:     HyperliquidClient with auth — raises if auth is None
        symbol_map: Loaded HyperliquidSymbol for asset ID resolution

    Important notes from docs:
        - Minimum order value: $10
        - Prices must respect tick size for each asset
        - Sizes must respect lot size (szDecimals) for each asset
        - Always test on testnet first
    """

    def __init__(
        self,
        client: HyperliquidClient,
        symbol_map: HyperliquidSymbol,
    ) -> None:
        if client.auth is None:
            raise ValueError(
                "HyperliquidTrading requires a client with auth. "
                "Pass auth=HyperliquidAuth(...) when creating HyperliquidClient."
            )
        self._client = client
        self._symbol_map = symbol_map

    # ──────────────────────────────────────────────────────────────
    # ORDER PLACEMENT
    # ──────────────────────────────────────────────────────────────

    def place_limit_order(
        self,
        symbol: str,
        is_buy: bool,
        price: str,
        size: str,
        reduce_only: bool = False,
        tif: str = "Gtc",
        cloid: str | None = None,
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Places a limit order.

        Args:
            symbol:       e.g. "BTC", "ETH"
            is_buy:       True for buy/long, False for sell/short
            price:        Limit price as string e.g. "50000.0"
            size:         Order size as string e.g. "0.001"
            reduce_only:  True to only reduce an existing position
            tif:          Time in force — "Gtc" | "Ioc" | "Alo"
                          Gtc = Good Till Canceled (rests on book)
                          Ioc = Immediate Or Cancel (unfilled part canceled)
                          Alo = Add Liquidity Only / Post Only (canceled if would match)
            cloid:        Optional client order ID (128-bit hex string)
                          e.g. "0x1234567890abcdef1234567890abcdef"
            vault_address: Optional vault/subaccount address

        Returns:
            Exchange response dict with order status.
            Check response["response"]["data"]["statuses"][0] for result:
              {"resting": {"oid": 123}}   → order is on the book
              {"filled": {"oid": 123, "totalSz": "0.001", "avgPx": "50000"}} → filled
              {"error": "..."} → rejected

        Raises:
            SymbolNotFoundError: if symbol not in universe
        """
        asset_id = self._symbol_map.get_perp_asset_id(symbol)

        order: dict[str, Any] = {
            "a": asset_id,
            "b": is_buy,
            "p": price,
            "s": size,
            "r": reduce_only,
            "t": {"limit": {"tif": tif}},
        }
        if cloid is not None:
            order["c"] = cloid

        action = {
            "type": "order",
            "orders": [order],
            "grouping": "na",
        }

        logger.debug(
            "Placing limit order: %s %s %s @ %s (tif=%s)",
            "BUY" if is_buy else "SELL",
            size,
            symbol,
            price,
            tif,
        )
        return self._client.exchange(action, vault_address=vault_address)

    def place_market_order(
        self,
        symbol: str,
        is_buy: bool,
        size: str,
        reduce_only: bool = False,
        cloid: str | None = None,
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Places a market order using IOC with a slippage-adjusted price.

        Hyperliquid has no dedicated "market" order type. Market orders
        are simulated using IOC limit orders with a price set far enough
        from the market that they will always fill immediately:
          - Buy:  price = mid * 1.05  (5% above mid — will always cross)
          - Sell: price = mid * 0.95  (5% below mid — will always cross)

        The unfilled portion is automatically canceled (IOC behavior).

        Args:
            symbol:      e.g. "BTC"
            is_buy:      True for buy, False for sell
            size:        Order size as string e.g. "0.001"
            reduce_only: True to only reduce an existing position
            cloid:       Optional client order ID
            vault_address: Optional vault/subaccount address

        Returns:
            Exchange response dict. A filled order looks like:
            {"filled": {"oid": 123, "totalSz": "0.001", "avgPx": "50000"}}
        """
        asset_id = self._symbol_map.get_perp_asset_id(symbol)

        # Get current mid price for slippage calculation
        all_mids: dict[str, str] = self._client.info({"type": "allMids"})
        mid = float(all_mids.get(symbol, "0"))
        if mid == 0:
            raise ValueError(f"Could not get mid price for {symbol}")

        # 5% slippage tolerance
        slippage = 0.05
        raw_price = mid * (1 + slippage) if is_buy else mid * (1 - slippage)
        sz_decimals = self._symbol_map.get_sz_decimals(symbol)
        price = _round_price(raw_price, sz_decimals)

        order: dict[str, Any] = {
            "a": asset_id,
            "b": is_buy,
            "p": price,
            "s": size,
            "r": reduce_only,
            "t": {"limit": {"tif": "Ioc"}},  # IOC = market behavior
        }
        if cloid is not None:
            order["c"] = cloid

        action = {
            "type": "order",
            "orders": [order],
            "grouping": "na",
        }

        logger.debug(
            "Placing market order: %s %s %s (slippage price=%s)",
            "BUY" if is_buy else "SELL",
            size,
            symbol,
            price,
        )
        return self._client.exchange(action, vault_address=vault_address)

    def place_batch_orders(
        self,
        orders: list[dict[str, Any]],
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Places multiple orders in a single request.

        More efficient than individual calls — counts as 1 request
        for IP rate limiting (but n requests for address-based limits).

        Args:
            orders: List of order dicts, each with keys:
                    symbol, is_buy, price, size, reduce_only, tif, cloid
            vault_address: Optional vault/subaccount address

        Returns:
            Exchange response with statuses list (one per order).
        """
        order_list = []
        for o in orders:
            asset_id = self._symbol_map.get_perp_asset_id(o["symbol"])
            order: dict[str, Any] = {
                "a": asset_id,
                "b": o["is_buy"],
                "p": o["price"],
                "s": o["size"],
                "r": o.get("reduce_only", False),
                "t": {"limit": {"tif": o.get("tif", "Gtc")}},
            }
            if "cloid" in o and o["cloid"]:
                order["c"] = o["cloid"]
            order_list.append(order)

        action = {
            "type": "order",
            "orders": order_list,
            "grouping": "na",
        }

        logger.debug("Placing batch of %d orders", len(order_list))
        return self._client.exchange(action, vault_address=vault_address)

    # ──────────────────────────────────────────────────────────────
    # ORDER CANCELLATION
    # ──────────────────────────────────────────────────────────────

    def cancel_order(
        self,
        symbol: str,
        oid: int,
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Cancels an open order by order ID.

        Args:
            symbol: e.g. "BTC" — needed for asset ID
            oid:    Order ID integer (from place_limit_order response)
            vault_address: Optional vault/subaccount address

        Returns:
            Exchange response. Success looks like:
            {"status": "ok", "response": {"type": "cancel", "data": {"statuses": ["success"]}}}

            Error looks like:
            {"statuses": [{"error": "Order was never placed, already canceled, or filled."}]}
        """
        asset_id = self._symbol_map.get_perp_asset_id(symbol)

        action = {
            "type": "cancel",
            "cancels": [{"a": asset_id, "o": oid}],
        }

        logger.debug("Canceling order %d for %s", oid, symbol)
        return self._client.exchange(action, vault_address=vault_address)

    def cancel_order_by_cloid(
        self,
        symbol: str,
        cloid: str,
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Cancels an order by client order ID (cloid).

        Args:
            symbol: e.g. "BTC"
            cloid:  Client order ID string you assigned when placing the order
            vault_address: Optional vault/subaccount address

        Returns:
            Exchange response dict.
        """
        asset_id = self._symbol_map.get_perp_asset_id(symbol)

        action = {
            "type": "cancelByCloid",
            "cancels": [{"asset": asset_id, "cloid": cloid}],
        }

        logger.debug("Canceling order by cloid %s for %s", cloid, symbol)
        return self._client.exchange(action, vault_address=vault_address)

    def cancel_all_orders(
        self,
        symbol: str | None = None,
        vault_address: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Cancels all open orders, optionally filtered by symbol.

        Fetches open orders from /info first, then cancels each one.
        Note: this is multiple round trips — one info call + one cancel
        per symbol with open orders.

        Args:
            symbol: If provided, only cancel orders for this symbol.
                    If None, cancel all open orders.
            vault_address: Optional vault/subaccount address

        Returns:
            List of exchange responses, one per cancel call.
        """
        # Get open orders
        account_address = self._client.auth.account_address  # type: ignore
        raw_orders = self._client.info(
            {
                "type": "openOrders",
                "user": account_address,
            }
        )

        if symbol is not None:
            raw_orders = [o for o in raw_orders if o.get("coin") == symbol]

        if not raw_orders:
            logger.debug("No open orders to cancel")
            return []

        # Group by asset and cancel in batches
        from collections import defaultdict

        by_asset: dict[int, list[int]] = defaultdict(list)
        for o in raw_orders:
            coin = o["coin"]
            try:
                asset_id = self._symbol_map.get_perp_asset_id(coin)
                by_asset[asset_id].append(o["oid"])
            except Exception:
                continue

        results = []
        for asset_id, oids in by_asset.items():
            action = {
                "type": "cancel",
                "cancels": [{"a": asset_id, "o": oid} for oid in oids],
            }
            logger.debug("Canceling %d orders for asset %d", len(oids), asset_id)
            result = self._client.exchange(action, vault_address=vault_address)
            results.append(result)

        return results

    # ──────────────────────────────────────────────────────────────
    # ORDER MODIFICATION
    # ──────────────────────────────────────────────────────────────

    def modify_order(
        self,
        symbol: str,
        oid: int,
        price: str,
        size: str,
        is_buy: bool,
        reduce_only: bool = False,
        tif: str = "Gtc",
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Modifies an existing open order.

        Args:
            symbol:   e.g. "BTC"
            oid:      Order ID to modify
            price:    New limit price as string
            size:     New size as string
            is_buy:   True for buy, False for sell
            reduce_only: True to reduce only
            tif:      New time in force
            vault_address: Optional vault/subaccount address

        Returns:
            Exchange response dict.
        """
        asset_id = self._symbol_map.get_perp_asset_id(symbol)

        action = {
            "type": "modify",
            "oid": oid,
            "order": {
                "a": asset_id,
                "b": is_buy,
                "p": price,
                "s": size,
                "r": reduce_only,
                "t": {"limit": {"tif": tif}},
            },
        }

        logger.debug(
            "Modifying order %d for %s → price=%s size=%s", oid, symbol, price, size
        )
        return self._client.exchange(action, vault_address=vault_address)

    # ──────────────────────────────────────────────────────────────
    # LEVERAGE
    # ──────────────────────────────────────────────────────────────

    def set_leverage(
        self,
        symbol: str,
        leverage: int,
        is_cross: bool = True,
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Sets leverage for a symbol.

        Args:
            symbol:    e.g. "BTC"
            leverage:  Integer leverage value e.g. 10 for 10x
                       Must be within the asset's max leverage
            is_cross:  True for cross margin, False for isolated margin
            vault_address: Optional vault/subaccount address

        Returns:
            Exchange response. Success: {"status": "ok", "response": {"type": "default"}}

        Note:
            Max leverage varies by asset. Check AssetMeta.maxLeverage
            from the meta response. Exceeding it will be rejected.
        """
        asset_id = self._symbol_map.get_perp_asset_id(symbol)

        action = {
            "type": "updateLeverage",
            "asset": asset_id,
            "isCross": is_cross,
            "leverage": leverage,
        }

        logger.debug(
            "Setting leverage for %s: %dx (%s)",
            symbol,
            leverage,
            "cross" if is_cross else "isolated",
        )
        return self._client.exchange(action, vault_address=vault_address)
