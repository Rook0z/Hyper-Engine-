"""
Monte Carlo simulation for trade-sequence robustness testing.

Reuses the trades already produced by a single Backtester run (see
BacktestResult.trades) — this module never re-runs the backtester and
never touches strategy or signal logic. It randomizes the ORDER (and,
in "bootstrap" mode, the SAMPLE) of the same realized trade PnLs
across many simulated equity paths, to test whether a strategy's
apparent performance depended on a lucky specific sequence of
wins/losses ("sequence risk") rather than testing the strategy's
signal logic itself, which is exactly what Backtester/backtest_all()
already do.

Two modes:
  - "shuffle" (default): a random permutation of the SAME trades, no
    repeats or omissions. Total PnL is identical across every
    simulation (same trades, different order) — only the PATH (how
    deep drawdowns get, when losses cluster) varies. This isolates
    pure sequence risk from everything else.
  - "bootstrap": trades are resampled WITH replacement (same count as
    the original), so some trades may repeat and others be omitted.
    Total PnL varies across simulations too — a broader robustness
    check against sensitivity to the specific sample of trades
    realized.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from backtester.backtester import BacktestResult
from backtester.performance import PerformanceAnalyser

_VALID_METHODS = ("shuffle", "bootstrap")


@dataclass
class MonteCarloSimulationResult:
    """One simulated equity path."""

    equity_curve: list[float]
    final_equity: float
    total_pnl: float
    max_drawdown: float  # fraction, same convention as PerformanceReport.max_drawdown


@dataclass
class MonteCarloReport:
    """
    Aggregated result across all Monte Carlo simulations. Percentiles
    are computed on final_equity and max_drawdown across every
    simulated path, alongside the ORIGINAL (unrandomized) backtest's
    own results for direct comparison.
    """

    num_simulations: int
    method: str
    initial_capital: float
    original_final_equity: float
    original_max_drawdown: float
    simulations: list[MonteCarloSimulationResult] = field(default_factory=list)

    @staticmethod
    def _percentile(values: list[float], pct: float) -> float:
        """Linear-interpolated percentile, pct in [0, 1]."""
        if not values:
            return 0.0
        s = sorted(values)
        if len(s) == 1:
            return s[0]
        k = (len(s) - 1) * pct
        f = int(k)
        c = min(f + 1, len(s) - 1)
        if f == c:
            return s[f]
        return s[f] + (s[c] - s[f]) * (k - f)

    @property
    def final_equity_values(self) -> list[float]:
        return [s.final_equity for s in self.simulations]

    @property
    def max_drawdown_values(self) -> list[float]:
        return [s.max_drawdown for s in self.simulations]

    @property
    def median_final_equity(self) -> float:
        return self._percentile(self.final_equity_values, 0.5)

    @property
    def mean_final_equity(self) -> float:
        vals = self.final_equity_values
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def worst_final_equity(self) -> float:
        vals = self.final_equity_values
        return min(vals) if vals else 0.0

    @property
    def best_final_equity(self) -> float:
        vals = self.final_equity_values
        return max(vals) if vals else 0.0

    @property
    def probability_of_loss(self) -> float:
        """Fraction of simulations ending with final equity below
        initial_capital — the Monte Carlo analogue of "how often does
        this strategy lose money overall, across plausible trade
        sequences/samples"."""
        vals = self.final_equity_values
        if not vals:
            return 0.0
        return sum(1 for v in vals if v < self.initial_capital) / len(vals)

    @property
    def median_max_drawdown(self) -> float:
        return self._percentile(self.max_drawdown_values, 0.5)

    @property
    def worst_max_drawdown(self) -> float:
        vals = self.max_drawdown_values
        return max(vals) if vals else 0.0

    def final_equity_percentile(self, pct: float) -> float:
        """pct in [0, 1], e.g. 0.05 for the 5th percentile."""
        return self._percentile(self.final_equity_values, pct)

    def max_drawdown_percentile(self, pct: float) -> float:
        return self._percentile(self.max_drawdown_values, pct)

    def __str__(self) -> str:
        return (
            f"\n{'=' * 65}\n"
            f"  MONTE CARLO SIMULATION ({self.method}, n={self.num_simulations})\n"
            f"{'=' * 65}\n"
            f"  Original final equity   : {self.original_final_equity:.2f}\n"
            f"  Original max drawdown   : {self.original_max_drawdown:.1%}\n"
            f"{'-' * 65}\n"
            f"  Simulated final equity:\n"
            f"    5th pct  : {self.final_equity_percentile(0.05):.2f}\n"
            f"    25th pct : {self.final_equity_percentile(0.25):.2f}\n"
            f"    median   : {self.median_final_equity:.2f}\n"
            f"    75th pct : {self.final_equity_percentile(0.75):.2f}\n"
            f"    95th pct : {self.final_equity_percentile(0.95):.2f}\n"
            f"    mean     : {self.mean_final_equity:.2f}\n"
            f"    worst    : {self.worst_final_equity:.2f}\n"
            f"    best     : {self.best_final_equity:.2f}\n"
            f"{'-' * 65}\n"
            f"  Simulated max drawdown:\n"
            f"    median   : {self.median_max_drawdown:.1%}\n"
            f"    worst    : {self.worst_max_drawdown:.1%}\n"
            f"{'-' * 65}\n"
            f"  Probability of loss (final equity < initial capital): "
            f"{self.probability_of_loss:.1%}\n"
            f"{'=' * 65}\n"
        )


def run_monte_carlo_simulation(
    result: BacktestResult,
    num_simulations: int = 1000,
    method: str = "shuffle",
    seed: int | None = None,
) -> MonteCarloReport:
    """
    Runs a Monte Carlo trade-sequence robustness test on an existing
    BacktestResult.

    Never re-runs the Backtester and never touches strategy/signal
    logic — this only randomizes the ORDER (and, in "bootstrap" mode,
    the SAMPLE) of the trade PnLs a backtest already produced, to test
    how sensitive the outcome is to the specific sequence/sample of
    trades realized.

    Args:
        result:          A BacktestResult with completed trades (from
                          Backtester.run()).
        num_simulations: Number of randomized paths to simulate.
                          Must be positive. Default 1000.
        method:          "shuffle" (default) — random permutation, same
                          trades, no repeats; total PnL is identical to
                          the original across every simulation, only
                          the path/drawdown sequence varies.
                          "bootstrap" — resample WITH replacement (same
                          count); total PnL varies across simulations
                          too.
        seed:            Optional random seed for reproducibility —
                          the same seed always produces the same set
                          of simulated paths.

    Returns:
        MonteCarloReport with every simulated path plus aggregate
        percentile statistics.

    Raises:
        ValueError: if there are no trades to simulate, num_simulations
                    is not positive, or method is not recognized.
    """
    if not result.trades:
        raise ValueError("BacktestResult has no trades to simulate.")
    if num_simulations <= 0:
        raise ValueError(f"num_simulations must be positive, got {num_simulations}")
    if method not in _VALID_METHODS:
        raise ValueError(f"method must be one of {_VALID_METHODS}, got {method!r}")

    rng = random.Random(seed)
    initial_capital = result.equity_curve[0] if result.equity_curve else 0.0
    pnls = [t.pnl for t in result.trades]

    analyser = PerformanceAnalyser()
    simulations: list[MonteCarloSimulationResult] = []

    for _ in range(num_simulations):
        if method == "shuffle":
            sample = pnls.copy()
            rng.shuffle(sample)
        else:  # bootstrap
            sample = [rng.choice(pnls) for _ in range(len(pnls))]

        equity_curve = [initial_capital]
        running = initial_capital
        for pnl in sample:
            running += pnl
            equity_curve.append(running)

        max_dd = analyser.max_drawdown(equity_curve)

        simulations.append(
            MonteCarloSimulationResult(
                equity_curve=equity_curve,
                final_equity=equity_curve[-1],
                total_pnl=equity_curve[-1] - initial_capital,
                max_drawdown=max_dd,
            )
        )

    original_final_equity = (
        result.equity_curve[-1] if result.equity_curve else initial_capital
    )

    return MonteCarloReport(
        num_simulations=num_simulations,
        method=method,
        initial_capital=initial_capital,
        original_final_equity=original_final_equity,
        original_max_drawdown=result.max_drawdown,
        simulations=simulations,
    )
