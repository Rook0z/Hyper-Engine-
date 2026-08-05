import pytest
from strategies.vwap_strategy import VWAPStrategy


def make_candle(ts, open_, high, low, close, volume):
    return [ts, open_, high, low, close, volume]


# ──────────────────────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────────────────────


def test_default_mode():
    s = VWAPStrategy()
    assert s.mode == "crossover"
    assert s.num_std == 2.0


def test_custom_mode():
    s = VWAPStrategy(mode="reversion", num_std=1.5)
    assert s.mode == "reversion"
    assert s.num_std == 1.5


def test_invalid_mode_raises():
    with pytest.raises(ValueError, match="mode must be"):
        VWAPStrategy(mode="bogus")


def test_num_std_zero_raises():
    with pytest.raises(ValueError, match="num_std must be > 0"):
        VWAPStrategy(num_std=0.0)


def test_num_std_negative_raises():
    with pytest.raises(ValueError, match="num_std must be > 0"):
        VWAPStrategy(num_std=-1.0)


def test_name_crossover():
    s = VWAPStrategy(mode="crossover")
    assert s.name == "VWAP(crossover)"


def test_name_reversion():
    s = VWAPStrategy(mode="reversion")
    assert s.name == "VWAP(reversion)"


def test_min_periods():
    s = VWAPStrategy()
    assert s.min_periods == 2


# ──────────────────────────────────────────────────────────────
# generate_signal() — closes-only interface must always HOLD
# ──────────────────────────────────────────────────────────────


def test_generate_signal_always_holds():
    """
    VWAPStrategy needs full OHLCV data, not just closes.
    generate_signal() exists only to satisfy BaseStrategy and must
    always return HOLD — real signals come from
    generate_signal_from_candles().
    """
    s = VWAPStrategy()
    assert s.generate_signal([1.0, 2.0, 3.0]) == "HOLD"
    assert s.generate_signal([]) == "HOLD"


# ──────────────────────────────────────────────────────────────
# generate_signal_from_candles() — CROSSOVER MODE
# ──────────────────────────────────────────────────────────────


def test_hold_when_not_enough_candles():
    s = VWAPStrategy(mode="crossover")
    assert (
        s.generate_signal_from_candles([make_candle(1000, 10, 11, 9, 10, 100)])
        == "HOLD"
    )


def test_hold_on_empty_candles():
    s = VWAPStrategy(mode="crossover")
    assert s.generate_signal_from_candles([]) == "HOLD"


def test_buy_on_crossover_above_vwap():
    """Price starts below VWAP, then a low-volume spike pushes close above it."""
    s = VWAPStrategy(mode="crossover")
    candles = [
        make_candle(1000, 100.0, 101.0, 99.0, 95.0, 1000.0),  # below vwap
        make_candle(2000, 100.0, 200.0, 100.0, 150.0, 1.0),  # spikes above
    ]
    assert s.generate_signal_from_candles(candles) == "BUY"


def test_sell_on_crossover_below_vwap():
    """Price starts above VWAP, then a low-volume drop pushes close below it."""
    s = VWAPStrategy(mode="crossover")
    candles = [
        make_candle(1000, 100.0, 101.0, 99.0, 105.0, 1000.0),  # above vwap
        make_candle(2000, 100.0, 100.0, 50.0, 60.0, 1.0),  # drops below
    ]
    assert s.generate_signal_from_candles(candles) == "SELL"


def test_signal_returns_valid_string():
    s = VWAPStrategy(mode="crossover")
    candles = [
        make_candle(i * 1000, 100.0, 101.0, 99.0, 100.0 + i, 100.0) for i in range(10)
    ]
    result = s.generate_signal_from_candles(candles)
    assert result in ("BUY", "SELL", "HOLD")


def test_crossover_no_crash_when_vwap_is_zero():
    """
    Regression guard: curr_vwap == 0 (degenerate all-zero-price input)
    must not raise ZeroDivisionError in the near_vwap check.
    Zero/negative prices are normally stripped by clean_data() upstream,
    but the strategy itself must not crash on this input.
    """
    s = VWAPStrategy(mode="crossover")
    candles = [
        make_candle(1000, 0.0, 0.0, 0.0, 0.0, 100.0),
        make_candle(2000, 0.0, 0.0, 0.0, 0.0, 100.0),
    ]
    result = s.generate_signal_from_candles(candles)
    assert result in ("BUY", "SELL", "HOLD")


# ──────────────────────────────────────────────────────────────
# generate_signal_from_candles() — REVERSION MODE
# ──────────────────────────────────────────────────────────────


def test_reversion_buy_below_lower_band():
    s = VWAPStrategy(mode="reversion", num_std=1.0)
    candles = [
        make_candle(1000, 100.0, 105.0, 95.0, 100.0, 100.0),
        make_candle(2000, 100.0, 105.0, 95.0, 100.0, 100.0),
        make_candle(3000, 100.0, 105.0, 95.0, 100.0, 100.0),
        make_candle(4000, 100.0, 40.0, 30.0, 30.0, 1.0),  # extreme drop
    ]
    assert s.generate_signal_from_candles(candles) == "BUY"


def test_reversion_hold_within_bands():
    s = VWAPStrategy(mode="reversion", num_std=2.0)
    candles = [
        make_candle(i * 1000, 100.0, 101.0, 99.0, 100.0, 100.0) for i in range(5)
    ]
    assert s.generate_signal_from_candles(candles) == "HOLD"


# ──────────────────────────────────────────────────────────────
# get_vwap_values()
# ──────────────────────────────────────────────────────────────


def test_get_vwap_values_length_matches_candles():
    s = VWAPStrategy()
    candles = [
        make_candle(i * 1000, 100.0, 101.0, 99.0, 100.0, 100.0) for i in range(5)
    ]
    result = s.get_vwap_values(candles)
    assert len(result) == len(candles)


def test_get_vwap_values_keys():
    s = VWAPStrategy()
    candles = [make_candle(1000, 100.0, 101.0, 99.0, 100.0, 100.0)]
    result = s.get_vwap_values(candles)
    expected_keys = {"vwap", "upper1", "lower1", "upper2", "lower2", "deviation"}
    assert expected_keys.issubset(result[0].keys())
