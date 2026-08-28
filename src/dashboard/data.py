"""
Dashboard data layer.

Pure Python: no Streamlit (or any UI framework) import anywhere in
this file. Every function here takes a Database instance and returns
plain dicts/lists, ready to hand to a UI layer (src/dashboard/views/)
or to a future API. This split exists specifically so the data layer
is fully unit-testable without the optional `dashboard` dependency
group (Streamlit) installed — see tests/test_dashboard_data.py.

Read-only by construction: every function here only ever calls
Database's existing read methods (get_*/list_*) or PerformanceAnalyser
methods. Nothing in this module writes to the database, places an
order, or touches TestnetExecutor/HyperliquidTrading/RiskManager in
any way that could submit or modify anything.

Calculation reuse: wherever a metric already has a home elsewhere in
the codebase (win rate, expectancy, profit factor, drawdown, Monte
Carlo percentiles, walk-forward aggregates), this module calls that
existing code rather than recomputing it. For MonteCarloReport and
WalkForwardReport specifically, their most useful numbers are
computed *properties*, not stored fields, so they aren't literally
present in the persisted JSON (dataclasses.asdict() only captures
fields) — _rehydrate_monte_carlo()/_rehydrate_walk_forward() below
reconstruct the real dataclass from the stored dict and read its own
properties, rather than reimplementing that math here.
"""

from __future__ import annotations

from typing import Any

from backtester.backtester import BacktestResult
from backtester.monte_carlo import MonteCarloReport, MonteCarloSimulationResult
from backtester.performance import PerformanceAnalyser
from backtester.walk_forward import (
    WalkForwardReport,
    WalkForwardWindow,
    WalkForwardWindowResult,
)
from core.config import settings
from core.database import Database

_analyser = PerformanceAnalyser()


# ──────────────────────────────────────────────────────────────
# 1. OVERVIEW
# ──────────────────────────────────────────────────────────────


def get_current_session(db: Database) -> dict[str, Any] | None:
    """Most recent trading session (by started_at), or None if the
    database has no sessions yet."""
    sessions = db.list_sessions(limit=1)
    return sessions[0] if sessions else None


def get_overview(db: Database, session_id: str | None = None) -> dict[str, Any]:
    """
    Summary stats for the overview page: total/winning/losing trades,
    win rate, total PnL, average trade PnL, and the most recent trades.

    Win rate and average trade PnL (expectancy) are computed via
    PerformanceAnalyser on the persisted trade PnLs, rather than
    reimplementing that arithmetic here.

    Args:
        db:         Database instance.
        session_id: Restrict to one session's trades, or None for all
                    persisted trades across every session.

    Returns:
        Dict with: num_trades, num_winning, num_losing, win_rate,
        total_pnl, avg_trade_pnl, recent_trades (up to 10, newest
        first), current_session.
    """
    trades = db.list_trades(session_id=session_id, limit=10_000)
    current_session = get_current_session(db)

    if not trades:
        return {
            "num_trades": 0,
            "num_winning": 0,
            "num_losing": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_trade_pnl": 0.0,
            "recent_trades": [],
            "current_session": current_session,
        }

    pnl_list = [t["pnl"] for t in trades]
    num_winning = sum(1 for p in pnl_list if p > 0)
    num_losing = sum(1 for p in pnl_list if p < 0)

    return {
        "num_trades": len(trades),
        "num_winning": num_winning,
        "num_losing": num_losing,
        "win_rate": _analyser.win_rate(pnl_list),
        "total_pnl": _analyser.total_pnl(pnl_list),
        "avg_trade_pnl": _analyser.expectancy(pnl_list),
        "recent_trades": trades[:10],
        "current_session": current_session,
    }


# ──────────────────────────────────────────────────────────────
# 2. TRADING HISTORY
# ──────────────────────────────────────────────────────────────


def list_trades_view(
    db: Database,
    symbol: str | None = None,
    side: str | None = None,
    session_id: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """
    Persisted completed trades for the trading-history view, with
    filtering. symbol/session_id are pushed down to Database.list_trades()
    (already supported there); side and date-range filtering are
    applied afterward in Python, since Database.list_trades() doesn't
    natively support them and adding new query parameters to the
    Database API isn't warranted for two extra dashboard filters (see
    "do not redesign the schema/API unless necessary").

    Args:
        db:         Database instance.
        symbol:     e.g. "BTC" — exact match, pushed to the DB query.
        side:       e.g. "LONG"/"SHORT"/"BUY"/"SELL" — exact match,
                    filtered in Python.
        session_id: Restrict to one session.
        start_time: Inclusive ISO-8601 lower bound on exit_time
                    (string comparison — exit_time is stored as ISO
                    text, so this works correctly without parsing).
        end_time:   Inclusive ISO-8601 upper bound on exit_time.
        limit:      Max rows fetched from the DB before filtering —
                    note the returned list may be shorter than limit
                    once side/date filters are applied.
    """
    trades = db.list_trades(session_id=session_id, symbol=symbol, limit=limit)

    if side is not None:
        trades = [t for t in trades if t["side"] == side]
    if start_time is not None:
        trades = [t for t in trades if t["exit_time"] >= start_time]
    if end_time is not None:
        trades = [t for t in trades if t["exit_time"] <= end_time]

    return trades


# ──────────────────────────────────────────────────────────────
# 3. ORDERS AND FILLS
# ──────────────────────────────────────────────────────────────


def list_orders_view(
    db: Database, session_id: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    """Persisted historical orders. See Database.save_order() for what
    gets recorded — this is a read-only, historical record, not a live
    order-status feed."""
    return db.list_orders(session_id=session_id, limit=limit)


def list_fills_view(
    db: Database, session_id: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    """Persisted historical fills. Same caveat as list_orders_view —
    historical record only."""
    return db.list_fills(session_id=session_id, limit=limit)


# ──────────────────────────────────────────────────────────────
# 4. PERFORMANCE
# ──────────────────────────────────────────────────────────────


def get_latest_backtest_performance(
    db: Database, strategy_name: str | None = None, symbol: str | None = None
) -> dict[str, Any] | None:
    """
    Most recent persisted backtest result (result_type="backtest"),
    with its full stored PerformanceReport — computed once by
    PerformanceAnalyser at backtest time (see
    Database.save_backtest_result()) and never recalculated here.

    Returns:
        The stored summary dict (with "result" and "report" keys), or
        None if nothing has been persisted yet.
    """
    results = db.list_analysis_results(
        result_type="backtest", strategy_name=strategy_name, symbol=symbol, limit=1
    )
    if not results:
        return None
    full = db.get_analysis_result(results[0]["id"])
    return full["summary"] if full else None


def get_live_trades_performance(
    db: Database, session_id: str | None = None, symbol: str | None = None
) -> dict[str, Any]:
    """
    Performance metrics computed from PERSISTED LIVE/paper trades
    (not a backtest) — win rate, profit factor, expectancy, Sharpe,
    max drawdown — all via PerformanceAnalyser on the trades' PnL/
    return series, and an equity curve built by cumulatively summing
    persisted trade PnLs (the same construction Backtester itself uses
    for equity_curve — see Backtester._build_result()).

    Returns a zeroed dict (matching PerformanceAnalyser's own
    zero-trades convention) if there are no persisted trades to
    analyse.
    """
    trades = db.list_trades(session_id=session_id, symbol=symbol, limit=10_000)
    if not trades:
        return {
            "num_trades": 0,
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "equity_curve": [],
        }

    # Chronological order for a meaningful equity curve — trades come
    # back newest-first from Database.list_trades().
    trades = sorted(trades, key=lambda t: t["exit_time"])
    pnl_list = [t["pnl"] for t in trades]
    returns = [t["pnl_pct"] for t in trades]

    equity_curve = [0.0]
    running = 0.0
    for pnl in pnl_list:
        running += pnl
        equity_curve.append(running)

    return {
        "num_trades": len(trades),
        "total_pnl": _analyser.total_pnl(pnl_list),
        "win_rate": _analyser.win_rate(pnl_list),
        "profit_factor": _analyser.profit_factor(pnl_list),
        "expectancy": _analyser.expectancy(pnl_list),
        "sharpe_ratio": _analyser.sharpe_ratio(returns),
        "max_drawdown": _analyser.max_drawdown(equity_curve),
        "equity_curve": equity_curve,
    }


# ──────────────────────────────────────────────────────────────
# 5. STRATEGY ANALYSIS (backtest / OOS / walk-forward / Monte Carlo)
# ──────────────────────────────────────────────────────────────


def list_analysis_results_view(
    db: Database,
    result_type: str | None = None,
    strategy_name: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Metadata-only listing (id/type/strategy/symbol/created_at) for
    browsing stored analysis results — see get_analysis_result_detail()
    for the full stored report."""
    return db.list_analysis_results(
        result_type=result_type,
        strategy_name=strategy_name,
        symbol=symbol,
        limit=limit,
    )


def get_analysis_result_detail(db: Database, result_id: int) -> dict[str, Any] | None:
    """
    Full stored analysis result for one row, with result_type-specific
    rehydration applied where the report's most useful numbers are
    computed properties rather than stored fields (Monte Carlo, walk-
    forward) — see module docstring. BacktestResult/PerformanceReport
    and OutOfSampleReport need no rehydration: every field they expose
    is a real stored field, already present in the persisted JSON
    exactly as computed at analysis time.

    Returns:
        None if result_id doesn't exist. Otherwise the DB row dict
        plus "summary" (raw stored dict) and, for monte_carlo/
        walk_forward, "rehydrated" (the reconstructed dataclass, for
        direct property access).
    """
    row = db.get_analysis_result(result_id)
    if row is None:
        return None

    if row["result_type"] == "monte_carlo":
        row["rehydrated"] = _rehydrate_monte_carlo(row["summary"])
    elif row["result_type"] == "walk_forward":
        row["rehydrated"] = _rehydrate_walk_forward(row["summary"])

    return row


def _rehydrate_monte_carlo(summary: dict[str, Any]) -> MonteCarloReport:
    """
    Reconstructs a real MonteCarloReport from its persisted JSON, so
    its existing @property methods (median_final_equity,
    probability_of_loss, final_equity_percentile(), etc.) can be
    called directly instead of reimplementing that percentile/
    probability math in the dashboard.
    """
    simulations = [
        MonteCarloSimulationResult(
            equity_curve=s["equity_curve"],
            final_equity=s["final_equity"],
            total_pnl=s["total_pnl"],
            max_drawdown=s["max_drawdown"],
        )
        for s in summary.get("simulations", [])
    ]
    return MonteCarloReport(
        num_simulations=summary["num_simulations"],
        method=summary["method"],
        initial_capital=summary["initial_capital"],
        original_final_equity=summary["original_final_equity"],
        original_max_drawdown=summary["original_max_drawdown"],
        simulations=simulations,
    )


def _rehydrate_walk_forward(summary: dict[str, Any]) -> WalkForwardReport:
    """
    Reconstructs a real WalkForwardReport from its persisted JSON, so
    its existing @property aggregates (total_test_trades,
    total_test_pnl, average_test_sharpe, profitable_window_count,
    combined_test_equity_curve()) can be called directly instead of
    reimplementing those sums/averages in the dashboard.

    Note: BacktestResult.trades is left as plain dicts (not
    reconstructed into Trade objects) inside train_result/test_result
    — none of WalkForwardReport's properties touch individual Trade
    objects (they use test_report's already-computed fields, and
    test_result.equity_curve, which is a plain list[float]), so this
    is sufficient for full fidelity of every existing aggregate.
    """
    window_results = []
    for wr in summary.get("window_results", []):
        w = wr["window"]
        window_results.append(
            WalkForwardWindowResult(
                window=WalkForwardWindow(
                    window_index=w["window_index"], train=w["train"], test=w["test"]
                ),
                strategy_name=wr["strategy_name"],
                train_result=BacktestResult(**wr["train_result"]),
                train_report=_dict_to_performance_report(wr["train_report"]),
                test_result=BacktestResult(**wr["test_result"]),
                test_report=_dict_to_performance_report(wr["test_report"]),
            )
        )
    return WalkForwardReport(window_results=window_results)


def _dict_to_performance_report(d: dict[str, Any]) -> Any:
    """PerformanceReport has no computed properties, so a straight
    keyword unpack is sufficient — imported locally to avoid an
    unused-name lint warning when only used inside one helper."""
    from backtester.performance import PerformanceReport

    return PerformanceReport(**d)


# ──────────────────────────────────────────────────────────────
# 6. MONTE CARLO
# ──────────────────────────────────────────────────────────────


def get_monte_carlo_summary(db: Database, result_id: int) -> dict[str, Any] | None:
    """
    Displayable summary for one stored Monte Carlo result: final-
    equity percentiles, probability of loss, median/worst drawdown,
    and simulation metadata — all read directly from the rehydrated
    MonteCarloReport's own existing properties (see
    _rehydrate_monte_carlo()), never recomputed here.

    Returns:
        None if result_id doesn't exist or isn't a monte_carlo result.
    """
    detail = get_analysis_result_detail(db, result_id)
    if detail is None or detail["result_type"] != "monte_carlo":
        return None

    report: MonteCarloReport = detail["rehydrated"]
    return {
        "num_simulations": report.num_simulations,
        "method": report.method,
        "initial_capital": report.initial_capital,
        "original_final_equity": report.original_final_equity,
        "original_max_drawdown": report.original_max_drawdown,
        "final_equity_p5": report.final_equity_percentile(0.05),
        "final_equity_p25": report.final_equity_percentile(0.25),
        "final_equity_median": report.median_final_equity,
        "final_equity_p75": report.final_equity_percentile(0.75),
        "final_equity_p95": report.final_equity_percentile(0.95),
        "final_equity_mean": report.mean_final_equity,
        "final_equity_worst": report.worst_final_equity,
        "final_equity_best": report.best_final_equity,
        "median_max_drawdown": report.median_max_drawdown,
        "worst_max_drawdown": report.worst_max_drawdown,
        "probability_of_loss": report.probability_of_loss,
    }


# ──────────────────────────────────────────────────────────────
# 7. RISK (observation only — no new risk rules, nothing modified)
# ──────────────────────────────────────────────────────────────


def get_risk_overview(db: Database, session_id: str | None = None) -> dict[str, Any]:
    """
    Read-only risk snapshot for the dashboard: the CONFIGURED limits
    RiskManager actually enforces (read from settings — the same
    config object RiskManager itself is constructed from in
    strategy_runner.py; nothing here re-derives or overrides those
    values), plus a derived, informational "today's realized loss"
    figure computed from persisted trades — the same underlying
    concept RiskManager's own daily-loss check uses, but computed here
    for DISPLAY from the database rather than read from a live
    process's in-memory state.

    This function creates no risk rules of its own and cannot affect
    RiskManager's actual enforcement in any way — it only reads
    settings and persisted trade rows.
    """
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    trades = db.list_trades(session_id=session_id, limit=10_000)
    todays_losses = [
        t["pnl"] for t in trades if t["exit_time"].startswith(today) and t["pnl"] < 0
    ]
    today_realized_loss = abs(sum(todays_losses)) if todays_losses else 0.0

    configured_daily_loss_cap = settings.initial_capital * settings.max_daily_loss_pct

    return {
        "configured_max_position_pct": settings.max_position_pct,
        "configured_max_daily_loss_pct": settings.max_daily_loss_pct,
        "configured_max_daily_loss_usdc": configured_daily_loss_cap,
        "configured_max_open_positions": settings.max_open_positions,
        "configured_position_size": settings.position_size,
        "today_realized_loss_usdc": today_realized_loss,
        "today_loss_pct_of_cap": (
            today_realized_loss / configured_daily_loss_cap
            if configured_daily_loss_cap > 0
            else 0.0
        ),
    }
