from __future__ import annotations

import logging

from strategies.base_strategy import BaseStrategy
from indicators.rsi import calculate_rsi

logger = logging.getLogger(__name__)

RSI_NEUTRAL_LOW = 40.0
RSI_NEUTRAL_HIGH = 60.0


class RSIStrategy(BaseStrategy):
    """
    RSI Overbought/Oversold Strategy.

    Generates BUY when RSI drops below oversold_threshold.
    Generates SELL when RSI rises above overbought_threshold.
    Generates HOLD otherwise.

    Args:
        period:               RSI calculation period. Default 14.
        oversold_threshold:   RSI level to trigger BUY. Default 30.
        overbought_threshold: RSI level to trigger SELL. Default 70.

    Raises:
        ValueError: if thresholds are invalid or period < 2

    Usage:
        strategy = RSIStrategy(period=14, oversold_threshold=30, overbought_threshold=70)
        closes = [50000.0, ...]   # at least 15 values (period + 1)
        signal = strategy.generate_signal(closes)
    """

    def __init__(
        self,
        period: int = 14,
        oversold_threshold: float = 30.0,
        overbought_threshold: float = 70.0,
    ) -> None:
        if period < 2:
            raise ValueError(f"period must be >= 2, got {period}.")
        if oversold_threshold >= overbought_threshold:
            raise ValueError(
                f"oversold_threshold ({oversold_threshold}) must be less than "
                f"overbought_threshold ({overbought_threshold})."
            )
        if not 0 < oversold_threshold < 100:
            raise ValueError(f"oversold_threshold must be between 0 and 100.")
        if not 0 < overbought_threshold < 100:
            raise ValueError(f"overbought_threshold must be between 0 and 100.")

        self.period = period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self._last_signal: str = self.HOLD

    @property
    def name(self) -> str:
        return (
            f"RSI({self.period}) "
            f"OB={self.overbought_threshold}/OS={self.oversold_threshold}"
        )

    @property
    def min_periods(self) -> int:
        # period + 1 closes needed to calculate first RSI value
        return self.period + 1

    def generate_signal(self, closes: list[float]) -> str:
        """
        Generates a trading signal from RSI.

        Args:
            closes: List of close prices, oldest first.

        Returns:
            "BUY"  — RSI crossed below oversold threshold
            "SELL" — RSI crossed above overbought threshold
            "HOLD" — RSI in neutral zone or not enough data
        """
        if len(closes) < self.min_periods:
            logger.debug(
                "%s: not enough data (%d/%d) — HOLD",
                self.name,
                len(closes),
                self.min_periods,
            )
            return self.HOLD

        rsi_values = calculate_rsi(closes, self.period)
        rsi_curr = rsi_values[-1]
        rsi_prev = rsi_values[-2]

        if rsi_curr is None or rsi_prev is None:
            return self.HOLD

        # BUY: RSI just crossed below oversold threshold
        # Transition: was above (or at) threshold, now below
        crossed_oversold = (
            rsi_prev >= self.oversold_threshold and rsi_curr < self.oversold_threshold
        )

        # SELL: RSI just crossed above overbought threshold
        # Transition: was below (or at) threshold, now above
        crossed_overbought = (
            rsi_prev <= self.overbought_threshold
            and rsi_curr > self.overbought_threshold
        )

        # Reset signal state when RSI returns to neutral zone
        # This allows the next oversold/overbought signal to fire
        if RSI_NEUTRAL_LOW <= rsi_curr <= RSI_NEUTRAL_HIGH:
            self._last_signal = self.HOLD

        if crossed_oversold and self._last_signal != self.BUY:
            self._last_signal = self.BUY
            logger.debug(
                "%s: BUY — RSI crossed below %.1f (RSI=%.2f)",
                self.name,
                self.oversold_threshold,
                rsi_curr,
            )
            return self.BUY

        if crossed_overbought and self._last_signal != self.SELL:
            self._last_signal = self.SELL
            logger.debug(
                "%s: SELL — RSI crossed above %.1f (RSI=%.2f)",
                self.name,
                self.overbought_threshold,
                rsi_curr,
            )
            return self.SELL

        return self.HOLD

    def get_rsi_values(self, closes: list[float]) -> list[float | None]:
        """
        Returns the full RSI series for charting or debugging.

        Args:
            closes: List of close prices, oldest first.

        Returns:
            List of RSI values. None where not enough data.
        """
        if len(closes) < self.min_periods:
            return [None] * len(closes)
        return calculate_rsi(closes, self.period)
