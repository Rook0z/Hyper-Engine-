from unittest.mock import MagicMock
import pytest
from hyperliquid.trading import HyperliquidTrading, _round_price
from hyperliquid.symbol import HyperliquidSymbol, SymbolNotFoundError

TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ACCOUNT_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"

ORDER_OK = {
    "status": "ok",
    "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 12345}}]}},
}
CANCEL_OK = {
    "status": "ok",
    "response": {"type": "cancel", "data": {"statuses": ["success"]}},
}
LEVERAGE_OK = {"status": "ok", "response": {"type": "default"}}


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.account_address = TEST_ACCOUNT_ADDRESS
    auth.side_effect = lambda action, vault_address=None: {
        "action": action,
        "nonce": 123,
        "signature": {"r": "0x1", "s": "0x2", "v": 27},
    }
    return auth


@pytest.fixture
def mock_client(mock_auth):
    client = MagicMock()
    client.auth = mock_auth
    client.exchange.return_value = ORDER_OK
    client.info.return_value = {"BTC": "50000.0", "ETH": "3000.0"}
    return client


@pytest.fixture
def mock_symbol_map():
    sm = MagicMock(spec=HyperliquidSymbol)
    symbol_ids = {"BTC": 0, "ETH": 1}
    sz_decimals = {"BTC": 5, "ETH": 4}

    def get_perp_asset_id(symbol):
        if symbol not in symbol_ids:
            raise SymbolNotFoundError(symbol)
        return symbol_ids[symbol]

    def get_sz_decimals(symbol):
        if symbol not in sz_decimals:
            raise SymbolNotFoundError(symbol)
        return sz_decimals[symbol]

    sm.get_perp_asset_id.side_effect = get_perp_asset_id
    sm.get_sz_decimals.side_effect = get_sz_decimals
    return sm


@pytest.fixture
def trading(mock_client, mock_symbol_map):
    return HyperliquidTrading(client=mock_client, symbol_map=mock_symbol_map)


# ── INIT ──────────────────────────────────────────────────────


def test_trading_raises_without_auth(mock_symbol_map):
    client = MagicMock()
    client.auth = None
    with pytest.raises(ValueError, match="auth"):
        HyperliquidTrading(client=client, symbol_map=mock_symbol_map)


# ── LIMIT ORDER ───────────────────────────────────────────────


def test_place_limit_order_posts_correct_action(trading, mock_client):
    trading.place_limit_order("BTC", is_buy=True, price="50000.0", size="0.001")
    action = mock_client.exchange.call_args[0][0]
    assert action["type"] == "order"
    assert action["orders"][0]["a"] == 0  # BTC asset ID
    assert action["orders"][0]["b"] is True  # is_buy
    assert action["orders"][0]["p"] == "50000.0"
    assert action["orders"][0]["s"] == "0.001"
    assert action["orders"][0]["t"] == {"limit": {"tif": "Gtc"}}


def test_place_limit_order_sell(trading, mock_client):
    trading.place_limit_order("ETH", is_buy=False, price="3000.0", size="0.1")
    action = mock_client.exchange.call_args[0][0]
    assert action["orders"][0]["a"] == 1  # ETH asset ID
    assert action["orders"][0]["b"] is False  # sell


def test_place_limit_order_with_ioc(trading, mock_client):
    trading.place_limit_order(
        "BTC", is_buy=True, price="50000.0", size="0.001", tif="Ioc"
    )
    action = mock_client.exchange.call_args[0][0]
    assert action["orders"][0]["t"] == {"limit": {"tif": "Ioc"}}


def test_place_limit_order_reduce_only(trading, mock_client):
    trading.place_limit_order(
        "BTC", is_buy=False, price="50000.0", size="0.001", reduce_only=True
    )
    action = mock_client.exchange.call_args[0][0]
    assert action["orders"][0]["r"] is True


def test_place_limit_order_with_cloid(trading, mock_client):
    cloid = "0x1234567890abcdef1234567890abcdef"
    trading.place_limit_order(
        "BTC", is_buy=True, price="50000.0", size="0.001", cloid=cloid
    )
    action = mock_client.exchange.call_args[0][0]
    assert action["orders"][0]["c"] == cloid


def test_place_limit_order_unknown_symbol_raises(trading, mock_symbol_map):
    mock_symbol_map.get_perp_asset_id.side_effect = SymbolNotFoundError("XYZ")
    with pytest.raises(SymbolNotFoundError):
        trading.place_limit_order("XYZ", is_buy=True, price="1.0", size="1.0")


# ── MARKET ORDER ─────────────────────────────────────────────


def test_place_market_order_uses_ioc(trading, mock_client):
    trading.place_market_order("BTC", is_buy=True, size="0.001")
    action = mock_client.exchange.call_args[0][0]
    assert action["orders"][0]["t"] == {"limit": {"tif": "Ioc"}}


def test_place_market_order_buy_price_above_mid(trading, mock_client):
    mock_client.info.return_value = {"BTC": "50000.0"}
    trading.place_market_order("BTC", is_buy=True, size="0.001")
    action = mock_client.exchange.call_args[0][0]
    price = float(action["orders"][0]["p"])
    assert price > 50000.0  # buy price above mid


def test_place_market_order_sell_price_below_mid(trading, mock_client):
    mock_client.info.return_value = {"BTC": "50000.0"}
    trading.place_market_order("BTC", is_buy=False, size="0.001")
    action = mock_client.exchange.call_args[0][0]
    price = float(action["orders"][0]["p"])
    assert price < 50000.0  # sell price below mid


def test_place_market_order_price_respects_significant_figure_limit(
    trading, mock_client
):
    """
    Regression test for the real bug found via the testnet smoke test:
    the old `round(mid * 1.05, 6)` rounded to 6 DECIMAL places, not 5
    SIGNIFICANT figures, so realistic BTC prices (e.g. mid=64966.5)
    produced an 8-significant-figure price like "68214.825" that
    Hyperliquid rejects with "Order has invalid price."
    """
    mock_client.info.return_value = {"BTC": "64966.5"}
    trading.place_market_order("BTC", is_buy=True, size="0.001")
    action = mock_client.exchange.call_args[0][0]
    price_str = action["orders"][0]["p"]

    significant_digits = price_str.replace(".", "").lstrip("0")
    assert (
        len(significant_digits) <= 5
    ), f"price '{price_str}' has more than 5 significant figures"


def test_place_market_order_price_respects_decimal_limit_for_sz_decimals(
    trading, mock_client
):
    """BTC has szDecimals=5, so prices may have at most (6-5)=1 decimal place."""
    mock_client.info.return_value = {"BTC": "64966.5"}
    trading.place_market_order("BTC", is_buy=True, size="0.001")
    action = mock_client.exchange.call_args[0][0]
    price_str = action["orders"][0]["p"]
    decimals = price_str.split(".")[1] if "." in price_str else ""
    assert len(decimals) <= 1


# ── CANCEL ORDER ─────────────────────────────────────────────


def test_cancel_order_posts_correct_action(trading, mock_client):
    mock_client.exchange.return_value = CANCEL_OK
    trading.cancel_order("BTC", oid=12345)
    action = mock_client.exchange.call_args[0][0]
    assert action["type"] == "cancel"
    assert action["cancels"][0] == {"a": 0, "o": 12345}


def test_cancel_order_by_cloid(trading, mock_client):
    mock_client.exchange.return_value = CANCEL_OK
    cloid = "0x1234567890abcdef1234567890abcdef"
    trading.cancel_order_by_cloid("BTC", cloid=cloid)
    action = mock_client.exchange.call_args[0][0]
    assert action["type"] == "cancelByCloid"
    assert action["cancels"][0]["cloid"] == cloid


# ── LEVERAGE ─────────────────────────────────────────────────


def test_set_leverage_posts_correct_action(trading, mock_client):
    mock_client.exchange.return_value = LEVERAGE_OK
    trading.set_leverage("BTC", leverage=10, is_cross=True)
    action = mock_client.exchange.call_args[0][0]
    assert action["type"] == "updateLeverage"
    assert action["asset"] == 0
    assert action["leverage"] == 10
    assert action["isCross"] is True


def test_set_leverage_isolated(trading, mock_client):
    mock_client.exchange.return_value = LEVERAGE_OK
    trading.set_leverage("ETH", leverage=5, is_cross=False)
    action = mock_client.exchange.call_args[0][0]
    assert action["isCross"] is False
    assert action["leverage"] == 5


# ── BATCH ORDERS ─────────────────────────────────────────────


def test_place_batch_orders(trading, mock_client):
    orders = [
        {"symbol": "BTC", "is_buy": True, "price": "50000.0", "size": "0.001"},
        {"symbol": "ETH", "is_buy": False, "price": "3000.0", "size": "0.1"},
    ]
    trading.place_batch_orders(orders)
    action = mock_client.exchange.call_args[0][0]
    assert action["type"] == "order"
    assert len(action["orders"]) == 2
    assert action["orders"][0]["a"] == 0  # BTC
    assert action["orders"][1]["a"] == 1  # ETH


def test_place_batch_orders_with_cloid(trading, mock_client):
    orders = [
        {
            "symbol": "BTC",
            "is_buy": True,
            "price": "50000.0",
            "size": "0.001",
            "cloid": "0x1234567890abcdef1234567890abcdef",
        }
    ]
    trading.place_batch_orders(orders)
    action = mock_client.exchange.call_args[0][0]
    assert action["orders"][0]["c"] == "0x1234567890abcdef1234567890abcdef"


def test_modify_order(trading, mock_client):
    trading.modify_order("BTC", oid=123, price="51000.0", size="0.002", is_buy=True)
    action = mock_client.exchange.call_args[0][0]
    assert action["type"] == "modify"
    assert action["oid"] == 123
    assert action["order"]["p"] == "51000.0"
    assert action["order"]["s"] == "0.002"


def test_cancel_all_orders_for_symbol(trading, mock_client):
    mock_client.auth.account_address = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
    mock_client.info.return_value = [
        {
            "coin": "BTC",
            "oid": 1,
            "side": "B",
            "limitPx": "50000",
            "sz": "0.001",
            "timestamp": 123,
        },
    ]
    mock_client.exchange.return_value = {"status": "ok"}
    results = trading.cancel_all_orders(symbol="BTC")
    assert len(results) == 1
    action = mock_client.exchange.call_args[0][0]
    assert action["type"] == "cancel"
    assert action["cancels"][0]["o"] == 1


def test_cancel_all_orders_empty(trading, mock_client):
    mock_client.auth.account_address = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
    mock_client.info.return_value = []
    results = trading.cancel_all_orders()
    assert results == []


# ── _round_price (Hyperliquid price precision) ────────────────────────


def test_round_price_caps_at_5_significant_figures():
    # 68214.825 -> 5 sig figs -> 68215, then capped to 1 decimal (6-5) -> "68215"
    assert _round_price(68214.825, sz_decimals=5) == "68215"


def test_round_price_caps_decimals_by_sz_decimals():
    # szDecimals=2 -> max 4 decimal places
    assert _round_price(1.23456789, sz_decimals=2) == "1.2346"


def test_round_price_zero_decimals_when_sz_decimals_at_limit():
    # szDecimals=6 -> max(6-6,0)=0 decimal places -> integer string
    assert _round_price(123.456, sz_decimals=6) == "123"


def test_round_price_zero_or_negative_returns_zero_string():
    assert _round_price(0.0, sz_decimals=5) == "0"
    assert _round_price(-5.0, sz_decimals=5) == "0"


def test_round_price_strips_trailing_zeros():
    assert _round_price(50000.0, sz_decimals=5) == "50000"


def test_round_price_small_price_high_sz_decimals():
    # szDecimals=0 -> max 6 decimal places allowed. 5-sig-fig rounding
    # gives 0.00012346 (8 digits after the point), but the 6-decimal
    # cap is the stricter, binding constraint here, truncating to
    # 0.000123.
    assert _round_price(0.00012345678, sz_decimals=0) == "0.000123"
