from __future__ import annotations

import logging
import os
import time
from dotenv import load_dotenv

from hyperliquid.auth import HyperliquidAuth
from hyperliquid.client import HyperliquidClient, NetworkError, APIError
from hyperliquid.symbol import HyperliquidSymbol
from data.ohlcv_provider import OHLCVProvider
from strategies.ema_strategy import EMAStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.bb_strategy import BollingerStrategy
from strategies.base_strategy import BaseStrategy
from backtester.backtester import Backtester, BacktestResult
from backtester.performance import PerformanceAnalyser, PerformanceReport
from risk.risk_manager import RiskManager
from core.trade_logger import TradeLogger

load_dotenv()

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────

SYMBOL           = "BTC"
INTERVAL         = "1h"
BACKTEST_CANDLES = 500       # candles used for backtesting
POSITION_SIZE    = 0.001     # BTC per trade
INITIAL_CAPITAL  = 10_000.0
SLIPPAGE_PCT     = 0.001
SLEEP_SECONDS    = 60        # check every 60 seconds
RUN_HOURS        = 2         # how long to paper trade
IS_MAINNET       = False


MIN_SHARPE_TO_TRADE = 0.5

# ──────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("strategy_runner")


# ──────────────────────────────────────────────────────────────
# CONNECT
# ──────────────────────────────────────────────────────────────

def connect() -> tuple[HyperliquidClient, HyperliquidSymbol, OHLCVProvider]:
    """Connects to Hyperliquid and returns client, symbol map, ohlcv provider."""
    private_key = os.getenv("HL_PRIVATE_KEY")
    account_address = os.getenv("HL_ACCOUNT_ADDRESS")
    base_url = os.getenv("HL_BASE_URL", "https://api.hyperliquid-testnet.xyz")

    if not private_key or not account_address:
        raise ValueError("HL_PRIVATE_KEY and HL_ACCOUNT_ADDRESS must be set in .env")

    auth = HyperliquidAuth(
        private_key=private_key,
        account_address=account_address,
        is_mainnet=IS_MAINNET,
    )
    client = HyperliquidClient(auth=auth, base_url=base_url, max_retries=3)
    symbol_map = HyperliquidSymbol(client=client)
    symbol_map.load()
    ohlcv = OHLCVProvider(client=client)

    logger.info("Connected to %s", base_url)
    return client, symbol_map, ohlcv


# ──────────────────────────────────────────────────────────────
# FETCH DATA
# ──────────────────────────────────────────────────────────────

def fetch_data(ohlcv: OHLCVProvider, limit: int = BACKTEST_CANDLES) -> list[list]:
    """Fetches OHLCV candles from Hyperliquid."""
    logger.info("Fetching %d candles of %s %s...", limit, SYMBOL, INTERVAL)
    candles = ohlcv.fetch(SYMBOL, interval=INTERVAL, limit=limit)
    logger.info("Fetched %d candles", len(candles))
    return candles


# ──────────────────────────────────────────────────────────────
# CLEAN DATA
# ──────────────────────────────────────────────────────────────

def clean_data(candles: list[list]) -> list[list]:
    """
    Cleans raw OHLCV candles.

    Removes:
    - Candles with zero or negative prices
    - Candles where high < low
    - Candles where close is outside [low, high]
    - Duplicate timestamps
    - Candles with zero volume

    Returns clean candles sorted oldest → newest.
    """
    if not candles:
        raise ValueError("No candles to clean.")

    seen_timestamps: set[int] = set()
    clean: list[list] = []
    removed = 0

    for candle in candles:
        ts, open_, high, low, close, volume = candle

        # Duplicate timestamp
        if ts in seen_timestamps:
            removed += 1
            continue

        # Zero or negative prices
        if any(p <= 0 for p in [open_, high, low, close]):
            removed += 1
            continue

        # High must be >= low
        if high < low:
            removed += 1
            continue

        # Close must be within [low, high]
        if not (low <= close <= high):
            removed += 1
            continue

        # Zero volume (likely a bad candle)
        if volume <= 0:
            removed += 1
            continue

        seen_timestamps.add(ts)
        clean.append(candle)

    # Sort by timestamp oldest → newest
    clean.sort(key=lambda c: c[0])

    logger.info(
        "Data cleaned: %d candles kept, %d removed",
        len(clean), removed,
    )
    return clean


# ──────────────────────────────────────────────────────────────
# BACKTEST ALL STRATEGIES
# ──────────────────────────────────────────────────────────────

def backtest_all(
    candles: list[list],
) -> list[tuple[BaseStrategy, BacktestResult, PerformanceReport]]:
    """
    Runs all three strategies on the same candle data.
    Returns list of (strategy, result, report) sorted by Sharpe ratio descending.
    """
    strategies: list[BaseStrategy] = [
        EMAStrategy(fast_period=9, slow_period=21),
        RSIStrategy(period=14, oversold_threshold=30, overbought_threshold=70),
        BollingerStrategy(period=20, num_std=2.0),
    ]

    analyser = PerformanceAnalyser()
    results = []

    for strategy in strategies:
        logger.info("Backtesting %s...", strategy.name)

        b = Backtester(
            strategy=strategy,
            initial_capital=INITIAL_CAPITAL,
            position_size=POSITION_SIZE,
            slippage_pct=SLIPPAGE_PCT,
            symbol=SYMBOL,
        )
        result = b.run(candles)
        report = analyser.analyse(result)

        logger.info(
            "  %s → trades=%d PnL=%+.2f sharpe=%.4f winrate=%.1f%%",
            strategy.name,
            report.num_trades,
            report.total_pnl,
            report.sharpe_ratio,
            report.win_rate * 100,
        )
        results.append((strategy, result, report))

    # Sort by Sharpe ratio — best first
    results.sort(key=lambda x: x[2].sharpe_ratio, reverse=True)
    return results


# ──────────────────────────────────────────────────────────────
# PRINT COMPARISON
# ──────────────────────────────────────────────────────────────

def print_comparison(
    results: list[tuple[BaseStrategy, BacktestResult, PerformanceReport]],
) -> None:
    """Prints a side-by-side comparison of all strategy results."""
    print("\n" + "="*65)
    print("  STRATEGY COMPARISON")
    print("="*65)
    print(f"  {'Strategy':<30} {'Trades':>6} {'PnL':>10} {'Sharpe':>8} {'WinRate':>8}")
    print("-"*65)
    for strategy, result, report in results:
        pf = f"{report.profit_factor:.2f}" if report.profit_factor != float("inf") else "∞"
        print(
            f"  {strategy.name:<30} "
            f"{report.num_trades:>6} "
            f"{report.total_pnl:>+10.2f} "
            f"{report.sharpe_ratio:>8.4f} "
            f"{report.win_rate:>7.1%}"
        )
    print("="*65)
    print(f"\n  Best strategy: {results[0][0].name}")
    print(f"  Sharpe ratio:  {results[0][2].sharpe_ratio:.4f}")
    print(f"  Total PnL:     {results[0][2].total_pnl:+.2f} USDC")
    print()


# ──────────────────────────────────────────────────────────────
# PAPER TRADE
# ──────────────────────────────────────────────────────────────

def paper_trade(
    strategy: BaseStrategy,
    ohlcv: OHLCVProvider,
    run_hours: float = RUN_HOURS,
) -> None:
    """
    Paper trades the given strategy for run_hours hours.
    Fetches live candles, runs strategy, simulates fills, logs everything.
    """
    logger.info(
        "Starting paper trade: %s for %.1f hours",
        strategy.name, run_hours,
    )

    trade_log = TradeLogger(
        log_dir="logs",
        symbol=SYMBOL,
        strategy=strategy.name,
    )

    risk = RiskManager(
        account_balance=INITIAL_CAPITAL,
        max_position_pct=0.05,
        max_daily_loss_pct=0.02,
    )

    trade_log.log_session_start(
        balance=INITIAL_CAPITAL,
        extra={"strategy": strategy.name, "mode": "paper_trade"},
    )

    in_position = False
    entry_price = 0.0
    entry_time = ""
    total_pnl = 0.0
    num_trades = 0
    daily_loss = 0.0
    last_signal = "HOLD"

    run_seconds = run_hours * 3600
    start = time.time()

    try:
        while time.time() - start < run_seconds:
            # Fetch latest candles
            candles = ohlcv.fetch(SYMBOL, interval=INTERVAL, limit=50)
            if not candles:
                logger.warning("No candles returned — skipping tick")
                time.sleep(SLEEP_SECONDS)
                continue

            candles = clean_data(candles)
            closes = [c[4] for c in candles]
            price = closes[-1]

            # Get signal
            signal = strategy.generate_signal(closes)

            # Log signal (skip repeated HOLDs to keep logs clean)
            if signal != "HOLD" or last_signal != "HOLD":
                trade_log.log_signal(signal, price=price)

            logger.info(
                "[%s] Price=%.2f Signal=%s InPosition=%s PnL=%+.2f",
                strategy.name, price, signal, in_position, total_pnl,
            )
            last_signal = signal

            # BUY
            if signal == "BUY" and not in_position:
                risk_result = risk.check_trade(
                    symbol=SYMBOL,
                    price=price,
                    requested_size=POSITION_SIZE,
                    current_daily_loss=daily_loss,
                    open_positions=0,
                )
                if risk_result.allowed:
                    entry_price = price
                    entry_time = _now_iso()
                    in_position = True
                    trade_log.log_order("BUY", price=price, size=POSITION_SIZE)
                    trade_log.log_fill("BUY", price=price, size=POSITION_SIZE)
                    logger.info("PAPER BUY: %.4f BTC @ %.2f", POSITION_SIZE, price)
                else:
                    trade_log.log_risk_block(
                        reason=risk_result.reason,
                        requested_size=POSITION_SIZE,
                    )
                    logger.warning("Risk blocked: %s", risk_result.reason)

            # SELL
            elif signal == "SELL" and in_position:
                exit_price = price
                pnl = (exit_price - entry_price) * POSITION_SIZE
                pnl_pct = (exit_price - entry_price) / entry_price

                in_position = False
                total_pnl += pnl
                num_trades += 1
                if pnl < 0:
                    daily_loss += abs(pnl)

                trade_log.log_order("SELL", price=exit_price, size=POSITION_SIZE)
                trade_log.log_fill("SELL", price=exit_price, size=POSITION_SIZE)
                trade_log.log_trade_closed(
                    side="LONG",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    size=POSITION_SIZE,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    entry_time=entry_time,
                )
                risk.update_balance(INITIAL_CAPITAL + total_pnl)

                logger.info(
                    "PAPER SELL: %.4f BTC @ %.2f | PnL=%+.4f USDC (%+.2f%%)",
                    POSITION_SIZE, exit_price, pnl, pnl_pct * 100,
                )

            elapsed = time.time() - start
            remaining = run_seconds - elapsed
            logger.info(
                "Sleeping %ds | Time remaining: %.0fm",
                SLEEP_SECONDS, remaining / 60,
            )
            time.sleep(SLEEP_SECONDS)

    except KeyboardInterrupt:
        logger.info("Stopped by user.")

    finally:
        # Force close open position
        if in_position:
            candles = ohlcv.fetch(SYMBOL, interval=INTERVAL, limit=2)
            if candles:
                final_price = candles[-1][4]
                pnl = (final_price - entry_price) * POSITION_SIZE
                total_pnl += pnl
                num_trades += 1
                trade_log.log_trade_closed(
                    "LONG", entry_price, final_price,
                    POSITION_SIZE, pnl, pnl / (entry_price * POSITION_SIZE),
                    entry_time,
                )
                logger.info("Force closed at %.2f | PnL=%+.4f", final_price, pnl)

        trade_log.log_session_end(
            balance=INITIAL_CAPITAL + total_pnl,
            total_pnl=total_pnl,
            num_trades=num_trades,
        )
        logger.info(
            "Paper trade complete — trades=%d total_pnl=%+.4f USDC",
            num_trades, total_pnl,
        )


# ──────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ──────────────────────────────────────────────────────────────

def run_pipeline() -> None:
    """
    Full pipeline:
        connect → fetch → clean → backtest → compare → paper trade winner
    """
    print("\n" + "="*65)
    print("  HYPER-ENGINE STRATEGY PIPELINE")
    print("="*65 + "\n")

    client, symbol_map, ohlcv = connect()

    candles = fetch_data(ohlcv, limit=BACKTEST_CANDLES)

    candles = clean_data(candles)

    if len(candles) < 50:
        logger.error("Not enough clean candles (%d). Aborting.", len(candles))
        return

    results = backtest_all(candles)

    print_comparison(results)

    best_strategy, best_result, best_report = results[0]

    if best_report.sharpe_ratio < MIN_SHARPE_TO_TRADE:
        logger.warning(
            "Best strategy Sharpe (%.4f) is below minimum (%.1f). "
            "No paper trading — market conditions not favourable.",
            best_report.sharpe_ratio, MIN_SHARPE_TO_TRADE,
        )
        print(f"  ⚠ No paper trade — Sharpe {best_report.sharpe_ratio:.4f} "
              f"< minimum {MIN_SHARPE_TO_TRADE}")
        return

    if best_result.num_trades == 0:
        logger.warning("Best strategy had zero trades. No paper trading.")
        print("  ⚠ No paper trade — strategy produced zero trades on backtest data.")
        return

    print(f"  ✓ Selected: {best_strategy.name}")
    print(f"  Starting {RUN_HOURS}h paper trade session...\n")

    paper_trade(best_strategy, ohlcv, run_hours=RUN_HOURS)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    run_pipeline()