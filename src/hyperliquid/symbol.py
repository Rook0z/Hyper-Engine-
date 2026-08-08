from __future__ import annotations

import logging

from hyperliquid.client import HyperliquidClient
from hyperliquid.responses import Meta, SpotMeta

logger = logging.getLogger(__name__)


class SymbolNotFoundError(Exception):
    """Raised when a symbol is not found in the loaded universe."""


class HyperliquidSymbol:
    """
    Resolves symbol strings to Hyperliquid asset IDs and back.

    Must call load() before any lookups.
    Fetches meta and spotMeta once at startup — not on every call.

    Usage:
        symbol_map = HyperliquidSymbol(client=client)
        symbol_map.load()

        btc_id = symbol_map.get_perp_asset_id("BTC")   # → 0
        eth_id = symbol_map.get_perp_asset_id("ETH")   # → 1
        purr_id = symbol_map.get_spot_asset_id("PURR/USDC")  # → 10000
        name = symbol_map.get_symbol(0)                 # → "BTC"
    """

    def __init__(self, client: HyperliquidClient) -> None:
        self._client = client
        self._perp_map: dict[str, int] = {}  # "BTC" → 0
        self._spot_map: dict[str, int] = {}  # "PURR/USDC" → 10000
        self._reverse_map: dict[int, str] = {}  # 0 → "BTC", 10000 → "PURR/USDC"
        self._sz_decimals: dict[str, int] = {}  # "BTC" → 5
        self._loaded = False

    def load(self) -> None:
        """
        Fetches meta and spotMeta from the API and builds lookup maps.

        Makes exactly 2 HTTP calls. Must be called once before any lookups.
        Call again to refresh if suspect the universe has changed.
        """
        self._load_perps()
        self._load_spot()
        self._loaded = True
        logger.info(
            "Symbol map loaded: %d perp assets, %d spot assets",
            len(self._perp_map),
            len(self._spot_map),
        )

    def _load_perps(self) -> None:
        """Fetches perpetuals universe and builds perp lookup map."""
        raw = self._client.info({"type": "meta"})
        meta = Meta(**raw)

        for index, asset in enumerate(meta.universe):
            if asset.isDelisted:
                continue  # skip delisted assets
            self._perp_map[asset.name] = index
            self._reverse_map[index] = asset.name
            self._sz_decimals[asset.name] = asset.szDecimals

        logger.debug("Loaded %d perp symbols", len(self._perp_map))

    def _load_spot(self) -> None:
        """Fetches spot universe and builds spot lookup map."""
        raw = self._client.info({"type": "spotMeta"})
        spot_meta = SpotMeta(**raw)

        for asset in spot_meta.universe:
            asset_id = 10000 + asset.index
            self._spot_map[asset.name] = asset_id
            self._reverse_map[asset_id] = asset.name

        logger.debug("Loaded %d spot symbols", len(self._spot_map))

    # ──────────────────────────────────────────────────────────────
    # PUBLIC LOOKUP METHODS
    # ──────────────────────────────────────────────────────────────

    def get_perp_asset_id(self, symbol: str) -> int:
        """
        Returns the perpetual asset ID for a symbol string.

        Args:
            symbol: e.g. "BTC", "ETH", "SOL"

        Returns:
            Integer asset ID (e.g. 0 for BTC)

        Raises:
            RuntimeError: If load() has not been called yet
            SymbolNotFoundError: If the symbol is not in the universe
        """
        self._require_loaded()
        asset_id = self._perp_map.get(symbol)
        if asset_id is None:
            available = sorted(self._perp_map.keys())
            raise SymbolNotFoundError(
                f"Perp symbol '{symbol}' not found. "
                f"Available: {available[:10]}{'...' if len(available) > 10 else ''}"
            )
        return asset_id

    def get_spot_asset_id(self, symbol: str) -> int:
        """
        Returns the spot asset ID for a symbol string.

        Args:
            symbol: e.g. "PURR/USDC"

        Returns:
            Integer asset ID (e.g. 10000 for PURR/USDC)

        Raises:
            RuntimeError: If load() has not been called yet
            SymbolNotFoundError: If the symbol is not in the universe
        """
        self._require_loaded()
        asset_id = self._spot_map.get(symbol)
        if asset_id is None:
            available = sorted(self._spot_map.keys())
            raise SymbolNotFoundError(
                f"Spot symbol '{symbol}' not found. "
                f"Available: {available[:10]}{'...' if len(available) > 10 else ''}"
            )
        return asset_id

    def get_symbol(self, asset_id: int) -> str:
        """
        Reverse lookup — returns the symbol string for an asset ID.

        Args:
            asset_id: Integer asset ID (e.g. 0, 1, 10000)

        Returns:
            Symbol string (e.g. "BTC", "PURR/USDC")

        Raises:
            RuntimeError: If load() has not been called yet
            SymbolNotFoundError: If the asset ID is not known
        """
        self._require_loaded()
        symbol = self._reverse_map.get(asset_id)
        if symbol is None:
            raise SymbolNotFoundError(f"Asset ID {asset_id} not found in reverse map.")
        return symbol

    def get_sz_decimals(self, symbol: str) -> int:
        """
        Returns the perpetual asset's szDecimals (size precision) —
        also needed to compute Hyperliquid's price precision limit:
        prices may have at most (6 - szDecimals) decimal places, in
        addition to the separate 5-significant-figure limit.

        Args:
            symbol: e.g. "BTC"

        Raises:
            RuntimeError: If load() has not been called yet
            SymbolNotFoundError: If the symbol is not in the universe
        """
        self._require_loaded()
        decimals = self._sz_decimals.get(symbol)
        if decimals is None:
            raise SymbolNotFoundError(f"Perp symbol '{symbol}' not found.")
        return decimals

    def all_perp_symbols(self) -> list[str]:
        """Returns a sorted list of all tradeable perpetual symbols."""
        self._require_loaded()
        return sorted(self._perp_map.keys())

    def all_spot_symbols(self) -> list[str]:
        """Returns a sorted list of all spot symbols."""
        self._require_loaded()
        return sorted(self._spot_map.keys())

    def is_loaded(self) -> bool:
        """Returns True if load() has been called successfully."""
        return self._loaded

    # ──────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────

    def _require_loaded(self) -> None:
        """Raises RuntimeError if load() hasn't been called yet."""
        if not self._loaded:
            raise RuntimeError(
                "HyperliquidSymbol.load() must be called before any lookups. "
                "Call symbol_map.load() once at startup."
            )
