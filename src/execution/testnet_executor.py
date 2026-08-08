from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from core.config import settings
from hyperliquid.account import HyperliquidAccount
from hyperliquid.client import TESTNET_URL, HyperliquidClient
from hyperliquid.market import HyperliquidMarket
from hyperliquid.symbol import HyperliquidSymbol
from hyperliquid.trading import HyperliquidTrading

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# EXCEPTIONS
# ──────────────────────────────────────────────────────────────


class TestnetSafetyError(Exception):
    """
    Raised when a safety precondition for REAL testnet execution is not
    met. Always raised BEFORE any order can possibly be placed — every
    check lives in TestnetExecutor.__init__, so a TestnetExecutor
    object simply cannot exist unless every guard passes.
    """


class TestnetExecutionError(Exception):
    """
    Raised when a real testnet order does not reach a safe, expected
    state (rejected by the exchange, or the account is left in a
    surprising state after submission).
    """


# ──────────────────────────────────────────────────────────────
# RESULT TYPES
# ──────────────────────────────────────────────────────────────


@dataclass
class FillResult:
    """
    Outcome of waiting for a REAL testnet order to reach a terminal
    state.

    status is one of: "filled", "rejected", "canceled", "marginCanceled",
    "timeout" (the poll loop gave up — the order may still be open).
    """

    oid: int
    side: str  # "BUY" | "SELL"
    status: str
    filled_size: float = 0.0
    avg_price: float = 0.0


# ──────────────────────────────────────────────────────────────
# EXECUTOR
# ──────────────────────────────────────────────────────────────


class TestnetExecutor:
    """
    Executes REAL orders on Hyperliquid TESTNET using the existing
    HyperliquidTrading / HyperliquidAccount / HyperliquidMarket
    infrastructure.

    This is NOT paper trading. Every order placed through this class is
    a real exchange order against your real testnet account — it will
    show up in Hyperliquid's Open Orders / Order History / Trade
    History / Positions. It is entirely separate from
    Backtester / strategy_runner.paper_trade(), which only ever
    simulate fills and never touch this class.

    Safety — every check below runs in __init__, before any order can
    possibly be placed. Constructing a TestnetExecutor is itself proof
    all three guards passed:
        1. settings.is_mainnet must be False.
        2. client.base_url must be the Hyperliquid TESTNET endpoint —
           not just "not mainnet"; it must match exactly.
        3. settings.enable_testnet_live_execution must be True — the
           dedicated opt-in flag, off by default, so this can never
           trigger during normal backtesting/paper-trading use.

    Args:
        client:     HyperliquidClient with auth attached, pointed at testnet.
        symbol_map: Loaded HyperliquidSymbol.
        symbol:     Asset to trade, e.g. "BTC".
    """

    def __init__(
        self,
        client: HyperliquidClient,
        symbol_map: HyperliquidSymbol,
        symbol: str = "BTC",
    ) -> None:
        self._assert_safe_environment(client)

        if client.auth is None:
            raise TestnetSafetyError(
                "HyperliquidClient has no auth — TestnetExecutor requires a "
                "client built with auth=HyperliquidAuth(...)."
            )

        self.client = client
        self.symbol_map = symbol_map
        self.symbol = symbol
        self.trading = HyperliquidTrading(client=client, symbol_map=symbol_map)
        self.market = HyperliquidMarket(client=client, symbol_map=symbol_map)
        self.account = HyperliquidAccount(
            client=client,
            account_address=client.auth.account_address,
        )

        logger.warning(
            "TestnetExecutor constructed for %s — REAL TESTNET orders are "
            "now possible. base_url=%s",
            symbol,
            client.base_url,
        )

    @staticmethod
    def _assert_safe_environment(client: HyperliquidClient) -> None:
        """
        Hard-fails construction if any safety precondition isn't met.
        Never softens, warns-and-continues, or auto-corrects — refusing
        to construct is the only acceptable response to a failed check.
        """
        if settings.is_mainnet:
            raise TestnetSafetyError(
                "IS_MAINNET=True — refusing to construct TestnetExecutor. "
                "Real testnet execution requires IS_MAINNET=False."
            )
        if client.base_url != TESTNET_URL:
            raise TestnetSafetyError(
                f"Client base_url '{client.base_url}' is not the Hyperliquid "
                f"testnet endpoint ('{TESTNET_URL}'). Refusing to construct "
                f"TestnetExecutor — real orders must only ever be sent to "
                f"testnet."
            )
        if not settings.enable_testnet_live_execution:
            raise TestnetSafetyError(
                "ENABLE_TESTNET_LIVE_EXECUTION is not set to true. Real "
                "testnet order execution is disabled by default. Set "
                "ENABLE_TESTNET_LIVE_EXECUTION=true in .env to enable it. "
                "This flag never affects backtesting or paper trading."
            )

    # ──────────────────────────────────────────────────────────────
    # ACCOUNT / MARKET STATE
    # ──────────────────────────────────────────────────────────────

    def get_price(self) -> float:
        """Current mid price for self.symbol."""
        return float(self.market.get_price(self.symbol))

    def get_position_size(self) -> float:
        """
        Signed position size for self.symbol (positive=long,
        negative=short, 0.0 if flat).
        """
        for pos in self.account.get_positions():
            if pos.get("coin") == self.symbol:
                return float(pos["szi"])
        return 0.0

    def has_open_orders(self) -> bool:
        """True if there is already an open order for self.symbol."""
        return any(o.coin == self.symbol for o in self.account.get_open_orders())

    # ──────────────────────────────────────────────────────────────
    # ORDER SUBMISSION
    # ──────────────────────────────────────────────────────────────

    def submit_market_order(self, is_buy: bool, size: float) -> int:
        """
        Submits a REAL testnet market (IOC) order and returns its order ID.

        Args:
            is_buy: True for BUY, False for SELL.
            size:   Order size in base currency. Never scaled or
                    adjusted here — pass the exact size you want sent.

        Raises:
            TestnetExecutionError: if the exchange rejects the order or
                                    returns no order ID.
        """
        side = "BUY" if is_buy else "SELL"
        size_str = f"{size:.8f}".rstrip("0").rstrip(".")
        response = self.trading.place_market_order(
            self.symbol, is_buy=is_buy, size=size_str
        )
        oid = self._extract_oid(response)
        if oid is None:
            raise TestnetExecutionError(
                f"{side} order was not accepted by the exchange "
                f"(no order ID in response): {response}"
            )
        logger.info(
            "TESTNET ORDER SUBMITTED side=%s symbol=%s size=%s order_id=%s",
            side,
            self.symbol,
            size_str,
            oid,
        )
        return oid

    def wait_for_fill(
        self,
        oid: int,
        side: str,
        poll_interval: float | None = None,
        timeout: float | None = None,
    ) -> FillResult:
        """
        Polls order status via the account/info endpoint until the
        order reaches FILLED, a canceled/rejected state, or timeout.

        Args:
            oid:           Order ID from submit_market_order().
            side:           "BUY" or "SELL", for logging only.
            poll_interval:  Seconds between polls. Defaults to
                            settings.execution_poll_interval_seconds.
            timeout:        Max seconds to wait. Defaults to
                            settings.execution_poll_timeout_seconds.
        """
        poll_interval = (
            poll_interval
            if poll_interval is not None
            else settings.execution_poll_interval_seconds
        )
        timeout = timeout if timeout is not None else settings.execution_poll_timeout_seconds
        deadline = time.time() + timeout

        while True:
            raw = self.account.get_order_status(oid)
            status = raw.get("status", "")

            if status == "filled":
                order = raw.get("order", {}) or {}
                filled_size = float(order.get("sz", 0.0) or order.get("origSz", 0.0) or 0.0)
                avg_price = self._lookup_fill_price(oid)
                logger.info(
                    "TESTNET ORDER FILLED side=%s order_id=%s size=%s avg_price=%s",
                    side,
                    oid,
                    filled_size,
                    avg_price,
                )
                return FillResult(
                    oid=oid,
                    side=side,
                    status="filled",
                    filled_size=filled_size,
                    avg_price=avg_price,
                )

            if status in ("rejected", "canceled", "marginCanceled"):
                logger.error(
                    "TESTNET ORDER %s side=%s order_id=%s", status.upper(), side, oid
                )
                return FillResult(oid=oid, side=side, status=status)

            if time.time() >= deadline:
                logger.error(
                    "TESTNET ORDER TIMEOUT side=%s order_id=%s (waited %.1fs)",
                    side,
                    oid,
                    timeout,
                )
                return FillResult(oid=oid, side=side, status="timeout")

            time.sleep(poll_interval)

    @staticmethod
    def _extract_oid(response: dict) -> int | None:
        """Pulls the order ID out of a place_market_order() response, if present."""
        try:
            statuses = response["response"]["data"]["statuses"]
            first = statuses[0]
            if "filled" in first:
                return int(first["filled"]["oid"])
            if "resting" in first:
                return int(first["resting"]["oid"])
        except (KeyError, IndexError, TypeError):
            pass
        return None

    def _lookup_fill_price(self, oid: int) -> float:
        """
        Looks up the volume-weighted average fill price for an order
        from account fill history (userFills). orderStatus does not
        reliably include a fill price field (OrderStatusData has no
        avgPx), so this is the authoritative source — an order can also
        be filled across multiple partial fills, which this averages
        correctly.

        Returns 0.0 if no matching fill is found yet (e.g. fills
        haven't propagated to this endpoint the instant status flips
        to "filled") or if the lookup itself fails — callers should
        treat 0.0 as "unknown", not "filled at zero".
        """
        try:
            fills = [f for f in self.account.get_fills() if f.oid == oid]
        except Exception as e:
            logger.warning("Could not look up fill price for oid=%s: %s", oid, e)
            return 0.0
        if not fills:
            return 0.0
        total_size = sum(float(f.sz) for f in fills)
        if total_size == 0:
            return 0.0
        weighted = sum(float(f.px) * float(f.sz) for f in fills)
        return weighted / total_size

    # ──────────────────────────────────────────────────────────────
    # FULL BUY -> SELL SMOKE CYCLE
    # ──────────────────────────────────────────────────────────────

    def run_smoke_cycle(
        self, size: float | None = None
    ) -> tuple[FillResult, FillResult | None]:
        """
        Full BUY -> verify -> SELL -> verify lifecycle used by the
        dedicated smoke test (execution/smoke_test.py).

        Logs the complete lifecycle:
            SIGNAL/TEST -> BUY SUBMITTED -> BUY FILLED -> POSITION OPEN
            -> SELL SUBMITTED -> SELL FILLED -> POSITION CLOSED

        Safety:
            - Refuses to start if an open order already exists for
              this symbol (never places overlapping/duplicate orders).
            - Never submits a SELL if the BUY did not fill — returns
              (buy_result, None) in that case.
            - If the BUY fills but the SELL submission or fill fails,
              the remaining open position is clearly logged so it can
              be closed manually; the exception (if any) still
              propagates rather than being swallowed.

        Args:
            size: Order size in base currency. Defaults to
                  settings.position_size.

        Returns:
            (buy_result, sell_result). sell_result is None only when
            the BUY did not fill.

        Raises:
            TestnetExecutionError: if an open order already exists for
                this symbol, or if SELL submission fails outright after
                a successful BUY (position is left open — see log).
        """
        size = size if size is not None else settings.position_size

        if self.has_open_orders():
            raise TestnetExecutionError(
                f"An open order already exists for {self.symbol} — refusing "
                f"to start a new smoke-test cycle. Resolve it manually first."
            )

        logger.info(
            "SIGNAL/TEST — starting REAL TESTNET BUY->SELL smoke cycle, "
            "symbol=%s size=%s",
            self.symbol,
            size,
        )

        # BUY
        buy_oid = self.submit_market_order(is_buy=True, size=size)
        buy_result = self.wait_for_fill(buy_oid, side="BUY")

        if buy_result.status != "filled":
            logger.error(
                "BUY did not fill (status=%s) — aborting. SELL will NOT be "
                "submitted.",
                buy_result.status,
            )
            return buy_result, None

        position = self.get_position_size()
        logger.info("POSITION OPEN size=%s %s", position, self.symbol)

        filled_qty = buy_result.filled_size or size

        # SELL — exact filled quantity, never the originally requested size
        try:
            sell_oid = self.submit_market_order(is_buy=False, size=filled_qty)
        except TestnetExecutionError:
            remaining = self.get_position_size()
            logger.error(
                "SELL submission FAILED after a successful BUY. Remaining "
                "OPEN TESTNET POSITION: %s %s — close manually.",
                remaining,
                self.symbol,
            )
            raise

        sell_result = self.wait_for_fill(sell_oid, side="SELL")

        if sell_result.status != "filled":
            remaining = self.get_position_size()
            logger.error(
                "SELL did not fill (status=%s). Remaining OPEN TESTNET "
                "POSITION: %s %s — close manually.",
                sell_result.status,
                remaining,
                self.symbol,
            )
            return buy_result, sell_result

        final_position = self.get_position_size()
        logger.info(
            "POSITION CLOSED remaining_size=%s %s", final_position, self.symbol
        )

        return buy_result, sell_result
