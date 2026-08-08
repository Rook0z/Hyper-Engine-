# Hyper-Engine

A production-grade algorithmic trading framework built on the [Hyperliquid](https://hyperliquid.xyz) L1 blockchain.

Built from scratch in Python — no trading libraries, no shortcuts. Every indicator, strategy, and risk rule is implemented from the mathematical formula up.

---

## What It Does

```
Fetch real BTC data from Hyperliquid
    → Clean the data
        → Backtest EMA, RSI, and Bollinger Bands strategies
            → Pick the best by Sharpe ratio
                → Paper trade the winner with live market data
```

---

## Architecture

```
src/
├── hyperliquid/     ← Hyperliquid API client (auth, HTTP, responses, trading)
├── data/            ← OHLCV candle fetching and pagination
├── indicators/      ← EMA, RSI, Bollinger Bands (built from formula)
├── strategies/      ← EMA crossover, RSI, Bollinger (signal generation)
├── backtester/      ← Backtest engine + performance metrics (pandas + numpy)
├── risk/            ← Position sizing, daily loss limits, Kelly criterion
├── core/            ← Config, logging, exceptions, utilities
└── strategy_runner.py ← Main pipeline
```

---

## Installation

**Requirements:** Python 3.12+, [Poetry](https://python-poetry.org)

```bash
git clone https://github.com/Rook0z/Hyper-Engine-.git
cd Hyper-Engine-
poetry install
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

```env
HL_PRIVATE_KEY=0x...        # API wallet private key
HL_ACCOUNT_ADDRESS=0x...    # Master wallet address (NOT the API wallet)
HL_BASE_URL=https://api.hyperliquid-testnet.xyz
```

> **Always use testnet first.** Never set `IS_MAINNET=true` until fully verified.

All other settings have sensible defaults. Override in `.env` only if needed:

```env
SYMBOL=BTC
INTERVAL=1h
POSITION_SIZE=0.001
INITIAL_CAPITAL=10000
RUN_HOURS=2
```

---

## Usage

### Run the full pipeline

```bash
poetry run python src/strategy_runner.py
```

Output:
```
=================================================================
  HYPER-ENGINE STRATEGY PIPELINE
=================================================================

Fetching 500 candles of BTC 1h...
Backtesting EMA Crossover 9/21...
Backtesting RSI(14) OB=70/OS=30...
Backtesting Bollinger(20, 2.0)...

=================================================================
  STRATEGY COMPARISON
=================================================================
  Strategy                       Trades        PnL   Sharpe  WinRate
-----------------------------------------------------------------
  RSI(14) OB=70/OS=30                 2      +0.11   0.7606   50.0%
  Bollinger(20, 2.0)                  5      -3.55  -5.7327   40.0%
  EMA Crossover 9/21                 13      -4.32  -6.8681   38.5%
=================================================================

  Selected : RSI(14) OB=70/OS=30
  Starting 2h paper trade...
```

### Run tests

```bash
poetry run pytest --cov=src
```

### Lint and format

```bash
poetry run ruff format .
poetry run ruff check .
poetry run mypy src tests
```

---

## Strategies

| Strategy | Type | Signal |
|---|---|---|
| EMA Crossover | Trend following | Fast EMA crosses above/below slow EMA |
| RSI | Mean reversion | RSI crosses below 30 (buy) or above 70 (sell) |
| Bollinger Bands | Mean reversion | Price crosses outside the bands |

The pipeline backtests all three on recent data and selects the best by Sharpe ratio. A minimum Sharpe of 0.5 is required to proceed to paper trading.

---

## Adding a Strategy

1. Create `src/strategies/my_strategy.py`
2. Inherit from `BaseStrategy`
3. Implement `generate_signal(closes: list[float]) -> str`
4. Return `"BUY"`, `"SELL"`, or `"HOLD"` — nothing else
5. Write tests in `tests/test_my_strategy.py`
6. Add to the strategies list in `strategy_runner.py`

```python
from strategies.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "My Strategy"

    @property
    def min_periods(self) -> int:
        return 20  # minimum closes needed

    def generate_signal(self, closes: list[float]) -> str:
        if len(closes) < self.min_periods:
            return self.HOLD
        # your logic here
        return self.HOLD
```

---

## Project Structure

```
Hyper-Engine/
├── src/
│   ├── hyperliquid/
│   │   ├── auth.py           ← EIP-712 signing, phantom agent
│   │   ├── client.py         ← HTTP client, retry + backoff
│   │   ├── responses.py      ← Pydantic response models
│   │   ├── symbol.py         ← Asset ID resolution
│   │   ├── market.py         ← Prices, orderbook, trades
│   │   ├── account.py        ← Balances, positions, fills
│   │   └── trading.py        ← Orders, cancels, leverage
│   ├── data/
│   │   └── ohlcv_provider.py ← Candle fetching + pagination
│   ├── indicators/
│   │   ├── ema.py            ← Exponential Moving Average
│   │   ├── rsi.py            ← RSI (Wilder smoothing)
│   │   └── bollinger.py      ← Bollinger Bands
│   ├── strategies/
│   │   ├── base_strategy.py  ← Abstract base class
│   │   ├── ema_strategy.py   ← EMA crossover
│   │   ├── rsi_strategy.py   ← RSI overbought/oversold
│   │   └── bb_strategy.py    ← Bollinger mean reversion
│   ├── backtester/
│   │   ├── backtester.py     ← Backtest engine (pandas)
│   │   └── performance.py    ← Sharpe, Sortino, Calmar, drawdown
│   ├── risk/
│   │   └── risk_manager.py   ← Position sizing, Kelly criterion
│   ├── core/
│   │   ├── config.py         ← Centralised settings (pydantic-settings)
│   │   ├── trade_logger.py   ← Structured JSON trade logging
│   │   ├── exceptions.py     ← Custom exception hierarchy
│   │   └── utils.py          ← Shared utilities
│   └── strategy_runner.py    ← Main pipeline
├── tests/                    ← Full test suite (100+ tests, 87%+ coverage)
├── docs/
│   ├── hyperliquid_notes.md
│   ├── hyperliquid_architecture.md
│   
├── .env.example
├── pyproject.toml
└── README.md
```

---

## Key Technical Decisions

- **EIP-712 signing** — Hyperliquid uses Ethereum wallet auth, not API keys. Every order is signed with a private key using the phantom agent construction.
- **No trading libraries** — every indicator is built from the mathematical formula. EMA, RSI (Wilder smoothing), Bollinger Bands — all from scratch.
- **Pandas + numpy backtester** — vectorised operations, no Python loops for performance-critical code.
- **TDD** — tests written alongside the code. 100+ tests, all HTTP mocked, zero real network calls in the test suite.
- **Pydantic v2 responses** — every API response validated at the boundary with `extra="ignore"` for forward compatibility.
- **Centralised config** — all settings in one place via `pydantic-settings`. Override anything from `.env`.

---

## Logs

Every paper trade session writes structured JSON logs to `logs/trades_YYYY-MM-DD.jsonl`.

```bash
# View today's signals
cat logs/trades-$(date +%Y-%m-%d).jsonl | python -m json.tool

# Count trades
grep '"action": "TRADE_CLOSED"' logs/trades-*.jsonl | wc -l
```

---


## License

MIT