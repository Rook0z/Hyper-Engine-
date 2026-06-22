from __future__ import annotations

import logging

from strategies.base_strategy import BaseStrategy
from indicators.ema import calculate_ema

logger = logging.getLogger(__name__)


class EMAStrategy(BaseStrategy):
    """
    EMA Crossover Strategy.

    Generates BUY when fast EMA crosses above slow EMA.
    Generates SELL when fast EMA crosses below slow EMA.
    Generates HOLD otherwise.

    Args:
        fast_period: Period for the fast (reactive) EMA. Default 9.
        slow_period: Period for the slow (smooth) EMA. Default 21.

    Raises:
        ValueError: if fast_period >= slow_period

    Usage:
        strategy = EMAStrategy(fast_period=9, slow_period=21)
        closes = [50000.0, 50500.0, ...]   # at least 22 values
        signal = strategy.generate_signal(closes)
        # signal is "BUY", "SELL", or "HOLD"
    """

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError(
                f"fast_period ({fast_period}) must be less than "
                f"slow_period ({slow_period})."
            )
        if fast_period < 2:
            raise ValueError(f"fast_period must be >= 2, got {fast_period}.")

        self.fast_period = fast_period
        self.slow_period = slow_period
        self._last_crossover: str = self.HOLD

    @property
    def name(self) -> str:
        return f"EMA Crossover {self.fast_period}/{self.slow_period}"

    @property
    def min_periods(self) -> int:
        # Need slow_period closes to seed the slow EMA,
        # plus 1 more to have a "previous" bar to detect the crossover
        return self.slow_period + 1

    def generate_signal(self, closes: list[float]) -> str:
        """
        Generates a trading signal from close prices.

        Requires at least min_periods closes. Returns HOLD if not enough data.

        Args:
            closes: List of close prices, oldest first.

        Returns:
            "BUY"  — fast EMA just crossed above slow EMA
            "SELL" — fast EMA just crossed below slow EMA
            "HOLD" — no crossover detected or not enough data
        """
        if len(closes) < self.min_periods:
            logger.debug(
                "%s: not enough data (%d/%d) — HOLD",
                self.name,
                len(closes),
                self.min_periods,
            )
            return self.HOLD

        fast_ema = calculate_ema(closes, self.fast_period)
        slow_ema = calculate_ema(closes, self.slow_period)

        fast_curr = fast_ema[-1]
        fast_prev = fast_ema[-2]
        slow_curr = slow_ema[-1]
        slow_prev = slow_ema[-2]

        if any(v is None for v in [fast_curr, fast_prev, slow_curr, slow_prev]):
            return self.HOLD

        crossed_up = fast_prev <= slow_prev and fast_curr > slow_curr
        crossed_down = fast_prev >= slow_prev and fast_curr < slow_curr

        if crossed_up and self._last_crossover != self.BUY:
            self._last_crossover = self.BUY
            logger.debug(
                "%s: BUY — fast=%.4f crossed above slow=%.4f",
                self.name,
                fast_curr,
                slow_curr,
            )
            return self.BUY

        if crossed_down and self._last_crossover != self.SELL:
            self._last_crossover = self.SELL
            logger.debug(
                "%s: SELL — fast=%.4f crossed below slow=%.4f",
                self.name,
                fast_curr,
                slow_curr,
            )
            return self.SELL

        return self.HOLD

    def get_ema_values(
        self,
        closes: list[float],
    ) -> dict[str, list[float | None]]:
        """
        Returns both EMA series for charting or debugging.

        Args:
            closes: List of close prices, oldest first.

        Returns:
            Dict with "fast" and "slow" keys, each a list of EMA values.
            None where not enough data exists.
        """
        return {
            "fast": calculate_ema(closes, self.fast_period),
            "slow": calculate_ema(closes, self.slow_period),
        }
