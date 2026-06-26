import math
import pytest
from indicators.bollinger import BollingerValue, calculate_bollinger, bollinger_latest

SIMPLE_CLOSES = [10.0, 11.0, 12.0, 13.0, 14.0]


# ── BOLLINGER VALUE DATACLASS ─────────────────────────────────


def test_bollinger_value_fields():
    bv = BollingerValue(
        upper=12.0, middle=11.0, lower=10.0, percent_b=0.5, bandwidth=0.18
    )
    assert bv.upper == 12.0
    assert bv.middle == 11.0
    assert bv.lower == 10.0
    assert bv.percent_b == 0.5
    assert bv.bandwidth == 0.18


def test_bollinger_value_none_fields():
    bv = BollingerValue(
        upper=None, middle=None, lower=None, percent_b=None, bandwidth=None
    )
    assert bv.upper is None


# ── CALCULATE BOLLINGER ───────────────────────────────────────


def test_bollinger_length_matches_input():
    result = calculate_bollinger(SIMPLE_CLOSES, period=3)
    assert len(result) == len(SIMPLE_CLOSES)


def test_bollinger_first_values_are_none():
    # period=3 → first 2 values have None fields
    result = calculate_bollinger(SIMPLE_CLOSES, period=3)
    assert result[0].middle is None
    assert result[1].middle is None


def test_bollinger_first_calculated_middle():
    # index 2: middle = mean([10,11,12]) = 11.0
    result = calculate_bollinger(SIMPLE_CLOSES, period=3, num_std=1.0)
    assert math.isclose(result[2].middle, 11.0, rel_tol=1e-9)


def test_bollinger_first_calculated_upper():
    # upper = 11.0 + 1*1.0 = 12.0
    result = calculate_bollinger(SIMPLE_CLOSES, period=3, num_std=1.0)
    assert math.isclose(result[2].upper, 12.0, rel_tol=1e-9)


def test_bollinger_first_calculated_lower():
    # lower = 11.0 - 1*1.0 = 10.0
    result = calculate_bollinger(SIMPLE_CLOSES, period=3, num_std=1.0)
    assert math.isclose(result[2].lower, 10.0, rel_tol=1e-9)


def test_bollinger_percent_b_at_upper():
    # close=12 is at upper band → %B = 1.0
    result = calculate_bollinger(SIMPLE_CLOSES, period=3, num_std=1.0)
    assert math.isclose(result[2].percent_b, 1.0, rel_tol=1e-9)


def test_bollinger_bandwidth_calculation():
    # bandwidth = (upper - lower) / middle = (12-10)/11 = 0.18182
    result = calculate_bollinger(SIMPLE_CLOSES, period=3, num_std=1.0)
    assert math.isclose(result[2].bandwidth, 2.0 / 11.0, rel_tol=1e-9)


def test_bollinger_upper_above_middle():
    result = calculate_bollinger(SIMPLE_CLOSES, period=3)
    for bv in result:
        if bv.upper is not None:
            assert bv.upper >= bv.middle


def test_bollinger_lower_below_middle():
    result = calculate_bollinger(SIMPLE_CLOSES, period=3)
    for bv in result:
        if bv.lower is not None:
            assert bv.lower <= bv.middle


def test_bollinger_upper_minus_lower_is_symmetric():
    # upper - middle == middle - lower
    result = calculate_bollinger(SIMPLE_CLOSES, period=3, num_std=2.0)
    for bv in result:
        if bv.upper is not None:
            assert math.isclose(
                bv.upper - bv.middle, bv.middle - bv.lower, rel_tol=1e-9
            )


def test_bollinger_flat_prices_zero_bandwidth():
    # No variation → std=0 → bands collapse to middle
    closes = [100.0] * 10
    result = calculate_bollinger(closes, period=5)
    for bv in result[4:]:
        assert math.isclose(bv.upper, bv.middle, abs_tol=1e-9)
        assert math.isclose(bv.lower, bv.middle, abs_tol=1e-9)
        assert math.isclose(bv.bandwidth, 0.0, abs_tol=1e-9)


def test_bollinger_volatile_prices_wider_bands():
    # High volatility → wider bands
    volatile = [
        100.0,
        120.0,
        80.0,
        130.0,
        70.0,
        140.0,
        60.0,
        150.0,
        50.0,
        160.0,
        40.0,
        170.0,
    ]
    stable = [
        100.0,
        101.0,
        99.0,
        100.5,
        99.5,
        100.0,
        100.2,
        99.8,
        100.1,
        99.9,
        100.0,
        100.3,
    ]

    result_volatile = calculate_bollinger(volatile, period=5)
    result_stable = calculate_bollinger(stable, period=5)

    # Last valid bandwidth
    bw_volatile = [bv.bandwidth for bv in result_volatile if bv.bandwidth is not None][
        -1
    ]
    bw_stable = [bv.bandwidth for bv in result_stable if bv.bandwidth is not None][-1]

    assert bw_volatile > bw_stable


def test_bollinger_num_std_2_wider_than_1():
    result_1 = calculate_bollinger(SIMPLE_CLOSES, period=3, num_std=1.0)
    result_2 = calculate_bollinger(SIMPLE_CLOSES, period=3, num_std=2.0)
    for b1, b2 in zip(result_1, result_2):
        if b1.upper is not None:
            assert b2.upper > b1.upper
            assert b2.lower < b1.lower


def test_bollinger_percent_b_below_lower():
    # Price below lower band → %B < 0
    closes = [100.0] * 19 + [50.0]
    result = calculate_bollinger(closes, period=10, num_std=2.0)
    last = result[-1]
    assert last.percent_b is not None
    assert last.percent_b < 0.0


def test_bollinger_percent_b_above_upper():
    # Price above upper band → %B > 1
    closes = [100.0] * 19 + [200.0]
    result = calculate_bollinger(closes, period=10, num_std=2.0)
    last = result[-1]
    assert last.percent_b is not None
    assert last.percent_b > 1.0


# ── VALIDATION ERRORS ─────────────────────────────────────────


def test_bollinger_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        calculate_bollinger([], period=20)


def test_bollinger_period_less_than_2_raises():
    with pytest.raises(ValueError, match="period must be >= 2"):
        calculate_bollinger([1.0, 2.0, 3.0], period=1)


def test_bollinger_num_std_zero_raises():
    with pytest.raises(ValueError, match="num_std must be > 0"):
        calculate_bollinger([1.0] * 10, period=5, num_std=0.0)


def test_bollinger_num_std_negative_raises():
    with pytest.raises(ValueError, match="num_std must be > 0"):
        calculate_bollinger([1.0] * 10, period=5, num_std=-1.0)


def test_bollinger_period_exceeds_length_raises():
    with pytest.raises(ValueError, match="cannot exceed"):
        calculate_bollinger([1.0, 2.0], period=5)


# ── BOLLINGER LATEST ──────────────────────────────────────────


def test_bollinger_latest_returns_value():
    result = bollinger_latest(SIMPLE_CLOSES, period=3)
    assert isinstance(result, BollingerValue)


def test_bollinger_latest_not_none():
    result = bollinger_latest(SIMPLE_CLOSES, period=3)
    assert result.middle is not None
    assert result.upper is not None
    assert result.lower is not None


def test_bollinger_latest_matches_last():
    full = calculate_bollinger(SIMPLE_CLOSES, period=3)
    latest = bollinger_latest(SIMPLE_CLOSES, period=3)
    assert math.isclose(latest.middle, full[-1].middle, rel_tol=1e-9)


def test_bollinger_latest_not_enough_raises():
    with pytest.raises(ValueError):
        bollinger_latest([1.0, 2.0], period=20)
