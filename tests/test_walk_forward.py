"""
Tests for backtester/walk_forward.py — window generation, leakage
prevention, and report aggregation. Pure, strategy-agnostic; the
orchestration (run_walk_forward_test) is covered in
test_strategy_runner.py.
"""

from backtester.backtester import BacktestResult
from backtester.performance import PerformanceReport
from backtester.walk_forward import (
    WalkForwardReport,
    WalkForwardWindow,
    WalkForwardWindowResult,
    generate_walk_forward_windows,
)

import pytest


def make_candle(timestamp, close):
    return [timestamp, close, close * 1.01, close * 0.99, close, 100.0]


def make_candles(n, start_ts=1_000_000_000_000, interval_ms=3_600_000):
    return [make_candle(start_ts + i * interval_ms, 100.0 + i) for i in range(n)]


# ──────────────────────────────────────────────────────────────
# WINDOW GENERATION — BASIC CORRECTNESS
# ──────────────────────────────────────────────────────────────


def test_generates_correct_number_of_windows_default_step():
    # 100 candles, train=20, test=10 -> step defaults to 10.
    # Windows fit while start + 30 <= 100: start = 0,10,...,70 -> 8 windows.
    candles = make_candles(100)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10
    )
    assert len(windows) == 8


def test_window_train_and_test_sizes_correct():
    candles = make_candles(100)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10
    )
    for w in windows:
        assert len(w.train) == 20
        assert len(w.test) == 10


def test_window_index_increments_from_zero():
    candles = make_candles(60)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10
    )
    assert [w.window_index for w in windows] == list(range(len(windows)))


def test_windows_slide_forward_by_step_size():
    candles = make_candles(100)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10, step_size=15
    )
    # window 0 train starts at candles[0]; window 1 train starts at candles[15]
    assert windows[0].train[0] == candles[0]
    assert windows[1].train[0] == candles[15]


def test_timestamp_properties():
    candles = make_candles(40)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10
    )
    w = windows[0]
    assert w.train_start_timestamp == candles[0][0]
    assert w.test_start_timestamp == candles[20][0]
    assert w.test_end_timestamp == candles[29][0]


# ──────────────────────────────────────────────────────────────
# DATA LEAKAGE PREVENTION
# ──────────────────────────────────────────────────────────────


def test_train_strictly_precedes_test_within_every_window():
    candles = make_candles(100)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10, step_size=5
    )
    for w in windows:
        max_train_ts = max(c[0] for c in w.train)
        min_test_ts = min(c[0] for c in w.test)
        assert min_test_ts > max_train_ts


def test_train_and_test_disjoint_within_every_window():
    candles = make_candles(100)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10, step_size=5
    )
    for w in windows:
        train_ts = {c[0] for c in w.train}
        test_ts = {c[0] for c in w.test}
        assert train_ts.isdisjoint(test_ts)


def test_test_starts_immediately_after_train_within_window():
    candles = make_candles(60)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10
    )
    for w in windows:
        boundary_index = candles.index(w.train[-1])
        assert candles[boundary_index + 1] == w.test[0]


def test_default_step_produces_non_overlapping_test_periods_across_windows():
    """The standard, non-overlapping walk-forward configuration: no
    candle is ever evaluated out-of-sample by more than one window."""
    candles = make_candles(100)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10
    )
    seen_test_ts: set = set()
    for w in windows:
        test_ts = {c[0] for c in w.test}
        assert test_ts.isdisjoint(seen_test_ts)
        seen_test_ts |= test_ts


def test_smaller_step_size_allows_overlapping_test_periods():
    """A deliberate trade-off, not a bug: a step smaller than
    test_window_size means consecutive windows' test periods can
    overlap."""
    candles = make_candles(100)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10, step_size=5
    )
    test_ts_0 = {c[0] for c in windows[0].test}
    test_ts_1 = {c[0] for c in windows[1].test}
    assert not test_ts_0.isdisjoint(test_ts_1)


def test_train_windows_may_legitimately_overlap_across_steps():
    """Not leakage: window 2's train reusing some of window 1's train
    candles is normal, expected rolling walk-forward behavior."""
    candles = make_candles(100)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10, step_size=5
    )
    train_ts_0 = {c[0] for c in windows[0].train}
    train_ts_1 = {c[0] for c in windows[1].train}
    assert not train_ts_0.isdisjoint(train_ts_1)


# ──────────────────────────────────────────────────────────────
# VALIDATION / EDGE CASES
# ──────────────────────────────────────────────────────────────


def test_insufficient_data_returns_empty_list():
    candles = make_candles(10)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10
    )
    assert windows == []


def test_train_window_size_zero_raises():
    with pytest.raises(ValueError, match="train_window_size"):
        generate_walk_forward_windows(
            make_candles(50), train_window_size=0, test_window_size=10
        )


def test_train_window_size_negative_raises():
    with pytest.raises(ValueError, match="train_window_size"):
        generate_walk_forward_windows(
            make_candles(50), train_window_size=-5, test_window_size=10
        )


def test_test_window_size_zero_raises():
    with pytest.raises(ValueError, match="test_window_size"):
        generate_walk_forward_windows(
            make_candles(50), train_window_size=10, test_window_size=0
        )


def test_step_size_zero_raises():
    with pytest.raises(ValueError, match="step_size"):
        generate_walk_forward_windows(
            make_candles(50), train_window_size=10, test_window_size=10, step_size=0
        )


def test_step_size_negative_raises():
    with pytest.raises(ValueError, match="step_size"):
        generate_walk_forward_windows(
            make_candles(50), train_window_size=10, test_window_size=10, step_size=-1
        )


def test_exact_fit_produces_exactly_one_window():
    candles = make_candles(30)
    windows = generate_walk_forward_windows(
        candles, train_window_size=20, test_window_size=10
    )
    assert len(windows) == 1
    assert windows[0].train + windows[0].test == candles


# ──────────────────────────────────────────────────────────────
# WalkForwardReport AGGREGATION
# ──────────────────────────────────────────────────────────────


def _make_report(num_trades, total_pnl, sharpe, win_rate):
    return PerformanceReport(
        strategy_name="Test",
        symbol="BTC",
        num_trades=num_trades,
        total_pnl=total_pnl,
        win_rate=win_rate,
        profit_factor=1.0,
        max_drawdown=0.1,
        sharpe_ratio=sharpe,
        sortino_ratio=sharpe,
        calmar_ratio=1.0,
        avg_win=1.0,
        avg_loss=-1.0,
        expectancy=0.1,
        gross_profit=abs(total_pnl),
        gross_loss=0.0,
        candles_tested=100,
    )


def _make_window_result(index, test_pnl, test_sharpe, test_trades, equity_curve):
    window = WalkForwardWindow(
        window_index=index,
        train=make_candles(20, start_ts=index * 100_000),
        test=make_candles(10, start_ts=index * 100_000 + 20_000),
    )
    train_report = _make_report(5, 10.0, 1.0, 0.6)
    test_report = _make_report(test_trades, test_pnl, test_sharpe, 0.5)
    train_result = BacktestResult(strategy_name="Test", symbol="BTC", candles_tested=20)
    test_result = BacktestResult(
        strategy_name="Test",
        symbol="BTC",
        candles_tested=10,
        equity_curve=equity_curve,
    )
    return WalkForwardWindowResult(
        window=window,
        strategy_name="Test",
        train_result=train_result,
        train_report=train_report,
        test_result=test_result,
        test_report=test_report,
    )


def test_empty_report_aggregates_to_zero():
    report = WalkForwardReport(window_results=[])
    assert report.num_windows == 0
    assert report.total_test_trades == 0
    assert report.total_test_pnl == 0.0
    assert report.average_test_sharpe == 0.0
    assert report.average_test_win_rate == 0.0
    assert report.profitable_window_count == 0


def test_total_test_trades_sums_across_windows():
    results = [
        _make_window_result(0, 10.0, 1.0, 3, [10_000.0, 10_010.0]),
        _make_window_result(1, -5.0, 0.5, 2, [10_000.0, 9_995.0]),
    ]
    report = WalkForwardReport(window_results=results)
    assert report.total_test_trades == 5


def test_total_test_pnl_sums_across_windows():
    results = [
        _make_window_result(0, 10.0, 1.0, 3, [10_000.0, 10_010.0]),
        _make_window_result(1, -5.0, 0.5, 2, [10_000.0, 9_995.0]),
    ]
    report = WalkForwardReport(window_results=results)
    assert report.total_test_pnl == pytest.approx(5.0)


def test_average_test_sharpe_averages_across_windows():
    results = [
        _make_window_result(0, 10.0, 2.0, 3, [10_000.0]),
        _make_window_result(1, -5.0, 1.0, 2, [10_000.0]),
    ]
    report = WalkForwardReport(window_results=results)
    assert report.average_test_sharpe == pytest.approx(1.5)


def test_profitable_window_count():
    results = [
        _make_window_result(0, 10.0, 1.0, 3, [10_000.0]),
        _make_window_result(1, -5.0, 0.5, 2, [10_000.0]),
        _make_window_result(2, 20.0, 1.5, 4, [10_000.0]),
    ]
    report = WalkForwardReport(window_results=results)
    assert report.profitable_window_count == 2


def test_combined_test_equity_curve_chains_correctly():
    results = [
        _make_window_result(0, 100.0, 1.0, 3, [10_000.0, 10_050.0, 10_100.0]),
        _make_window_result(1, -50.0, 0.5, 2, [10_000.0, 9_975.0, 9_950.0]),
    ]
    report = WalkForwardReport(window_results=results)
    combined = report.combined_test_equity_curve(initial_capital=10_000.0)

    # First window: deltas +50, +100 applied to running=10_000
    # Second window: deltas -25, -50 applied to running=10_100 (end of window 0)
    assert combined == [10_000.0, 10_050.0, 10_100.0, 10_075.0, 10_050.0]


def test_combined_test_equity_curve_skips_empty_curves():
    results = [_make_window_result(0, 0.0, 0.0, 0, [])]
    report = WalkForwardReport(window_results=results)
    combined = report.combined_test_equity_curve(initial_capital=10_000.0)
    assert combined == [10_000.0]


def test_report_str_contains_key_sections():
    results = [_make_window_result(0, 10.0, 1.0, 3, [10_000.0, 10_010.0])]
    report = WalkForwardReport(window_results=results)
    output = str(report)
    assert "WALK-FORWARD TEST" in output
    assert "Windows" in output
    assert "Profitable windows" in output
    assert "Test" in output  # strategy name column
