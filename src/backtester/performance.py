from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field

from backtester.backtester import BacktestResult, Trade

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

    # ── New metrics (all defaulted — existing callers unaffected) ──
    total_return_pct: float = 0.0
    num_winning_trades: int = 0
    num_losing_trades: int = 0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_trade_return_pct: float = 0.0
    avg_holding_time_hours: float = 0.0
    final_equity: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    recovery_factor: float = 0.0
    exposure_time_pct: float = 0.0
    max_drawdown_duration_hours: float = 0.0
    max_drawdown_recovered: bool = True
    estimated_slippage_cost: float = 0.0

    def __str__(self) -> str:
        pf = f"{self.profit_factor:.2f}" if self.profit_factor != float("inf") else "∞"
        rf = f"{self.recovery_factor:.2f}" if self.recovery_factor != float("inf") else "∞"
        recovered_label = "yes" if self.max_drawdown_recovered else "no (ongoing at end of backtest)"
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
            f"{'─'*50}\n"
            f"  Total return       : {self.total_return_pct:+.2f}%\n"
            f"  Final equity       : {self.final_equity:.2f} USDC\n"
            f"  Winning trades     : {self.num_winning_trades}\n"
            f"  Losing trades      : {self.num_losing_trades}\n"
            f"  Largest win        : {self.largest_win:+.2f} USDC\n"
            f"  Largest loss       : {self.largest_loss:+.2f} USDC\n"
            f"  Avg trade return   : {self.avg_trade_return_pct:+.2f}%\n"
            f"  Avg holding time   : {self.avg_holding_time_hours:.2f}h\n"
            f"  Recovery factor    : {rf}\n"
            f"  Exposure time      : {self.exposure_time_pct:.1f}%\n"
            f"  Max DD duration    : {self.max_drawdown_duration_hours:.2f}h (recovered: {recovered_label})\n"
            f"  Est. slippage cost : {self.estimated_slippage_cost:.2f} USDC\n"
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
            final_equity = (
                result.equity_curve[-1]
                if result.equity_curve
                else result.backtest_initial_capital
            )
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
                total_return_pct=0.0,
                num_winning_trades=0,
                num_losing_trades=0,
                largest_win=0.0,
                largest_loss=0.0,
                avg_trade_return_pct=0.0,
                avg_holding_time_hours=0.0,
                final_equity=final_equity,
                equity_curve=list(result.equity_curve),
                recovery_factor=0.0,
                exposure_time_pct=0.0,
                max_drawdown_duration_hours=0.0,
                max_drawdown_recovered=True,
                estimated_slippage_cost=0.0,
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

        total_return = self.total_return_pct(result.equity_curve)
        num_wins, num_losses = self.count_wins_losses(pnl_list)
        lw = self.largest_win(pnl_list)
        ll = self.largest_loss(pnl_list)
        avg_ret_pct = self.avg_trade_return_pct(returns)
        avg_hold = self.avg_holding_time(trades)
        final_equity = (
            result.equity_curve[-1]
            if result.equity_curve
            else result.backtest_initial_capital
        )

        max_dd_dollar = self._max_drawdown_dollar(result.equity_curve)
        rf = self.recovery_factor(result.total_pnl, max_dd_dollar)

        exposure = self.exposure_time(
            trades, result.backtest_start_time, result.backtest_end_time
        )

        timestamps = self._equity_timestamps(result)
        dd_duration_hours, dd_recovered = self.max_drawdown_duration(
            result.equity_curve, timestamps, result.backtest_end_time
        )

        slip_cost = self.estimated_slippage_cost(trades, result.slippage_pct)

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
            total_return_pct=total_return,
            num_winning_trades=num_wins,
            num_losing_trades=num_losses,
            largest_win=lw,
            largest_loss=ll,
            avg_trade_return_pct=avg_ret_pct,
            avg_holding_time_hours=avg_hold,
            final_equity=final_equity,
            equity_curve=list(result.equity_curve),
            recovery_factor=rf,
            exposure_time_pct=exposure,
            max_drawdown_duration_hours=dd_duration_hours,
            max_drawdown_recovered=dd_recovered,
            estimated_slippage_cost=slip_cost,
        )

    # ──────────────────────────────────────────────────────────────
    # INDIVIDUAL METRICS (existing)
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

    # ──────────────────────────────────────────────────────────────
    # INDIVIDUAL METRICS (new)
    # ──────────────────────────────────────────────────────────────

    def total_return_pct(self, equity_curve: list[float]) -> float:
        """
        Total return over the backtest, as a percentage.

        Formula: (final_equity / initial_equity - 1) * 100

        equity_curve[0] is always the starting capital and
        equity_curve[-1] is the equity after the last trade closed
        (both set by Backtester._build_result()).

        Returns:
            0.0 if equity_curve is empty or starts at 0 (degenerate
            input — avoids a ZeroDivisionError rather than crashing).
        """
        if not equity_curve or equity_curve[0] == 0:
            return 0.0
        return (equity_curve[-1] / equity_curve[0] - 1) * 100

    def count_wins_losses(self, pnl_list: list[float]) -> tuple[int, int]:
        """
        Returns (num_winning_trades, num_losing_trades).

        Breakeven trades (pnl == 0) count as neither a win nor a loss —
        the same convention win_rate() already uses.
        """
        if not pnl_list:
            raise ValueError("pnl_list cannot be empty.")
        wins = sum(1 for p in pnl_list if p > 0)
        losses = sum(1 for p in pnl_list if p < 0)
        return wins, losses

    def largest_win(self, pnl_list: list[float]) -> float:
        """
        Largest single winning trade, in USDC.

        Returns:
            0.0 if there are no winning trades.
        """
        if not pnl_list:
            raise ValueError("pnl_list cannot be empty.")
        wins = [p for p in pnl_list if p > 0]
        return max(wins) if wins else 0.0

    def largest_loss(self, pnl_list: list[float]) -> float:
        """
        Largest single losing trade, in USDC (a negative number — the
        most negative value is the worst loss).

        Returns:
            0.0 if there are no losing trades.
        """
        if not pnl_list:
            raise ValueError("pnl_list cannot be empty.")
        losses = [p for p in pnl_list if p < 0]
        return min(losses) if losses else 0.0

    def avg_trade_return_pct(self, returns: list[float]) -> float:
        """
        Average per-trade return, as a percentage.

        Formula: mean(pnl_pct) * 100

        Distinct from expectancy(), which averages PnL in USDC.
        This is the average percentage return per trade — independent
        of position size, so it's comparable across strategies or
        position-size configurations that expectancy() is not.
        """
        if not returns:
            raise ValueError("returns cannot be empty.")
        return (sum(returns) / len(returns)) * 100

    def avg_holding_time(self, trades: list[Trade]) -> float:
        """
        Average time a position was held open, in hours.

        Formula: mean(exit_time - entry_time) / 3,600,000

        Trade.entry_time / exit_time are millisecond timestamps — the
        same convention used elsewhere in the backtester (e.g.
        Backtester.summary_by_day()).
        """
        if not trades:
            raise ValueError("trades cannot be empty.")
        durations_ms = [t.exit_time - t.entry_time for t in trades]
        return (sum(durations_ms) / len(durations_ms)) / 3_600_000

    def recovery_factor(self, net_profit: float, max_drawdown_dollar: float) -> float:
        """
        Net profit divided by the maximum peak-to-trough dollar drawdown.

        Formula: net_profit / max_drawdown_dollar

        Measures how much profit was generated per dollar of the worst
        losing streak experienced along the way — higher is better.
        Unlike Calmar ratio (which annualises average return and
        divides by drawdown as a *fraction*), this uses raw dollar
        amounts and total net profit — a common alternative convention
        in retail/prop-style backtest reports, included here alongside
        Calmar rather than in place of it.

        Args:
            net_profit:           Total PnL in USDC (BacktestResult.total_pnl).
            max_drawdown_dollar:  Peak-to-trough decline in USDC (not a
                                   fraction — see _max_drawdown_dollar()).

        Returns:
            float("inf") if there was no drawdown and profit is
            positive (profit was generated without ever giving any of
            it back). 0.0 if there was no drawdown and no profit.
        """
        if max_drawdown_dollar == 0:
            return float("inf") if net_profit > 0 else 0.0
        return net_profit / max_drawdown_dollar

    def exposure_time(
        self,
        trades: list[Trade],
        backtest_start_time: int,
        backtest_end_time: int,
    ) -> float:
        """
        Percentage of the total backtest time a position was held open.

        Formula: sum(trade durations) / (backtest_end_time - backtest_start_time) * 100

        Backtester._simulate_trades() only ever holds one position at a
        time (it looks for BUY only when not in_position, SELL only
        when in_position), so summing individual trade durations never
        double-counts overlapping time.

        Args:
            trades:               Completed trades.
            backtest_start_time:  BacktestResult.backtest_start_time.
            backtest_end_time:    BacktestResult.backtest_end_time.

        Returns:
            0.0 if the backtest time span is zero or negative — this is
            the correct value for a BacktestResult built without this
            metadata (e.g. constructed directly in older test code)
            rather than raising or dividing by zero.
        """
        span = backtest_end_time - backtest_start_time
        if span <= 0:
            return 0.0
        time_in_market = sum(t.exit_time - t.entry_time for t in trades)
        return (time_in_market / span) * 100

    def max_drawdown_duration(
        self,
        equity_curve: list[float],
        timestamps: list[int],
        backtest_end_time: int,
    ) -> tuple[float, bool]:
        """
        Duration of the maximum drawdown, using peak-to-recovery
        methodology.

        Finds the equity peak that precedes the single largest
        peak-to-trough decline, then measures the time until equity
        first climbs back to or above that peak level again. If
        recovery never happens before the end of the backtest,
        duration is measured up to backtest_end_time instead, and the
        report indicates recovery was not achieved.

        Args:
            equity_curve: One value per point (same as BacktestResult's).
            timestamps:   One millisecond timestamp per equity_curve
                           point, same length and order — see
                           PerformanceAnalyser._equity_timestamps().
            backtest_end_time: End of the backtest window; used as the
                           duration ceiling when recovery never occurs.

        Returns:
            (duration_hours, recovered) tuple.
              duration_hours: 0.0 if there's no drawdown, fewer than 2
                  points, or timestamps don't line up with equity_curve.
              recovered: True if there was no drawdown to recover from,
                  or equity actually climbed back to the pre-drawdown
                  peak before backtest_end_time. False if the drawdown
                  was still ongoing when the backtest ended.

        Assumption: if multiple drawdowns tie for the maximum
        peak-to-trough decline, the first one encountered (scanning
        oldest → newest) is used — a standard forward-scan convention.
        """
        if len(equity_curve) < 2 or len(equity_curve) != len(timestamps):
            return 0.0, True

        peak_idx = 0
        max_dd = 0.0
        dd_peak_idx = 0
        dd_trough_idx = 0

        for i in range(1, len(equity_curve)):
            if equity_curve[i] > equity_curve[peak_idx]:
                peak_idx = i
            peak_value = equity_curve[peak_idx]
            dd = (peak_value - equity_curve[i]) / peak_value if peak_value != 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                dd_peak_idx = peak_idx
                dd_trough_idx = i

        if max_dd == 0.0:
            return 0.0, True

        peak_value = equity_curve[dd_peak_idx]
        peak_time = timestamps[dd_peak_idx]

        recovery_idx = None
        for i in range(dd_trough_idx, len(equity_curve)):
            if equity_curve[i] >= peak_value:
                recovery_idx = i
                break

        if recovery_idx is not None:
            duration_ms = timestamps[recovery_idx] - peak_time
            recovered = True
        else:
            duration_ms = backtest_end_time - peak_time
            recovered = False

        duration_hours = max(duration_ms, 0) / 3_600_000
        return duration_hours, recovered

    def estimated_slippage_cost(
        self,
        trades: list[Trade],
        slippage_pct: float,
    ) -> float:
        """
        Estimated total cost paid to slippage across all trades, in USDC.

        Backtester._simulate_trades() fills buys above the reference
        price and sells below it:
            entry_price = fill_price * (1 + slippage_pct)
            exit_price  = fill_price * (1 - slippage_pct)

        This reverses that relationship to recover the pre-slippage
        fill price on each side and compute the dollar cost of
        slippage:
            entry_cost = entry_price * slippage_pct / (1 + slippage_pct)
            exit_cost  = exit_price  * slippage_pct / (1 - slippage_pct)

        Total cost per trade = (entry_cost + exit_cost) * size, summed
        across all trades.

        Args:
            trades:       Completed trades.
            slippage_pct: The slippage rate the backtest that produced
                          these trades actually used
                          (BacktestResult.slippage_pct). This is
                          metadata only — it is not re-applied to
                          anything, only used to back-calculate cost.

        Returns:
            0.0 if there are no trades or slippage_pct is 0 — the
            correct value for a BacktestResult built without this
            metadata tracked (an accurate "unknown", not a guess).
        """
        if not trades or slippage_pct == 0:
            return 0.0
        total = 0.0
        for t in trades:
            entry_cost = t.entry_price * slippage_pct / (1 + slippage_pct)
            exit_cost = t.exit_price * slippage_pct / (1 - slippage_pct)
            total += (entry_cost + exit_cost) * t.size
        return total

    # ──────────────────────────────────────────────────────────────
    # INTERNAL WIRING (not independently meaningful metrics — used to
    # feed the public methods above from a BacktestResult)
    # ──────────────────────────────────────────────────────────────

    def _max_drawdown_dollar(self, equity_curve: list[float]) -> float:
        """
        Peak-to-trough maximum drawdown in raw dollar terms (unlike
        max_drawdown(), which returns a fraction). Feeds recovery_factor().
        """
        if len(equity_curve) < 2:
            return 0.0
        peak = equity_curve[0]
        max_dd = 0.0
        for value in equity_curve[1:]:
            if value > peak:
                peak = value
            dd = peak - value
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def _equity_timestamps(self, result: BacktestResult) -> list[int]:
        """
        Builds one timestamp per point in result.equity_curve, so
        max_drawdown_duration() can measure timing.

        equity_curve[0] is the starting equity → backtest_start_time.
        Each subsequent point is the equity right after a trade closes
        → that trade's exit_time. This lines up 1:1 with how
        Backtester._build_result() constructs equity_curve
        ([initial_capital] + one cumulative point per trade).
        """
        return [result.backtest_start_time] + [t.exit_time for t in result.trades]
