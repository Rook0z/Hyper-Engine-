"""Overview page: current session, key stats, recent trades."""

from __future__ import annotations

import streamlit as st

from core.database import Database
from dashboard import data


def render(db: Database) -> None:
    st.header("Overview")

    overview = data.get_overview(db)
    session = overview["current_session"]

    if session is None:
        st.info("No trading sessions recorded yet.")
        return

    st.subheader("Current / Most Recent Session")
    status = "Running" if session["ended_at"] is None else "Ended"
    cols = st.columns(4)
    cols[0].metric("Status", status)
    cols[1].metric("Symbol", session["symbol"])
    cols[2].metric("Strategy", session["strategy"])
    cols[3].metric("Mode", session["mode"])

    st.subheader("Summary")
    cols = st.columns(4)
    cols[0].metric("Total Trades", overview["num_trades"])
    cols[1].metric("Winning Trades", overview["num_winning"])
    cols[2].metric("Losing Trades", overview["num_losing"])
    cols[3].metric("Win Rate", f"{overview['win_rate']:.1%}")

    cols = st.columns(2)
    cols[0].metric("Total PnL", f"{overview['total_pnl']:+.2f}")
    cols[1].metric("Avg Trade PnL", f"{overview['avg_trade_pnl']:+.4f}")

    st.subheader("Recent Trades")
    if overview["recent_trades"]:
        st.dataframe(overview["recent_trades"], use_container_width=True)
    else:
        st.info("No trades recorded yet.")
