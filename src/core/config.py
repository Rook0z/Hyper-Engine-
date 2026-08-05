from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All Hyper-Engine configuration in one place.

    Settings are loaded in this order (later overrides earlier):
        1. Default values defined here
        2. .env file in project root
        3. Environment variables

    All field names map directly to env var names (case-insensitive).
    e.g. `hl_private_key` reads from `HL_PRIVATE_KEY` in .env
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # ignore unknown env vars
    )

    # ──────────────────────────────────────────────────────────────
    # HYPERLIQUID CREDENTIALS
    # ──────────────────────────────────────────────────────────────

    hl_private_key: str = Field(
        default="",
        description="Ethereum private key for signing (API wallet key, not master wallet).",
    )
    hl_account_address: str = Field(
        default="",
        description="Master wallet address (NOT the API wallet address).",
    )
    hl_base_url: str = Field(
        default="https://api.hyperliquid-testnet.xyz",
        description="Hyperliquid API base URL. Testnet by default.",
    )

    # ──────────────────────────────────────────────────────────────
    # TRADING SETTINGS
    # ──────────────────────────────────────────────────────────────

    symbol: str = Field(
        default="BTC",
        description="Asset to trade. e.g. BTC, ETH, SOL.",
    )
    interval: str = Field(
        default="1h",
        description=(
            "Candle interval for OHLCV data and strategy signals. "
            "Options: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 8h, 12h, 1d."
        ),
    )
    position_size: float = Field(
        default=0.001,
        gt=0,
        description="Size of each trade in base currency. e.g. 0.001 BTC.",
    )
    slippage_pct: float = Field(
        default=0.001,
        ge=0,
        lt=1,
        description="Slippage as fraction of fill price. 0.001 = 0.1%.",
    )
    is_mainnet: bool = Field(
        default=False,
        description="True = mainnet, False = testnet. ALWAYS False until fully tested.",
    )

    # ──────────────────────────────────────────────────────────────
    # CAPITAL & RISK
    # ──────────────────────────────────────────────────────────────

    initial_capital: float = Field(
        default=10_000.0,
        gt=0,
        description="Starting portfolio value in USDC.",
    )
    max_position_pct: float = Field(
        default=0.05,
        gt=0,
        le=1,
        description="Max position size as fraction of account. 0.05 = 5%.",
    )
    max_daily_loss_pct: float = Field(
        default=0.02,
        gt=0,
        le=1,
        description="Stop trading if daily loss exceeds this fraction. 0.02 = 2%.",
    )
    max_open_positions: int = Field(
        default=3,
        ge=1,
        description="Maximum number of concurrent open positions.",
    )

    # ──────────────────────────────────────────────────────────────
    # STRATEGY SETTINGS
    # ──────────────────────────────────────────────────────────────

    # EMA
    ema_fast_period: int = Field(
        default=9,
        ge=2,
        description="Fast EMA period for EMA crossover strategy.",
    )
    ema_slow_period: int = Field(
        default=21,
        ge=2,
        description="Slow EMA period for EMA crossover strategy.",
    )

    # RSI
    rsi_period: int = Field(
        default=14,
        ge=2,
        description="RSI calculation period.",
    )
    rsi_oversold: float = Field(
        default=30.0,
        ge=0,
        le=100,
        description="RSI level to trigger BUY signal.",
    )
    rsi_overbought: float = Field(
        default=70.0,
        ge=0,
        le=100,
        description="RSI level to trigger SELL signal.",
    )

    # Bollinger Bands
    bb_period: int = Field(
        default=20,
        ge=2,
        description="Bollinger Bands SMA period.",
    )
    bb_num_std: float = Field(
        default=2.0,
        gt=0,
        description="Number of standard deviations for Bollinger Bands.",
    )

    # VWAP
    vwap_mode: str = Field(
        default="crossover",
        description="VWAP strategy mode: 'crossover' (trend) or 'reversion' (mean reversion).",
    )
    vwap_num_std: float = Field(
        default=2.0,
        gt=0,
        description="Number of standard deviations for VWAP bands (used in reversion mode).",
    )

    # ──────────────────────────────────────────────────────────────
    # BACKTESTER SETTINGS
    # ──────────────────────────────────────────────────────────────

    backtest_candles: int = Field(
        default=500,
        ge=50,
        description="Number of candles to use for backtesting.",
    )
    min_sharpe_to_trade: float = Field(
        default=0.5,
        description=(
            "Minimum Sharpe ratio from backtest to proceed to paper trading. "
            "If no strategy exceeds this, no paper trade is started."
        ),
    )

    # ──────────────────────────────────────────────────────────────
    # RUNNER SETTINGS
    # ──────────────────────────────────────────────────────────────

    sleep_seconds: int = Field(
        default=60,
        ge=1,
        description="Seconds between each strategy check in the live runner.",
    )
    run_hours: float = Field(
        default=2.0,
        gt=0,
        description="How long to run the paper trade session in hours.",
    )
    log_dir: str = Field(
        default="logs",
        description="Directory for trade log files.",
    )

    # ──────────────────────────────────────────────────────────────
    # VALIDATORS
    # ──────────────────────────────────────────────────────────────

    @field_validator("interval")
    @classmethod
    def validate_interval(cls, v: str) -> str:
        valid = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"}
        if v not in valid:
            raise ValueError(f"interval must be one of {sorted(valid)}, got '{v}'")
        return v

    @field_validator("ema_fast_period", "ema_slow_period", mode="before")
    @classmethod
    def validate_ema_periods(cls, v: int) -> int:
        return int(v)

    @field_validator("rsi_oversold")
    @classmethod
    def validate_rsi_oversold(cls, v: float) -> float:
        if v >= 50:
            raise ValueError(f"rsi_oversold must be below 50, got {v}")
        return v

    @field_validator("rsi_overbought")
    @classmethod
    def validate_rsi_overbought(cls, v: float) -> float:
        if v <= 50:
            raise ValueError(f"rsi_overbought must be above 50, got {v}")
        return v

    @field_validator("vwap_mode")
    @classmethod
    def validate_vwap_mode(cls, v: str) -> str:
        valid = {"crossover", "reversion"}
        if v not in valid:
            raise ValueError(f"vwap_mode must be one of {sorted(valid)}, got '{v}'")
        return v

    # ──────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────

    def has_credentials(self) -> bool:
        """Returns True if API credentials are configured."""
        return bool(self.hl_private_key and self.hl_account_address)

    def assert_credentials(self) -> None:
        """Raises ValueError if credentials are missing."""
        if not self.has_credentials():
            raise ValueError(
                "HL_PRIVATE_KEY and HL_ACCOUNT_ADDRESS must be set in .env\n"
                "Copy .env.example to .env and fill in your credentials."
            )

    def assert_testnet(self) -> None:
        """Raises ValueError if IS_MAINNET is True — safety guard."""
        if self.is_mainnet:
            raise ValueError(
                "IS_MAINNET=True detected. "
                "Set IS_MAINNET=False to use testnet. "
                "Only set True after thorough testnet verification."
            )

    def summary(self) -> str:
        """Returns a human-readable config summary for logging."""
        return (
            f"Config: symbol={self.symbol} interval={self.interval} "
            f"capital={self.initial_capital:.0f} "
            f"position={self.position_size} "
            f"mainnet={self.is_mainnet} "
            f"url={self.hl_base_url}"
        )


settings = Settings()
