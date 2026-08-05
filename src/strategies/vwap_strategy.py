from __future__ import annotations

import logging

from strategies.base_strategy import BaseStrategy
from indicators.vwap import calculate_vwap

logger = logging.getLogger(__name__)


class VWAPStrategy(BaseStrategy):
    """
    VWAP Strategy — two modes of operation.

    Note: uses a CUMULATIVE / ROLLING VWAP (see calculate_vwap() in
    indicators/vwap.py), not a session-anchored daily VWAP. It does not
    reset at the start of each trading day — it accumulates over
    whatever candle window is passed in (e.g. the full backtest range).
    Over long windows this behaves more like a slow-moving, volume-
    weighted trend line than institutional "average price paid today"
    VWAP. Session-based resets are a known follow-up, not yet implemented.

    Mode "crossover" (default):
        BUY  when price crosses above VWAP from below
        SELL when price crosses below VWAP from above
        Trend-following — rides institutional momentum

    Mode "reversion":
        BUY  when price crosses below lower band (price << VWAP)
        SELL when price crosses above upper band (price >> VWAP)
        Mean-reversion — fades extreme moves away from VWAP

    Args:
        mode:    "crossover" or "reversion". Default "crossover".
        num_std: Standard deviation multiplier for bands.
                 Only used in reversion mode. Default 2.0.

    Usage:
        strategy = VWAPStrategy(mode="crossover")
        # needs at least 2 candles to detect crossover
        signal = strategy.generate_signal_from_candles(candles)
    """

    CROSSOVER = "crossover"
    REVERSION = "reversion"

    def __init__(
        self,
        mode: str = "crossover",
        num_std: float = 2.0,
    ) -> None:
        if mode not in (self.CROSSOVER, self.REVERSION):
            raise ValueError(f"mode must be 'crossover' or 'reversion', got '{mode}'.")
        if num_std <= 0:
            raise ValueError(f"num_std must be > 0, got {num_std}.")

        self.mode = mode
        self.num_std = num_std
        self._last_signal: str = self.HOLD

    @property
    def name(self) -> str:
        return f"VWAP({self.mode})"

    @property
    def min_periods(self) -> int:
        # Need at least 2 candles to detect a crossover
        return 2

    def generate_signal(self, closes: list[float]) -> str:
        """
        Note: VWAP requires full OHLCV candles (not just closes)
        because it uses high, low, and volume in the formula.

        This method exists to satisfy the BaseStrategy interface.
        For VWAP, use generate_signal_from_candles() instead.

        When called with closes only, returns HOLD always.
        """
        logger.debug(
            "%s: generate_signal() called with closes only — "
            "use generate_signal_from_candles() for VWAP signals.",
            self.name,
        )
        return self.HOLD

    def generate_signal_from_candles(self, candles: list[list]) -> str:
        """
        Generates a VWAP trading signal from OHLCV candles.

        Args:
            candles: List of [timestamp, open, high, low, close, volume]
                     Sorted oldest → newest. At least 2 candles needed.

        Returns:
            "BUY", "SELL", or "HOLD"
        """
        if len(candles) < self.min_periods:
            return self.HOLD

        vwap_values = calculate_vwap(candles, self.num_std)

        curr = vwap_values[-1]
        prev = vwap_values[-2]

        curr_close = candles[-1][4]  # close price of current candle
        prev_close = candles[-2][4]  # close price of previous candle

        if self.mode == self.CROSSOVER:
            return self._crossover_signal(
                prev_close,
                curr_close,
                prev.vwap,
                curr.vwap,
            )
        else:
            return self._reversion_signal(curr, prev_close, curr_close)

    def _crossover_signal(
        self,
        prev_close: float,
        curr_close: float,
        prev_vwap: float,
        curr_vwap: float,
    ) -> str:
        """
        Crossover mode:
            BUY  when price crosses from below VWAP to above VWAP
            SELL when price crosses from above VWAP to below VWAP
        """
        # Reset signal state when price is near VWAP (within 0.1%).
        # Guard against curr_vwap == 0 (degenerate zero-price input) to
        # avoid a ZeroDivisionError — treat that case as "not near VWAP"
        # rather than crashing.
        near_vwap = curr_vwap != 0 and abs(curr_close - curr_vwap) / curr_vwap < 0.001
        if near_vwap:
            self._last_signal = self.HOLD

        crossed_above = prev_close <= prev_vwap and curr_close > curr_vwap
        crossed_below = prev_close >= prev_vwap and curr_close < curr_vwap

        if crossed_above and self._last_signal != self.BUY:
            self._last_signal = self.BUY
            logger.debug(
                "%s: BUY — price crossed above VWAP (close=%.2f vwap=%.2f)",
                self.name,
                curr_close,
                curr_vwap,
            )
            return self.BUY

        if crossed_below and self._last_signal != self.SELL:
            self._last_signal = self.SELL
            logger.debug(
                "%s: SELL — price crossed below VWAP (close=%.2f vwap=%.2f)",
                self.name,
                curr_close,
                curr_vwap,
            )
            return self.SELL

        return self.HOLD

    def _reversion_signal(
        self,
        curr,
        prev_close: float,
        curr_close: float,
    ) -> str:
        """
        Reversion mode:
            BUY  when price crosses below lower band (%B equivalent < 0)
            SELL when price crosses above upper band (%B equivalent > 1)
        """
        # Reset when price returns to within bands
        within_bands = curr.lower2 <= curr_close <= curr.upper2
        if within_bands:
            self._last_signal = self.HOLD

        crossed_below_lower = prev_close >= curr.lower2 and curr_close < curr.lower2
        crossed_above_upper = prev_close <= curr.upper2 and curr_close > curr.upper2

        if crossed_below_lower and self._last_signal != self.BUY:
            self._last_signal = self.BUY
            logger.debug(
                "%s: BUY — price below lower band (close=%.2f lower=%.2f)",
                self.name,
                curr_close,
                curr.lower2,
            )
            return self.BUY

        if crossed_above_upper and self._last_signal != self.SELL:
            self._last_signal = self.SELL
            logger.debug(
                "%s: SELL — price above upper band (close=%.2f upper=%.2f)",
                self.name,
                curr_close,
                curr.upper2,
            )
            return self.SELL

        return self.HOLD

    def get_vwap_values(self, candles: list[list]) -> list[dict]:
        """
        Returns VWAP values for all candles as a list of dicts for charting.

        Args:
            candles: List of OHLCV candles

        Returns:
            List of dicts with vwap, upper1, lower1, upper2, lower2, deviation
        """
        values = calculate_vwap(candles, self.num_std)
        return [
            {
                "vwap": v.vwap,
                "upper1": v.upper1,
                "lower1": v.lower1,
                "upper2": v.upper2,
                "lower2": v.lower2,
                "deviation": v.deviation,
            }
            for v in values
        ]
