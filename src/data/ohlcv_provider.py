from __future__ import annotations

import logging
import math
import time as _time
from typing import Any

logger = logging.getLogger(__name__)

# Candle interval → milliseconds per candle
INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}

VALID_INTERVALS = set(INTERVAL_MS.keys())

# Hyperliquid returns max 5000 candles per call
MAX_CANDLES_PER_CALL = 5000

# Type alias — one OHLCV row
OHLCVRow = list


class OHLCVProvider:
    """
    Fetches and stores OHLCV candlestick data from Hyperliquid.

    Output format for every candle:
        [timestamp, open, high, low, close, volume]
        [int(ms),   float, float, float, float, float]

    Args:
        client: HyperliquidClient instance (no auth needed — /info is public)

    Usage:
        provider = OHLCVProvider(client=client)

        # Fetch last 100 hourly BTC candles
        candles = provider.fetch("BTC", interval="1h", limit=100)

        # Fetch candles in a specific date range
        candles = provider.fetch_range(
            "BTC",
            interval="1h",
            start_time=1700000000000,
            end_time=1700100000000,
        )

        # Access individual fields
        for candle in candles:
            timestamp, open_, high, low, close, volume = candle
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    # ──────────────────────────────────────────────────────────────
    # PUBLIC METHODS
    # ──────────────────────────────────────────────────────────────

    def fetch(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100,
        end_time: int | None = None,
    ) -> list[OHLCVRow]:
        """
        Fetches the most recent `limit` candles for a symbol.

        Args:
            symbol:   Asset symbol e.g. "BTC", "ETH", "SOL"
            interval: Candle interval. One of:
                      "1m", "3m", "5m", "15m", "30m",
                      "1h", "2h", "4h", "8h", "12h",
                      "1d", "3d", "1w"
            limit:    Number of candles to return (default 100, max 5000)
            end_time: End timestamp in ms. Defaults to now.

        Returns:
            List of OHLCV rows: [[timestamp, open, high, low, close, volume], ...]
            Sorted oldest → newest.

        Raises:
            ValueError: if interval is invalid or limit < 1
        """
        self._validate_interval(interval)
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit}")
        if limit > MAX_CANDLES_PER_CALL:
            raise ValueError(
                f"limit cannot exceed {MAX_CANDLES_PER_CALL} per call. "
                f"Use fetch_range() for larger requests."
            )

        if end_time is None:
            end_time = int(_time.time() * 1000)

        ms_per_candle = INTERVAL_MS[interval]
        start_time = end_time - (limit * ms_per_candle)

        candles = self._fetch_one(symbol, interval, start_time, end_time)

        # Return exactly `limit` candles (API may return slightly more)
        return candles[-limit:] if len(candles) > limit else candles

    def fetch_range(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> list[OHLCVRow]:
        """
        Fetches all candles in a time range, paginating if necessary.

        Hyperliquid returns max 5000 candles per call. If the range
        contains more than 5000 candles, this method paginates
        automatically by making multiple calls.

        Args:
            symbol:     Asset symbol e.g. "BTC"
            interval:   Candle interval e.g. "1h"
            start_time: Start timestamp in milliseconds (inclusive)
            end_time:   End timestamp in milliseconds (inclusive)

        Returns:
            List of OHLCV rows sorted oldest → newest.
            May be empty if no data in range.

        Raises:
            ValueError: if interval is invalid or start_time >= end_time
        """
        self._validate_interval(interval)
        if start_time >= end_time:
            raise ValueError(
                f"start_time must be before end_time. "
                f"Got start={start_time}, end={end_time}"
            )

        ms_per_candle = INTERVAL_MS[interval]
        max_range_ms = MAX_CANDLES_PER_CALL * ms_per_candle

        all_candles: list[OHLCVRow] = []
        current_start = start_time

        while current_start < end_time:
            current_end = min(current_start + max_range_ms, end_time)

            logger.debug(
                "Fetching %s %s: %d → %d", symbol, interval, current_start, current_end
            )

            batch = self._fetch_one(symbol, interval, current_start, current_end)

            if not batch:
                break

            all_candles.extend(batch)

            # Move start to after the last candle we received
            last_timestamp = batch[-1][0]
            current_start = last_timestamp + ms_per_candle

            # Safety: if API returned nothing new, stop
            if current_start >= end_time:
                break

        # Deduplicate by timestamp (in case of overlap)
        seen: set[int] = set()
        unique: list[OHLCVRow] = []
        for candle in all_candles:
            ts = candle[0]
            if ts not in seen:
                seen.add(ts)
                unique.append(candle)

        logger.info(
            "Fetched %d %s candles for %s (%d → %d)",
            len(unique),
            interval,
            symbol,
            start_time,
            end_time,
        )
        return unique

    def get_close_prices(self, candles: list[OHLCVRow]) -> list[float]:
        """
        Extracts close prices from a list of OHLCV rows.

        Args:
            candles: output from fetch() or fetch_range()

        Returns:
            List of close prices as floats, oldest first.
        """
        return [candle[4] for candle in candles]

    def get_volumes(self, candles: list[OHLCVRow]) -> list[float]:
        """Extracts volume from a list of OHLCV rows."""
        return [candle[5] for candle in candles]

    def get_timestamps(self, candles: list[OHLCVRow]) -> list[int]:
        """Extracts timestamps (ms) from a list of OHLCV rows."""
        return [candle[0] for candle in candles]

    def latest_close(self, symbol: str, interval: str = "1h") -> float:
        """
        Returns the most recent close price for a symbol.

        Convenience method — fetches 1 candle and returns its close.

        Args:
            symbol:   e.g. "BTC"
            interval: candle interval

        Returns:
            Latest close price as float.
        """
        candles = self.fetch(symbol, interval=interval, limit=1)
        if not candles:
            raise ValueError(f"No candles returned for {symbol} {interval}")
        return candles[-1][4]

    # ──────────────────────────────────────────────────────────────
    # PRIVATE METHODS
    # ──────────────────────────────────────────────────────────────

    def _fetch_one(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> list[OHLCVRow]:
        """
        Single API call to candleSnapshot.
        Converts raw candle dicts to [timestamp, o, h, l, c, v] format.

        Individual malformed candles (missing/non-numeric/non-finite
        fields) are skipped and logged rather than crashing the whole
        batch — one bad row from the API should never take down an
        otherwise-good response. Duplicate timestamps within a single
        response are also removed (keeping the first occurrence),
        defensively — fetch_range() already deduplicates across
        paginated batches, but fetch() (a single call) previously had
        no such guard at all.
        """
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": start_time,
                "endTime": end_time,
            },
        }

        raw: list[dict] = self._client.info(payload)

        if not raw:
            return []

        candles: list[OHLCVRow] = []
        skipped = 0
        for c in raw:
            try:
                candles.append(self._parse_candle(c))
            except (KeyError, TypeError, ValueError) as e:
                skipped += 1
                logger.warning("Skipping malformed candle from API: %r (%s)", c, e)
        if skipped:
            logger.warning(
                "Skipped %d malformed candle(s) out of %d received for %s %s",
                skipped,
                len(raw),
                symbol,
                interval,
            )

        # Always sort by timestamp — defensive against out-of-order responses
        candles.sort(key=lambda c: c[0])

        # Deduplicate by timestamp (keep first occurrence) — defensive
        # against the API returning the same candle twice in one response.
        seen: set[int] = set()
        deduped: list[OHLCVRow] = []
        duplicates = 0
        for candle in candles:
            ts = candle[0]
            if ts in seen:
                duplicates += 1
                continue
            seen.add(ts)
            deduped.append(candle)
        if duplicates:
            logger.warning(
                "Removed %d duplicate-timestamp candle(s) within one %s %s "
                "API response",
                duplicates,
                symbol,
                interval,
            )

        return deduped

    def _parse_candle(self, raw: dict) -> OHLCVRow:
        """
        Converts a raw API candle dict to [timestamp, o, h, l, c, v].

        Raw fields:
            t = open time ms (int)
            o = open (string)
            h = high (string)
            l = low (string)
            c = close (string)
            v = volume (string)

        Returns:
            [timestamp(int), open(float), high(float), low(float),
             close(float), volume(float)]

        Raises:
            KeyError:   if a required field is missing.
            TypeError:  if a field's value can't be converted at all
                        (e.g. None).
            ValueError: if a field can't be parsed as a number, or
                        parses to a non-finite value (NaN/Infinity) —
                        callers (_fetch_one) treat all three as "skip
                        this malformed candle", not a hard failure for
                        the whole batch.
        """
        timestamp = int(raw["t"])
        open_ = float(raw["o"])
        high = float(raw["h"])
        low = float(raw["l"])
        close = float(raw["c"])
        volume = float(raw["v"])

        for name, value in (
            ("open", open_),
            ("high", high),
            ("low", low),
            ("close", close),
            ("volume", volume),
        ):
            if not math.isfinite(value):
                raise ValueError(f"non-finite {name} value: {value!r}")

        return [timestamp, open_, high, low, close, volume]

    def _validate_interval(self, interval: str) -> None:
        """Raises ValueError if interval is not a valid Hyperliquid interval."""
        if interval not in VALID_INTERVALS:
            raise ValueError(
                f"Invalid interval '{interval}'. "
                f"Must be one of: {sorted(VALID_INTERVALS)}"
            )
