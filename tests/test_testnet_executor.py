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


def _order_status_response(status: str, order_fields: dict | None = None) -> dict:
    """
    Builds a REAL-shaped Hyperliquid orderStatus response — double
    nested, matching what account.get_order_status() actually returns:

        {"status": "order", "order": {"order": {...fields...},
         "status": <real status>, "statusTimestamp": ...}}

    Every test in this file must use this helper (or the equally-nested
    shape directly) rather than a flat {"status": ..., "order": {...}}
    guess — that flat shape was the actual bug this file regression-
    tests against.
    """
    return {
        "status": "order",
        "order": {
            "order": order_fields or {},
            "status": status,
            "statusTimestamp": 1234567890,
        },
    }


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
# _parse_order_status — FOCUSED FILL-STATUS PARSING TESTS
#
# Regression coverage for the real bug: a genuinely filled order was
# reported as "timeout" because the code read the WRONG "status" field
# (the top-level found/not-found indicator) instead of the real,
# double-nested per-order status.
# ──────────────────────────────────────────────────────────────


def test_parse_order_status_extracts_filled_from_real_shape(safe_settings):
    raw = _order_status_response("filled", {"sz": "0.001", "origSz": "0.001"})
    status, fields = TestnetExecutor._parse_order_status(raw)
    assert status == "filled"
    assert fields["sz"] == "0.001"


def test_parse_order_status_extracts_open(safe_settings):
    raw = _order_status_response("open", {"sz": "0.001"})
    status, _ = TestnetExecutor._parse_order_status(raw)
    assert status == "open"


def test_parse_order_status_extracts_rejected(safe_settings):
    raw = _order_status_response("rejected")
    status, _ = TestnetExecutor._parse_order_status(raw)
    assert status == "rejected"


def test_parse_order_status_top_level_status_is_never_mistaken_for_fill_status():
    """
    The exact bug this whole test block exists to catch: top-level
    "status" is "order" (found) or "unknownOid" (not found) — it must
    NEVER be read as if it were the fill status.
    """
    raw = _order_status_response("filled", {"sz": "0.001"})
    assert raw["status"] == "order"  # sanity check on the fixture itself
    status, _ = TestnetExecutor._parse_order_status(raw)
    assert status == "filled"  # must come from the NESTED status, not "order"


def test_parse_order_status_unknown_oid_returns_empty():
    raw = {"status": "unknownOid"}
    status, fields = TestnetExecutor._parse_order_status(raw)
    assert status == ""
    assert fields == {}


def test_parse_order_status_missing_order_key_returns_empty():
    raw = {"status": "order"}  # malformed/unexpected: no "order" key at all
    status, fields = TestnetExecutor._parse_order_status(raw)
    assert status == ""
    assert fields == {}


def test_parse_order_status_malformed_order_value_returns_empty():
    raw = {"status": "order", "order": "not-a-dict"}
    status, fields = TestnetExecutor._parse_order_status(raw)
    assert status == ""
    assert fields == {}


def test_parse_order_status_missing_inner_order_fields_defaults_empty_dict():
    raw = {"status": "order", "order": {"status": "filled", "statusTimestamp": 1}}
    status, fields = TestnetExecutor._parse_order_status(raw)
    assert status == "filled"
    assert fields == {}


def test_parse_order_status_handles_flat_shape():
    """
    Robustness: if the real response turns out to be flatter than
    documented (status and order as direct siblings, one level up from
    what was originally assumed), the recursive walk must still find
    it — this is exactly the kind of shape mismatch that caused the
    real reported bug (a genuinely filled order timing out).
    """
    raw = {"status": "filled", "order": {"sz": "0.001", "oid": 1}}
    status, fields = TestnetExecutor._parse_order_status(raw)
    assert status == "filled"
    assert fields["sz"] == "0.001"


def test_parse_order_status_handles_triple_nested_shape():
    """Robustness: one level deeper than the documented double-nesting
    must also still resolve correctly."""
    raw = {
        "status": "order",
        "order": {"data": {"order": {"sz": "0.001"}, "status": "filled"}},
    }
    status, fields = TestnetExecutor._parse_order_status(raw)
    assert status == "filled"
    assert fields["sz"] == "0.001"


def test_parse_order_status_wrapper_values_never_match_as_fill_status():
    """
    "order" and "unknownOid" are wrapper/found-indicator values, never
    real fill statuses — even the recursive walk must never treat a
    "status": "order" pair as a fill status just because it's shaped
    like one.
    """
    raw = {"status": "order", "order": {"status": "order", "order": {"sz": "1"}}}
    status, fields = TestnetExecutor._parse_order_status(raw)
    assert status == ""
    assert fields == {}


def test_parse_order_status_non_dict_input_returns_empty():
    status, fields = TestnetExecutor._parse_order_status("not a dict")  # type: ignore[arg-type]
    assert status == ""
    assert fields == {}


def test_parse_order_status_no_recognized_status_anywhere_returns_empty():
    raw = {"status": "order", "order": {"foo": "bar"}}
    status, fields = TestnetExecutor._parse_order_status(raw)
    assert status == ""
    assert fields == {}


# ──────────────────────────────────────────────────────────────
# _fill_totals_for_oid — AUTHORITATIVE FILL CONFIRMATION
#
# This is now the PRIMARY source wait_for_fill() relies on. Real
# Hyperliquid testnet has been observed returning
# {"status": "unknownOid"} from orderStatus for market/IOC orders that
# filled instantly and left the book — fills are the only reliable
# ground truth for whether an order actually executed.
# ──────────────────────────────────────────────────────────────


def test_fill_totals_for_oid_single_fill(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = [
        {"oid": 1, "sz": "0.001", "px": "50000", "side": "B", "coin": "BTC"}
    ]
    size, price = executor._fill_totals_for_oid(1)
    assert size == 0.001
    assert price == 50000.0


def test_fill_totals_for_oid_volume_weighted_across_partial_fills(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = [
        {"oid": 1, "sz": "0.001", "px": "50000"},
        {"oid": 1, "sz": "0.001", "px": "50100"},
    ]
    size, price = executor._fill_totals_for_oid(1)
    assert size == pytest.approx(0.002)
    assert price == pytest.approx(50050.0)


def test_fill_totals_for_oid_ignores_other_oids(safe_settings):
    """Must identify the SPECIFIC submitted order by oid — an
    unrelated fill for a different order must never count."""
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = [
        {"oid": 2, "sz": "0.005", "px": "60000"},
    ]
    size, price = executor._fill_totals_for_oid(1)
    assert (size, price) == (0.0, 0.0)


def test_fill_totals_for_oid_no_fills_returns_zero(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = []
    size, price = executor._fill_totals_for_oid(1)
    assert (size, price) == (0.0, 0.0)


def test_fill_totals_for_oid_lookup_failure_returns_zero(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.side_effect = RuntimeError("network error")
    size, price = executor._fill_totals_for_oid(1)
    assert (size, price) == (0.0, 0.0)


def test_fill_totals_for_oid_matches_across_string_int_oid_mismatch(safe_settings):
    """
    Regression guard for a real suspected failure mode: if the API
    returns "oid" as a JSON string while the submitted oid is a Python
    int (or vice versa), a strict == compare would silently never
    match. String-normalized comparison must still find it.
    """
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = [
        {"oid": "57627138319", "sz": "0.001", "px": "64891.0"}
    ]
    size, price = executor._fill_totals_for_oid(57627138319)
    assert size == pytest.approx(0.001)
    assert price == pytest.approx(64891.0)


def test_fill_totals_for_oid_non_list_response_returns_zero(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = {"unexpected": "shape"}
    size, price = executor._fill_totals_for_oid(1)
    assert (size, price) == (0.0, 0.0)


def test_fill_totals_for_oid_malformed_matched_fill_degrades_gracefully(safe_settings):
    """A matched fill missing sz/px must never crash — degrades to
    "not confirmed yet" rather than raising."""
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = [{"oid": 1, "side": "B"}]
    size, price = executor._fill_totals_for_oid(1)
    assert (size, price) == (0.0, 0.0)


# ──────────────────────────────────────────────────────────────
# WAIT FOR FILL
# ──────────────────────────────────────────────────────────────


def test_wait_for_fill_confirms_via_user_fills(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = [
        {"oid": 1, "sz": "0.001", "px": "50000"}
    ]
    executor.account.get_order_status.return_value = {"status": "unknownOid"}

    result = executor.wait_for_fill(oid=1, side="BUY")
    assert result.status == "filled"
    assert result.filled_size == 0.001
    assert result.avg_price == 50000.0


def test_wait_for_fill_confirms_via_fills_when_order_status_is_unknown_oid(
    safe_settings,
):
    """
    THE regression test for the real reported bug: a genuinely filled
    market/IOC order where orderStatus returns {"status": "unknownOid"}
    for its entire lifetime must still be confirmed filled via
    user_fills, and must NEVER be reported as timeout.
    """
    executor = make_executor(safe_settings)
    executor.account.get_order_status.return_value = {"status": "unknownOid"}
    executor.account.get_raw_fills.return_value = [
        {"oid": 1, "sz": "0.001", "px": "64891.0"}
    ]

    result = executor.wait_for_fill(oid=1, side="BUY", poll_interval=0.0, timeout=0.05)
    assert result.status == "filled"
    assert result.filled_size == 0.001


def test_wait_for_fill_avg_price_is_volume_weighted_across_partial_fills(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_order_status.return_value = {"status": "unknownOid"}
    executor.account.get_raw_fills.return_value = [
        {"oid": 1, "sz": "0.001", "px": "50000"},
        {"oid": 1, "sz": "0.001", "px": "50100"},
    ]

    result = executor.wait_for_fill(oid=1, side="BUY")
    assert result.avg_price == pytest.approx(50050.0)
    assert result.filled_size == pytest.approx(0.002)


def test_wait_for_fill_returns_rejected_via_order_status(safe_settings):
    """
    Rejected/canceled orders produce zero fills, so order_status is
    still the only source for this terminal-negative signal.
    """
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = []
    executor.account.get_order_status.return_value = _order_status_response("rejected")
    result = executor.wait_for_fill(oid=1, side="BUY")
    assert result.status == "rejected"


def test_wait_for_fill_times_out_when_no_fills_and_no_rejection(safe_settings):
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = []
    executor.account.get_order_status.return_value = {"status": "unknownOid"}
    result = executor.wait_for_fill(oid=1, side="BUY", poll_interval=0.0, timeout=0.01)
    assert result.status == "timeout"


def test_wait_for_fill_fills_check_takes_priority_over_order_status(safe_settings):
    """
    Regression guard: fills are checked FIRST and are authoritative —
    a genuine fill match must win even if order_status disagrees.
    """
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = [
        {"oid": 1, "sz": "0.001", "px": "50000"}
    ]
    executor.account.get_order_status.return_value = _order_status_response("open")
    result = executor.wait_for_fill(oid=1, side="BUY")
    assert result.status == "filled"


def test_wait_for_fill_only_reads_never_submits(safe_settings):
    """wait_for_fill() only ever reads state — regardless of how many
    times it polls or what order_status/fills return, it must never
    call place_market_order."""
    executor = make_executor(safe_settings)
    executor.account.get_raw_fills.return_value = []
    executor.account.get_order_status.return_value = {"status": "unknownOid"}
    executor.wait_for_fill(oid=1, side="BUY", poll_interval=0.0, timeout=0.02)
    executor.trading.place_market_order.assert_not_called()


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
    executor.account.get_raw_fills.return_value = []
    executor.account.get_order_status.return_value = _order_status_response("rejected")

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
    executor.account.get_order_status.return_value = {"status": "unknownOid"}
    executor.account.get_raw_fills.return_value = [
        {"oid": 1, "sz": "0.001", "px": "50000"},
        {"oid": 2, "sz": "0.001", "px": "50100"},
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
    executor.account.get_order_status.return_value = {"status": "unknownOid"}
    executor.account.get_raw_fills.return_value = [
        {"oid": 1, "sz": "0.0007", "px": "50000"},  # BUY partial fill
        {"oid": 2, "sz": "0.0007", "px": "50100"},  # SELL fill
    ]
    executor.account.get_positions.return_value = []

    executor.run_smoke_cycle(size=0.001)

    _, sell_kwargs = executor.trading.place_market_order.call_args_list[1]
    assert sell_kwargs["size"] == "0.0007"


def test_smoke_cycle_confirms_via_fills_when_order_status_is_unknown_oid(safe_settings):
    """
    End-to-end regression for the real reported bug: with orderStatus
    returning {"status": "unknownOid"} throughout, BOTH the BUY and
    SELL of a full smoke cycle must still be confirmed filled via
    user_fills and the cycle must complete — not time out.
    """
    executor = make_executor(safe_settings)
    executor.account.get_open_orders.return_value = []
    executor.trading.place_market_order.side_effect = [
        _mock_filled_order_response(57627138319),
        _mock_filled_order_response(57627138320),
    ]
    executor.account.get_order_status.return_value = {"status": "unknownOid"}
    executor.account.get_raw_fills.return_value = [
        {"oid": 57627138319, "sz": "0.001", "px": "64891.0"},
        {"oid": 57627138320, "sz": "0.001", "px": "64850.0"},
    ]
    executor.account.get_positions.return_value = []

    buy_result, sell_result = executor.run_smoke_cycle(size=0.001)

    assert buy_result.status == "filled"
    assert sell_result is not None
    assert sell_result.status == "filled"
