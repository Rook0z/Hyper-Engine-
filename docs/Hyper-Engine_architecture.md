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
│   ├── Hyper-Engine_architecture.md
│   └── dashboard.md
│
├── src/
│   ├── hyperliquid/
│   ├── stats/
│   ├── data/
│   ├── indicators/
│   ├── strategies/
│   ├── backtester/
│   ├── risk/
│   ├── execution/
│   ├── core/
│   └── dashboard/
│
├── storage/            ← hyper_engine.db (SQLite, gitignored)
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

### `src/execution/`

```
execution/
├── testnet_executor.py  ← places REAL orders on Hyperliquid TESTNET
│                          submit_market_order() / wait_for_fill() /
│                          get_position_size() / has_open_orders()
│                          refuses to construct unless IS_MAINNET=false
│                          AND ENABLE_TESTNET_LIVE_EXECUTION=true
└── smoke_test.py        ← one-shot proof: BUY -> confirmed fill -> SELL
                           -> confirmed fill, using TestnetExecutor
                           directly; persists through TradeLogger/
                           Database like a real strategy_runner session
```

The ONLY package that is allowed to place, or wait on the fill of, a real
order. `strategy_runner.live_testnet_trade()` and `execution/smoke_test.py`
are the only two callers — both go through this same executor, never a
separate order-submission path. A SELL is never submitted unless the
preceding BUY is CONFIRMED filled (checked via the account's actual fills,
not assumed from the order response).

---

### `src/core/`

```
core/
├── config.py         ← all settings in one place (pydantic-settings)
│                      reads .env; includes the IS_MAINNET and
│                      ENABLE_TESTNET_LIVE_EXECUTION safety switches
├── database.py       ← SQLite persistence layer — sessions, orders,
│                      fills, trades, analysis_results (backtest/OOS/
│                      walk-forward/Monte Carlo). The dashboard's ONLY
│                      data source — it never reads anything else.
├── trade_logger.py   ← logs every order, fill, PnL, timestamp to
│                      structured JSONL (logs/trades_YYYY-MM-DD.jsonl)
│                      AND, when constructed with db=Database(), to the
│                      same SQLite database — one call site, two
│                      durable records, never a second logging path to
│                      drift out of sync with the dashboard.
├── exceptions.py     ← custom exception hierarchy
└── utils.py          ← shared utilities (timestamps, rounding, formatting)
```

You cannot improve what you do not measure.
Every professional trading system logs everything — and every log call
that matters to "what happened" also durably persists to SQLite, not just
a file, so it survives independently of the log file and is queryable.

---

### `src/dashboard/`

```
dashboard/
├── app.py            ← Streamlit entrypoint (poetry run streamlit run
│                      src/dashboard/app.py); page routing only
├── data.py           ← read-only data access layer — no Streamlit import
│                      anywhere in this file, so it's fully unit-
│                      testable without the dashboard dependency group.
│                      Every function takes a Database and returns
│                      plain dicts/lists; calls PerformanceAnalyser for
│                      any metric that already has a home there rather
│                      than recomputing it.
└── views/            ← one module per page: Overview, Trading History,
                       Orders & Fills, Performance, Strategy Analysis,
                       Monte Carlo, Risk
```

Read-only by construction — the dashboard never calls anything in
`src/execution/`, `src/hyperliquid/trading.py`, or `src/risk/`; it only
reads from `src/core/database.py`. It cannot place, cancel, or modify an
order no matter what the person clicks. Makes every persisted session —
paper trade, real testnet execution, or smoke test — visible without
touching code. See `docs/dashboard.md` for the full page-by-page writeup.

---

## How Everything Connects

```
src/hyperliquid/         ← only thing that talks to the exchange
      │
      ├─→ src/data/         ← fetches candles via the client
      │         │
      │         └─→ src/indicators/   ← computes signals from candles
      │                    │
      │                    └─→ src/strategies/  ← BUY / SELL / HOLD
      │                               │
      │                    src/stats/ ─┤
      │                               │
      │                    src/risk/ ──┤← validates + sizes the signal
      │                               │
      │              ┌───────────────┴──────────────────────┐
      │              │                                            │
      │     paper_trade():                            live_testnet_trade():
      │     simulated fill,                            src/execution/
      │     no real order                              testnet_executor.py
      │     (src/strategy_runner.py)                   ← REAL Hyperliquid
      │                                                 TESTNET order,
      │                                                 confirmed-fill only
      │              │                                            │
      │              └───────────────┬──────────────────────┘
      │                                 │
      │                        src/core/trade_logger.py
      │                        ← JSONL file AND, via db=Database(),
      │                          src/core/database.py (SQLite)
      │                                 │
      └──────────────────────────→  src/dashboard/  ← reads ONLY the
                                          database, shows everything
```

The dependency only flows downward.
`src/hyperliquid/` is the only package that knows about the exchange.
Everything above it is pure Python — no API calls, fully testable.
Both `paper_trade()` and `live_testnet_trade()` write through the exact
same `TradeLogger`/`Database`, so the dashboard sees both the same way —
it is never told which mode produced a given session.

---

## Paper Trading & Live Testnet Execution — The Integration Points

Not separate folders. The day everything connects for the first time —
and it branches in two ways from the same point, both reusing every stage
up to and including risk management:

```
ohlcv_provider.py (data)
    → strategy.generate_signal() (strategies)
        → risk_manager.check_trade() (risk)
            → EITHER
              paper_trade(): simulated fill, no real order (default)
              OR
              live_testnet_trade(): src/execution/testnet_executor.py
                  → REAL Hyperliquid TESTNET order, confirmed-fill only,
                    SELL never submitted unless BUY confirmed filled
                → trade_logger.log() (core) → JSONL + SQLite
                    → src/dashboard/ (reads SQLite only)
```

Which branch runs is controlled by one explicit switch,
`ENABLE_TESTNET_LIVE_EXECUTION` (`.env`), checked in
`strategy_runner.run_pipeline()`. `TestnetExecutor` independently
re-verifies both `IS_MAINNET=false` and the testnet base URL at
construction time — it does not trust the caller to have already checked.
`execution/smoke_test.py` exercises the same `TestnetExecutor` directly
(BUY → confirmed fill → SELL → confirmed fill, in one shot) as a fast way
to prove the execution path and the dashboard are both working, without
waiting on a live strategy signal.

Run on Hyperliquid testnet first.
Live data behaves differently than historical — paper trading and real
testnet execution both reveal issues backtesting never finds; testnet
execution additionally reveals order-lifecycle issues paper trading can't
(actual fill latency, actual rejection reasons, actual partial fills).

---

## The Rule That Doesn't Change

Every folder has one job. Every file inside it has one job.
No folder bleeds into another's responsibility.

One job. One place. Always.

---
