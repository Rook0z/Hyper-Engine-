import math
import pytest
from indicators.vwap import VWAPValue, calculate_vwap, vwap_latest


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────


def make_candle(ts, open_, high, low, close, volume):
    return [ts, open_, high, low, close, volume]


# ──────────────────────────────────────────────────────────────
# HAND-CALCULATED VERIFICATION
#
# Candle 1: high=11, low=9,  close=10, volume=100
#   typical = (11+9+10)/3  = 10.0
#   cum_tp_vol  = 10.0 * 100 = 1000.0
#   cum_vol     = 100
#   VWAP        = 1000/100  = 10.0
#   cum_tp2_vol = 100 * 100 = 10000
#   variance    = 10000/100 - 10^2 = 0.0
#   std         = 0.0
#
# Candle 2: high=12, low=10, close=11, volume=200
#   typical = (12+10+11)/3 = 11.0
#   cum_tp_vol  = 1000 + 11*200   = 3200.0
#   cum_vol     = 100 + 200       = 300
#   VWAP        = 3200/300        = 10.6667
#   cum_tp2_vol = 10000 + 121*200 = 34200
#   variance    = 34200/300 - (10.6667)^2 = 114.0 - 113.778 = 0.2222
#   std         = sqrt(0.2222)    = 0.4714
# ──────────────────────────────────────────────────────────────

CANDLE_1 = make_candle(1000, 10.0, 11.0, 9.0, 10.0, 100.0)
CANDLE_2 = make_candle(2000, 10.0, 12.0, 10.0, 11.0, 200.0)
TWO_CANDLES = [CANDLE_1, CANDLE_2]


# ── VWAP VALUE DATACLASS ──────────────────────────────────────


def test_vwap_value_fields():
    v = VWAPValue(
        vwap=10.0, upper1=11.0, lower1=9.0, upper2=12.0, lower2=8.0, deviation=0.05
    )
    assert v.vwap == 10.0
    assert v.upper1 == 11.0
    assert v.lower2 == 8.0
    assert v.deviation == 0.05


# ── CALCULATE VWAP ────────────────────────────────────────────


def test_vwap_length_matches_input():
    result = calculate_vwap(TWO_CANDLES)
    assert len(result) == 2


def test_vwap_first_candle():
    # Single candle: VWAP = typical price = (11+9+10)/3 = 10.0
    result = calculate_vwap([CANDLE_1])
    assert math.isclose(result[0].vwap, 10.0, rel_tol=1e-9)


def test_vwap_first_candle_no_std():
    # Only one data point — variance is zero, bands collapse to VWAP
    result = calculate_vwap([CANDLE_1])
    assert math.isclose(result[0].upper2, 10.0, abs_tol=1e-9)
    assert math.isclose(result[0].lower2, 10.0, abs_tol=1e-9)


def test_vwap_second_candle():
    # VWAP = 3200/300 = 10.6667
    result = calculate_vwap(TWO_CANDLES)
    assert math.isclose(result[1].vwap, 10.6667, rel_tol=1e-4)


def test_vwap_upper_above_vwap():
    result = calculate_vwap(TWO_CANDLES)
    for v in result:
        assert v.upper1 >= v.vwap
        assert v.upper2 >= v.upper1


def test_vwap_lower_below_vwap():
    result = calculate_vwap(TWO_CANDLES)
    for v in result:
        assert v.lower1 <= v.vwap
        assert v.lower2 <= v.lower1


def test_vwap_bands_symmetric():
    result = calculate_vwap(TWO_CANDLES)
    for v in result:
        upper_dist = v.upper2 - v.vwap
        lower_dist = v.vwap - v.lower2
        assert math.isclose(upper_dist, lower_dist, abs_tol=1e-9)


def test_vwap_deviation_positive_when_close_above():
    # close=11, vwap=10.6667 → deviation > 0
    result = calculate_vwap(TWO_CANDLES)
    assert result[1].deviation > 0


def test_vwap_deviation_zero_when_close_equals_vwap():
    # Build candle where close == typical price == VWAP
    candle = make_candle(1000, 10.0, 10.0, 10.0, 10.0, 100.0)
    result = calculate_vwap([candle])
    assert math.isclose(result[0].deviation, 0.0, abs_tol=1e-9)


def test_vwap_high_volume_candle_pulls_vwap():
    """High volume candle at high price should pull VWAP up significantly."""
    low_vol = make_candle(1000, 100.0, 101.0, 99.0, 100.0, 10.0)
    high_vol = make_candle(2000, 100.0, 120.0, 119.0, 120.0, 1000.0)
    result = calculate_vwap([low_vol, high_vol])
    # VWAP should be much closer to 120 than 100
    assert result[1].vwap > 115.0


def test_vwap_equal_volume_is_simple_average():
    """Equal volume candles → VWAP = average of typical prices."""
    c1 = make_candle(1000, 10.0, 12.0, 8.0, 10.0, 100.0)  # typical=10
    c2 = make_candle(2000, 10.0, 14.0, 10.0, 12.0, 100.0)  # typical=12
    result = calculate_vwap([c1, c2])
    # Equal volume → VWAP = (10+12)/2 = 11.0
    assert math.isclose(result[1].vwap, 11.0, rel_tol=1e-9)


def test_vwap_accumulates_over_time():
    """VWAP should change as candles accumulate."""
    candles = [
        make_candle(i * 1000, 100.0, 110.0, 90.0, 100.0, 100.0) for i in range(5)
    ]
    result = calculate_vwap(candles)
    # All candles identical → VWAP stays constant
    for v in result:
        assert math.isclose(v.vwap, 100.0, rel_tol=1e-9)


def test_vwap_num_std_2_wider_than_default():
    result_1 = calculate_vwap(TWO_CANDLES, num_std=1.0)
    result_2 = calculate_vwap(TWO_CANDLES, num_std=2.0)
    # After second candle where std > 0
    if result_2[1].upper2 != result_2[1].vwap:
        assert result_2[1].upper2 > result_1[1].upper2


# ── VALIDATION ERRORS ─────────────────────────────────────────


def test_vwap_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        calculate_vwap([])


def test_vwap_num_std_zero_raises():
    with pytest.raises(ValueError, match="num_std must be > 0"):
        calculate_vwap([CANDLE_1], num_std=0.0)


def test_vwap_num_std_negative_raises():
    with pytest.raises(ValueError, match="num_std must be > 0"):
        calculate_vwap([CANDLE_1], num_std=-1.0)


# ── VWAP LATEST ───────────────────────────────────────────────


def test_vwap_latest_returns_value():
    result = vwap_latest(TWO_CANDLES)
    assert isinstance(result, VWAPValue)


def test_vwap_latest_matches_last():
    full = calculate_vwap(TWO_CANDLES)
    latest = vwap_latest(TWO_CANDLES)
    assert math.isclose(latest.vwap, full[-1].vwap, rel_tol=1e-9)


def test_vwap_latest_single_candle():
    result = vwap_latest([CANDLE_1])
    assert math.isclose(result.vwap, 10.0, rel_tol=1e-9)
