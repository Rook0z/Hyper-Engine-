"""
Tests for execution/testnet_executor.py — safety guards and execution
logic only. No real network calls: HyperliquidClient/auth are stubbed,
and TestnetExecutor's own .trading / .account / .market are replaced
with MagicMocks after construction so tests control exactly what the
"exchange" returns.
"""

from unittest.mock import MagicMock

import pytest

from core.config import settings
from execution.testnet_executor import (
    TestnetExecutionError,
    TestnetExecutor,
    TestnetSafetyError,
)
from hyperliquid.client import TESTNET_URL, MAINNET_URL


# ──────────────────────────────────────────────────────────────
# FIXTURES / HELPERS
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def safe_settings(monkeypatch):
    """Puts the global settings singleton into a state where
    TestnetExecutor is allowed to construct."""
    monkeypatch.setattr(settings, "is_mainnet", False)
    monkeypatch.setattr(settings, "enable_testnet_live_execution", True)
    monkeypatch.setattr(settings, "execution_poll_interval_seconds", 0.0)
    monkeypatch.setattr(settings, "execution_poll_timeout_seconds", 0.05)
    yield settings


def make_client(base_url: str = TESTNET_URL) -> MagicMock:
    client = MagicMock()
    client.base_url = base_url
    client.auth = MagicMock()
    client.auth.account_address = "0xTestAccount"
    return client


def make_executor(safe_settings, base_url: str = TESTNET_URL) -> TestnetExecutor:
    """Builds a TestnetExecutor with all three sub-clients mocked."""
    client = make_client(base_url)
    executor = TestnetExecutor(client=client, symbol_map=MagicMock(), symbol="BTC")
    executor.trading = MagicMock()
    executor.account = MagicMock()
    executor.market = MagicMock()
    return executor


# ──────────────────────────────────────────────────────────────
# SAFETY GUARDS (construction)
# ──────────────────────────────────────────────────────────────


def test_construction_succeeds_when_all_guards_pass(safe_settings):
    executor = make_executor(safe_settings)
    assert executor.symbol == "BTC"


def test_refuses_when_mainnet_true(safe_settings, monkeypatch):
    monkeypatch.setattr(settings, "is_mainnet", True)
    with pytest.raises(TestnetSafetyError, match="IS_MAINNET"):
        TestnetExecutor(client=make_client(), symbol_map=MagicMock())


def test_refuses_when_base_url_is_not_testnet(safe_settings):
    with pytest.raises(TestnetSafetyError, match="testnet endpoint"):
        TestnetExecutor(client=make_client(MAINNET_URL), symbol_map=MagicMock())


def test_refuses_when_base_url_is_some_other_url(safe_settings):
    with pytest.raises(TestnetSafetyError, match="testnet endpoint"):
        TestnetExecutor(
            client=make_client("https://example.com"), symbol_map=MagicMock()
        )


def test_refuses_when_live_execution_flag_disabled(safe_settings, monkeypatch):
    monkeypatch.setattr(settings, "enable_testnet_live_execution", False)
    with pytest.raises(TestnetSafetyError, match="ENABLE_TESTNET_LIVE_EXECUTION"):
        TestnetExecutor(client=make_client(), symbol_map=MagicMock())


def test_refuses_when_client_has_no_auth(safe_settings):
    client = make_client()
    client.auth = None
    with pytest.raises(TestnetSafetyError, match="no auth"):
        TestnetExecutor(client=client, symbol_map=MagicMock())


def test_live_execution_flag_default_is_false(monkeypatch):
    """The flag itself must default to False — this is the real
    project default, not a test-isolated value. Must strip both the
    .env file AND actual OS environment variables — Settings(_env_file=
    None) only skips the file, not env vars a real shell may have set
    (e.g. while running the testnet smoke test)."""
    from core.config import Settings

    monkeypatch.delenv("ENABLE_TESTNET_LIVE_EXECUTION", raising=False)
    monkeypatch.delenv("enable_testnet_live_execution", raising=False)
    assert Settings(_env_file=None).enable_testnet_live_execution is False


# ──────────────────────────────────────────────────────────────
# ORDER SUBMISSION
# ──────────────────────────────────────────────────────────────


def test_submit_market_order_extracts_oid_from_filled_response(safe_settings):
    executor = make_executor(safe_settings)
    executor.trading.place_market_order.return_value = {
        "response": {"data": {"statuses": [{"filled": {"oid": 555}}]}}
    }
    oid = executor.submit_market_order(is_buy=True, size=0.001)
    assert oid == 555


def test_submit_market_order_extracts_oid_from_resting_response(safe_settings):
    executor = make_executor(safe_settings)
    executor.trading.place_market_order.return_value = {
        "response": {"data": {"statuses": [{"resting": {"oid": 777}}]}}
    }
    oid = executor.submit_market_order(is_buy=False, size=0.001)
    assert oid == 777


def test_submit_market_order_raises_on_missing_oid(safe_settings):
    executor = make_executor(safe_settings)
    executor.trading.place_market_order.return_value = {"status": "err"}
    with pytest.raises(TestnetExecutionError, match="not accepted"):
        executor.submit_market_order(is_buy=True, size=0.001)


def test_submit_market_order_never_exceeds_configured_size(safe_settings):
    """Regression guard: the exact size passed is what gets sent — no
    silent scaling up."""
    executor = make_executor(safe_settings)
    executor.trading.place_market_order.return_value = {
        "response": {"data": {"statuses": [{"filled": {"oid": 1}}]}}
    }
    executor.submit_market_order(is_buy=True, size=0.001)
    _, kwargs = executor.trading.place_market_order.call_args
    assert kwargs["size"] == "0.001"


# ──────────────────────────────────────────────────────────────
# WAIT FOR FILL
# ──────────────────────────────────────────────────────────────


def test_wait_for_fill_returns_filled(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_order_status.return_value = {
        "order": {"sz": "0.001"},
        "status": "filled",
    }
    fill = MagicMock()
    fill.oid = 1
    fill.sz = "0.001"
    fill.px = "50000"
    executor.account.get_fills.return_value = [fill]

    result = executor.wait_for_fill(oid=1, side="BUY")
    assert result.status == "filled"
    assert result.filled_size == 0.001
    assert result.avg_price == 50000.0


def test_wait_for_fill_avg_price_is_volume_weighted_across_partial_fills(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_order_status.return_value = {
        "order": {"sz": "0.002"},
        "status": "filled",
    }
    fill_a = MagicMock(oid=1, sz="0.001", px="50000")
    fill_b = MagicMock(oid=1, sz="0.001", px="50100")
    executor.account.get_fills.return_value = [fill_a, fill_b]

    result = executor.wait_for_fill(oid=1, side="BUY")
    assert result.avg_price == pytest.approx(50050.0)


def test_wait_for_fill_avg_price_zero_when_no_matching_fill(safe_settings):
    """No matching fill record yet -> 0.0 (treated as 'unknown' by
    callers), not a crash."""
    executor = make_executor(safe_settings)
    executor.account.get_order_status.return_value = {
        "order": {"sz": "0.001"},
        "status": "filled",
    }
    executor.account.get_fills.return_value = []
    result = executor.wait_for_fill(oid=1, side="BUY")
    assert result.avg_price == 0.0


def test_wait_for_fill_returns_rejected(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_order_status.return_value = {"status": "rejected"}
    result = executor.wait_for_fill(oid=1, side="BUY")
    assert result.status == "rejected"


def test_wait_for_fill_times_out(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_order_status.return_value = {"status": "open"}
    result = executor.wait_for_fill(oid=1, side="BUY", poll_interval=0.0, timeout=0.01)
    assert result.status == "timeout"


# ──────────────────────────────────────────────────────────────
# ACCOUNT STATE
# ──────────────────────────────────────────────────────────────


def test_get_position_size_returns_zero_when_flat(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_positions.return_value = []
    assert executor.get_position_size() == 0.0


def test_get_position_size_finds_matching_symbol(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_positions.return_value = [
        {"coin": "ETH", "szi": "1.0"},
        {"coin": "BTC", "szi": "0.001"},
    ]
    assert executor.get_position_size() == 0.001


def test_has_open_orders_true_when_symbol_matches(safe_settings):
    executor = make_executor(safe_settings)
    order = MagicMock()
    order.coin = "BTC"
    executor.account.get_open_orders.return_value = [order]
    assert executor.has_open_orders() is True


def test_has_open_orders_false_when_no_match(safe_settings):
    executor = make_executor(safe_settings)
    order = MagicMock()
    order.coin = "ETH"
    executor.account.get_open_orders.return_value = [order]
    assert executor.has_open_orders() is False


# ──────────────────────────────────────────────────────────────
# FULL BUY -> SELL SMOKE CYCLE
# ──────────────────────────────────────────────────────────────


def _mock_filled_order_response(oid: int) -> dict:
    return {"response": {"data": {"statuses": [{"filled": {"oid": oid}}]}}}


def test_smoke_cycle_refuses_if_open_order_exists(safe_settings):
    executor = make_executor(safe_settings)
    order = MagicMock()
    order.coin = "BTC"
    executor.account.get_open_orders.return_value = [order]
    with pytest.raises(TestnetExecutionError, match="already exists"):
        executor.run_smoke_cycle(size=0.001)
    executor.trading.place_market_order.assert_not_called()


def test_smoke_cycle_does_not_submit_sell_if_buy_not_filled(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_open_orders.return_value = []
    executor.trading.place_market_order.return_value = _mock_filled_order_response(1)
    executor.account.get_order_status.return_value = {"status": "rejected"}

    buy_result, sell_result = executor.run_smoke_cycle(size=0.001)

    assert buy_result.status == "rejected"
    assert sell_result is None
    # Only the BUY should have been submitted — never a SELL.
    assert executor.trading.place_market_order.call_count == 1


def test_smoke_cycle_full_happy_path(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_open_orders.return_value = []
    executor.trading.place_market_order.side_effect = [
        _mock_filled_order_response(1),  # BUY
        _mock_filled_order_response(2),  # SELL
    ]
    executor.account.get_order_status.return_value = {
        "order": {"sz": "0.001"},
        "status": "filled",
    }
    executor.account.get_fills.return_value = [
        MagicMock(oid=1, sz="0.001", px="50000"),
        MagicMock(oid=2, sz="0.001", px="50100"),
    ]
    executor.account.get_positions.return_value = []  # flat after SELL

    buy_result, sell_result = executor.run_smoke_cycle(size=0.001)

    assert buy_result.status == "filled"
    assert buy_result.avg_price == 50000.0
    assert sell_result is not None
    assert sell_result.status == "filled"
    assert sell_result.avg_price == 50100.0
    assert executor.trading.place_market_order.call_count == 2


def test_smoke_cycle_sell_uses_actual_filled_qty_not_requested_size(safe_settings):
    """Regression guard: SELL must use the BUY's actual filled_size,
    not the originally requested size, if they differ (partial fill)."""
    executor = make_executor(safe_settings)
    executor.account.get_open_orders.return_value = []
    executor.trading.place_market_order.side_effect = [
        _mock_filled_order_response(1),
        _mock_filled_order_response(2),
    ]
    executor.account.get_order_status.side_effect = [
        {"order": {"sz": "0.0007"}, "status": "filled"},  # BUY partial
        {"order": {"sz": "0.0007"}, "status": "filled"},  # SELL
    ]
    executor.account.get_fills.return_value = []
    executor.account.get_positions.return_value = []

    executor.run_smoke_cycle(size=0.001)

    _, sell_kwargs = executor.trading.place_market_order.call_args_list[1]
    assert sell_kwargs["size"] == "0.0007"
