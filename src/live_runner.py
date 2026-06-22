from __future__ import annotations

import os
import time
import logging
from dotenv import load_dotenv

from hyperliquid.auth import HyperliquidAuth
from hyperliquid.client import HyperliquidClient, APIError, NetworkError
from hyperliquid.symbol import HyperliquidSymbol
from data.ohlcv_provider import OHLCVProvider
from strategies.ema_strategy import EMAStrategy
from risk.risk_manager import RiskManager
from core.trade_logger import TradeLogger

load_dotenv()

# ──────────────────────────────────────────────────────────────
# CONFIGURATION — edit these before running
# ──────────────────────────────────────────────────────────────

SYMBOL = "BTC"
INTERVAL = "1h"
CANDLE_LIMIT = 50  # how many candles to feed strategy
FAST_EMA = 9  # fast EMA period
SLOW_EMA = 21  # slow EMA period
POSITION_SIZE = 0.001  # per trade
SLEEP_SECONDS = 60  # seconds between checks (60 = check every minute)
IS_MAINNET = False
RUN_DURATION_S = 2 * 60 * 60  # 2 hours in seconds

# Risk parameters
INITIAL_BALANCE = 10_000.0
MAX_POSITION_PCT = 0.05  # max 5% of balance per trade
MAX_DAILY_LOSS_PCT = 0.02  # stop if daily loss > 2%

# ──────────────────────────────────────────────────────────────
# LOGGING SETUP
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("live_runner")


# ──────────────────────────────────────────────────────────────
# RUNNER
# ──────────────────────────────────────────────────────────────


class LiveRunner:
    """
    Wires OHLCV data → strategy → risk manager → order → trade logger.

    One class. One run loop. Clean shutdown on KeyboardInterrupt.
    """

    def __init__(self) -> None:
        private_key = os.getenv("HL_PRIVATE_KEY")
        account_address = os.getenv("HL_ACCOUNT_ADDRESS")
        base_url = os.getenv("HL_BASE_URL", "https://api.hyperliquid-testnet.xyz")

        if not private_key or not account_address:
            raise ValueError(
                "HL_PRIVATE_KEY and HL_ACCOUNT_ADDRESS must be set in .env"
            )

        # Hyperliquid client
        self.auth = HyperliquidAuth(
            private_key=private_key,
            account_address=account_address,
            is_mainnet=IS_MAINNET,
        )
        self.client = HyperliquidClient(
            auth=self.auth,
            base_url=base_url,
            max_retries=3,
        )

        # Symbol map — load once at startup
        self.symbol_map = HyperliquidSymbol(client=self.client)
        self.symbol_map.load()

        # data, strategy, risk
        self.ohlcv = OHLCVProvider(client=self.client)
        self.strategy = EMAStrategy(fast_period=FAST_EMA, slow_period=SLOW_EMA)
        self.risk = RiskManager(
            account_balance=INITIAL_BALANCE,
            max_position_pct=MAX_POSITION_PCT,
            max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
        )

        # Trade logger
        self.trade_log = TradeLogger(
            log_dir="logs",
            symbol=SYMBOL,
            strategy=self.strategy.name,
        )

        # State
        self.in_position = False
        self.entry_price: float = 0.0
        self.entry_time: str = ""
        self.daily_loss: float = 0.0
        self.total_pnl: float = 0.0
        self.num_trades: int = 0

        logger.info(
            "LiveRunner initialized — %s %s %s (mainnet=%s)",
            SYMBOL,
            INTERVAL,
            self.strategy.name,
            IS_MAINNET,
        )

    def run(self) -> None:
        """Main loop — runs for RUN_DURATION_S seconds."""
        self.trade_log.log_session_start(balance=INITIAL_BALANCE)
        logger.info("Session started. Running for %d minutes.", RUN_DURATION_S // 60)

        start_time = time.time()

        try:
            while time.time() - start_time < RUN_DURATION_S:
                try:
                    self._tick()
                except NetworkError as e:
                    logger.warning("Network error — will retry next tick: %s", e)
                    self.trade_log.log_error(str(e), context={"type": "NetworkError"})
                except APIError as e:
                    logger.error("API error: %s", e)
                    self.trade_log.log_error(str(e), context={"type": "APIError"})
                except Exception as e:
                    logger.exception("Unexpected error: %s", e)
                    self.trade_log.log_error(
                        str(e), context={"type": "UnexpectedException"}
                    )

                elapsed = time.time() - start_time
                remaining = RUN_DURATION_S - elapsed
                logger.info(
                    "Tick complete. Next in %ds. Time remaining: %.0fm",
                    SLEEP_SECONDS,
                    remaining / 60,
                )
                time.sleep(SLEEP_SECONDS)

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt — shutting down cleanly.")

        finally:
            self._shutdown()

    def _tick(self) -> None:
        """One iteration of the trading loop."""
        # Fetch candles
        candles = self.ohlcv.fetch(SYMBOL, interval=INTERVAL, limit=CANDLE_LIMIT)
        if not candles:
            logger.warning("No candles returned — skipping tick.")
            return

        closes = self.ohlcv.get_close_prices(candles)
        current_price = closes[-1]
        logger.info("Price: %.2f | In position: %s", current_price, self.in_position)

        # Get strategy signal
        signal = self.strategy.generate_signal(closes)

        # Get EMA values for logging context
        ema_values = self.strategy.get_ema_values(closes)
        fast_ema = ema_values["fast"][-1]
        slow_ema = ema_values["slow"][-1]

        self.trade_log.log_signal(
            signal,
            price=current_price,
            extra={
                "fast_ema": round(fast_ema, 2) if fast_ema else None,
                "slow_ema": round(slow_ema, 2) if slow_ema else None,
            },
        )
        logger.info(
            "Signal: %s | Fast EMA: %s | Slow EMA: %s",
            signal,
            f"{fast_ema:.2f}" if fast_ema else "N/A",
            f"{slow_ema:.2f}" if slow_ema else "N/A",
        )

        # Act on signal
        if signal == "BUY" and not self.in_position:
            self._enter_long(current_price)

        elif signal == "SELL" and self.in_position:
            self._exit_long(current_price)

    def _enter_long(self, price: float) -> None:
        """Checks risk, places buy order, logs everything."""
        # Risk check
        risk_result = self.risk.check_trade(
            symbol=SYMBOL,
            price=price,
            requested_size=POSITION_SIZE,
            current_daily_loss=self.daily_loss,
            open_positions=1 if self.in_position else 0,
        )

        if not risk_result.allowed:
            logger.warning("Trade blocked by risk manager: %s", risk_result.reason)
            self.trade_log.log_risk_block(
                reason=risk_result.reason,
                requested_size=POSITION_SIZE,
            )
            return

        approved_size = risk_result.position_size

        # Log the order attempt
        self.trade_log.log_order("BUY", price=price, size=approved_size)

        try:
            # Place order on Hyperliquid
            from hyperliquid.trading import HyperliquidTrading

            trading = HyperliquidTrading(
                client=self.client,
                symbol_map=self.symbol_map,
            )
            result = trading.place_limit_order(
                symbol=SYMBOL,
                is_buy=True,
                price=str(round(price * 0.9995, 1)),  # slight discount for limit fill
                size=str(approved_size),
                tif="Gtc",
            )

            # Check response
            response = result.get("response", {})
            statuses = response.get("data", {}).get("statuses", [{}])
            status = statuses[0] if statuses else {}

            if "resting" in status or "filled" in status:
                oid = (status.get("resting") or status.get("filled", {})).get("oid")
                self.in_position = True
                self.entry_price = price
                self.entry_time = self._now_iso()

                self.trade_log.log_fill("BUY", price=price, size=approved_size, oid=oid)
                logger.info(
                    "BUY order placed: size=%.4f price=%.2f oid=%s",
                    approved_size,
                    price,
                    oid,
                )
            else:
                error = status.get("error", "Unknown error")
                logger.warning("Order rejected: %s", error)
                self.trade_log.log_error(f"Order rejected: {error}")

        except Exception as e:
            logger.exception("Failed to place buy order: %s", e)
            self.trade_log.log_error(str(e), context={"action": "BUY"})

    def _exit_long(self, price: float) -> None:
        """Places sell order to close position, logs trade result."""
        self.trade_log.log_order("SELL", price=price, size=POSITION_SIZE)

        try:
            from hyperliquid.trading import HyperliquidTrading

            trading = HyperliquidTrading(
                client=self.client,
                symbol_map=self.symbol_map,
            )
            result = trading.place_market_order(
                symbol=SYMBOL,
                is_buy=False,
                size=str(POSITION_SIZE),
                reduce_only=True,
            )

            response = result.get("response", {})
            statuses = response.get("data", {}).get("statuses", [{}])
            status = statuses[0] if statuses else {}

            if "filled" in status:
                fill = status["filled"]
                exit_price = float(fill.get("avgPx", price))
                pnl = (exit_price - self.entry_price) * POSITION_SIZE
                pnl_pct = (exit_price - self.entry_price) / self.entry_price

                self.in_position = False
                self.total_pnl += pnl
                self.num_trades += 1

                if pnl < 0:
                    self.daily_loss += abs(pnl)

                self.trade_log.log_fill(
                    "SELL", price=exit_price, size=POSITION_SIZE, oid=fill.get("oid")
                )
                self.trade_log.log_trade_closed(
                    side="LONG",
                    entry_price=self.entry_price,
                    exit_price=exit_price,
                    size=POSITION_SIZE,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    entry_time=self.entry_time,
                )

                logger.info(
                    "SELL filled: exit=%.2f entry=%.2f PnL=%+.4f USDC (%+.2f%%)",
                    exit_price,
                    self.entry_price,
                    pnl,
                    pnl_pct * 100,
                )
                self.risk.update_balance(INITIAL_BALANCE + self.total_pnl)

            else:
                error = status.get("error", "Unknown error")
                logger.warning("Sell order rejected: %s", error)
                self.trade_log.log_error(f"Sell rejected: {error}")

        except Exception as e:
            logger.exception("Failed to place sell order: %s", e)
            self.trade_log.log_error(str(e), context={"action": "SELL"})

    def _shutdown(self) -> None:
        """Clean shutdown — logs session summary."""
        final_balance = INITIAL_BALANCE + self.total_pnl
        self.trade_log.log_session_end(
            balance=final_balance,
            total_pnl=self.total_pnl,
            num_trades=self.num_trades,
        )
        logger.info(
            "Session ended — trades: %d | total PnL: %+.4f USDC | balance: %.2f",
            self.num_trades,
            self.total_pnl,
            final_balance,
        )

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    runner = LiveRunner()
    runner.run()
