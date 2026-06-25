import math
import pytest
from indicators.rsi import calculate_rsi, rsi_latest, _rsi_from_averages


# ──────────────────────────────────────────────────────────────
# HAND-CALCULATED VERIFICATION
#
# period=3, closes=[10, 11, 12, 11, 13, 12, 14]
#   changes:  +1, +1, -1, +2, -1, +2
#   gains:     1,  1,  0,  2,  0,  2
#   losses:    0,  0,  1,  0,  1,  0
#
#   First avg (mean of first 3):
#       avg_gain = (1+1+0)/3 = 0.6667
#       avg_loss = (0+0+1)/3 = 0.3333
#       RS = 0.6667/0.3333 = 2.0
#       RSI[3] = 100 - 100/(1+2) = 66.67
#
#   Wilder for change[3]=+2 (gain=2, loss=0):
#       avg_gain = (0.6667*2 + 2) / 3 = 1.1111
#       avg_loss = (0.3333*2 + 0) / 3 = 0.2222
#       RS = 1.1111/0.2222 = 5.0
#       RSI[4] = 100 - 100/(1+5) = 83.33
# ──────────────────────────────────────────────────────────────

HAND_CLOSES = [10.0, 11.0, 12.0, 11.0, 13.0, 12.0, 14.0]


# ── RSI FROM AVERAGES ─────────────────────────────────────────


def test_rsi_from_averages_normal():
    # RS=2 → RSI = 100 - 100/3 = 66.67
    result = _rsi_from_averages(avg_gain=2.0, avg_loss=1.0)
    assert math.isclose(result, 66.6667, rel_tol=1e-4)


def test_rsi_from_averages_no_loss_returns_100():
    result = _rsi_from_averages(avg_gain=1.0, avg_loss=0.0)
    assert result == 100.0


def test_rsi_from_averages_no_movement_returns_50():
    result = _rsi_from_averages(avg_gain=0.0, avg_loss=0.0)
    assert result == 50.0


def test_rsi_from_averages_no_gain_returns_low():
    # avg_gain=0, avg_loss=1 → RS=0 → RSI = 100 - 100/1 = 0
    result = _rsi_from_averages(avg_gain=0.0, avg_loss=1.0)
    assert result == 0.0


def test_rsi_from_averages_equal_returns_50():
    # RS=1 → RSI = 100 - 100/2 = 50
    result = _rsi_from_averages(avg_gain=1.0, avg_loss=1.0)
    assert math.isclose(result, 50.0, rel_tol=1e-9)


# ── CALCULATE RSI ─────────────────────────────────────────────


def test_rsi_length_matches_input():
    result = calculate_rsi(HAND_CLOSES, period=3)
    assert len(result) == len(HAND_CLOSES)


def test_rsi_first_values_are_none():
    # period=3 → first 3 values are None
    result = calculate_rsi(HAND_CLOSES, period=3)
    assert result[0] is None
    assert result[1] is None
    assert result[2] is None


def test_rsi_first_calculated_value():
    # RSI[3] = 66.67 (from hand calculation above)
    result = calculate_rsi(HAND_CLOSES, period=3)
    assert math.isclose(result[3], 66.6667, rel_tol=1e-4)


def test_rsi_second_calculated_value():
    # RSI[4] = 83.33 (from hand calculation above)
    result = calculate_rsi(HAND_CLOSES, period=3)
    assert math.isclose(result[4], 83.3333, rel_tol=1e-4)


def test_rsi_range_0_to_100():
    # All RSI values must be between 0 and 100
    closes = [float(50 + i % 10) for i in range(30)]
    result = calculate_rsi(closes, period=14)
    for v in result:
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_rsi_rising_prices_high_rsi():
    # Consistently rising prices → RSI should be high (above 50)
    closes = [100.0 + i * 2.0 for i in range(20)]
    result = calculate_rsi(closes, period=14)
    non_none = [v for v in result if v is not None]
    assert all(v > 50 for v in non_none)


def test_rsi_falling_prices_low_rsi():
    # Consistently falling prices → RSI should be low (below 50)
    closes = [200.0 - i * 2.0 for i in range(20)]
    result = calculate_rsi(closes, period=14)
    non_none = [v for v in result if v is not None]
    assert all(v < 50 for v in non_none)


def test_rsi_flat_prices_returns_50():
    # No movement → avg_gain=0, avg_loss=0 → RSI=50
    closes = [100.0] * 20
    result = calculate_rsi(closes, period=14)
    non_none = [v for v in result if v is not None]
    assert all(math.isclose(v, 50.0, abs_tol=1e-6) for v in non_none)


def test_rsi_pure_up_returns_100():
    # Only gains, no losses → RSI = 100
    closes = [100.0 + i * 10.0 for i in range(20)]
    result = calculate_rsi(closes, period=14)
    non_none = [v for v in result if v is not None]
    assert all(math.isclose(v, 100.0, abs_tol=1e-6) for v in non_none)


def test_rsi_pure_down_returns_0():
    # Only losses, no gains → RSI = 0
    closes = [200.0 - i * 10.0 for i in range(20)]
    result = calculate_rsi(closes, period=14)
    non_none = [v for v in result if v is not None]
    assert all(math.isclose(v, 0.0, abs_tol=1e-6) for v in non_none)


def test_rsi_default_period_14():
    closes = [float(i) for i in range(1, 30)]
    result = calculate_rsi(closes)
    # First 14 should be None
    assert all(v is None for v in result[:14])
    assert result[14] is not None


def test_rsi_period_2():
    closes = [10.0, 11.0, 10.0, 12.0]
    result = calculate_rsi(closes, period=2)
    assert result[0] is None
    assert result[1] is None
    assert result[2] is not None


# ── VALIDATION ERRORS ─────────────────────────────────────────


def test_rsi_empty_closes_raises():
    with pytest.raises(ValueError, match="empty"):
        calculate_rsi([], period=14)


def test_rsi_period_less_than_2_raises():
    with pytest.raises(ValueError, match="period must be >= 2"):
        calculate_rsi([1.0, 2.0, 3.0], period=1)


def test_rsi_period_equals_length_raises():
    # Need period + 1 closes — period == len(closes) is not enough
    with pytest.raises(ValueError, match="less than"):
        calculate_rsi([1.0, 2.0, 3.0], period=3)


def test_rsi_period_exceeds_length_raises():
    with pytest.raises(ValueError, match="less than"):
        calculate_rsi([1.0, 2.0], period=5)


# ── RSI LATEST ────────────────────────────────────────────────


def test_rsi_latest_returns_float():
    closes = [float(i) for i in range(1, 20)]
    result = rsi_latest(closes, period=14)
    assert isinstance(result, float)


def test_rsi_latest_matches_last_value():
    closes = [float(i) for i in range(1, 20)]
    full = calculate_rsi(closes, period=14)
    assert math.isclose(rsi_latest(closes, period=14), full[-1], rel_tol=1e-9)


def test_rsi_latest_in_range():
    closes = [float(i) for i in range(1, 20)]
    result = rsi_latest(closes, period=14)
    assert 0.0 <= result <= 100.0


def test_rsi_latest_not_enough_data_raises():
    with pytest.raises(ValueError):
        rsi_latest([1.0, 2.0, 3.0], period=14)


# ── WILDER SMOOTHING PROPERTY ─────────────────────────────────


def test_wilder_smoother_than_simple_average():
    """Wilder smoothing — test with mixed data so avg_loss > 0."""
    # Mix of up and down bars so avg_loss is never zero
    prices = [
        100.0,
        102.0,
        98.0,
        103.0,
        99.0,
        104.0,
        100.0,
        105.0,
        101.0,
        106.0,
        102.0,
        107.0,
        103.0,
        108.0,
        104.0,
        # Now spike up
        120.0,
        130.0,
        140.0,
        150.0,
        160.0,
    ]
    rsi_vals = calculate_rsi(prices, period=14)
    non_none = [v for v in rsi_vals if v is not None]
    last = non_none[-1]
    assert last > 50.0  # spike pulled RSI up
    assert last < 100.0  # but Wilder smoothing — not instantly 100
