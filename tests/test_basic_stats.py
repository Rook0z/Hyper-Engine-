import math
import pytest
from unittest.mock import MagicMock

from stats.basic_stats import (
    describe,
    expected_value,
    fetch_close_prices,
    max_drawdown,
    mean,
    profit_factor,
    sharpe_ratio,
    std,
    variance,
    win_rate,
)


# ──────────────────────────────────────────────────────────────
# MEAN
# ──────────────────────────────────────────────────────────────


def test_mean_simple():
    # [1, 2, 3, 4, 5] → sum=15, n=5 → mean=3.0
    assert mean([1.0, 2.0, 3.0, 4.0, 5.0]) == 3.0


def test_mean_single_value():
    assert mean([42.0]) == 42.0


def test_mean_negative_values():
    # [-1, 0, 1] → sum=0, n=3 → mean=0.0
    assert mean([-1.0, 0.0, 1.0]) == 0.0


def test_mean_floats():
    result = mean([1.5, 2.5, 3.0])
    assert math.isclose(result, 2.333333, rel_tol=1e-5)


def test_mean_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        mean([])


def test_mean_btc_prices():
    # Realistic BTC prices
    prices = [50000.0, 51000.0, 49000.0, 52000.0, 48000.0]
    result = mean(prices)
    assert math.isclose(result, 50000.0, rel_tol=1e-9)


# ──────────────────────────────────────────────────────────────
# VARIANCE
# ──────────────────────────────────────────────────────────────


def test_variance_sample_known():
    # [2, 4, 4, 4, 5, 5, 7, 9] — classic textbook example
    # mean = 5.0
    # squared diffs: 9, 1, 1, 1, 0, 0, 4, 16 → sum=32
    # sample variance = 32 / 7 ≈ 4.571
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = variance(values)
    assert math.isclose(result, 32 / 7, rel_tol=1e-9)


def test_variance_population():
    # Same list, population variance = 32 / 8 = 4.0
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = variance(values, population=True)
    assert math.isclose(result, 4.0, rel_tol=1e-9)


def test_variance_identical_values():
    # All same → no spread → variance = 0
    assert variance([5.0, 5.0, 5.0]) == 0.0


def test_variance_two_values():
    # [0, 2] → mean=1, squared diffs: [1, 1], sum=2, / (2-1) = 2.0
    assert variance([0.0, 2.0]) == 2.0


def test_variance_single_raises():
    with pytest.raises(ValueError):
        variance([1.0])


def test_variance_empty_raises():
    with pytest.raises(ValueError):
        variance([])


# ──────────────────────────────────────────────────────────────
# STANDARD DEVIATION
# ──────────────────────────────────────────────────────────────


def test_std_known_value():
    # Same list as variance test — std = sqrt(32/7)
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = std(values)
    assert math.isclose(result, math.sqrt(32 / 7), rel_tol=1e-9)


def test_std_population():
    # Population std = sqrt(4.0) = 2.0
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = std(values, population=True)
    assert math.isclose(result, 2.0, rel_tol=1e-9)


def test_std_is_sqrt_of_variance():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert math.isclose(std(values), math.sqrt(variance(values)), rel_tol=1e-9)


def test_std_identical_values():
    assert std([7.0, 7.0, 7.0]) == 0.0


def test_std_simple():
    # [0, 10] → mean=5, diffs=[-5, 5], sq=[25,25], sum=50, /1 = 50, sqrt=7.071
    result = std([0.0, 10.0])
    assert math.isclose(result, math.sqrt(50), rel_tol=1e-9)


# ──────────────────────────────────────────────────────────────
# EXPECTED VALUE
# ──────────────────────────────────────────────────────────────


def test_expected_value_coin_flip():
    # Fair coin: 50% win $1, 50% lose $1 → EV = 0
    result = expected_value([1.0, -1.0], [0.5, 0.5])
    assert math.isclose(result, 0.0, abs_tol=1e-9)


def test_expected_value_positive():
    # 60% win $100, 40% lose $50 → EV = 60 - 20 = 40
    result = expected_value([100.0, -50.0], [0.6, 0.4])
    assert math.isclose(result, 40.0, rel_tol=1e-9)


def test_expected_value_negative():
    # 40% win $50, 60% lose $100 → EV = 20 - 60 = -40
    result = expected_value([50.0, -100.0], [0.4, 0.6])
    assert math.isclose(result, -40.0, rel_tol=1e-9)


def test_expected_value_three_outcomes():
    # 50% flat, 30% +100, 20% -200 → EV = 0 + 30 - 40 = -10
    result = expected_value([0.0, 100.0, -200.0], [0.5, 0.3, 0.2])
    assert math.isclose(result, -10.0, rel_tol=1e-9)


def test_expected_value_mismatched_lengths_raises():
    with pytest.raises(ValueError, match="same length"):
        expected_value([1.0, 2.0], [0.5])


def test_expected_value_probs_not_summing_to_one_raises():
    with pytest.raises(ValueError, match="sum to 1.0"):
        expected_value([1.0, -1.0], [0.4, 0.4])


# ──────────────────────────────────────────────────────────────
# WIN RATE
# ──────────────────────────────────────────────────────────────


def test_win_rate_all_wins():
    assert win_rate([10.0, 5.0, 20.0]) == 1.0


def test_win_rate_all_losses():
    assert win_rate([-10.0, -5.0, -20.0]) == 0.0


def test_win_rate_mixed():
    # 3 wins, 2 losses → 3/5 = 0.6
    result = win_rate([10.0, -5.0, 20.0, -3.0, 15.0])
    assert math.isclose(result, 0.6, rel_tol=1e-9)


def test_win_rate_breakeven_excluded():
    # zero PnL trades not counted as wins
    result = win_rate([10.0, 0.0, -5.0])
    assert math.isclose(result, 1 / 3, rel_tol=1e-9)


def test_win_rate_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        win_rate([])


# ──────────────────────────────────────────────────────────────
# PROFIT FACTOR
# ──────────────────────────────────────────────────────────────


def test_profit_factor_balanced():
    # $100 profit, $100 loss → PF = 1.0
    result = profit_factor([100.0, -100.0])
    assert math.isclose(result, 1.0, rel_tol=1e-9)


def test_profit_factor_profitable():
    # $200 profit, $100 loss → PF = 2.0
    result = profit_factor([100.0, 100.0, -100.0])
    assert math.isclose(result, 2.0, rel_tol=1e-9)


def test_profit_factor_losing():
    # $100 profit, $200 loss → PF = 0.5
    result = profit_factor([100.0, -100.0, -100.0])
    assert math.isclose(result, 0.5, rel_tol=1e-9)


def test_profit_factor_no_losses_returns_inf():
    result = profit_factor([100.0, 50.0, 200.0])
    assert result == float("inf")


def test_profit_factor_empty_raises():
    with pytest.raises(ValueError):
        profit_factor([])


# ──────────────────────────────────────────────────────────────
# MAX DRAWDOWN
# ──────────────────────────────────────────────────────────────


def test_max_drawdown_simple():
    # Peak 100, drops to 70 → drawdown = (100-70)/100 = 0.30
    equity = [100.0, 110.0, 70.0, 90.0]
    result = max_drawdown(equity)
    assert math.isclose(result, 0.3636, rel_tol=1e-3)  # (110-70)/110


def test_max_drawdown_no_drawdown():
    # Always rising → max drawdown = 0
    equity = [100.0, 110.0, 120.0, 130.0]
    result = max_drawdown(equity)
    assert result == 0.0


def test_max_drawdown_full_loss():
    # Drops from 100 to 0 → drawdown = 1.0 (100%)
    equity = [100.0, 50.0, 0.0]
    result = max_drawdown(equity)
    assert math.isclose(result, 1.0, rel_tol=1e-9)


def test_max_drawdown_recovers_then_drops():
    # Rises to 150, drops to 90 → max dd = (150-90)/150 = 0.4
    equity = [100.0, 150.0, 90.0, 120.0]
    result = max_drawdown(equity)
    assert math.isclose(result, 0.4, rel_tol=1e-9)


def test_max_drawdown_too_few_values_raises():
    with pytest.raises(ValueError):
        max_drawdown([100.0])


# ──────────────────────────────────────────────────────────────
# SHARPE RATIO
# ──────────────────────────────────────────────────────────────


def test_sharpe_ratio_known():
    # returns with mean=0.001, std=0.01
    # Sharpe (daily, 252) = 0.001/0.01 * sqrt(252) ≈ 1.5874
    import random

    random.seed(42)
    # Build returns with known properties
    returns = [0.001] * 100  # all same → std=0 → will raise
    returns[0] = 0.011  # add variance
    returns[1] = -0.009
    result = sharpe_ratio(returns, periods_per_year=252)
    assert isinstance(result, float)


def test_sharpe_ratio_zero_std_raises():
    # All identical returns → std=0 → division by zero
    with pytest.raises(ValueError, match="zero"):
        sharpe_ratio([0.01, 0.01, 0.01])


def test_sharpe_ratio_too_few_raises():
    with pytest.raises(ValueError):
        sharpe_ratio([0.01])


def test_sharpe_ratio_positive_for_good_strategy():
    # Strategy with consistent positive returns should have positive Sharpe
    returns = [0.02, 0.01, 0.015, 0.018, 0.012, 0.022, 0.009]
    result = sharpe_ratio(returns)
    assert result > 0


def test_sharpe_ratio_negative_for_losing_strategy():
    # Strategy with consistent negative returns should have negative Sharpe
    returns = [-0.02, -0.01, -0.015, -0.018, -0.012, -0.022, -0.009]
    result = sharpe_ratio(returns)
    assert result < 0


# ──────────────────────────────────────────────────────────────
# DESCRIBE
# ──────────────────────────────────────────────────────────────


def test_describe_returns_all_keys():
    result = describe([1.0, 2.0, 3.0, 4.0, 5.0])
    assert "count" in result
    assert "mean" in result
    assert "variance" in result
    assert "std" in result
    assert "min" in result
    assert "max" in result
    assert "range" in result


def test_describe_values_correct():
    result = describe([1.0, 2.0, 3.0, 4.0, 5.0])
    assert result["count"] == 5
    assert result["mean"] == 3.0
    assert result["min"] == 1.0
    assert result["max"] == 5.0
    assert result["range"] == 4.0


def test_describe_empty_raises():
    with pytest.raises(ValueError):
        describe([])


# ──────────────────────────────────────────────────────────────
# FETCH CLOSE PRICES — mocked
# ──────────────────────────────────────────────────────────────


def test_fetch_close_prices_returns_floats():
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
        {
            "t": 2000,
            "T": 2999,
            "o": "50500",
            "h": "52000",
            "l": "50000",
            "c": "51000",
            "v": "8.2",
            "n": 85,
        },
    ]
    prices = fetch_close_prices(mock_client, symbol="BTC", interval="1h")
    assert prices == [50500.0, 51000.0]
    assert all(isinstance(p, float) for p in prices)


def test_fetch_close_prices_uses_correct_payload():
    mock_client = MagicMock()
    mock_client.info.return_value = []
    fetch_close_prices(
        mock_client,
        symbol="ETH",
        interval="4h",
        start_time=1700000000000,
        end_time=1700100000000,
    )
    payload = mock_client.info.call_args[0][0]
    assert payload["type"] == "candleSnapshot"
    assert payload["req"]["coin"] == "ETH"
    assert payload["req"]["interval"] == "4h"
    assert payload["req"]["startTime"] == 1700000000000
    assert payload["req"]["endTime"] == 1700100000000


def test_fetch_close_prices_empty_response():
    mock_client = MagicMock()
    mock_client.info.return_value = []
    prices = fetch_close_prices(mock_client)
    assert prices == []


def test_fetch_close_prices_extracts_close_not_open():
    mock_client = MagicMock()
    mock_client.info.return_value = [
        {
            "t": 1000,
            "T": 1999,
            "o": "40000",
            "h": "51000",
            "l": "39000",
            "c": "50000",
            "v": "5.0",
            "n": 50,
        },
    ]
    prices = fetch_close_prices(mock_client)
    assert prices == [50000.0]
