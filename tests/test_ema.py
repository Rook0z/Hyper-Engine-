import math
import pytest
from indicators.ema import calculate_ema, ema_latest


SIMPLE_CLOSES = [10.0, 11.0, 12.0, 13.0, 14.0]


def test_ema_length_matches_input():
    result = calculate_ema(SIMPLE_CLOSES, period=3)
    assert len(result) == len(SIMPLE_CLOSES)


def test_ema_first_values_are_none():
    result = calculate_ema(SIMPLE_CLOSES, period=3)
    assert result[0] is None
    assert result[1] is None


def test_ema_seed_is_simple_mean():
    result = calculate_ema(SIMPLE_CLOSES, period=3)
    assert math.isclose(result[2], 11.0, rel_tol=1e-9)


def test_ema_fourth_value():
    result = calculate_ema(SIMPLE_CLOSES, period=3)
    assert math.isclose(result[3], 12.0, rel_tol=1e-9)


def test_ema_fifth_value():
    result = calculate_ema(SIMPLE_CLOSES, period=3)
    assert math.isclose(result[4], 13.0, rel_tol=1e-9)


def test_ema_period_2():
    result = calculate_ema([1.0, 2.0, 3.0], period=2)
    assert result[0] is None
    assert math.isclose(result[1], 1.5, rel_tol=1e-9)
    assert math.isclose(result[2], 2.5, rel_tol=1e-9)


def test_ema_period_equals_length():
    result = calculate_ema([1.0, 2.0, 3.0], period=3)
    assert result[0] is None
    assert result[1] is None
    assert math.isclose(result[2], 2.0, rel_tol=1e-9)


def test_ema_rising_prices_ema_rises():
    closes = [i * 1.0 for i in range(1, 21)]
    result = calculate_ema(closes, period=5)
    non_none = [v for v in result if v is not None]
    assert non_none[-1] > non_none[0]


def test_ema_flat_prices_equals_price():
    closes = [100.0] * 10
    result = calculate_ema(closes, period=5)
    for v in result[4:]:
        assert math.isclose(v, 100.0, rel_tol=1e-9)


def test_ema_recent_price_weighted_more():
    base = [100.0] * 10
    base[-1] = 200.0
    result = calculate_ema(base, period=5)
    assert result[-1] > 100.0


def test_ema_empty_closes_raises():
    with pytest.raises(ValueError, match="empty"):
        calculate_ema([], period=3)


def test_ema_period_less_than_2_raises():
    with pytest.raises(ValueError, match=">= 2"):
        calculate_ema([1.0, 2.0, 3.0], period=1)


def test_ema_period_exceeds_closes_raises():
    with pytest.raises(ValueError, match="cannot exceed"):
        calculate_ema([1.0, 2.0], period=5)


def test_ema_latest_returns_float():
    result = ema_latest(SIMPLE_CLOSES, period=3)
    assert isinstance(result, float)


def test_ema_latest_matches_last_value():
    full = calculate_ema(SIMPLE_CLOSES, period=3)
    assert math.isclose(ema_latest(SIMPLE_CLOSES, period=3), full[-1], rel_tol=1e-9)


def test_ema_latest_not_enough_data_raises():
    with pytest.raises(ValueError):
        ema_latest([1.0, 2.0], period=5)
