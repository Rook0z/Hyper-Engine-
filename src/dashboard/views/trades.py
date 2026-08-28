"""Trading history page: persisted completed trades, with filtering."""

from __future__ import annotations

import streamlit as st

from core.database import Database
from dashboard import data


def render(db: Database) -> None:
    st.header("Trading History")
    st.caption("Persisted completed (entry + exit) trades.")

    col1, col2, col3 = st.columns(3)
    symbol = col1.text_input("Symbol filter (e.g. BTC)", value="") or None
    side = col2.text_input("Side filter (e.g. LONG)", value="") or None
    session_id = col3.text_input("Session ID filter", value="") or None

    col4, col5 = st.columns(2)
    start_time = col4.text_input("Start time (ISO, e.g. 2026-01-01)", value="") or None
    end_time = col5.text_input("End time (ISO, e.g. 2026-01-31)", value="") or None

    trades = data.list_trades_view(
        db,
        symbol=symbol,
        side=side,
        session_id=session_id,
        start_time=start_time,
        end_time=end_time,
    )

    st.caption(f"{len(trades)} trade(s) matching filters")
    if trades:
        st.dataframe(trades, use_container_width=True)
    else:
        st.info("No trades match the current filters.")
