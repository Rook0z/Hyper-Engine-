import pytest
from pydantic import ValidationError
from core.config import Settings


# ──────────────────────────────────────────────────────────────
# ENV ISOLATION
#
# Settings loads config in order: class defaults -> .env file ->
# OS environment variables (each overriding the last). A plain
# Settings() — or even Settings(_env_file=None), which only skips the
# .env FILE — will still silently pick up matching OS environment
# variables from the developer's shell (e.g. an exported INTERVAL=5m,
# RSI_PERIOD=5 left over from running the live runner locally).
#
# The isolated_settings fixture strips every OS environment variable
# that matches a Settings field name (case-insensitively) for the
# duration of a test, so Settings(_env_file=None) inside that test
# reflects the class's true defaults regardless of what's exported in
# the local shell or set in .env.
# ──────────────────────────────────────────────────────────────

SETTINGS_FIELD_NAMES = list(Settings.model_fields.keys())


@pytest.fixture
def isolated_settings(monkeypatch):
    for name in SETTINGS_FIELD_NAMES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)
    yield


# ──────────────────────────────────────────────────────────────
# DEFAULTS
# ──────────────────────────────────────────────────────────────


def test_default_symbol(isolated_settings):
    s = Settings(_env_file=None)
    assert s.symbol == "BTC"


def test_default_interval(isolated_settings):
    s = Settings(_env_file=None)
    assert s.interval == "1h"


def test_default_is_testnet(isolated_settings):
    s = Settings(_env_file=None)
    assert s.is_mainnet is False


def test_default_position_size(isolated_settings):
    s = Settings(_env_file=None)
    assert s.position_size == 0.001


def test_default_initial_capital(isolated_settings):
    s = Settings(_env_file=None)
    assert s.initial_capital == 10_000.0


def test_default_ema_periods(isolated_settings):
    s = Settings(_env_file=None)
    assert s.ema_fast_period == 9
    assert s.ema_slow_period == 21


def test_default_rsi_settings(isolated_settings):
    s = Settings(_env_file=None)
    assert s.rsi_period == 14
    assert s.rsi_oversold == 30.0
    assert s.rsi_overbought == 70.0


def test_default_bb_settings(isolated_settings):
    s = Settings(_env_file=None)
    assert s.bb_period == 20
    assert s.bb_num_std == 2.0


def test_default_sleep_seconds(isolated_settings):
    s = Settings(_env_file=None)
    assert s.sleep_seconds == 60


def test_default_run_hours(isolated_settings):
    s = Settings(_env_file=None)
    assert s.run_hours == 2.0


def test_default_log_dir(isolated_settings):
    s = Settings(_env_file=None)
    assert s.log_dir == "logs"


def test_default_backtest_candles(isolated_settings):
    s = Settings(_env_file=None)
    assert s.backtest_candles == 500


def test_default_min_sharpe(isolated_settings):
    s = Settings(_env_file=None)
    assert s.min_sharpe_to_trade == 0.5


# ──────────────────────────────────────────────────────────────
# OVERRIDE VIA KWARGS
#
# These pass values as explicit constructor kwargs, which is the
# highest-precedence source in pydantic-settings — always wins over
# env vars and .env regardless of what's exported locally, so no
# isolation fixture is needed here.
# ──────────────────────────────────────────────────────────────


def test_override_symbol():
    s = Settings(symbol="ETH")
    assert s.symbol == "ETH"


def test_override_interval():
    s = Settings(interval="5m")
    assert s.interval == "5m"


def test_override_is_mainnet():
    s = Settings(is_mainnet=True)
    assert s.is_mainnet is True


def test_override_capital():
    s = Settings(initial_capital=5_000.0)
    assert s.initial_capital == 5_000.0


def test_override_position_size():
    s = Settings(position_size=0.01)
    assert s.position_size == 0.01


def test_override_ema_periods():
    s = Settings(ema_fast_period=12, ema_slow_period=26)
    assert s.ema_fast_period == 12
    assert s.ema_slow_period == 26


def test_override_rsi():
    s = Settings(rsi_period=9, rsi_oversold=20.0, rsi_overbought=80.0)
    assert s.rsi_period == 9
    assert s.rsi_oversold == 20.0
    assert s.rsi_overbought == 80.0


# ──────────────────────────────────────────────────────────────
# VALIDATORS
#
# Explicit kwargs here too — validators fire on the passed value
# regardless of env/.env state, so no isolation needed.
# ──────────────────────────────────────────────────────────────


def test_invalid_interval_raises():
    with pytest.raises(ValidationError, match="interval"):
        Settings(interval="2d")


def test_invalid_interval_empty_raises():
    with pytest.raises(ValidationError):
        Settings(interval="")


def test_valid_intervals_pass():
    valid = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d"]
    for interval in valid:
        s = Settings(interval=interval)
        assert s.interval == interval


def test_rsi_oversold_above_50_raises():
    with pytest.raises(ValidationError, match="below 50"):
        Settings(rsi_oversold=60.0)


def test_rsi_overbought_below_50_raises():
    with pytest.raises(ValidationError, match="above 50"):
        Settings(rsi_overbought=40.0)


def test_position_size_zero_raises():
    with pytest.raises(ValidationError):
        Settings(position_size=0.0)


def test_position_size_negative_raises():
    with pytest.raises(ValidationError):
        Settings(position_size=-0.001)


def test_initial_capital_zero_raises():
    with pytest.raises(ValidationError):
        Settings(initial_capital=0.0)


def test_max_position_pct_over_1_raises():
    with pytest.raises(ValidationError):
        Settings(max_position_pct=1.5)


def test_sleep_seconds_zero_raises():
    with pytest.raises(ValidationError):
        Settings(sleep_seconds=0)


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────


def test_has_credentials_false_when_empty():
    s = Settings(hl_private_key="", hl_account_address="")
    assert s.has_credentials() is False


def test_has_credentials_true_when_set():
    s = Settings(
        hl_private_key="0xabc123",
        hl_account_address="0xdef456",
    )
    assert s.has_credentials() is True


def test_assert_credentials_raises_when_empty():
    s = Settings(hl_private_key="", hl_account_address="")
    with pytest.raises(ValueError, match="HL_PRIVATE_KEY"):
        s.assert_credentials()


def test_assert_credentials_passes_when_set():
    s = Settings(
        hl_private_key="0xabc123",
        hl_account_address="0xdef456",
    )
    s.assert_credentials()  # should not raise


def test_assert_testnet_raises_when_mainnet():
    s = Settings(is_mainnet=True)
    with pytest.raises(ValueError, match="IS_MAINNET"):
        s.assert_testnet()


def test_assert_testnet_passes_when_testnet():
    s = Settings(is_mainnet=False)
    s.assert_testnet()  # should not raise


def test_summary_contains_symbol():
    s = Settings(symbol="ETH")
    assert "ETH" in s.summary()


def test_summary_contains_interval():
    s = Settings(interval="4h")
    assert "4h" in s.summary()


def test_summary_contains_mainnet_flag():
    s = Settings(is_mainnet=False)
    assert "False" in s.summary()


def test_summary_returns_string():
    s = Settings()
    assert isinstance(s.summary(), str)


# ──────────────────────────────────────────────────────────────
# SINGLETON IMPORT
#
# These intentionally test the real settings singleton as-is
# (reflecting real .env / environment), not isolated defaults — that
# is the correct behavior for these two tests, so no fixture is used.
# ──────────────────────────────────────────────────────────────


def test_settings_singleton_importable():
    from core.config import settings

    assert settings is not None
    assert isinstance(settings, Settings)


def test_settings_singleton_has_defaults():
    from core.config import settings

    assert settings.symbol == "BTC"
    assert settings.is_mainnet is False
