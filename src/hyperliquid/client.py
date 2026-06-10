import logging
from typing import Any

import httpx

from hyperliquid.auth import HyperliquidAuth

logger = logging.getLogger(__name__)

TESTNET_URL = "https://api.hyperliquid-testnet.xyz"
MAINNET_URL = "https://api.hyperliquid.xyz"


class APIError(Exception):
    """Raised when the API returns a 4xx error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"API error {status_code}: {message}")


class RateLimitError(APIError):
    """Raised when the API returns 429 Too Many Requests."""


class NetworkError(Exception):
    """Raised on 5xx errors or connection failures — eligible for retry."""


class HyperliquidClient:
    """
    HTTP client for the Hyperliquid REST API.

    Args:
        auth:     HyperliquidAuth instance for signing exchange requests.
                  Pass None for info-only usage (no trading).
        base_url: API base URL. Defaults to testnet — always testnet first.
        timeout:  Request timeout in seconds. Default 10.

    Usage:
        auth = HyperliquidAuth(private_key=..., account_address=...)
        client = HyperliquidClient(auth=auth)

        # Read data — no signing
        state = client.info({"type": "clearinghouseState", "user": "0x..."})

        # Write data — auto-signed
        result = client.exchange({"type": "order", ...})
    """

    def __init__(
        self,
        auth: HyperliquidAuth | None = None,
        base_url: str = TESTNET_URL,
        timeout: float = 10.0,
    ) -> None:
        self.auth = auth
        self.base_url = base_url
        self.timeout = timeout

    # ──────────────────────────────────────────────────────────────
    # PUBLIC METHODS
    # ──────────────────────────────────────────────────────────────

    def info(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        POST to /info — read-only, no signature required.

        Args:
            payload: Request body. Must contain a "type" field.
                     Example: {"type": "clearinghouseState", "user": "0x..."}

        Returns:
            Parsed JSON response as a dict.
        """
        logger.debug("INFO request: %s", payload.get("type"))
        return self._post("/info", payload)

    def exchange(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        POST to /exchange — write operations, must be signed.

        Calls self.auth(action) to build the signed request body,
        then POSTs it to /exchange.

        Args:
            action: The action dict. Example: {"type": "order", "asset": 0, ...}

        Returns:
            Parsed JSON response as a dict.

        Raises:
            ValueError: If no auth instance was provided.
        """
        if self.auth is None:
            raise ValueError(
                "HyperliquidClient requires an auth instance for exchange requests. "
                "Pass auth=HyperliquidAuth(...) when creating the client."
            )

        signed_body = self.auth(action)
        logger.debug("EXCHANGE request: %s", action.get("type"))
        return self._post("/exchange", signed_body)

    # ──────────────────────────────────────────────────────────────
    # PRIVATE METHODS
    # ──────────────────────────────────────────────────────────────

    def _post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        """
        Base POST method. Handles headers, timeout, error handling, logging.

        All requests go through here — info and exchange both use this.
        """
        url = self.base_url + endpoint
        headers = {"Content-Type": "application/json"}

        try:
            response = httpx.post(
                url,
                json=body,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as e:
            raise NetworkError(f"Request timed out after {self.timeout}s: {e}") from e
        except httpx.ConnectError as e:
            raise NetworkError(f"Connection failed to {url}: {e}") from e

        logger.debug("Response %s from %s", response.status_code, endpoint)

        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """
        Parses the response and raises the right error for each status code.

        200 → return parsed JSON
        429 → RateLimitError
        4xx → APIError
        5xx → NetworkError
        """
        if response.status_code == 200:
            try:
                return response.json()
            except Exception as e:
                raise APIError(
                    200, f"Failed to parse JSON response: {response.text}"
                ) from e

        if response.status_code == 429:
            raise RateLimitError(429, "Rate limited — wait before retrying")

        if 400 <= response.status_code < 500:
            try:
                error_body = response.json()
                message = error_body.get("error", response.text)
            except Exception:
                message = response.text
            raise APIError(response.status_code, message)

        if response.status_code >= 500:
            raise NetworkError(f"Server error {response.status_code}: {response.text}")

        raise APIError(response.status_code, response.text)
