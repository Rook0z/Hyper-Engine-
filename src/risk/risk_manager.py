from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    """
    Result of a risk check.

    allowed:       True if the trade is allowed to proceed
    reason:        Why it was blocked (empty string if allowed)
    position_size: Approved position size (may be reduced from requested)
    """

    allowed: bool
    reason: str = ""
    position_size: float = 0.0


class RiskManager:
    """
    Controls position sizing and enforces risk limits.

    Args:
        account_balance:      Current account value in USDC
        max_position_pct:     Max position size as % of account (default 10%)
        max_daily_loss_pct:   Stop trading if daily loss exceeds this % (default 5%)
        max_open_positions:   Maximum concurrent open positions (default 3)
        min_position_size:    Minimum order size in base currency (default 0.001)

    Usage:
        rm = RiskManager(account_balance=10_000.0)

        # Check before placing a trade
        result = rm.check_trade(
            symbol="BTC",
            price=50_000.0,
            requested_size=0.01,
            current_daily_loss=0.0,
            open_positions=0,
        )
        if result.allowed:
            trading.place_limit_order("BTC", True, price, result.position_size)
        else:
            print(f"Trade blocked: {result.reason}")
    """

    def __init__(
        self,
        account_balance: float,
        max_position_pct: float = 0.10,
        max_daily_loss_pct: float = 0.05,
        max_open_positions: int = 3,
        min_position_size: float = 0.001,
    ) -> None:
        if account_balance <= 0:
            raise ValueError(f"account_balance must be > 0, got {account_balance}")
        if not 0 < max_position_pct <= 1:
            raise ValueError(
                f"max_position_pct must be between 0 and 1, got {max_position_pct}"
            )
        if not 0 < max_daily_loss_pct <= 1:
            raise ValueError(
                f"max_daily_loss_pct must be between 0 and 1, got {max_daily_loss_pct}"
            )
        if max_open_positions < 1:
            raise ValueError(
                f"max_open_positions must be >= 1, got {max_open_positions}"
            )
        if min_position_size <= 0:
            raise ValueError(
                f"min_position_size must be > 0, got {min_position_size}. "
                f"A non-positive minimum silently disables the minimum-size "
                f"safety floor in check_position_size()."
            )

        self.account_balance = account_balance
        self.max_position_pct = max_position_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_open_positions = max_open_positions
        self.min_position_size = min_position_size

    # ──────────────────────────────────────────────────────────────
    # MAIN INTERFACE
    # ──────────────────────────────────────────────────────────────

    def check_trade(
        self,
        symbol: str,
        price: float,
        requested_size: float,
        current_daily_loss: float = 0.0,
        open_positions: int = 0,
    ) -> RiskCheckResult:
        """
        Full risk check before placing a trade.

        Checks in order:
            1. Daily loss limit not breached
            2. Max open positions not exceeded
            3. Position size within limits

        Returns the first failing check. If all pass, returns
        an approved RiskCheckResult with the final position size.

        Args:
            symbol:             e.g. "BTC"
            price:              current price in USDC
            requested_size:     how much base currency you want to buy
            current_daily_loss: how much USDC you've lost today (positive number)
            open_positions:     number of currently open positions

        Returns:
            RiskCheckResult with allowed=True/False and reason if blocked.
        """
        # Check 1: daily loss limit
        daily_check = self.check_daily_loss_limit(current_daily_loss)
        if not daily_check.allowed:
            return daily_check

        # Check 2: max open positions
        position_check = self.check_max_positions(open_positions)
        if not position_check.allowed:
            return position_check

        # Check 3: position size
        size_check = self.check_position_size(price, requested_size)
        if not size_check.allowed:
            return size_check

        logger.debug(
            "Trade approved: %s size=%.4f price=%.2f",
            symbol,
            size_check.position_size,
            price,
        )
        return size_check

    def check_daily_loss_limit(self, current_daily_loss: float) -> RiskCheckResult:
        """
        Blocks trading if daily loss exceeds the limit.

        Args:
            current_daily_loss: Total loss today in USDC (positive number).
                                e.g. 200.0 means you've lost $200 today.

        Returns:
            RiskCheckResult — blocked if loss exceeds max_daily_loss_pct of balance.
        """
        if current_daily_loss < 0:
            raise ValueError(
                "current_daily_loss must be >= 0 (it's a loss amount, not a signed value)."
            )

        max_loss = self.account_balance * self.max_daily_loss_pct
        if current_daily_loss >= max_loss:
            reason = (
                f"Daily loss limit breached: lost {current_daily_loss:.2f} USDC "
                f"(limit: {max_loss:.2f} USDC = {self.max_daily_loss_pct:.0%} of balance). "
                f"No more trading today."
            )
            logger.warning(reason)
            return RiskCheckResult(allowed=False, reason=reason, position_size=0.0)

        return RiskCheckResult(allowed=True, position_size=0.0)

    def check_max_positions(self, open_positions: int) -> RiskCheckResult:
        """
        Blocks new trades if max open positions already reached.

        Args:
            open_positions: number of currently open positions

        Returns:
            RiskCheckResult — blocked if at or above max.
        """
        if open_positions >= self.max_open_positions:
            reason = (
                f"Max open positions reached: {open_positions}/{self.max_open_positions}. "
                f"Close a position before opening a new one."
            )
            logger.warning(reason)
            return RiskCheckResult(allowed=False, reason=reason, position_size=0.0)

        return RiskCheckResult(allowed=True, position_size=0.0)

    def check_position_size(
        self,
        price: float,
        requested_size: float,
    ) -> RiskCheckResult:
        """
        Validates and adjusts position size.

        Caps size at max_position_pct of account balance.
        Returns min_position_size as approved size if capped size is too small.

        Args:
            price:          current asset price in USDC
            requested_size: how much base currency you want to buy

        Returns:
            RiskCheckResult with approved position_size.
        """
        if price <= 0:
            raise ValueError(f"price must be > 0, got {price}")
        if requested_size <= 0:
            raise ValueError(f"requested_size must be > 0, got {requested_size}")

        # Max value we allow in this position
        max_value = self.account_balance * self.max_position_pct
        max_size = max_value / price

        approved_size = min(requested_size, max_size)

        if approved_size < self.min_position_size:
            reason = (
                f"Approved position size {approved_size:.6f} is below minimum "
                f"{self.min_position_size:.6f}. Trade too small."
            )
            logger.warning(reason)
            return RiskCheckResult(allowed=False, reason=reason, position_size=0.0)

        if approved_size < requested_size:
            logger.info(
                "Position size reduced: %.4f → %.4f (max position %.1f%% of balance)",
                requested_size,
                approved_size,
                self.max_position_pct * 100,
            )

        return RiskCheckResult(allowed=True, position_size=approved_size)

    # ──────────────────────────────────────────────────────────────
    # POSITION SIZING
    # ──────────────────────────────────────────────────────────────

    def fixed_position_size(self, price: float) -> float:
        """
        Fixed fractional position sizing — max_position_pct of balance.

        The simplest position sizing method. Always risks the same
        percentage of your account on each trade.

        Args:
            price: current asset price in USDC

        Returns:
            Position size in base currency.
        """
        value = self.account_balance * self.max_position_pct
        return value / price

    def kelly_position_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        price: float,
        kelly_fraction: float = 0.25,
    ) -> float:
        """
        Kelly criterion position sizing.

        The Kelly criterion calculates the mathematically optimal fraction
        of your account to risk on each trade to maximize long-term growth.

        Formula:
            b = avg_win / abs(avg_loss)   (win/loss ratio)
            p = win_rate
            q = 1 - win_rate
            kelly% = (b * p - q) / b

        Why kelly_fraction < 1.0?
            Full Kelly is extremely aggressive and leads to large drawdowns.
            Most professional traders use Quarter Kelly (0.25) or Half Kelly (0.5)
            to smooth the equity curve at the cost of slightly lower growth.

        Args:
            win_rate:      fraction of winning trades (e.g. 0.6 = 60%)
            avg_win:       average profit on winning trades (positive float)
            avg_loss:      average loss on losing trades (positive float — absolute value)
            price:         current asset price in USDC
            kelly_fraction: fraction of full Kelly to use (default 0.25 = Quarter Kelly)

        Returns:
            Position size in base currency.
            Returns min_position_size if Kelly is negative (no edge).

        Raises:
            ValueError: if inputs are invalid
        """
        if not 0 < win_rate < 1:
            raise ValueError(f"win_rate must be between 0 and 1, got {win_rate}")
        if avg_win <= 0:
            raise ValueError(f"avg_win must be > 0, got {avg_win}")
        if avg_loss <= 0:
            raise ValueError(f"avg_loss must be > 0 (absolute value), got {avg_loss}")
        if price <= 0:
            raise ValueError(f"price must be > 0, got {price}")
        if not 0 < kelly_fraction <= 1:
            raise ValueError(
                f"kelly_fraction must be between 0 and 1, got {kelly_fraction}"
            )

        loss_rate = 1 - win_rate
        win_loss_ratio = avg_win / avg_loss

        # Kelly formula
        kelly_pct = (win_loss_ratio * win_rate - loss_rate) / win_loss_ratio

        if kelly_pct <= 0:
            logger.warning(
                "Kelly criterion is negative (%.4f) — strategy has no edge. "
                "Using minimum position size.",
                kelly_pct,
            )
            return self.min_position_size

        # Apply fraction and cap at max position percentage
        fractional_kelly = kelly_pct * kelly_fraction
        capped_kelly = min(fractional_kelly, self.max_position_pct)

        value = self.account_balance * capped_kelly
        size = value / price

        logger.debug(
            "Kelly sizing: win_rate=%.1f%%, win/loss=%.2f, "
            "full_kelly=%.2f%%, quarter_kelly=%.2f%%, size=%.4f",
            win_rate * 100,
            win_loss_ratio,
            kelly_pct * 100,
            fractional_kelly * 100,
            size,
        )

        return max(size, self.min_position_size)

    def update_balance(self, new_balance: float) -> None:
        """
        Updates account balance — call after each trade settles.

        Args:
            new_balance: new account value in USDC
        """
        if new_balance <= 0:
            raise ValueError(f"new_balance must be > 0, got {new_balance}")
        old = self.account_balance
        self.account_balance = new_balance
        logger.debug("Balance updated: %.2f → %.2f", old, new_balance)
