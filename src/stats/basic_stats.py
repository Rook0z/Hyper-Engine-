from __future__ import annotations

import math
import time as _time
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# DATA FETCHING — pulls real price data from Hyperliquid
# ──────────────────────────────────────────────────────────────


def fetch_close_prices(
    client: Any,
    symbol: str = "BTC",
    interval: str = "1h",
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 100,
) -> list[float]:
    """
    Fetches closing prices for a symbol from Hyperliquid.

    Uses the candleSnapshot endpoint which returns OHLCV candles.
    We extract the close price from each candle.

    Candle response fields:
        t = open time (ms)
        T = close time (ms)
        o = open price (string)
        h = high price (string)
        l = low price (string)
        c = close price (string)  ← this is what we want
        v = volume (string)
        n = number of trades

    Args:
        client:     HyperliquidClient instance
        symbol:     e.g. "BTC", "ETH"
        interval:   candle interval — "1m", "5m", "15m", "1h", "4h", "1d"
        start_time: start timestamp in milliseconds (optional)
        end_time:   end timestamp in milliseconds (optional)
        limit:      number of candles to fetch (max 5000 per API call)

    Returns:
        List of close prices as floats, oldest first.
    """

    # Default: last `limit` hours of 1h candles
    if end_time is None:
        end_time = int(_time.time() * 1000)
    if start_time is None:
        # Go back enough candles based on interval
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
    logger.debug(
        "Fetched %d close prices for %s (%s) — range: %.2f to %.2f",
        len(prices),
        symbol,
        interval,
        min(prices),
        max(prices),
    )
    return prices


# ──────────────────────────────────────────────────────────────
# CORE STATISTICS — built from formula
# ──────────────────────────────────────────────────────────────


def mean(values: list[float]) -> float:
    """
    Arithmetic mean — the average value.

    Formula: sum(values) / n

    In trading: average return, average price, average fill size.

    Args:
        values: list of numbers

    Returns:
        The mean as a float.

    Raises:
        ValueError: if values is empty
    """
    if not values:
        raise ValueError("Cannot calculate mean of empty list.")
    return sum(values) / len(values)


def variance(values: list[float], population: bool = False) -> float:
    """
    Variance — measures how spread out values are from the mean.

    Formula:
        Population variance:  sum((x - mean)^2) / n
        Sample variance:      sum((x - mean)^2) / (n - 1)

    We use sample variance (population=False) by default because in trading
    we always have a sample of returns, never the full population.
    Dividing by (n-1) instead of n corrects for the bias in a sample
    (Bessel's correction).

    In trading: variance of returns measures risk.
    Higher variance = more volatile = riskier.

    Args:
        values:     list of numbers
        population: if True use population variance (/ n), else sample (/ n-1)

    Returns:
        Variance as a float.

    Raises:
        ValueError: if values has fewer than 2 elements (sample variance needs n-1 >= 1)
    """
    if len(values) < 2:
        raise ValueError("Variance requires at least 2 values.")

    m = mean(values)
    squared_diffs = [(x - m) ** 2 for x in values]
    divisor = len(values) if population else len(values) - 1
    return sum(squared_diffs) / divisor


def std(values: list[float], population: bool = False) -> float:
    """
    Standard deviation — square root of variance.

    Formula: sqrt(variance(values))

    Standard deviation is in the same units as the original data,
    which makes it more interpretable than variance.

    In trading: std of returns = volatility.
    If BTC daily returns have std = 3%, then on any given day
    you can roughly expect the price to move ±3% from its mean.

    The Sharpe ratio uses std to normalize returns by risk:
        Sharpe = mean_return / std_return

    Args:
        values:     list of numbers
        population: passed through to variance()

    Returns:
        Standard deviation as a float.
    """
    return math.sqrt(variance(values, population=population))


def expected_value(outcomes: list[float], probabilities: list[float]) -> float:
    """
    Expected value — probability-weighted average outcome.

    Formula: sum(outcome_i * probability_i)

    In trading: expected value of a strategy =
        (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    A positive expected value means the strategy makes money on average.
    A negative expected value means it loses money on average.
    No amount of risk management saves a negative EV strategy long-term.

    Args:
        outcomes:      list of possible outcomes (e.g. [100.0, -50.0])
        probabilities: list of probabilities for each outcome (must sum to 1.0)

    Returns:
        Expected value as a float.

    Raises:
        ValueError: if lengths don't match or probabilities don't sum to ~1.0
    """
    if len(outcomes) != len(probabilities):
        raise ValueError(
            f"outcomes and probabilities must have same length. "
            f"Got {len(outcomes)} and {len(probabilities)}."
        )
    if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-6):
        raise ValueError(
            f"Probabilities must sum to 1.0. Got {sum(probabilities):.6f}."
        )
    return sum(o * p for o, p in zip(outcomes, probabilities))


def win_rate(pnl_list: list[float]) -> float:
    """
    Fraction of trades that were profitable.

    Formula: winning_trades / total_trades

    In trading: a strategy with win_rate = 0.6 wins 60% of trades.
    But win rate alone means nothing — a strategy with 90% win rate
    that loses 10x on the losers still loses money overall.
    Always pair win rate with profit factor or expected value.

    Args:
        pnl_list: list of per-trade PnL values (positive = win, negative = loss)

    Returns:
        Win rate as float between 0.0 and 1.0

    Raises:
        ValueError: if pnl_list is empty
    """
    if not pnl_list:
        raise ValueError("Cannot calculate win rate of empty list.")
    wins = sum(1 for pnl in pnl_list if pnl > 0)
    return wins / len(pnl_list)


def profit_factor(pnl_list: list[float]) -> float:
    """
    Ratio of gross profit to gross loss.

    Formula: sum(winning_trades) / abs(sum(losing_trades))

    Interpretation:
        profit_factor > 1.0 → strategy is profitable
        profit_factor = 1.0 → break even
        profit_factor < 1.0 → losing strategy
        profit_factor = 2.0 → for every $1 lost, $2 is made

    A good strategy typically has profit_factor > 1.5.
    Combined with win_rate, gives a full picture of strategy quality.

    Args:
        pnl_list: list of per-trade PnL values

    Returns:
        Profit factor as float.

    Raises:
        ValueError: if no losing trades (division by zero)
    """
    if not pnl_list:
        raise ValueError("Cannot calculate profit factor of empty list.")

    gross_profit = sum(pnl for pnl in pnl_list if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnl_list if pnl < 0))

    if gross_loss == 0:
        if gross_profit > 0:
            return float("inf")  # all trades profitable — infinite profit factor
        raise ValueError("No losing trades and no winning trades.")

    return gross_profit / gross_loss


def max_drawdown(equity_curve: list[float]) -> float:
    """
    Maximum peak-to-trough decline in the equity curve.

    Formula:
        For each point, find the maximum loss from any previous peak.
        max_drawdown = max((peak - trough) / peak) across all points.

    In trading: max drawdown is the worst loss streak.
    If you start with $10,000 and it drops to $7,000, max drawdown = 30%.

    Critical for risk management:
        - Most traders set a max drawdown limit (e.g. stop trading at -20%)
        - Investors use max drawdown to evaluate strategy risk
        - Lower max drawdown with same returns = better risk-adjusted performance

    Args:
        equity_curve: list of portfolio values over time (e.g. [10000, 10500, 9800, ...])

    Returns:
        Max drawdown as a positive float (e.g. 0.30 = 30% drawdown)

    Raises:
        ValueError: if equity_curve has fewer than 2 values
    """
    if len(equity_curve) < 2:
        raise ValueError("Equity curve requires at least 2 values.")

    peak = equity_curve[0]
    max_dd = 0.0

    for value in equity_curve[1:]:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd


def sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """
    Risk-adjusted return — return per unit of risk.

    Formula: (mean_return - risk_free_rate) / std_return * sqrt(periods_per_year)

    Interpretation:
        Sharpe > 2.0 → excellent
        Sharpe > 1.0 → good
        Sharpe > 0.5 → acceptable
        Sharpe < 0   → worse than risk-free

    The sqrt(periods_per_year) annualizes the ratio:
        Daily returns:  periods_per_year = 252 (trading days)
        Hourly returns: periods_per_year = 252 * 24 = 6048
        Minute returns: periods_per_year = 252 * 24 * 60

    Args:
        returns:          list of period returns (e.g. [0.01, -0.005, 0.02, ...])
        risk_free_rate:   annualized risk-free rate (default 0.0 for crypto)
        periods_per_year: trading periods in a year (default 252 for daily)

    Returns:
        Annualized Sharpe ratio as float.

    Raises:
        ValueError: if returns has fewer than 2 values or std is zero
    """
    if len(returns) < 2:
        raise ValueError("Sharpe ratio requires at least 2 return values.")

    m = mean(returns)
    s = std(returns)

    if s == 0:
        raise ValueError("Standard deviation is zero — all returns are identical.")

    # Convert annualized risk-free rate to per-period
    period_rf = risk_free_rate / periods_per_year

    return (m - period_rf) / s * math.sqrt(periods_per_year)


# ──────────────────────────────────────────────────────────────
# CONVENIENCE — run all stats on a price series at once
# ──────────────────────────────────────────────────────────────


def describe(values: list[float]) -> dict[str, float]:
    """
    Returns a summary of all basic statistics for a list of values.

    Args:
        values: list of numbers (e.g. close prices or returns)

    Returns:
        Dict with: count, mean, variance, std, min, max, range
    """
    if not values:
        raise ValueError("Cannot describe empty list.")

    return {
        "count": len(values),
        "mean": mean(values),
        "variance": variance(values),
        "std": std(values),
        "min": min(values),
        "max": max(values),
        "range": max(values) - min(values),
    }
