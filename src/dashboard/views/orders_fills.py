"""Orders and fills page: persisted historical order/fill records."""

from __future__ import annotations

import streamlit as st

from core.database import Database
from dashboard import data


def render(db: Database) -> None:
    st.header("Orders & Fills")
    st.caption(
        "Historical, persisted records only — this is not a live order-status "
        "feed. The dashboard never places, cancels, or modifies orders."
    )

    session_id = st.text_input("Session ID filter (optional)", value="") or None

    st.subheader("Orders")
    orders = data.list_orders_view(db, session_id=session_id)
    if orders:
        st.dataframe(orders, use_container_width=True)
    else:
        st.info("No orders recorded yet.")

    st.subheader("Fills")
    fills = data.list_fills_view(db, session_id=session_id)
    if fills:
        st.dataframe(fills, use_container_width=True)
    else:
        st.info("No fills recorded yet.")
