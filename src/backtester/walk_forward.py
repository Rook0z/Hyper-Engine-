"""
Walk-forward testing.

Repeated out-of-sample testing across a chronological sequence of
rolling train/test window pairs, sliding forward through the full
history — as opposed to out_of_sample.py's single 70/30-style split.
Each window selects/configures a strategy using ONLY that window's own
training slice (see strategy_runner.run_walk_forward_test(), which
reuses backtest_all() and _build_strategy() exactly as
out_of_sample.py's single-split version does), then evaluates a
completely fresh instance of the winning strategy on that window's
disjoint, immediately-following test slice. Results are aggregated
across every window's test period.

This module only handles the (pure, strategy-agnostic) window
generation and result bundling/aggregation — the actual
train-then-test orchestration per window lives in
strategy_runner.run_walk_forward_test().
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backtester.backtester import BacktestResult
from backtester.performance import PerformanceReport


@dataclass
class WalkForwardWindow:
    """
    One rolling train/test window. train is strictly earlier than
    test, and the two are disjoint (test starts exactly where train
    ends) — the same leakage-prevention guarantee as
    out_of_sample.OutOfSampleSplit, applied per window.
    """

    window_index: int
    train: list[list]
    test: list[list]

    @property
    def train_start_timestamp(self) -> int:
        return int(self.train[0][0])

    @property
    def test_start_timestamp(self) -> int:
        return int(self.test[0][0])

    @property
    def test_end_timestamp(self) -> int:
        return int(self.test[-1][0])


def generate_walk_forward_windows(
    candles: list[list],
    train_window_size: int,
    test_window_size: int,
    step_size: int | None = None,
) -> list[WalkForwardWindow]:
    """
    Generates a chronological sequence of rolling train/test windows.

    For window i: train = candles[start : start+train_window_size],
    test = candles[start+train_window_size : start+train_window_size+test_window_size],
    where start advances by step_size each iteration (default:
    step_size == test_window_size, so consecutive test periods tile
    the data with no gaps or overlaps between windows — the standard,
    non-overlapping walk-forward configuration). A smaller step_size
    produces overlapping test periods across windows (more windows,
    more statistical power, at the cost of each candle potentially
    being evaluated out-of-sample more than once) — a deliberate
    trade-off left to the caller, not a bug.

    Within EVERY window, train is strictly earlier than test and the
    two never overlap (test starts exactly where that window's train
    ends) — this is the leakage-prevention guarantee, identical in
    spirit to out_of_sample.split_in_out_of_sample(), just repeated
    across a rolling sequence. Train windows ARE allowed to overlap
    each other across different steps (window 2's train may reuse some
    of window 1's train candles) — that's normal, expected behavior
    for rolling walk-forward analysis, not leakage: leakage
    specifically means a window's OWN test data influencing its OWN
    training, which never happens here.

    Args:
        candles: Full OHLCV history, sorted oldest -> newest.
        train_window_size: Number of candles per training window.
        test_window_size: Number of candles per test window.
        step_size: How far the window start advances each iteration.
                   Defaults to test_window_size (non-overlapping test
                   periods). Must be > 0 if given.

    Returns:
        List of WalkForwardWindow, oldest first. Empty if there isn't
        enough data for even one full window — not an error condition
        on its own; see strategy_runner.run_walk_forward_test() for
        how the orchestration layer handles that.

    Raises:
        ValueError: if train_window_size, test_window_size, or
                    step_size (when given) is not a positive integer.
    """
    if train_window_size <= 0:
        raise ValueError(f"train_window_size must be positive, got {train_window_size}")
    if test_window_size <= 0:
        raise ValueError(f"test_window_size must be positive, got {test_window_size}")
    if step_size is None:
        step_size = test_window_size
    if step_size <= 0:
        raise ValueError(f"step_size must be positive, got {step_size}")

    windows: list[WalkForwardWindow] = []
    start = 0
    window_index = 0
    window_span = train_window_size + test_window_size

    while start + window_span <= len(candles):
        train = candles[start : start + train_window_size]
        test = candles[start + train_window_size : start + window_span]
        windows.append(
            WalkForwardWindow(window_index=window_index, train=train, test=test)
        )
        start += step_size
        window_index += 1

    return windows


@dataclass
class WalkForwardWindowResult:
    """Selection + evaluation result for a single walk-forward window."""

    window: WalkForwardWindow
    strategy_name: str
    train_result: BacktestResult
    train_report: PerformanceReport
    test_result: BacktestResult
    test_report: PerformanceReport


@dataclass
class WalkForwardReport:
    """
    Aggregated result of a full walk-forward test: one
    WalkForwardWindowResult per rolling window, plus summary statistics
    computed across every window's TEST (out-of-sample) period only —
    train-period results are kept per-window for inspection but never
    folded into the aggregate, since the aggregate is meant to answer
    "how would this approach have performed on data it never
    selected/trained on".
    """

    window_results: list[WalkForwardWindowResult] = field(default_factory=list)

    @property
    def num_windows(self) -> int:
        return len(self.window_results)

    @property
    def total_test_trades(self) -> int:
        return sum(w.test_report.num_trades for w in self.window_results)

    @property
    def total_test_pnl(self) -> float:
        return sum(w.test_report.total_pnl for w in self.window_results)

    @property
    def average_test_sharpe(self) -> float:
        if not self.window_results:
            return 0.0
        return sum(w.test_report.sharpe_ratio for w in self.window_results) / len(
            self.window_results
        )

    @property
    def average_test_win_rate(self) -> float:
        if not self.window_results:
            return 0.0
        return sum(w.test_report.win_rate for w in self.window_results) / len(
            self.window_results
        )

    @property
    def profitable_window_count(self) -> int:
        """Number of windows whose test period had positive total PnL —
        a walk-forward "consistency" metric distinct from total PnL
        (a strategy profitable overall but only via one huge window
        looks very different from one that's consistently profitable)."""
        return sum(1 for w in self.window_results if w.test_report.total_pnl > 0)

    def combined_test_equity_curve(self, initial_capital: float) -> list[float]:
        """
        Chains every window's test-period equity curve into one
        continuous curve, as if each window's test period were traded
        back-to-back starting from initial_capital. Each window's own
        equity_curve is offset relative to its own baseline (see
        Backtester._build_result()); this rebases each window's
        deltas onto the running total carried over from the previous
        window, rather than re-simulating anything.
        """
        combined = [initial_capital]
        running = initial_capital
        for w in self.window_results:
            curve = w.test_result.equity_curve
            if not curve:
                continue
            baseline = curve[0]
            for value in curve[1:]:
                delta = value - baseline
                combined.append(running + delta)
            running = combined[-1]
        return combined

    def __str__(self) -> str:
        lines = [
            "",
            "=" * 65,
            "  WALK-FORWARD TEST",
            "=" * 65,
            f"  Windows              : {self.num_windows}",
            f"  Total test trades    : {self.total_test_trades}",
            f"  Total test PnL       : {self.total_test_pnl:+.2f}",
            f"  Average test Sharpe  : {self.average_test_sharpe:.4f}",
            f"  Average test winrate : {self.average_test_win_rate:.1%}",
            f"  Profitable windows   : "
            f"{self.profitable_window_count}/{self.num_windows}",
            "-" * 65,
            f"  {'#':>3} {'Strategy':<20} {'TrainTr':>8} {'TestTr':>7} "
            f"{'TestPnL':>10} {'TestSharpe':>11}",
        ]
        for w in self.window_results:
            lines.append(
                f"  {w.window.window_index:>3} {w.strategy_name:<20} "
                f"{w.train_report.num_trades:>8} {w.test_report.num_trades:>7} "
                f"{w.test_report.total_pnl:>+10.2f} {w.test_report.sharpe_ratio:>11.4f}"
            )
        lines.append("=" * 65)
        lines.append("")
        return "\n".join(lines)
