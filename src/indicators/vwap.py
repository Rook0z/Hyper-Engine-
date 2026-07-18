from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VWAPValue:
    """
    VWAP values for one bar.

    vwap:      the VWAP value at this bar
    upper1:    VWAP + 1 standard deviation
    lower1:    VWAP - 1 standard deviation
    upper2:    VWAP + 2 standard deviations
    lower2:    VWAP - 2 standard deviations
    deviation: current price distance from VWAP as fraction
               positive = price above VWAP, negative = below
    """

    vwap: float
    upper1: float
    lower1: float
    upper2: float
    lower2: float
    deviation: float  # (close - vwap) / vwap


def calculate_vwap(
    candles: list[list],
    num_std: float = 2.0,
) -> list[VWAPValue]:
    """
    Calculates VWAP and standard deviation bands for a list of OHLCV candles.

    VWAP accumulates from the first candle — it does not reset by day here
    because Hyperliquid candles are indexed from when you request them.
    Pass only candles from the current trading day for true daily VWAP.

    Args:
        candles:  List of [timestamp, open, high, low, close, volume]
                  Sorted oldest → newest.
        num_std:  Number of standard deviations for bands. Default 2.0.

    Returns:
        List of VWAPValue dataclasses, same length as candles.
        All values are valid from the first candle onward (no warm-up period).

    Raises:
        ValueError: if candles is empty or num_std <= 0

    Hand-calculated example (2 candles):
        Candle 1: high=11, low=9,  close=10, volume=100
            typical_price = (11+9+10)/3  = 10.0
            cum_tp_vol    = 10.0 * 100   = 1000.0
            cum_vol       = 100
            VWAP          = 1000/100     = 10.0

        Candle 2: high=12, low=10, close=11, volume=200
            typical_price = (12+10+11)/3 = 11.0
            cum_tp_vol    = 1000 + 11*200 = 3200.0
            cum_vol       = 100 + 200     = 300
            VWAP          = 3200/300      = 10.6667
    """
    if not candles:
        raise ValueError("candles cannot be empty.")
    if num_std <= 0:
        raise ValueError(f"num_std must be > 0, got {num_std}.")

    result: list[VWAPValue] = []

    cum_tp_vol = 0.0  # cumulative (typical_price * volume)
    cum_vol = 0.0  # cumulative volume
    cum_tp2_vol = 0.0  # cumulative (typical_price^2 * volume) — for std calculation

    for candle in candles:
        _, _, high, low, close, volume = candle

        # Typical price — centre of gravity of the candle
        typical_price = (high + low + close) / 3.0

        # Accumulate
        cum_tp_vol += typical_price * volume
        cum_vol += volume
        cum_tp2_vol += (typical_price**2) * volume

        if cum_vol == 0:
            # No volume — use typical price as VWAP
            vwap = typical_price
            std = 0.0
        else:
            vwap = cum_tp_vol / cum_vol

            # Variance = E[x^2] - E[x]^2 (weighted)
            # = (cum_tp2_vol / cum_vol) - vwap^2
            variance = max(0.0, (cum_tp2_vol / cum_vol) - vwap**2)
            std = math.sqrt(variance)

        deviation = (close - vwap) / vwap if vwap != 0 else 0.0

        result.append(
            VWAPValue(
                vwap=vwap,
                upper1=vwap + 1.0 * std,
                lower1=vwap - 1.0 * std,
                upper2=vwap + num_std * std,
                lower2=vwap - num_std * std,
                deviation=deviation,
            )
        )

    logger.debug(
        "VWAP calculated over %d candles — latest: %.2f",
        len(candles),
        result[-1].vwap,
    )
    return result


def vwap_latest(
    candles: list[list],
    num_std: float = 2.0,
) -> VWAPValue:
    """
    Returns only the most recent VWAP value.

    Args:
        candles:  List of OHLCV candles
        num_std:  Standard deviation multiplier for bands

    Returns:
        Latest VWAPValue
    """
    values = calculate_vwap(candles, num_std)
    return values[-1]
