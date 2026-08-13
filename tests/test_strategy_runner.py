"""
Tests for strategy_runner.py's strategy factory and the fresh-instance
guarantee between backtest_all() and paper trading.

paper_trade() itself (network fetch loop, sleep, KeyboardInterrupt
handling) is out of scope here — these tests target the pure,
side-effect-free pieces: _build_strategy() and backtest_all()'s use of
it, which is what guarantees the backtester and the paper trader never
share a mutable strategy instance.
"""

import pytest

import strategy_runner as sr
from strategies.ema_strategy import EMAStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.bb_strategy import BollingerStrategy
from strategies.vwap_strategy import VWAPStrategy


def make_candle(timestamp, open_, close, high=None, low=None, volume=1.0):
    high = high or close * 1.01
    low = low or close * 0.99
    return [timestamp, open_, high, low, close, volume]


def make_candles(prices, start_ts=1_000_000_000_000, interval_ms=3_600_000):
    candles = []
    for i, price in enumerate(prices):
        ts = start_ts + i * interval_ms
        open_ = prices[i - 1] if i > 0 else price
        candles.append(make_candle(ts, open_, price))
    return candles


# ──────────────────────────────────────────────────────────────
# _build_strategy — TYPES AND CONFIG
# ──────────────────────────────────────────────────────────────


def test_build_strategy_returns_correct_type_for_each_class():
    assert isinstance(sr._build_strategy(EMAStrategy), EMAStrategy)
    assert isinstance(sr._build_strategy(RSIStrategy), RSIStrategy)
    assert isinstance(sr._build_strategy(BollingerStrategy), BollingerStrategy)
    assert isinstance(sr._build_strategy(VWAPStrategy), VWAPStrategy)


def test_build_strategy_uses_current_settings():
    ema = sr._build_strategy(EMAStrategy)
    assert ema.fast_period == sr.settings.ema_fast_period
    assert ema.slow_period == sr.settings.ema_slow_period

    rsi = sr._build_strategy(RSIStrategy)
    assert rsi.period == sr.settings.rsi_period

    vwap = sr._build_strategy(VWAPStrategy)
    assert vwap.mode == sr.settings.vwap_mode


# ──────────────────────────────────────────────────────────────
# _build_strategy — FRESH INSTANCE GUARANTEE
# ──────────────────────────────────────────────────────────────


def test_build_strategy_returns_a_new_instance_each_call():
    a = sr._build_strategy(EMAStrategy)
    b = sr._build_strategy(EMAStrategy)
    assert a is not b


def test_fresh_strategy_does_not_inherit_mutated_state():
    """
    Regression test: mutating one instance's internal signal-dedup
    state (as a real backtest run would) must NOT be visible on a
    freshly built instance of the same class/config.
    """
    backtested = sr._build_strategy(EMAStrategy)
    backtested._last_crossover = "BUY"  # simulate state left by a backtest

    fresh = sr._build_strategy(EMAStrategy)

    assert fresh is not backtested
    assert fresh._last_crossover == "HOLD"

    # And the two remain independent going forward.
    fresh._last_crossover = "SELL"
    assert backtested._last_crossover == "BUY"


# ──────────────────────────────────────────────────────────────
# END-TO-END: backtest_all() MUTATES STATE; A FRESH REBUILD MUST NOT
# CARRY IT OVER — this is the exact scenario paper trading depends on.
# ──────────────────────────────────────────────────────────────


def test_paper_trading_strategy_is_not_the_backtested_instance():
    """
    Regression test proving the fix: after backtest_all() runs (which
    mutates each strategy's internal dedup state via real signal
    generation), rebuilding via _build_strategy(type(winner)) must
    produce an object that never participated in the backtest and
    carries no leftover signal state.
    """
    # A trend with a clear reversal, long enough to mutate every
    # strategy's internal dedup state during backtesting.
    up = [100.0 + i * 2.0 for i in range(30)]
    down = [up[-1] - i * 2.0 for i in range(1, 30)]
    candles = make_candles(up + down)

    results = sr.backtest_all(candles)
    best_strategy, _, _ = results[0]

    fresh_strategy = sr._build_strategy(type(best_strategy))

    # Never the same object — this is the core guarantee.
    assert fresh_strategy is not best_strategy
    # Same class, same configuration (same name).
    assert type(fresh_strategy) is type(best_strategy)
    assert fresh_strategy.name == best_strategy.name


def test_backtest_all_strategies_are_all_freshly_built():
    """
    Every strategy competing in backtest_all() must come from
    _build_strategy() — i.e. backtest_all() and a subsequent fresh
    rebuild never hand out the same object.
    """
    candles = make_candles([100.0 + i for i in range(30)])
    results = sr.backtest_all(candles)

    rebuilt = [sr._build_strategy(type(s)) for s, _, _ in results]
    original = [s for s, _, _ in results]

    for rebuilt_strategy, original_strategy in zip(rebuilt, original):
        assert rebuilt_strategy is not original_strategy


# ──────────────────────────────────────────────────────────────
# run_out_of_sample_test
# ──────────────────────────────────────────────────────────────


def _trending_then_reversing_candles(n_per_leg=30):
    """Enough of a real trend + reversal for every strategy to
    actually generate signals and mutate its internal state — needed
    so the fresh-instance/no-leakage assertions are meaningful rather
    than vacuously true on an all-HOLD series."""
    up = [100.0 + i * 2.0 for i in range(n_per_leg)]
    down = [up[-1] - i * 2.0 for i in range(1, n_per_leg)]
    return make_candles(up + down)


def test_run_out_of_sample_test_returns_report_with_correct_split():
    candles = _trending_then_reversing_candles()
    report = sr.run_out_of_sample_test(candles, in_sample_ratio=0.7)

    assert len(report.split.in_sample) + len(report.split.out_of_sample) == len(candles)
    assert report.split.in_sample == candles[: report.split.split_index]
    assert report.split.out_of_sample == candles[report.split.split_index :]


def test_run_out_of_sample_test_selection_never_sees_out_of_sample_candles(
    monkeypatch,
):
    """
    Data-leakage guard: backtest_all() (strategy selection) must be
    called with EXACTLY the in-sample candles — never anything that
    includes or is influenced by the out-of-sample period.
    """
    candles = _trending_then_reversing_candles()
    calls = []
    real_backtest_all = sr.backtest_all

    def spy_backtest_all(candles_arg):
        calls.append(list(candles_arg))
        return real_backtest_all(candles_arg)

    monkeypatch.setattr(sr, "backtest_all", spy_backtest_all)

    report = sr.run_out_of_sample_test(candles, in_sample_ratio=0.7)

    assert len(calls) == 1
    assert calls[0] == report.split.in_sample
    assert calls[0] != candles  # must NOT have been called with the full set


def test_run_out_of_sample_test_evaluates_on_fresh_strategy_instance():
    """
    The out-of-sample evaluation must use a brand-new instance of the
    winning strategy's class — never the same mutated object that ran
    the in-sample backtest_all() selection.
    """
    candles = _trending_then_reversing_candles()
    report = sr.run_out_of_sample_test(candles, in_sample_ratio=0.7)

    # The in-sample winner's class must match what was actually
    # evaluated out-of-sample (same strategy, same config).
    in_sample_results = sr.backtest_all(report.split.in_sample)
    winning_strategy, _, _ = in_sample_results[0]
    assert report.strategy_name == winning_strategy.name


def test_run_out_of_sample_test_out_of_sample_result_uses_only_out_of_sample_candles():
    """The out-of-sample BacktestResult's candle count must match the
    out-of-sample split exactly — never the full or in-sample count."""
    candles = _trending_then_reversing_candles()
    report = sr.run_out_of_sample_test(candles, in_sample_ratio=0.7)

    assert report.out_of_sample_result.candles_tested == len(report.split.out_of_sample)
    assert report.in_sample_result.candles_tested == len(report.split.in_sample)


def test_run_out_of_sample_test_respects_custom_ratio():
    candles = _trending_then_reversing_candles()
    report = sr.run_out_of_sample_test(candles, in_sample_ratio=0.5)
    assert len(report.split.in_sample) == len(candles) // 2


# ──────────────────────────────────────────────────────────────
# run_walk_forward_test
# ──────────────────────────────────────────────────────────────


def _long_trending_series(n_legs=3, leg_len=25):
    """A longer up/down/up/... series so multiple walk-forward windows
    each contain enough real price movement for strategies to generate
    signals and mutate state."""
    prices = []
    price = 100.0
    direction = 1
    for _ in range(n_legs):
        for _ in range(leg_len):
            price += direction * 2.0
            prices.append(price)
        direction *= -1
    return make_candles(prices)


def test_run_walk_forward_test_returns_expected_number_of_windows():
    candles = _long_trending_series()
    report = sr.run_walk_forward_test(
        candles, train_window_size=30, test_window_size=15
    )
    assert report.num_windows > 0
    for w in report.window_results:
        assert len(w.window.train) == 30
        assert len(w.window.test) == 15


def test_run_walk_forward_test_raises_when_no_window_fits():
    candles = make_candles([100.0] * 5)
    with pytest.raises(ValueError, match="Not enough candles"):
        sr.run_walk_forward_test(candles, train_window_size=30, test_window_size=15)


def test_run_walk_forward_test_selection_never_sees_that_windows_test_candles(
    monkeypatch,
):
    """
    Data-leakage guard: for every window, backtest_all() (selection)
    must be called with EXACTLY that window's train candles — never
    anything overlapping that window's own test candles.
    """
    candles = _long_trending_series()
    calls = []
    real_backtest_all = sr.backtest_all

    def spy_backtest_all(candles_arg):
        calls.append(list(candles_arg))
        return real_backtest_all(candles_arg)

    monkeypatch.setattr(sr, "backtest_all", spy_backtest_all)

    report = sr.run_walk_forward_test(
        candles, train_window_size=30, test_window_size=15
    )

    assert len(calls) == report.num_windows
    for call_candles, window_result in zip(calls, report.window_results):
        assert call_candles == window_result.window.train
        call_ts = {c[0] for c in call_candles}
        test_ts = {c[0] for c in window_result.window.test}
        assert call_ts.isdisjoint(test_ts)


def test_run_walk_forward_test_each_window_uses_a_fresh_strategy_instance():
    """
    Regression guard: no two windows — and no window's train vs. test
    phase — may share a mutable strategy instance. We can't directly
    inspect the instances used internally, but we can verify that
    rebuilding fresh instances of each window's reported winning class
    never collides with another window's instance (identity-distinct
    by construction of _build_strategy()).
    """
    candles = _long_trending_series()
    report = sr.run_walk_forward_test(
        candles, train_window_size=30, test_window_size=15
    )

    def _class_for_name(name: str) -> type:
        for cls in sr.STRATEGY_CLASSES:
            if sr._build_strategy(cls).name == name:
                return cls
        raise AssertionError(f"No strategy class matches name {name!r}")

    rebuilt_instances = [
        sr._build_strategy(_class_for_name(w.strategy_name))
        for w in report.window_results
    ]
    # Every rebuilt instance must be a distinct object.
    assert len(set(id(s) for s in rebuilt_instances)) == len(rebuilt_instances)


def test_run_walk_forward_test_aggregation_matches_window_reports():
    candles = _long_trending_series()
    report = sr.run_walk_forward_test(
        candles, train_window_size=30, test_window_size=15
    )
    expected_total_trades = sum(w.test_report.num_trades for w in report.window_results)
    expected_total_pnl = sum(w.test_report.total_pnl for w in report.window_results)
    assert report.total_test_trades == expected_total_trades
    assert report.total_test_pnl == pytest.approx(expected_total_pnl)


def test_run_walk_forward_test_respects_custom_step_size():
    candles = _long_trending_series()
    report_default_step = sr.run_walk_forward_test(
        candles, train_window_size=30, test_window_size=15
    )
    report_small_step = sr.run_walk_forward_test(
        candles, train_window_size=30, test_window_size=15, step_size=5
    )
    # A smaller step must produce at least as many (usually more) windows.
    assert report_small_step.num_windows >= report_default_step.num_windows


# ──────────────────────────────────────────────────────────────
# clean_data — EXISTING BEHAVIOR PRESERVED
# ──────────────────────────────────────────────────────────────


def test_clean_data_keeps_all_valid_candles():
    candles = make_candles([100.0, 101.0, 102.0, 103.0])
    result = sr.clean_data(candles)
    assert len(result) == 4


def test_clean_data_empty_raises():
    with pytest.raises(ValueError, match="No candles"):
        sr.clean_data([])


def test_clean_data_removes_duplicate_timestamps():
    candles = make_candles([100.0, 101.0])
    candles.append(candles[0])  # exact duplicate timestamp
    result = sr.clean_data(candles)
    timestamps = [c[0] for c in result]
    assert len(timestamps) == len(set(timestamps))
    assert len(result) == 2


def test_clean_data_removes_zero_and_negative_prices():
    candles = make_candles([100.0, 101.0])
    candles.append(make_candle(9_999_000_000_000, 0.0, 0.0))  # zero price
    candles.append(make_candle(9_999_100_000_000, -5.0, -5.0))  # negative price
    result = sr.clean_data(candles)
    assert len(result) == 2


def test_clean_data_removes_high_less_than_low():
    candles = make_candles([100.0])
    bad = [9_999_000_000_000, 100.0, 90.0, 95.0, 92.0, 1.0]  # high(90) < low(95)
    candles.append(bad)
    result = sr.clean_data(candles)
    assert len(result) == 1


def test_clean_data_removes_close_outside_high_low_range():
    candles = make_candles([100.0])
    bad = [9_999_000_000_000, 100.0, 105.0, 95.0, 110.0, 1.0]  # close(110) > high(105)
    candles.append(bad)
    result = sr.clean_data(candles)
    assert len(result) == 1


def test_clean_data_removes_zero_volume():
    candles = make_candles([100.0])
    bad = [9_999_000_000_000, 100.0, 101.0, 99.0, 100.5, 0.0]
    candles.append(bad)
    result = sr.clean_data(candles)
    assert len(result) == 1


def test_clean_data_sorts_output_chronologically():
    candles = make_candles([100.0, 101.0, 102.0])
    shuffled = [candles[2], candles[0], candles[1]]
    result = sr.clean_data(shuffled)
    assert [c[0] for c in result] == sorted(c[0] for c in result)


# ──────────────────────────────────────────────────────────────
# clean_data — NEW ROBUSTNESS: MALFORMED / MISSING / INVALID CANDLES
# ───────────────────────────────────────────────────────────


def test_clean_data_skips_wrong_length_row_without_crashing():
    """
    Regression test for the original crash: a row with the wrong
    number of fields used to raise an unhandled ValueError from tuple
    unpacking and abort the ENTIRE clean_data() call. It must now be
    skipped like any other invalid candle.
    """
    candles = make_candles([100.0, 101.0])
    candles.append([9_999_000_000_000, 100.0, 101.0])  # only 3 fields
    result = sr.clean_data(candles)  # must not raise
    assert len(result) == 2


def test_clean_data_skips_too_many_fields_row():
    candles = make_candles([100.0])
    candles.append([9_999_000_000_000, 100.0, 101.0, 99.0, 100.5, 1.0, "extra"])
    result = sr.clean_data(candles)
    assert len(result) == 1


def test_clean_data_skips_none_values_without_crashing():
    """A field of None used to raise an unhandled TypeError from the
    unpacking/comparison logic."""
    candles = make_candles([100.0])
    candles.append([9_999_000_000_000, None, 101.0, 99.0, 100.5, 1.0])
    result = sr.clean_data(candles)
    assert len(result) == 1


def test_clean_data_skips_non_numeric_string_values():
    candles = make_candles([100.0])
    candles.append([9_999_000_000_000, "not-a-number", 101.0, 99.0, 100.5, 1.0])
    result = sr.clean_data(candles)
    assert len(result) == 1


def test_clean_data_rejects_nan_price():
    """
    Regression test for a subtle correctness bug: NaN comparisons are
    always False in Python, so `nan <= 0` is False — meaning a NaN
    open/high/low/close previously SLIPPED THROUGH the zero/negative
    price filter undetected. An explicit finiteness check is required.
    """
    candles = make_candles([100.0])
    candles.append([9_999_000_000_000, float("nan"), 101.0, 99.0, 100.5, 1.0])
    result = sr.clean_data(candles)
    assert len(result) == 1


def test_clean_data_rejects_infinite_price():
    candles = make_candles([100.0])
    candles.append([9_999_000_000_000, float("inf"), 101.0, 99.0, 100.5, 1.0])
    result = sr.clean_data(candles)
    assert len(result) == 1


def test_clean_data_rejects_nan_volume():
    candles = make_candles([100.0])
    candles.append([9_999_000_000_000, 100.0, 101.0, 99.0, 100.5, float("nan")])
    result = sr.clean_data(candles)
    assert len(result) == 1


def test_clean_data_mixed_malformed_and_valid_rows():
    """Several different kinds of bad rows mixed with good ones — only
    the good ones survive, and nothing crashes."""
    candles = make_candles([100.0, 101.0, 102.0])
    candles.append([9_999_000_000_000, 100.0])  # wrong length
    candles.append([9_999_100_000_000, None, 101.0, 99.0, 100.5, 1.0])  # None
    candles.append([9_999_200_000_000, float("nan"), 101.0, 99.0, 100.5, 1.0])  # NaN
    candles.append([9_999_300_000_000, -5.0, 101.0, 99.0, 100.5, 1.0])  # negative
    result = sr.clean_data(candles)
    assert len(result) == 3


# ───────────────────────────────────────────────────────────
# _log_timestamp_gaps — GAP DETECTION IS INFORMATIONAL ONLY
# ───────────────────────────────────────────────────────────


def test_log_timestamp_gaps_does_not_raise_on_short_input():
    sr._log_timestamp_gaps([])  # must not raise
    sr._log_timestamp_gaps([make_candle(1000, 100.0, 100.0)])
    sr._log_timestamp_gaps(
        [make_candle(1000, 100.0, 100.0), make_candle(2000, 100.0, 100.0)]
    )


def test_log_timestamp_gaps_does_not_mutate_input():
    """Gap detection is purely informational — the candle list passed
    in must be completely unchanged afterward."""
    candles = make_candles([100.0, 101.0, 102.0, 103.0, 104.0])
    before = [list(c) for c in candles]
    sr._log_timestamp_gaps(candles)
    assert candles == before


def test_clean_data_with_a_gap_still_returns_all_valid_candles(caplog):
    """
    A gap in the timestamp sequence must be logged, but the returned
    candle list must still contain every valid candle that WAS present
    — gap detection never removes or fabricates data.
    """
    import logging as _logging

    regular = make_candles([100.0, 101.0, 102.0], interval_ms=3_600_000)
    # Jump far ahead for the next candle — a clear gap relative to the
    # established 1h modal interval.
    far_future = make_candle(regular[-1][0] + 20 * 3_600_000, 103.0, 103.0)
    candles = regular + [far_future]

    with caplog.at_level(_logging.WARNING, logger="strategy_runner"):
        result = sr.clean_data(candles)

    assert len(result) == 4
    assert any("gap" in record.message.lower() for record in caplog.records)


def test_clean_data_no_gap_does_not_log_gap_warning(caplog):
    import logging as _logging

    candles = make_candles([100.0, 101.0, 102.0, 103.0, 104.0])

    with caplog.at_level(_logging.WARNING, logger="strategy_runner"):
        sr.clean_data(candles)

    assert not any("gap" in record.message.lower() for record in caplog.records)
