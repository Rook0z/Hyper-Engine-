import pytest
from core.exceptions import (
    HyperEngineError,
    APIError,
    RateLimitError,
    NetworkError,
    SymbolNotFoundError,
    OrderRejectedError,
    RiskLimitError,
    ConfigurationError,
    CredentialsError,
)


# ── HIERARCHY ─────────────────────────────────────────────────


def test_api_error_is_hyper_engine_error():
    assert issubclass(APIError, HyperEngineError)


def test_rate_limit_is_api_error():
    assert issubclass(RateLimitError, APIError)


def test_network_error_is_hyper_engine_error():
    assert issubclass(NetworkError, HyperEngineError)


def test_symbol_not_found_is_hyper_engine_error():
    assert issubclass(SymbolNotFoundError, HyperEngineError)


def test_order_rejected_is_hyper_engine_error():
    assert issubclass(OrderRejectedError, HyperEngineError)


def test_risk_limit_is_hyper_engine_error():
    assert issubclass(RiskLimitError, HyperEngineError)


def test_credentials_error_is_configuration_error():
    assert issubclass(CredentialsError, ConfigurationError)


def test_configuration_error_is_hyper_engine_error():
    assert issubclass(ConfigurationError, HyperEngineError)


# ── API ERROR ─────────────────────────────────────────────────


def test_api_error_stores_status_code():
    e = APIError(400, "bad request")
    assert e.status_code == 400


def test_api_error_stores_message():
    e = APIError(400, "bad request")
    assert e.message == "bad request"


def test_api_error_str():
    e = APIError(400, "bad request")
    assert "400" in str(e)
    assert "bad request" in str(e)


def test_api_error_is_exception():
    with pytest.raises(APIError):
        raise APIError(400, "bad request")


# ── RATE LIMIT ERROR ──────────────────────────────────────────


def test_rate_limit_status_is_429():
    e = RateLimitError()
    assert e.status_code == 429


def test_rate_limit_custom_message():
    e = RateLimitError("custom message")
    assert e.message == "custom message"


def test_rate_limit_caught_as_api_error():
    with pytest.raises(APIError):
        raise RateLimitError()


# ── NETWORK ERROR ─────────────────────────────────────────────


def test_network_error_message():
    e = NetworkError("connection refused")
    assert "connection refused" in str(e)


def test_network_error_not_api_error():
    assert not issubclass(NetworkError, APIError)


# ── ORDER REJECTED ────────────────────────────────────────────


def test_order_rejected_stores_reason():
    e = OrderRejectedError("MinTradeNtl", "BTC")
    assert e.reason == "MinTradeNtl"
    assert e.symbol == "BTC"


def test_order_rejected_str_contains_reason():
    e = OrderRejectedError("PerpMargin", "ETH")
    assert "PerpMargin" in str(e)
    assert "ETH" in str(e)


def test_order_rejected_no_symbol():
    e = OrderRejectedError("Tick")
    assert e.symbol == ""


# ── RISK LIMIT ────────────────────────────────────────────────


def test_risk_limit_stores_reason():
    e = RiskLimitError("Daily loss limit breached")
    assert e.reason == "Daily loss limit breached"


def test_risk_limit_str():
    e = RiskLimitError("Max positions")
    assert "Max positions" in str(e)


# ── CREDENTIALS ERROR ─────────────────────────────────────────


def test_credentials_error_message():
    e = CredentialsError()
    assert "HL_PRIVATE_KEY" in str(e)
    assert ".env" in str(e)
