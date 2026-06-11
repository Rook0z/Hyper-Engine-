from unittest.mock import MagicMock
import pytest
from hyperliquid.account import HyperliquidAccount

ACCOUNT_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"

CLEARINGHOUSE_DATA = {
    "marginSummary": {
        "accountValue": "13109.48",
        "totalNtlPos": "100.02",
        "totalRawUsd": "13009.45",
        "totalMarginUsed": "4.96",
    },
    "crossMarginSummary": {
        "accountValue": "13104.51",
        "totalNtlPos": "0.0",
        "totalRawUsd": "13104.51",
        "totalMarginUsed": "0.0",
    },
    "crossMaintenanceMarginUsed": "0.0",
    "withdrawable": "13104.51",
    "assetPositions": [
        {
            "position": {
                "coin": "ETH",
                "szi": "0.0335",
                "entryPx": "2986.3",
                "unrealizedPnl": "-0.013",
                "marginUsed": "4.96",
                "liquidationPx": "2866.26",
                "positionValue": "100.02",
                "returnOnEquity": "-0.002",
                "maxLeverage": 50,
                "leverage": {"type": "isolated", "value": 20, "rawUsd": "-95.05"},
                "cumFunding": {
                    "allTime": "514.08",
                    "sinceChange": "0.0",
                    "sinceOpen": "0.0",
                },
            },
            "type": "oneWay",
        }
    ],
    "time": 1708622398623,
}


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def account(mock_client):
    return HyperliquidAccount(client=mock_client, account_address=ACCOUNT_ADDRESS)


def test_get_balances_returns_state(account, mock_client):
    mock_client.info.return_value = CLEARINGHOUSE_DATA
    state = account.get_balances()
    assert state.marginSummary.accountValue == "13109.48"
    assert state.withdrawable == "13104.51"


def test_get_balances_uses_correct_address(account, mock_client):
    mock_client.info.return_value = CLEARINGHOUSE_DATA
    account.get_balances()
    payload = mock_client.info.call_args[0][0]
    assert payload["user"] == ACCOUNT_ADDRESS
    assert payload["type"] == "clearinghouseState"


def test_get_positions_filters_nonzero(account, mock_client):
    mock_client.info.return_value = CLEARINGHOUSE_DATA
    positions = account.get_positions()
    assert len(positions) == 1
    assert positions[0]["coin"] == "ETH"


def test_get_positions_empty_when_no_positions(account, mock_client):
    data = {**CLEARINGHOUSE_DATA, "assetPositions": []}
    mock_client.info.return_value = data
    positions = account.get_positions()
    assert positions == []


def test_get_open_orders_returns_list(account, mock_client):
    mock_client.info.return_value = [
        {
            "coin": "BTC",
            "side": "B",
            "limitPx": "50000",
            "sz": "0.001",
            "oid": 123,
            "timestamp": 1234567890,
        }
    ]
    orders = account.get_open_orders()
    assert len(orders) == 1
    assert orders[0].coin == "BTC"
    assert orders[0].oid == 123


def test_get_open_orders_empty(account, mock_client):
    mock_client.info.return_value = []
    orders = account.get_open_orders()
    assert orders == []


def test_get_order_status(account, mock_client):
    mock_client.info.return_value = {
        "order": {
            "coin": "BTC",
            "side": "B",
            "limitPx": "50000",
            "sz": "0.001",
            "oid": 123,
            "timestamp": 0,
            "origSz": "0.001",
        },
        "status": "open",
        "statusTimestamp": 1234567890,
    }
    result = account.get_order_status(123)
    assert result["status"] == "open"


def test_get_fills_returns_list(account, mock_client):
    mock_client.info.return_value = [
        {
            "coin": "BTC",
            "side": "B",
            "px": "50000",
            "sz": "0.001",
            "time": 123,
            "startPosition": "0",
            "dir": "Open Long",
            "closedPnl": "0",
            "hash": "0xabc",
            "oid": 1,
            "crossed": False,
            "fee": "0.05",
        }
    ]
    fills = account.get_fills()
    assert len(fills) == 1
    assert fills[0].coin == "BTC"


def test_get_fills_with_start_time(account, mock_client):
    mock_client.info.return_value = []
    account.get_fills(start_time=1700000000000)
    payload = mock_client.info.call_args[0][0]
    assert payload["startTime"] == 1700000000000
