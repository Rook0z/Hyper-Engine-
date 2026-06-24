import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock
from backtester.backtester import Backtester, BacktestResult, Trade
from strategies.base_strategy import BaseStrategy
from strategies.ema_strategy import EMAStrategy


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────


def make_candle(timestamp, open_, close, high=None, low=None, volume=1.0):
    high = high or close * 1.01
    low = low or close * 0.99
    return [timestamp, open_, high, low, close, volume]


def make_candles(prices, start_ts=1_000_000_000_000, interval_ms=3_600_000):
    candles = []
    for i, price in enumerate(prices):
        ts = start_ts + i * interval_ms
        open_ = prices[i - 1] if i > 0 else price
        candles.append(make_candle(ts, open_, price))
    return candles


def mock_strategy(signals):
    strategy = MagicMock(spec=BaseStrategy)
    strategy.name = "MockStrategy"
    strategy.min_periods = 1
    signal_iter = iter(signals)
    strategy.generate_signal.side_effect = lambda closes: next(signal_iter, "HOLD")
    return strategy


# ──────────────────────────────────────────────────────────────
# BUILD DATAFRAME
# ──────────────────────────────────────────────────────────────


def test_build_dataframe_columns():
    b = Backtester(strategy=mock_strategy([]))
    candles = make_candles([100.0, 110.0, 120.0])
    df = b._build_dataframe(candles)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


def test_build_dataframe_types():
    b = Backtester(strategy=mock_strategy([]))
    candles = make_candles([100.0, 110.0])
    df = b._build_dataframe(candles)
    assert df["close"].dtype == np.float64
    assert df["timestamp"].dtype == np.int64


def test_build_dataframe_row_count():
    b = Backtester(strategy=mock_strategy([]))
    candles = make_candles([100.0] * 5)
    df = b._build_dataframe(candles)
    assert len(df) == 5


# ──────────────────────────────────────────────────────────────
# GENERATE SIGNALS
# ──────────────────────────────────────────────────────────────


def test_generate_signals_adds_column():
    s = mock_strategy(["HOLD"] * 5)
    b = Backtester(strategy=s)
    candles = make_candles([100.0] * 5)
    df = b._build_dataframe(candles)
    df = b._generate_signals(df)
    assert "signal" in df.columns


def test_generate_signals_length_matches():
    s = mock_strategy(["HOLD"] * 5)
    b = Backtester(strategy=s)
    candles = make_candles([100.0] * 5)
    df = b._build_dataframe(candles)
    df = b._generate_signals(df)
    assert len(df["signal"]) == 5


def test_generate_signals_values_are_strings():
    s = mock_strategy(["BUY", "HOLD", "SELL", "HOLD", "HOLD"])
    b = Backtester(strategy=s)
    candles = make_candles([100.0] * 5)
    df = b._build_dataframe(candles)
    df = b._generate_signals(df)
    assert all(isinstance(v, str) for v in df["signal"])


# ──────────────────────────────────────────────────────────────
# RUN — BASIC
# ──────────────────────────────────────────────────────────────


def test_run_returns_backtest_result():
    s = mock_strategy(["HOLD"] * 10)
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 10))
    assert isinstance(result, BacktestResult)


def test_run_too_few_candles():
    s = mock_strategy([])
    b = Backtester(strategy=s)
    result = b.run([make_candle(0, 100.0, 100.0)])
    assert result.num_trades == 0


def test_run_empty_candles():
    s = mock_strategy([])
    b = Backtester(strategy=s)
    result = b.run([])
    assert result.num_trades == 0


def test_run_all_hold_no_trades():
    s = mock_strategy(["HOLD"] * 10)
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 10))
    assert result.num_trades == 0


def test_run_records_candles_tested():
    s = mock_strategy(["HOLD"] * 10)
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 10))
    assert result.candles_tested == 10


def test_run_sets_strategy_name():
    s = mock_strategy(["HOLD"])
    s.name = "TestStrategy"
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 5))
    assert result.strategy_name == "TestStrategy"


# ──────────────────────────────────────────────────────────────
# TRADE EXECUTION
# ──────────────────────────────────────────────────────────────


def test_buy_then_sell_creates_one_trade():
    s = mock_strategy(["BUY", "HOLD", "SELL", "HOLD"])
    b = Backtester(strategy=s, slippage_pct=0.0)
    result = b.run(make_candles([100.0, 110.0, 120.0, 130.0, 140.0]))
    assert result.num_trades == 1


def test_trade_fills_at_next_open():
    s = mock_strategy(["BUY", "HOLD", "SELL", "HOLD"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),  # BUY fills here
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),  # SELL fills here
        make_candle(5000, 300.0, 310.0),
    ]
    result = b.run(candles)
    assert result.num_trades == 1
    assert result.trades[0].entry_price == 150.0
    assert result.trades[0].exit_price == 250.0


def test_profitable_trade_positive_pnl():
    s = mock_strategy(["BUY", "HOLD", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
    ]
    result = b.run(candles)
    assert result.total_pnl > 0


def test_losing_trade_negative_pnl():
    s = mock_strategy(["BUY", "HOLD", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = [
        make_candle(1000, 300.0, 290.0),
        make_candle(2000, 250.0, 240.0),
        make_candle(3000, 150.0, 140.0),
        make_candle(4000, 100.0, 90.0),
    ]
    result = b.run(candles)
    assert result.total_pnl < 0


def test_no_double_entry():
    s = mock_strategy(["BUY", "BUY", "BUY", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    result = b.run(make_candles([100.0, 110.0, 120.0, 130.0, 140.0]))
    assert result.num_trades == 1


def test_no_exit_without_entry():
    s = mock_strategy(["SELL", "SELL", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0)
    result = b.run(make_candles([100.0, 90.0, 80.0, 70.0]))
    assert result.num_trades == 0


def test_open_position_force_closed():
    s = mock_strategy(["BUY"] + ["HOLD"] * 10)
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    result = b.run(make_candles([100.0, 110.0, 120.0, 130.0]))
    assert result.num_trades == 1


# ──────────────────────────────────────────────────────────────
# SLIPPAGE
# ──────────────────────────────────────────────────────────────


def test_slippage_buy_above_price():
    b = Backtester(strategy=mock_strategy([]), slippage_pct=0.01)
    assert b.slippage_pct == 0.01


def test_slippage_reduces_pnl():
    prices = [100.0, 100.0, 200.0, 200.0]
    candles_no_slip = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
    ]
    s1 = mock_strategy(["BUY", "HOLD", "SELL"])
    b1 = Backtester(strategy=s1, slippage_pct=0.0, position_size=1.0)
    s2 = mock_strategy(["BUY", "HOLD", "SELL"])
    b2 = Backtester(strategy=s2, slippage_pct=0.01, position_size=1.0)
    r1 = b1.run(candles_no_slip)
    r2 = b2.run(candles_no_slip)
    assert r1.total_pnl > r2.total_pnl


# ──────────────────────────────────────────────────────────────
# PERFORMANCE METRICS
# ──────────────────────────────────────────────────────────────


def test_win_rate_all_winners():
    s = mock_strategy(["BUY", "SELL", "BUY", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
        make_candle(5000, 300.0, 310.0),
        make_candle(6000, 350.0, 360.0),
    ]
    result = b.run(candles)
    assert result.win_rate == 1.0


def test_equity_curve_starts_at_initial_capital():
    s = mock_strategy(["HOLD"] * 5)
    b = Backtester(strategy=s, initial_capital=10_000.0)
    result = b.run(make_candles([100.0] * 5))
    assert result.equity_curve[0] == 10_000.0


def test_equity_curve_increases_on_profit():
    s = mock_strategy(["BUY", "HOLD", "SELL"])
    b = Backtester(
        strategy=s, slippage_pct=0.0, position_size=1.0, initial_capital=10_000.0
    )
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
    ]
    result = b.run(candles)
    assert result.equity_curve[-1] > 10_000.0


def test_max_drawdown_no_loss():
    s = mock_strategy(["HOLD"] * 10)
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 10))
    assert result.max_drawdown == 0.0


# ──────────────────────────────────────────────────────────────
# PANDAS SPECIFIC — SUMMARY BY DAY
# ──────────────────────────────────────────────────────────────


def test_summary_by_day_returns_dataframe():
    s = mock_strategy(["BUY", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
    ]
    result = b.run(candles)
    daily = b.summary_by_day(result)
    assert isinstance(daily, pd.DataFrame)


def test_summary_by_day_empty_result():
    s = mock_strategy(["HOLD"] * 5)
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 5))
    daily = b.summary_by_day(result)
    assert len(daily) == 0


def test_summary_by_day_columns():
    s = mock_strategy(["HOLD"] * 5)
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 5))
    daily = b.summary_by_day(result)
    assert "num_trades" in daily.columns
    assert "total_pnl" in daily.columns
    assert "win_rate" in daily.columns


# ──────────────────────────────────────────────────────────────
# PANDAS SPECIFIC — EQUITY AS SERIES
# ──────────────────────────────────────────────────────────────


def test_equity_as_series_returns_series():
    s = mock_strategy(["HOLD"] * 5)
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 5))
    eq = b.equity_as_series(result)
    assert isinstance(eq, pd.Series)


def test_equity_as_series_name():
    s = mock_strategy(["HOLD"] * 5)
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 5))
    eq = b.equity_as_series(result)
    assert eq.name == "equity"


def test_equity_as_series_length():
    s = mock_strategy(["BUY", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0)
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
    ]
    result = b.run(candles)
    eq = b.equity_as_series(result)
    assert len(eq) == result.num_trades + 1


# ──────────────────────────────────────────────────────────────
# INTEGRATION — EMA STRATEGY ON SYNTHETIC DATA
# ──────────────────────────────────────────────────────────────


def test_ema_strategy_backtest_runs():
    strategy = EMAStrategy(fast_period=3, slow_period=5)
    b = Backtester(strategy=strategy, slippage_pct=0.001, position_size=0.001)
    prices = [100 + i * 2.0 for i in range(15)] + [130 - i * 2.0 for i in range(15)]
    result = b.run(make_candles(prices))
    assert isinstance(result, BacktestResult)
    assert result.candles_tested == 30
    assert 0.0 <= result.win_rate <= 1.0


def test_equity_curve_length_equals_trades_plus_one():
    strategy = EMAStrategy(fast_period=3, slow_period=5)
    b = Backtester(strategy=strategy, slippage_pct=0.0)
    prices = [100 + i * 2.0 for i in range(20)]
    result = b.run(make_candles(prices))
    assert len(result.equity_curve) == result.num_trades + 1


def test_numpy_equity_curve_cumsum():
    """Equity curve should equal initial_capital + cumsum of PnLs."""
    s = mock_strategy(["BUY", "SELL", "BUY", "SELL"])
    b = Backtester(
        strategy=s, slippage_pct=0.0, position_size=1.0, initial_capital=10_000.0
    )
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
        make_candle(5000, 300.0, 310.0),
        make_candle(6000, 350.0, 360.0),
    ]
    result = b.run(candles)
    if result.num_trades > 0:
        pnl_arr = np.array([t.pnl for t in result.trades])
        expected_curve = [10_000.0] + list(10_000.0 + np.cumsum(pnl_arr))
        for actual, expected in zip(result.equity_curve, expected_curve):
            assert abs(actual - expected) < 1e-6
