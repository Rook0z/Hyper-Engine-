# src/hyperliquid/auth.py
# Hyperliquid Authentication & Request Signing
#
# How it works (plain English):
# ─────────────────────────────
# Hyperliquid is a blockchain. Your identity is an Ethereum wallet.
# Instead of API key + secret, you prove who you are by cryptographically
# signing every request with your wallet's private key.
#
# Two signing schemes exist:
#   1. sign_l1_action()          → trading actions (order, cancel)
#   2. sign_user_signed_action() → user actions (withdraw, transfer, approveAgent)
#
# L1 action signing flow:
#   action dict → msgpack serialize → keccak256 hash → "phantom agent" → EIP-712 sign
#
# The phantom agent is just a small dict {"source": "a", "connectionId": <hash>}
# that acts as a temporary proxy identity for your action.
# "source" = "a" for mainnet, "b" for testnet.

import time
from typing import Any

import msgpack
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_account.signers.local import LocalAccount
from eth_utils import keccak, to_hex


class HyperliquidAuth:
    """
    Signs requests for the Hyperliquid API.

    Args:
        private_key:     Ethereum private key (hex string, with or without 0x prefix)
        account_address: Master account wallet address (NOT the API wallet address)
        is_mainnet:      True for mainnet, False for testnet (default: False — always testnet first)
    """

    def __init__(
        self,
        private_key: str,
        account_address: str,
        is_mainnet: bool = False,
    ) -> None:
        self.wallet: LocalAccount = Account.from_key(private_key)
        self.account_address: str = account_address.lower()
        self.is_mainnet: bool = is_mainnet

    def generate_nonce(self) -> int:
        """
        Returns current time in milliseconds.

        Nonces must be strictly increasing per signer address.
        The top 100 nonces are stored per signer on Hyperliquid's side.
        Using millisecond timestamps guarantees uniqueness in normal usage.
        """
        return int(time.time() * 1000)

    # ──────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────

    def _address_to_bytes(self, address: str) -> bytes:
        """Strips 0x prefix and converts hex address to raw bytes."""
        return bytes.fromhex(address[2:] if address.startswith("0x") else address)

    def _action_hash(
        self,
        action: Any,
        vault_address: str | None,
        nonce: int,
    ) -> bytes:
        """
        Hashes the action payload using msgpack + keccak256.

        Steps:
          1. Serialize the action dict with msgpack (field order matters!)
          2. Append the nonce as an 8-byte big-endian integer
          3. Append vault address indicator byte:
             - b"\\x00" if no vault
             - b"\\x01" + vault address bytes if vault present
          4. keccak256 hash the whole thing

        This hash becomes the "connectionId" of the phantom agent.
        """
        data = msgpack.packb(action)
        data += nonce.to_bytes(8, "big")

        if vault_address is None:
            data += b"\x00"
        else:
            data += b"\x01"
            data += self._address_to_bytes(vault_address)

        return keccak(data)

    def _construct_phantom_agent(self, hash: bytes) -> dict[str, Any]:
        """
        Wraps the action hash in a phantom agent dict.

        The phantom agent is what actually gets EIP-712 signed.
        source = "a" for mainnet, "b" for testnet.
        """
        return {
            "source": "a" if self.is_mainnet else "b",
            "connectionId": hash,
        }

    def _l1_payload(self, phantom_agent: dict[str, Any]) -> dict[str, Any]:
        """
        Wraps phantom agent in the full EIP-712 payload structure.

        This is the standard EIP-712 typed data envelope:
        - domain: identifies the signing contract (chainId 1337, Exchange)
        - types: defines the shape of the Agent struct
        - primaryType: tells EIP-712 which type to sign
        - message: the actual phantom agent data
        """
        return {
            "domain": {
                "chainId": 1337,
                "name": "Exchange",
                "verifyingContract": "0x0000000000000000000000000000000000000000",
                "version": "1",
            },
            "types": {
                "Agent": [
                    {"name": "source", "type": "string"},
                    {"name": "connectionId", "type": "bytes32"},
                ],
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
            },
            "primaryType": "Agent",
            "message": phantom_agent,
        }

    def _user_signed_payload(
        self,
        primary_type: str,
        payload_types: list[dict[str, str]],
        action: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Builds EIP-712 payload for user-signed actions (withdraw, transfer, etc).

        Unlike L1 actions, user-signed actions are signed directly —
        no phantom agent, no msgpack. The action itself IS the message.
        """
        chain_id = int(action["signatureChainId"], 16)
        return {
            "domain": {
                "name": "HyperliquidSignTransaction",
                "version": "1",
                "chainId": chain_id,
                "verifyingContract": "0x0000000000000000000000000000000000000000",
            },
            "types": {
                primary_type: payload_types,
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
            },
            "primaryType": primary_type,
            "message": action,
        }

    def _sign_inner(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        The actual signing step. Takes a fully built EIP-712 payload,
        encodes it, signs it with the wallet, and returns {r, s, v}.

        r, s, v are the three components of an Ethereum ECDSA signature.
        """
        structured_data = encode_typed_data(full_message=data)
        signed = self.wallet.sign_message(structured_data)
        return {
            "r": to_hex(signed["r"]),
            "s": to_hex(signed["s"]),
            "v": signed["v"],
        }

    # ──────────────────────────────────────────────────────────────
    # PUBLIC SIGNING METHODS
    # ──────────────────────────────────────────────────────────────

    def sign_l1_action(
        self,
        action: dict[str, Any],
        nonce: int,
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Signs a trading action (order, cancel) using the phantom agent construction.

        Full flow:
          action → msgpack → keccak256 → phantom agent → EIP-712 payload → sign → {r, s, v}

        Args:
            action:        The action payload dict (e.g. {"type": "order", ...})
            nonce:         Millisecond timestamp nonce from generate_nonce()
            vault_address: Optional vault address if trading on behalf of a vault

        Returns:
            Signature dict: {"r": "0x...", "s": "0x...", "v": 27 or 28}
        """
        hash = self._action_hash(action, vault_address, nonce)
        phantom_agent = self._construct_phantom_agent(hash)
        payload = self._l1_payload(phantom_agent)
        return self._sign_inner(payload)

    def sign_user_signed_action(
        self,
        action: dict[str, Any],
        payload_types: list[dict[str, str]],
        primary_type: str,
    ) -> dict[str, Any]:
        """
        Signs a user-facing action (withdraw, transfer, approveAgent).

        Unlike L1 actions, these are signed directly via EIP-712.
        signatureChainId is set to Hyperliquid EVM (0x66eee).
        hyperliquidChain determines mainnet vs testnet environment.

        Args:
            action:        The action payload dict
            payload_types: EIP-712 type definitions for this action
            primary_type:  EIP-712 primary type name (e.g. "HyperliquidTransaction:Withdraw")

        Returns:
            Signature dict: {"r": "0x...", "s": "0x...", "v": 27 or 28}
        """
        # These two fields are added to the action before signing
        action["signatureChainId"] = "0x66eee"
        action["hyperliquidChain"] = "Mainnet" if self.is_mainnet else "Testnet"

        payload = self._user_signed_payload(primary_type, payload_types, action)
        return self._sign_inner(payload)

    def __call__(
        self,
        action: dict[str, Any],
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Builds a complete signed request body ready to POST to /exchange.

        This is the convenience method — it generates the nonce, signs the action,
        and assembles the full request body in one call.

        Usage:
            auth = HyperliquidAuth(private_key=..., account_address=...)
            body = auth(action={"type": "order", ...})
            # body is ready to POST directly to /exchange

        Returns:
            {
                "action": action,
                "nonce": <millisecond timestamp>,
                "signature": {"r": "0x...", "s": "0x...", "v": 27}
            }
        """
        nonce = self.generate_nonce()
        signature = self.sign_l1_action(action, nonce, vault_address)
        return {
            "action": action,
            "nonce": nonce,
            "signature": signature,
        }
