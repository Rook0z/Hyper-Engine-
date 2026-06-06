# Hyperliquid API Notes
> **Hyper-Engine — Day 1, Phase 1**
> Source: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api

---

## What Is Hyperliquid?

Hyperliquid is a Layer 1 blockchain built from scratch, optimized for high-performance trading.
It uses a custom consensus algorithm called **HyperBFT** (inspired by Hotstuff).

**Hyperliquid itself is the L1.** The whole thing is one single blockchain — not a layer on top of anything else.

Within that L1, state execution is split into two components:

**HyperBFT — the consensus algorithm**
Not a layer you interact with. It's the engine underneath everything. Inspired by HotStuff. Both the algorithm and the networking stack are optimized from scratch for the demands of this specific chain. It's what gives both components their one-block finality.

**HyperCore — trading component**
Handles fully on-chain perpetual futures and spot order books. Every order, cancel, trade, and liquidation happens transparently with one-block finality inherited from HyperBFT. Currently supports 200k orders/second.

**HyperEVM — smart contract component**
Brings the general-purpose Ethereum-compatible smart contract platform to the Hyperliquid chain. The key point from the docs: HyperEVM can access HyperCore's liquidity and financial primitives as permissionless building blocks. They share the same chain — they're not isolated from each other.

The correct mental model:
```
Hyperliquid L1
├── consensus:   HyperBFT  (the engine — one-block finality)
├── component 1: HyperCore (perps + spot order books)
└── component 2: HyperEVM  (smart contracts, accesses HyperCore primitives)
```

> **What this means for your work:** You are only touching **HyperCore** via the REST API — the `/info` and `/exchange` endpoints. HyperEVM (smart contracts, Solidity) is completely out of scope for this entire phase.

---

## Base URLs

| Network  | REST                                    | WebSocket                                  |
|----------|-----------------------------------------|--------------------------------------------|
| Mainnet  | `https://api.hyperliquid.xyz`           | `wss://api.hyperliquid.xyz/ws`             |
| Testnet  | `https://api.hyperliquid-testnet.xyz`   | `wss://api.hyperliquid-testnet.xyz/ws`     |

> **Rule:** Always develop and test against testnet first. Never touch mainnet with untested code.

---

## API Structure — Three Areas

### 1. Info Endpoint — `POST /info`
- Used to **read** data: market info, user positions, open orders, fills, funding history, etc.
- **No signature required** — publicly accessible.
- All requests are `POST` with a JSON body containing a `type` field that identifies what you want.
- Works for both Perpetuals and Spot.
- Responses that take a time range only return 500 elements. For larger ranges, paginate by using the last returned timestamp as the next `startTime`.

Example request body:
```json
{ "type": "clearinghouseState", "user": "0x1234...abcd" }
```

Key info endpoints:
| Type string | What it returns |
|---|---|
| `meta` | Universe of perp assets and their indices |
| `spotMeta` | Universe of spot assets |
| `clearinghouseState` | User's perp positions, balances, margin |
| `spotClearinghouseState` | User's spot balances |
| `openOrders` | User's open orders |
| `userFills` | User's trade history |
| `orderStatus` | Status of a specific order by OID or CLOID |
| `l2Book` | Order book for a given coin |
| `allMids` | Mid prices for all assets |
| `fundingHistory` | Historical funding rates |

> **Note:** To look up data for a master account, pass the master account address — not the API wallet address. Using the API wallet address leads to an empty result (common pitfall).

---

### 2. Exchange Endpoint — `POST /exchange`
- Used to **write**: place orders, cancel orders, transfer funds, withdraw, approve API wallets.
- **All requests must be signed** with a wallet private key.
- The request body always has this structure:
```json
{
  "action": { ... },
  "nonce": 1698693262000,
  "signature": { "r": "0x...", "s": "0x...", "v": 27 }
}
```

Key exchange actions:
| `type` field | What it does |
|---|---|
| `order` | Place one or more orders |
| `cancel` | Cancel one or more orders by OID |
| `cancelByCloid` | Cancel orders by client order ID |
| `approveAgent` | Register an API wallet (agent wallet) |
| `withdraw3` | Initiate a USDC withdrawal |
| `usdClassTransfer` | Transfer USDC between perp and spot |

**Asset IDs:**
- Perpetuals: use the index from `meta` universe array (e.g. BTC = 0, ETH = 1, etc.)
- Spot: use `10000 + index` where index comes from `spotMeta.universe`
  - Example: PURR/USDC has spot index 0, so use asset `10000`

**Order fields — Time In Force (TIF):**
- `GTC` — Good Till Canceled (default, rests on book)
- `ALO` — Add Liquidity Only / Post Only (cancels instead of matching immediately)
- `IOC` — Immediate Or Cancel (unfilled portion is canceled)

**Client Order ID (cloid):** Optional 128-bit hex string you assign to track your own orders. Example: `0x1234567890abcdef1234567890abcdef`

**`expiresAfter` field:** Optional timestamp (ms). Action is rejected if it arrives after this time. Note: actions that expire due to stale `expiresAfter` consume 5x the normal address-based rate limit.

> **Important:** Subaccounts and vaults do not have private keys. You sign on their behalf using an approved API wallet.

---

### 3. WebSocket — `wss://api.hyperliquid.xyz/ws`
- Used for **real-time streaming** data: order book updates, trades, user fills, positions.
- Also supports sending signed actions (same as exchange endpoint but over WebSocket).

Subscribe format:
```json
{ "method": "subscribe", "subscription": { ... } }
```

Subscription snapshots: when you first subscribe to a time-series feed, you receive a snapshot of historical data tagged `isSnapshot: true`. You can ignore these if you already have the data.

WebSocket post requests wrap the normal HTTP payload:
```json
{ "method": "post", "id": 1, "request": { ... } }
```

---

## Authentication Deep Dive

### How It Works
Hyperliquid does **NOT** use API key + secret like centralised exchanges.
Instead: your **Ethereum wallet address IS your identity**. You sign requests with the wallet's private key.

There are **two signing schemes**:

| Scheme | SDK method | Used for |
|---|---|---|
| L1 Action signing | `sign_l1_action` | All trading actions (order, cancel, etc.) |
| User-signed action | `sign_user_signed_action` | User-facing actions (transfers, withdrawals, approving agents) |

> **Critical:** These are two different code paths. Mixing them up is one of the most common bugs. Know which one each action requires before writing any signing code.

### EIP-712 Structured Data Signing
All signatures use the **EIP-712** standard (Ethereum typed structured data).

The output signature has three fields:
```json
{ "r": "0x...", "s": "0x...", "v": 27 }
```

### L1 Action Signing — Phantom Agent
L1 actions (trading) use a **phantom agent construction**:
1. The action payload is serialized using **msgpack** (field order matters — wrong order = wrong hash)
2. A hash is computed from the serialized action
3. This hash becomes the "phantom agent" — a temporary signing identity
4. The phantom agent is signed via EIP-712 with chain ID `1337`

### User-Signed Actions
Actions like transfers and withdrawals are signed directly via EIP-712 using the `signatureChainId` field (e.g. `"0xa4b1"` for Arbitrum, or `"0x66eee"` for Hyperliquid EVM).

### Common Signing Bugs (from official docs)
1. **Two signing schemes** — using `sign_l1_action` when you should use `sign_user_signed_action` or vice versa
2. **msgpack field order** — fields must be in the exact right order when serializing for L1 actions
3. **Trailing zeroes on numbers** — e.g. `1.0` vs `1` can produce a different hash
4. **Address capitalisation** — always **lowercase** all addresses before signing. Some fields are parsed as bytes and auto-lowercased, others are not.
5. **Local recover signer succeeds but API rejects** — the payload used for local recovery is constructed from the action and may not match exactly what the API expects

> **Debugging tip:** If you get `"L1 error: User or API Wallet 0x... does not exist"` or a mismatched address, your signature is wrong. Add logging to compare each step against the Python SDK output.

---

## Nonces

### Why Nonces Exist
A decentralised exchange must prevent **replay attacks** — someone intercepting a signed transaction and broadcasting it multiple times. Nonces solve this.

### How Hyperliquid Nonces Work
- Nonce = **current timestamp in milliseconds** (recommended)
- The 100 highest nonces are stored per signer address
- Each new action's nonce must be **within the top 100** of the stored nonces — not necessarily strictly sequential, but it must not reuse a nonce that's already been consumed
- Nonces are stored **per signer** (i.e. per private key used to sign), not per account address

### Practical Rules
- Use `int(time.time() * 1000)` for nonces — millisecond timestamp
- The nonce in the outer request body **must match** the nonce inside the action object (for actions that include it, like withdrawals)
- Each trading process or frontend session should use a **separate private key** — because nonces are per signer, parallel processes using the same key will conflict

---

## API Wallets (Agent Wallets)

### What They Are
API wallets are separate Ethereum keypairs that are **approved to sign on behalf of your master account**.

### Why Use Them (Security)
- API wallets **cannot withdraw funds** — they can only trade
- Your master wallet key stays offline/cold
- If an API wallet key is compromised, the attacker cannot drain your account
- This is the correct setup for any automated trading bot

### Setup Flow
1. Generate a new Ethereum keypair (this becomes your API wallet)
2. Send an `approveAgent` action signed by your **master wallet** to register it
3. Use the API wallet's private key in your bot's `.env`
4. Pass the **master account address** (not API wallet address) when querying account data

### Capacity
- 1 unnamed API wallet per master account
- Up to 3 named API wallets per master account
- Up to 2 named agents per subaccount

### When API Wallets Are Pruned
- The wallet is deregistered
- An unnamed API wallet is replaced when a new `approveAgent` action is sent for an unnamed wallet

---

## Rate Limits

### IP-Based Limits (per IP address)

| Limit | Value |
|---|---|
| REST weight per minute | **1200** |
| Max WebSocket connections | 10 |
| New WebSocket connections per minute | 30 |
| WebSocket subscriptions | 1000 |
| Unique users across user WebSocket subs | 10 |
| Messages sent to HL per minute (all WS) | 2000 |
| Inflight post messages (all WS) | 100 |

**Request weights:**
- Exchange actions (unbatched): weight **1**
- Exchange actions (batched): weight `1 + floor(batch_length / 40)`
  - e.g. 79 orders in a batch = weight 2
- Info `l2Book`, `allMids`, `clearinghouseState`, `orderStatus`, `spotClearinghouseState`, `exchangeStatus`: weight **2**
- Info `userRole`: weight **60**
- All other info requests: weight **20**
- Some endpoints add extra weight per 20 items returned (e.g. `userFills`, `fundingHistory`, `historicalOrders`)
- Explorer requests: weight **40**

### Address-Based Limits (per wallet address)
- Starting buffer: **10,000 requests**
- Ongoing: **1 request per 1 USDC traded** cumulatively since account creation
  - Example: 100 USDC order value requires 1% fill rate to earn 1 request
- When rate limited: **1 request every 10 seconds**
- Cancels get extra headroom: `min(limit + 100_000, limit * 2)` — so you can always cancel open orders even when rate limited
- Address-based limits apply to **actions only** — not info requests

### Open Order Limits
- Default: **1000 open orders** per user
- Scales: +1 per 5M USDC of volume, capped at **5000**
- At 1000+ open orders: reduce-only and trigger orders are rejected

### Batching Note
A batched request with `n` orders counts as **1 request** for IP rate limiting but **n requests** for address-based rate limiting.

---

## Error Responses

### Order/Cancel Errors (batched)
Returned as a vector with the same length as the batch.

| Error | Meaning |
|---|---|
| `Tick` | Price not divisible by tick size |
| `MinTradeNtl` | Order below $10 minimum value |
| `PerpMargin` | Not enough margin |
| `ReduceOnly` | Reduce-only order would increase position |
| `BadAloPx` | Post-only order would have matched immediately |
| `IocCancel` | IOC order found no resting liquidity |
| `BadTriggerPx` | Invalid TP/SL price |
| `MarketOrderNoLiquidity` | No liquidity for market order |
| `Oracle` | Order price too far from oracle |
| `PerpMaxPosition` | Position would exceed margin tier limit at current leverage |
| `InsufficientSpotBalance` | Not enough spot balance (spot only) |
| `MissingOrder` (cancel) | Order was never placed, already filled, or already canceled |

### Pre-Validation Errors (single error for whole batch)
Some errors are returned as a single error for the whole batch before individual order processing:
- Empty batch of orders
- Non reduce-only TP/SL orders
- Order too far from reference price
- Some tick size violations

> **Implementation note:** Always handle the case where a single error is returned for a multi-order batch. When this happens, duplicate the error `n` times before passing to your callback, since the whole batch was rejected for the same reason.

---

## Asset IDs — How They Work

- **Perpetuals:** integer index in the `universe` array from `meta` response
  - BTC = 0, ETH = 1, etc.
- **Spot:** `10000 + index` where index comes from `spotMeta.universe`
  - PURR/USDC (spot index 0) → asset ID = `10000`

> Always fetch `meta` and `spotMeta` at startup and build a symbol-to-asset-ID map. Never hardcode asset IDs.

---

## Official SDKs

| Language | Repo | Maintainer |
|---|---|---|
| Python | https://github.com/hyperliquid-dex/hyperliquid-python-sdk | Official |
| Rust | https://github.com/infinitefield/hypersdk | Community |
| TypeScript | https://github.com/nktkas/hyperliquid | Community |
| TypeScript | https://github.com/nomeida/hyperliquid | Community |

---

## Key Gotchas — Things That Will Bite You

1. **Never query account data with the API wallet address** — always use the master account address
2. **Lowercase all addresses before signing** — capitalisation changes the signature
3. **msgpack field order matters for L1 actions** — wrong order = wrong hash = wrong signature
4. **The nonce in the outer body must match the nonce inside the action** (for applicable actions)
5. **Two signing schemes exist** — `sign_l1_action` and `sign_user_signed_action` — know which one each action needs
6. **Always fetch `meta` at runtime** — never hardcode asset indices
7. **Paginate time-range queries** — max 500 elements per response
8. **Testnet first, always** — testnet URL: `https://api.hyperliquid-testnet.xyz`

---
