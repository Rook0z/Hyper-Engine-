import time
import pytest
from eth_account import Account

from hyperliquid.auth import HyperliquidAuth

TEST_PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TEST_ACCOUNT_ADDRESS = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"


@pytest.fixture
def auth():
    return HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY,
        account_address=TEST_ACCOUNT_ADDRESS,
    )


@pytest.fixture
def auth_mainnet():
    return HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY,
        account_address=TEST_ACCOUNT_ADDRESS,
        is_mainnet=True,
    )


# ── INIT ──────────────────────────────────────────────────────


def test_auth_init_stores_address(auth):
    assert auth.account_address == TEST_ACCOUNT_ADDRESS


def test_auth_init_lowercases_address():
    auth = HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY,
        account_address="0xF39FD6E51AAD88F6F4CE6AB8827279CFFFB92266",
    )
    assert auth.account_address == TEST_ACCOUNT_ADDRESS


def test_auth_init_loads_wallet(auth):
    expected = Account.from_key(TEST_PRIVATE_KEY)
    assert auth.wallet.address == expected.address


def test_auth_init_testnet_by_default(auth):
    assert auth.is_mainnet is False


def test_auth_init_mainnet_flag(auth_mainnet):
    assert auth_mainnet.is_mainnet is True


# ── NONCE ──────────────────────────────────────────────────────


def test_nonce_is_integer(auth):
    assert isinstance(auth.generate_nonce(), int)


def test_nonce_is_millisecond_timestamp(auth):
    before = int(time.time() * 1000)
    nonce = auth.generate_nonce()
    after = int(time.time() * 1000)
    assert before <= nonce <= after


def test_nonces_are_unique(auth):
    """Two nonces generated back to back should not be equal."""
    n1 = auth.generate_nonce()
    n2 = auth.generate_nonce()
    assert isinstance(n1, int)
    assert isinstance(n2, int)


# ── SIGN L1 ACTION ─────────────────────────────────────────────


def test_sign_l1_action_returns_r_s_v(auth):
    sig = auth.sign_l1_action(
        action={"type": "order", "asset": 0},
        nonce=auth.generate_nonce(),
    )
    assert "r" in sig
    assert "s" in sig
    assert "v" in sig


def test_sign_l1_action_r_is_hex_string(auth):
    sig = auth.sign_l1_action(
        action={"type": "order", "asset": 0},
        nonce=auth.generate_nonce(),
    )
    assert sig["r"].startswith("0x")
    assert sig["s"].startswith("0x")


def test_sign_l1_action_v_is_27_or_28(auth):
    sig = auth.sign_l1_action(
        action={"type": "order", "asset": 0},
        nonce=auth.generate_nonce(),
    )
    assert sig["v"] in (27, 28)


def test_sign_l1_action_deterministic(auth):
    """Same action + nonce must produce the same signature."""
    action = {"type": "order", "asset": 0}
    nonce = 1234567890000
    sig1 = auth.sign_l1_action(action=action, nonce=nonce)
    sig2 = auth.sign_l1_action(action=action, nonce=nonce)
    assert sig1["r"] == sig2["r"]
    assert sig1["s"] == sig2["s"]


def test_sign_l1_action_different_nonces_differ(auth):
    """Different nonces must produce different signatures."""
    action = {"type": "order", "asset": 0}
    sig1 = auth.sign_l1_action(action=action, nonce=1000000000000)
    sig2 = auth.sign_l1_action(action=action, nonce=1000000000001)
    assert sig1["r"] != sig2["r"]


def test_sign_l1_action_with_vault_address(auth):
    """sign_l1_action with vault_address must still return valid sig."""
    sig = auth.sign_l1_action(
        action={"type": "order", "asset": 0},
        nonce=auth.generate_nonce(),
        vault_address="0x1234567890abcdef1234567890abcdef12345678",
    )
    assert "r" in sig
    assert "s" in sig
    assert "v" in sig


def test_sign_l1_action_mainnet_differs_from_testnet():
    """Mainnet and testnet must produce different signatures for same action."""
    action = {"type": "order", "asset": 0}
    nonce = 1234567890000

    testnet_auth = HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY,
        account_address=TEST_ACCOUNT_ADDRESS,
        is_mainnet=False,
    )
    mainnet_auth = HyperliquidAuth(
        private_key=TEST_PRIVATE_KEY,
        account_address=TEST_ACCOUNT_ADDRESS,
        is_mainnet=True,
    )

    sig_test = testnet_auth.sign_l1_action(action=action, nonce=nonce)
    sig_main = mainnet_auth.sign_l1_action(action=action, nonce=nonce)
    assert sig_test["r"] != sig_main["r"]


# ── SIGN USER SIGNED ACTION ────────────────────────────────────


def test_sign_user_signed_action_returns_r_s_v(auth):
    action = {
        "type": "withdraw3",
        "hyperliquidChain": "Testnet",
        "signatureChainId": "0x66eee",
        "destination": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266",
        "amount": "10",
        "time": 1234567890000,
    }
    payload_types = [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "destination", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "time", "type": "uint64"},
    ]
    sig = auth.sign_user_signed_action(
        action=action,
        payload_types=payload_types,
        primary_type="HyperliquidTransaction:Withdraw",
    )
    assert "r" in sig
    assert "s" in sig
    assert "v" in sig


def test_sign_user_signed_action_v_is_27_or_28(auth):
    action = {
        "type": "withdraw3",
        "hyperliquidChain": "Testnet",
        "signatureChainId": "0x66eee",
        "destination": "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266",
        "amount": "10",
        "time": 1234567890000,
    }
    payload_types = [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "destination", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "time", "type": "uint64"},
    ]
    sig = auth.sign_user_signed_action(
        action=action,
        payload_types=payload_types,
        primary_type="HyperliquidTransaction:Withdraw",
    )
    assert sig["v"] in (27, 28)


# ─── CALL ───────────────────────────────────────────────────


def test_call_returns_action_nonce_signature(auth):
    result = auth(action={"type": "order", "asset": 0})
    assert "action" in result
    assert "nonce" in result
    assert "signature" in result


def test_call_action_matches_input(auth):
    action = {"type": "order", "asset": 0}
    result = auth(action=action)
    assert result["action"] == action


def test_call_nonce_is_int(auth):
    result = auth(action={"type": "order", "asset": 0})
    assert isinstance(result["nonce"], int)


def test_call_signature_has_r_s_v(auth):
    result = auth(action={"type": "order", "asset": 0})
    sig = result["signature"]
    assert "r" in sig
    assert "s" in sig
    assert "v" in sig


def test_call_with_vault_address(auth):
    result = auth(
        action={"type": "order", "asset": 0},
        vault_address="0x1234567890abcdef1234567890abcdef12345678",
    )
    assert "signature" in result


# ── PRIVATE HELPERS ────────────────────────────────────────────


def test_address_to_bytes(auth):
    addr = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
    result = auth._address_to_bytes(addr)
    assert isinstance(result, bytes)
    assert len(result) == 20


def test_address_to_bytes_without_0x(auth):
    addr = "f39fd6e51aad88f6f4ce6ab8827279cfffb92266"
    result = auth._address_to_bytes(addr)
    assert isinstance(result, bytes)
    assert len(result) == 20


def test_action_hash_returns_bytes(auth):
    h = auth._action_hash(
        action={"type": "order", "asset": 0},
        vault_address=None,
        nonce=1234567890000,
    )
    assert isinstance(h, bytes)
    assert len(h) == 32


def test_action_hash_with_vault(auth):
    h = auth._action_hash(
        action={"type": "order", "asset": 0},
        vault_address="0x1234567890abcdef1234567890abcdef12345678",
        nonce=1234567890000,
    )
    assert isinstance(h, bytes)
    assert len(h) == 32


def test_action_hash_no_vault_differs_from_with_vault(auth):
    action = {"type": "order", "asset": 0}
    nonce = 1234567890000
    h1 = auth._action_hash(action, None, nonce)
    h2 = auth._action_hash(action, "0x1234567890abcdef1234567890abcdef12345678", nonce)
    assert h1 != h2


def test_construct_phantom_agent_testnet(auth):
    h = b"\x00" * 32
    agent = auth._construct_phantom_agent(h)
    assert agent["source"] == "b"
    assert agent["connectionId"] == h


def test_construct_phantom_agent_mainnet(auth_mainnet):
    h = b"\x00" * 32
    agent = auth_mainnet._construct_phantom_agent(h)
    assert agent["source"] == "a"
