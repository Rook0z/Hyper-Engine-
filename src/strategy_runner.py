from __future__ import annotations

import logging
import time
from dotenv import load_dotenv

from core.config import settings
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
    settings.assert_credentials()
    settings.assert_testnet()

    auth = HyperliquidAuth(
        private_key=settings.hl_private_key,
        account_address=settings.hl_account_address,
        is_mainnet=settings.is_mainnet,
    )
    client = HyperliquidClient(
        auth=auth,
        base_url=settings.hl_base_url,
        max_retries=3,
    )
    symbol_map = HyperliquidSymbol(client=client)
    symbol_map.load()
    ohlcv = OHLCVProvider(client=client)

    logger.info("Connected — %s", settings.summary())
    return client, symbol_map, ohlcv


# ──────────────────────────────────────────────────────────────
# FETCH DATA
# ──────────────────────────────────────────────────────────────


def fetch_data(ohlcv: OHLCVProvider) -> list[list]:
    """Fetches OHLCV candles from Hyperliquid."""
    logger.info(
        "Fetching %d candles of %s %s...",
        settings.backtest_candles,
        settings.symbol,
        settings.interval,
    )
    candles = ohlcv.fetch(
        settings.symbol,
        interval=settings.interval,
        limit=settings.backtest_candles,
    )
    logger.info("Fetched %d candles", len(candles))
    return candles


# ──────────────────────────────────────────────────────────────
# CLEAN DATA
# ──────────────────────────────────────────────────────────────


def clean_data(candles: list[list]) -> list[list]:
    """
    Cleans raw OHLCV candles.
    Removes: zero/negative prices, high < low, close outside range,
             duplicate timestamps, zero volume.
    """
    if not candles:
        raise ValueError("No candles to clean.")

    seen: set[int] = set()
    clean: list[list] = []
    removed = 0

    for candle in candles:
        ts, open_, high, low, close, volume = candle

        if ts in seen:
            removed += 1
            continue
        if any(p <= 0 for p in [open_, high, low, close]):
            removed += 1
            continue
        if high < low:
            removed += 1
            continue
        if not (low <= close <= high):
            removed += 1
            continue
        if volume <= 0:
            removed += 1
            continue

        seen.add(ts)
        clean.append(candle)

    clean.sort(key=lambda c: c[0])
    logger.info("Data cleaned: %d kept, %d removed", len(clean), removed)
    return clean


# ──────────────────────────────────────────────────────────────
# BACKTEST ALL STRATEGIES
# ──────────────────────────────────────────────────────────────


def backtest_all(
    candles: list[list],
) -> list[tuple[BaseStrategy, BacktestResult, PerformanceReport]]:
    """Runs all strategies on the same data. Returns sorted by Sharpe desc."""
    strategies: list[BaseStrategy] = [
        EMAStrategy(
            fast_period=settings.ema_fast_period,
            slow_period=settings.ema_slow_period,
        ),
        RSIStrategy(
            period=settings.rsi_period,
            oversold_threshold=settings.rsi_oversold,
            overbought_threshold=settings.rsi_overbought,
        ),
        BollingerStrategy(
            period=settings.bb_period,
            num_std=settings.bb_num_std,
        ),
    ]

    analyser = PerformanceAnalyser()
    results = []

    for strategy in strategies:
        logger.info("Backtesting %s...", strategy.name)
        b = Backtester(
            strategy=strategy,
            initial_capital=settings.initial_capital,
            position_size=settings.position_size,
            slippage_pct=settings.slippage_pct,
            symbol=settings.symbol,
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

    results.sort(key=lambda x: x[2].sharpe_ratio, reverse=True)
    return results


# ──────────────────────────────────────────────────────────────
# PRINT COMPARISON
# ──────────────────────────────────────────────────────────────


def print_comparison(
    results: list[tuple[BaseStrategy, BacktestResult, PerformanceReport]],
) -> None:
    """Prints side-by-side strategy comparison."""
    print("\n" + "=" * 65)
    print("  STRATEGY COMPARISON")
    print("=" * 65)
    print(f"  {'Strategy':<30} {'Trades':>6} {'PnL':>10} {'Sharpe':>8} {'WinRate':>8}")
    print("-" * 65)
    for strategy, result, report in results:
        print(
            f"  {strategy.name:<30} "
            f"{report.num_trades:>6} "
            f"{report.total_pnl:>+10.2f} "
            f"{report.sharpe_ratio:>8.4f} "
            f"{report.win_rate:>7.1%}"
        )
    print("=" * 65)
    print(f"\n  Best strategy : {results[0][0].name}")
    print(f"  Sharpe ratio  : {results[0][2].sharpe_ratio:.4f}")
    print(f"  Total PnL     : {results[0][2].total_pnl:+.2f} USDC\n")


# ──────────────────────────────────────────────────────────────
# PAPER TRADE
# ──────────────────────────────────────────────────────────────


def paper_trade(
    strategy: BaseStrategy,
    ohlcv: OHLCVProvider,
) -> None:
    """Paper trades the given strategy using settings from config."""
    logger.info(
        "Starting paper trade: %s for %.1f hours",
        strategy.name,
        settings.run_hours,
    )

    trade_log = TradeLogger(
        log_dir=settings.log_dir,
        symbol=settings.symbol,
        strategy=strategy.name,
    )
    risk = RiskManager(
        account_balance=settings.initial_capital,
        max_position_pct=settings.max_position_pct,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        max_open_positions=settings.max_open_positions,
    )

    trade_log.log_session_start(
        balance=settings.initial_capital,
        extra={"strategy": strategy.name, "mode": "paper_trade"},
    )

    in_position = False
    entry_price = 0.0
    entry_time = ""
    total_pnl = 0.0
    num_trades = 0
    daily_loss = 0.0
    last_signal = "HOLD"

    run_seconds = settings.run_hours * 3600
    start = time.time()

    try:
        while time.time() - start < run_seconds:
            try:
                candles = ohlcv.fetch(
                    settings.symbol,
                    interval=settings.interval,
                    limit=50,
                )
                if not candles:
                    logger.warning("No candles — skipping tick")
                    time.sleep(settings.sleep_seconds)
                    continue

                candles = clean_data(candles)
                closes = [c[4] for c in candles]
                price = closes[-1]

                signal = strategy.generate_signal(closes)

                if signal != "HOLD" or last_signal != "HOLD":
                    trade_log.log_signal(signal, price=price)

                logger.info(
                    "[%s] Price=%.2f Signal=%s InPosition=%s PnL=%+.2f",
                    strategy.name,
                    price,
                    signal,
                    in_position,
                    total_pnl,
                )
                last_signal = signal

                # BUY
                if signal == "BUY" and not in_position:
                    risk_result = risk.check_trade(
                        symbol=settings.symbol,
                        price=price,
                        requested_size=settings.position_size,
                        current_daily_loss=daily_loss,
                        open_positions=0,
                    )
                    if risk_result.allowed:
                        entry_price = price
                        entry_time = _now_iso()
                        in_position = True
                        trade_log.log_order(
                            "BUY", price=price, size=settings.position_size
                        )
                        trade_log.log_fill(
                            "BUY", price=price, size=settings.position_size
                        )
                        logger.info(
                            "PAPER BUY: %.4f %s @ %.2f",
                            settings.position_size,
                            settings.symbol,
                            price,
                        )
                    else:
                        trade_log.log_risk_block(
                            reason=risk_result.reason,
                            requested_size=settings.position_size,
                        )
                        logger.warning("Risk blocked: %s", risk_result.reason)

                # SELL
                elif signal == "SELL" and in_position:
                    pnl = (price - entry_price) * settings.position_size
                    pnl_pct = (price - entry_price) / entry_price

                    in_position = False
                    total_pnl += pnl
                    num_trades += 1
                    if pnl < 0:
                        daily_loss += abs(pnl)

                    trade_log.log_order(
                        "SELL", price=price, size=settings.position_size
                    )
                    trade_log.log_fill("SELL", price=price, size=settings.position_size)
                    trade_log.log_trade_closed(
                        side="LONG",
                        entry_price=entry_price,
                        exit_price=price,
                        size=settings.position_size,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                        entry_time=entry_time,
                    )
                    risk.update_balance(settings.initial_capital + total_pnl)
                    logger.info(
                        "PAPER SELL: %.4f %s @ %.2f | PnL=%+.4f USDC (%+.2f%%)",
                        settings.position_size,
                        settings.symbol,
                        price,
                        pnl,
                        pnl_pct * 100,
                    )

            except NetworkError as e:
                logger.warning("Network error — retrying next tick: %s", e)
                trade_log.log_error(str(e), context={"type": "NetworkError"})
            except APIError as e:
                logger.error("API error: %s", e)
                trade_log.log_error(str(e), context={"type": "APIError"})
            except Exception as e:
                logger.exception("Unexpected error: %s", e)
                trade_log.log_error(str(e), context={"type": "Exception"})

            elapsed = time.time() - start
            remaining = run_seconds - elapsed
            logger.info(
                "Sleeping %ds | Remaining: %.0fm",
                settings.sleep_seconds,
                remaining / 60,
            )
            time.sleep(settings.sleep_seconds)

    except KeyboardInterrupt:
        logger.info("Stopped by user.")

    finally:
        if in_position:
            try:
                candles = ohlcv.fetch(
                    settings.symbol, interval=settings.interval, limit=2
                )
                if candles:
                    final_price = candles[-1][4]
                    pnl = (final_price - entry_price) * settings.position_size
                    total_pnl += pnl
                    num_trades += 1
                    trade_log.log_trade_closed(
                        "LONG",
                        entry_price,
                        final_price,
                        settings.position_size,
                        pnl,
                        pnl / (entry_price * settings.position_size),
                        entry_time,
                    )
                    logger.info("Force closed at %.2f | PnL=%+.4f", final_price, pnl)
            except Exception as e:
                logger.error("Failed to force close: %s", e)

        trade_log.log_session_end(
            balance=settings.initial_capital + total_pnl,
            total_pnl=total_pnl,
            num_trades=num_trades,
        )
        logger.info(
            "Session ended — trades=%d total_pnl=%+.4f USDC",
            num_trades,
            total_pnl,
        )


# ──────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ──────────────────────────────────────────────────────────────


def run_pipeline() -> None:
    """
    Full pipeline: connect → fetch → clean → backtest → compare → paper trade
    """
    print("\n" + "=" * 65)
    print("  HYPER-ENGINE STRATEGY PIPELINE")
    print("=" * 65 + "\n")

    client, symbol_map, ohlcv = connect()
    candles = fetch_data(ohlcv)
    candles = clean_data(candles)

    if len(candles) < 50:
        logger.error("Not enough clean candles (%d). Aborting.", len(candles))
        return

    results = backtest_all(candles)
    print_comparison(results)

    best_strategy, best_result, best_report = results[0]

    if best_report.sharpe_ratio < settings.min_sharpe_to_trade:
        print(
            f"  No paper trade — best Sharpe {best_report.sharpe_ratio:.4f} "
            f"< minimum {settings.min_sharpe_to_trade}"
        )
        logger.warning(
            "Best Sharpe %.4f below minimum %.1f — no paper trading.",
            best_report.sharpe_ratio,
            settings.min_sharpe_to_trade,
        )
        return

    if best_result.num_trades == 0:
        print("  No paper trade — strategy had zero trades on backtest data.")
        logger.warning("Best strategy had zero trades.")
        return

    print(f"  Selected : {best_strategy.name}")
    print(f"  Starting {settings.run_hours}h paper trade...\n")
    paper_trade(best_strategy, ohlcv)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    run_pipeline()
