from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def calculate_ema(
    closes: list[float],
    period: int,
) -> list[float | None]:
    """
    Calculates EMA for a list of closing prices.

    Args:
        closes: List of close prices, oldest first.
                e.g. [50000.0, 50500.0, 51000.0, ...]
        period: EMA period. e.g. 9 for fast EMA, 21 for slow EMA.
                Must be >= 2 and <= len(closes).

    Returns:
        List of EMA values, same length as closes.
        First (period - 1) values are None — not enough data to calculate.
        e.g. for period=3, closes=[1,2,3,4,5]:
             returns [None, None, 2.0, 2.5, 3.25]

    Raises:
        ValueError: if period < 2 or closes is empty or period > len(closes)
    """
    if not closes:
        raise ValueError("closes cannot be empty.")
    if period < 2:
        raise ValueError(f"period must be >= 2, got {period}.")
    if period > len(closes):
        raise ValueError(
            f"period ({period}) cannot exceed number of closes ({len(closes)})."
        )

    multiplier = 2.0 / (period + 1)

    # Seed: simple mean of first `period` closes
    seed = sum(closes[:period]) / period

    # Build result list — None for values before we have enough data
    result: list[float | None] = [None] * (period - 1)
    result.append(seed)

    # Calculate EMA for every remaining close
    prev_ema = seed
    for close in closes[period:]:
        ema = close * multiplier + prev_ema * (1 - multiplier)
        result.append(ema)
        prev_ema = ema

    logger.debug(
        "EMA(%d) calculated over %d closes — first value: %.4f, last: %.4f",
        period,
        len(closes),
        seed,
        result[-1],  # type: ignore
    )

    return result


def ema_latest(closes: list[float], period: int) -> float:
    """
    Returns only the most recent EMA value.

    Convenience function for live trading — you usually only need
    the current EMA value, not the full history.

    Args:
        closes: List of close prices, oldest first.
        period: EMA period.

    Returns:
        The latest EMA value as float.

    Raises:
        ValueError: same as calculate_ema()
    """
    values = calculate_ema(closes, period)
    latest = values[-1]
    if latest is None:
        raise ValueError(
            f"Not enough data to calculate EMA({period}). "
            f"Need at least {period} closes, got {len(closes)}."
        )
    return latest
