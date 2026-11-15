"""Tests for instantaneous (realtime_15min) fetches from the OGC `continuous` collection.

Measured 2026-11-15: discharge there is parameter_code 00060 with
statistic_id 00011 (not 00003); `limit` caps at 50,000; and with NO
`datetime` parameter the API silently returns only the most recent ~1 year,
so an explicit range is mandatory or a historical pull truncates in silence.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.acquisition.usgs_waterdata_client import (
    CONTINUOUS_STATISTIC_ID,
    USGSWaterDataClient,
    USGSWaterDataError,
    USGSWaterDataTransientError,
)

UTC = timezone.utc


class _FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload, self.status_code = payload, status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


def _feature(time, value, approval="Approved", qualifier=None, **over):
    props = {
        "time_series_id": "ts-1",
        "monitoring_location_id": "USGS-12200500",
        "parameter_code": "00060",
        "statistic_id": "00011",
        "time": time,
        "value": value,
        "unit_of_measure": "ft^3/s",
        "approval_status": approval,
        "qualifier": qualifier,
        "last_modified": "2026-05-05T17:41:15.094031+00:00",
        "method_category": None,
    }
    props.update(over)
    return {"properties": props}


def _page(features, next_url=None):
    links = [{"rel": "self", "href": "x"}]
    if next_url:
        links.append({"rel": "next", "href": next_url})
    return {"type": "FeatureCollection", "features": features, "links": links}


def _client():
    return USGSWaterDataClient(api_key="k")


# --- shape -------------------------------------------------------------

def test_emits_full_utc_timestamp_not_midnight():
    # realtime_15min keeps sub-daily resolution; the midnight-UTC rule is
    # daily_mean only.
    page = _page([_feature("2026-11-15T18:15:00+00:00", "47300")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert len(obs) == 1
    assert obs[0]["observed_at"] == datetime(2026, 11, 15, 18, 15, tzinfo=UTC)
    assert obs[0]["observed_at"].tzinfo is not None


def test_obs_dict_shape():
    page = _page([_feature("2026-11-15T18:15:00+00:00", "47300")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert set(obs[0]) == {
        "observed_at", "discharge", "unit", "type", "quality_code"}
    assert obs[0]["unit"] == "cfs"
    assert obs[0]["type"] == "realtime_15min"
    assert obs[0]["discharge"] == 47300.0
    assert isinstance(obs[0]["discharge"], float)


# --- the silent-truncation trap ---------------------------------------

def test_always_sends_an_explicit_datetime_range():
    # Omitting `datetime` makes the API return only the last ~1 year, which
    # would silently truncate a historical pull.
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC))

    assert "datetime" in g.call_args.kwargs["params"]


def test_requests_the_continuous_collection_and_statistic_00011():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2026, 11, 2, tzinfo=UTC))

    url = g.call_args.args[0] if g.call_args.args else g.call_args.kwargs["url"]
    params = g.call_args.kwargs["params"]
    assert "/continuous/items" in url
    assert params["parameter_code"] == "00060"
    assert params["statistic_id"] == CONTINUOUS_STATISTIC_ID == "00011"


def test_end_date_defaults_to_now_not_omitted():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous("12200500", datetime(2026, 11, 1, tzinfo=UTC))

    assert "datetime" in g.call_args.kwargs["params"]


# --- windowing ---------------------------------------------------------

def test_long_range_is_split_into_windows():
    # A year of 15-minute data is ~35,040 points; several years in one
    # request would exceed the 50,000 cap, so the range must be chunked.
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2023, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC))

    assert g.call_count > 1, "a 3-year range must be split into windows"
    sent = [c.kwargs["params"]["datetime"] for c in g.call_args_list]
    assert len(set(sent)) == len(sent), "windows must not repeat"


def test_short_range_is_a_single_request():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2026, 11, 8, tzinfo=UTC))

    assert g.call_count == 1


def test_windows_cover_the_whole_range_without_gaps():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 7, 1, tzinfo=UTC))

    spans = [c.kwargs["params"]["datetime"] for c in g.call_args_list]
    starts = [s.split("/")[0] for s in spans]
    ends = [s.split("/")[1] for s in spans]
    assert starts[0].startswith("2024-01-01")
    assert ends[-1].startswith("2025-07-01")
    for earlier_end, later_start in zip(ends, starts[1:]):
        assert later_start >= earlier_end, "windows must not leave a gap"


def test_reversed_range_raises_value_error_before_any_request():
    # Some OGC servers silently ignore a malformed `datetime` interval and
    # fall back to the default ~1-year window — a truncation the provenance
    # guard cannot detect, since station/parameter/statistic/unit still all
    # match. This must be caught before any request is issued.
    with patch("src.acquisition.usgs_waterdata_client.requests.get") as g:
        with pytest.raises(ValueError):
            _client().get_instantaneous(
                "12200500", datetime(2026, 11, 16, tzinfo=UTC),
                datetime(2026, 11, 15, tzinfo=UTC))

    g.assert_not_called()


def test_equal_start_and_end_is_accepted_as_a_single_window():
    # Not an error: a degenerate (zero-width) single-instant request is
    # well-defined, unlike end < start.
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 15, tzinfo=UTC))

    assert g.call_count == 1
    assert obs == []


def test_naive_start_date_with_defaulted_end_date_is_accepted():
    # A naive start_date combined with a defaulted (aware, now()) end_date
    # used to raise TypeError inside _windows (naive/aware datetimes are not
    # comparable) before _as_iso's own normalisation could ever run.
    # Normalising both dates up front in get_instantaneous fixes this
    # regardless of argument ordering.
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous("12200500", datetime(2026, 11, 1))

    assert g.call_args.kwargs["params"]["datetime"].startswith("2026-11-01")


# --- dedupe ------------------------------------------------------------

def test_duplicate_timestamps_collapse_to_one():
    # Two rows sharing (station, observed_at, type) would break the upsert
    # with "ON CONFLICT DO UPDATE cannot affect row a second time".
    page = _page([
        _feature("2026-11-15T18:15:00+00:00", "47300"),
        _feature("2026-11-15T18:15:00+00:00", "47400", **{"time_series_id": "ts-2"}),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert len(obs) == 1
    stamps = [o["observed_at"] for o in obs]
    assert len(set(stamps)) == len(stamps)


def test_dedupe_is_deterministic_across_calls():
    page = _page([
        _feature("2026-11-15T18:15:00+00:00", "47300"),
        _feature("2026-11-15T18:15:00+00:00", "47400", **{"time_series_id": "ts-2"}),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        a = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))
        b = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert [o["discharge"] for o in a] == [o["discharge"] for o in b]


# --- provenance --------------------------------------------------------

@pytest.mark.parametrize("override", [
    {"monitoring_location_id": "USGS-99999999"},
    {"parameter_code": "00065"},
    {"statistic_id": "00003"},
    {"unit_of_measure": "m^3/s"},
])
def test_server_ignoring_a_filter_raises(override):
    # OGC servers commonly ignore unrecognised query params; without this
    # guard a renamed filter would write another series in as discharge.
    page = _page([_feature("2026-11-15T18:15:00+00:00", "47300", **override)])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with pytest.raises(USGSWaterDataError):
            _client().get_instantaneous(
                "12200500", datetime(2026, 11, 15, tzinfo=UTC),
                datetime(2026, 11, 16, tzinfo=UTC))


# --- values and errors -------------------------------------------------

def test_null_and_unparseable_values_are_skipped():
    page = _page([
        _feature("2026-11-15T18:15:00+00:00", "47300"),
        _feature("2026-11-15T18:30:00+00:00", None),
        _feature("2026-11-15T18:45:00+00:00", "not-a-number"),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert len(obs) == 1


def test_negative_values_are_retained():
    # Negative instantaneous flow is real at tidal and canal sites; the
    # daily path already retains it.
    page = _page([_feature("2026-11-15T18:15:00+00:00", "-120.5")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert obs[0]["discharge"] == -120.5


def test_quality_code_mapping_matches_the_daily_path():
    page = _page([_feature("2026-11-15T18:15:00+00:00", "47300",
                           approval="Provisional", qualifier=["ESTIMATED"])])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert obs[0]["quality_code"] == "P, e"
    assert len(obs[0]["quality_code"]) <= 10


def test_429_is_transient():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=429)):
        with pytest.raises(USGSWaterDataTransientError):
            _client().get_instantaneous(
                "12200500", datetime(2026, 11, 15, tzinfo=UTC),
                datetime(2026, 11, 16, tzinfo=UTC), _retries=0)


def test_404_is_permanent():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=404)):
        with pytest.raises(USGSWaterDataError):
            _client().get_instantaneous(
                "12200500", datetime(2026, 11, 15, tzinfo=UTC),
                datetime(2026, 11, 16, tzinfo=UTC), _retries=0)


def test_empty_result_is_an_empty_list():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))):
        assert _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC)) == []


def test_multiple_time_series_are_logged(caplog):
    page = _page([
        _feature("2026-11-15T18:15:00+00:00", "47300"),
        _feature("2026-11-15T18:30:00+00:00", "47400", **{"time_series_id": "ts-2"}),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with caplog.at_level("WARNING"):
            _client().get_instantaneous(
                "12200500", datetime(2026, 11, 15, tzinfo=UTC),
                datetime(2026, 11, 16, tzinfo=UTC))

    assert any("multiple time series" in r.message.lower()
               for r in caplog.records)


def test_results_are_sorted_by_timestamp():
    page = _page([
        _feature("2026-11-15T18:45:00+00:00", "3"),
        _feature("2026-11-15T18:15:00+00:00", "1"),
        _feature("2026-11-15T18:30:00+00:00", "2"),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert [o["discharge"] for o in obs] == [1.0, 2.0, 3.0]


@pytest.mark.integration
def test_live_continuous_returns_recent_points():
    # Asserting only a lower bound does not actually test the thing this
    # task exists to prevent: if the server silently ignored the `datetime`
    # parameter and fell back to its default ~1-year window, it would
    # return ~35,040 points for this station, which also satisfies
    # `len(obs) > 100`. An upper bound, plus checking that every returned
    # timestamp actually falls inside the requested window, is what closes
    # the loop on silent truncation.
    from datetime import datetime as _dt
    end = _dt.now(UTC)
    start = end - timedelta(days=3)
    obs = USGSWaterDataClient().get_instantaneous("12200500", start, end)

    # ~288 points expected for 3 days at 15-minute resolution. The upper
    # bound leaves room for a denser 1- or 5-minute series while still
    # failing hard on a full-year (~35,040-point) return.
    assert 100 < len(obs) < 2000, (
        f"expected ~288 points for 3 days, got {len(obs)} — a count this "
        "far outside the 15-minute-resolution range would mean the server "
        "ignored the `datetime` filter and returned its default window."
    )
    assert all(o["type"] == "realtime_15min" for o in obs)
    assert all(o["unit"] == "cfs" for o in obs)
    stamps = [o["observed_at"] for o in obs]
    assert len(set(stamps)) == len(stamps), "live data must have unique stamps"

    # The pair that actually proves the range was honoured: every returned
    # timestamp must fall inside [start, end], not just be plausible in count.
    assert min(stamps) >= start, "earliest point falls before the requested window"
    assert max(stamps) <= end, "latest point falls after the requested window"
