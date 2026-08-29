"""
Performance page: metrics from PerformanceAnalyser — either the most
recent persisted backtest result, or a live-trades-derived snapshot.
Nothing here recalculates what PerformanceAnalyser/Backtester already
computed.
"""

from __future__ import annotations

import streamlit as st

from core.database import Database
from dashboard import data


def render(db: Database) -> None:
    st.header("Performance")

    tab_live, tab_backtest = st.tabs(["Live / Paper Trades", "Latest Backtest"])

    with tab_live:
        perf = data.get_live_trades_performance(db)
        if perf["num_trades"] == 0:
            st.info("No persisted trades yet.")
        else:
            cols = st.columns(4)
            cols[0].metric("Trades", perf["num_trades"])
            cols[1].metric("Total PnL", f"{perf['total_pnl']:+.2f}")
            cols[2].metric("Win Rate", f"{perf['win_rate']:.1%}")
            cols[3].metric(
                "Profit Factor",
                f"{perf['profit_factor']:.2f}"
                if perf["profit_factor"] != float("inf")
                else "\u221e",
            )
            cols = st.columns(3)
            cols[0].metric("Expectancy", f"{perf['expectancy']:+.4f}")
            cols[1].metric("Sharpe Ratio", f"{perf['sharpe_ratio']:.4f}")
            cols[2].metric("Max Drawdown", f"{perf['max_drawdown']:.1%}")

            if perf["equity_curve"]:
                st.subheader("Cumulative PnL (Equity Curve)")
                st.line_chart(perf["equity_curve"])

    with tab_backtest:
        strategy_name = (
            st.text_input("Strategy name filter (optional)", value="") or None
        )
        symbol = (
            st.text_input("Symbol filter (optional)", value="", key="bt_symbol") or None
        )
        result = data.get_latest_backtest_performance(
            db, strategy_name=strategy_name, symbol=symbol
        )
        if result is None:
            st.info("No backtest results persisted yet.")
        else:
            report = result["report"]
            cols = st.columns(4)
            cols[0].metric("Trades", report["num_trades"])
            cols[1].metric("Total PnL", f"{report['total_pnl']:+.2f}")
            cols[2].metric("Win Rate", f"{report['win_rate']:.1%}")
            cols[3].metric("Sharpe Ratio", f"{report['sharpe_ratio']:.4f}")
            cols = st.columns(3)
            cols[0].metric("Max Drawdown", f"{report['max_drawdown']:.1%}")
            cols[1].metric("Total Return", f"{report.get('total_return_pct', 0):+.2f}%")
            cols[2].metric("Final Equity", f"{report.get('final_equity', 0):.2f}")

            equity_curve = report.get("equity_curve")
            if equity_curve:
                st.subheader("Equity Curve")
                st.line_chart(equity_curve)
