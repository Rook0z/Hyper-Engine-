import math
import numpy as np
import pytest
from stats.basic_stats import (
    describe,
    expected_value,
    fetch_close_prices,
    log_returns,
    max_drawdown,
    mean,
    pct_returns,
    profit_factor,
    rolling_mean,
    rolling_std,
    sharpe_ratio,
    std,
    variance,
    win_rate,
)
from unittest.mock import MagicMock


# ── MEAN ──────────────────────────────────────────────────────


def test_mean_simple():
    assert mean([1.0, 2.0, 3.0, 4.0, 5.0]) == 3.0


def test_mean_single():
    assert mean([42.0]) == 42.0


def test_mean_negative():
    assert mean([-1.0, 0.0, 1.0]) == 0.0


def test_mean_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        mean([])


def test_mean_returns_float():
    assert isinstance(mean([1.0, 2.0, 3.0]), float)


# ── VARIANCE ──────────────────────────────────────────────────


def test_variance_sample_known():
    # [2,4,4,4,5,5,7,9] → sample variance = 32/7
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    assert math.isclose(variance(values), 32 / 7, rel_tol=1e-9)


def test_variance_population():
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    assert math.isclose(variance(values, population=True), 4.0, rel_tol=1e-9)


def test_variance_identical_values():
    assert variance([5.0, 5.0, 5.0]) == 0.0


def test_variance_single_raises():
    with pytest.raises(ValueError):
        variance([1.0])


def test_variance_empty_raises():
    with pytest.raises(ValueError):
        variance([])


# ── STD ───────────────────────────────────────────────────────


def test_std_known():
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    assert math.isclose(std(values), math.sqrt(32 / 7), rel_tol=1e-9)


def test_std_population():
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    assert math.isclose(std(values, population=True), 2.0, rel_tol=1e-9)


def test_std_is_sqrt_of_variance():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert math.isclose(std(values), math.sqrt(variance(values)), rel_tol=1e-9)


def test_std_identical_values():
    assert std([7.0, 7.0, 7.0]) == 0.0


def test_std_single_raises():
    with pytest.raises(ValueError):
        std([1.0])


# ── EXPECTED VALUE ────────────────────────────────────────────


def test_ev_coin_flip():
    # 50/50 win/lose $1 → EV = 0
    assert math.isclose(expected_value([1.0, -1.0], [0.5, 0.5]), 0.0, abs_tol=1e-9)


def test_ev_positive():
    # 60% win $100, 40% lose $50 → EV = 40
    assert math.isclose(expected_value([100.0, -50.0], [0.6, 0.4]), 40.0, rel_tol=1e-9)


def test_ev_negative():
    assert math.isclose(expected_value([50.0, -100.0], [0.4, 0.6]), -40.0, rel_tol=1e-9)


def test_ev_uses_dot_product():
    # numpy dot product should give same as manual calculation
    outcomes = [100.0, 50.0, -200.0]
    probs = [0.5, 0.3, 0.2]
    expected = 100 * 0.5 + 50 * 0.3 + (-200) * 0.2
    assert math.isclose(expected_value(outcomes, probs), expected, rel_tol=1e-9)


def test_ev_mismatched_raises():
    with pytest.raises(ValueError, match="same length"):
        expected_value([1.0, 2.0], [0.5])


def test_ev_probs_not_one_raises():
    with pytest.raises(ValueError, match="sum to 1.0"):
        expected_value([1.0, -1.0], [0.4, 0.4])


# ── WIN RATE ──────────────────────────────────────────────────


def test_win_rate_all_wins():
    assert win_rate([10.0, 5.0, 20.0]) == 1.0


def test_win_rate_all_losses():
    assert win_rate([-10.0, -5.0]) == 0.0


def test_win_rate_mixed():
    assert math.isclose(win_rate([10.0, -5.0, 20.0, -3.0, 15.0]), 0.6, rel_tol=1e-9)


def test_win_rate_uses_boolean_mask():
    # zero PnL not counted as win
    assert math.isclose(win_rate([10.0, 0.0, -5.0]), 1 / 3, rel_tol=1e-9)


def test_win_rate_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        win_rate([])


# ── PROFIT FACTOR ─────────────────────────────────────────────


def test_profit_factor_balanced():
    assert math.isclose(profit_factor([100.0, -100.0]), 1.0)


def test_profit_factor_profitable():
    assert math.isclose(profit_factor([200.0, -100.0]), 2.0)


def test_profit_factor_no_losses_inf():
    assert profit_factor([100.0, 50.0]) == float("inf")


def test_profit_factor_no_wins_zero():
    assert profit_factor([-100.0, -50.0]) == 0.0


def test_profit_factor_empty_raises():
    with pytest.raises(ValueError):
        profit_factor([])


# ── MAX DRAWDOWN ──────────────────────────────────────────────


def test_max_drawdown_uses_accumulate():
    # Peak 110, trough 70 → (110-70)/110
    equity = [100.0, 110.0, 70.0, 90.0]
    assert math.isclose(max_drawdown(equity), (110 - 70) / 110, rel_tol=1e-9)


def test_max_drawdown_no_drawdown():
    assert max_drawdown([100.0, 110.0, 120.0]) == 0.0


def test_max_drawdown_recovers_then_drops():
    # Peak 150, drops to 90 → (150-90)/150 = 0.4
    equity = [100.0, 150.0, 90.0, 120.0]
    assert math.isclose(max_drawdown(equity), 0.4, rel_tol=1e-9)


def test_max_drawdown_too_few_raises():
    with pytest.raises(ValueError):
        max_drawdown([100.0])


# ── SHARPE RATIO ──────────────────────────────────────────────


def test_sharpe_positive_for_gains():
    returns = [0.02, 0.01, 0.015, 0.018, 0.012, 0.022]
    assert sharpe_ratio(returns) > 0


def test_sharpe_negative_for_losses():
    returns = [-0.02, -0.01, -0.015, -0.018]
    assert sharpe_ratio(returns) < 0


def test_sharpe_zero_for_single():
    assert sharpe_ratio([0.01]) == 0.0


def test_sharpe_zero_for_identical():
    assert sharpe_ratio([0.01, 0.01, 0.01]) == 0.0


# ── DESCRIBE ──────────────────────────────────────────────────


def test_describe_keys():
    result = describe([1.0, 2.0, 3.0, 4.0, 5.0])
    assert all(
        k in result for k in ["count", "mean", "variance", "std", "min", "max", "range"]
    )


def test_describe_values():
    result = describe([1.0, 2.0, 3.0, 4.0, 5.0])
    assert result["count"] == 5.0
    assert result["mean"] == 3.0
    assert result["min"] == 1.0
    assert result["max"] == 5.0
    assert result["range"] == 4.0


def test_describe_empty_raises():
    with pytest.raises(ValueError):
        describe([])


# ── PCT RETURNS ───────────────────────────────────────────────


def test_pct_returns_simple():
    # [100, 110] → return = 0.10
    result = pct_returns([100.0, 110.0])
    assert math.isclose(result[0], 0.10, rel_tol=1e-9)


def test_pct_returns_length():
    prices = [100.0, 110.0, 121.0, 133.1]
    result = pct_returns(prices)
    assert len(result) == 3


def test_pct_returns_returns_ndarray():
    result = pct_returns([100.0, 110.0, 120.0])
    assert isinstance(result, np.ndarray)


def test_pct_returns_negative():
    result = pct_returns([100.0, 90.0])
    assert math.isclose(result[0], -0.10, rel_tol=1e-9)


def test_pct_returns_too_few_raises():
    with pytest.raises(ValueError):
        pct_returns([100.0])


# ── LOG RETURNS ───────────────────────────────────────────────


def test_log_returns_simple():
    # ln(110/100) = ln(1.1)
    result = log_returns([100.0, 110.0])
    assert math.isclose(result[0], math.log(1.1), rel_tol=1e-9)


def test_log_returns_returns_ndarray():
    result = log_returns([100.0, 110.0, 120.0])
    assert isinstance(result, np.ndarray)


def test_log_returns_length():
    result = log_returns([100.0, 110.0, 121.0])
    assert len(result) == 2


def test_log_returns_too_few_raises():
    with pytest.raises(ValueError):
        log_returns([100.0])


# ── ROLLING MEAN ─────────────────────────────────────────────


def test_rolling_mean_simple():
    # [1,2,3,4,5] window=3 → [nan,nan,2,3,4]
    result = rolling_mean([1.0, 2.0, 3.0, 4.0, 5.0], window=3)
    assert np.isnan(result[0])
    assert np.isnan(result[1])
    assert math.isclose(result[2], 2.0, rel_tol=1e-9)
    assert math.isclose(result[3], 3.0, rel_tol=1e-9)
    assert math.isclose(result[4], 4.0, rel_tol=1e-9)


def test_rolling_mean_length():
    result = rolling_mean([1.0, 2.0, 3.0, 4.0, 5.0], window=2)
    assert len(result) == 5


def test_rolling_mean_nans_at_start():
    result = rolling_mean([1.0] * 10, window=5)
    assert sum(np.isnan(result)) == 4


def test_rolling_mean_invalid_window_raises():
    with pytest.raises(ValueError):
        rolling_mean([1.0, 2.0, 3.0], window=0)


def test_rolling_mean_window_too_large_raises():
    with pytest.raises(ValueError):
        rolling_mean([1.0, 2.0], window=5)


# ── ROLLING STD ───────────────────────────────────────────────


def test_rolling_std_length():
    result = rolling_std([1.0, 2.0, 3.0, 4.0, 5.0], window=3)
    assert len(result) == 5


def test_rolling_std_nans_at_start():
    result = rolling_std([1.0] * 10, window=4)
    assert sum(np.isnan(result)) == 3


def test_rolling_std_flat_is_zero():
    result = rolling_std([5.0] * 5, window=3)
    for v in result[2:]:
        assert math.isclose(v, 0.0, abs_tol=1e-9)


def test_rolling_std_window_1_raises():
    with pytest.raises(ValueError):
        rolling_std([1.0, 2.0, 3.0], window=1)


# ── FETCH CLOSE PRICES ────────────────────────────────────────


def test_fetch_returns_floats():
    mock_client = MagicMock()
    mock_client.info.return_value = [
        {
            "t": 1000,
            "T": 1999,
            "o": "50000",
            "h": "51000",
            "l": "49000",
            "c": "50500",
            "v": "10.5",
            "n": 100,
        },
    ]
    prices = fetch_close_prices(mock_client, symbol="BTC")
    assert prices == [50500.0]
    assert isinstance(prices[0], float)


def test_fetch_empty_returns_empty():
    mock_client = MagicMock()
    mock_client.info.return_value = []
    assert fetch_close_prices(mock_client) == []
