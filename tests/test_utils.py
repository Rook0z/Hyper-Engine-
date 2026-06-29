import math
import pytest
from datetime import datetime, timezone
from core.utils import (
    now_iso,
    now_ms,
    ms_to_iso,
    ms_to_datetime,
    format_price,
    format_pnl,
    format_pct,
    round_size,
    round_price,
    pct_change,
    clamp,
)


# ── TIMESTAMP HELPERS ─────────────────────────────────────────


def test_now_iso_returns_string():
    assert isinstance(now_iso(), str)


def test_now_iso_is_utc():
    result = now_iso()
    assert "+00:00" in result


def test_now_iso_format():
    result = now_iso()
    # Should parse without error
    datetime.fromisoformat(result)


def test_now_ms_returns_int():
    assert isinstance(now_ms(), int)


def test_now_ms_is_milliseconds():
    # Current time in ms should be around 1.7 trillion
    ts = now_ms()
    assert ts > 1_700_000_000_000


def test_ms_to_iso_known_value():
    # 0ms = 1970-01-01T00:00:00+00:00
    result = ms_to_iso(0)
    assert "1970-01-01" in result


def test_ms_to_iso_returns_string():
    assert isinstance(ms_to_iso(1_700_000_000_000), str)


def test_ms_to_iso_utc():
    result = ms_to_iso(1_700_000_000_000)
    assert "+00:00" in result


def test_ms_to_datetime_returns_datetime():
    result = ms_to_datetime(1_700_000_000_000)
    assert isinstance(result, datetime)


def test_ms_to_datetime_is_utc():
    result = ms_to_datetime(1_700_000_000_000)
    assert result.tzinfo == timezone.utc


def test_ms_to_datetime_zero():
    result = ms_to_datetime(0)
    assert result.year == 1970


# ── FORMAT PRICE ──────────────────────────────────────────────


def test_format_price_basic():
    assert format_price(50123.456) == "50,123.46"


def test_format_price_commas():
    assert "," in format_price(50000.0)


def test_format_price_custom_decimals():
    assert format_price(50123.456, decimals=0) == "50,123"


def test_format_price_returns_string():
    assert isinstance(format_price(100.0), str)


def test_format_price_small():
    assert format_price(0.5, decimals=4) == "0.5000"


# ── FORMAT PNL ────────────────────────────────────────────────


def test_format_pnl_positive():
    result = format_pnl(0.1234)
    assert result.startswith("+")


def test_format_pnl_negative():
    result = format_pnl(-0.5678)
    assert result.startswith("-")


def test_format_pnl_zero():
    result = format_pnl(0.0)
    assert "+" in result or result == "+0.0000"


def test_format_pnl_decimals():
    result = format_pnl(1.23456789, decimals=2)
    assert result == "+1.23"


def test_format_pnl_returns_string():
    assert isinstance(format_pnl(1.0), str)


# ── FORMAT PCT ────────────────────────────────────────────────


def test_format_pct_basic():
    assert format_pct(0.6) == "60.00%"


def test_format_pct_ends_with_percent():
    assert format_pct(0.386).endswith("%")


def test_format_pct_custom_decimals():
    assert format_pct(0.3846, decimals=1) == "38.5%"


def test_format_pct_zero():
    assert format_pct(0.0) == "0.00%"


def test_format_pct_one():
    assert format_pct(1.0) == "100.00%"


# ── ROUND SIZE ────────────────────────────────────────────────


def test_round_size_5_decimals():
    assert round_size(0.00123456, 5) == 0.00123


def test_round_size_3_decimals():
    assert round_size(0.123456, 3) == 0.123


def test_round_size_floors_not_rounds():
    # 0.0019 with 3 decimals → 0.001 (floor), not 0.002 (round)
    assert round_size(0.0019, 3) == 0.001


def test_round_size_zero_decimals():
    assert round_size(1.9, 0) == 1.0


def test_round_size_exact():
    assert round_size(0.001, 3) == 0.001


# ── ROUND PRICE ───────────────────────────────────────────────


def test_round_price_basic():
    assert round_price(50123.456, tick_size=0.1) == pytest.approx(50123.4)


def test_round_price_integer_tick():
    assert round_price(50123.456, tick_size=1.0) == 50123.0


def test_round_price_floors():
    # 50123.99 with tick 1.0 → 50123 (floor not round)
    assert round_price(50123.99, tick_size=1.0) == 50123.0


def test_round_price_zero_tick_raises():
    with pytest.raises(ValueError):
        round_price(50000.0, tick_size=0.0)


def test_round_price_negative_tick_raises():
    with pytest.raises(ValueError):
        round_price(50000.0, tick_size=-1.0)


def test_round_price_exact():
    assert round_price(50000.0, tick_size=0.5) == 50000.0


# ── PCT CHANGE ────────────────────────────────────────────────


def test_pct_change_increase():
    # 100 → 110 = 10%
    assert math.isclose(pct_change(100.0, 110.0), 0.10, rel_tol=1e-9)


def test_pct_change_decrease():
    # 100 → 90 = -10%
    assert math.isclose(pct_change(100.0, 90.0), -0.10, rel_tol=1e-9)


def test_pct_change_no_change():
    assert pct_change(100.0, 100.0) == 0.0


def test_pct_change_zero_old_raises():
    with pytest.raises(ValueError, match="zero"):
        pct_change(0.0, 100.0)


def test_pct_change_btc_example():
    # BTC goes from 50000 to 55000 = 10%
    assert math.isclose(pct_change(50000.0, 55000.0), 0.10, rel_tol=1e-9)


# ── CLAMP ─────────────────────────────────────────────────────


def test_clamp_below_min():
    assert clamp(0.0005, 0.001, 0.1) == 0.001


def test_clamp_above_max():
    assert clamp(0.5, 0.001, 0.1) == 0.1


def test_clamp_within_range():
    assert clamp(0.01, 0.001, 0.1) == 0.01


def test_clamp_at_min():
    assert clamp(0.001, 0.001, 0.1) == 0.001


def test_clamp_at_max():
    assert clamp(0.1, 0.001, 0.1) == 0.1


def test_clamp_returns_float():
    assert isinstance(clamp(0.05, 0.001, 0.1), float)
