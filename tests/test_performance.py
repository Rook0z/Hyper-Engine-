import math
import pytest
from backtester.performance import PerformanceAnalyser, PerformanceReport
from backtester.backtester import BacktestResult, Trade


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────


def make_trade(pnl: float, pnl_pct: float | None = None) -> Trade:
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


def test_sortino_returns_inf_no_losses(analyser):
    returns = [0.01, 0.02, 0.03]
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


def test_calmar_zero_when_empty_returns(analyser):
    assert analyser.calmar_ratio([], max_drawdown=0.1) == 0.0


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


# ──────────────────────────────────────────────────────────────
# NEW METRICS: HELPERS
# ──────────────────────────────────────────────────────────────


def make_trade_timed(
    entry_time: int, exit_time: int, pnl: float, pnl_pct: float | None = None
) -> Trade:
    pnl_pct = pnl_pct if pnl_pct is not None else pnl / 100.0
    return Trade(
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        size=1.0,
        pnl=pnl,
        pnl_pct=pnl_pct,
    )


def make_result_with_metadata(
    trades: list[Trade],
    equity_start: float = 10_000.0,
    slippage_pct: float = 0.0,
    backtest_start_time: int = 0,
    backtest_end_time: int = 0,
) -> BacktestResult:
    equity = equity_start
    curve = [equity]
    for t in trades:
        equity += t.pnl
        curve.append(equity)
    return BacktestResult(
        trades=trades,
        total_pnl=sum(t.pnl for t in trades),
        win_rate=sum(1 for t in trades if t.pnl > 0) / len(trades) if trades else 0.0,
        profit_factor=0.0,
        max_drawdown=0.0,
        num_trades=len(trades),
        equity_curve=curve,
        strategy_name="TestStrategy",
        symbol="BTC",
        candles_tested=100,
        slippage_pct=slippage_pct,
        backtest_start_time=backtest_start_time,
        backtest_end_time=backtest_end_time,
        backtest_initial_capital=equity_start,
    )


# ──────────────────────────────────────────────────────────────
# TOTAL RETURN %
# ──────────────────────────────────────────────────────────────


def test_total_return_pct_positive(analyser):
    result = analyser.total_return_pct([10_000.0, 11_000.0, 12_000.0])
    assert math.isclose(result, 20.0)


def test_total_return_pct_negative(analyser):
    result = analyser.total_return_pct([10_000.0, 9_000.0])
    assert math.isclose(result, -10.0)


def test_total_return_pct_empty_curve_is_zero(analyser):
    assert analyser.total_return_pct([]) == 0.0


def test_total_return_pct_zero_start_is_zero(analyser):
    assert analyser.total_return_pct([0.0, 100.0]) == 0.0


# ──────────────────────────────────────────────────────────────
# WINNING / LOSING TRADE COUNTS
# ──────────────────────────────────────────────────────────────


def test_count_wins_losses_mixed(analyser):
    wins, losses = analyser.count_wins_losses([10.0, -5.0, 20.0, -3.0, 0.0])
    assert wins == 2
    assert losses == 2  # breakeven (0.0) counts as neither


def test_count_wins_losses_empty_raises(analyser):
    with pytest.raises(ValueError):
        analyser.count_wins_losses([])


# ──────────────────────────────────────────────────────────────
# LARGEST WIN / LOSS
# ──────────────────────────────────────────────────────────────


def test_largest_win(analyser):
    assert analyser.largest_win([10.0, 50.0, -5.0, 20.0]) == 50.0


def test_largest_win_no_wins_is_zero(analyser):
    assert analyser.largest_win([-10.0, -20.0]) == 0.0


def test_largest_loss(analyser):
    assert analyser.largest_loss([10.0, -50.0, -5.0, 20.0]) == -50.0


def test_largest_loss_no_losses_is_zero(analyser):
    assert analyser.largest_loss([10.0, 20.0]) == 0.0


def test_largest_win_loss_empty_raises(analyser):
    with pytest.raises(ValueError):
        analyser.largest_win([])
    with pytest.raises(ValueError):
        analyser.largest_loss([])


# ──────────────────────────────────────────────────────────────
# AVERAGE TRADE RETURN %
# ──────────────────────────────────────────────────────────────


def test_avg_trade_return_pct(analyser):
    result = analyser.avg_trade_return_pct([0.02, -0.01, 0.03])
    assert math.isclose(result, (0.02 - 0.01 + 0.03) / 3 * 100)


def test_avg_trade_return_pct_empty_raises(analyser):
    with pytest.raises(ValueError):
        analyser.avg_trade_return_pct([])


# ──────────────────────────────────────────────────────────────
# AVERAGE HOLDING TIME
# ──────────────────────────────────────────────────────────────


def test_avg_holding_time_hours(analyser):
    trades = [make_trade_timed(0, 2 * 3_600_000, 10.0)]
    assert math.isclose(analyser.avg_holding_time(trades), 2.0)


def test_avg_holding_time_multiple_trades(analyser):
    trades = [
        make_trade_timed(0, 3_600_000, 10.0),
        make_trade_timed(3_600_000, 3 * 3_600_000, -5.0),
    ]
    assert math.isclose(analyser.avg_holding_time(trades), 1.5)


def test_avg_holding_time_empty_raises(analyser):
    with pytest.raises(ValueError):
        analyser.avg_holding_time([])


# ──────────────────────────────────────────────────────────────
# RECOVERY FACTOR
# ──────────────────────────────────────────────────────────────


def test_recovery_factor_normal(analyser):
    assert math.isclose(analyser.recovery_factor(500.0, 100.0), 5.0)


def test_recovery_factor_no_drawdown_positive_profit_is_inf(analyser):
    assert analyser.recovery_factor(500.0, 0.0) == float("inf")


def test_recovery_factor_no_drawdown_no_profit_is_zero(analyser):
    assert analyser.recovery_factor(0.0, 0.0) == 0.0
    assert analyser.recovery_factor(-50.0, 0.0) == 0.0


# ──────────────────────────────────────────────────────────────
# EXPOSURE TIME %
# ──────────────────────────────────────────────────────────────


def test_exposure_time_half(analyser):
    trades = [make_trade_timed(0, 3_600_000, 10.0)]
    result = analyser.exposure_time(
        trades, backtest_start_time=0, backtest_end_time=2 * 3_600_000
    )
    assert math.isclose(result, 50.0)


def test_exposure_time_full(analyser):
    trades = [make_trade_timed(0, 3_600_000, 10.0)]
    result = analyser.exposure_time(
        trades, backtest_start_time=0, backtest_end_time=3_600_000
    )
    assert math.isclose(result, 100.0)


def test_exposure_time_no_trades_is_zero(analyser):
    result = analyser.exposure_time(
        [], backtest_start_time=0, backtest_end_time=3_600_000
    )
    assert result == 0.0


def test_exposure_time_zero_span_is_zero(analyser):
    trades = [make_trade_timed(0, 3_600_000, 10.0)]
    result = analyser.exposure_time(trades, backtest_start_time=0, backtest_end_time=0)
    assert result == 0.0


def test_exposure_time_negative_span_is_zero(analyser):
    trades = [make_trade_timed(0, 3_600_000, 10.0)]
    result = analyser.exposure_time(
        trades, backtest_start_time=100, backtest_end_time=0
    )
    assert result == 0.0


# ──────────────────────────────────────────────────────────────
# MAX DRAWDOWN DURATION (peak-to-recovery)
# ──────────────────────────────────────────────────────────────


def test_max_drawdown_duration_recovers(analyser):
    # equity: 100 (t0) -> 150 (t1, peak) -> 100 (t2, trough) -> 160 (t3, recovers)
    equity = [100.0, 150.0, 100.0, 160.0]
    timestamps = [0, 3_600_000, 2 * 3_600_000, 5 * 3_600_000]
    hours, recovered = analyser.max_drawdown_duration(
        equity, timestamps, backtest_end_time=5 * 3_600_000
    )
    assert math.isclose(hours, 4.0)  # peak at 1h, recovers at 5h
    assert recovered is True


def test_max_drawdown_duration_never_recovers(analyser):
    # equity: 100 (t0) -> 150 (t1, peak) -> 100 (t2, trough), backtest ends there
    equity = [100.0, 150.0, 100.0]
    timestamps = [0, 3_600_000, 4 * 3_600_000]
    hours, recovered = analyser.max_drawdown_duration(
        equity, timestamps, backtest_end_time=4 * 3_600_000
    )
    assert math.isclose(hours, 3.0)  # peak at 1h, backtest ends at 4h
    assert recovered is False


def test_max_drawdown_duration_no_drawdown(analyser):
    equity = [100.0, 110.0, 120.0]
    timestamps = [0, 3_600_000, 7_200_000]
    hours, recovered = analyser.max_drawdown_duration(
        equity, timestamps, backtest_end_time=7_200_000
    )
    assert hours == 0.0
    assert recovered is True


def test_max_drawdown_duration_mismatched_lengths_is_safe(analyser):
    hours, recovered = analyser.max_drawdown_duration(
        [100.0, 90.0], [0], backtest_end_time=1000
    )
    assert hours == 0.0
    assert recovered is True


def test_max_drawdown_duration_too_few_points(analyser):
    hours, recovered = analyser.max_drawdown_duration(
        [100.0], [0], backtest_end_time=1000
    )
    assert hours == 0.0
    assert recovered is True


# ──────────────────────────────────────────────────────────────
# ESTIMATED SLIPPAGE COST
# ──────────────────────────────────────────────────────────────


def test_estimated_slippage_cost_basic(analyser):
    slippage_pct = 0.001
    trade = Trade(
        entry_time=0,
        exit_time=1000,
        entry_price=100.1,
        exit_price=99.9,
        size=2.0,
        pnl=(99.9 - 100.1) * 2.0,
        pnl_pct=(99.9 - 100.1) / 100.1,
    )
    cost = analyser.estimated_slippage_cost([trade], slippage_pct)
    entry_cost = 100.1 * slippage_pct / (1 + slippage_pct)
    exit_cost = 99.9 * slippage_pct / (1 - slippage_pct)
    expected = (entry_cost + exit_cost) * 2.0
    assert math.isclose(cost, expected, rel_tol=1e-9)


def test_estimated_slippage_cost_zero_slippage_is_zero(analyser):
    trade = make_trade(10.0)
    assert analyser.estimated_slippage_cost([trade], 0.0) == 0.0


def test_estimated_slippage_cost_no_trades_is_zero(analyser):
    assert analyser.estimated_slippage_cost([], 0.001) == 0.0


# ──────────────────────────────────────────────────────────────
# ANALYSE — FULL INTEGRATION (new fields)
# ──────────────────────────────────────────────────────────────


def test_analyse_includes_new_fields_with_trades(analyser):
    trades = [
        make_trade_timed(0, 3_600_000, 100.0),
        make_trade_timed(3_600_000, 2 * 3_600_000, -50.0),
    ]
    result = make_result_with_metadata(
        trades,
        equity_start=10_000.0,
        slippage_pct=0.001,
        backtest_start_time=0,
        backtest_end_time=2 * 3_600_000,
    )
    report = analyser.analyse(result)

    assert report.num_winning_trades == 1
    assert report.num_losing_trades == 1
    assert report.largest_win == 100.0
    assert report.largest_loss == -50.0
    assert math.isclose(report.final_equity, 10_050.0)
    assert report.equity_curve == result.equity_curve
    assert math.isclose(report.total_return_pct, 0.5)
    assert report.exposure_time_pct > 0.0
    assert report.estimated_slippage_cost > 0.0


def test_analyse_no_trades_zeroes_new_fields(analyser):
    result = BacktestResult(
        strategy_name="Test",
        symbol="BTC",
        candles_tested=100,
        backtest_initial_capital=10_000.0,
    )
    report = analyser.analyse(result)

    assert report.total_return_pct == 0.0
    assert report.num_winning_trades == 0
    assert report.num_losing_trades == 0
    assert report.largest_win == 0.0
    assert report.largest_loss == 0.0
    assert report.avg_trade_return_pct == 0.0
    assert report.avg_holding_time_hours == 0.0
    assert report.final_equity == 10_000.0
    assert report.recovery_factor == 0.0
    assert report.exposure_time_pct == 0.0
    assert report.max_drawdown_duration_hours == 0.0
    assert report.max_drawdown_recovered is True
    assert report.estimated_slippage_cost == 0.0


def test_report_str_contains_new_metrics(analyser):
    trades = [make_trade_timed(0, 3_600_000, 100.0)]
    result = make_result_with_metadata(
        trades, backtest_start_time=0, backtest_end_time=3_600_000
    )
    report = analyser.analyse(result)
    output = str(report)
    assert "Total return" in output
    assert "Recovery factor" in output
    assert "Exposure time" in output
    assert "Max DD duration" in output
    assert "Est. slippage cost" in output
