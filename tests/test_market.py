from unittest.mock import MagicMock
import pytest
from hyperliquid.market import HyperliquidMarket
from hyperliquid.symbol import HyperliquidSymbol, SymbolNotFoundError


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def mock_symbol_map():
    sm = MagicMock(spec=HyperliquidSymbol)
    symbol_ids = {"BTC": 0, "ETH": 1}

    def get_perp_asset_id(symbol):
        if symbol not in symbol_ids:
            raise SymbolNotFoundError(symbol)
        return symbol_ids[symbol]

    sm.get_perp_asset_id.side_effect = get_perp_asset_id
    return sm


@pytest.fixture
def market(mock_client, mock_symbol_map):
    return HyperliquidMarket(client=mock_client, symbol_map=mock_symbol_map)


def test_get_price_returns_mid(market, mock_client):
    mock_client.info.return_value = {"BTC": "50000.0", "ETH": "3000.0"}
    price = market.get_price("BTC")
    assert price == "50000.0"


def test_get_price_unknown_symbol_raises(market, mock_symbol_map):
    mock_symbol_map.get_perp_asset_id.side_effect = SymbolNotFoundError("XYZ")
    with pytest.raises(SymbolNotFoundError):
        market.get_price("XYZ")


def test_get_all_mids_returns_dict(market, mock_client):
    mock_client.info.return_value = {"BTC": "50000.0", "ETH": "3000.0"}
    result = market.get_all_mids()
    assert "BTC" in result
    assert "ETH" in result


def test_get_orderbook_returns_l2book(market, mock_client):
    mock_client.info.return_value = {
        "coin": "BTC",
        "time": 1234567890,
        "levels": [
            [{"px": "49999.0", "sz": "0.5", "n": 2}],
            [{"px": "50001.0", "sz": "0.3", "n": 1}],
        ],
    }
    book = market.get_orderbook("BTC")
    assert book.coin == "BTC"
    assert book.levels[0][0].px == "49999.0"


def test_get_orderbook_posts_correct_payload(market, mock_client):
    mock_client.info.return_value = {"coin": "ETH", "time": 0, "levels": [[], []]}
    market.get_orderbook("ETH", depth=10)
    call_payload = mock_client.info.call_args[0][0]
    assert call_payload["type"] == "l2Book"
    assert call_payload["coin"] == "ETH"
    assert call_payload["nSigFigs"] == 10


def test_get_trades_returns_list(market, mock_client):
    mock_client.info.return_value = [
        {
            "coin": "BTC",
            "side": "B",
            "px": "50000",
            "sz": "0.01",
            "time": 123,
            "hash": "0xabc",
        }
    ]
    trades = market.get_trades("BTC")
    assert isinstance(trades, list)
    assert trades[0]["coin"] == "BTC"


def test_get_meta_returns_model(market, mock_client):
    mock_client.info.return_value = {
        "universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 50}]
    }
    meta = market.get_meta()
    assert meta.universe[0].name == "BTC"
