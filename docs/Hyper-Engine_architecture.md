# Hyper-Engine Architecture Plan
> **Phase 1**
> This document answers one question: what files am I building, what does each one do, and why does it exist?

---

## The Big Picture

The goal of Phase 1 is to build a **clean, tested, professional Python client** for the Hyperliquid API. Not a quick script — a structured codebase with separation of concerns, Pydantic validation, and proper error handling.

Every file has one job. No file does two jobs. That's the rule.

```
src/hyperliquid/
├── __init__.py
├── hyperliquid_auth.py        ← signing only
├── hyperliquid_client.py      ← HTTP only
├── hyperliquid_responses.py   ← data models only
└── hyperliquid_symbol.py      ← asset ID lookup only
```

---

## File-by-File Plan

---

### `__init__.py`
**Job:** Makes `src/hyperliquid/` a Python package. Exports the public interface.

**What goes in it:**
```python
from .hyperliquid_client import HyperliquidClient
from .hyperliquid_auth import HyperliquidAuth
```

**Why it exists:** So callers can do `from hyperliquid import HyperliquidClient` cleanly instead of digging into submodules.

**What does NOT go in it:** No logic. No classes. No signing. Just imports.

---

### `hyperliquid_auth.py`
**Job:** One job only — **sign requests**. Nothing else.

**Why it exists:** Signing is complex and completely separate from HTTP. It deserves its own file. If signing changes, only this file changes.

**What it contains:**

`HyperliquidAuth` class with:

| Method | What it does |
|---|---|
| `__init__(private_key, account_address)` | Loads the wallet from the private key. Stores the master account address. |
| `sign_l1_action(action, nonce, vault_address)` | Signs trading actions (order, cancel). Uses phantom agent + EIP-712 with chain ID 1337. |
| `sign_user_signed_action(action)` | Signs user-facing actions (withdraw, transfer, approveAgent). Uses EIP-712 directly with signatureChainId. |
| `__call__(action, nonce)` | Convenience — builds the full signed request body `{ action, nonce, signature }` ready to POST. |

**Dependencies it needs:**
- `eth_account` — for EIP-712 signing and wallet loading
- `msgpack` — for serializing L1 action payloads (field order matters)
- `time` — for nonce generation

**What it does NOT do:**
- No HTTP calls
- No Pydantic models
- No asset ID lookups
- No response parsing

**Key rules baked into this class:**
- Always lowercase addresses before signing
- Nonce = `int(time.time() * 1000)` — milliseconds
- `sign_l1_action` and `sign_user_signed_action` are separate methods — never merged

**How `__call__` is used (from Day 2 dunder methods work):**
```python
auth = HyperliquidAuth(private_key=..., account_address=...)
signed_body = auth(action={"type": "order", ...}, nonce=nonce)
# signed_body = { "action": {...}, "nonce": 123456789, "signature": { "r": ..., "s": ..., "v": 27 } }
```

**Study reference before writing:** `hyperliquid/utils/signing.py` in the official Python SDK.
Read it fully. Understand every line. Close it. Write yours from scratch.

---

### `hyperliquid_client.py`
**Job:** One job only — **make HTTP requests** to `/info` and `/exchange`. Nothing else.

**Why it exists:** HTTP transport is completely separate from signing and completely separate from data modelling. If the base URL changes, only this file changes. If the auth method changes, only `hyperliquid_auth.py` changes.

**What it contains:**

`HyperliquidClient` class with:

| Method | What it does |
|---|---|
| `__init__(auth, base_url, timeout)` | Takes an `HyperliquidAuth` instance. Stores base URL (defaults to testnet — always testnet first). |
| `info(payload)` | POST to `/info`. No signing needed. Returns raw dict. |
| `exchange(action)` | POST to `/exchange`. Calls `self.auth(action)` to sign. Returns raw dict. |
| `_post(endpoint, body)` | Private base method. Handles headers, timeout, error handling, logging. |

**How the client + auth work together:**
```python
# The client owns the HTTP layer
# The auth owns the signing layer
# They never bleed into each other

client = HyperliquidClient(auth=auth, base_url="https://api.hyperliquid-testnet.xyz")

# Info — no signing
positions = client.info({"type": "clearinghouseState", "user": "0x..."})

# Exchange — auto-signs via auth
result = client.exchange({"type": "order", ...})
```

**Error handling it must cover:**
- HTTP 4xx — raise `APIError` with status code and message
- HTTP 5xx — raise `NetworkError`, eligible for retry
- Rate limited (429) — raise `RateLimitError`
- JSON parse failure — raise `APIError`
- Timeout — raise `NetworkError`

**Dependencies it needs:**
- `httpx` (async) or `requests` (sync — simpler for Phase 1, upgrade later)
- `hyperliquid_auth.HyperliquidAuth` — injected, not imported directly
- Custom exceptions from `src/core/exceptions.py` (already built in the 100-day roadmap)
- `src/core/logger.py` — log every request and response (already built)

**What it does NOT do:**
- No signing logic
- No Pydantic validation
- No asset ID resolution
- No business logic

---

### `hyperliquid_responses.py`
**Job:** One job only — **define the shape of every API response** as a Pydantic model.

**Why it exists:** The API returns raw JSON dicts. Without models, you access fields like `response["marginSummary"]["accountValue"]` everywhere — fragile, no autocomplete, no validation. With Pydantic models, bad API responses are caught immediately at the boundary.

**What it contains — key models:**

```python
# Perpetuals
class PerpPosition(BaseModel): ...       # one open position
class MarginSummary(BaseModel): ...      # account value, margin used, etc.
class ClearinghouseState(BaseModel): ... # full perp account state

# Orders
class OpenOrder(BaseModel): ...          # a single open order
class OrderStatus(BaseModel): ...        # status of a specific order
class Fill(BaseModel): ...               # a completed trade

# Market data
class AssetMeta(BaseModel): ...          # one asset's metadata (name, szDecimals, etc.)
class Meta(BaseModel): ...               # full meta response — list of AssetMeta
class L2Level(BaseModel): ...            # one price level in the order book
class L2Book(BaseModel): ...             # full order book

# Exchange responses
class OrderResponse(BaseModel): ...      # response after placing an order
class CancelResponse(BaseModel): ...     # response after canceling
```

**Pattern for every model:**
```python
class PerpPosition(BaseModel):
    coin: str
    szi: str          # size — string in API, convert to Decimal when needed
    entryPx: str      # entry price — string
    unrealizedPnl: str
    leverage: dict

    class Config:
        extra = "ignore"  # ignore unknown fields — API may add new fields
```

**Why `extra = "ignore"`:** The API may return fields not in your model. Without this, Pydantic raises an error. With it, unknown fields are silently ignored — your model stays stable even if the API adds new fields.

**What it does NOT do:**
- No HTTP calls
- No signing
- No business logic
- No calculations — models just hold data, they don't compute P&L or anything

---

### `hyperliquid_symbol.py`
**Job:** One job only — **resolve symbol strings to asset IDs** and back.

**Why it exists:** The API uses integer asset IDs, not symbol strings. You cannot hardcode them — they can change. This file fetches `meta` and `spotMeta` at runtime and builds a lookup map.

**What it contains:**

`HyperliquidSymbol` class with:

| Method | What it does |
|---|---|
| `__init__(client)` | Takes a `HyperliquidClient`. Does not fetch yet. |
| `load()` | Fetches `meta` and `spotMeta`. Builds internal lookup maps. Must be called before any lookups. |
| `get_perp_asset_id(symbol)` | `"BTC"` → `0`. Raises `ValueError` if not found. |
| `get_spot_asset_id(symbol)` | `"PURR"` → `10000`. Raises `ValueError` if not found. |
| `get_symbol(asset_id)` | `0` → `"BTC"`. Reverse lookup. |
| `all_perp_symbols()` | Returns list of all tradeable perp symbols. |

**How it works internally:**
```python
# After load():
self._perp_map  = { "BTC": 0, "ETH": 1, ... }
self._spot_map  = { "PURR": 10000, ... }
self._reverse   = { 0: "BTC", 1: "ETH", 10000: "PURR", ... }
```

**Why asset IDs must never be hardcoded:**
The `meta` endpoint is the source of truth. Asset indices can change when new assets are listed or delisted. Any hardcoded `0` for BTC is a bug waiting to happen.

**Usage pattern at startup:**
```python
symbol_map = HyperliquidSymbol(client=client)
symbol_map.load()  # one HTTP call, done once at startup

btc_id = symbol_map.get_perp_asset_id("BTC")  # → 0
```

**What it does NOT do:**
- No signing
- No HTTP calls directly — delegates to `HyperliquidClient.info()`
- No Pydantic models (it uses them but doesn't define them)

---

## How All Four Files Connect

```
HyperliquidAuth          HyperliquidSymbol
      │                         │
      │ signs requests           │ resolves "BTC" → 0
      ▼                         ▼
           HyperliquidClient
           (makes HTTP calls)
                 │
                 │ raw JSON response
                 ▼
        HyperliquidResponses
        (Pydantic validates + structures)
```

**The flow for placing an order:**
1. `HyperliquidSymbol.get_perp_asset_id("BTC")` → `0`
2. Build action: `{ "type": "order", "asset": 0, ... }`
3. `HyperliquidClient.exchange(action)` → calls `HyperliquidAuth.__call__(action)` → signs it → POSTs to `/exchange`
4. Raw response → `OrderResponse(**response)` → validated Pydantic object

---

## Build Order

Build in this order — each file depends on the ones before it:

| Order | File | Why this order |
|---|---|---|
| 1 | `hyperliquid_auth.py` | No dependencies on other HL files. Pure signing logic. |
| 2 | `hyperliquid_responses.py` | Pure data models. No dependencies. Can be built in parallel with auth. |
| 3 | `hyperliquid_client.py` | Depends on auth (to sign) and responses (to validate). |
| 4 | `hyperliquid_symbol.py` | Depends on client (to fetch meta) and responses (to parse meta). |
| 5 | `__init__.py` | Wire everything together once all four are done. |

---

## Testing Plan (One Test File Per Source File)

| Source file | Test file | What to test |
|---|---|---|
| `hyperliquid_auth.py` | `test_hyperliquid_auth.py` | Sign with fake keys, verify `r/s/v` fields present, verify nonce format, test both signing schemes separately |
| `hyperliquid_responses.py` | `test_hyperliquid_responses.py` | Valid data passes, missing required fields raise `ValidationError`, extra fields are ignored |
| `hyperliquid_client.py` | `test_hyperliquid_client.py` | Mock HTTP — test info() sends no signature, test exchange() sends signature, test every error code (429, 500, etc.) |
| `hyperliquid_symbol.py` | `test_hyperliquid_symbol.py` | Mock meta response, test symbol → ID, test ID → symbol, test unknown symbol raises `ValueError` |

**Rule:** No test ever hits a real server. All HTTP is mocked with `AsyncMock` / `patch`.

---
