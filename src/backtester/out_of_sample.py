"""
Out-of-sample (OOS) testing.

Strategy selection happens using ONLY the in-sample split; the winning
strategy is then evaluated, completely unmodified, on a strictly
later, disjoint out-of-sample split it never influenced the selection
of. This is the standard defense against overfitting a strategy choice
to one historical window — good in-sample performance that collapses
out-of-sample is the classic sign of curve-fitting.

This module only handles the (pure, strategy-agnostic) data split and
result bundling. The actual "select on in-sample, evaluate on
out-of-sample" orchestration lives in strategy_runner.run_out_of_sample_test(),
which reuses backtest_all(), _build_strategy(), Backtester, and
PerformanceAnalyser directly — nothing new is introduced there either.
"""

from __future__ import annotations

from dataclasses import dataclass

from backtester.backtester import BacktestResult
from backtester.performance import PerformanceReport


@dataclass
class OutOfSampleSplit:
    """
    A chronological, non-overlapping in-sample / out-of-sample candle
    split. in_sample is strictly earlier than out_of_sample — every
    timestamp in out_of_sample is greater than every timestamp in
    in_sample, with no shared candles between the two.
    """

    in_sample: list[list]
    out_of_sample: list[list]
    split_index: int
    split_timestamp: int


def split_in_out_of_sample(
    candles: list[list],
    in_sample_ratio: float = 0.7,
) -> OutOfSampleSplit:
    """
    Splits candles STRICTLY chronologically into an in-sample (earlier)
    period and an out-of-sample (later) period.

    Deliberately never shuffles or randomly samples: candles are
    time-series data, and a random split would let future information
    leak into the "in-sample" period (a candle from later in time could
    end up in-sample while an earlier one ends up out-of-sample),
    defeating the entire purpose of out-of-sample testing. The split is
    always a single cut point — everything before it is in_sample,
    everything from it onward is out_of_sample.

    Args:
        candles: OHLCV candles, sorted oldest -> newest (the same
                 ordering convention Backtester.run() assumes).
        in_sample_ratio: Fraction of candles allocated to the
                         in-sample period. Must be strictly between 0
                         and 1. Default 0.7 (70% in-sample, 30%
                         out-of-sample) — a common default split.

    Returns:
        OutOfSampleSplit with disjoint in_sample/out_of_sample lists.

    Raises:
        ValueError: if in_sample_ratio is not in (0, 1), or there
                    aren't enough candles to form a non-empty period on
                    both sides of the split.
    """
    if not 0 < in_sample_ratio < 1:
        raise ValueError(
            f"in_sample_ratio must be strictly between 0 and 1, got {in_sample_ratio}"
        )
    if len(candles) < 2:
        raise ValueError(
            f"Need at least 2 candles to form both a non-empty in-sample "
            f"and out-of-sample period, got {len(candles)}."
        )

    split_index = int(len(candles) * in_sample_ratio)
    # Clamp so both sides are guaranteed non-empty even at extreme
    # ratios (e.g. 0.99 with only 3 candles) rather than silently
    # producing an empty out-of-sample period.
    split_index = max(1, min(split_index, len(candles) - 1))

    in_sample = candles[:split_index]
    out_of_sample = candles[split_index:]

    return OutOfSampleSplit(
        in_sample=in_sample,
        out_of_sample=out_of_sample,
        split_index=split_index,
        split_timestamp=int(out_of_sample[0][0]),
    )


@dataclass
class OutOfSampleReport:
    """
    Full result of an out-of-sample test: the same strategy (same
    class, same configuration, but never the same mutable instance —
    see strategy_runner.run_out_of_sample_test()), evaluated separately
    on two disjoint, chronologically-ordered periods.
    """

    strategy_name: str
    split: OutOfSampleSplit
    in_sample_result: BacktestResult
    in_sample_report: PerformanceReport
    out_of_sample_result: BacktestResult
    out_of_sample_report: PerformanceReport

    def __str__(self) -> str:
        isr = self.in_sample_report
        oos = self.out_of_sample_report
        return (
            f"\n{'=' * 65}\n"
            f"  OUT-OF-SAMPLE TEST — {self.strategy_name}\n"
            f"{'=' * 65}\n"
            f"  In-sample candles     : {len(self.split.in_sample)}\n"
            f"  Out-of-sample candles : {len(self.split.out_of_sample)}\n"
            f"  Split timestamp       : {self.split.split_timestamp}\n"
            f"{'-' * 65}\n"
            f"  {'Metric':<20} {'In-Sample':>18} {'Out-of-Sample':>18}\n"
            f"  {'Trades':<20} {isr.num_trades:>18} {oos.num_trades:>18}\n"
            f"  {'Total PnL':<20} {isr.total_pnl:>+18.2f} {oos.total_pnl:>+18.2f}\n"
            f"  {'Win rate':<20} {isr.win_rate:>17.1%} {oos.win_rate:>17.1%}\n"
            f"  {'Sharpe ratio':<20} {isr.sharpe_ratio:>18.4f} {oos.sharpe_ratio:>18.4f}\n"
            f"  {'Max drawdown':<20} {isr.max_drawdown:>17.1%} {oos.max_drawdown:>17.1%}\n"
            f"  {'Profit factor':<20} {isr.profit_factor:>18.2f} {oos.profit_factor:>18.2f}\n"
            f"{'=' * 65}\n"
        )
