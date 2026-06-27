from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

logger = logging.getLogger(__name__)


class LogEvent(str, Enum):
    """Event types logged by TradeLogger."""

    ORDER = "ORDER"
    FILL = "FILL"
    CANCEL = "CANCEL"
    SIGNAL = "SIGNAL"
    ERROR = "ERROR"
    SESSION = "SESSION"
    RISK = "RISK"


class TradeLogger:
    """
    Logs every trading event in structured JSON format (JSONL).

    One log entry per line. One file per day.
    All timestamps in UTC ISO 8601 format.

    Args:
        log_dir:     Directory to write log files. Created if not exists.
        symbol:      Asset being traded e.g. "BTC"
        strategy:    Strategy name e.g. "EMA Crossover 9/21"
        session_id:  Unique ID for this trading session (optional)

    Usage:
        tl = TradeLogger(log_dir="logs", symbol="BTC", strategy="EMA 9/21")
        tl.log_session_start(balance=10_000.0)
        tl.log_signal("BUY", fast_ema=50100.0, slow_ema=49900.0)
        tl.log_order(side="BUY", price=50000.0, size=0.001)
        tl.log_fill(side="BUY", price=50050.0, size=0.001, fee=0.05)
        tl.log_session_end(balance=10_050.0, total_pnl=50.0, num_trades=3)
    """

    def __init__(
        self,
        log_dir: str = "logs",
        symbol: str = "BTC",
        strategy: str = "unknown",
        session_id: str | None = None,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.symbol = symbol
        self.strategy = strategy
        self.session_id = session_id or self._generate_session_id()

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_date: str = ""
        self._file_handle: "TextIO | None" = None

        logger.info(
            "TradeLogger initialized: dir=%s symbol=%s strategy=%s session=%s",
            log_dir,
            symbol,
            strategy,
            self.session_id,
        )

    # ──────────────────────────────────────────────────────────────
    # PUBLIC LOGGING METHODS
    # ──────────────────────────────────────────────────────────────

    def log_session_start(
        self,
        balance: float,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Logs the start of a trading session."""
        self._write(
            LogEvent.SESSION,
            {
                "action": "START",
                "balance": balance,
                "symbol": self.symbol,
                "strategy": self.strategy,
                **(extra or {}),
            },
        )

    def log_session_end(
        self,
        balance: float,
        total_pnl: float,
        num_trades: int,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Logs the end of a trading session with summary stats."""
        self._write(
            LogEvent.SESSION,
            {
                "action": "END",
                "balance": balance,
                "total_pnl": total_pnl,
                "num_trades": num_trades,
                "symbol": self.symbol,
                "strategy": self.strategy,
                **(extra or {}),
            },
        )

    def log_signal(
        self,
        signal: str,
        price: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """
        Logs a strategy signal (BUY, SELL, HOLD).

        Args:
            signal: "BUY", "SELL", or "HOLD"
            price:  current market price when signal fired
            extra:  any additional context (e.g. fast_ema, slow_ema values)
        """
        self._write(
            LogEvent.SIGNAL,
            {
                "signal": signal,
                "symbol": self.symbol,
                "strategy": self.strategy,
                "price": price,
                **(extra or {}),
            },
        )

    def log_order(
        self,
        side: str,
        price: float,
        size: float,
        order_type: str = "LIMIT",
        cloid: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """
        Logs an order being sent to the exchange.

        Args:
            side:       "BUY" or "SELL"
            price:      order price
            size:       order size in base currency
            order_type: "LIMIT", "MARKET", etc.
            cloid:      client order ID if set
        """
        self._write(
            LogEvent.ORDER,
            {
                "side": side,
                "price": price,
                "size": size,
                "order_type": order_type,
                "symbol": self.symbol,
                "cloid": cloid,
                "value_usdc": round(price * size, 4),
                **(extra or {}),
            },
        )

    def log_fill(
        self,
        side: str,
        price: float,
        size: float,
        fee: float = 0.0,
        oid: int | None = None,
        cloid: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """
        Logs a confirmed order fill from the exchange.

        Args:
            side:   "BUY" or "SELL"
            price:  fill price
            size:   filled size in base currency
            fee:    fee paid in USDC (negative = rebate received)
            oid:    exchange order ID
            cloid:  client order ID
        """
        self._write(
            LogEvent.FILL,
            {
                "side": side,
                "price": price,
                "size": size,
                "fee": fee,
                "oid": oid,
                "cloid": cloid,
                "symbol": self.symbol,
                "value_usdc": round(price * size, 4),
                **(extra or {}),
            },
        )

    def log_trade_closed(
        self,
        side: str,
        entry_price: float,
        exit_price: float,
        size: float,
        pnl: float,
        pnl_pct: float,
        entry_time: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """
        Logs a completed round-trip trade (entry + exit).

        Args:
            side:        direction of the trade ("LONG" or "SHORT")
            entry_price: price at which position was opened
            exit_price:  price at which position was closed
            size:        position size in base currency
            pnl:         profit or loss in USDC
            pnl_pct:     profit or loss as percentage
            entry_time:  ISO timestamp of entry (optional)
        """
        self._write(
            LogEvent.FILL,
            {
                "action": "TRADE_CLOSED",
                "side": side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "size": size,
                "pnl": round(pnl, 4),
                "pnl_pct": round(pnl_pct * 100, 4),
                "symbol": self.symbol,
                "entry_time": entry_time,
                **(extra or {}),
            },
        )

    def log_cancel(
        self,
        oid: int | None = None,
        cloid: str | None = None,
        reason: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Logs an order cancellation."""
        self._write(
            LogEvent.CANCEL,
            {
                "oid": oid,
                "cloid": cloid,
                "symbol": self.symbol,
                "reason": reason,
                **(extra or {}),
            },
        )

    def log_risk_block(
        self,
        reason: str,
        requested_size: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Logs when a trade is blocked by the risk manager."""
        self._write(
            LogEvent.RISK,
            {
                "action": "BLOCKED",
                "reason": reason,
                "symbol": self.symbol,
                "requested_size": requested_size,
                **(extra or {}),
            },
        )

    def log_error(
        self,
        error: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Logs an error that occurred during trading.

        Args:
            error:   error message or exception string
            context: any additional context to help debugging
        """
        self._write(
            LogEvent.ERROR,
            {
                "error": error,
                "symbol": self.symbol,
                "strategy": self.strategy,
                **(context or {}),
            },
        )

    # ──────────────────────────────────────────────────────────────
    # LOG READING
    # ──────────────────────────────────────────────────────────────

    def load_today(self) -> list[dict[str, Any]]:
        """
        Loads all log entries from today's log file.

        Returns:
            List of log entry dicts, oldest first.
            Empty list if no log file exists for today.
        """
        path = self._get_log_path()
        if not path.exists():
            return []
        return self._load_file(path)

    def load_file(self, date: str) -> list[dict[str, Any]]:
        """
        Loads all log entries from a specific date's log file.

        Args:
            date: date string in YYYY-MM-DD format e.g. "2025-06-15"

        Returns:
            List of log entry dicts.
        """
        path = self.log_dir / f"trades_{date}.jsonl"
        if not path.exists():
            logger.warning("No log file found for date: %s", date)
            return []
        return self._load_file(path)

    def filter_by_event(
        self,
        entries: list[dict[str, Any]],
        event: LogEvent,
    ) -> list[dict[str, Any]]:
        """Filters log entries by event type."""
        return [e for e in entries if e.get("event") == event.value]

    def calculate_session_pnl(
        self,
        entries: list[dict[str, Any]],
    ) -> float:
        """
        Calculates total PnL from TRADE_CLOSED entries in a log file.

        Args:
            entries: list of log entries from load_today() or load_file()

        Returns:
            Total PnL in USDC.
        """
        fills = self.filter_by_event(entries, LogEvent.FILL)
        closed = [e for e in fills if e.get("action") == "TRADE_CLOSED"]
        return sum(e.get("pnl", 0.0) for e in closed)

    # ──────────────────────────────────────────────────────────────
    # PRIVATE METHODS
    # ──────────────────────────────────────────────────────────────

    def _write(self, event: LogEvent, data: dict[str, Any]) -> None:
        """
        Writes one JSON log entry to the current day's file.
        Rotates to a new file if the date has changed.
        """
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        # Rotate file if date changed
        if today != self._current_date:
            self._rotate(today)

        entry = {
            "timestamp": now.isoformat(),
            "event": event.value,
            "session_id": self.session_id,
            **data,
        }

        try:
            line = json.dumps(entry, default=str) + "\n"
            if self._file_handle is None:
                logger.error("Log file handle is None — entry dropped: %s", entry)
                return
            self._file_handle.write(line)
            self._file_handle.flush()
        except Exception as e:
            logger.error("Failed to write log entry: %s", e)

    def _rotate(self, new_date: str) -> None:
        """Opens a new log file for the given date."""
        if self._file_handle is not None:
            try:
                self._file_handle.close()
            except Exception:
                pass

        self._current_date = new_date
        path = self._get_log_path()
        self._file_handle = open(path, "a", encoding="utf-8")
        logger.info("Log file rotated: %s", path)

    def _get_log_path(self) -> Path:
        """Returns the path for the current date's log file."""
        date = self._current_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.log_dir / f"trades_{date}.jsonl"

    def _load_file(self, path: Path) -> list[dict[str, Any]]:
        """Loads a JSONL file and returns list of parsed dicts."""
        entries = []
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Skipping malformed line %d in %s: %s", i + 1, path, e
                    )
        return entries

    def _generate_session_id(self) -> str:
        """Generates a unique session ID from current UTC timestamp."""
        return datetime.now(timezone.utc).strftime("session_%Y%m%d_%H%M%S")

    def __del__(self) -> None:
        """Close file handle on cleanup."""
        if self._file_handle is not None:
            try:
                self._file_handle.close()
            except Exception:
                pass
