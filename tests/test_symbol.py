from unittest.mock import MagicMock

import pytest

from hyperliquid.symbol import HyperliquidSymbol, SymbolNotFoundError


# ──────────────────────────────────────────────────────────────
# MOCK DATA — mirrors real API response shapes
# ──────────────────────────────────────────────────────────────

MOCK_META = {
    "universe": [
        {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
        {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
        {"name": "SOL", "szDecimals": 2, "maxLeverage": 20},
        {"name": "LOOM", "szDecimals": 1, "maxLeverage": 3, "isDelisted": True},
    ]
}

MOCK_SPOT_META = {
    "universe": [
        {"name": "PURR/USDC", "index": 0},
        {"name": "HYPE/USDC", "index": 1},
    ]
}


# ──────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    """Mock client that returns fake meta responses."""
    client = MagicMock()
    client.info.side_effect = lambda payload: (
        MOCK_META if payload["type"] == "meta" else MOCK_SPOT_META
    )
    return client


@pytest.fixture
def loaded_symbol_map(mock_client):
    """Symbol map that has already been loaded."""
    symbol_map = HyperliquidSymbol(client=mock_client)
    symbol_map.load()
    return symbol_map


# ──────────────────────────────────────────────────────────────
# LOAD TESTS
# ──────────────────────────────────────────────────────────────


def test_load_calls_meta_and_spot_meta(mock_client):
    """load() must make exactly 2 info calls — meta and spotMeta."""
    symbol_map = HyperliquidSymbol(client=mock_client)
    symbol_map.load()
    assert mock_client.info.call_count == 2


def test_is_loaded_false_before_load(mock_client):
    symbol_map = HyperliquidSymbol(client=mock_client)
    assert symbol_map.is_loaded() is False


def test_is_loaded_true_after_load(loaded_symbol_map):
    assert loaded_symbol_map.is_loaded() is True


# ──────────────────────────────────────────────────────────────
# PERP LOOKUP TESTS
# ──────────────────────────────────────────────────────────────


def test_get_perp_asset_id_btc(loaded_symbol_map):
    assert loaded_symbol_map.get_perp_asset_id("BTC") == 0


def test_get_perp_asset_id_eth(loaded_symbol_map):
    assert loaded_symbol_map.get_perp_asset_id("ETH") == 1


def test_get_perp_asset_id_sol(loaded_symbol_map):
    assert loaded_symbol_map.get_perp_asset_id("SOL") == 2


def test_delisted_asset_not_in_perp_map(loaded_symbol_map):
    """Delisted assets must not be in the lookup map."""
    with pytest.raises(SymbolNotFoundError):
        loaded_symbol_map.get_perp_asset_id("LOOM")


def test_get_perp_asset_id_unknown_raises(loaded_symbol_map):
    with pytest.raises(SymbolNotFoundError, match="XYZ"):
        loaded_symbol_map.get_perp_asset_id("XYZ")


# ───────────────────────────────────────────────────────────
# SZ_DECIMALS TESTS
# ───────────────────────────────────────────────────────────


def test_get_sz_decimals_btc(loaded_symbol_map):
    assert loaded_symbol_map.get_sz_decimals("BTC") == 5


def test_get_sz_decimals_eth(loaded_symbol_map):
    assert loaded_symbol_map.get_sz_decimals("ETH") == 4


def test_get_sz_decimals_sol(loaded_symbol_map):
    assert loaded_symbol_map.get_sz_decimals("SOL") == 2


def test_get_sz_decimals_unknown_raises(loaded_symbol_map):
    with pytest.raises(SymbolNotFoundError, match="XYZ"):
        loaded_symbol_map.get_sz_decimals("XYZ")


def test_get_sz_decimals_delisted_raises(loaded_symbol_map):
    """Delisted assets are skipped entirely during load, same as get_perp_asset_id."""
    with pytest.raises(SymbolNotFoundError):
        loaded_symbol_map.get_sz_decimals("LOOM")


def test_get_sz_decimals_before_load_raises(mock_client):
    symbol_map = HyperliquidSymbol(client=mock_client)
    with pytest.raises(RuntimeError, match="load()"):
        symbol_map.get_sz_decimals("BTC")


# ──────────────────────────────────────────────────────────────
# SPOT LOOKUP TESTS
# ──────────────────────────────────────────────────────────────


def test_get_spot_asset_id_purr(loaded_symbol_map):
    assert loaded_symbol_map.get_spot_asset_id("PURR/USDC") == 10000


def test_get_spot_asset_id_hype(loaded_symbol_map):
    assert loaded_symbol_map.get_spot_asset_id("HYPE/USDC") == 10001


def test_get_spot_asset_id_unknown_raises(loaded_symbol_map):
    with pytest.raises(SymbolNotFoundError, match="UNKNOWN/USDC"):
        loaded_symbol_map.get_spot_asset_id("UNKNOWN/USDC")


# ──────────────────────────────────────────────────────────────
# REVERSE LOOKUP TESTS
# ──────────────────────────────────────────────────────────────


def test_get_symbol_from_perp_id(loaded_symbol_map):
    assert loaded_symbol_map.get_symbol(0) == "BTC"
    assert loaded_symbol_map.get_symbol(1) == "ETH"


def test_get_symbol_from_spot_id(loaded_symbol_map):
    assert loaded_symbol_map.get_symbol(10000) == "PURR/USDC"


def test_get_symbol_unknown_id_raises(loaded_symbol_map):
    with pytest.raises(SymbolNotFoundError):
        loaded_symbol_map.get_symbol(9999)


# ──────────────────────────────────────────────────────────────
# ALL SYMBOLS TESTS
# ──────────────────────────────────────────────────────────────


def test_all_perp_symbols(loaded_symbol_map):
    symbols = loaded_symbol_map.all_perp_symbols()
    assert "BTC" in symbols
    assert "ETH" in symbols
    assert "LOOM" not in symbols  # delisted


def test_all_spot_symbols(loaded_symbol_map):
    symbols = loaded_symbol_map.all_spot_symbols()
    assert "PURR/USDC" in symbols
    assert "HYPE/USDC" in symbols


# ──────────────────────────────────────────────────────────────
# NOT LOADED GUARD TESTS
# ──────────────────────────────────────────────────────────────


def test_lookup_before_load_raises(mock_client):
    """Any lookup before load() must raise RuntimeError."""
    symbol_map = HyperliquidSymbol(client=mock_client)
    with pytest.raises(RuntimeError, match="load()"):
        symbol_map.get_perp_asset_id("BTC")


def test_reverse_lookup_before_load_raises(mock_client):
    symbol_map = HyperliquidSymbol(client=mock_client)
    with pytest.raises(RuntimeError, match="load()"):
        symbol_map.get_symbol(0)
