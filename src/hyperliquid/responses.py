from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HLBaseModel(BaseModel):
    """Base model for all Hyperliquid responses. Ignores unknown fields."""

    model_config = ConfigDict(extra="ignore")


# ──────────────────────────────────────────────────────────────
# META — perpetuals universe
# ──────────────────────────────────────────────────────────────


class AssetMeta(HLBaseModel):
    """
    One asset's metadata from the meta response.
    Used to build the symbol → asset ID map.

    Example:
        {"name": "BTC", "szDecimals": 5, "maxLeverage": 50}
    """

    name: str
    szDecimals: int
    maxLeverage: int
    onlyIsolated: bool = False
    isDelisted: bool = False


class Meta(HLBaseModel):
    """
    Full response from {"type": "meta"}.
    universe[i].name → asset ID is just i (the index).

    Example:
        universe[0].name == "BTC" → asset ID 0
        universe[1].name == "ETH" → asset ID 1
    """

    universe: list[AssetMeta]


# ──────────────────────────────────────────────────────────────
# SPOT META
# ──────────────────────────────────────────────────────────────


class SpotAssetMeta(HLBaseModel):
    """
    One spot asset's metadata from the spotMeta response.
    Spot asset ID = 10000 + index in this list.

    Example:
        {"name": "PURR/USDC", "index": 0, ...} → asset ID 10000
    """

    name: str
    index: int
    tokenId: str | None = None


class SpotMeta(HLBaseModel):
    """Full response from {"type": "spotMeta"}."""

    universe: list[SpotAssetMeta]


# ──────────────────────────────────────────────────────────────
# CLEARINGHOUSE STATE — user's perp account
# ──────────────────────────────────────────────────────────────


class MarginSummary(HLBaseModel):
    """
    Account value and margin usage summary.
    All values are strings from the API — convert to Decimal for math.

    Example:
        {"accountValue": "13109.48", "totalMarginUsed": "4.97", ...}
    """

    accountValue: str
    totalNtlPos: str
    totalRawUsd: str
    totalMarginUsed: str


class CumFunding(HLBaseModel):
    """Cumulative funding paid/received on a position."""

    allTime: str
    sinceChange: str
    sinceOpen: str


class Leverage(HLBaseModel):
    """
    Leverage info for a position.
    type is "cross" or "isolated".
    """

    type: str
    value: int
    rawUsd: str | None = None


class Position(HLBaseModel):
    """
    One open perpetual position.

    szi:            size (positive = long, negative = short)
    entryPx:        average entry price
    unrealizedPnl:  current unrealized P&L
    marginUsed:     margin allocated to this position
    liquidationPx:  price at which position gets liquidated
    """

    coin: str
    szi: str
    entryPx: str | None = None
    unrealizedPnl: str
    marginUsed: str
    liquidationPx: str | None = None
    positionValue: str
    returnOnEquity: str
    maxLeverage: int
    leverage: Leverage
    cumFunding: CumFunding


class AssetPosition(HLBaseModel):
    """Wrapper around Position with position type."""

    position: Position
    type: str  # "oneWay"


class ClearinghouseState(HLBaseModel):
    """
    Full response from {"type": "clearinghouseState", "user": "0x..."}.
    Contains all open positions and margin summary.
    """

    marginSummary: MarginSummary
    crossMarginSummary: MarginSummary
    crossMaintenanceMarginUsed: str
    withdrawable: str
    assetPositions: list[AssetPosition]
    time: int


# ──────────────────────────────────────────────────────────────
# OPEN ORDERS
# ──────────────────────────────────────────────────────────────


class OpenOrder(HLBaseModel):
    """
    One open order from {"type": "openOrders", "user": "0x..."}.

    coin:       asset symbol e.g. "BTC"
    side:       "B" (buy) or "A" (ask/sell)
    limitPx:    limit price as string
    sz:         order size as string
    oid:        order ID (integer)
    timestamp:  when the order was placed (ms)
    cloid:      client order ID if set, else None
    """

    coin: str
    side: str
    limitPx: str
    sz: str
    oid: int
    timestamp: int
    cloid: str | None = None


# ──────────────────────────────────────────────────────────────
# ORDER STATUS
# ──────────────────────────────────────────────────────────────


class OrderStatusData(HLBaseModel):
    """The order's own fields, nested inside the order-status response."""

    coin: str
    side: str
    limitPx: str
    sz: str
    oid: int
    timestamp: int
    origSz: str
    cloid: str | None = None


class OrderStatusInfo(HLBaseModel):
    """
    The inner "order" object of an orderStatus response — the order's
    own fields plus its real fill status.
    """

    order: OrderStatusData
    status: str
    statusTimestamp: int


class OrderStatus(HLBaseModel):
    """
    Response from {"type": "orderStatus", "oid": 123}.

    IMPORTANT — this response is double-nested. The TOP-LEVEL `status`
    is only "order" (the oid was found) or "unknownOid" (not found) —
    it is NEVER "filled"/"open"/etc. The real per-order fill status is
    nested one level deeper, at `.order.status`, with the order's own
    fields nested one level deeper still, at `.order.order`:

        {
          "status": "order",
          "order": {
            "order": {"coin": ..., "sz": ..., "oid": ..., ...},
            "status": "filled",   # one of: open, filled, canceled,
                                   # triggered, rejected, marginCanceled
            "statusTimestamp": ...
          }
        }

    account.get_order_status() returns the raw dict rather than parsing
    through this model (see execution/testnet_executor.py's
    _parse_order_status(), which reads this same nested shape directly)
    — this model exists so the true shape is documented accurately for
    any future caller that does want a typed response.
    """

    status: str
    order: OrderStatusInfo | None = None


# ──────────────────────────────────────────────────────────────
# FILLS (trade history)
# ──────────────────────────────────────────────────────────────


class Fill(HLBaseModel):
    """
    One completed trade from {"type": "userFills", "user": "0x..."}.

    side:   "B" (bought) or "A" (sold)
    px:     fill price
    sz:     fill size
    fee:    fee paid (negative = rebate received)
    """

    coin: str
    side: str
    px: str
    sz: str
    time: int
    startPosition: str
    dir: str
    closedPnl: str
    hash: str
    oid: int
    crossed: bool
    fee: str
    cloid: str | None = None
    feeToken: str | None = None


# ──────────────────────────────────────────────────────────────
# L2 ORDER BOOK
# ──────────────────────────────────────────────────────────────


class L2Level(HLBaseModel):
    """
    One price level in the order book.
    px:  price as string
    sz:  total size at this price level as string
    n:   number of orders at this level
    """

    px: str
    sz: str
    n: int


class L2Book(HLBaseModel):
    """
    Full order book from {"type": "l2Book", "coin": "BTC"}.
    levels[0] = bids (sorted descending by price)
    levels[1] = asks (sorted ascending by price)
    """

    coin: str
    time: int
    levels: list[list[L2Level]]


# ──────────────────────────────────────────────────────────────
# EXCHANGE RESPONSES — after placing/canceling orders
# ──────────────────────────────────────────────────────────────


class OrderResult(HLBaseModel):
    """
    Result for one order in a batch.
    resting:  the order was placed and is resting on the book
    filled:   the order matched immediately
    error:    something went wrong — check the error string
    """

    resting: dict | None = None
    filled: dict | None = None
    error: str | None = None


class ExchangeResponse(HLBaseModel):
    """
    Top-level response from POST /exchange.
    status is "ok" on success, "err" on failure.
    """

    status: str
    response: dict | None = None
