"""Monte Carlo page: stored simulation percentile/probability summaries."""

from __future__ import annotations

import streamlit as st

from core.database import Database
from dashboard import data


def render(db: Database) -> None:
    st.header("Monte Carlo Simulation")
    st.caption(
        "Displays persisted Monte Carlo results. Every statistic below "
        "was computed by MonteCarloReport at simulation time and is read "
        "directly from the stored result — nothing here is recalculated."
    )

    results = data.list_analysis_results_view(db, result_type="monte_carlo", limit=50)
    if not results:
        st.info("No Monte Carlo results persisted yet.")
        return

    labels = [
        f"#{r['id']} — {r['strategy_name']} / {r['symbol']} — {r['created_at']}"
        for r in results
    ]
    selected = st.selectbox("Result", labels)
    selected_id = results[labels.index(selected)]["id"]

    summary = data.get_monte_carlo_summary(db, selected_id)
    if summary is None:
        st.error("Result not found.")
        return

    st.subheader(f"{summary['method'].title()} — {summary['num_simulations']} simulations")

    cols = st.columns(3)
    cols[0].metric("Original Final Equity", f"{summary['original_final_equity']:.2f}")
    cols[1].metric("Original Max Drawdown", f"{summary['original_max_drawdown']:.1%}")
    cols[2].metric("Probability of Loss", f"{summary['probability_of_loss']:.1%}")

    st.subheader("Simulated Final Equity")
    cols = st.columns(4)
    cols[0].metric("5th pct", f"{summary['final_equity_p5']:.2f}")
    cols[1].metric("Median", f"{summary['final_equity_median']:.2f}")
    cols[2].metric("95th pct", f"{summary['final_equity_p95']:.2f}")
    cols[3].metric("Mean", f"{summary['final_equity_mean']:.2f}")
    cols = st.columns(2)
    cols[0].metric("Worst", f"{summary['final_equity_worst']:.2f}")
    cols[1].metric("Best", f"{summary['final_equity_best']:.2f}")

    st.subheader("Simulated Max Drawdown")
    cols = st.columns(2)
    cols[0].metric("Median", f"{summary['median_max_drawdown']:.1%}")
    cols[1].metric("Worst", f"{summary['worst_max_drawdown']:.1%}")
