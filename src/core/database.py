from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    starting_balance REAL,
    ending_balance REAL,
    total_pnl REAL,
    num_trades INTEGER
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    order_type TEXT,
    oid INTEGER,
    cloid TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    fee REAL DEFAULT 0.0,
    oid INTEGER,
    cloid TEXT,
    filled_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    size REAL NOT NULL,
    pnl REAL NOT NULL,
    pnl_pct REAL NOT NULL,
    entry_time TEXT,
    exit_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_type TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    created_at TEXT NOT NULL,
    summary_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_session ON orders(session_id);
CREATE INDEX IF NOT EXISTS idx_fills_session ON fills(session_id);
CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_analysis_type ON analysis_results(result_type);
CREATE INDEX IF NOT EXISTS idx_analysis_strategy ON analysis_results(strategy_name);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(obj: Any) -> Any:
    """
    Recursively converts dataclasses (including nested ones, e.g.
    OutOfSampleReport containing BacktestResult/PerformanceReport) to
    plain dicts/lists for JSON storage. Falls through to json.dumps'
    own default=str handling for anything else it doesn't recognize.
    """
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    return obj


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _require_lastrowid(cur: sqlite3.Cursor) -> int:
    """
    sqlite3.Cursor.lastrowid is typed as int | None (it's None for
    cursors that never executed an INSERT) — for every INSERT in this
    module it's always a real int immediately after execute(), but
    that fact isn't visible to mypy from the stub alone. This narrows
    it explicitly with a clear error instead of an int(None) TypeError
    if that assumption is ever wrong.
    """
    if cur.lastrowid is None:
        raise RuntimeError("INSERT did not return a row id (lastrowid is None).")
    return cur.lastrowid


class Database:
    """
    SQLite-backed persistence for Hyper-Engine. One file, safe for
    single-process concurrent use (guarded by an internal lock — this
    is an embedded local database, not a multi-writer server).

    Usage:
        db = Database()  # defaults to storage/hyper_engine.db
        db.save_session_start(session_id="s1", symbol="BTC", strategy="EMA(9,21)", mode="paper", starting_balance=10_000.0)
        db.save_fill(session_id="s1", symbol="BTC", side="BUY", price=50000.0, size=0.001)
        db.save_backtest_result("EMA(9,21)", "BTC", result, report)
        db.list_trades(symbol="BTC", limit=20)
    """

    def __init__(self, db_path: str = "storage/hyper_engine.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
        logger.info("Database initialized at %s", self.db_path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ──────────────────────────────────────────────────────────────
    # SESSIONS
    # ──────────────────────────────────────────────────────────────

    def save_session_start(
        self,
        session_id: str,
        symbol: str,
        strategy: str,
        mode: str,
        starting_balance: float,
    ) -> None:
        """
        Inserts a new session row, or is a no-op if session_id already
        exists (INSERT OR IGNORE) — safe to call defensively without
        needing to check existence first.
        """
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO sessions
                    (session_id, symbol, strategy, mode, started_at, starting_balance)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, symbol, strategy, mode, _now_iso(), starting_balance),
            )

    def save_session_end(
        self,
        session_id: str,
        ending_balance: float,
        total_pnl: float,
        num_trades: int,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE sessions
                SET ended_at = ?, ending_balance = ?, total_pnl = ?, num_trades = ?
                WHERE session_id = ?
                """,
                (_now_iso(), ending_balance, total_pnl, num_trades, session_id),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return _row_to_dict(row)

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────────────────────────────────────────────────
    # ORDERS / FILLS / TRADES
    # ──────────────────────────────────────────────────────────────

    def save_order(
        self,
        session_id: str,
        symbol: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "MARKET",
        oid: int | None = None,
        cloid: str | None = None,
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO orders
                    (session_id, symbol, side, price, size, order_type, oid, cloid, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    symbol,
                    side,
                    price,
                    size,
                    order_type,
                    oid,
                    cloid,
                    _now_iso(),
                ),
            )
            return _require_lastrowid(cur)

    def save_fill(
        self,
        session_id: str,
        symbol: str,
        side: str,
        price: float,
        size: float,
        fee: float = 0.0,
        oid: int | None = None,
        cloid: str | None = None,
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO fills
                    (session_id, symbol, side, price, size, fee, oid, cloid, filled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, symbol, side, price, size, fee, oid, cloid, _now_iso()),
            )
            return _require_lastrowid(cur)

    def save_trade(
        self,
        session_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        size: float,
        pnl: float,
        pnl_pct: float,
        entry_time: str | None = None,
        exit_time: str | None = None,
    ) -> int:
        """Persists one completed round-trip trade (entry + exit)."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO trades
                    (session_id, symbol, side, entry_price, exit_price, size,
                     pnl, pnl_pct, entry_time, exit_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    symbol,
                    side,
                    entry_price,
                    exit_price,
                    size,
                    pnl,
                    pnl_pct,
                    entry_time,
                    exit_time or _now_iso(),
                ),
            )
            return _require_lastrowid(cur)

    def list_orders(
        self, session_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._list("orders", "created_at", session_id=session_id, limit=limit)

    def list_fills(
        self, session_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._list("fills", "filled_at", session_id=session_id, limit=limit)

    def list_trades(
        self,
        session_id: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM trades {where} ORDER BY exit_time DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def _list(
        self,
        table: str,
        order_col: str,
        session_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if session_id is not None:
            query = f"SELECT * FROM {table} WHERE session_id = ? ORDER BY {order_col} DESC LIMIT ?"
            params: tuple = (session_id, limit)
        else:
            query = f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT ?"
            params = (limit,)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────────────────────────────────────────────────
    # ANALYSIS RESULTS (backtest / OOS / walk-forward / Monte Carlo)
    # ──────────────────────────────────────────────────────────────

    def save_analysis_result(
        self,
        result_type: str,
        strategy_name: str,
        symbol: str,
        result: Any,
    ) -> int:
        """
        Persists any analysis result as JSON. Accepts a dataclass (or
        nested dataclasses — recursively serialized), a plain dict, or
        anything else json.dumps can handle with default=str.

        Args:
            result_type: e.g. "backtest", "out_of_sample",
                         "walk_forward", "monte_carlo" — free-form, but
                         keep it consistent for querying via
                         list_analysis_results(result_type=...).
            strategy_name: e.g. "EMA(9,21)".
            symbol: e.g. "BTC".
            result: the object to persist.

        Returns:
            The new row's id.
        """
        summary_json = json.dumps(_serialize(result), default=str)
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO analysis_results
                    (result_type, strategy_name, symbol, created_at, summary_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (result_type, strategy_name, symbol, _now_iso(), summary_json),
            )
            return _require_lastrowid(cur)

    def get_analysis_result(self, result_id: int) -> dict[str, Any] | None:
        """Returns the row plus `summary` (the parsed JSON dict), or
        None if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM analysis_results WHERE id = ?", (result_id,)
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["summary"] = json.loads(data["summary_json"])
        return data

    def list_analysis_results(
        self,
        result_type: str | None = None,
        strategy_name: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Lists analysis results (metadata only — summary_json is NOT
        parsed here, for speed when listing many rows; use
        get_analysis_result(id) for the full parsed summary).
        """
        clauses = []
        params: list[Any] = []
        if result_type is not None:
            clauses.append("result_type = ?")
            params.append(result_type)
        if strategy_name is not None:
            clauses.append("strategy_name = ?")
            params.append(strategy_name)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, result_type, strategy_name, symbol, created_at "
                f"FROM analysis_results {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Typed convenience wrappers (thin, mypy-checked call sites) ──

    def save_backtest_result(
        self, strategy_name: str, symbol: str, result: Any, report: Any
    ) -> int:
        """Persists a Backtester.run() result + its PerformanceReport together."""
        return self.save_analysis_result(
            "backtest",
            strategy_name,
            symbol,
            {"result": result, "report": report},
        )

    def save_out_of_sample_result(self, symbol: str, oos_report: Any) -> int:
        """Persists an OutOfSampleReport (from run_out_of_sample_test())."""
        return self.save_analysis_result(
            "out_of_sample", oos_report.strategy_name, symbol, oos_report
        )

    def save_walk_forward_result(
        self, strategy_name: str, symbol: str, wf_report: Any
    ) -> int:
        """Persists a WalkForwardReport (from run_walk_forward_test())."""
        return self.save_analysis_result(
            "walk_forward", strategy_name, symbol, wf_report
        )

    def save_monte_carlo_result(
        self, strategy_name: str, symbol: str, mc_report: Any
    ) -> int:
        """Persists a MonteCarloReport (from run_monte_carlo_simulation())."""
        return self.save_analysis_result(
            "monte_carlo", strategy_name, symbol, mc_report
        )
