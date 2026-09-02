# ⚡ Hyper-Engine

## Algorithmic Trading Framework for Hyperliquid

> A production-oriented algorithmic trading framework built from scratch in Python, covering the trading lifecycle from market data and strategy research to risk management, testnet execution, persistence, and monitoring.

---

## 📌 Project Overview

**Hyper-Engine** is an algorithmic trading framework I built from scratch for the Hyperliquid L1 ecosystem.

The objective was not simply to build a trading strategy or a trading bot. I wanted to understand and implement the engineering systems required to take a trading idea through the complete lifecycle:

```text
Market Data
     ↓
Indicators
     ↓
Strategy
     ↓
Backtesting
     ↓
Performance Analysis
     ↓
Strategy Selection
     ↓
Risk Management
     ↓
Execution
     ↓
Order / Fill Tracking
     ↓
Persistence
     ↓
Monitoring
```

The project combines quantitative research, asynchronous programming, API integration, execution logic, risk controls, database persistence, testing, and observability into one system.

---

## 🎯 Problem

Algorithmic trading systems are often presented as:

```text
Market Data → Strategy → Buy/Sell
```

In reality, a reliable trading system needs to solve many more problems:

- A strategy needs historical data to be evaluated.
- Its performance needs to be measured.
- Risk needs to be evaluated before an order is submitted.
- Orders need to be tracked independently from signals.
- A submitted order is not necessarily a filled order.
- Execution can fail or timeout.
- Trading state needs to survive process restarts.
- Once the system is running, there needs to be a way to monitor what is happening.

Hyper-Engine was built to explore these problems as an integrated software system rather than as isolated scripts.

---

## 🏗️ Architecture

The system is organized into separate components with clearly defined responsibilities.

```text
                    HYPER-ENGINE
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     Market Data     Strategies        Risk
          │              │              │
          └──────────────┼──────────────┘
                         │
                    Backtesting
                         │
                Performance Analysis
                         │
                  Strategy Selection
                         │
                  Execution Engine
                         │
                  Order / Fill State
                         │
                    Trade Logger
                         │
                     SQLite DB
                         │
                    Dashboard
```

The architecture keeps strategy research, execution, persistence, and monitoring separated so that individual components can be tested and changed without rewriting the entire system.

---

## 📡 1. Market Data

Hyper-Engine integrates directly with Hyperliquid's APIs to retrieve market information.

The data layer supports historical OHLCV data used for strategy research and backtesting, while the system architecture also supports real-time market data for execution workflows.

A typical strategy run begins by connecting to the configured Hyperliquid environment and retrieving historical candles.

Example:

```text
Connected to Hyperliquid testnet

Fetching 500 candles of BTC 1h...
Fetched 500 candles
Data cleaned: 500 kept, 0 removed
```

The data is validated before being passed to the strategy and backtesting layers.

---

## 📊 2. Technical Indicators

Rather than relying on a technical-analysis library for the core indicators, I implemented the indicators directly in Python.

Current indicators include:

- EMA
- RSI
- Bollinger Bands
- VWAP

The RSI implementation uses Wilder smoothing.

The purpose was to understand the calculations at the implementation level rather than treating indicators as black-box functions. This also makes the indicator layer independently testable.

---

## 🧠 3. Strategy Layer

Hyper-Engine currently supports multiple strategies that can operate through the same framework.

The strategy layer includes:

- EMA Crossover
- RSI
- Bollinger Bands
- VWAP Crossover

Each strategy is evaluated using the same backtesting infrastructure. This makes it possible to compare strategies using consistent performance metrics rather than evaluating each strategy through separate scripts.

---

## 🧪 4. Backtesting

Historical data is passed through the backtesting engine to evaluate strategy behavior before execution.

The backtester records information such as:

- Number of trades
- Profit and loss
- Winning trades
- Losing trades
- Win rate
- Returns
- Risk-adjusted performance

Example strategy comparison:

```text
STRATEGY COMPARISON

Strategy                 Trades    PnL      Sharpe    WinRate
VWAP(Crossover)             3     +14.53    9.3583     66.7%
Bollinger(20, 2.0)          6      +2.55    7.5927     66.7%
EMA Crossover 9/21         10      +7.86    2.9529     20.0%
RSI(14)                     2      -0.10   -1.7589     50.0%
```

In this particular run, VWAP Crossover produced the highest Sharpe ratio and was selected by the strategy-selection logic.

> **Important:** These are backtest results from a specific dataset/run. They are not a claim of live profitability or future performance.

---

## 📈 5. Performance Analysis

The framework separates strategy execution from performance analysis. This allows the system to evaluate strategies using quantitative metrics rather than relying only on raw PnL.

Metrics include:

- Total PnL
- Trade count
- Win rate
- Sharpe ratio
- Drawdown-related analysis
- Strategy-level performance

Additional research components include:

- Walk-forward analysis
- Out-of-sample analysis
- Monte Carlo analysis

The goal is to make strategy evaluation more robust than simply checking whether a backtest made money.

---

## 🛡️ 6. Risk Management

A strategy signal does not automatically become an order. Before execution, the signal passes through the risk-management layer.

The framework includes functionality for:

- Position sizing
- Risk limits
- Daily loss controls
- Kelly-based sizing
- Position constraints
- Execution safety checks

The architecture treats risk management as a separate component rather than embedding risk rules directly inside individual strategies. This makes the same risk controls reusable across different strategies.

---

## ⚡ 7. Hyperliquid Execution

Hyper-Engine integrates with Hyperliquid for order execution.

The execution layer handles:

- EIP-712 signing
- Account authentication
- Order submission
- Order status
- Fill confirmation
- Position tracking
- Order cancellation
- Testnet execution

The system explicitly distinguishes between research/paper execution and real testnet execution. Testnet execution is protected by explicit configuration and safety checks to prevent accidental mainnet execution.

---

## 🔐 8. Execution Safety

One of the most important design decisions was treating execution state explicitly.

A trading signal saying **BUY** does not mean **BUY FILLED**.

The system therefore tracks execution state rather than assuming that a submitted order succeeded.

For a two-leg trade lifecycle:

```text
BUY submitted
      ↓
BUY confirmed
      ↓
SELL allowed
      ↓
SELL submitted
      ↓
SELL confirmed
      ↓
Trade completed
```

A SELL cannot proceed simply because a BUY request was submitted. The BUY must reach the required confirmed-fill state first.

Similarly, failed or timed-out execution legs must not silently advance the trade lifecycle. This prevents execution state from becoming disconnected from actual exchange state.

---

## 💾 9. Persistence

Trading activity is persisted through SQLite.

The persistence layer records information such as:

- Trading sessions
- Signals
- Orders
- Fills
- Trades
- Execution events

The purpose is to maintain a persistent source of truth rather than relying only on terminal output or in-memory Python objects. The same database is used by the trading system and the monitoring dashboard.

---

## 📊 10. Monitoring Dashboard

Hyper-Engine includes a read-only Streamlit dashboard for monitoring trading activity.

The dashboard provides views for:

- Overview
- Trades
- Orders & fills
- Performance
- Strategy analysis
- Monte Carlo analysis
- Risk

The dashboard does not implement a separate trading system. Instead, it reads the persisted state produced by the underlying trading components. This keeps monitoring separate from execution while still providing visibility into the system.

---

## 🧪 11. Testing

Testing was a major part of the project.

The system includes automated tests covering areas such as:

- Technical indicators
- Strategies
- Backtesting
- Performance analysis
- Risk management
- Execution behavior
- Order and fill handling
- Persistence
- Dashboard data access

External exchange interactions are mocked where appropriate so that the test suite can run without placing real orders. The goal is to verify both individual components and important system-level behavior.

Run the test suite with:

```bash
poetry run pytest
```

---

## 🔧 12. Technology Stack

**Core**
- Python
- Poetry
- Pydantic

**Trading / APIs**
- Hyperliquid API
- HTTP APIs
- WebSockets
- EIP-712 signing
- httpx
- asyncio

**Quantitative Research**
- NumPy
- Pandas
- Custom indicators
- Backtesting engine
- Performance analysis
- Monte Carlo analysis
- Walk-forward testing

**Persistence**
- SQLite

**Monitoring**
- Streamlit

**Testing / Code Quality**
- Pytest
- Mypy
- Ruff

---

## 🔄 Complete Trading Lifecycle

The final architecture is designed around a complete trading lifecycle:

```text
                    Historical Data
                          ↓
                     Backtesting
                          ↓
                 Performance Analysis
                          ↓
                   Strategy Selection
                          ↓
                   Risk Management
                          ↓
                  Testnet Execution
                          ↓
                   Strategy Signal
                          ↓
                    BUY Request
                          ↓
                  BUY Confirmation
                          ↓
                    SELL Request
                          ↓
                  SELL Confirmation
                          ↓
                    Trade Logging
                          ↓
                       SQLite
                          ↓
                     Dashboard
```

Each stage has a defined responsibility and can be tested independently.

---

## 🧱 Engineering Principles

Several principles guided the implementation.

**1. Explicit state**

The system should know whether an order was:

- Requested
- Submitted
- Confirmed
- Filled
- Failed
- Timed out
- Cancelled

rather than assuming success.

**2. Separation of concerns**

Strategy logic should not be responsible for:

- Database implementation
- Exchange authentication
- Dashboard rendering
- Order-state management

Each concern belongs to its own component.

**3. Safety before execution**

A strategy signal must pass through the required risk and execution checks before an order can reach the exchange.

**4. One source of truth**

Execution, logging, persistence, and monitoring should operate around the same underlying trading state.

**5. Test before live execution**

The development lifecycle moves from:

```text
Research
   ↓
Backtest
   ↓
Validation
   ↓
Paper/Test
   ↓
Testnet
   ↓
Potential Mainnet Deployment
```

The project does not treat backtest performance as proof of live profitability.

---

## 📸 Example Run

A typical run begins with the engine connecting to Hyperliquid testnet:

```text
Connected - Config:
symbol=BTC
interval=1h
capital=10000
position=0.001
mainnet=False
```

The system then retrieves historical data:

```text
Fetching 500 candles of BTC 1h...
Fetched 500 candles
Data cleaned: 500 kept, 0 removed
```

The strategies are backtested:

- EMA Crossover 9/21
- RSI(14)
- Bollinger(20, 2.0)
- VWAP(Crossover)

The results are compared and a strategy is selected based on the configured selection criteria.

The selected strategy can then pass through risk management and, when explicitly enabled, enter Hyperliquid testnet execution.

---

## 🎯 What This Project Demonstrates

Hyper-Engine was primarily an engineering project. It demonstrates experience with:

- Designing modular trading systems
- Integrating financial APIs
- Asynchronous Python
- Algorithmic strategy implementation
- Backtesting
- Quantitative performance analysis
- Risk management
- Exchange order execution
- EIP-712 signing
- Order/fill state management
- Database persistence
- Automated testing
- Monitoring systems
- Failure handling

More importantly, the project gave me experience thinking about what happens between a strategy signal and a completed trade.

---

## 🚧 Future Development

Potential areas for future development include:

- More advanced execution algorithms
- Smart order routing
- Latency optimization
- Rust-based performance-critical components
- Additional exchange integrations
- More robust market microstructure models
- Distributed execution
- Advanced portfolio-level risk management

These are future directions rather than requirements for the current V1 system.

---

## ⚠️ Disclaimer

Hyper-Engine is an engineering and research project.

Backtested performance does not guarantee future results or live profitability. Testnet execution is used for validating execution behavior without exposing real capital.

Nothing in this project should be considered financial advice.

---

## 👨‍💻 About

I'm Rook, an algorithmic trading software developer focused on crypto trading infrastructure and automated financial systems.

My main areas of interest include:

- Algorithmic trading
- Trading system architecture
- Exchange APIs
- Automated execution
- Backtesting
- Risk management
- Crypto infrastructure
- Python backend systems

I'm open to remote roles, freelance contracts, and collaborations involving algorithmic trading, crypto infrastructure, backend engineering, and financial automation.

**Links**
- GitHub: https://github.com/Rook0z
- Hyper-Engine: https://github.com/Rook0z/Hyper-Engine-
- X: https://x.com/Rook0z
- LinkedIn: https://www.linkedin.com/in/daniel-j-2b4a413a7/