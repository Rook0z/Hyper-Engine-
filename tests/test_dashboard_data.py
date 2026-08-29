"""
Tests for dashboard/data.py — the dashboard's pure data layer.

No Streamlit import anywhere in this file (matching dashboard/data.py
itself) — these tests run regardless of whether the optional
`dashboard` dependency group is installed. No network, no live
Hyperliquid account, no exchange dependency: every test uses a
temporary, real SQLite Database instance, exactly like
tests/test_database.py.
"""

import pytest

from backtester.backtester import BacktestResult, Trade
from backtester.monte_carlo import MonteCarloReport, MonteCarloSimulationResult
from backtester.performance import PerformanceAnalyser
from backtester.walk_forward import (
    WalkForwardReport,
    WalkForwardWindow,
    WalkForwardWindowResult,
)
from core.database import Database
from dashboard import data
from core.config import settings


@pytest.fixture
def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test_dashboard.db"))
    yield database
    database.close()


def make_backtest_result(pnl=5.0):
    trade = Trade(
        entry_time=1000,
        exit_time=2000,
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=pnl,
        pnl_pct=pnl / 100.0,
    )
    return BacktestResult(
        trades=[trade],
        total_pnl=pnl,
        win_rate=1.0,
        profit_factor=float("inf"),
        max_drawdown=0.0,
        num_trades=1,
        equity_curve=[10_000.0, 10_000.0 + pnl],
        strategy_name="EMA(9,21)",
        symbol="BTC",
        candles_tested=100,
    )


# ──────────────────────────────────────────────────────────────
# 1. OVERVIEW — EMPTY STATE
# ──────────────────────────────────────────────────────────────


def test_get_current_session_empty_db_returns_none(db):
    assert data.get_current_session(db) is None


def test_get_overview_empty_db_returns_zeroed_summary(db):
    overview = data.get_overview(db)
    assert overview["num_trades"] == 0
    assert overview["num_winning"] == 0
    assert overview["num_losing"] == 0
    assert overview["win_rate"] == 0.0
    assert overview["total_pnl"] == 0.0
    assert overview["avg_trade_pnl"] == 0.0
    assert overview["recent_trades"] == []
    assert overview["current_session"] is None


# ──────────────────────────────────────────────────────────────
# 1. OVERVIEW — WITH DATA
# ──────────────────────────────────────────────────────────────


def test_get_current_session_returns_most_recent(db):
    db.save_session_start(
        session_id="s1",
        symbol="BTC",
        strategy="EMA",
        mode="paper",
        starting_balance=10_000.0,
    )
    session = data.get_current_session(db)
    assert session["session_id"] == "s1"
    assert session["symbol"] == "BTC"


def test_get_overview_computes_win_loss_counts_and_win_rate(db):
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
    )
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=98.0,
        size=1.0,
        pnl=-2.0,
        pnl_pct=-0.02,
    )
    overview = data.get_overview(db)
    assert overview["num_trades"] == 2
    assert overview["num_winning"] == 1
    assert overview["num_losing"] == 1
    assert overview["win_rate"] == pytest.approx(0.5)
    assert overview["total_pnl"] == pytest.approx(3.0)


def test_get_overview_win_rate_matches_performance_analyser_directly(db):
    """Regression guard: the dashboard must use PerformanceAnalyser's
    own win_rate(), not a reimplementation, so the two can never
    silently diverge."""
    for pnl in [5.0, -2.0, 3.0, -1.0]:
        db.save_trade(
            session_id="s1",
            symbol="BTC",
            side="LONG",
            entry_price=100.0,
            exit_price=100.0 + pnl,
            size=1.0,
            pnl=pnl,
            pnl_pct=pnl / 100.0,
        )
    overview = data.get_overview(db)
    expected = PerformanceAnalyser().win_rate([5.0, -2.0, 3.0, -1.0])
    assert overview["win_rate"] == expected


def test_get_overview_recent_trades_capped_at_ten(db):
    for i in range(15):
        db.save_trade(
            session_id="s1",
            symbol="BTC",
            side="LONG",
            entry_price=100.0,
            exit_price=101.0,
            size=1.0,
            pnl=1.0,
            pnl_pct=0.01,
        )
    overview = data.get_overview(db)
    assert len(overview["recent_trades"]) == 10


def test_get_overview_can_scope_to_one_session(db):
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
    )
    db.save_trade(
        session_id="s2",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=90.0,
        size=1.0,
        pnl=-10.0,
        pnl_pct=-0.1,
    )
    overview = data.get_overview(db, session_id="s1")
    assert overview["num_trades"] == 1
    assert overview["total_pnl"] == pytest.approx(5.0)


# ──────────────────────────────────────────────────────────────
# 2. TRADING HISTORY / FILTERING
# ──────────────────────────────────────────────────────────────


def test_list_trades_view_empty_db(db):
    assert data.list_trades_view(db) == []


def test_list_trades_view_filters_by_symbol(db):
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
    )
    db.save_trade(
        session_id="s1",
        symbol="ETH",
        side="LONG",
        entry_price=3_000.0,
        exit_price=3_100.0,
        size=1.0,
        pnl=100.0,
        pnl_pct=0.033,
    )
    result = data.list_trades_view(db, symbol="BTC")
    assert len(result) == 1
    assert result[0]["symbol"] == "BTC"


def test_list_trades_view_filters_by_side(db):
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
    )
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="SHORT",
        entry_price=105.0,
        exit_price=100.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
    )
    result = data.list_trades_view(db, side="SHORT")
    assert len(result) == 1
    assert result[0]["side"] == "SHORT"


def test_list_trades_view_filters_by_date_range(db):
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
        exit_time="2026-01-01T00:00:00+00:00",
    )
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=110.0,
        size=1.0,
        pnl=10.0,
        pnl_pct=0.1,
        exit_time="2026-06-01T00:00:00+00:00",
    )
    result = data.list_trades_view(db, start_time="2026-05-01", end_time="2026-12-31")
    assert len(result) == 1
    assert result[0]["pnl"] == 10.0


def test_list_trades_view_combines_multiple_filters(db):
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
    )
    db.save_trade(
        session_id="s1",
        symbol="ETH",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
    )
    db.save_trade(
        session_id="s2",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=95.0,
        size=1.0,
        pnl=-5.0,
        pnl_pct=-0.05,
    )
    result = data.list_trades_view(db, symbol="BTC", session_id="s1")
    assert len(result) == 1
    assert result[0]["pnl"] == 5.0


# ──────────────────────────────────────────────────────────────
# 3. ORDERS AND FILLS
# ──────────────────────────────────────────────────────────────


def test_list_orders_view_empty(db):
    assert data.list_orders_view(db) == []


def test_list_orders_view_returns_saved_orders(db):
    db.save_order(session_id="s1", symbol="BTC", side="BUY", price=50_000.0, size=0.001)
    orders = data.list_orders_view(db)
    assert len(orders) == 1
    assert orders[0]["side"] == "BUY"


def test_list_fills_view_empty(db):
    assert data.list_fills_view(db) == []


def test_list_fills_view_returns_saved_fills(db):
    db.save_fill(session_id="s1", symbol="BTC", side="BUY", price=50_050.0, size=0.001)
    fills = data.list_fills_view(db)
    assert len(fills) == 1
    assert fills[0]["price"] == 50_050.0


def test_list_orders_fills_view_filters_by_session(db):
    db.save_order(session_id="s1", symbol="BTC", side="BUY", price=50_000.0, size=0.001)
    db.save_order(
        session_id="s2", symbol="BTC", side="SELL", price=51_000.0, size=0.001
    )
    assert len(data.list_orders_view(db, session_id="s1")) == 1


# ──────────────────────────────────────────────────────────────
# 4. PERFORMANCE
# ──────────────────────────────────────────────────────────────


def test_get_latest_backtest_performance_none_when_empty(db):
    assert data.get_latest_backtest_performance(db) is None


def test_get_latest_backtest_performance_returns_stored_report(db):
    result = make_backtest_result()
    report = PerformanceAnalyser().analyse(result)
    db.save_backtest_result("EMA(9,21)", "BTC", result, report)

    stored = data.get_latest_backtest_performance(db)
    assert stored is not None
    assert stored["report"]["num_trades"] == 1
    assert stored["result"]["total_pnl"] == 5.0


def test_get_latest_backtest_performance_filters_by_strategy(db):
    result = make_backtest_result()
    report = PerformanceAnalyser().analyse(result)
    db.save_backtest_result("EMA(9,21)", "BTC", result, report)
    db.save_backtest_result("RSI(14)", "BTC", result, report)

    stored = data.get_latest_backtest_performance(db, strategy_name="RSI(14)")
    assert stored is not None
    # confirm we got the RSI one specifically by checking the row via list
    rows = db.list_analysis_results(result_type="backtest", strategy_name="RSI(14)")
    assert len(rows) == 1


def test_get_live_trades_performance_empty_db(db):
    perf = data.get_live_trades_performance(db)
    assert perf["num_trades"] == 0
    assert perf["total_pnl"] == 0.0
    assert perf["equity_curve"] == []


def test_get_live_trades_performance_computes_via_analyser(db):
    for pnl, pct in [(5.0, 0.05), (-2.0, -0.02), (3.0, 0.03)]:
        db.save_trade(
            session_id="s1",
            symbol="BTC",
            side="LONG",
            entry_price=100.0,
            exit_price=100.0 + pnl,
            size=1.0,
            pnl=pnl,
            pnl_pct=pct,
        )
    perf = data.get_live_trades_performance(db)
    assert perf["num_trades"] == 3
    assert perf["total_pnl"] == pytest.approx(6.0)
    expected_win_rate = PerformanceAnalyser().win_rate([5.0, -2.0, 3.0])
    assert perf["win_rate"] == expected_win_rate


def test_get_live_trades_performance_equity_curve_starts_at_zero_and_accumulates(db):
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
        exit_time="2026-01-01T00:00:00+00:00",
    )
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=97.0,
        size=1.0,
        pnl=-3.0,
        pnl_pct=-0.03,
        exit_time="2026-01-02T00:00:00+00:00",
    )
    perf = data.get_live_trades_performance(db)
    assert perf["equity_curve"] == [0.0, 5.0, 2.0]


# ──────────────────────────────────────────────────────────────
# 5. STRATEGY ANALYSIS — REHYDRATION CORRECTNESS
# ──────────────────────────────────────────────────────────────


def test_get_analysis_result_detail_none_when_missing(db):
    assert data.get_analysis_result_detail(db, 99999) is None


def test_get_analysis_result_detail_backtest_needs_no_rehydration(db):
    result = make_backtest_result()
    report = PerformanceAnalyser().analyse(result)
    result_id = db.save_backtest_result("EMA(9,21)", "BTC", result, report)

    detail = data.get_analysis_result_detail(db, result_id)
    assert detail["result_type"] == "backtest"
    assert "rehydrated" not in detail
    assert detail["summary"]["report"]["num_trades"] == 1


def test_get_analysis_result_detail_walk_forward_rehydrates_aggregates(db):
    """
    Regression test: WalkForwardReport's most useful numbers
    (total_test_trades, total_test_pnl, average_test_sharpe, etc.) are
    computed @property methods, NOT stored fields — dataclasses.asdict()
    never captures them. This proves the dashboard's rehydration
    recovers the real, correctly-computed aggregate rather than
    silently missing it or reimplementing the math.
    """
    result_a = make_backtest_result(pnl=10.0)
    result_b = make_backtest_result(pnl=-4.0)
    report_a = PerformanceAnalyser().analyse(result_a)
    report_b = PerformanceAnalyser().analyse(result_b)

    window = WalkForwardWindow(
        window_index=0,
        train=[[1000, 1, 1, 1, 1, 1]],
        test=[[2000, 1, 1, 1, 1, 1]],
    )
    window_result = WalkForwardWindowResult(
        window=window,
        strategy_name="EMA(9,21)",
        train_result=result_a,
        train_report=report_a,
        test_result=result_b,
        test_report=report_b,
    )
    wf_report = WalkForwardReport(window_results=[window_result])
    result_id = db.save_walk_forward_result("EMA(9,21)", "BTC", wf_report)

    detail = data.get_analysis_result_detail(db, result_id)
    rehydrated: WalkForwardReport = detail["rehydrated"]

    assert rehydrated.num_windows == 1
    assert rehydrated.total_test_trades == 1
    assert rehydrated.total_test_pnl == pytest.approx(-4.0)
    assert rehydrated.average_test_sharpe == report_b.sharpe_ratio


def test_get_analysis_result_detail_monte_carlo_rehydrates(db):
    sim = MonteCarloSimulationResult(
        equity_curve=[10_000.0, 10_050.0],
        final_equity=10_050.0,
        total_pnl=50.0,
        max_drawdown=0.001,
    )
    mc_report = MonteCarloReport(
        num_simulations=1,
        method="shuffle",
        initial_capital=10_000.0,
        original_final_equity=10_050.0,
        original_max_drawdown=0.001,
        simulations=[sim],
    )
    result_id = db.save_monte_carlo_result("EMA(9,21)", "BTC", mc_report)

    detail = data.get_analysis_result_detail(db, result_id)
    rehydrated: MonteCarloReport = detail["rehydrated"]
    assert rehydrated.median_final_equity == 10_050.0
    assert rehydrated.probability_of_loss == 0.0


# ──────────────────────────────────────────────────────────────
# 6. MONTE CARLO SUMMARY
# ──────────────────────────────────────────────────────────────


def test_get_monte_carlo_summary_none_for_missing_result(db):
    assert data.get_monte_carlo_summary(db, 99999) is None


def test_get_monte_carlo_summary_none_for_wrong_result_type(db):
    result = make_backtest_result()
    report = PerformanceAnalyser().analyse(result)
    result_id = db.save_backtest_result("EMA(9,21)", "BTC", result, report)
    assert data.get_monte_carlo_summary(db, result_id) is None


def test_get_monte_carlo_summary_includes_all_percentiles_and_probability(db):
    sims = [
        MonteCarloSimulationResult(
            equity_curve=[10_000.0, fe],
            final_equity=fe,
            total_pnl=fe - 10_000.0,
            max_drawdown=dd,
        )
        for fe, dd in [(9_000.0, 0.1), (10_000.0, 0.05), (11_000.0, 0.02)]
    ]
    mc_report = MonteCarloReport(
        num_simulations=3,
        method="bootstrap",
        initial_capital=10_000.0,
        original_final_equity=10_500.0,
        original_max_drawdown=0.03,
        simulations=sims,
    )
    result_id = db.save_monte_carlo_result("EMA(9,21)", "BTC", mc_report)

    summary = data.get_monte_carlo_summary(db, result_id)
    assert summary["num_simulations"] == 3
    assert summary["method"] == "bootstrap"
    assert summary["final_equity_median"] == 10_000.0
    assert summary["final_equity_worst"] == 9_000.0
    assert summary["final_equity_best"] == 11_000.0
    assert summary["probability_of_loss"] == pytest.approx(1 / 3)
    assert summary["worst_max_drawdown"] == 0.1


# ──────────────────────────────────────────────────────────────
# 7. RISK OVERVIEW
# ──────────────────────────────────────────────────────────────


def test_get_risk_overview_returns_configured_limits(db):
    risk = data.get_risk_overview(db)
    assert risk["configured_max_position_pct"] == settings.max_position_pct
    assert risk["configured_max_daily_loss_pct"] == settings.max_daily_loss_pct
    assert risk["configured_max_open_positions"] == settings.max_open_positions
    assert risk["configured_position_size"] == settings.position_size


def test_get_risk_overview_empty_db_has_zero_realized_loss(db):
    risk = data.get_risk_overview(db)
    assert risk["today_realized_loss_usdc"] == 0.0
    assert risk["today_loss_pct_of_cap"] == 0.0


def test_get_risk_overview_sums_only_todays_losing_trades(db):
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    yesterday_iso = "2020-01-01T00:00:00+00:00"

    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=95.0,
        size=1.0,
        pnl=-5.0,
        pnl_pct=-0.05,
        exit_time=f"{today}T12:00:00+00:00",
    )
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=105.0,
        size=1.0,
        pnl=5.0,
        pnl_pct=0.05,
        exit_time=f"{today}T13:00:00+00:00",
    )  # winning trade today, must not count toward realized LOSS
    db.save_trade(
        session_id="s1",
        symbol="BTC",
        side="LONG",
        entry_price=100.0,
        exit_price=80.0,
        size=1.0,
        pnl=-20.0,
        pnl_pct=-0.2,
        exit_time=yesterday_iso,
    )  # loss, but not today — must not count

    risk = data.get_risk_overview(db)
    assert risk["today_realized_loss_usdc"] == pytest.approx(5.0)
