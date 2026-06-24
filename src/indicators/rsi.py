from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def calculate_rsi(
    closes: list[float],
    period: int = 14,
) -> list[float | None]:
    """
    Calculates RSI for a list of closing prices using Wilder smoothing.

    Args:
        closes: List of close prices, oldest first.
                Minimum length: period + 1
        period: RSI period. Default 14 (Wilder's original).
                Common values: 14 (standard), 9 (fast), 21 (slow)

    Returns:
        List of RSI values, same length as closes.
        First `period` values are None — not enough data yet.
        Values range from 0.0 to 100.0.

    Raises:
        ValueError: if period < 2 or closes is empty or period >= len(closes)

    Hand-calculated example (period=3, closes=[10,11,12,11,13,12,14]):
        Changes:     +1, +1, -1, +2, -1, +2
        Gains:        1,  1,  0,  2,  0,  2
        Losses:       0,  0,  1,  0,  1,  0

        First avg (mean of first 3):
            avg_gain = (1+1+0)/3 = 0.667
            avg_loss = (0+0+1)/3 = 0.333

        Wilder smoothing for change[3]=+2:
            avg_gain = (0.667*2 + 2) / 3 = 1.111
            avg_loss = (0.333*2 + 0) / 3 = 0.222
            RS  = 1.111/0.222 = 5.0
            RSI = 100 - 100/(1+5) = 83.33
    """
    if not closes:
        raise ValueError("closes cannot be empty.")
    if period < 2:
        raise ValueError(f"period must be >= 2, got {period}.")
    if period >= len(closes):
        raise ValueError(
            f"period ({period}) must be less than number of closes ({len(closes)}). "
            f"Need at least {period + 1} closes."
        )

    # Calculate price changes
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    # Separate gains and losses
    gains = [max(c, 0.0) for c in changes]
    losses = [abs(min(c, 0.0)) for c in changes]

    # Result array — None for first `period` closes (no RSI yet)
    result: list[float | None] = [None] * period

    # First average — simple mean of first `period` changes
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # First RSI value
    result.append(_rsi_from_averages(avg_gain, avg_loss))

    # Wilder smoothing for all remaining bars
    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result.append(_rsi_from_averages(avg_gain, avg_loss))

    logger.debug(
        "RSI(%d) calculated over %d closes — latest: %.2f",
        period,
        len(closes),
        result[-1] if result[-1] is not None else 0,
    )

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    """
    Converts average gain and average loss to RSI value.

    Special cases:
        avg_loss == 0, avg_gain > 0  → RSI = 100 (pure up move)
        avg_loss == 0, avg_gain == 0 → RSI = 50  (no movement)
    """
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def rsi_latest(closes: list[float], period: int = 14) -> float:
    """
    Returns only the most recent RSI value.

    Convenience function for live trading.

    Args:
        closes: List of close prices, oldest first.
        period: RSI period.

    Returns:
        Latest RSI value as float (0.0 to 100.0).

    Raises:
        ValueError: same as calculate_rsi()
    """
    values = calculate_rsi(closes, period)
    latest = values[-1]
    if latest is None:
        raise ValueError(
            f"Not enough data for RSI({period}). "
            f"Need at least {period + 1} closes, got {len(closes)}."
        )
    return latest
