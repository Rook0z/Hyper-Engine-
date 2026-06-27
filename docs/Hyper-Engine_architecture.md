# Hyper-Engine Architecture

---

## What Hyper-Engine Is

A production-grade algorithmic trading framework built on the Hyperliquid L1.
Full stack: API client → data → indicators → strategies → backtester → risk → live trading → dashboard.

---

## Full Project Structure

```
Hyper-Engine/
│
├── docs/
│   ├── hyperliquid_notes.md
│   ├── hyperliquid_architecture.md
│   
│   
│
├── src/
│   ├── hyperliquid/
│   ├── stats/
│   ├── data/
│   ├── indicators/
│   ├── strategies/
│   ├── backtester/
│   ├── risk/
│   ├── core/
│   └── dashboard/
│
├── tests/
├── .env
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## Hyperliquid API Client 

**Folder:** `src/hyperliquid/`

```
src/hyperliquid/
├── __init__.py
├── auth.py           ← EIP-712 signing, phantom agent, wallet management
├── client.py         ← HTTP layer, /info and /exchange, retry + backoff
├── responses.py      ← Pydantic models for every API response
├── symbol.py         ← symbol → asset ID lookup, loaded once at startup
├── market.py         ← prices, orderbook, trades, funding rates
├── account.py        ← balances, positions, open orders, fills
├── trading.py        ← limit orders, market orders, cancel, leverage
└── websocket.py      ← live price and orderbook streaming (Phase 2)
```

---

## Execution Engine & Strategy

---

### `src/stats/`

```
stats/
└── basic_stats.py    ← mean, std, variance, expected value,
                         win rate, profit factor
```

The mathematical foundation. Everything above depends on these.
Built from scratch — no libraries for the core math.

---

### `src/data/`

```
data/
└── ohlcv_provider.py ← fetches OHLCV candle data from Hyperliquid
                         type: candleSnapshot via /info
                         returns clean pandas DataFrames
                         handles 500-row limit with automatic pagination
```

Feeds historical price data to the backtester.
Feeds live price data to strategies.
Uses the Phase 1 client directly.

---

### `src/indicators/`

```
indicators/
├── ema.py         ← Exponential Moving Average
├── rsi.py         ← Relative Strength Index (Wilder smoothing)
├── bollinger.py   ← Bollinger Bands (mean ± 2 standard deviations)
└── vwap.py        ← Volume Weighted Average Price
```

- Takes a `pd.DataFrame` from `ohlcv_provider.py` as input
- Returns the same DataFrame with new indicator columns added
- Pure functions — no side effects, no API calls
- Built from the mathematical formula — not TA-Lib

---

### `src/strategies/`

```
strategies/
├── base_strategy.py    ← abstract base class, defines generate_signal()
├── ema_strategy.py     ← trend following via EMA crossover
├── rsi_strategy.py     ← momentum via RSI overbought/oversold levels
├── bb_strategy.py      ← mean reversion on Bollinger Band touches
└── vwap_strategy.py    ← price vs VWAP as directional signal
```

- Consume indicators from `src/indicators/`
- Output a signal: BUY, SELL, or HOLD — nothing else
- Never place orders directly — signal only, execution acts
- All inherit from `base_strategy.py` — same interface, swappable

---

### `src/backtester/`

```
backtester/
├── backtester.py     ← simulates strategy on historical OHLCV data
│                        replays candles one by one
│                        calls strategy.generate_signal() each candle
│                        simulates fills with slippage model
└── performance.py    ← PnL, win rate, max drawdown, number of trades,
                         Sharpe ratio, Sortino ratio, Calmar ratio,
                         max drawdown duration, equity curve
```

Never trade a strategy you haven't backtested.
Slippage modeling is required — backtests without slippage are lies.

---

### `src/risk/`

```
risk/
└── risk_manager.py   ← max position size per asset
                         max open positions
                         daily loss limit
                         max drawdown limit
                         position sizing via Kelly criterion
```

Sits between strategy signals and order execution.
Strategy says "BUY BTC" — risk manager decides how much and whether to allow it.
A strategy with no risk management is a gambling system.

---

### `src/core/`

```
core/
└── trade_logger.py   ← logs every order, fill, PnL, timestamp
                         structured JSON format
                         persistent record of every action the system takes
```

You cannot improve what you do not measure.
Every professional trading system logs everything.

---

### `src/dashboard/`

```
dashboard/
└── dashboard.py      ← terminal dashboard using the rich library
                         live strategy PnL, open positions, recent fills
                         account balance, system health
                         connects to live Hyperliquid WebSocket data
```

Makes the live system visible without touching code.

---

## How Everything Connects

```
src/hyperliquid/         ← only thing that talks to the exchange
      │
      ├──→ src/data/         ← fetches candles via Phase 1 client
      │         │
      │         └──→ src/indicators/   ← computes signals from candles
      │                    │
      │                    └──→ src/strategies/  ← BUY / SELL / HOLD
      │                               │
      │                    src/stats/ ─┤
      │                               │
      │                    src/risk/ ──┤← validates + sizes the signal
      │                               │
      └──→ src/hyperliquid/trading.py ←┘← executes the order
                    │
           src/core/trade_logger.py   ← logs everything
                    │
           src/dashboard/             ← shows everything live
```

The dependency only flows downward.
`src/hyperliquid/` is the only package that knows about the exchange.
Everything above it is pure Python — no API calls, fully testable.

---

## Paper Trading — The Integration Point

Not a separate folder. The day everything connects for the first time:

```
ohlcv_provider.py (data)
    → strategy.generate_signal() (strategies)
        → risk_manager.check() (risk)
            → trading.place_order() (hyperliquid)
                → trade_logger.log() (core)
```

Run on Hyperliquid testnet first.
Live data behaves differently than historical — paper trading reveals
issues backtesting never finds.

---

## The Rule That Doesn't Change

Every folder has one job. Every file inside it has one job.
No folder bleeds into another's responsibility.

One job. One place. Always.

---
