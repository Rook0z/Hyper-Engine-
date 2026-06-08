import time
from hyperliquid.auth import HyperliquidAuth

# Test private key — not a real wallet, just for testing
TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ACCOUNT_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"


def test_auth_init():
    """Auth loads wallet and stores account address correctly."""
    auth = HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY, account_address=TEST_ACCOUNT_ADDRESS
    )
    assert auth.account_address == TEST_ACCOUNT_ADDRESS


def test_nonce_is_millisecond_timestamp():
    """Nonce must be current time in milliseconds."""
    auth = HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY, account_address=TEST_ACCOUNT_ADDRESS
    )
    before = int(time.time() * 1000)
    nonce = auth.generate_nonce()
    after = int(time.time() * 1000)
    assert isinstance(nonce, int)
    assert before <= nonce <= after


def test_sign_l1_action_returns_valid_signature():
    """L1 action signature must have r, s, v fields."""
    auth = HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY, account_address=TEST_ACCOUNT_ADDRESS
    )
    action = {"type": "order", "asset": 0}
    nonce = auth.generate_nonce()
    signature = auth.sign_l1_action(action=action, nonce=nonce)
    assert "r" in signature
    assert "s" in signature
    assert "v" in signature


def test_call_returns_signed_request_body():
    """__call__ must return action + nonce + signature dict."""
    auth = HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY, account_address=TEST_ACCOUNT_ADDRESS
    )
    action = {"type": "order", "asset": 0}
    result = auth(action=action)
    assert "action" in result
    assert "nonce" in result
    assert "signature" in result
