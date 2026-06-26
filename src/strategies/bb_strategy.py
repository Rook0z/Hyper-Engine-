from __future__ import annotations

import logging

from strategies.base_strategy import BaseStrategy
from indicators.bollinger import calculate_bollinger

logger = logging.getLogger(__name__)

MIDDLE_ZONE_LOW = 0.2
MIDDLE_ZONE_HIGH = 0.8


class BollingerStrategy(BaseStrategy):
    """
    Bollinger Bands Mean Reversion Strategy.

    Generates BUY when price crosses below the lower band (%B < 0).
    Generates SELL when price crosses above the upper band (%B > 1).
    Generates HOLD otherwise.

    Args:
        period:  SMA period for Bollinger Bands. Default 20.
        num_std: Number of standard deviations. Default 2.0.

    Raises:
        ValueError: if period < 2 or num_std <= 0

    Usage:
        strategy = BollingerStrategy(period=20, num_std=2.0)
        closes = [50000.0, ...]   # at least 20 values
        signal = strategy.generate_signal(closes)
    """

    def __init__(
        self,
        period: int = 20,
        num_std: float = 2.0,
    ) -> None:
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}.")
        if num_std <= 0:
            raise ValueError(f"num_std must be > 0, got {num_std}.")

        self.period = period
        self.num_std = num_std
        self._last_signal: str = self.HOLD

    @property
    def name(self) -> str:
        return f"Bollinger({self.period}, {self.num_std})"

    @property
    def min_periods(self) -> int:
        return self.period + 1

    def generate_signal(self, closes: list[float]) -> str:
        """
        Generates a trading signal from Bollinger Bands.

        Uses %B to detect when price crosses outside the bands:
            %B < 0.0 → price below lower band → BUY
            %B > 1.0 → price above upper band → SELL

        Args:
            closes: List of close prices, oldest first.

        Returns:
            "BUY"  — price crossed below lower band
            "SELL" — price crossed above upper band
            "HOLD" — price inside bands or not enough data
        """
        if len(closes) < self.min_periods:
            logger.debug(
                "%s: not enough data (%d/%d) — HOLD",
                self.name,
                len(closes),
                self.min_periods,
            )
            return self.HOLD

        bands = calculate_bollinger(closes, self.period, self.num_std)

        curr = bands[-1]
        prev = bands[-2]

        if curr.percent_b is None or prev.percent_b is None:
            return self.HOLD

        pb_curr = curr.percent_b
        pb_prev = prev.percent_b

        # Reset signal state when price returns to middle zone
        if MIDDLE_ZONE_LOW <= pb_curr <= MIDDLE_ZONE_HIGH:
            self._last_signal = self.HOLD

        # BUY: %B crossed below 0 (price crossed below lower band)
        crossed_lower = pb_prev >= 0.0 and pb_curr < 0.0
        if crossed_lower and self._last_signal != self.BUY:
            self._last_signal = self.BUY
            logger.debug(
                "%s: BUY — price crossed below lower band (%%B=%.4f)",
                self.name,
                pb_curr,
            )
            return self.BUY

        # SELL: %B crossed above 1 (price crossed above upper band)
        crossed_upper = pb_prev <= 1.0 and pb_curr > 1.0
        if crossed_upper and self._last_signal != self.SELL:
            self._last_signal = self.SELL
            logger.debug(
                "%s: SELL — price crossed above upper band (%%B=%.4f)",
                self.name,
                pb_curr,
            )
            return self.SELL

        return self.HOLD

    def get_band_values(
        self,
        closes: list[float],
    ) -> dict[str, list]:
        """
        Returns upper, middle, lower band values and %B for charting.

        Args:
            closes: List of close prices, oldest first.

        Returns:
            Dict with keys: upper, middle, lower, percent_b, bandwidth.
            Each value is a list of floats (None where not enough data).
        """
        bands = calculate_bollinger(closes, self.period, self.num_std)
        return {
            "upper": [b.upper for b in bands],
            "middle": [b.middle for b in bands],
            "lower": [b.lower for b in bands],
            "percent_b": [b.percent_b for b in bands],
            "bandwidth": [b.bandwidth for b in bands],
        }
