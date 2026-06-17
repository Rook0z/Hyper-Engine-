from unittest.mock import MagicMock
import pytest
from data.ohlcv_provider import OHLCVProvider, INTERVAL_MS

# ──────────────────────────────────────────────────────────────
# SAMPLE DATA
# ──────────────────────────────────────────────────────────────


def make_raw_candle(t: int, o="50000", h="51000", low="49000", c="50500", v="10.5"):
    return {
        "t": t,
        "T": t + 3600000,
        "o": o,
        "h": h,
        "l": low,
        "c": c,
        "v": v,
        "n": 100,
        "s": "BTC",
    }


RAW_CANDLES = [
    make_raw_candle(
        1000000000000, o="50000", h="51000", low="49000", c="50500", v="10.5"
    ),
    make_raw_candle(
        1000003600000, o="50500", h="52000", low="50000", c="51000", v="8.2"
    ),
    make_raw_candle(
        1000007200000, o="51000", h="53000", low="50500", c="52000", v="12.0"
    ),
]


# ──────────────────────────────────────────────────────────────
# FIXTURES
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.info.return_value = RAW_CANDLES
    return client


@pytest.fixture
def provider(mock_client):
    return OHLCVProvider(client=mock_client)


# ──────────────────────────────────────────────────────────────
# PARSE CANDLE
# ──────────────────────────────────────────────────────────────


def test_parse_candle_returns_correct_format(provider):
    raw = make_raw_candle(
        1000000000000, o="50000", h="51000", low="49000", c="50500", v="10.5"
    )
    result = provider._parse_candle(raw)
    assert result == [1000000000000, 50000.0, 51000.0, 49000.0, 50500.0, 10.5]


def test_parse_candle_types(provider):
    raw = make_raw_candle(1000000000000)
    result = provider._parse_candle(raw)
    assert isinstance(result[0], int)  # timestamp
    assert isinstance(result[1], float)  # open
    assert isinstance(result[2], float)  # high
    assert isinstance(result[3], float)  # low
    assert isinstance(result[4], float)  # close
    assert isinstance(result[5], float)  # volume


def test_parse_candle_uses_close_not_open(provider):
    raw = make_raw_candle(1000000000000, o="40000", c="50000")
    result = provider._parse_candle(raw)
    assert result[1] == 40000.0  # open
    assert result[4] == 50000.0  # close


# ──────────────────────────────────────────────────────────────
# VALIDATE INTERVAL
# ──────────────────────────────────────────────────────────────


def test_valid_intervals_pass(provider):
    for interval in INTERVAL_MS.keys():
        provider._validate_interval(interval)  # should not raise


def test_invalid_interval_raises(provider):
    with pytest.raises(ValueError, match="Invalid interval"):
        provider._validate_interval("2d")


def test_invalid_interval_message_shows_valid_options(provider):
    with pytest.raises(ValueError, match="Must be one of"):
        provider._validate_interval("10m")


# ──────────────────────────────────────────────────────────────
# FETCH
# ──────────────────────────────────────────────────────────────


def test_fetch_returns_list_of_rows(provider):
    candles = provider.fetch("BTC", interval="1h", limit=3)
    assert isinstance(candles, list)
    assert len(candles) == 3


def test_fetch_each_row_has_six_elements(provider):
    candles = provider.fetch("BTC", interval="1h", limit=3)
    for candle in candles:
        assert len(candle) == 6


def test_fetch_uses_correct_payload(provider, mock_client):
    provider.fetch("ETH", interval="4h", limit=10)
    payload = mock_client.info.call_args[0][0]
    assert payload["type"] == "candleSnapshot"
    assert payload["req"]["coin"] == "ETH"
    assert payload["req"]["interval"] == "4h"


def test_fetch_invalid_interval_raises(provider):
    with pytest.raises(ValueError, match="Invalid interval"):
        provider.fetch("BTC", interval="2d")


def test_fetch_limit_zero_raises(provider):
    with pytest.raises(ValueError, match="limit must be >= 1"):
        provider.fetch("BTC", limit=0)


def test_fetch_limit_too_large_raises(provider):
    with pytest.raises(ValueError, match="5000"):
        provider.fetch("BTC", limit=5001)


def test_fetch_sorted_oldest_first(provider, mock_client):
    # Return candles out of order — provider should sort them
    mock_client.info.return_value = [
        make_raw_candle(1000007200000),
        make_raw_candle(1000000000000),
        make_raw_candle(1000003600000),
    ]
    candles = provider.fetch("BTC", interval="1h", limit=3)
    timestamps = [c[0] for c in candles]
    assert timestamps == sorted(timestamps)


def test_fetch_empty_response_returns_empty(provider, mock_client):
    mock_client.info.return_value = []
    candles = provider.fetch("BTC", interval="1h", limit=10)
    assert candles == []


def test_fetch_respects_limit(provider, mock_client):
    # API returns 3 candles but we only want 2
    mock_client.info.return_value = RAW_CANDLES
    candles = provider.fetch("BTC", interval="1h", limit=2)
    assert len(candles) == 2


# ──────────────────────────────────────────────────────────────
# FETCH RANGE
# ──────────────────────────────────────────────────────────────


def test_fetch_range_returns_candles(provider, mock_client):
    # Return data on first call, empty on second to stop pagination
    mock_client.info.side_effect = [RAW_CANDLES, []]
    candles = provider.fetch_range(
        "BTC",
        interval="1h",
        start_time=1000000000000,
        end_time=1000100000000,
    )
    assert isinstance(candles, list)


def test_fetch_range_start_after_end_raises(provider):
    with pytest.raises(ValueError, match="start_time must be before end_time"):
        provider.fetch_range(
            "BTC",
            interval="1h",
            start_time=1000100000000,
            end_time=1000000000000,
        )


def test_fetch_range_start_equal_end_raises(provider):
    with pytest.raises(ValueError):
        provider.fetch_range(
            "BTC",
            interval="1h",
            start_time=1000000000000,
            end_time=1000000000000,
        )


def test_fetch_range_deduplicates(provider, mock_client):
    mock_client.info.side_effect = [
        [make_raw_candle(1000000000000)],
        [],
    ]
    candles = provider.fetch_range(
        "BTC",
        interval="1h",
        start_time=1000000000000,
        end_time=1000003600001,
    )
    timestamps = [c[0] for c in candles]
    assert len(timestamps) == len(set(timestamps))


def test_fetch_range_sorted_oldest_first(provider, mock_client):
    mock_client.info.side_effect = [RAW_CANDLES, []]
    candles = provider.fetch_range(
        "BTC",
        interval="1h",
        start_time=1000000000000,
        end_time=1000100000000,
    )
    timestamps = [c[0] for c in candles]
    assert timestamps == sorted(timestamps)


# ──────────────────────────────────────────────────────────────
# HELPER METHODS
# ──────────────────────────────────────────────────────────────


def test_get_close_prices(provider):
    candles = provider.fetch("BTC", interval="1h", limit=3)
    closes = provider.get_close_prices(candles)
    assert closes == [50500.0, 51000.0, 52000.0]


def test_get_volumes(provider):
    candles = provider.fetch("BTC", interval="1h", limit=3)
    volumes = provider.get_volumes(candles)
    assert volumes == [10.5, 8.2, 12.0]


def test_get_timestamps(provider):
    candles = provider.fetch("BTC", interval="1h", limit=3)
    timestamps = provider.get_timestamps(candles)
    assert all(isinstance(t, int) for t in timestamps)
    assert timestamps == sorted(timestamps)


def test_latest_close_returns_float(provider):
    result = provider.latest_close("BTC", interval="1h")
    assert isinstance(result, float)


def test_latest_close_returns_most_recent(provider, mock_client):
    mock_client.info.return_value = [make_raw_candle(1000000000000, c="52000")]
    result = provider.latest_close("BTC")
    assert result == 52000.0


def test_latest_close_empty_raises(provider, mock_client):
    mock_client.info.return_value = []
    with pytest.raises(ValueError, match="No candles"):
        provider.latest_close("BTC")
