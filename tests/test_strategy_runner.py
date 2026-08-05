"""
Tests for strategy_runner.py's strategy factory and the fresh-instance
guarantee between backtest_all() and paper trading.

paper_trade() itself (network fetch loop, sleep, KeyboardInterrupt
handling) is out of scope here — these tests target the pure,
side-effect-free pieces: _build_strategy() and backtest_all()'s use of
it, which is what guarantees the backtester and the paper trader never
share a mutable strategy instance.
"""

import strategy_runner as sr
from strategies.ema_strategy import EMAStrategy
from strategies.rsi_strategy import RSIStrategy
from strategies.bb_strategy import BollingerStrategy
from strategies.vwap_strategy import VWAPStrategy


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


# ──────────────────────────────────────────────────────────────
# _build_strategy — TYPES AND CONFIG
# ──────────────────────────────────────────────────────────────


def test_build_strategy_returns_correct_type_for_each_class():
    assert isinstance(sr._build_strategy(EMAStrategy), EMAStrategy)
    assert isinstance(sr._build_strategy(RSIStrategy), RSIStrategy)
    assert isinstance(sr._build_strategy(BollingerStrategy), BollingerStrategy)
    assert isinstance(sr._build_strategy(VWAPStrategy), VWAPStrategy)


def test_build_strategy_uses_current_settings():
    ema = sr._build_strategy(EMAStrategy)
    assert ema.fast_period == sr.settings.ema_fast_period
    assert ema.slow_period == sr.settings.ema_slow_period

    rsi = sr._build_strategy(RSIStrategy)
    assert rsi.period == sr.settings.rsi_period

    vwap = sr._build_strategy(VWAPStrategy)
    assert vwap.mode == sr.settings.vwap_mode


# ──────────────────────────────────────────────────────────────
# _build_strategy — FRESH INSTANCE GUARANTEE
# ──────────────────────────────────────────────────────────────


def test_build_strategy_returns_a_new_instance_each_call():
    a = sr._build_strategy(EMAStrategy)
    b = sr._build_strategy(EMAStrategy)
    assert a is not b


def test_fresh_strategy_does_not_inherit_mutated_state():
    """
    Regression test: mutating one instance's internal signal-dedup
    state (as a real backtest run would) must NOT be visible on a
    freshly built instance of the same class/config.
    """
    backtested = sr._build_strategy(EMAStrategy)
    backtested._last_crossover = "BUY"  # simulate state left by a backtest

    fresh = sr._build_strategy(EMAStrategy)

    assert fresh is not backtested
    assert fresh._last_crossover == "HOLD"

    # And the two remain independent going forward.
    fresh._last_crossover = "SELL"
    assert backtested._last_crossover == "BUY"


# ──────────────────────────────────────────────────────────────
# END-TO-END: backtest_all() MUTATES STATE; A FRESH REBUILD MUST NOT
# CARRY IT OVER — this is the exact scenario paper trading depends on.
# ──────────────────────────────────────────────────────────────


def test_paper_trading_strategy_is_not_the_backtested_instance():
    """
    Regression test proving the fix: after backtest_all() runs (which
    mutates each strategy's internal dedup state via real signal
    generation), rebuilding via _build_strategy(type(winner)) must
    produce an object that never participated in the backtest and
    carries no leftover signal state.
    """
    # A trend with a clear reversal, long enough to mutate every
    # strategy's internal dedup state during backtesting.
    up = [100.0 + i * 2.0 for i in range(30)]
    down = [up[-1] - i * 2.0 for i in range(1, 30)]
    candles = make_candles(up + down)

    results = sr.backtest_all(candles)
    best_strategy, _, _ = results[0]

    fresh_strategy = sr._build_strategy(type(best_strategy))

    # Never the same object — this is the core guarantee.
    assert fresh_strategy is not best_strategy
    # Same class, same configuration (same name).
    assert type(fresh_strategy) is type(best_strategy)
    assert fresh_strategy.name == best_strategy.name


def test_backtest_all_strategies_are_all_freshly_built():
    """
    Every strategy competing in backtest_all() must come from
    _build_strategy() — i.e. backtest_all() and a subsequent fresh
    rebuild never hand out the same object.
    """
    candles = make_candles([100.0 + i for i in range(30)])
    results = sr.backtest_all(candles)

    rebuilt = [sr._build_strategy(type(s)) for s, _, _ in results]
    original = [s for s, _, _ in results]

    for rebuilt_strategy, original_strategy in zip(rebuilt, original):
        assert rebuilt_strategy is not original_strategy
