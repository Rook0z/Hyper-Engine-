import pytest
from unittest.mock import MagicMock
from backtester.backtester import Backtester, BacktestResult, Trade
from strategies.base_strategy import BaseStrategy
from strategies.ema_strategy import EMAStrategy


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────


def make_candle(
    timestamp: int,
    open_: float,
    close: float,
    high: float = None,
    low: float = None,
    volume: float = 1.0,
):
    """Creates a single OHLCV candle."""
    high = high or close * 1.01
    low = low or close * 0.99
    return [timestamp, open_, high, low, close, volume]


def make_candles(
    prices: list[float], start_ts: int = 1_000_000_000_000, interval_ms: int = 3_600_000
):
    """Creates a list of candles from a list of prices. open = previous close."""
    candles = []
    for i, price in enumerate(prices):
        ts = start_ts + i * interval_ms
        open_ = prices[i - 1] if i > 0 else price
        candles.append(make_candle(ts, open_, price))
    return candles


def mock_strategy(signals: list[str]) -> MagicMock:
    """
    Creates a mock strategy that returns signals in order.
    Pads with HOLD if signals run out.
    """
    strategy = MagicMock(spec=BaseStrategy)
    strategy.name = "MockStrategy"
    strategy.min_periods = 1
    signal_iter = iter(signals)
    strategy.generate_signal.side_effect = lambda closes: next(signal_iter, "HOLD")
    return strategy


# ──────────────────────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────────────────────


def test_backtester_default_params():
    s = EMAStrategy()
    b = Backtester(strategy=s)
    assert b.initial_capital == 10_000.0
    assert b.position_size == 0.001
    assert b.slippage_pct == 0.001
    assert b.symbol == "BTC"


def test_backtester_custom_params():
    s = EMAStrategy()
    b = Backtester(strategy=s, initial_capital=5000.0, position_size=0.01, symbol="ETH")
    assert b.initial_capital == 5000.0
    assert b.position_size == 0.01
    assert b.symbol == "ETH"


# ──────────────────────────────────────────────────────────────
# RUN — BASIC
# ──────────────────────────────────────────────────────────────


def test_run_returns_backtest_result():
    s = mock_strategy(["HOLD"] * 10)
    b = Backtester(strategy=s)
    candles = make_candles([100.0] * 10)
    result = b.run(candles)
    assert isinstance(result, BacktestResult)


def test_run_too_few_candles_returns_empty_result():
    s = mock_strategy([])
    b = Backtester(strategy=s)
    result = b.run([make_candle(0, 100.0, 100.0)])
    assert result.num_trades == 0
    assert result.total_pnl == 0.0


def test_run_empty_candles_returns_empty_result():
    s = mock_strategy([])
    b = Backtester(strategy=s)
    result = b.run([])
    assert result.num_trades == 0


def test_run_all_hold_no_trades():
    s = mock_strategy(["HOLD"] * 10)
    b = Backtester(strategy=s)
    candles = make_candles([100.0] * 10)
    result = b.run(candles)
    assert result.num_trades == 0
    assert result.trades == []


def test_run_sets_strategy_name():
    s = mock_strategy(["HOLD"])
    s.name = "TestStrategy"
    b = Backtester(strategy=s)
    result = b.run(make_candles([100.0] * 5))
    assert result.strategy_name == "TestStrategy"


def test_run_sets_symbol():
    s = mock_strategy(["HOLD"])
    b = Backtester(strategy=s, symbol="ETH")
    result = b.run(make_candles([100.0] * 5))
    assert result.symbol == "ETH"


def test_run_records_candles_tested():
    s = mock_strategy(["HOLD"] * 10)
    b = Backtester(strategy=s)
    candles = make_candles([100.0] * 10)
    result = b.run(candles)
    assert result.candles_tested == 10


# ──────────────────────────────────────────────────────────────
# TRADE EXECUTION
# ──────────────────────────────────────────────────────────────


def test_buy_then_sell_creates_one_trade():
    # BUY on candle 0, SELL on candle 2, HOLD otherwise
    s = mock_strategy(["BUY", "HOLD", "SELL", "HOLD"])
    b = Backtester(strategy=s, slippage_pct=0.0)
    candles = make_candles([100.0, 110.0, 120.0, 130.0, 140.0])
    result = b.run(candles)
    assert result.num_trades == 1


def test_profitable_trade_positive_pnl():
    s = mock_strategy(["BUY", "HOLD", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    # open prices: 100, 150, 200, 250 — entry fills at 150, exit at 250
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
    ]
    result = b.run(candles)
    assert result.total_pnl > 0


def test_losing_trade_negative_pnl():
    # Buy at 200, sell at 100 → loss
    s = mock_strategy(["BUY", "HOLD", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = make_candles([200.0, 200.0, 100.0, 100.0])
    result = b.run(candles)
    assert result.total_pnl < 0


def test_trade_fills_at_next_candles_open():
    """Entry and exit fill at the NEXT candle's open, not current close."""
    s = mock_strategy(["BUY", "HOLD", "SELL", "HOLD"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),  #
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
        make_candle(5000, 300.0, 310.0),
    ]
    result = b.run(candles)
    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.entry_price == 150.0
    assert trade.exit_price == 250.0


def test_no_double_entry_without_exit():
    """Second BUY while in position should be ignored."""
    s = mock_strategy(["BUY", "BUY", "BUY", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = make_candles([100.0, 110.0, 120.0, 130.0, 140.0])
    result = b.run(candles)
    assert result.num_trades == 1


def test_no_exit_without_entry():
    """SELL without being in a position should be ignored."""
    s = mock_strategy(["SELL", "SELL", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0)
    candles = make_candles([100.0, 90.0, 80.0, 70.0])
    result = b.run(candles)
    assert result.num_trades == 0


def test_open_position_force_closed_at_end():
    """If still in position at last candle, it gets force-closed."""
    s = mock_strategy(["BUY"] + ["HOLD"] * 10)
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = make_candles([100.0, 110.0, 120.0, 130.0])
    result = b.run(candles)
    assert result.num_trades == 1  # force closed


# ──────────────────────────────────────────────────────────────
# SLIPPAGE
# ──────────────────────────────────────────────────────────────


def test_slippage_buy_fills_above_price():
    """Buy slippage makes entry price higher than quoted."""
    b = Backtester(strategy=mock_strategy([]), slippage_pct=0.01)
    price = b._apply_slippage(100.0, is_buy=True)
    assert price == 101.0


def test_slippage_sell_fills_below_price():
    """Sell slippage makes exit price lower than quoted."""
    b = Backtester(strategy=mock_strategy([]), slippage_pct=0.01)
    price = b._apply_slippage(100.0, is_buy=False)
    assert price == 99.0


def test_zero_slippage_fills_at_exact_price():
    b = Backtester(strategy=mock_strategy([]), slippage_pct=0.0)
    assert b._apply_slippage(100.0, is_buy=True) == 100.0
    assert b._apply_slippage(100.0, is_buy=False) == 100.0


def test_slippage_reduces_pnl():
    """Slippage should reduce PnL compared to zero slippage."""
    prices = [100.0, 100.0, 200.0, 200.0]

    s1 = mock_strategy(["BUY", "HOLD", "SELL"])
    b1 = Backtester(strategy=s1, slippage_pct=0.0, position_size=1.0)

    s2 = mock_strategy(["BUY", "HOLD", "SELL"])
    b2 = Backtester(strategy=s2, slippage_pct=0.01, position_size=1.0)

    r1 = b1.run(make_candles(prices))
    r2 = b2.run(make_candles(prices))

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


def test_win_rate_all_losers():
    s = mock_strategy(["BUY", "SELL", "BUY", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = [
        make_candle(1000, 300.0, 290.0),
        make_candle(2000, 250.0, 240.0),
        make_candle(3000, 150.0, 140.0),
        make_candle(4000, 100.0, 90.0),
        make_candle(5000, 50.0, 40.0),
        make_candle(6000, 20.0, 10.0),
    ]
    result = b.run(candles)
    assert result.win_rate == 0.0


def test_profit_factor_profitable():
    s = mock_strategy(["BUY", "SELL"])
    b = Backtester(strategy=s, slippage_pct=0.0, position_size=1.0)
    candles = [
        make_candle(1000, 100.0, 110.0),
        make_candle(2000, 150.0, 160.0),
        make_candle(3000, 200.0, 210.0),
        make_candle(4000, 250.0, 260.0),
    ]
    result = b.run(candles)
    assert result.profit_factor == float("inf")


def test_max_drawdown_no_drawdown():
    s = mock_strategy(["HOLD"] * 10)
    b = Backtester(strategy=s)
    candles = make_candles([100.0] * 10)
    result = b.run(candles)
    assert result.max_drawdown == 0.0


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
    candles = make_candles([100.0, 100.0, 200.0, 200.0])
    result = b.run(candles)
    assert result.equity_curve[-1] > 10_000.0


# ──────────────────────────────────────────────────────────────
# TRADE DATACLASS
# ──────────────────────────────────────────────────────────────


def test_trade_pnl_calculation():
    """entry=100, exit=150, size=1 → PnL = 50"""
    b = Backtester(strategy=mock_strategy([]), slippage_pct=0.0, position_size=1.0)
    trade = b._record_trade(1000, 2000, 100.0, 150.0)
    assert trade.pnl == pytest.approx(50.0)


def test_trade_pnl_pct_calculation():
    """entry=100, exit=150 → pnl_pct = 50%"""
    b = Backtester(strategy=mock_strategy([]), slippage_pct=0.0, position_size=1.0)
    trade = b._record_trade(1000, 2000, 100.0, 150.0)
    assert trade.pnl_pct == pytest.approx(0.5)


def test_trade_loss():
    """entry=150, exit=100 → PnL = -50"""
    b = Backtester(strategy=mock_strategy([]), slippage_pct=0.0, position_size=1.0)
    trade = b._record_trade(1000, 2000, 150.0, 100.0)
    assert trade.pnl == pytest.approx(-50.0)


# ──────────────────────────────────────────────────────────────
# BACKTEST RESULT STR
# ──────────────────────────────────────────────────────────────


def test_backtest_result_str():
    result = BacktestResult(
        strategy_name="EMA Crossover 9/21",
        symbol="BTC",
        candles_tested=720,
        num_trades=5,
        total_pnl=150.0,
        win_rate=0.6,
        profit_factor=1.8,
        max_drawdown=0.05,
    )
    output = str(result)
    assert "EMA Crossover 9/21" in output
    assert "BTC" in output
    assert "5" in output


# ──────────────────────────────────────────────────────────────
# INTEGRATION — EMA STRATEGY ON SYNTHETIC DATA
# ──────────────────────────────────────────────────────────────


def test_ema_strategy_backtest_runs_without_error():
    """End-to-end: real EMA strategy on synthetic candles."""
    strategy = EMAStrategy(fast_period=3, slow_period=5)
    b = Backtester(strategy=strategy, slippage_pct=0.001, position_size=0.001)

    # 30 synthetic candles: trending up then down
    prices = (
        [100 + i * 2.0 for i in range(15)]  # uptrend
        + [130 - i * 2.0 for i in range(15)]  # downtrend
    )
    candles = make_candles(prices)
    result = b.run(candles)

    assert isinstance(result, BacktestResult)
    assert result.candles_tested == 30
    assert 0.0 <= result.win_rate <= 1.0
    assert result.max_drawdown >= 0.0


def test_ema_strategy_backtest_equity_curve_length():
    """Equity curve length = initial point + number of trades."""
    strategy = EMAStrategy(fast_period=3, slow_period=5)
    b = Backtester(strategy=strategy, slippage_pct=0.0)
    prices = [100 + i * 2.0 for i in range(20)]
    candles = make_candles(prices)
    result = b.run(candles)
    assert len(result.equity_curve) == result.num_trades + 1
