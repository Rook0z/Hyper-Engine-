from unittest.mock import MagicMock, patch

import httpx
import pytest

from hyperliquid.auth import HyperliquidAuth
from hyperliquid.client import APIError, HyperliquidClient, NetworkError, RateLimitError

# ──────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────

TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ACCOUNT_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"


@pytest.fixture
def auth():
    return HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY,
        account_address=TEST_ACCOUNT_ADDRESS,
    )


@pytest.fixture
def client(auth):
    return HyperliquidClient(auth=auth)


@pytest.fixture
def client_no_auth():
    return HyperliquidClient(auth=None)


def make_mock_response(status_code: int, json_data: dict) -> MagicMock:
    """Helper — builds a fake httpx response."""
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.text = str(json_data)
    return mock


# ──────────────────────────────────────────────────────────────
# INIT TESTS
# ──────────────────────────────────────────────────────────────


def test_client_defaults_to_testnet(auth):
    """Client must default to testnet — never mainnet by default."""
    client = HyperliquidClient(auth=auth)
    assert "testnet" in client.base_url


def test_client_accepts_custom_base_url(auth):
    """Client accepts a custom base URL."""
    client = HyperliquidClient(auth=auth, base_url="https://api.hyperliquid.xyz")
    assert client.base_url == "https://api.hyperliquid.xyz"


# ──────────────────────────────────────────────────────────────
# INFO TESTS
# ──────────────────────────────────────────────────────────────


def test_info_posts_to_correct_endpoint(client):
    """info() must POST to /info."""
    mock_response = make_mock_response(200, {"marginSummary": {}})

    with patch("httpx.post", return_value=mock_response) as mock_post:
        client.info({"type": "clearinghouseState", "user": "0x123"})
        call_args = mock_post.call_args
        assert call_args[0][0].endswith("/info")


def test_info_does_not_add_signature(client):
    """info() must NOT add signature — /info is public."""
    mock_response = make_mock_response(200, {"marginSummary": {}})

    with patch("httpx.post", return_value=mock_response) as mock_post:
        client.info({"type": "clearinghouseState", "user": "0x123"})
        posted_body = mock_post.call_args[1]["json"]
        assert "signature" not in posted_body
        assert "nonce" not in posted_body


def test_info_returns_parsed_json(client):
    """info() must return the parsed JSON response."""
    expected = {"marginSummary": {"accountValue": "1000.0"}}
    mock_response = make_mock_response(200, expected)

    with patch("httpx.post", return_value=mock_response):
        result = client.info({"type": "clearinghouseState", "user": "0x123"})
        assert result == expected


# ──────────────────────────────────────────────────────────────
# EXCHANGE TESTS
# ──────────────────────────────────────────────────────────────


def test_exchange_posts_to_correct_endpoint(client):
    """exchange() must POST to /exchange."""
    mock_response = make_mock_response(200, {"status": "ok"})

    with patch("httpx.post", return_value=mock_response) as mock_post:
        client.exchange({"type": "order", "asset": 0})
        call_args = mock_post.call_args
        assert call_args[0][0].endswith("/exchange")


def test_exchange_adds_signature(client):
    """exchange() must add action + nonce + signature to request body."""
    mock_response = make_mock_response(200, {"status": "ok"})

    with patch("httpx.post", return_value=mock_response) as mock_post:
        client.exchange({"type": "order", "asset": 0})
        posted_body = mock_post.call_args[1]["json"]
        assert "action" in posted_body
        assert "nonce" in posted_body
        assert "signature" in posted_body


def test_exchange_raises_without_auth(client_no_auth):
    """exchange() must raise ValueError if no auth provided."""
    with pytest.raises(ValueError, match="auth instance"):
        client_no_auth.exchange({"type": "order", "asset": 0})


# ──────────────────────────────────────────────────────────────
# ERROR HANDLING TESTS
# ──────────────────────────────────────────────────────────────


def test_raises_rate_limit_error_on_429(client):
    """Must raise RateLimitError on HTTP 429."""
    mock_response = make_mock_response(429, {"error": "rate limited"})

    with patch("httpx.post", return_value=mock_response):
        with pytest.raises(RateLimitError):
            client.info({"type": "meta"})


def test_raises_api_error_on_400(client):
    """Must raise APIError on HTTP 400."""
    mock_response = make_mock_response(400, {"error": "bad request"})

    with patch("httpx.post", return_value=mock_response):
        with pytest.raises(APIError) as exc_info:
            client.info({"type": "meta"})
        assert exc_info.value.status_code == 400


def test_raises_network_error_on_500(client):
    """Must raise NetworkError on HTTP 500."""
    mock_response = make_mock_response(500, {"error": "server error"})
    mock_response.text = "server error"

    with patch("httpx.post", return_value=mock_response):
        with pytest.raises(NetworkError):
            client.info({"type": "meta"})


def test_raises_network_error_on_timeout(client):
    """Must raise NetworkError on request timeout."""
    with patch("httpx.post", side_effect=httpx.TimeoutException("timed out")):
        with pytest.raises(NetworkError, match="timed out"):
            client.info({"type": "meta"})


def test_raises_network_error_on_connection_failure(client):
    """Must raise NetworkError on connection failure."""
    with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
        with pytest.raises(NetworkError, match="Connection failed"):
            client.info({"type": "meta"})


def test_retries_on_network_error(auth):
    """Client must retry on NetworkError up to max_retries times."""
    client = HyperliquidClient(auth=auth, max_retries=2, base_delay=0.01)
    mock_response = make_mock_response(500, {"error": "server error"})
    mock_response.text = "server error"

    with patch("httpx.post", return_value=mock_response):
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(NetworkError):
                client.info({"type": "meta"})
            # Should have slept twice (2 retries = 2 sleeps before giving up)
            assert mock_sleep.call_count == 2


def test_retries_on_rate_limit(auth):
    """Client must retry on RateLimitError."""
    client = HyperliquidClient(auth=auth, max_retries=2, base_delay=0.01)
    mock_response = make_mock_response(429, {"error": "rate limited"})

    with patch("httpx.post", return_value=mock_response):
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(RateLimitError):
                client.info({"type": "meta"})
            assert mock_sleep.call_count == 2


def test_no_retry_on_4xx(auth):
    """Client must NOT retry on 4xx API errors."""
    client = HyperliquidClient(auth=auth, max_retries=3, base_delay=0.01)
    mock_response = make_mock_response(400, {"error": "bad request"})

    with patch("httpx.post", return_value=mock_response):
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(APIError):
                client.info({"type": "meta"})
            # No sleep — 4xx should not be retried
            assert mock_sleep.call_count == 0


def test_succeeds_on_retry_after_failure(auth):
    """Client must succeed if a retry attempt succeeds."""
    client = HyperliquidClient(auth=auth, max_retries=2, base_delay=0.01)

    fail_response = make_mock_response(500, {"error": "server error"})
    fail_response.text = "server error"
    success_response = make_mock_response(200, {"status": "ok"})

    with patch("httpx.post", side_effect=[fail_response, success_response]):
        with patch("time.sleep"):
            result = client.info({"type": "meta"})
            assert result == {"status": "ok"}


def test_backoff_delay_doubles(auth):
    """Backoff delay must double each attempt."""
    client = HyperliquidClient(auth=auth, max_retries=3, base_delay=1.0, max_delay=60.0)
    assert client._backoff_delay(0) == 1.0
    assert client._backoff_delay(1) == 2.0
    assert client._backoff_delay(2) == 4.0
    assert client._backoff_delay(3) == 8.0


def test_backoff_delay_capped_at_max(auth):
    """Backoff delay must not exceed max_delay."""
    client = HyperliquidClient(auth=auth, max_retries=10, base_delay=1.0, max_delay=5.0)
    assert client._backoff_delay(10) == 5.0


def test_zero_retries_raises_immediately(auth):
    """With max_retries=0, should fail on first attempt with no sleep."""
    client = HyperliquidClient(auth=auth, max_retries=0, base_delay=0.01)
    mock_response = make_mock_response(500, {"error": "server error"})
    mock_response.text = "server error"

    with patch("httpx.post", return_value=mock_response):
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(NetworkError):
                client.info({"type": "meta"})
            assert mock_sleep.call_count == 0


def test_handle_response_unknown_status_raises(auth):
    client = HyperliquidClient(auth=auth, max_retries=0)
    mock_response = make_mock_response(302, {})
    mock_response.text = "redirect"
    with patch("httpx.post", return_value=mock_response):
        with pytest.raises(APIError) as exc:
            client.info({"type": "meta"})
        assert exc.value.status_code == 302


def test_all_retries_exhausted_raises_last_exception(auth):
    client = HyperliquidClient(auth=auth, max_retries=2, base_delay=0.01)
    mock_response = make_mock_response(500, {"error": "server error"})
    mock_response.text = "server error"
    with patch("httpx.post", return_value=mock_response):
        with patch("time.sleep"):
            with pytest.raises(NetworkError):
                client.info({"type": "meta"})
