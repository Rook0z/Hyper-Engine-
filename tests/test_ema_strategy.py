import pytest
from strategies.ema_strategy import EMAStrategy

# ──────────────────────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────────────────────


def test_default_periods():
    s = EMAStrategy()
    assert s.fast_period == 9
    assert s.slow_period == 21


def test_custom_periods():
    s = EMAStrategy(fast_period=12, slow_period=26)
    assert s.fast_period == 12
    assert s.slow_period == 26


def test_fast_must_be_less_than_slow():
    with pytest.raises(ValueError, match="less than"):
        EMAStrategy(fast_period=21, slow_period=9)


def test_equal_periods_raises():
    with pytest.raises(ValueError, match="less than"):
        EMAStrategy(fast_period=9, slow_period=9)


def test_fast_period_too_small_raises():
    with pytest.raises(ValueError, match=">= 2"):
        EMAStrategy(fast_period=1, slow_period=9)


def test_name():
    s = EMAStrategy(fast_period=9, slow_period=21)
    assert s.name == "EMA Crossover 9/21"


def test_min_periods():
    s = EMAStrategy(fast_period=9, slow_period=21)
    assert s.min_periods == 22  # slow_period + 1


# ──────────────────────────────────────────────────────────────
# SIGNALS
# ──────────────────────────────────────────────────────────────


def test_hold_when_not_enough_data():
    s = EMAStrategy(fast_period=3, slow_period=5)
    result = s.generate_signal([1.0, 2.0, 3.0, 4.0, 5.0])
    assert result == "HOLD"


def test_hold_on_empty_closes():
    s = EMAStrategy(fast_period=3, slow_period=5)
    assert s.generate_signal([]) == "HOLD"


def test_hold_when_no_crossover():
    s = EMAStrategy(fast_period=3, slow_period=5)
    closes = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0]
    assert s.generate_signal(closes) == "HOLD"


def test_buy_on_bullish_crossover():
    """Falling prices then spike → fast crosses above slow → BUY."""
    s = EMAStrategy(fast_period=3, slow_period=5)
    falling = [20.0, 18.0, 16.0, 14.0, 12.0, 10.0, 8.0, 6.0]
    spike = falling + [50.0]
    assert s.generate_signal(spike) == "BUY"


def test_sell_on_bearish_crossover():
    """Rising prices then crash — check signal at the crossover bar."""
    s = EMAStrategy(fast_period=3, slow_period=5)
    rising = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0]
    crash = rising + [1.0]
    assert s.generate_signal(crash) == "SELL"


def test_signal_returns_valid_string():
    s = EMAStrategy(fast_period=3, slow_period=5)
    closes = [float(i) for i in range(1, 15)]
    result = s.generate_signal(closes)
    assert result in ("BUY", "SELL", "HOLD")


# ──────────────────────────────────────────────────────────────
# GET EMA VALUES
# ──────────────────────────────────────────────────────────────


def test_get_ema_values_returns_both_series():
    s = EMAStrategy(fast_period=3, slow_period=5)
    closes = [float(i) for i in range(1, 15)]
    result = s.get_ema_values(closes)
    assert "fast" in result
    assert "slow" in result


def test_get_ema_values_correct_lengths():
    s = EMAStrategy(fast_period=3, slow_period=5)
    closes = [float(i) for i in range(1, 15)]
    result = s.get_ema_values(closes)
    assert len(result["fast"]) == len(closes)
    assert len(result["slow"]) == len(closes)


def test_fast_has_fewer_nones_than_slow():
    s = EMAStrategy(fast_period=3, slow_period=5)
    closes = [float(i) for i in range(1, 15)]
    result = s.get_ema_values(closes)
    fast_nones = sum(1 for v in result["fast"] if v is None)
    slow_nones = sum(1 for v in result["slow"] if v is None)
    assert fast_nones < slow_nones
