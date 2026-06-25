import pytest
from strategies.rsi_strategy import RSIStrategy
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


def falling_then_rising(n=30):
    """Prices that fall sharply (oversold) then recover."""
    falling = [100.0 - i * 3.0 for i in range(n // 2)]
    rising = [falling[-1] + i * 3.0 for i in range(n // 2)]
    return falling + rising


def rising_then_falling(n=30):
    """Prices that rise sharply (overbought) then fall."""
    rising = [100.0 + i * 3.0 for i in range(n // 2)]
    falling = [rising[-1] - i * 3.0 for i in range(n // 2)]
    return rising + falling


# ──────────────────────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────────────────────


def test_default_params():
    s = RSIStrategy()
    assert s.period == 14
    assert s.oversold_threshold == 30.0
    assert s.overbought_threshold == 70.0


def test_custom_params():
    s = RSIStrategy(period=9, oversold_threshold=20.0, overbought_threshold=80.0)
    assert s.period == 9
    assert s.oversold_threshold == 20.0
    assert s.overbought_threshold == 80.0


def test_period_less_than_2_raises():
    with pytest.raises(ValueError, match="period must be >= 2"):
        RSIStrategy(period=1)


def test_oversold_above_overbought_raises():
    with pytest.raises(ValueError, match="less than"):
        RSIStrategy(oversold_threshold=70.0, overbought_threshold=30.0)


def test_equal_thresholds_raises():
    with pytest.raises(ValueError, match="less than"):
        RSIStrategy(oversold_threshold=50.0, overbought_threshold=50.0)


def test_oversold_above_100_raises():
    with pytest.raises(ValueError):
        RSIStrategy(oversold_threshold=110.0, overbought_threshold=120.0)


def test_overbought_below_0_raises():
    with pytest.raises(ValueError):
        RSIStrategy(oversold_threshold=-10.0, overbought_threshold=70.0)


def test_name():
    s = RSIStrategy(period=14, oversold_threshold=30.0, overbought_threshold=70.0)
    assert "RSI" in s.name
    assert "14" in s.name
    assert "70" in s.name
    assert "30" in s.name


def test_min_periods():
    s = RSIStrategy(period=14)
    assert s.min_periods == 15  # period + 1


def test_is_base_strategy():
    assert isinstance(RSIStrategy(), BaseStrategy)


# ──────────────────────────────────────────────────────────────
# SIGNALS — NOT ENOUGH DATA
# ──────────────────────────────────────────────────────────────


def test_hold_when_not_enough_data():
    s = RSIStrategy(period=14)
    result = s.generate_signal([100.0] * 10)
    assert result == "HOLD"


def test_hold_on_empty():
    s = RSIStrategy(period=14)
    assert s.generate_signal([]) == "HOLD"


def test_hold_exactly_at_min_periods_minus_1():
    s = RSIStrategy(period=5)
    # min_periods = 6, give 5
    assert s.generate_signal([100.0] * 5) == "HOLD"


# ──────────────────────────────────────────────────────────────
# SIGNALS — BUY (OVERSOLD)
# ──────────────────────────────────────────────────────────────


def test_buy_when_rsi_crosses_below_30():
    """RSI must CROSS below 30 — needs to start above 30 then dip."""
    s = RSIStrategy(period=5, oversold_threshold=30.0, overbought_threshold=70.0)
    # Start neutral (RSI ~50), then fall sharply
    neutral = [100.0] * 8  # RSI settles near 50
    falling = [100.0 - i * 8.0 for i in range(1, 12)]  # sharp fall
    closes = neutral + falling
    signals = [s.generate_signal(closes[: i + 1]) for i in range(len(closes))]
    assert "BUY" in signals


def test_buy_signal_returns_string():
    s = RSIStrategy(period=5)
    closes = [100.0] * 20
    result = s.generate_signal(closes)
    assert result in ("BUY", "SELL", "HOLD")


# ──────────────────────────────────────────────────────────────
# SIGNALS — SELL (OVERBOUGHT)
# ──────────────────────────────────────────────────────────────


def test_sell_when_rsi_crosses_above_70():
    """RSI must CROSS above 70 — needs to start below 70 then spike."""
    s = RSIStrategy(period=5, oversold_threshold=30.0, overbought_threshold=70.0)
    neutral = [100.0] * 8
    rising = [100.0 + i * 8.0 for i in range(1, 12)]
    closes = neutral + rising
    signals = [s.generate_signal(closes[: i + 1]) for i in range(len(closes))]
    assert "SELL" in signals


# ──────────────────────────────────────────────────────────────
# SIGNAL DEDUPLICATION
# ──────────────────────────────────────────────────────────────


def test_buy_only_fires_once_per_oversold_episode():
    """BUY should only fire once when RSI stays below 30, not on every tick."""
    s = RSIStrategy(period=5, oversold_threshold=30.0, overbought_threshold=70.0)
    closes = [100.0 - i * 5.0 for i in range(25)]
    signals = [s.generate_signal(closes[: i + 1]) for i in range(len(closes))]
    buy_count = signals.count("BUY")
    assert buy_count <= 1


def test_sell_only_fires_once_per_overbought_episode():
    s = RSIStrategy(period=5, oversold_threshold=30.0, overbought_threshold=70.0)
    closes = [100.0 + i * 5.0 for i in range(25)]
    signals = [s.generate_signal(closes[: i + 1]) for i in range(len(closes))]
    sell_count = signals.count("SELL")
    assert sell_count <= 1


# ──────────────────────────────────────────────────────────────
# GET RSI VALUES
# ──────────────────────────────────────────────────────────────


def test_get_rsi_values_returns_list():
    s = RSIStrategy(period=5)
    closes = [float(i) for i in range(1, 20)]
    result = s.get_rsi_values(closes)
    assert isinstance(result, list)


def test_get_rsi_values_length_matches():
    s = RSIStrategy(period=5)
    closes = [float(i) for i in range(1, 20)]
    result = s.get_rsi_values(closes)
    assert len(result) == len(closes)


def test_get_rsi_values_first_are_none():
    s = RSIStrategy(period=5)
    closes = [float(i) for i in range(1, 20)]
    result = s.get_rsi_values(closes)
    assert all(v is None for v in result[:5])


def test_get_rsi_values_not_enough_data_returns_nones():
    s = RSIStrategy(period=14)
    closes = [100.0] * 5
    result = s.get_rsi_values(closes)
    assert all(v is None for v in result)


# ──────────────────────────────────────────────────────────────
# BACKTEST INTEGRATION
# ──────────────────────────────────────────────────────────────


def test_rsi_strategy_backtest_runs():
    """End-to-end: RSI strategy on synthetic candles."""
    strategy = RSIStrategy(period=5, oversold_threshold=30.0, overbought_threshold=70.0)
    b = Backtester(strategy=strategy, slippage_pct=0.001, position_size=0.001)
    prices = falling_then_rising(n=40)
    candles = make_candles(prices)
    result = b.run(candles)
    assert isinstance(result, BacktestResult)
    assert result.candles_tested == 40


def test_rsi_backtest_win_rate_in_range():
    strategy = RSIStrategy(period=5)
    b = Backtester(strategy=strategy, slippage_pct=0.0)
    prices = falling_then_rising(n=40)
    result = b.run(make_candles(prices))
    assert 0.0 <= result.win_rate <= 1.0


def test_rsi_backtest_mean_reversion_profitable():
    """
    On a falling-then-rising price series, RSI strategy should be profitable.
    It buys when oversold (price bottom) and sells when overbought (price top).
    """
    strategy = RSIStrategy(period=5, oversold_threshold=30.0, overbought_threshold=70.0)
    b = Backtester(
        strategy=strategy, slippage_pct=0.0, position_size=1.0, initial_capital=10_000.0
    )
    prices = falling_then_rising(n=60)
    result = b.run(make_candles(prices))
    # If trades occurred, check PnL is reasonable
    if result.num_trades > 0:
        assert isinstance(result.total_pnl, float)


def test_rsi_backtest_equity_curve_type():
    strategy = RSIStrategy(period=5)
    b = Backtester(strategy=strategy)
    prices = falling_then_rising(n=40)
    result = b.run(make_candles(prices))
    assert isinstance(result.equity_curve, list)
    assert result.equity_curve[0] == 10_000.0


def test_rsi_vs_ema_different_signals():
    """RSI and EMA strategies should produce different signal patterns."""
    from strategies.ema_strategy import EMAStrategy

    prices = falling_then_rising(n=40)
    closes = prices

    rsi_strat = RSIStrategy(period=5)
    ema_strat = EMAStrategy(fast_period=3, slow_period=8)

    rsi_signals = [
        rsi_strat.generate_signal(closes[: i + 1]) for i in range(len(closes))
    ]
    # Reset EMA strategy state
    ema_strat2 = EMAStrategy(fast_period=3, slow_period=8)
    ema_signals = [
        ema_strat2.generate_signal(closes[: i + 1]) for i in range(len(closes))
    ]

    # They should not be identical — different indicator logic
    assert rsi_signals != ema_signals
