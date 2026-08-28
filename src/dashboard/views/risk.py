"""
Risk page: read-only display of configured risk limits and a derived,
informational "today's realized loss" figure. This page cannot modify
any risk setting, place any order, or change RiskManager's behavior in
any way — it only reads settings and persisted trade rows.
"""

from __future__ import annotations

import streamlit as st

from core.database import Database
from dashboard import data


def render(db: Database) -> None:
    st.header("Risk (Observation Only)")
    st.caption(
        "Read-only. This page displays configured risk limits and derived "
        "figures from persisted data — it cannot change any risk setting."
    )

    risk = data.get_risk_overview(db)

    st.subheader("Configured Limits")
    cols = st.columns(3)
    cols[0].metric("Max Position %", f"{risk['configured_max_position_pct']:.1%}")
    cols[1].metric("Max Daily Loss %", f"{risk['configured_max_daily_loss_pct']:.1%}")
    cols[2].metric("Max Open Positions", risk["configured_max_open_positions"])
    cols = st.columns(2)
    cols[0].metric("Configured Position Size", risk["configured_position_size"])
    cols[1].metric(
        "Max Daily Loss (USDC)", f"{risk['configured_max_daily_loss_usdc']:.2f}"
    )

    st.subheader("Today (derived from persisted trades)")
    cols = st.columns(2)
    cols[0].metric("Realized Loss Today", f"{risk['today_realized_loss_usdc']:.2f}")
    cols[1].metric("% of Daily Cap Used", f"{risk['today_loss_pct_of_cap']:.1%}")
