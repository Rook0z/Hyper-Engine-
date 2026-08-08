from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

import numpy as np
import pandas as pd

from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# TYPING HELPERS
# ──────────────────────────────────────────────────────────────


@runtime_checkable
class _CandleBasedStrategy(Protocol):
    """
    Structural type for strategies that need full OHLCV data instead of
    just closes (e.g. VWAPStrategy.generate_signal_from_candles) —
    used only so mypy can narrow self.strategy's type in
    _generate_signals() below.

    @runtime_checkable makes isinstance(x, _CandleBasedStrategy) check
    for the presence of a callable generate_signal_from_candles
    attribute, i.e. the exact same test hasattr(x,
    "generate_signal_from_candles") performed before — this is a
    typing-only change, not a behavior change.
    """

    def generate_signal_from_candles(
        self, candles: list[list[float]]
    ) -> str: ...


# ──────────────────────────────────────────────────────────────
# DATA CLASSES
# ──────────────────────────────────────────────────────────────


@dataclass
class Trade:
    """One completed round-trip trade (buy → sell)."""

    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float


@dataclass
class BacktestResult:
    """Full result of a backtest run."""

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

    # ── Metadata (added for reporting; never used in trade simulation) ──
    # These are informational only — they describe the conditions the
    # backtest ran under, so PerformanceAnalyser can compute metrics
    # like Estimated Slippage Cost and Exposure Time without having to
    # assume anything about equity_curve[0] or re-derive the time span
    # from trades alone. Setting them does not affect pricing, fills,
    # or any simulation output above.
    slippage_pct: float = 0.0
    backtest_start_time: int = 0
    backtest_end_time: int = 0
    backtest_initial_capital: float = 0.0

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
    Simulates a strategy on historical OHLCV data using pandas.

    Args:
        strategy:        Any strategy inheriting from BaseStrategy
        initial_capital: Starting portfolio value in USDC
        position_size:   Size of each trade in base currency
        slippage_pct:    Slippage as fraction of fill price
        symbol:          Asset being tested

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
        Runs the backtest on a list of OHLCV candles using pandas.

        Args:
            candles: List of [timestamp, open, high, low, close, volume]
                     Sorted oldest → newest.

        Returns:
            BacktestResult with all trades and metrics.
        """
        if len(candles) < 2:
            logger.warning("Not enough candles — need at least 2.")
            return BacktestResult(
                strategy_name=self.strategy.name,
                symbol=self.symbol,
                candles_tested=len(candles),
                slippage_pct=self.slippage_pct,
                backtest_initial_capital=self.initial_capital,
                backtest_start_time=int(candles[0][0]) if candles else 0,
                backtest_end_time=int(candles[-1][0]) if candles else 0,
            )

        df = self._build_dataframe(candles)

        df = self._generate_signals(df)

        df["exec_signal"] = df["signal"].shift(1)
        df["fill_price"] = df["open"]

        trades = self._simulate_trades(df)

        start_time = int(df["timestamp"].iloc[0])
        end_time = int(df["timestamp"].iloc[-1])
        result = self._build_result(trades, len(candles), start_time, end_time)

        logger.info(
            "Backtest complete: %d trades, PnL: %+.2f, win rate: %.1f%%",
            result.num_trades,
            result.total_pnl,
            result.win_rate * 100,
        )
        return result

    def summary_by_day(self, result: BacktestResult) -> pd.DataFrame:
        """
        Returns a DataFrame with daily PnL, trade count, and win rate.
        Useful for spotting patterns.

        Args:
            result: BacktestResult from run()

        Returns:
            DataFrame with columns: date, num_trades, total_pnl, win_rate
        """
        if not result.trades:
            return pd.DataFrame(columns=["date", "num_trades", "total_pnl", "win_rate"])

        records = [
            {
                "date": pd.to_datetime(t.entry_time, unit="ms").date(),
                "pnl": t.pnl,
                "win": 1 if t.pnl > 0 else 0,
            }
            for t in result.trades
        ]
        trades_df = pd.DataFrame(records)

        daily = (
            trades_df.groupby("date")
            .agg(
                num_trades=("pnl", "count"),
                total_pnl=("pnl", "sum"),
                win_rate=("win", "mean"),
            )
            .reset_index()
        )

        return daily

    def equity_as_series(self, result: BacktestResult) -> pd.Series:
        """
        Returns the equity curve as a pandas Series for resampling.

        Useful for plotting or resampling to weekly/monthly performance.

        Args:
            result: BacktestResult from run()

        Returns:
            pd.Series with equity values indexed by trade number.
        """
        return pd.Series(result.equity_curve, name="equity")

    # ──────────────────────────────────────────────────────────────
    # PRIVATE
    # ──────────────────────────────────────────────────────────────

    def _build_dataframe(self, candles: list[list]) -> pd.DataFrame:
        """
        Converts raw OHLCV candles to a pandas DataFrame.

        Columns: timestamp, open, high, low, close, volume
        Index:   RangeIndex (0, 1, 2, ...)
        """
        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = df["timestamp"].astype(np.int64)
        df[["open", "high", "low", "close", "volume"]] = df[
            ["open", "high", "low", "close", "volume"]
        ].astype(np.float64)
        return df

    def _generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        For each row i, calls the strategy's signal method and stores the
        result in df["signal"].

        Strategies that only need close prices implement
        generate_signal(closes). Strategies that need full OHLCV data
        (e.g. VWAP) implement generate_signal_from_candles(candles) instead.
        This is detected via duck typing so close-only strategies
        (EMA, RSI, Bollinger) are completely unaffected.

        signal values: "BUY", "SELL", "HOLD"
        """
        closes = df["close"].tolist()
        signals = []

        use_candles = isinstance(self.strategy, _CandleBasedStrategy)
        candles: list[list[float]] | None = (
            df[["timestamp", "open", "high", "low", "close", "volume"]].values.tolist()
            if use_candles
            else None
        )

        for i in range(len(closes)):
            if (
                use_candles
                and candles is not None
                and isinstance(self.strategy, _CandleBasedStrategy)
            ):
                signal = self.strategy.generate_signal_from_candles(candles[: i + 1])
            else:
                signal = self.strategy.generate_signal(closes[: i + 1])
            signals.append(signal)

        df["signal"] = signals
        return df

    def _simulate_trades(self, df: pd.DataFrame) -> list[Trade]:
        """
        Simulates trades based on execution signals.

        Uses df.itertuples() — faster than iterrows() for row iteration.
        Slippage applied at fill: buys fill above, sells fill below.

        Position state:
            in_position = False → look for BUY
            in_position = True  → look for SELL
        """
        trades: list[Trade] = []
        in_position = False
        entry_price = 0.0
        entry_time = 0

        for row in df.itertuples():
            exec_signal = getattr(row, "exec_signal", None)
            # pandas-stubs types itertuples() row fields as a very broad
            # scalar union (it can't know per-field dtypes statically).
            # At runtime these are always real numpy floats/ints from
            # _build_dataframe()'s explicit astype() calls — cast(Any, ...)
            # narrows for mypy without changing the runtime value passed
            # to float()/int().
            fill_price = float(cast(Any, row.fill_price))
            ts = int(cast(Any, row.timestamp))

            if pd.isna(exec_signal):
                continue

            if exec_signal == BaseStrategy.BUY and not in_position:
                entry_price = fill_price * (1 + self.slippage_pct)
                entry_time = ts
                in_position = True

            elif exec_signal == BaseStrategy.SELL and in_position:
                exit_price = fill_price * (1 - self.slippage_pct)
                pnl = (exit_price - entry_price) * self.position_size
                pnl_pct = (exit_price - entry_price) / entry_price

                trades.append(
                    Trade(
                        entry_time=entry_time,
                        exit_time=ts,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        size=self.position_size,
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                    )
                )
                in_position = False

        if in_position and len(df) > 0:
            last = df.iloc[-1]
            exit_price = float(cast(Any, last["close"])) * (1 - self.slippage_pct)
            pnl = (exit_price - entry_price) * self.position_size
            pnl_pct = (exit_price - entry_price) / entry_price
            trades.append(
                Trade(
                    entry_time=entry_time,
                    exit_time=int(cast(Any, last["timestamp"])),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    size=self.position_size,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                )
            )

        return trades

    def _build_result(
        self,
        trades: list[Trade],
        candles_tested: int,
        start_time: int = 0,
        end_time: int = 0,
    ) -> BacktestResult:
        if not trades:
            return BacktestResult(
                strategy_name=self.strategy.name,
                symbol=self.symbol,
                candles_tested=candles_tested,
                equity_curve=[self.initial_capital],
                slippage_pct=self.slippage_pct,
                backtest_initial_capital=self.initial_capital,
                backtest_start_time=start_time,
                backtest_end_time=end_time,
            )

        pnl_arr = np.array([t.pnl for t in trades], dtype=np.float64)

        total_pnl = float(np.sum(pnl_arr))
        win_rate = float(np.sum(pnl_arr > 0) / len(pnl_arr))

        gross_profit = float(np.sum(pnl_arr[pnl_arr > 0]))
        gross_loss = float(np.abs(np.sum(pnl_arr[pnl_arr < 0])))
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else float("inf")
            if gross_profit > 0
            else 0.0
        )

        equity_curve = [self.initial_capital] + list(
            self.initial_capital + np.cumsum(pnl_arr)
        )

        eq_arr = np.array(equity_curve, dtype=np.float64)
        peak = np.maximum.accumulate(eq_arr)
        drawdowns = (peak - eq_arr) / peak
        max_dd = float(np.max(drawdowns))

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
            slippage_pct=self.slippage_pct,
            backtest_initial_capital=self.initial_capital,
            backtest_start_time=start_time,
            backtest_end_time=end_time,
        )

    def _calculate_max_drawdown(self, equity_curve: list[float]) -> float:
        if len(equity_curve) < 2:
            return 0.0
        arr = np.array(equity_curve, dtype=np.float64)
        peak = np.maximum.accumulate(arr)
        return float(np.max((peak - arr) / peak))
