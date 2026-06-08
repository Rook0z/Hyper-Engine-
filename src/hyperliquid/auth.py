import time
from typing import Any
from eth_account import Account
from eth_account.signers.local import LocalAccount


class HyperliquidAuth:
    """
    Signs requests for the Hyperliquid API.

    Args:
        private_key:     Ethereum private key (hex string, with or without 0x prefix)
        account_address: Master account wallet address (not the API wallet address)
    """

    def __init__(self, private_key: str, account_address: str) -> None:
        self.wallet: LocalAccount = Account.from_key(private_key)
        self.account_address: str = account_address.lower()

    def generate_nonce(self) -> int:
        """
        Returns current time in milliseconds.
        Nonces must be strictly increasing per signer address.
        """
        return int(time.time() * 1000)

    def sign_l1_action(
        self,
        action: dict[str, Any],
        nonce: int,
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Signs a trading action (order, cancel) using the phantom agent construction.
        Uses EIP-712 with chain ID 1337.

        Args:
            action:        The action payload dict (e.g. {"type": "order", ...})
            nonce:         Millisecond timestamp nonce
            vault_address: Optional vault address if trading on behalf of a vault

        Returns:
            Signature dict with r, s, v fields
        """
        raise NotImplementedError

    def sign_user_signed_action(
        self,
        action: dict[str, Any],
        payload_types: list[dict[str, str]],
        primary_type: str,
        chain_id: int,
    ) -> dict[str, Any]:
        """
        Signs a user-facing action (withdraw, transfer, approveAgent).
        Uses EIP-712 directly with the provided chain ID.

        Args:
            action:        The action payload dict
            payload_types: EIP-712 type definitions for this action
            primary_type:  EIP-712 primary type name
            chain_id:      Chain ID (e.g. 42161 for Arbitrum, 998 for Hyperliquid EVM)

        Returns:
            Signature dict with r, s, v fields
        """
        raise NotImplementedError

    def __call__(
        self,
        action: dict[str, Any],
        vault_address: str | None = None,
    ) -> dict[str, Any]:
        """
        Builds a complete signed request body ready to POST to /exchange.

        Returns:
            {
                "action": action,
                "nonce": <millisecond timestamp>,
                "signature": { "r": ..., "s": ..., "v": ... }
            }
        """
        raise NotImplementedError
