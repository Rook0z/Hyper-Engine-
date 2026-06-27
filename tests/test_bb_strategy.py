import pytest
from strategies.rsi_strategy import RSIStrategy
from strategies.bb_strategy import BollingerStrategy
from strategies.base_strategy import BaseStrategy
from backtester.backtester import Backtester, BacktestResult


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────


def make_candle(ts, open_, close, high=None, low=None, volume=1.0):
    return [ts, open_, high or close * 1.01, low or close * 0.99, close, volume]


def make_candles(prices, start_ts=1_000_000_000_000, interval_ms=3_600_000):
    candles = []
    for i, price in enumerate(prices):
        ts = start_ts + i * interval_ms
        open_ = prices[i - 1] if i > 0 else price
        candles.append(make_candle(ts, open_, price))
    return candles


def stable_then_spike_down(n_stable=25, spike_size=50.0):
    """Stable prices then sharp drop below lower band."""
    stable = [100.0] * n_stable
    spike = [100.0 - spike_size]
    return stable + spike


def stable_then_spike_up(n_stable=25, spike_size=50.0):
    """Stable prices then sharp spike above upper band."""
    stable = [100.0] * n_stable
    spike = [100.0 + spike_size]
    return stable + spike


# ──────────────────────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────────────────────


def test_default_params():
    s = BollingerStrategy()
    assert s.period == 20
    assert s.num_std == 2.0


def test_custom_params():
    s = BollingerStrategy(period=10, num_std=1.5)
    assert s.period == 10
    assert s.num_std == 1.5


def test_period_less_than_2_raises():
    with pytest.raises(ValueError, match="period must be >= 2"):
        BollingerStrategy(period=1)


def test_num_std_zero_raises():
    with pytest.raises(ValueError, match="num_std must be > 0"):
        BollingerStrategy(num_std=0.0)


def test_num_std_negative_raises():
    with pytest.raises(ValueError, match="num_std must be > 0"):
        BollingerStrategy(num_std=-1.0)


def test_name():
    s = BollingerStrategy(period=20, num_std=2.0)
    assert "Bollinger" in s.name
    assert "20" in s.name
    assert "2.0" in s.name


def test_min_periods():
    s = BollingerStrategy(period=20)
    assert s.min_periods == 21  # period + 1


def test_is_base_strategy():
    assert isinstance(BollingerStrategy(), BaseStrategy)


# ──────────────────────────────────────────────────────────────
# SIGNALS — NOT ENOUGH DATA
# ──────────────────────────────────────────────────────────────


def test_hold_not_enough_data():
    s = BollingerStrategy(period=20)
    assert s.generate_signal([100.0] * 10) == "HOLD"


def test_hold_empty():
    s = BollingerStrategy(period=20)
    assert s.generate_signal([]) == "HOLD"


def test_hold_exactly_at_min_minus_1():
    s = BollingerStrategy(period=5)
    assert s.generate_signal([100.0] * 5) == "HOLD"


# ──────────────────────────────────────────────────────────────
# SIGNALS — BUY (LOWER BAND CROSS)
# ──────────────────────────────────────────────────────────────


def test_buy_when_price_crosses_below_lower_band():
    """Stable prices then sharp drop → %B crosses below 0 → BUY."""
    s = BollingerStrategy(period=5, num_std=1.0)
    closes = stable_then_spike_down(n_stable=10, spike_size=20.0)
    signals = [s.generate_signal(closes[: i + 1]) for i in range(len(closes))]
    assert "BUY" in signals


def test_buy_fires_at_lower_band_crossover():
    """BUY fires on the bar where %B first crosses below 0."""
    s = BollingerStrategy(period=5, num_std=1.0)
    closes = stable_then_spike_down(n_stable=10, spike_size=20.0)
    signals = [s.generate_signal(closes[: i + 1]) for i in range(len(closes))]
    buy_index = signals.index("BUY")
    assert buy_index >= s.period


# ──────────────────────────────────────────────────────────────
# SIGNALS — SELL (UPPER BAND CROSS)
# ──────────────────────────────────────────────────────────────


def test_sell_when_price_crosses_above_upper_band():
    """Stable prices then sharp spike → %B crosses above 1 → SELL."""
    s = BollingerStrategy(period=5, num_std=1.0)
    closes = stable_then_spike_up(n_stable=10, spike_size=20.0)
    signals = [s.generate_signal(closes[: i + 1]) for i in range(len(closes))]
    assert "SELL" in signals


def test_signal_returns_valid_string():
    s = BollingerStrategy(period=5)
    closes = [float(i % 10 + 95) for i in range(30)]
    result = s.generate_signal(closes)
    assert result in ("BUY", "SELL", "HOLD")


# ──────────────────────────────────────────────────────────────
# SIGNAL DEDUPLICATION
# ──────────────────────────────────────────────────────────────


def test_buy_fires_only_once_per_episode():
    """BUY should fire once when price stays below lower band."""
    s = BollingerStrategy(period=5, num_std=1.0)
    closes = [100.0] * 10 + [50.0] * 10  # sustained below lower band
    signals = [s.generate_signal(closes[: i + 1]) for i in range(len(closes))]
    assert signals.count("BUY") <= 1


def test_sell_fires_only_once_per_episode():
    s = BollingerStrategy(period=5, num_std=1.0)
    closes = [100.0] * 10 + [150.0] * 10  # sustained above upper band
    signals = [s.generate_signal(closes[: i + 1]) for i in range(len(closes))]
    assert signals.count("SELL") <= 1


# ──────────────────────────────────────────────────────────────
# GET BAND VALUES
# ──────────────────────────────────────────────────────────────


def test_get_band_values_returns_dict():
    s = BollingerStrategy(period=5)
    closes = [float(i) for i in range(1, 20)]
    result = s.get_band_values(closes)
    assert isinstance(result, dict)


def test_get_band_values_keys():
    s = BollingerStrategy(period=5)
    closes = [float(i) for i in range(1, 20)]
    result = s.get_band_values(closes)
    assert "upper" in result
    assert "middle" in result
    assert "lower" in result
    assert "percent_b" in result
    assert "bandwidth" in result


def test_get_band_values_length():
    s = BollingerStrategy(period=5)
    closes = [float(i) for i in range(1, 20)]
    result = s.get_band_values(closes)
    assert len(result["upper"]) == len(closes)
    assert len(result["lower"]) == len(closes)


def test_get_band_values_first_are_none():
    s = BollingerStrategy(period=5)
    closes = [float(i) for i in range(1, 20)]
    result = s.get_band_values(closes)
    assert all(v is None for v in result["upper"][:4])


# ──────────────────────────────────────────────────────────────
# BACKTEST INTEGRATION
# ──────────────────────────────────────────────────────────────


def test_bb_backtest_runs():
    strategy = BollingerStrategy(period=5, num_std=1.0)
    b = Backtester(strategy=strategy, slippage_pct=0.001, position_size=0.001)
    prices = stable_then_spike_down(n_stable=20, spike_size=30.0)
    prices += [100.0] * 10  # recovery
    result = b.run(make_candles(prices))
    assert isinstance(result, BacktestResult)
    assert result.candles_tested == len(prices)


def test_bb_backtest_win_rate_in_range():
    strategy = BollingerStrategy(period=5, num_std=1.0)
    b = Backtester(strategy=strategy)
    prices = (
        [100.0] * 10
        + [60.0] * 3  # spike down → BUY
        + [100.0] * 10
        + [140.0] * 3  # spike up → SELL
        + [100.0] * 5
    )
    result = b.run(make_candles(prices))
    assert 0.0 <= result.win_rate <= 1.0


def test_bb_different_from_rsi_signals():
    """BB uses %B, RSI uses momentum — they measure different things."""
    prices = [100.0] * 10 + [100.0 + i * 3.0 for i in range(20)]

    bb = BollingerStrategy(period=5, num_std=1.0)
    rsi = RSIStrategy(period=5)

    bb_signals = [bb.generate_signal(prices[: i + 1]) for i in range(len(prices))]
    rsi_signals = [rsi.generate_signal(prices[: i + 1]) for i in range(len(prices))]
    assert bb_signals != rsi_signals or "SELL" in rsi_signals


def test_bb_equity_curve_starts_at_capital():
    strategy = BollingerStrategy(period=5, num_std=1.0)
    b = Backtester(strategy=strategy, initial_capital=10_000.0)
    prices = [100.0] * 30
    result = b.run(make_candles(prices))
    assert result.equity_curve[0] == 10_000.0
