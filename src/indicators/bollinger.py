from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BollingerValue:
    """
    Bollinger Bands values for one bar.

    All values are None if not enough data exists yet.
    """

    upper: float | None
    middle: float | None
    lower: float | None
    percent_b: float | None
    bandwidth: float | None


def calculate_bollinger(
    closes: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> list[BollingerValue]:
    """
    Calculates Bollinger Bands for a list of closing prices.

    Args:
        closes:  List of close prices, oldest first.
        period:  SMA period. Default 20 (Bollinger's original).
        num_std: Number of standard deviations for bands. Default 2.0.

    Returns:
        List of BollingerValue dataclasses, same length as closes.
        First (period - 1) values have all None fields — not enough data.

    Raises:
        ValueError: if period < 2, num_std <= 0, or closes is empty
    """
    if not closes:
        raise ValueError("closes cannot be empty.")
    if period < 2:
        raise ValueError(f"period must be >= 2, got {period}.")
    if num_std <= 0:
        raise ValueError(f"num_std must be > 0, got {num_std}.")
    if period > len(closes):
        raise ValueError(
            f"period ({period}) cannot exceed number of closes ({len(closes)})."
        )

    result: list[BollingerValue] = []

    for i in range(len(closes)):
        if i < period - 1:
            # Not enough data yet
            result.append(
                BollingerValue(
                    upper=None,
                    middle=None,
                    lower=None,
                    percent_b=None,
                    bandwidth=None,
                )
            )
            continue

        # Window of closes for this bar
        window = closes[i - period + 1 : i + 1]
        close = closes[i]

        # Middle band = SMA
        middle = sum(window) / period

        # Standard deviation (sample, ddof=1)
        mean_w = middle
        variance = sum((x - mean_w) ** 2 for x in window) / (period - 1)
        std = math.sqrt(variance)

        # Upper and lower bands
        upper = middle + num_std * std
        lower = middle - num_std * std

        # %B — where is price within the bands
        band_width = upper - lower
        if band_width == 0:
            percent_b = 0.5  # bands collapsed, price at middle
        else:
            percent_b = (close - lower) / band_width

        # Bandwidth — how wide are the bands relative to middle
        bandwidth = band_width / middle if middle != 0 else 0.0

        result.append(
            BollingerValue(
                upper=upper,
                middle=middle,
                lower=lower,
                percent_b=percent_b,
                bandwidth=bandwidth,
            )
        )

    logger.debug(
        "Bollinger(%d, %.1f) calculated — latest: upper=%.2f middle=%.2f lower=%.2f",
        period,
        num_std,
        result[-1].upper or 0,
        result[-1].middle or 0,
        result[-1].lower or 0,
    )

    return result


def bollinger_latest(
    closes: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> BollingerValue:
    """
    Returns only the most recent Bollinger Bands values.

    Convenience function for live trading.

    Args:
        closes:  List of close prices, oldest first.
        period:  SMA period.
        num_std: Number of standard deviations.

    Returns:
        Latest BollingerValue.

    Raises:
        ValueError: if not enough data
    """
    values = calculate_bollinger(closes, period, num_std)
    latest = values[-1]
    if latest.middle is None:
        raise ValueError(
            f"Not enough data for Bollinger({period}). "
            f"Need at least {period} closes, got {len(closes)}."
        )
    return latest
