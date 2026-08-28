"""
Hyper-Engine read-only monitoring dashboard.

Run with:
    poetry install --with dashboard
    poetry run streamlit run src/dashboard/app.py

Reads from the SAME SQLite database the rest of Hyper-Engine writes to
(via core.database.Database — see Database.__init__'s db_path default,
"storage/hyper_engine.db") and displays it. This dashboard is STRICTLY
READ-ONLY: it never places, cancels, or modifies an order, never
touches TestnetExecutor/HyperliquidTrading/RiskManager, and never
writes to the database — every code path in dashboard/ only ever
calls Database's existing get_*/list_* methods.

See docs/dashboard.md for the full writeup.
"""

from __future__ import annotations

import sys
from pathlib import Path

# `streamlit run` executes this file as a standalone script, so it
# does NOT pick up pyproject.toml's [tool.pytest.ini_options]
# pythonpath = ["src"] setting (that only applies to pytest) — `src/`
# is never added to sys.path automatically the way it is for tests or
# mypy. Inserting it explicitly makes the documented single command
# (`streamlit run src/dashboard/app.py`) work regardless of the
# caller's working directory or environment, with no PYTHONPATH env
# var required.
#
# NOTE: this file is deliberately named app.py, NOT dashboard.py.
# Naming it dashboard.py (matching its own containing package,
# src/dashboard/) causes a classic Python footgun: when a script is
# run directly, Python auto-adds the SCRIPT'S OWN DIRECTORY
# (src/dashboard/) to sys.path — and if a file in that directory is
# also literally named "dashboard", `import dashboard` resolves
# self-referentially to that FILE (a plain module) instead of the
# PACKAGE one level up, breaking every `from dashboard.xxx import`
# statement with "dashboard is not a package" — regardless of what
# else is on sys.path. Renaming the entrypoint avoids this entire
# class of bug at the source, rather than working around it.
_SRC_DIR = str(Path(__file__).resolve().parent.parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import streamlit as st

from core.database import Database
from dashboard.views import (
    monte_carlo,
    orders_fills,
    overview,
    performance,
    risk,
    strategy_analysis,
    trades,
)

st.set_page_config(page_title="Hyper-Engine Dashboard", layout="wide")

PAGES = {
    "Overview": overview,
    "Trading History": trades,
    "Orders & Fills": orders_fills,
    "Performance": performance,
    "Strategy Analysis": strategy_analysis,
    "Monte Carlo": monte_carlo,
    "Risk": risk,
}


@st.cache_resource
def get_db() -> Database:
    # Uses Database's own default path ("storage/hyper_engine.db") —
    # the SAME file the persistence layer (core/database.py,
    # TradeLogger's optional `db` integration) writes to when enabled.
    # No dashboard-specific config was added; this stays in sync with
    # the persistence layer's own default automatically.
    return Database()


def main() -> None:
    st.sidebar.title("Hyper-Engine")
    st.sidebar.caption("Read-only monitoring dashboard")
    page_name = st.sidebar.radio("Navigate", list(PAGES.keys()))

    db = get_db()
    PAGES[page_name].render(db)


if __name__ == "__main__":
    main()
