"""
Strategy analysis page: browse persisted BacktestResult/
PerformanceReport, OutOfSampleReport, and WalkForwardReport results.
(Monte Carlo has its own dedicated page — see monte_carlo.py.)
"""

from __future__ import annotations

import streamlit as st

from core.database import Database
from dashboard import data


def render(db: Database) -> None:
    st.header("Strategy Analysis")
    st.caption(
        "Browses stored analysis results — nothing on this page is "
        "recalculated; every number was computed once at analysis time "
        "and persisted as-is."
    )

    result_type = st.selectbox(
        "Result type", ["backtest", "out_of_sample", "walk_forward"]
    )
    results = data.list_analysis_results_view(db, result_type=result_type, limit=50)

    if not results:
        st.info(f"No '{result_type}' results persisted yet.")
        return

    labels = [
        f"#{r['id']} — {r['strategy_name']} / {r['symbol']} — {r['created_at']}"
        for r in results
    ]
    selected = st.selectbox("Result", labels)
    selected_id = results[labels.index(selected)]["id"]

    detail = data.get_analysis_result_detail(db, selected_id)
    if detail is None:
        st.error("Result not found.")
        return

    summary = detail["summary"]

    if result_type == "backtest":
        _render_backtest(summary)
    elif result_type == "out_of_sample":
        _render_out_of_sample(summary)
    elif result_type == "walk_forward":
        _render_walk_forward(detail["rehydrated"])


def _render_backtest(summary: dict) -> None:
    report = summary["report"]
    cols = st.columns(4)
    cols[0].metric("Trades", report["num_trades"])
    cols[1].metric("Total PnL", f"{report['total_pnl']:+.2f}")
    cols[2].metric("Win Rate", f"{report['win_rate']:.1%}")
    cols[3].metric("Sharpe", f"{report['sharpe_ratio']:.4f}")
    if report.get("equity_curve"):
        st.line_chart(report["equity_curve"])


def _render_out_of_sample(summary: dict) -> None:
    isr = summary["in_sample_report"]
    oos = summary["out_of_sample_report"]
    st.subheader(f"Strategy: {summary['strategy_name']}")
    col_is, col_oos = st.columns(2)
    with col_is:
        st.markdown("**In-Sample**")
        st.metric("Trades", isr["num_trades"])
        st.metric("Total PnL", f"{isr['total_pnl']:+.2f}")
        st.metric("Sharpe", f"{isr['sharpe_ratio']:.4f}")
    with col_oos:
        st.markdown("**Out-of-Sample**")
        st.metric("Trades", oos["num_trades"])
        st.metric("Total PnL", f"{oos['total_pnl']:+.2f}")
        st.metric("Sharpe", f"{oos['sharpe_ratio']:.4f}")


def _render_walk_forward(report) -> None: 
    cols = st.columns(4)
    cols[0].metric("Windows", report.num_windows)
    cols[1].metric("Total Test Trades", report.total_test_trades)
    cols[2].metric("Total Test PnL", f"{report.total_test_pnl:+.2f}")
    cols[3].metric("Avg Test Sharpe", f"{report.average_test_sharpe:.4f}")
    cols = st.columns(2)
    cols[0].metric(
        "Profitable Windows", f"{report.profitable_window_count}/{report.num_windows}"
    )
    cols[1].metric("Avg Test Win Rate", f"{report.average_test_win_rate:.1%}")

    rows = [
        {
            "window": w.window.window_index,
            "strategy": w.strategy_name,
            "train_trades": w.train_report.num_trades,
            "test_trades": w.test_report.num_trades,
            "test_pnl": w.test_report.total_pnl,
            "test_sharpe": w.test_report.sharpe_ratio,
        }
        for w in report.window_results
    ]
    st.dataframe(rows, use_container_width=True)
