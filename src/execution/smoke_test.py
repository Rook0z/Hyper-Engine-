"""
REAL Hyperliquid TESTNET execution smoke test.

Places an ACTUAL BUY order and then an ACTUAL SELL order on Hyperliquid
TESTNET, using real testnet USDC, to prove the execution path works
end-to-end (submit -> fill -> position -> submit -> fill -> flat).

This is NOT a simulation and NOT paper trading. A successful run means
Hyperliquid TESTNET actually shows the BUY and SELL in your account's
Open Orders / Order History / Trade History / Positions.

Disabled by default. Requires, in .env:
    IS_MAINNET=false
    ENABLE_TESTNET_LIVE_EXECUTION=true

Run:
    poetry run python -m execution.smoke_test
"""

from __future__ import annotations

import logging

from core.config import settings
from core.database import Database
from core.trade_logger import TradeLogger
from execution.testnet_executor import (
    TestnetExecutionError,
    TestnetExecutor,
    TestnetSafetyError,
)
from hyperliquid.auth import HyperliquidAuth
from hyperliquid.client import HyperliquidClient
from hyperliquid.symbol import HyperliquidSymbol

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("testnet_smoke_test")


def main() -> None:
    print("\n" + "=" * 65)
    print("  HYPER-ENGINE — REAL TESTNET EXECUTION SMOKE TEST")
    print("  (this places ACTUAL orders on Hyperliquid TESTNET)")
    print("=" * 65 + "\n")

    # 1. Config must be explicitly testnet.
    settings.assert_credentials()
    settings.assert_testnet()

    auth = HyperliquidAuth(
        private_key=settings.hl_private_key,
        account_address=settings.hl_account_address,
        is_mainnet=settings.is_mainnet,
    )
    # 2. Connect using the existing client, explicitly pinned to the
    # configured (testnet) base URL — TestnetExecutor re-verifies this
    # independently below.
    client = HyperliquidClient(auth=auth, base_url=settings.hl_base_url)
    symbol_map = HyperliquidSymbol(client=client)
    symbol_map.load()

    try:
        executor = TestnetExecutor(
            client=client, symbol_map=symbol_map, symbol=settings.symbol
        )
    except TestnetSafetyError as e:
        logger.error("Refusing to run: %s", e)
        print(f"\nABORTED (safety check failed): {e}\n")
        return

    # 3. Current price.
    price = executor.get_price()
    print(f"Current {settings.symbol} price: {price}")

    # 4. Account balance.
    balances = executor.account.get_balances()
    print(f"Account value : {balances.marginSummary.accountValue} USDC")
    print(f"Withdrawable  : {balances.withdrawable} USDC")

    # 5. Test size.
    size = settings.position_size
    print(f"Test size     : {size} {settings.symbol}\n")

    # 6-13. BUY -> verify -> SELL -> verify, fully handled by the
    # executor (see execution/testnet_executor.py for the safety
    # guards and full lifecycle logging). This does not change or wrap
    # that logic in any way — we only persist its result through the
    # same TradeLogger/Database the dashboard already reads, so a
    # smoke test run shows up in the dashboard exactly like a
    # strategy_runner-driven trade would.
    trade_log = TradeLogger(
        log_dir=settings.log_dir,
        symbol=settings.symbol,
        strategy="SmokeTest",
        db=Database(),
    )
    trade_log.log_session_start(
        balance=settings.initial_capital,
        extra={"strategy": "SmokeTest", "mode": "smoke_test"},
    )

    try:
        buy_result, sell_result = executor.run_smoke_cycle(size=size)
    except TestnetExecutionError as e:
        logger.error("Smoke test aborted: %s", e)
        print(f"\nABORTED: {e}\n")
        trade_log.log_error(
            str(e),
            context={"type": "TestnetExecutionError", "stage": "run_smoke_cycle"},
        )
        trade_log.log_session_end(
            balance=settings.initial_capital, total_pnl=0.0, num_trades=0
        )
        return

    trade_log.log_order("BUY", price=price, size=size, order_type="MARKET")
    if buy_result.status == "filled":
        trade_log.log_fill(
            "BUY",
            price=buy_result.avg_price,
            size=buy_result.filled_size,
            oid=buy_result.oid,
        )
    if sell_result is not None:
        trade_log.log_order(
            "SELL",
            price=buy_result.avg_price,
            size=buy_result.filled_size,
            order_type="MARKET",
        )
        if sell_result.status == "filled":
            trade_log.log_fill(
                "SELL",
                price=sell_result.avg_price,
                size=sell_result.filled_size,
                oid=sell_result.oid,
            )

    buy_filled = buy_result.status == "filled"
    sell_filled = sell_result is not None and sell_result.status == "filled"

    # LEG ISOLATION, same rule as live_testnet_trade(): a completed
    # "trade" row is only ever written when BOTH legs are confirmed
    # filled — never fabricated from a BUY-only or incomplete cycle.
    total_pnl = 0.0
    num_trades = 0
    if buy_filled and sell_filled:
        assert sell_result is not None  # sell_filled already implies this
        total_pnl = (
            sell_result.avg_price - buy_result.avg_price
        ) * buy_result.filled_size
        pnl_pct = (sell_result.avg_price - buy_result.avg_price) / buy_result.avg_price
        num_trades = 1
        trade_log.log_trade_closed(
            side="LONG",
            entry_price=buy_result.avg_price,
            exit_price=sell_result.avg_price,
            size=buy_result.filled_size,
            pnl=total_pnl,
            pnl_pct=pnl_pct,
        )
    elif buy_filled and not sell_filled:
        trade_log.log_error(
            f"SELL unresolved: {sell_result.status if sell_result else 'not submitted'}",
            context={"stage": "smoke_test", "buy_oid": buy_result.oid},
        )
    else:
        trade_log.log_error(
            f"BUY not filled: {buy_result.status}",
            context={"stage": "smoke_test", "buy_oid": buy_result.oid},
        )

    trade_log.log_session_end(
        balance=settings.initial_capital + total_pnl,
        total_pnl=total_pnl,
        num_trades=num_trades,
    )

    print("\n" + "=" * 65)
    print("  RESULT")
    print("=" * 65)
    print(
        f"  BUY  : status={buy_result.status} oid={buy_result.oid} "
        f"filled={buy_result.filled_size} avg_px={buy_result.avg_price}"
    )
    if sell_result is not None:
        print(
            f"  SELL : status={sell_result.status} oid={sell_result.oid} "
            f"filled={sell_result.filled_size} avg_px={sell_result.avg_price}"
        )
    else:
        print("  SELL : NOT submitted (BUY did not fill)")
    print("=" * 65)

    buy_filled = buy_result.status == "filled"
    sell_filled = sell_result is not None and sell_result.status == "filled"

    if buy_filled and sell_filled:
        print("\n  SMOKE TEST COMPLETE — BUY and SELL both confirmed filled.")
    elif buy_filled and not sell_filled:
        print(
            "\n  SMOKE TEST INCOMPLETE — BUY was filled but SELL is "
            "UNRESOLVED.\n"
            "  Do NOT treat this as a successful cycle. Check the open "
            "position on Hyperliquid TESTNET and close it manually if needed."
        )
    else:
        print(
            "\n  SMOKE TEST INCOMPLETE — BUY was not confirmed filled. "
            "SELL was never submitted."
        )

    print(
        "\nCheck your Hyperliquid TESTNET account — Open Orders / Order "
        "History / Trade History / Positions — to confirm.\n"
    )


if __name__ == "__main__":
    main()
