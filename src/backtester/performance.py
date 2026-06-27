from __future__ import annotations

import math
import logging
from dataclasses import dataclass

from backtester.backtester import BacktestResult

logger = logging.getLogger(__name__)


@dataclass
class PerformanceReport:
    """
    Full performance report for a backtest run.
    All metrics in one place — print or log at end of backtest.
    """

    strategy_name: str
    symbol: str
    num_trades: int
    total_pnl: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    avg_win: float
    avg_loss: float
    expectancy: float
    gross_profit: float
    gross_loss: float
    candles_tested: int

    def __str__(self) -> str:
        pf = f"{self.profit_factor:.2f}" if self.profit_factor != float("inf") else "∞"
        return (
            f"\n{'='*50}\n"
            f"  PERFORMANCE REPORT\n"
            f"  Strategy : {self.strategy_name}\n"
            f"  Symbol   : {self.symbol}\n"
            f"{'='*50}\n"
            f"  Candles tested : {self.candles_tested}\n"
            f"  Num trades     : {self.num_trades}\n"
            f"  Total PnL      : {self.total_pnl:+.2f} USDC\n"
            f"  Gross profit   : {self.gross_profit:.2f} USDC\n"
            f"  Gross loss     : {self.gross_loss:.2f} USDC\n"
            f"{'─'*50}\n"
            f"  Win rate       : {self.win_rate:.1%}\n"
            f"  Profit factor  : {pf}\n"
            f"  Avg win        : {self.avg_win:+.2f} USDC\n"
            f"  Avg loss       : {self.avg_loss:+.2f} USDC\n"
            f"  Expectancy     : {self.expectancy:+.4f} USDC/trade\n"
            f"{'─'*50}\n"
            f"  Max drawdown   : {self.max_drawdown:.1%}\n"
            f"  Sharpe ratio   : {self.sharpe_ratio:.4f}\n"
            f"  Sortino ratio  : {self.sortino_ratio:.4f}\n"
            f"  Calmar ratio   : {self.calmar_ratio:.4f}\n"
            f"{'='*50}\n"
        )


class PerformanceAnalyser:
    """
    Computes performance metrics from a BacktestResult.

    Usage:
        result = backtester.run(candles)
        analyser = PerformanceAnalyser()
        report = analyser.analyse(result)
        print(report)
    """

    def analyse(self, result: BacktestResult) -> PerformanceReport:
        """
        Runs all metrics on a BacktestResult and returns a PerformanceReport.

        Args:
            result: BacktestResult from Backtester.run()

        Returns:
            PerformanceReport with all metrics computed.
        """
        trades = result.trades

        if not trades:
            logger.warning("No trades to analyse — returning zeroed report.")
            return PerformanceReport(
                strategy_name=result.strategy_name,
                symbol=result.symbol,
                num_trades=0,
                total_pnl=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                max_drawdown=result.max_drawdown,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                calmar_ratio=0.0,
                avg_win=0.0,
                avg_loss=0.0,
                expectancy=0.0,
                gross_profit=0.0,
                gross_loss=0.0,
                candles_tested=result.candles_tested,
            )

        pnl_list = [t.pnl for t in trades]
        returns = [t.pnl_pct for t in trades]

        gp, gl = self.gross_profit_loss(pnl_list)
        wr = self.win_rate(pnl_list)
        pf = self.profit_factor(pnl_list)
        aw, al = self.avg_win_loss(pnl_list)
        ex = self.expectancy(pnl_list)
        sr = self.sharpe_ratio(returns)
        so = self.sortino_ratio(returns)
        cr = self.calmar_ratio(returns, result.max_drawdown)

        return PerformanceReport(
            strategy_name=result.strategy_name,
            symbol=result.symbol,
            num_trades=len(trades),
            total_pnl=result.total_pnl,
            win_rate=wr,
            profit_factor=pf,
            max_drawdown=result.max_drawdown,
            sharpe_ratio=sr,
            sortino_ratio=so,
            calmar_ratio=cr,
            avg_win=aw,
            avg_loss=al,
            expectancy=ex,
            gross_profit=gp,
            gross_loss=gl,
            candles_tested=result.candles_tested,
        )

    # ──────────────────────────────────────────────────────────────
    # INDIVIDUAL METRICS
    # ──────────────────────────────────────────────────────────────

    def total_pnl(self, pnl_list: list[float]) -> float:
        """Sum of all trade PnLs."""
        if not pnl_list:
            raise ValueError("pnl_list cannot be empty.")
        return sum(pnl_list)

    def win_rate(self, pnl_list: list[float]) -> float:
        """
        Fraction of trades that were profitable.

        Returns:
            Float between 0.0 and 1.0.
            0.6 means 60% of trades made money.
        """
        if not pnl_list:
            raise ValueError("pnl_list cannot be empty.")
        wins = sum(1 for p in pnl_list if p > 0)
        return wins / len(pnl_list)

    def max_drawdown(self, equity_curve: list[float]) -> float:
        """
        Maximum peak-to-trough decline in the equity curve.

        Formula: max((peak - trough) / peak) across all points.

        Returns:
            Max drawdown as positive fraction. 0.20 = 20% drawdown.
        """
        if len(equity_curve) < 2:
            raise ValueError("equity_curve needs at least 2 values.")
        peak = equity_curve[0]
        max_dd = 0.0
        for value in equity_curve[1:]:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def profit_factor(self, pnl_list: list[float]) -> float:
        """
        Gross profit / gross loss.

        > 1.0 → profitable
        = 1.0 → break even
        < 1.0 → losing
        inf   → no losing trades
        """
        if not pnl_list:
            raise ValueError("pnl_list cannot be empty.")
        gross_profit = sum(p for p in pnl_list if p > 0)
        gross_loss = abs(sum(p for p in pnl_list if p < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    def gross_profit_loss(self, pnl_list: list[float]) -> tuple[float, float]:
        """Returns (gross_profit, gross_loss) tuple."""
        if not pnl_list:
            raise ValueError("pnl_list cannot be empty.")
        gp = sum(p for p in pnl_list if p > 0)
        gl = abs(sum(p for p in pnl_list if p < 0))
        return gp, gl

    def avg_win_loss(self, pnl_list: list[float]) -> tuple[float, float]:
        """
        Returns (avg_win, avg_loss) tuple.
        avg_loss is negative (it's a loss).
        Returns 0.0 for each if no wins or no losses exist.
        """
        if not pnl_list:
            raise ValueError("pnl_list cannot be empty.")
        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p < 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        return avg_win, avg_loss

    def expectancy(self, pnl_list: list[float]) -> float:
        """
        Average expected PnL per trade.

        Formula: (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

        Positive expectancy → strategy makes money on average.
        Negative expectancy → strategy loses money on average.
        No amount of position sizing saves a negative expectancy strategy.
        """
        if not pnl_list:
            raise ValueError("pnl_list cannot be empty.")
        return sum(pnl_list) / len(pnl_list)

    def sharpe_ratio(
        self,
        returns: list[float],
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252,
    ) -> float:
        """
        Risk-adjusted return — return per unit of total volatility.

        Formula: (mean_return - risk_free_rate) / std_return * sqrt(periods)

        > 2.0 → excellent
        > 1.0 → good
        > 0.5 → acceptable
        < 0   → worse than risk-free

        Args:
            returns:          list of per-trade return percentages
            risk_free_rate:   annualised risk-free rate (0 for crypto)
            periods_per_year: trading periods per year (252 = daily)

        Returns:
            0.0 if fewer than 2 returns or std is zero.
        """
        if len(returns) < 2:
            return 0.0
        n = len(returns)
        m = sum(returns) / n
        variance = sum((r - m) ** 2 for r in returns) / (n - 1)
        s = math.sqrt(variance)
        if s == 0:
            return 0.0
        period_rf = risk_free_rate / periods_per_year
        return (m - period_rf) / s * math.sqrt(periods_per_year)

    def sortino_ratio(
        self,
        returns: list[float],
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252,
    ) -> float:
        """
        Like Sharpe but only penalises downside volatility.

        Sharpe treats upside and downside volatility equally.
        Sortino only uses downside deviation in the denominator.
        A strategy with lots of large wins but small losses
        will have a better Sortino than Sharpe.

        Returns:
            0.0 if fewer than 2 returns or no downside volatility.
        """
        if len(returns) < 2:
            return 0.0
        n = len(returns)
        m = sum(returns) / n
        downside = [r for r in returns if r < 0]
        if not downside:
            return float("inf") if m > 0 else 0.0
        downside_var = sum(r**2 for r in downside) / n
        downside_std = math.sqrt(downside_var)
        if downside_std == 0:
            return 0.0
        period_rf = risk_free_rate / periods_per_year
        return (m - period_rf) / downside_std * math.sqrt(periods_per_year)

    def calmar_ratio(
        self,
        returns: list[float],
        max_drawdown: float,
        periods_per_year: int = 252,
    ) -> float:
        """
        Annualised return divided by max drawdown.

        Measures return relative to the worst losing streak.
        Higher is better — same return with less drawdown = better Calmar.

        Returns:
            0.0 if max_drawdown is zero or no returns.
        """
        if not returns or max_drawdown == 0:
            return 0.0
        avg_return = sum(returns) / len(returns)
        annualised = avg_return * periods_per_year
        return annualised / max_drawdown
