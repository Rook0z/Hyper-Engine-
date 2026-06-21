import json
import os
import tempfile
import pytest
from pathlib import Path
from core.trade_logger import TradeLogger, LogEvent


# ──────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_log_dir(tmp_path):
    """Temporary directory for log files — cleaned up after each test."""
    return str(tmp_path / "logs")


@pytest.fixture
def tl(tmp_log_dir):
    """TradeLogger instance using a temp directory."""
    return TradeLogger(
        log_dir=tmp_log_dir,
        symbol="BTC",
        strategy="EMA Crossover 9/21",
        session_id="test_session_001",
    )


def load_logs(tl: TradeLogger) -> list[dict]:
    """Helper — loads all entries from today's log."""
    return tl.load_today()


# ──────────────────────────────────────────────────────────────
# INIT
# ──────────────────────────────────────────────────────────────


def test_creates_log_directory(tmp_log_dir):
    tl = TradeLogger(log_dir=tmp_log_dir, symbol="BTC")
    assert Path(tmp_log_dir).exists()


def test_session_id_stored(tl):
    assert tl.session_id == "test_session_001"


def test_session_id_auto_generated(tmp_log_dir):
    tl = TradeLogger(log_dir=tmp_log_dir)
    assert tl.session_id.startswith("session_")


def test_symbol_stored(tl):
    assert tl.symbol == "BTC"


def test_strategy_stored(tl):
    assert tl.strategy == "EMA Crossover 9/21"


# ──────────────────────────────────────────────────────────────
# LOG ENTRY STRUCTURE
# ──────────────────────────────────────────────────────────────


def test_every_entry_has_timestamp(tl):
    tl.log_signal("BUY", price=50_000.0)
    entries = load_logs(tl)
    assert "timestamp" in entries[0]


def test_every_entry_has_event(tl):
    tl.log_signal("BUY", price=50_000.0)
    entries = load_logs(tl)
    assert "event" in entries[0]


def test_every_entry_has_session_id(tl):
    tl.log_signal("HOLD", price=50_000.0)
    entries = load_logs(tl)
    assert entries[0]["session_id"] == "test_session_001"


def test_entries_are_valid_json(tl):
    tl.log_signal("BUY", price=50_000.0)
    tl.log_order("BUY", price=50_000.0, size=0.001)
    entries = load_logs(tl)
    assert len(entries) == 2
    for e in entries:
        assert isinstance(e, dict)


# ──────────────────────────────────────────────────────────────
# LOG SESSION
# ──────────────────────────────────────────────────────────────


def test_log_session_start(tl):
    tl.log_session_start(balance=10_000.0)
    entries = load_logs(tl)
    e = entries[0]
    assert e["event"] == LogEvent.SESSION.value
    assert e["action"] == "START"
    assert e["balance"] == 10_000.0


def test_log_session_end(tl):
    tl.log_session_end(balance=10_500.0, total_pnl=500.0, num_trades=3)
    entries = load_logs(tl)
    e = entries[0]
    assert e["event"] == LogEvent.SESSION.value
    assert e["action"] == "END"
    assert e["total_pnl"] == 500.0
    assert e["num_trades"] == 3


# ──────────────────────────────────────────────────────────────
# LOG SIGNAL
# ──────────────────────────────────────────────────────────────


def test_log_signal_buy(tl):
    tl.log_signal("BUY", price=50_000.0)
    entries = load_logs(tl)
    e = entries[0]
    assert e["event"] == LogEvent.SIGNAL.value
    assert e["signal"] == "BUY"
    assert e["price"] == 50_000.0


def test_log_signal_with_extra(tl):
    tl.log_signal(
        "BUY", price=50_000.0, extra={"fast_ema": 50100.0, "slow_ema": 49900.0}
    )
    entries = load_logs(tl)
    e = entries[0]
    assert e["fast_ema"] == 50100.0
    assert e["slow_ema"] == 49900.0


def test_log_signal_hold(tl):
    tl.log_signal("HOLD", price=50_000.0)
    entries = load_logs(tl)
    assert entries[0]["signal"] == "HOLD"


# ──────────────────────────────────────────────────────────────
# LOG ORDER
# ──────────────────────────────────────────────────────────────


def test_log_order_fields(tl):
    tl.log_order("BUY", price=50_000.0, size=0.001)
    entries = load_logs(tl)
    e = entries[0]
    assert e["event"] == LogEvent.ORDER.value
    assert e["side"] == "BUY"
    assert e["price"] == 50_000.0
    assert e["size"] == 0.001
    assert e["symbol"] == "BTC"


def test_log_order_calculates_value(tl):
    tl.log_order("BUY", price=50_000.0, size=0.002)
    entries = load_logs(tl)
    assert entries[0]["value_usdc"] == 100.0


def test_log_order_with_cloid(tl):
    tl.log_order(
        "BUY", price=50_000.0, size=0.001, cloid="0x1234567890abcdef1234567890abcdef"
    )
    entries = load_logs(tl)
    assert entries[0]["cloid"] == "0x1234567890abcdef1234567890abcdef"


def test_log_order_type(tl):
    tl.log_order("SELL", price=50_000.0, size=0.001, order_type="MARKET")
    entries = load_logs(tl)
    assert entries[0]["order_type"] == "MARKET"


# ──────────────────────────────────────────────────────────────
# LOG FILL
# ──────────────────────────────────────────────────────────────


def test_log_fill_fields(tl):
    tl.log_fill("BUY", price=50_050.0, size=0.001, fee=0.05, oid=12345)
    entries = load_logs(tl)
    e = entries[0]
    assert e["event"] == LogEvent.FILL.value
    assert e["side"] == "BUY"
    assert e["price"] == 50_050.0
    assert e["fee"] == 0.05
    assert e["oid"] == 12345


def test_log_fill_value(tl):
    tl.log_fill("BUY", price=50_000.0, size=0.002)
    entries = load_logs(tl)
    assert entries[0]["value_usdc"] == 100.0


# ──────────────────────────────────────────────────────────────
# LOG TRADE CLOSED
# ──────────────────────────────────────────────────────────────


def test_log_trade_closed(tl):
    tl.log_trade_closed(
        side="LONG",
        entry_price=50_000.0,
        exit_price=51_000.0,
        size=0.001,
        pnl=1.0,
        pnl_pct=0.02,
    )
    entries = load_logs(tl)
    e = entries[0]
    assert e["action"] == "TRADE_CLOSED"
    assert e["pnl"] == 1.0
    assert e["entry_price"] == 50_000.0
    assert e["exit_price"] == 51_000.0


def test_log_trade_closed_pnl_pct_converted(tl):
    tl.log_trade_closed("LONG", 100.0, 102.0, 1.0, pnl=2.0, pnl_pct=0.02)
    entries = load_logs(tl)
    # pnl_pct stored as percentage (2.0) not fraction (0.02)
    assert entries[0]["pnl_pct"] == 2.0


# ──────────────────────────────────────────────────────────────
# LOG CANCEL
# ──────────────────────────────────────────────────────────────


def test_log_cancel(tl):
    tl.log_cancel(oid=12345, reason="Stale order")
    entries = load_logs(tl)
    e = entries[0]
    assert e["event"] == LogEvent.CANCEL.value
    assert e["oid"] == 12345
    assert e["reason"] == "Stale order"


# ──────────────────────────────────────────────────────────────
# LOG RISK BLOCK
# ──────────────────────────────────────────────────────────────


def test_log_risk_block(tl):
    tl.log_risk_block(reason="Daily loss limit breached", requested_size=0.01)
    entries = load_logs(tl)
    e = entries[0]
    assert e["event"] == LogEvent.RISK.value
    assert e["action"] == "BLOCKED"
    assert "Daily loss" in e["reason"]
    assert e["requested_size"] == 0.01


# ──────────────────────────────────────────────────────────────
# LOG ERROR
# ──────────────────────────────────────────────────────────────


def test_log_error(tl):
    tl.log_error("Connection timeout", context={"endpoint": "/exchange"})
    entries = load_logs(tl)
    e = entries[0]
    assert e["event"] == LogEvent.ERROR.value
    assert e["error"] == "Connection timeout"
    assert e["endpoint"] == "/exchange"


# ──────────────────────────────────────────────────────────────
# MULTIPLE ENTRIES
# ──────────────────────────────────────────────────────────────


def test_multiple_entries_in_order(tl):
    tl.log_session_start(balance=10_000.0)
    tl.log_signal("BUY", price=50_000.0)
    tl.log_order("BUY", price=50_000.0, size=0.001)
    tl.log_fill("BUY", price=50_050.0, size=0.001)
    entries = load_logs(tl)
    assert len(entries) == 4
    assert entries[0]["event"] == "SESSION"
    assert entries[1]["event"] == "SIGNAL"
    assert entries[2]["event"] == "ORDER"
    assert entries[3]["event"] == "FILL"


# ──────────────────────────────────────────────────────────────
# FILTER BY EVENT
# ──────────────────────────────────────────────────────────────


def test_filter_by_event(tl):
    tl.log_signal("BUY", price=50_000.0)
    tl.log_order("BUY", price=50_000.0, size=0.001)
    tl.log_signal("SELL", price=51_000.0)
    entries = load_logs(tl)
    signals = tl.filter_by_event(entries, LogEvent.SIGNAL)
    assert len(signals) == 2
    assert all(e["event"] == "SIGNAL" for e in signals)


# ──────────────────────────────────────────────────────────────
# CALCULATE SESSION PNL
# ──────────────────────────────────────────────────────────────


def test_calculate_session_pnl(tl):
    tl.log_trade_closed("LONG", 100.0, 110.0, 1.0, pnl=10.0, pnl_pct=0.1)
    tl.log_trade_closed("LONG", 110.0, 105.0, 1.0, pnl=-5.0, pnl_pct=-0.05)
    entries = load_logs(tl)
    total = tl.calculate_session_pnl(entries)
    assert total == 5.0


def test_calculate_session_pnl_no_trades(tl):
    tl.log_signal("HOLD", price=50_000.0)
    entries = load_logs(tl)
    assert tl.calculate_session_pnl(entries) == 0.0


# ──────────────────────────────────────────────────────────────
# LOAD FILE
# ──────────────────────────────────────────────────────────────


def test_load_today_empty_if_no_file(tmp_log_dir):
    tl = TradeLogger(log_dir=tmp_log_dir)
    # Force current date without writing anything
    from datetime import datetime, timezone

    tl._current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = tl.load_today()
    assert entries == []


def test_load_file_missing_date_returns_empty(tl):
    entries = tl.load_file("1999-01-01")
    assert entries == []


def test_log_file_is_jsonl(tl):
    """Each line in the log file must be valid JSON."""
    tl.log_signal("BUY", price=50_000.0)
    tl.log_order("BUY", price=50_000.0, size=0.001)

    path = tl._get_log_path()
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
