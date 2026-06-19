from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# DATA CLASSES
# ──────────────────────────────────────────────────────────────


@dataclass
class Trade:
    """
    Represents one completed round-trip trade (buy → sell).

    Attributes:
        entry_time:  timestamp of entry candle (ms)
        exit_time:   timestamp of exit candle (ms)
        entry_price: fill price on entry (with slippage)
        exit_price:  fill price on exit (with slippage)
        size:        position size in base currency (e.g. 0.001 BTC)
        pnl:         profit or loss in quote currency (e.g. USDC)
        pnl_pct:     profit or loss as percentage of entry value
    """

    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float


@dataclass
class BacktestResult:
    """
    Full result of a backtest run.

    Attributes:
        trades:          list of all completed trades
        total_pnl:       sum of all trade PnLs
        win_rate:        fraction of trades that were profitable
        profit_factor:   gross profit / gross loss
        max_drawdown:    largest peak-to-trough equity decline (as fraction)
        num_trades:      total number of completed trades
        equity_curve:    portfolio value after each trade
        strategy_name:   name of the strategy that was tested
        symbol:          asset that was tested
        candles_tested:  number of candles in the backtest
    """

    trades: list[Trade] = field(default_factory=list)
    total_pnl: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    num_trades: int = 0
    equity_curve: list[float] = field(default_factory=list)
    strategy_name: str = ""
    symbol: str = ""
    candles_tested: int = 0

    def __str__(self) -> str:
        return (
            f"BacktestResult({self.strategy_name} on {self.symbol})\n"
            f"  Candles tested : {self.candles_tested}\n"
            f"  Trades         : {self.num_trades}\n"
            f"  Total PnL      : {self.total_pnl:+.2f} USDC\n"
            f"  Win rate       : {self.win_rate:.1%}\n"
            f"  Profit factor  : {self.profit_factor:.2f}\n"
            f"  Max drawdown   : {self.max_drawdown:.1%}\n"
        )


# ──────────────────────────────────────────────────────────────
# BACKTESTER
# ──────────────────────────────────────────────────────────────


class Backtester:
    """
    Simulates a strategy on historical OHLCV data.

    Args:
        strategy:     Any strategy that inherits from BaseStrategy
        initial_capital: Starting portfolio value in USDC (default 10000)
        position_size:   Size of each trade in base currency (default 0.001 BTC)
        slippage_pct:    Slippage as fraction of fill price (default 0.001 = 0.1%)
        symbol:          Asset being tested (for reporting only)

    Usage:
        strategy = EMAStrategy(fast_period=9, slow_period=21)
        backtester = Backtester(strategy=strategy)
        candles = provider.fetch_range("BTC", "1h", start, end)
        result = backtester.run(candles)
        print(result)
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_capital: float = 10_000.0,
        position_size: float = 0.001,
        slippage_pct: float = 0.001,
        symbol: str = "BTC",
    ) -> None:
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.position_size = position_size
        self.slippage_pct = slippage_pct
        self.symbol = symbol

    def run(self, candles: list[list]) -> BacktestResult:
        """
        Runs the backtest on a list of OHLCV candles.

        Args:
            candles: List of [timestamp, open, high, low, close, volume]
                     Must be sorted oldest → newest.
                     Minimum: strategy.min_periods + 1 candles.

        Returns:
            BacktestResult with all trades and performance metrics.

        Notes:
            - Signal is generated using closes up to candle[i]
            - Trade is filled at candle[i+1]'s open (next bar execution)
            - Last candle cannot generate a filled trade (no next bar)
        """
        if len(candles) < 2:
            logger.warning("Not enough candles to backtest — need at least 2.")
            return BacktestResult(
                strategy_name=self.strategy.name,
                symbol=self.symbol,
                candles_tested=len(candles),
            )

        trades: list[Trade] = []
        equity = self.initial_capital
        equity_curve: list[float] = [equity]

        in_position = False
        entry_price: float = 0.0
        entry_time: int = 0

        closes: list[float] = []

        # Walk through candles one by one — simulate live trading
        for i, candle in enumerate(candles):
            timestamp = candle[0]
            open_price = candle[1]
            close_price = candle[4]

            closes.append(close_price)

            # Cannot trade on the last candle — no next bar to fill on
            if i == len(candles) - 1:
                break

            # Get signal using all closes up to and including this candle
            signal = self.strategy.generate_signal(closes)

            # Next candle's open is our fill price
            next_open = candles[i + 1][1]
            next_time = candles[i + 1][0]

            if signal == BaseStrategy.BUY and not in_position:
                # Enter long — buy at next open with slippage
                entry_price = self._apply_slippage(next_open, is_buy=True)
                entry_time = next_time
                in_position = True
                logger.debug(
                    "BUY at %.2f (candle %d, time %d)", entry_price, i + 1, entry_time
                )

            elif signal == BaseStrategy.SELL and in_position:
                # Exit long — sell at next open with slippage
                exit_price = self._apply_slippage(next_open, is_buy=False)
                exit_time = next_time

                trade = self._record_trade(
                    entry_time,
                    exit_time,
                    entry_price,
                    exit_price,
                )
                trades.append(trade)
                equity += trade.pnl
                equity_curve.append(equity)

                in_position = False
                logger.debug(
                    "SELL at %.2f (candle %d) — PnL: %+.2f",
                    exit_price,
                    i + 1,
                    trade.pnl,
                )

        # Force close any open position at last candle's close
        if in_position and len(candles) > 0:
            last_candle = candles[-1]
            exit_price = self._apply_slippage(last_candle[4], is_buy=False)
            trade = self._record_trade(
                entry_time,
                last_candle[0],
                entry_price,
                exit_price,
            )
            trades.append(trade)
            equity += trade.pnl
            equity_curve.append(equity)
            logger.debug("Force closed at %.2f — PnL: %+.2f", exit_price, trade.pnl)

        result = self._build_result(trades, equity_curve, len(candles))
        logger.info(
            "Backtest complete: %d trades, total PnL: %+.2f, win rate: %.1%%",
            result.num_trades,
            result.total_pnl,
            result.win_rate * 100,
        )
        return result

    # ──────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────

    def _apply_slippage(self, price: float, is_buy: bool) -> float:
        """
        Applies slippage to a fill price.

        Buys fill slightly above the quoted price (you pay more).
        Sells fill slightly below the quoted price (you receive less).

        This makes backtests more realistic — in live trading you
        rarely fill at exactly the quoted price.
        """
        if is_buy:
            return price * (1 + self.slippage_pct)
        return price * (1 - self.slippage_pct)

    def _record_trade(
        self,
        entry_time: int,
        exit_time: int,
        entry_price: float,
        exit_price: float,
    ) -> Trade:
        """Creates a Trade record with PnL calculated."""
        pnl = (exit_price - entry_price) * self.position_size
        pnl_pct = (exit_price - entry_price) / entry_price
        return Trade(
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            size=self.position_size,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )

    def _build_result(
        self,
        trades: list[Trade],
        equity_curve: list[float],
        candles_tested: int,
    ) -> BacktestResult:
        """Computes all summary statistics from completed trades."""
        if not trades:
            return BacktestResult(
                strategy_name=self.strategy.name,
                symbol=self.symbol,
                candles_tested=candles_tested,
                equity_curve=equity_curve,
            )

        pnl_list = [t.pnl for t in trades]
        total_pnl = sum(pnl_list)

        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p < 0]

        win_rate = len(wins) / len(trades)

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else float("inf")
            if gross_profit > 0
            else 0.0
        )

        max_dd = self._calculate_max_drawdown(equity_curve)

        return BacktestResult(
            trades=trades,
            total_pnl=total_pnl,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_dd,
            num_trades=len(trades),
            equity_curve=equity_curve,
            strategy_name=self.strategy.name,
            symbol=self.symbol,
            candles_tested=candles_tested,
        )

    def _calculate_max_drawdown(self, equity_curve: list[float]) -> float:
        """Maximum peak-to-trough decline in equity curve."""
        if len(equity_curve) < 2:
            return 0.0
        peak = equity_curve[0]
        max_dd = 0.0
        for value in equity_curve[1:]:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd
