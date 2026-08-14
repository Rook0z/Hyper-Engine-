import math
import pytest
from risk.risk_manager import RiskManager, RiskCheckResult


@pytest.fixture
def rm():
    return RiskManager(
        account_balance=10_000.0,
        max_position_pct=0.10,
        max_daily_loss_pct=0.05,
        max_open_positions=3,
        min_position_size=0.001,
    )


# ──────────────────────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────────────────────


def test_init_stores_values(rm):
    assert rm.account_balance == 10_000.0
    assert rm.max_position_pct == 0.10
    assert rm.max_daily_loss_pct == 0.05
    assert rm.max_open_positions == 3


def test_init_zero_balance_raises():
    with pytest.raises(ValueError, match="account_balance"):
        RiskManager(account_balance=0.0)


def test_init_negative_balance_raises():
    with pytest.raises(ValueError):
        RiskManager(account_balance=-1000.0)


def test_init_invalid_position_pct_raises():
    with pytest.raises(ValueError, match="max_position_pct"):
        RiskManager(account_balance=10_000.0, max_position_pct=0.0)


def test_init_position_pct_over_1_raises():
    with pytest.raises(ValueError):
        RiskManager(account_balance=10_000.0, max_position_pct=1.5)


def test_init_zero_max_positions_raises():
    with pytest.raises(ValueError):
        RiskManager(account_balance=10_000.0, max_open_positions=0)


def test_init_zero_min_position_size_raises():
    """
    Regression test for a real gap: min_position_size was never
    validated at construction. A non-positive value silently disables
    the minimum-size safety floor in check_position_size() (the
    `approved_size < self.min_position_size` check can never trigger
    if min_position_size <= 0), so it must be rejected up front.
    """
    with pytest.raises(ValueError, match="min_position_size"):
        RiskManager(account_balance=10_000.0, min_position_size=0.0)


def test_init_negative_min_position_size_raises():
    with pytest.raises(ValueError, match="min_position_size"):
        RiskManager(account_balance=10_000.0, min_position_size=-0.001)


# ──────────────────────────────────────────────────────────────
# DAILY LOSS LIMIT
# ──────────────────────────────────────────────────────────────


def test_daily_loss_under_limit_allowed(rm):
    # limit = 10000 * 0.05 = 500
    result = rm.check_daily_loss_limit(current_daily_loss=100.0)
    assert result.allowed is True


def test_daily_loss_at_limit_blocked(rm):
    # exactly at limit = 500
    result = rm.check_daily_loss_limit(current_daily_loss=500.0)
    assert result.allowed is False


def test_daily_loss_over_limit_blocked(rm):
    result = rm.check_daily_loss_limit(current_daily_loss=600.0)
    assert result.allowed is False
    assert "Daily loss limit" in result.reason


def test_daily_loss_zero_allowed(rm):
    result = rm.check_daily_loss_limit(current_daily_loss=0.0)
    assert result.allowed is True


def test_daily_loss_negative_raises(rm):
    with pytest.raises(ValueError):
        rm.check_daily_loss_limit(current_daily_loss=-100.0)


# ──────────────────────────────────────────────────────────────
# MAX OPEN POSITIONS
# ──────────────────────────────────────────────────────────────


def test_max_positions_under_limit_allowed(rm):
    result = rm.check_max_positions(open_positions=2)
    assert result.allowed is True


def test_max_positions_at_limit_blocked(rm):
    result = rm.check_max_positions(open_positions=3)
    assert result.allowed is False


def test_max_positions_over_limit_blocked(rm):
    result = rm.check_max_positions(open_positions=5)
    assert result.allowed is False
    assert "Max open positions" in result.reason


def test_max_positions_zero_allowed(rm):
    result = rm.check_max_positions(open_positions=0)
    assert result.allowed is True


# ──────────────────────────────────────────────────────────────
# POSITION SIZE CHECK
# ──────────────────────────────────────────────────────────────


def test_position_size_within_limit_approved(rm):
    # max value = 10000 * 0.10 = 1000
    # at price 50000, max size = 1000/50000 = 0.02
    result = rm.check_position_size(price=50_000.0, requested_size=0.01)
    assert result.allowed is True
    assert math.isclose(result.position_size, 0.01)


def test_position_size_capped_at_max(rm):
    # max size at 50000 = 0.02, requesting 0.1 → capped to 0.02
    result = rm.check_position_size(price=50_000.0, requested_size=0.1)
    assert result.allowed is True
    assert math.isclose(result.position_size, 0.02, rel_tol=1e-9)


def test_position_size_below_minimum_blocked(rm):
    # max size at 10_000_000 = 1000/10_000_000 = 0.0001 < min 0.001
    result = rm.check_position_size(price=10_000_000.0, requested_size=0.001)
    assert result.allowed is False
    assert "minimum" in result.reason


def test_position_size_zero_price_raises(rm):
    with pytest.raises(ValueError):
        rm.check_position_size(price=0.0, requested_size=0.001)


def test_position_size_zero_size_raises(rm):
    with pytest.raises(ValueError):
        rm.check_position_size(price=50_000.0, requested_size=0.0)


# ──────────────────────────────────────────────────────────────
# CHECK TRADE — FULL PIPELINE
# ──────────────────────────────────────────────────────────────


def test_check_trade_all_pass(rm):
    result = rm.check_trade(
        symbol="BTC",
        price=50_000.0,
        requested_size=0.01,
        current_daily_loss=0.0,
        open_positions=0,
    )
    assert result.allowed is True


def test_check_trade_daily_loss_fails_first(rm):
    result = rm.check_trade(
        symbol="BTC",
        price=50_000.0,
        requested_size=0.01,
        current_daily_loss=999.0,  # over limit
        open_positions=0,
    )
    assert result.allowed is False
    assert "Daily loss" in result.reason


def test_check_trade_max_positions_fails(rm):
    result = rm.check_trade(
        symbol="BTC",
        price=50_000.0,
        requested_size=0.01,
        current_daily_loss=0.0,
        open_positions=3,  # at max
    )
    assert result.allowed is False
    assert "Max open positions" in result.reason


def test_check_trade_returns_risk_check_result(rm):
    result = rm.check_trade("BTC", 50_000.0, 0.01)
    assert isinstance(result, RiskCheckResult)


# ──────────────────────────────────────────────────────────────
# FIXED POSITION SIZE
# ──────────────────────────────────────────────────────────────


def test_fixed_position_size(rm):
    # 10% of 10000 = 1000 USDC → at 50000, size = 0.02 BTC
    result = rm.fixed_position_size(price=50_000.0)
    assert math.isclose(result, 0.02, rel_tol=1e-9)


def test_fixed_position_size_low_price(rm):
    # 10% of 10000 = 1000 USDC → at 1000, size = 1.0
    result = rm.fixed_position_size(price=1_000.0)
    assert math.isclose(result, 1.0, rel_tol=1e-9)


# ──────────────────────────────────────────────────────────────
# KELLY CRITERION
# ──────────────────────────────────────────────────────────────


def test_kelly_positive_edge():
    """
    win_rate=0.6, avg_win=100, avg_loss=50
    b = 100/50 = 2.0
    kelly% = (2.0 * 0.6 - 0.4) / 2.0 = (1.2 - 0.4) / 2 = 0.8/2 = 0.40
    quarter_kelly = 0.40 * 0.25 = 0.10
    value = 10000 * 0.10 = 1000
    size = 1000 / 50000 = 0.02
    """
    rm = RiskManager(account_balance=10_000.0, max_position_pct=0.10)
    size = rm.kelly_position_size(
        win_rate=0.6,
        avg_win=100.0,
        avg_loss=50.0,
        price=50_000.0,
        kelly_fraction=0.25,
    )
    assert math.isclose(size, 0.02, rel_tol=1e-6)


def test_kelly_no_edge_returns_minimum():
    """
    win_rate=0.3, avg_win=50, avg_loss=100
    b = 50/100 = 0.5
    kelly% = (0.5 * 0.3 - 0.7) / 0.5 = (0.15 - 0.7) / 0.5 = -1.1 → negative
    """
    rm = RiskManager(account_balance=10_000.0, min_position_size=0.001)
    size = rm.kelly_position_size(
        win_rate=0.3,
        avg_win=50.0,
        avg_loss=100.0,
        price=50_000.0,
    )
    assert size == 0.001  # minimum position size


def test_kelly_capped_at_max_position_pct():
    """Kelly > max_position_pct should be capped."""
    rm = RiskManager(account_balance=10_000.0, max_position_pct=0.05)
    # Very high win rate → high Kelly → gets capped
    size = rm.kelly_position_size(
        win_rate=0.9,
        avg_win=200.0,
        avg_loss=10.0,
        price=50_000.0,
        kelly_fraction=1.0,
    )
    max_size = (10_000.0 * 0.05) / 50_000.0
    assert size <= max_size + 1e-9


def test_kelly_win_rate_zero_raises():
    rm = RiskManager(account_balance=10_000.0)
    with pytest.raises(ValueError, match="win_rate"):
        rm.kelly_position_size(0.0, 100.0, 50.0, 50_000.0)


def test_kelly_win_rate_one_raises():
    rm = RiskManager(account_balance=10_000.0)
    with pytest.raises(ValueError, match="win_rate"):
        rm.kelly_position_size(1.0, 100.0, 50.0, 50_000.0)


def test_kelly_avg_win_zero_raises():
    rm = RiskManager(account_balance=10_000.0)
    with pytest.raises(ValueError, match="avg_win"):
        rm.kelly_position_size(0.6, 0.0, 50.0, 50_000.0)


def test_kelly_avg_loss_zero_raises():
    rm = RiskManager(account_balance=10_000.0)
    with pytest.raises(ValueError, match="avg_loss"):
        rm.kelly_position_size(0.6, 100.0, 0.0, 50_000.0)


# ──────────────────────────────────────────────────────────────
# UPDATE BALANCE
# ──────────────────────────────────────────────────────────────


def test_update_balance(rm):
    rm.update_balance(12_000.0)
    assert rm.account_balance == 12_000.0


def test_update_balance_zero_raises(rm):
    with pytest.raises(ValueError):
        rm.update_balance(0.0)


def test_update_balance_negative_raises(rm):
    with pytest.raises(ValueError):
        rm.update_balance(-100.0)


def test_fixed_size_reflects_updated_balance():
    rm = RiskManager(account_balance=10_000.0, max_position_pct=0.10)
    size_before = rm.fixed_position_size(50_000.0)
    rm.update_balance(20_000.0)
    size_after = rm.fixed_position_size(50_000.0)
    assert math.isclose(size_after, size_before * 2, rel_tol=1e-9)
