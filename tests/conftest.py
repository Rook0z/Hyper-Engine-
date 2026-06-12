import pytest
from unittest.mock import MagicMock

from hyperliquid.auth import HyperliquidAuth
from hyperliquid.client import HyperliquidClient
from hyperliquid.symbol import HyperliquidSymbol, SymbolNotFoundError

# ──────────────────────────────────────────────────────────────
# CONSTANTS — safe public test keys (Hardhat/Foundry defaults)
# ──────────────────────────────────────────────────────────────

TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ACCOUNT_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"

SYMBOL_IDS = {"BTC": 0, "ETH": 1, "SOL": 2}

# ──────────────────────────────────────────────────────────────
# AUTH FIXTURES
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def auth():
    """Real HyperliquidAuth instance with test keys."""
    return HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY,
        account_address=TEST_ACCOUNT_ADDRESS,
    )


@pytest.fixture
def auth_mainnet():
    """Real HyperliquidAuth instance set to mainnet."""
    return HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY,
        account_address=TEST_ACCOUNT_ADDRESS,
        is_mainnet=True,
    )


# ──────────────────────────────────────────────────────────────
# CLIENT FIXTURES
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    """Mock HyperliquidClient — no real HTTP calls."""
    client = MagicMock(spec=HyperliquidClient)
    client.auth = MagicMock()
    client.auth.account_address = TEST_ACCOUNT_ADDRESS
    return client


@pytest.fixture
def real_client(auth):
    """Real HyperliquidClient pointed at testnet with real auth."""
    return HyperliquidClient(auth=auth)


@pytest.fixture
def client_no_auth():
    """Real HyperliquidClient with no auth — info only."""
    return HyperliquidClient(auth=None)


# ──────────────────────────────────────────────────────────────
# SYMBOL MAP FIXTURES
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_symbol_map():
    """Mock HyperliquidSymbol with BTC=0, ETH=1, SOL=2."""
    sm = MagicMock(spec=HyperliquidSymbol)

    def get_perp_asset_id(symbol):
        if symbol not in SYMBOL_IDS:
            raise SymbolNotFoundError(f"Perp symbol '{symbol}' not found.")
        return SYMBOL_IDS[symbol]

    def get_spot_asset_id(symbol):
        spot_ids = {"PURR/USDC": 10000, "HYPE/USDC": 10001}
        if symbol not in spot_ids:
            raise SymbolNotFoundError(f"Spot symbol '{symbol}' not found.")
        return spot_ids[symbol]

    sm.get_perp_asset_id.side_effect = get_perp_asset_id
    sm.get_spot_asset_id.side_effect = get_spot_asset_id
    sm.get_symbol.side_effect = lambda aid: {v: k for k, v in SYMBOL_IDS.items()}.get(
        aid
    )
    sm.all_perp_symbols.return_value = sorted(SYMBOL_IDS.keys())
    sm.is_loaded.return_value = True
    return sm


# ──────────────────────────────────────────────────────────────
# RESPONSE DATA FIXTURES
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def clearinghouse_data():
    """Realistic clearinghouseState response from the API."""
    return {
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
def meta_data():
    """Realistic meta response from the API."""
    return {
        "universe": [
            {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
            {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
            {"name": "SOL", "szDecimals": 2, "maxLeverage": 20},
        ]
    }


@pytest.fixture
def order_ok_response():
    """Successful order placement response."""
    return {
        "status": "ok",
        "response": {
            "type": "order",
            "data": {"statuses": [{"resting": {"oid": 12345}}]},
        },
    }


@pytest.fixture
def cancel_ok_response():
    """Successful cancel response."""
    return {
        "status": "ok",
        "response": {
            "type": "cancel",
            "data": {"statuses": ["success"]},
        },
    }
