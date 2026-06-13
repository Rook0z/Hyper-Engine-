# Phase 1 Review — Hyperliquid API Client
---

## What Phase 1 Actually Is

I built a **production-grade Python client for the Hyperliquid L1 blockchain**.

Not a script. Not a tutorial project. A structured, tested, documented codebase
that any professional developer could pick up and understand.

Seven modules. One job each. 100+ tests. 98% coverage.

This is the foundation every other phase builds on.
If this breaks, everything breaks. That's why you built it carefully.

---

## The Big Picture — How All Seven Files Connect

```
Request flow for placing an order:

trading.py          ← you call place_limit_order("BTC", ...)
    │
    ├── symbol.py   ← resolves "BTC" → asset ID 0
    │
    └── client.py   ← calls exchange(action)
            │
            ├── auth.py     ← signs the action → {r, s, v}
            │
            └── HTTP POST /exchange
                    │
                    └── responses.py  ← validates the response with Pydantic
```

Every file has one job. None of them bleed into each other.
That's the entire architecture in one diagram.

---

## File 1 — `auth.py`

### What it does
Signs every request you send to Hyperliquid.

### Why signing exists
Hyperliquid is a blockchain. There is no login system, no sessions, no API keys
the way Binance or Bitget work. Your identity IS your Ethereum wallet address.
When you want to place an order, you prove it's you by signing the request
with your wallet's private key. The blockchain can then verify the signature
and confirm the request came from you — without you ever sending your private key.

### How signing works — step by step

**For trading actions (orders, cancels):**
```
1. You have an action dict:  {"type": "order", "asset": 0, ...}
2. msgpack.packb(action)     → compress to bytes (field order matters here)
3. append nonce as 8 bytes   → ties this signature to this specific moment
4. append vault flag         → 0x00 if no vault, 0x01 + address if vault
5. keccak256(all of that)    → produces a 32-byte hash
6. wrap in phantom agent     → {"source": "a"/"b", "connectionId": <hash>}
7. wrap in EIP-712 envelope  → standard Ethereum signing structure
8. wallet.sign_message()     → produces {r, s, v}
```

The output `{r, s, v}` is the signature. Three numbers that mathematically
prove the request was signed by the owner of your private key.

**For user actions (withdraw, transfer, approveAgent):**
These skip steps 2-6. The action itself IS the message. It gets signed
directly with EIP-712 using the Hyperliquid chain ID.

### Why two signing schemes
Trading happens on HyperCore (the order book engine).
User operations like withdrawals happen at the account level.
They have different security models so they have different signing schemes.
Mixing them up is the most common bug when integrating Hyperliquid.

### What EIP-712 is
A standard for signing structured data in Ethereum.
Instead of signing raw bytes (which is dangerous — you could accidentally
sign anything), EIP-712 makes you sign typed data with a defined structure.
The structure is defined in the `domain` and `types` fields of the payload.

### Why msgpack field order matters
When you serialize the action to bytes, the same dict with different field
ordering produces different bytes, which produces a different hash,
which produces a different signature. Hyperliquid's servers serialize
in a specific order. Your serialization must match exactly or the API
rejects the request with a signature mismatch error.

### What the nonce is for
Replay attack prevention. If someone intercepts your signed order request,
they could broadcast it again later. The nonce (millisecond timestamp)
prevents this — each nonce can only be used once per signer address.
Hyperliquid stores the top 100 nonces per signer.

### Mainnet vs testnet
The phantom agent uses `source: "a"` for mainnet and `source: "b"` for testnet.
This means a testnet signature is mathematically different from a mainnet one.
You cannot accidentally broadcast testnet orders on mainnet.

---

## File 2 — `client.py`

### What it does
Makes HTTP requests to two endpoints: `/info` and `/exchange`.
That's the entire job.

### Why two endpoints
`/info` — read only. Get prices, positions, orders, fills. No signature needed.
`/exchange` — write only. Place orders, cancel, set leverage. Must be signed.

This maps directly to how blockchains work: reading state is free and open,
changing state requires proof of identity.

### How a request flows through client.py
```
client.exchange(action)
    → auth(action)              ← signs it, returns {action, nonce, signature}
    → _post_with_retry("/exchange", signed_body)
        → _post("/exchange", signed_body)
            → httpx.post(url, json=body)
                → _handle_response(response)
                    → return parsed JSON  OR  raise typed error
```

### The three error types and why they exist

`APIError` — HTTP 4xx. The request was bad. Wrong price format, order too small,
invalid asset. Retrying won't help — the request is broken. Raise immediately.

`RateLimitError` — HTTP 429. You're sending too many requests. Retrying after
a delay will work. Subclass of APIError because it's still a 4xx.

`NetworkError` — HTTP 5xx or connection failure. The server had a problem or
the network dropped. This is temporary. Worth retrying.

### Exponential backoff
When a retryable error happens, you don't retry immediately. You wait.
And each retry you wait longer:

```
Attempt 1 fails → wait 1s
Attempt 2 fails → wait 2s
Attempt 3 fails → wait 4s
Attempt 4 fails → give up, raise the error
```

The delay doubles each time: `min(base_delay * 2^attempt, max_delay)`

Why exponential instead of fixed? If 100 clients all hit a rate limit at the
same time and all retry after exactly 1 second, they all hit the server again
at the same time. Exponential backoff spreads them out naturally.

### Why `_post` and `_post_with_retry` are separate
Single responsibility. `_post` makes one HTTP call and returns or raises.
`_post_with_retry` handles the retry loop. They don't mix.
This also makes testing easier — you can test each in isolation.

---

## File 3 — `responses.py`

### What it does
Defines the shape of every API response as a Pydantic model.

### Why not just use raw dicts
The API returns JSON. You could access it like `response["marginSummary"]["accountValue"]`.
But that's fragile:
- Typo in a key? Silent `KeyError` at runtime.
- API returns unexpected type? Silent bug.
- No autocomplete in your editor.
- No documentation of what fields exist.

With Pydantic:
- Wrong type? `ValidationError` immediately at the boundary.
- Missing required field? `ValidationError` immediately.
- Full autocomplete in your editor.
- The model IS the documentation.

### Why `extra = "ignore"`
Hyperliquid is a live, actively developed blockchain. They add new fields to
API responses regularly. If your model raises on unknown fields, your bot
crashes every time they add something new. `extra = "ignore"` means unknown
fields are silently discarded. Your model stays stable.

### Why prices are strings not floats
Float precision. `50000.1` in IEEE 754 floating point is actually
`50000.099999999999999996...`. For financial data this matters.
The API sends prices as strings. You keep them as strings in the model.
When you need to do math, convert to `Decimal` at that point.
Never convert to `float`.

---

## File 4 — `symbol.py`

### What it does
Maps human-readable symbol strings to integer asset IDs and back.

### Why asset IDs exist
Hyperliquid's order book engine identifies assets by integer index, not string.
BTC is 0, ETH is 1, SOL is 2, etc. for perpetuals.
Spot assets are 10000 + their index.

### Why you can't hardcode them
The indices come from the position in the `meta.universe` array. New assets
get listed, old assets get delisted. The indices can shift. If you hardcode
`BTC = 0` and Hyperliquid reorders their universe, your orders go to the
wrong asset. `symbol.py` fetches the live mapping at startup.

### The `load()` pattern
`HyperliquidSymbol` doesn't fetch anything when you create it.
You must call `load()` explicitly. This is intentional:
- You control exactly when the network call happens
- Tests can create the object without triggering HTTP calls
- You can reload if you suspect the universe changed

After `load()`, all lookups are instant — they hit an in-memory dict.

---

## File 5 — `market.py`

### What it does
Public market data. No auth required. Gets prices, order books, recent trades,
funding rates.

### Why `get_market_order` uses IOC not a real market order
Hyperliquid has no "market order" type. You simulate it with an IOC (Immediate
Or Cancel) limit order priced far enough from the market that it always fills:
- Buy: set price 5% above current mid → will always cross the spread
- Sell: set price 5% below current mid → will always cross the spread

The unfilled portion cancels automatically (that's what IOC means).

### Why `get_price()` fetches all mids
The `allMids` endpoint returns prices for every asset in one call.
Fetching a single price would require a separate endpoint that costs more
weight on the rate limiter. `allMids` is weight 2 regardless of how many
assets exist. So fetching all and filtering is more efficient than
fetching one repeatedly.

---

## File 6 — `account.py`

### What it does
Reads account state — balances, positions, open orders, fills, funding history.
All read-only. Uses `/info` (no signing).

### The most important rule in this file
Always use the **master account address**, never the API wallet address.
If you query with the API wallet address, the API returns empty results.
No error. Just empty. This is a silent bug that wastes hours.

The master account address owns the positions and balance.
The API wallet is just a signing proxy with no positions of its own.

### `get_positions()` vs `get_balances()`
`get_balances()` returns the full `ClearinghouseState` — everything including
margin summary, withdrawable amount, cross margin data.

`get_positions()` is a convenience wrapper. It calls `get_balances()` internally
and returns just the positions list, filtered to non-zero sizes. It exists so
you don't have to dig into `state.assetPositions[i].position` everywhere.

### Why `get_fills()` has `start_time`
The API returns maximum 500 fills per call. If you have more than 500 fills
(which you will after running for a while), you paginate:
- First call: no `start_time` → get newest 500
- Next call: `start_time` = timestamp of the last fill returned → get next 500
- Repeat until you get fewer than 500 results

---

## File 7 — `trading.py`

### What it does
Places orders, cancels orders, modifies orders, sets leverage.
All write operations. All signed via `client.exchange()`.

### The order action structure
Every order sent to Hyperliquid has this shape:
```python
{
    "type": "order",
    "orders": [{
        "a": 0,           # asset ID (from symbol.py)
        "b": True,        # is_buy
        "p": "50000.0",   # price (string)
        "s": "0.001",     # size (string)
        "r": False,       # reduce_only
        "t": {"limit": {"tif": "Gtc"}}  # order type
    }],
    "grouping": "na"      # how to group fills (na = no grouping)
}
```

The short field names (`a`, `b`, `p`, `s`, `r`, `t`) are Hyperliquid's
internal format. They're deliberately terse to minimize payload size.

### The three TIF (Time In Force) types
`Gtc` — Good Till Canceled. Order rests on the book until filled or canceled.
This is the default for limit orders.

`Ioc` — Immediate Or Cancel. Fill what you can right now, cancel the rest.
Used for market order simulation and aggressive limit orders.

`Alo` — Add Liquidity Only (Post Only). If the order would match immediately,
cancel it instead of filling. Used by market makers who only want to add
liquidity and earn maker rebates, never pay taker fees.

### Why `cancel_all_orders()` makes multiple round trips
It has to:
1. First call `/info` to get the list of open orders (read)
2. Then call `/exchange` to cancel them (write)

There's no "cancel everything" atomic operation in the API.
The method groups cancels by asset to minimize the number of exchange calls.

### `reduce_only`
When `reduce_only=True`, the order can only reduce an existing position.
It cannot open or increase a position. If you have no position, the order
gets rejected. Used for stop losses and take profits to prevent accidentally
flipping from long to short.

### `set_leverage()`
Uses `updateLeverage` action with `isCross` (cross margin vs isolated margin).
Cross margin shares the account balance across all positions.
Isolated margin allocates a fixed amount to each position.
Isolated is safer — a liquidation on one position doesn't affect others.

---

### What mocking is for
 tests never hit a real server. Instead, `unittest.mock.patch` replaces
`httpx.post` with a fake that returns whatever response you configure.

Why:
- Tests run in milliseconds, not seconds
- Tests work offline
- Tests work on testnet and mainnet environments equally
- You can control exactly what the "API" returns — including errors

### `conftest.py`
Pytest loads this file automatically before any test runs.
Fixtures defined here are available in every test file without importing.
It's the shared setup for the entire test suite.

---

