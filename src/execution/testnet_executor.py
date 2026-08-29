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

# Real per-order fill statuses Hyperliquid ever returns for orderStatus
# (per their docs). The top-level wrapper status ("order" = found,
# "unknownOid" = not found) is deliberately NOT in this set — it must
# never be mistaken for a fill status.
_REAL_ORDER_STATUSES = {
    "open",
    "filled",
    "canceled",
    "triggered",
    "rejected",
    "marginCanceled",
    "vaultWithdrawalCanceled",
}


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

        signing_address = client.auth.wallet.address.lower()
        read_address = client.auth.account_address.lower()
        addresses_match = signing_address == read_address
        if addresses_match:
            logger.info(
                "TESTNET ACCOUNT: signing_wallet=%s (derived from "
                "HL_PRIVATE_KEY) trades and reads (orderStatus/userFills/"
                "positions) as the same account — no agent wallet in use.",
                signing_address,
            )
        else:
            # A different signing_wallet and read_address is the EXPECTED,
            # correctly-configured shape for an agent/API wallet setup
            # (HL_PRIVATE_KEY = the approved agent key, HL_ACCOUNT_ADDRESS
            # = the master account it trades on behalf of) — not itself a
            # problem, so this logs as informational rather than a
            # warning. It's still logged, and still names both addresses
            # explicitly, because the one thing this can't distinguish
            # from a correctly-configured agent wallet is HL_ACCOUNT_ADDRESS
            # being set to the wrong address by mistake — if this doesn't
            # match an agent-wallet pairing you actually set up on
            # Hyperliquid (Settings -> API Wallets), fix HL_ACCOUNT_ADDRESS
            # before trading.
            logger.info(
                "TESTNET ACCOUNT: operating in agent-wallet mode — "
                "signing_wallet=%s (agent, derived from HL_PRIVATE_KEY) "
                "submits orders on behalf of read_address=%s (master "
                "account, HL_ACCOUNT_ADDRESS — used for orderStatus/"
                "userFills/positions). If you did not set this agent wallet "
                "up yourself on Hyperliquid (Settings -> API Wallets), "
                "verify HL_ACCOUNT_ADDRESS is correct before trading.",
                signing_address,
                read_address,
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
            "TESTNET %s SUBMITTED oid=%s symbol=%s size=%s",
            side,
            oid,
            self.symbol,
            size_str,
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
        Confirms whether a REAL testnet order filled.

        PRIMARY / authoritative source: account fill history
        (userFills via HyperliquidAccount.get_fills()), filtered to
        this order's oid. Checked on EVERY poll, before anything else.
        This is ground truth for whether an order actually executed —
        Hyperliquid's testnet orderStatus endpoint has been observed
        returning {"status": "unknownOid"} for market/IOC orders that
        filled instantly and left the book, so orderStatus alone cannot
        be trusted as a negative signal.

        SECONDARY source: orderStatus, used ONLY to detect an explicit
        REJECTED/CANCELED/marginCanceled terminal state — fills can't
        distinguish "rejected" from "still pending" (both produce zero
        fills), so this is the one thing orderStatus is still needed
        for. Any other orderStatus result — "unknownOid", "open", or
        an unrecognized shape — is inconclusive and is simply ignored;
        it never overrides or delays the fills-based check above, and
        it never causes another order to be submitted (this method only
        ever reads state — see run_smoke_cycle() for where SELL is
        gated on a genuinely confirmed BUY).

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
        timeout = (
            timeout if timeout is not None else settings.execution_poll_timeout_seconds
        )
        deadline = time.time() + timeout
        last_order_status = ""

        while True:
            # 1. Authoritative: did this specific oid actually fill?
            filled_size, avg_price = self._fill_totals_for_oid(oid)
            if filled_size > 0:
                logger.info(
                    "TESTNET %s FILL CONFIRMED source=user_fills oid=%s size=%s "
                    "avg_price=%s",
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

            # 2. Secondary: did the exchange explicitly reject/cancel it?
            # (orderStatus is the only source for this terminal-negative
            # signal; every other result from it, including "unknownOid",
            # is inconclusive and does not affect the loop.)
            raw = self.account.get_order_status(oid)
            order_status, _ = self._parse_order_status(raw)
            last_order_status = order_status or raw.get("status", "")

            if order_status in ("rejected", "canceled", "marginCanceled"):
                logger.error(
                    "TESTNET %s %s source=order_status oid=%s",
                    side,
                    order_status.upper(),
                    oid,
                )
                return FillResult(oid=oid, side=side, status=order_status)

            if time.time() >= deadline:
                logger.error(
                    "TESTNET ORDER TIMEOUT side=%s order_id=%s (waited %.1fs, "
                    "last order_status=%r, no matching fills found via "
                    "user_fills)",
                    side,
                    oid,
                    timeout,
                    last_order_status,
                )
                return FillResult(oid=oid, side=side, status="timeout")

            time.sleep(poll_interval)

    @staticmethod
    def _parse_order_status(raw: dict) -> tuple[str, dict]:
        """
        Extracts the real per-order fill status and order fields from an
        account.get_order_status() response.

        Hyperliquid's orderStatus response wraps the real status inside
        a top-level "found/not found" indicator ("order" | "unknownOid"
        at raw["status"]), with the real fill status nested underneath —
        documented as raw["order"]["status"]. Rather than assuming that
        one fixed nesting depth (an earlier attempt at this did, and it
        turned out to still be wrong against the real testnet response),
        this recursively searches the whole response for a "status"
        value that is one of the known real fill-status strings, paired
        with its sibling "order" dict — so it keeps working regardless
        of exactly how deep that nesting turns out to be.

        Args:
            raw: The dict returned by HyperliquidAccount.get_order_status().

        Returns:
            (real_status, order_fields). real_status is "" if the oid
            was not found yet (raw["status"] == "unknownOid") or no
            recognized status string was found anywhere in the
            response. order_fields is {} in that case too.
        """
        if not isinstance(raw, dict):
            return "", {}
        if raw.get("status") == "unknownOid":
            return "", {}

        def _walk(node: object) -> tuple[str, dict]:
            if isinstance(node, dict):
                status_value = node.get("status")
                if (
                    isinstance(status_value, str)
                    and status_value in _REAL_ORDER_STATUSES
                ):
                    order_fields = node.get("order")
                    if isinstance(order_fields, dict):
                        return status_value, order_fields
                    return status_value, {}
                for value in node.values():
                    found_status, found_fields = _walk(value)
                    if found_status:
                        return found_status, found_fields
            elif isinstance(node, list):
                for item in node:
                    found_status, found_fields = _walk(item)
                    if found_status:
                        return found_status, found_fields
            return "", {}

        return _walk(raw)

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

    def _fill_totals_for_oid(self, oid: int) -> tuple[float, float]:
        """
        Returns (total_filled_size, volume_weighted_avg_price) for all
        fills matching this order ID, from RAW account fill history
        (userFills — see HyperliquidAccount.get_raw_fills()). This is
        the AUTHORITATIVE source for whether a market/IOC order
        actually executed on Hyperliquid testnet — the orderStatus
        endpoint has been observed returning {"status": "unknownOid"}
        for orders that filled instantly and left the book.

        Deliberately uses RAW dicts, not the Fill Pydantic model:
        HyperliquidAccount.get_fills() validates every fill through
        that model, and a field-name/type mismatch against the real
        API would raise there — which, caught broadly, is
        indistinguishable from "no fills yet". Raw dicts avoid that
        entire failure class.

        oid comparison is done as STRINGS on both sides
        (str(fill_oid) == str(oid)), not a direct int == int compare —
        if Hyperliquid's fills array returns "oid" as a JSON string
        while our submitted oid is a Python int (or vice versa), a
        strict type-sensitive comparison would silently fail every
        single fill forever, with no error and no visibility. String
        comparison sidesteps that regardless of which type the API
        actually uses.

        Logs a diagnostic line for every fill considered (oid, whether
        it matched, side, coin, size, price) — intentionally verbose
        while testnet fill-confirmation reliability is being hardened
        against the real, previously-unverified API shape.

        Returns:
            (0.0, 0.0) if no matching fill exists yet, the response
            wasn't a list, or the lookup itself failed — callers must
            treat that as "not confirmed yet", never as "filled at
            zero size".
        """
        try:
            raw_fills = self.account.get_raw_fills()
        except Exception as e:
            logger.warning("Could not fetch raw fills for oid=%s: %s", oid, e)
            return 0.0, 0.0

        if not isinstance(raw_fills, list):
            logger.warning(
                "userFills response for oid=%s was not a list: %r", oid, raw_fills
            )
            return 0.0, 0.0

        oid_str = str(oid)
        matched: list[dict] = []
        candidate_oids: list[object] = []

        for f in raw_fills:
            if not isinstance(f, dict):
                continue
            f_oid = f.get("oid")
            candidate_oids.append(f_oid)
            is_match = f_oid is not None and str(f_oid) == oid_str
            if is_match:
                logger.info(
                    "TESTNET fill MATCH oid=%s side=%s coin=%s size=%s price=%s",
                    f_oid,
                    f.get("side"),
                    f.get("coin"),
                    f.get("sz"),
                    f.get("px"),
                )
                matched.append(f)

        logger.info(
            "TESTNET fill-check oid=%s (submitted as %s): %d raw fills "
            "returned, %d matched, candidate oids=%r",
            oid,
            type(oid).__name__,
            len(raw_fills),
            len(matched),
            candidate_oids[:20],
        )

        if not matched:
            return 0.0, 0.0

        try:
            total_size = sum(float(f["sz"]) for f in matched)
            if total_size == 0:
                return 0.0, 0.0
            weighted = sum(float(f["px"]) * float(f["sz"]) for f in matched)
            return total_size, weighted / total_size
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(
                "Malformed fill data for oid=%s: %s (matched=%r)", oid, e, matched
            )
            return 0.0, 0.0

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
        logger.info("WAITING FOR BUY FILL oid=%s", buy_oid)
        buy_result = self.wait_for_fill(buy_oid, side="BUY")

        if buy_result.status != "filled":
            logger.error(
                "SMOKE TEST INCOMPLETE — BUY did not fill (status=%s). SELL will "
                "NOT be submitted.",
                buy_result.status,
            )
            return buy_result, None

        logger.info(
            "BUY FILLED oid=%s size=%s avg_price=%s",
            buy_result.oid,
            buy_result.filled_size,
            buy_result.avg_price,
        )
        position = self.get_position_size()
        logger.info("POSITION OPEN size=%s %s", position, self.symbol)

        filled_qty = buy_result.filled_size or size

        # SELL — exact filled quantity, never the originally requested size
        try:
            sell_oid = self.submit_market_order(is_buy=False, size=filled_qty)
        except TestnetExecutionError:
            remaining = self.get_position_size()
            logger.error(
                "SMOKE TEST INCOMPLETE — BUY was filled (size=%s avg_price=%s) "
                "but SELL submission FAILED. Remaining OPEN TESTNET POSITION: "
                "%s %s — close manually.",
                buy_result.filled_size,
                buy_result.avg_price,
                remaining,
                self.symbol,
            )
            raise

        logger.info("WAITING FOR SELL FILL oid=%s", sell_oid)
        sell_result = self.wait_for_fill(sell_oid, side="SELL")

        if sell_result.status != "filled":
            remaining = self.get_position_size()
            logger.error(
                "SMOKE TEST INCOMPLETE — BUY was filled (size=%s avg_price=%s) "
                "but SELL remains UNRESOLVED (status=%s). Remaining OPEN "
                "TESTNET POSITION: %s %s — close manually.",
                buy_result.filled_size,
                buy_result.avg_price,
                sell_result.status,
                remaining,
                self.symbol,
            )
            return buy_result, sell_result

        logger.info(
            "SELL FILLED oid=%s size=%s avg_price=%s",
            sell_result.oid,
            sell_result.filled_size,
            sell_result.avg_price,
        )
        final_position = self.get_position_size()
        logger.info("POSITION CLOSED remaining_size=%s %s", final_position, self.symbol)
        logger.info("SMOKE TEST COMPLETE — BUY and SELL both confirmed filled.")

        return buy_result, sell_result
