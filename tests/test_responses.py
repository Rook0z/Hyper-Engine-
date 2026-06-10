import pytest
from pydantic import ValidationError

from hyperliquid.responses import (
    AssetMeta,
    ClearinghouseState,
    ExchangeResponse,
    L2Book,
    Meta,
    OpenOrder,
    SpotAssetMeta,
    SpotMeta,
)


# ──────────────────────────────────────────────────────────────
# META
# ──────────────────────────────────────────────────────────────


def test_asset_meta_valid():
    data = {"name": "BTC", "szDecimals": 5, "maxLeverage": 50}
    asset = AssetMeta(**data)
    assert asset.name == "BTC"
    assert asset.szDecimals == 5
    assert asset.maxLeverage == 50
    assert asset.isDelisted is False  # default


def test_asset_meta_ignores_extra_fields():
    data = {"name": "BTC", "szDecimals": 5, "maxLeverage": 50, "unknownField": "xyz"}
    asset = AssetMeta(**data)
    assert asset.name == "BTC"


def test_meta_valid():
    data = {
        "universe": [
            {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
            {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
        ]
    }
    meta = Meta(**data)
    assert len(meta.universe) == 2
    assert meta.universe[0].name == "BTC"
    assert meta.universe[1].name == "ETH"


def test_meta_missing_universe_raises():
    with pytest.raises(ValidationError):
        Meta(**{})


# ──────────────────────────────────────────────────────────────
# SPOT META
# ──────────────────────────────────────────────────────────────


def test_spot_asset_meta_valid():
    data = {"name": "PURR/USDC", "index": 0}
    asset = SpotAssetMeta(**data)
    assert asset.name == "PURR/USDC"
    assert asset.index == 0


def test_spot_meta_valid():
    data = {"universe": [{"name": "PURR/USDC", "index": 0}]}
    spot_meta = SpotMeta(**data)
    assert len(spot_meta.universe) == 1
    assert spot_meta.universe[0].index == 0


# ──────────────────────────────────────────────────────────────
# CLEARINGHOUSE STATE
# ──────────────────────────────────────────────────────────────

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


def test_clearinghouse_state_valid():
    state = ClearinghouseState(**CLEARINGHOUSE_DATA)
    assert state.marginSummary.accountValue == "13109.48"
    assert len(state.assetPositions) == 1
    assert state.assetPositions[0].position.coin == "ETH"


def test_clearinghouse_state_no_positions():
    data = {**CLEARINGHOUSE_DATA, "assetPositions": []}
    state = ClearinghouseState(**data)
    assert state.assetPositions == []


def test_clearinghouse_state_ignores_extra_fields():
    data = {**CLEARINGHOUSE_DATA, "newFieldFromAPI": "somevalue"}
    state = ClearinghouseState(**data)
    assert state.withdrawable == "13104.51"


# ──────────────────────────────────────────────────────────────
# OPEN ORDER
# ──────────────────────────────────────────────────────────────


def test_open_order_valid():
    data = {
        "coin": "BTC",
        "side": "B",
        "limitPx": "50000.0",
        "sz": "0.001",
        "oid": 12345,
        "timestamp": 1708622398623,
    }
    order = OpenOrder(**data)
    assert order.coin == "BTC"
    assert order.side == "B"
    assert order.cloid is None  # optional, defaults to None


def test_open_order_with_cloid():
    data = {
        "coin": "ETH",
        "side": "A",
        "limitPx": "3000.0",
        "sz": "0.1",
        "oid": 67890,
        "timestamp": 1708622398623,
        "cloid": "0x1234567890abcdef1234567890abcdef",
    }
    order = OpenOrder(**data)
    assert order.cloid == "0x1234567890abcdef1234567890abcdef"


# ──────────────────────────────────────────────────────────────
# L2 BOOK
# ──────────────────────────────────────────────────────────────


def test_l2_book_valid():
    data = {
        "coin": "BTC",
        "time": 1708622398623,
        "levels": [
            [{"px": "49999.0", "sz": "0.5", "n": 3}],  # bids
            [{"px": "50001.0", "sz": "0.3", "n": 2}],  # asks
        ],
    }
    book = L2Book(**data)
    assert book.coin == "BTC"
    assert len(book.levels[0]) == 1  # 1 bid level
    assert len(book.levels[1]) == 1  # 1 ask level
    assert book.levels[0][0].px == "49999.0"
    assert book.levels[1][0].px == "50001.0"


# ──────────────────────────────────────────────────────────────
# EXCHANGE RESPONSE
# ──────────────────────────────────────────────────────────────


def test_exchange_response_ok():
    data = {"status": "ok", "response": {"type": "order", "data": {}}}
    resp = ExchangeResponse(**data)
    assert resp.status == "ok"


def test_exchange_response_error():
    data = {"status": "err", "response": None}
    resp = ExchangeResponse(**data)
    assert resp.status == "err"


def test_exchange_response_missing_status_raises():
    with pytest.raises(ValidationError):
        ExchangeResponse(**{})
