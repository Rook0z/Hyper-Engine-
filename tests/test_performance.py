import math
import pytest
from backtester.performance import PerformanceAnalyser, PerformanceReport
from backtester.backtester import BacktestResult, Trade


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────


def make_trade(pnl: float, pnl_pct: float = None) -> Trade:
    pnl_pct = pnl_pct if pnl_pct is not None else pnl / 100.0
    return Trade(
        entry_time=1000,
        exit_time=2000,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        size=1.0,
        pnl=pnl,
        pnl_pct=pnl_pct,
    )


def make_result(
    pnl_list: list[float], equity_start: float = 10_000.0
) -> BacktestResult:
    trades = [make_trade(p) for p in pnl_list]
    equity = equity_start
    curve = [equity]
    for p in pnl_list:
        equity += p
        curve.append(equity)
    return BacktestResult(
        trades=trades,
        total_pnl=sum(pnl_list),
        win_rate=sum(1 for p in pnl_list if p > 0) / len(pnl_list),
        profit_factor=0.0,
        max_drawdown=0.0,
        num_trades=len(trades),
        equity_curve=curve,
        strategy_name="TestStrategy",
        symbol="BTC",
        candles_tested=100,
    )


@pytest.fixture
def analyser():
    return PerformanceAnalyser()


# ──────────────────────────────────────────────────────────────
# TOTAL PNL
# ──────────────────────────────────────────────────────────────


def test_total_pnl_positive(analyser):
    assert analyser.total_pnl([10.0, 20.0, 30.0]) == 60.0


def test_total_pnl_mixed(analyser):
    assert analyser.total_pnl([100.0, -50.0, 25.0]) == 75.0


def test_total_pnl_all_losses(analyser):
    assert analyser.total_pnl([-10.0, -20.0]) == -30.0


def test_total_pnl_empty_raises(analyser):
    with pytest.raises(ValueError, match="empty"):
        analyser.total_pnl([])


# ──────────────────────────────────────────────────────────────
# WIN RATE
# ──────────────────────────────────────────────────────────────


def test_win_rate_all_wins(analyser):
    assert analyser.win_rate([10.0, 20.0, 30.0]) == 1.0


def test_win_rate_all_losses(analyser):
    assert analyser.win_rate([-10.0, -20.0]) == 0.0


def test_win_rate_mixed(analyser):
    # 3 wins, 2 losses = 0.6
    result = analyser.win_rate([10.0, -5.0, 20.0, -3.0, 15.0])
    assert math.isclose(result, 0.6, rel_tol=1e-9)


def test_win_rate_zero_pnl_not_counted_as_win(analyser):
    # 1 win, 1 zero, 1 loss → win_rate = 1/3
    result = analyser.win_rate([10.0, 0.0, -5.0])
    assert math.isclose(result, 1 / 3, rel_tol=1e-9)


def test_win_rate_empty_raises(analyser):
    with pytest.raises(ValueError):
        analyser.win_rate([])


# ──────────────────────────────────────────────────────────────
# MAX DRAWDOWN
# ──────────────────────────────────────────────────────────────


def test_max_drawdown_simple(analyser):
    # Peak 110, trough 70 → (110-70)/110 ≈ 0.3636
    equity = [100.0, 110.0, 70.0, 90.0]
    result = analyser.max_drawdown(equity)
    assert math.isclose(result, (110 - 70) / 110, rel_tol=1e-9)


def test_max_drawdown_no_drawdown(analyser):
    equity = [100.0, 110.0, 120.0, 130.0]
    assert analyser.max_drawdown(equity) == 0.0


def test_max_drawdown_full_loss(analyser):
    equity = [100.0, 50.0, 0.001]
    result = analyser.max_drawdown(equity)
    assert result > 0.99


def test_max_drawdown_too_few_raises(analyser):
    with pytest.raises(ValueError):
        analyser.max_drawdown([100.0])


# ──────────────────────────────────────────────────────────────
# PROFIT FACTOR
# ──────────────────────────────────────────────────────────────


def test_profit_factor_balanced(analyser):
    assert math.isclose(analyser.profit_factor([100.0, -100.0]), 1.0)


def test_profit_factor_2x(analyser):
    assert math.isclose(analyser.profit_factor([200.0, -100.0]), 2.0)


def test_profit_factor_no_losses_inf(analyser):
    assert analyser.profit_factor([100.0, 50.0]) == float("inf")


def test_profit_factor_no_wins_zero(analyser):
    assert analyser.profit_factor([-100.0, -50.0]) == 0.0


def test_profit_factor_empty_raises(analyser):
    with pytest.raises(ValueError):
        analyser.profit_factor([])


# ──────────────────────────────────────────────────────────────
# GROSS PROFIT / LOSS
# ──────────────────────────────────────────────────────────────


def test_gross_profit_loss(analyser):
    gp, gl = analyser.gross_profit_loss([100.0, -50.0, 200.0, -30.0])
    assert math.isclose(gp, 300.0)
    assert math.isclose(gl, 80.0)


def test_gross_profit_loss_all_wins(analyser):
    gp, gl = analyser.gross_profit_loss([100.0, 200.0])
    assert gp == 300.0
    assert gl == 0.0


# ──────────────────────────────────────────────────────────────
# AVG WIN / LOSS
# ──────────────────────────────────────────────────────────────


def test_avg_win_loss(analyser):
    # wins: [100, 200] → avg 150; losses: [-50, -30] → avg -40
    aw, al = analyser.avg_win_loss([100.0, -50.0, 200.0, -30.0])
    assert math.isclose(aw, 150.0)
    assert math.isclose(al, -40.0)


def test_avg_win_no_losses(analyser):
    aw, al = analyser.avg_win_loss([100.0, 200.0])
    assert aw == 150.0
    assert al == 0.0


def test_avg_loss_no_wins(analyser):
    aw, al = analyser.avg_win_loss([-100.0, -200.0])
    assert aw == 0.0
    assert al == -150.0


# ──────────────────────────────────────────────────────────────
# EXPECTANCY
# ──────────────────────────────────────────────────────────────


def test_expectancy_positive(analyser):
    # mean([100, -50, 200, -30]) = 220/4 = 55
    result = analyser.expectancy([100.0, -50.0, 200.0, -30.0])
    assert math.isclose(result, 55.0)


def test_expectancy_negative(analyser):
    result = analyser.expectancy([-100.0, -50.0])
    assert result < 0


def test_expectancy_zero(analyser):
    result = analyser.expectancy([100.0, -100.0])
    assert result == 0.0


# ──────────────────────────────────────────────────────────────
# SHARPE RATIO
# ──────────────────────────────────────────────────────────────


def test_sharpe_positive_for_consistent_gains(analyser):
    returns = [0.02, 0.01, 0.015, 0.018, 0.012, 0.022]
    result = analyser.sharpe_ratio(returns)
    assert result > 0


def test_sharpe_negative_for_consistent_losses(analyser):
    returns = [-0.02, -0.01, -0.015, -0.018]
    result = analyser.sharpe_ratio(returns)
    assert result < 0


def test_sharpe_zero_for_too_few_returns(analyser):
    assert analyser.sharpe_ratio([0.01]) == 0.0


def test_sharpe_zero_for_identical_returns(analyser):
    assert analyser.sharpe_ratio([0.01, 0.01, 0.01]) == 0.0


# ──────────────────────────────────────────────────────────────
# SORTINO RATIO
# ──────────────────────────────────────────────────────────────


def test_sortino_inf_when_no_losses(analyser):
    returns = [0.01, 0.02, 0.015]
    result = analyser.sortino_ratio(returns)
    assert result == float("inf")


def test_sortino_zero_for_too_few_returns(analyser):
    assert analyser.sortino_ratio([0.01]) == 0.0


def test_sortino_positive_for_gains(analyser):
    returns = [0.02, -0.01, 0.015, -0.005, 0.03]
    result = analyser.sortino_ratio(returns)
    assert result > 0


# ──────────────────────────────────────────────────────────────
# CALMAR RATIO
# ──────────────────────────────────────────────────────────────


def test_calmar_zero_when_no_drawdown(analyser):
    returns = [0.01, 0.02]
    assert analyser.calmar_ratio(returns, max_drawdown=0.0) == 0.0


def test_calmar_zero_when_no_returns(analyser):
    assert analyser.calmar_ratio([], max_drawdown=0.1) == 0.0


def test_calmar_positive_for_profitable_strategy(analyser):
    returns = [0.02, 0.01, 0.015, 0.018]
    result = analyser.calmar_ratio(returns, max_drawdown=0.05)
    assert result > 0


# ──────────────────────────────────────────────────────────────
# ANALYSE — FULL INTEGRATION
# ──────────────────────────────────────────────────────────────


def test_analyse_returns_report(analyser):
    result = make_result([100.0, -50.0, 200.0, -30.0])
    report = analyser.analyse(result)
    assert isinstance(report, PerformanceReport)


def test_analyse_no_trades_returns_zeroed(analyser):
    result = BacktestResult(strategy_name="Test", symbol="BTC", candles_tested=100)
    report = analyser.analyse(result)
    assert report.num_trades == 0
    assert report.total_pnl == 0.0


def test_analyse_total_pnl(analyser):
    result = make_result([100.0, -50.0, 200.0])
    report = analyser.analyse(result)
    assert math.isclose(report.total_pnl, 250.0)


def test_analyse_win_rate(analyser):
    result = make_result([100.0, -50.0, 200.0, -30.0])
    report = analyser.analyse(result)
    assert math.isclose(report.win_rate, 0.5)


def test_analyse_strategy_name(analyser):
    result = make_result([100.0])
    result.strategy_name = "EMA Crossover 9/21"
    report = analyser.analyse(result)
    assert report.strategy_name == "EMA Crossover 9/21"


def test_report_str_contains_key_info(analyser):
    result = make_result([100.0, -50.0])
    report = analyser.analyse(result)
    output = str(report)
    assert "PERFORMANCE REPORT" in output
    assert "Win rate" in output
    assert "Sharpe" in output
