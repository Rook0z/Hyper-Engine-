from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# DATA FETCHING
# ──────────────────────────────────────────────────────────────


def fetch_close_prices(
    client: Any,
    symbol: str = "BTC",
    interval: str = "1h",
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 100,
) -> list[float]:
    """Fetches closing prices from Hyperliquid candleSnapshot endpoint."""
    import time as _time

    if end_time is None:
        end_time = int(_time.time() * 1000)
    if start_time is None:
        interval_ms = {
            "1m": 60_000,
            "3m": 180_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "2h": 7_200_000,
            "4h": 14_400_000,
            "8h": 28_800_000,
            "12h": 43_200_000,
            "1d": 86_400_000,
        }
        ms_per_candle = interval_ms.get(interval, 3_600_000)
        start_time = end_time - (limit * ms_per_candle)

    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": symbol,
            "interval": interval,
            "startTime": start_time,
            "endTime": end_time,
        },
    }
    raw = client.info(payload)
    if not raw:
        logger.warning("No candles returned for %s %s", symbol, interval)
        return []
    prices = [float(candle["c"]) for candle in raw]
    logger.debug("Fetched %d close prices for %s (%s)", len(prices), symbol, interval)
    return prices


# ──────────────────────────────────────────────────────────────
# CORE STATISTICS
# ──────────────────────────────────────────────────────────────


def mean(values: list[float]) -> float:
    """
    Arithmetic mean using numpy.
    numpy: np.mean(arr)
    """
    if not values:
        raise ValueError("Cannot calculate mean of empty list.")
    return float(np.mean(np.array(values, dtype=np.float64)))


def variance(values: list[float], population: bool = False) -> float:
    """
    Variance using numpy.
    ddof=0 → population (divide by n)
    ddof=1 → sample (divide by n-1) — default, correct for trading
    numpy: np.var(arr, ddof=1)
    """
    if len(values) < 2:
        raise ValueError("Variance requires at least 2 values.")
    arr = np.array(values, dtype=np.float64)
    ddof = 0 if population else 1
    return float(np.var(arr, ddof=ddof))


def std(values: list[float], population: bool = False) -> float:
    """
    Standard deviation using numpy.
    numpy: np.std(arr, ddof=1)
    In trading: std of returns = volatility.
    """
    if len(values) < 2:
        raise ValueError("Std requires at least 2 values.")
    arr = np.array(values, dtype=np.float64)
    ddof = 0 if population else 1
    return float(np.std(arr, ddof=ddof))


def expected_value(outcomes: list[float], probabilities: list[float]) -> float:
    """
    Expected value using numpy dot product.
    np.dot(outcomes, probabilities) = sum(outcome_i * probability_i)
    dot product is exactly the EV formula — multiply then sum.
    """
    if len(outcomes) != len(probabilities):
        raise ValueError(
            f"outcomes and probabilities must have same length. "
            f"Got {len(outcomes)} and {len(probabilities)}."
        )
    prob_arr = np.array(probabilities, dtype=np.float64)
    if not math.isclose(float(np.sum(prob_arr)), 1.0, abs_tol=1e-6):
        raise ValueError(
            f"Probabilities must sum to 1.0. Got {float(np.sum(prob_arr)):.6f}."
        )
    out_arr = np.array(outcomes, dtype=np.float64)
    return float(np.dot(out_arr, prob_arr))


def win_rate(pnl_list: list[float]) -> float:
    """
    Win rate using numpy boolean mask.
    np.sum(arr > 0) counts winning trades efficiently.
    """
    if not pnl_list:
        raise ValueError("Cannot calculate win rate of empty list.")
    arr = np.array(pnl_list, dtype=np.float64)
    return float(np.sum(arr > 0) / len(arr))


def profit_factor(pnl_list: list[float]) -> float:
    """
    Gross profit / gross loss using numpy boolean masking.
    arr[arr > 0] extracts only winning trades.
    arr[arr < 0] extracts only losing trades.
    """
    if not pnl_list:
        raise ValueError("Cannot calculate profit factor of empty list.")
    arr = np.array(pnl_list, dtype=np.float64)
    gross_profit = float(np.sum(arr[arr > 0]))
    gross_loss = float(np.abs(np.sum(arr[arr < 0])))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def max_drawdown(equity_curve: list[float]) -> float:
    """
    Max drawdown using np.maximum.accumulate.

    np.maximum.accumulate tracks the running peak at each point.
    (peak - value) / peak gives the drawdown at each point.
    np.max gives the worst drawdown across the whole curve.
    """
    if len(equity_curve) < 2:
        raise ValueError("Equity curve requires at least 2 values.")
    arr = np.array(equity_curve, dtype=np.float64)
    peak = np.maximum.accumulate(arr)
    drawdowns = (peak - arr) / peak
    return float(np.max(drawdowns))


def sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """
    Sharpe ratio using numpy.
    (mean - rf_per_period) / std * sqrt(periods)
    Returns 0.0 if not enough data or std is zero.
    """
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=np.float64)
    m = float(np.mean(arr))
    s = float(np.std(arr, ddof=1))
    if s == 0:
        return 0.0
    period_rf = risk_free_rate / periods_per_year
    return (m - period_rf) / s * math.sqrt(periods_per_year)


def describe(values: list[float]) -> dict[str, float]:
    """Summary statistics using numpy — all computed in one array pass."""
    if not values:
        raise ValueError("Cannot describe empty list.")
    arr = np.array(values, dtype=np.float64)
    return {
        "count": float(len(arr)),
        "mean": float(np.mean(arr)),
        "variance": float(np.var(arr, ddof=1)),
        "std": float(np.std(arr, ddof=1)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "range": float(np.max(arr) - np.min(arr)),
    }


# ──────────────────────────────────────────────────────────────
# NEW — RETURNS & ROLLING
# ──────────────────────────────────────────────────────────────


def pct_returns(prices: list[float]) -> np.ndarray:
    """
    Percentage returns using np.diff.
    Formula: (price[i] - price[i-1]) / price[i-1]
    numpy:   np.diff(arr) / arr[:-1]
    Returns array of length len(prices) - 1.
    """
    if len(prices) < 2:
        raise ValueError("Need at least 2 prices to calculate returns.")
    arr = np.array(prices, dtype=np.float64)
    return np.diff(arr) / arr[:-1]


def log_returns(prices: list[float]) -> np.ndarray:
    """
    Log returns using np.diff(np.log(arr)).
    Formula: ln(price[i] / price[i-1])
    Returns array of length len(prices) - 1.
    """
    if len(prices) < 2:
        raise ValueError("Need at least 2 prices to calculate log returns.")
    arr = np.array(prices, dtype=np.float64)
    return np.diff(np.log(arr))


def rolling_mean(values: list[float], window: int) -> np.ndarray:
    """
    Rolling mean (SMA) using np.convolve.
    A uniform kernel convolved with the data gives the rolling average.
    First (window-1) values are np.nan — not enough data yet.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    if window > len(values):
        raise ValueError(f"window ({window}) cannot exceed data length ({len(values)})")
    arr = np.array(values, dtype=np.float64)
    result = np.full(len(arr), np.nan)
    kernel = np.ones(window) / window
    result[window - 1 :] = np.convolve(arr, kernel, mode="valid")
    return result


def rolling_std(values: list[float], window: int) -> np.ndarray:
    """
    Rolling standard deviation using numpy slicing.
    First (window-1) values are np.nan.
    Used for Bollinger Bands and volatility analysis.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2 for std, got {window}")
    if window > len(values):
        raise ValueError(f"window ({window}) cannot exceed data length ({len(values)})")
    arr = np.array(values, dtype=np.float64)
    result = np.full(len(arr), np.nan)
    for i in range(window - 1, len(arr)):
        result[i] = float(np.std(arr[i - window + 1 : i + 1], ddof=1))
    return result
