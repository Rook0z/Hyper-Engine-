"""
Tests for backtester/out_of_sample.py — the chronological split and
result-bundling type. Pure, strategy-agnostic, no Backtester/strategy
dependencies needed here (those are covered in
test_strategy_runner.py::run_out_of_sample_test tests).
"""

import pytest

from backtester.out_of_sample import (
    OutOfSampleReport,
    split_in_out_of_sample,
)


def make_candle(timestamp, close):
    return [timestamp, close, close * 1.01, close * 0.99, close, 100.0]


def make_candles(n, start_ts=1_000_000_000_000, interval_ms=3_600_000):
    return [make_candle(start_ts + i * interval_ms, 100.0 + i) for i in range(n)]


# ──────────────────────────────────────────────────────────────
# BASIC SPLIT CORRECTNESS
# ──────────────────────────────────────────────────────────────


def test_split_returns_correct_sizes_for_default_ratio():
    candles = make_candles(100)
    split = split_in_out_of_sample(candles)
    assert len(split.in_sample) == 70
    assert len(split.out_of_sample) == 30


def test_split_respects_custom_ratio():
    candles = make_candles(100)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.5)
    assert len(split.in_sample) == 50
    assert len(split.out_of_sample) == 50


def test_split_index_matches_in_sample_length():
    candles = make_candles(100)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.6)
    assert split.split_index == 60
    assert split.split_index == len(split.in_sample)


def test_split_timestamp_is_first_out_of_sample_candle():
    candles = make_candles(100)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.7)
    assert split.split_timestamp == split.out_of_sample[0][0]


def test_split_covers_every_candle_exactly_once():
    candles = make_candles(50)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.6)
    assert split.in_sample + split.out_of_sample == candles


# ──────────────────────────────────────────────────────────────
# DATA LEAKAGE PREVENTION
# ──────────────────────────────────────────────────────────────


def test_split_is_strictly_chronological_no_overlap():
    """Every out-of-sample timestamp must be greater than every
    in-sample timestamp — the core leakage-prevention guarantee."""
    candles = make_candles(100)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.7)

    max_in_sample_ts = max(c[0] for c in split.in_sample)
    min_out_of_sample_ts = min(c[0] for c in split.out_of_sample)
    assert min_out_of_sample_ts > max_in_sample_ts


def test_split_produces_disjoint_sets():
    """No candle (by identity/timestamp) appears in both periods."""
    candles = make_candles(100)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.7)

    in_sample_ts = {c[0] for c in split.in_sample}
    out_of_sample_ts = {c[0] for c in split.out_of_sample}
    assert in_sample_ts.isdisjoint(out_of_sample_ts)


def test_split_never_reorders_candles():
    """in_sample and out_of_sample must each remain in original
    chronological order — this is a slice, never a shuffle."""
    candles = make_candles(50)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.6)

    in_sample_ts = [c[0] for c in split.in_sample]
    out_of_sample_ts = [c[0] for c in split.out_of_sample]
    assert in_sample_ts == sorted(in_sample_ts)
    assert out_of_sample_ts == sorted(out_of_sample_ts)


def test_split_out_of_sample_starts_immediately_after_in_sample():
    """No gap and no overlap: out_of_sample[0] must be exactly the
    candle immediately following in_sample[-1] in the original list."""
    candles = make_candles(50)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.6)
    boundary_index = candles.index(split.in_sample[-1])
    assert candles[boundary_index + 1] == split.out_of_sample[0]


# ──────────────────────────────────────────────────────────────
# VALIDATION / EDGE CASES
# ──────────────────────────────────────────────────────────────


def test_split_ratio_zero_raises():
    with pytest.raises(ValueError, match="in_sample_ratio"):
        split_in_out_of_sample(make_candles(10), in_sample_ratio=0.0)


def test_split_ratio_one_raises():
    with pytest.raises(ValueError, match="in_sample_ratio"):
        split_in_out_of_sample(make_candles(10), in_sample_ratio=1.0)


def test_split_ratio_negative_raises():
    with pytest.raises(ValueError, match="in_sample_ratio"):
        split_in_out_of_sample(make_candles(10), in_sample_ratio=-0.5)


def test_split_ratio_above_one_raises():
    with pytest.raises(ValueError, match="in_sample_ratio"):
        split_in_out_of_sample(make_candles(10), in_sample_ratio=1.5)


def test_split_too_few_candles_raises():
    with pytest.raises(ValueError, match="at least 2"):
        split_in_out_of_sample([make_candle(1000, 100.0)])


def test_split_empty_candles_raises():
    with pytest.raises(ValueError, match="at least 2"):
        split_in_out_of_sample([])


def test_split_extreme_ratio_still_produces_non_empty_out_of_sample():
    """A ratio that would round to include ALL candles in-sample must
    still leave at least one candle out-of-sample (clamped), never
    silently produce an empty out-of-sample period."""
    candles = make_candles(3)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.99)
    assert len(split.out_of_sample) >= 1
    assert len(split.in_sample) >= 1


def test_split_extreme_low_ratio_still_produces_non_empty_in_sample():
    candles = make_candles(3)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.01)
    assert len(split.in_sample) >= 1
    assert len(split.out_of_sample) >= 1


def test_split_minimum_two_candles():
    candles = make_candles(2)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.5)
    assert len(split.in_sample) == 1
    assert len(split.out_of_sample) == 1


# ──────────────────────────────────────────────────────────────
# OutOfSampleReport __str__
# ──────────────────────────────────────────────────────────────


def test_out_of_sample_report_str_contains_key_sections():
    from backtester.backtester import BacktestResult
    from backtester.performance import PerformanceAnalyser

    candles = make_candles(50)
    split = split_in_out_of_sample(candles, in_sample_ratio=0.7)
    analyser = PerformanceAnalyser()
    empty_result = BacktestResult(strategy_name="Test", symbol="BTC", candles_tested=0)
    empty_report = analyser.analyse(empty_result)

    report = OutOfSampleReport(
        strategy_name="TestStrategy",
        split=split,
        in_sample_result=empty_result,
        in_sample_report=empty_report,
        out_of_sample_result=empty_result,
        out_of_sample_report=empty_report,
    )
    output = str(report)
    assert "OUT-OF-SAMPLE TEST" in output
    assert "TestStrategy" in output
    assert "In-Sample" in output
    assert "Out-of-Sample" in output
    assert "Sharpe ratio" in output
