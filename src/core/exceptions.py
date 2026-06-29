from __future__ import annotations


# ──────────────────────────────────────────────────────────────
# HTTP / API EXCEPTIONS
# ──────────────────────────────────────────────────────────────


class HyperEngineError(Exception):
    """Base exception for all Hyper-Engine errors."""


class APIError(HyperEngineError):
    """
    Raised when Hyperliquid API returns a 4xx error.
    Not retried — these are bad requests.

    Attributes:
        status_code: HTTP status code
        message:     Error message from the API
    """

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"API error {status_code}: {message}")


class RateLimitError(APIError):
    """
    Raised when API returns 429 Too Many Requests.
    Retried with exponential backoff.
    """

    def __init__(self, message: str = "Rate limited — backing off") -> None:
        super().__init__(status_code=429, message=message)


class NetworkError(HyperEngineError):
    """
    Raised on 5xx errors, timeouts, or connection failures.
    Retried with exponential backoff.
    """


# ──────────────────────────────────────────────────────────────
# DATA EXCEPTIONS
# ──────────────────────────────────────────────────────────────


class SymbolNotFoundError(HyperEngineError):
    """
    Raised when a symbol string cannot be resolved to an asset ID.
    Usually means the symbol is delisted or misspelled.

    Example:
        get_perp_asset_id("XYZ") → SymbolNotFoundError: "XYZ not found"
    """


class InsufficientDataError(HyperEngineError):
    """
    Raised when there is not enough data to compute an indicator or signal.

    Example:
        calculate_rsi([1.0, 2.0], period=14) → InsufficientDataError
    """


class DataCleaningError(HyperEngineError):
    """
    Raised when all candles are removed during data cleaning.
    Indicates a serious data quality problem.
    """


# ──────────────────────────────────────────────────────────────
# TRADING EXCEPTIONS
# ──────────────────────────────────────────────────────────────


class OrderRejectedError(HyperEngineError):
    """
    Raised when an order is rejected by the exchange.
    Check the error message for the specific reason
    (e.g. MinTradeNtl, PerpMargin, BadAloPx).

    Attributes:
        reason: rejection reason string from the API
        symbol: asset that was being traded
    """

    def __init__(self, reason: str, symbol: str = "") -> None:
        self.reason = reason
        self.symbol = symbol
        super().__init__(
            f"Order rejected{f' for {symbol}' if symbol else ''}: {reason}"
        )


class PositionNotFoundError(HyperEngineError):
    """
    Raised when trying to close a position that doesn't exist.
    """


class RiskLimitError(HyperEngineError):
    """
    Raised when a trade is blocked by the risk manager.

    Attributes:
        reason: which limit was breached
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Risk limit breached: {reason}")


# ──────────────────────────────────────────────────────────────
# CONFIGURATION EXCEPTIONS
# ──────────────────────────────────────────────────────────────


class ConfigurationError(HyperEngineError):
    """
    Raised when required configuration is missing or invalid.
    Usually means .env is not set up correctly.
    """


class CredentialsError(ConfigurationError):
    """
    Raised when API credentials are missing or invalid.
    """

    def __init__(self) -> None:
        super().__init__(
            "HL_PRIVATE_KEY and HL_ACCOUNT_ADDRESS must be set in .env. "
            "Copy .env.example to .env and fill in your credentials."
        )
