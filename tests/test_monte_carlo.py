"""
Tests for backtester/monte_carlo.py.

Two groups:
  - Mechanics: run_monte_carlo_simulation() against a real
    BacktestResult with real trades, checking the actual randomization
    behavior (shuffle preserves total PnL, bootstrap can vary it,
    reproducibility via seed, validation).
  - Aggregation math: MonteCarloReport built directly from known
    MonteCarloSimulationResult values, so percentile/probability math
    can be verified exactly (mirrors the pattern used for
    WalkForwardReport aggregation tests).
"""

import pytest

from backtester.backtester import BacktestResult, Trade
from backtester.monte_carlo import (
    MonteCarloReport,
    MonteCarloSimulationResult,
    run_monte_carlo_simulation,
)


def make_trade(pnl: float, entry_time=0, exit_time=1000) -> Trade:
    return Trade(
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        size=1.0,
        pnl=pnl,
        pnl_pct=pnl / 100.0,
    )


def make_result(pnls: list[float], initial_capital: float = 10_000.0) -> BacktestResult:
    trades = [make_trade(p, entry_time=i, exit_time=i + 1) for i, p in enumerate(pnls)]
    equity = initial_capital
    curve = [equity]
    for p in pnls:
        equity += p
        curve.append(equity)
    return BacktestResult(
        trades=trades,
        total_pnl=sum(pnls),
        num_trades=len(trades),
        equity_curve=curve,
        strategy_name="Test",
        symbol="BTC",
        candles_tested=100,
        max_drawdown=0.05,
    )


# ──────────────────────────────────────────────────────────────
# MECHANICS
# ──────────────────────────────────────────────────────────────


def test_returns_requested_number_of_simulations():
    result = make_result([10.0, -5.0, 20.0, -8.0, 15.0])
    report = run_monte_carlo_simulation(result, num_simulations=250, seed=1)
    assert report.num_simulations == 250
    assert len(report.simulations) == 250


def test_shuffle_preserves_total_pnl_across_every_simulation():
    """The core invariant of shuffle mode: same trades, only reordered
    — total PnL must be IDENTICAL to the original across every single
    simulation."""
    pnls = [10.0, -5.0, 20.0, -8.0, 15.0, -3.0]
    result = make_result(pnls)
    report = run_monte_carlo_simulation(
        result, num_simulations=200, method="shuffle", seed=42
    )
    expected_total = sum(pnls)
    for sim in report.simulations:
        assert sim.total_pnl == pytest.approx(expected_total)
        assert sim.final_equity == pytest.approx(10_000.0 + expected_total)


def test_shuffle_actually_reorders_trades():
    """Regression guard against an accidental no-op shuffle: across
    many simulations, at least one equity curve must differ from the
    original trade order."""
    pnls = [10.0, -5.0, 20.0, -8.0, 15.0, -3.0, 7.0, -2.0]
    result = make_result(pnls)
    report = run_monte_carlo_simulation(
        result, num_simulations=100, method="shuffle", seed=7
    )
    original_curve = result.equity_curve
    assert any(sim.equity_curve != original_curve for sim in report.simulations)


def test_bootstrap_can_vary_total_pnl():
    """Bootstrap resamples with replacement, so total PnL should vary
    across simulations (unlike shuffle, which never does)."""
    pnls = [10.0, -5.0, 20.0, -8.0, 15.0, -3.0, 7.0, -2.0]
    result = make_result(pnls)
    report = run_monte_carlo_simulation(
        result, num_simulations=200, method="bootstrap", seed=42
    )
    totals = {round(sim.total_pnl, 6) for sim in report.simulations}
    assert len(totals) > 1


def test_bootstrap_equity_curve_length_matches_original_trade_count():
    pnls = [10.0, -5.0, 20.0]
    result = make_result(pnls)
    report = run_monte_carlo_simulation(
        result, num_simulations=10, method="bootstrap", seed=1
    )
    for sim in report.simulations:
        assert len(sim.equity_curve) == len(pnls) + 1  # + starting point


def test_same_seed_is_reproducible():
    result = make_result([10.0, -5.0, 20.0, -8.0, 15.0])
    report_a = run_monte_carlo_simulation(result, num_simulations=50, seed=99)
    report_b = run_monte_carlo_simulation(result, num_simulations=50, seed=99)
    assert report_a.final_equity_values == report_b.final_equity_values


def test_different_seeds_produce_different_results():
    """
    In shuffle mode, final_equity is mathematically IDENTICAL across
    every simulation regardless of seed (same numbers summed,
    regardless of order) — that's correct, by-design behavior, not
    something that should vary. What actually varies with the shuffle
    order is the PATH: max_drawdown depends on when losses cluster,
    which does change with the order. That's the right metric to
    check here.
    """
    result = make_result([10.0, -5.0, 20.0, -8.0, 15.0, -3.0, 7.0, -2.0])
    report_a = run_monte_carlo_simulation(result, num_simulations=50, seed=1)
    report_b = run_monte_carlo_simulation(result, num_simulations=50, seed=2)
    assert report_a.max_drawdown_values != report_b.max_drawdown_values


def test_no_seed_still_runs():
    result = make_result([10.0, -5.0, 20.0])
    report = run_monte_carlo_simulation(result, num_simulations=10)
    assert report.num_simulations == 10


def test_every_equity_curve_starts_at_initial_capital():
    result = make_result([10.0, -5.0, 20.0], initial_capital=5_000.0)
    report = run_monte_carlo_simulation(result, num_simulations=20, seed=1)
    for sim in report.simulations:
        assert sim.equity_curve[0] == 5_000.0


# ──────────────────────────────────────────────────────────────
# VALIDATION
# ──────────────────────────────────────────────────────────────


def test_no_trades_raises():
    empty_result = BacktestResult(strategy_name="Test", symbol="BTC")
    with pytest.raises(ValueError, match="no trades"):
        run_monte_carlo_simulation(empty_result, num_simulations=10)


def test_zero_simulations_raises():
    result = make_result([10.0])
    with pytest.raises(ValueError, match="num_simulations"):
        run_monte_carlo_simulation(result, num_simulations=0)


def test_negative_simulations_raises():
    result = make_result([10.0])
    with pytest.raises(ValueError, match="num_simulations"):
        run_monte_carlo_simulation(result, num_simulations=-5)


def test_invalid_method_raises():
    result = make_result([10.0])
    with pytest.raises(ValueError, match="method"):
        run_monte_carlo_simulation(result, num_simulations=10, method="bogus")


# ──────────────────────────────────────────────────────────────
# AGGREGATION MATH (direct construction, known values)
# ──────────────────────────────────────────────────────────────


def _make_report(
    final_equities: list[float], drawdowns: list[float]
) -> MonteCarloReport:
    sims = [
        MonteCarloSimulationResult(
            equity_curve=[10_000.0, fe],
            final_equity=fe,
            total_pnl=fe - 10_000.0,
            max_drawdown=dd,
        )
        for fe, dd in zip(final_equities, drawdowns)
    ]
    return MonteCarloReport(
        num_simulations=len(sims),
        method="shuffle",
        initial_capital=10_000.0,
        original_final_equity=10_500.0,
        original_max_drawdown=0.05,
        simulations=sims,
    )


def test_median_final_equity_odd_count():
    report = _make_report([9000.0, 10_000.0, 11_000.0], [0.1, 0.05, 0.02])
    assert report.median_final_equity == 10_000.0


def test_median_final_equity_even_count():
    report = _make_report(
        [9000.0, 10_000.0, 11_000.0, 12_000.0], [0.1, 0.05, 0.02, 0.01]
    )
    assert report.median_final_equity == pytest.approx(10_500.0)


def test_mean_final_equity():
    report = _make_report([9000.0, 11_000.0], [0.1, 0.05])
    assert report.mean_final_equity == pytest.approx(10_000.0)


def test_worst_and_best_final_equity():
    report = _make_report([9000.0, 10_000.0, 11_000.0], [0.1, 0.05, 0.02])
    assert report.worst_final_equity == 9000.0
    assert report.best_final_equity == 11_000.0


def test_percentile_0_and_1_match_min_and_max():
    report = _make_report(
        [9000.0, 10_000.0, 11_000.0, 12_000.0], [0.1, 0.05, 0.02, 0.01]
    )
    assert report.final_equity_percentile(0.0) == 9000.0
    assert report.final_equity_percentile(1.0) == 12_000.0


def test_probability_of_loss():
    # 2 of 4 simulations end below initial_capital (10,000).
    report = _make_report([8000.0, 9000.0, 11_000.0, 12_000.0], [0.1, 0.1, 0.02, 0.01])
    assert report.probability_of_loss == pytest.approx(0.5)


def test_probability_of_loss_all_profitable():
    report = _make_report([10_500.0, 11_000.0], [0.05, 0.02])
    assert report.probability_of_loss == 0.0


def test_worst_max_drawdown():
    report = _make_report([9000.0, 10_000.0, 11_000.0], [0.1, 0.25, 0.02])
    assert report.worst_max_drawdown == 0.25


def test_median_max_drawdown():
    report = _make_report([9000.0, 10_000.0, 11_000.0], [0.1, 0.2, 0.3])
    assert report.median_max_drawdown == 0.2


def test_empty_simulations_do_not_crash():
    report = MonteCarloReport(
        num_simulations=0,
        method="shuffle",
        initial_capital=10_000.0,
        original_final_equity=10_000.0,
        original_max_drawdown=0.0,
        simulations=[],
    )
    assert report.median_final_equity == 0.0
    assert report.mean_final_equity == 0.0
    assert report.worst_final_equity == 0.0
    assert report.best_final_equity == 0.0
    assert report.probability_of_loss == 0.0


def test_report_str_contains_key_sections():
    report = _make_report([9000.0, 10_000.0, 11_000.0], [0.1, 0.05, 0.02])
    output = str(report)
    assert "MONTE CARLO SIMULATION" in output
    assert "Probability of loss" in output
    assert "Simulated final equity" in output
    assert "Simulated max drawdown" in output
