from __future__ import annotations

import math
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────
# TIMESTAMP HELPERS
# ──────────────────────────────────────────────────────────────


def now_iso() -> str:
    """
    Returns the current UTC time as an ISO 8601 string.

    Example: "2026-06-27T18:10:57.123456+00:00"
    """
    return datetime.now(timezone.utc).isoformat()


def now_ms() -> int:
    """
    Returns the current UTC time in milliseconds.

    Used for nonce generation and API timestamps.
    """
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def ms_to_iso(timestamp_ms: int) -> str:
    """
    Converts a millisecond timestamp to ISO 8601 string.

    Args:
        timestamp_ms: Unix timestamp in milliseconds

    Returns:
        ISO 8601 string in UTC e.g. "2026-06-27T18:10:57+00:00"

    Example:
        ms_to_iso(1751047857000) → "2026-06-27T18:10:57+00:00"
    """
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def ms_to_datetime(timestamp_ms: int) -> datetime:
    """
    Converts a millisecond timestamp to a Python datetime object (UTC).

    Args:
        timestamp_ms: Unix timestamp in milliseconds

    Returns:
        UTC datetime object
    """
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


# ──────────────────────────────────────────────────────────────
# PRICE & SIZE FORMATTING
# ──────────────────────────────────────────────────────────────


def format_price(price: float, decimals: int = 2) -> str:
    """
    Formats a price with commas and fixed decimal places.

    Args:
        price:    price in USDC
        decimals: decimal places (default 2)

    Returns:
        Formatted string e.g. "50,123.45"

    Example:
        format_price(50123.456) → "50,123.46"
    """
    return f"{price:,.{decimals}f}"


def format_pnl(pnl: float, decimals: int = 4) -> str:
    """
    Formats a PnL value with sign and fixed decimal places.

    Args:
        pnl:      profit or loss in USDC
        decimals: decimal places (default 4)

    Returns:
        Formatted string with sign e.g. "+0.1234" or "-0.5678"

    Example:
        format_pnl(0.1234)  → "+0.1234"
        format_pnl(-0.5678) → "-0.5678"
    """
    return f"{pnl:+.{decimals}f}"


def format_pct(value: float, decimals: int = 2) -> str:
    """
    Formats a fraction as a percentage string.

    Args:
        value:    fraction e.g. 0.60 for 60%
        decimals: decimal places (default 2)

    Returns:
        Percentage string e.g. "60.00%"

    Example:
        format_pct(0.6)   → "60.00%"
        format_pct(0.386) → "38.60%"
    """
    return f"{value * 100:.{decimals}f}%"


def round_size(size: float, sz_decimals: int) -> float:
    """
    Rounds a position size to the asset's allowed decimal places.

    Hyperliquid enforces szDecimals per asset — BTC allows 5 decimal places,
    ETH allows 4, etc. Sending a size with too many decimals causes rejection.

    Args:
        size:        raw position size
        sz_decimals: number of decimal places allowed for this asset

    Returns:
        Rounded size as float

    Example:
        round_size(0.00123456, sz_decimals=5) → 0.00123
        round_size(0.123456, sz_decimals=3)   → 0.123
    """
    factor = 10**sz_decimals
    return math.floor(size * factor) / factor


def round_price(price: float, tick_size: float) -> float:
    """
    Rounds a price to the nearest valid tick size.

    Hyperliquid enforces tick sizes per asset — prices not divisible
    by tick size are rejected with a "Tick" error.

    Args:
        price:     raw price
        tick_size: minimum price increment for this asset

    Returns:
        Price rounded down to nearest tick

    Example:
        round_price(50123.456, tick_size=0.1) → 50123.4
        round_price(50123.456, tick_size=1.0) → 50123.0
    """
    if tick_size <= 0:
        raise ValueError(f"tick_size must be > 0, got {tick_size}")
    return math.floor(price / tick_size) * tick_size


# ──────────────────────────────────────────────────────────────
# RETURNS CALCULATION
# ──────────────────────────────────────────────────────────────


def pct_change(old: float, new: float) -> float:
    """
    Calculates percentage change between two values.

    Formula: (new - old) / old

    Args:
        old: previous value
        new: current value

    Returns:
        Percentage change as fraction e.g. 0.10 = 10% increase

    Raises:
        ValueError: if old is zero
    """
    if old == 0:
        raise ValueError("Cannot calculate percentage change from zero.")
    return (new - old) / old


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    Clamps a value between min and max.

    Used for position sizing — ensures size never goes below minimum
    or above maximum regardless of what the calculation returns.

    Args:
        value:   value to clamp
        min_val: minimum allowed value
        max_val: maximum allowed value

    Returns:
        Clamped value

    Example:
        clamp(0.0005, 0.001, 0.1) → 0.001  (below min)
        clamp(0.5,    0.001, 0.1) → 0.1    (above max)
        clamp(0.01,   0.001, 0.1) → 0.01   (within range)
    """
    return max(min_val, min(value, max_val))
