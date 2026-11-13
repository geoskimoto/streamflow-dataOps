"""Tests for the USGS Water Data OGC API daily-mean client.

All HTTP is mocked. The live-API test is marked `integration` and skipped by
default, matching tests/test_usgs_client.py.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import requests

from src.acquisition.usgs_waterdata_client import (
    USGSWaterDataClient,
    USGSWaterDataError,
    USGSWaterDataTransientError,
    build_quality_code,
)


class _FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


class _BadJSONResponse(_FakeResponse):
    """A 200 whose body is truncated/empty — undecodable, not malformed."""

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def _feature(time, value, approval="Approved", qualifier=None):
    return {
        "properties": {
            "time_series_id": "abc",
            "monitoring_location_id": "USGS-12200500",
            "parameter_code": "00060",
            "statistic_id": "00003",
            "time": time,
            "value": value,
            "unit_of_measure": "ft^3/s",
            "approval_status": approval,
            "qualifier": qualifier,
            "last_modified": "2025-02-27T15:09:29.008013+00:00",
        }
    }


def _page(features, next_url=None):
    links = [{"rel": "self", "href": "x"}]
    if next_url:
        links.append({"rel": "next", "href": next_url})
    return {"type": "FeatureCollection", "features": features, "links": links}


# --- quality code mapping -------------------------------------------------

def test_quality_code_approved_no_qualifier():
    assert build_quality_code("Approved", None) == "A"


def test_quality_code_provisional():
    assert build_quality_code("Provisional", None) == "P"


def test_quality_code_approved_estimated_matches_legacy_format():
    # Legacy NWIS stored this as "A, e" and 654,593 such rows already exist.
    assert build_quality_code("Approved", ["ESTIMATED"]) == "A, e"


def test_quality_code_revised():
    assert build_quality_code("Approved", ["REVISED"]) == "A, R"


def test_quality_code_equip_and_estimated():
    # Canonical order (QUALIFIER_CODES declaration order) is ESTIMATED before
    # EQUIP, regardless of input order.
    assert build_quality_code("Approved", ["EQUIP", "ESTIMATED"]) == "A, e, q"


def test_quality_code_is_independent_of_input_order():
    forward = build_quality_code("Approved", ["EQUIP", "ESTIMATED"])
    reverse = build_quality_code("Approved", ["ESTIMATED", "EQUIP"])
    assert forward == reverse == "A, e, q"


def test_quality_code_unmapped_approval_status_raises(caplog):
    """B2: this used to log a warning and return a code with no base letter.
    Because DataProcessor upserts quality_code and the backfill defaults to
    the whole record, a USGS vocabulary change ("Approved" -> "approved")
    would have overwritten ~10M stored 'A'/'A, e' codes with an empty string
    behind one warning in a multi-hour log. It must fail the gage instead.
    """
    with pytest.raises(USGSWaterDataError, match="approval_status"):
        build_quality_code("SomethingNew", None)


def test_quality_code_none_approval_status_is_lenient():
    # Only a *present but unrecognised* status is an error; a missing one
    # simply contributes no base letter, as before.
    assert build_quality_code(None, ["ESTIMATED"]) == "e"


def test_quality_code_empty_approval_status_is_lenient():
    assert build_quality_code("", None) == ""


def test_unmapped_approval_status_fails_the_whole_station_fetch():
    page = _page([_feature("2021-11-16", "119000", approval="approved")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with pytest.raises(USGSWaterDataError, match="approval_status"):
            USGSWaterDataClient().get_daily_mean("12200500", None)


def test_quality_code_truncated_to_field_length():
    code = build_quality_code(
        "Approved", ["EQUIP", "ESTIMATED", "ICE", "MAINT", "BACKWATER", "REVISED"]
    )
    assert len(code) <= 10


def test_quality_code_unknown_qualifier_is_ignored_not_crashing():
    assert build_quality_code("Approved", ["SOMETHING_NEW"]) == "A"


# --- parsing --------------------------------------------------------------

def test_observed_at_is_midnight_utc():
    # All 25,311,950 existing USGS daily_mean rows are at 00:00:00 UTC. Any
    # other time-of-day would insert duplicates instead of updating.
    page = _page([_feature("2021-11-16", "119000")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert len(obs) == 1
    assert obs[0]["observed_at"] == datetime(2021, 11, 16, tzinfo=timezone.utc)
    assert obs[0]["observed_at"].tzinfo is not None


def test_string_value_is_converted_to_float():
    page = _page([_feature("2021-11-16", "119000")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert obs[0]["discharge"] == 119000.0
    assert isinstance(obs[0]["discharge"], float)


def test_obs_dict_shape_matches_legacy_client():
    page = _page([_feature("2021-11-16", "119000")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert set(obs[0]) == {
        "observed_at", "discharge", "unit", "type", "quality_code"
    }
    assert obs[0]["unit"] == "cfs"
    assert obs[0]["type"] == "daily_mean"


def test_the_skagit_crest_round_trips():
    crest = {
        "2021-11-13": ("65200", None),
        "2021-11-15": ("94100", ["EQUIP", "ESTIMATED"]),
        "2021-11-16": ("119000", ["EQUIP", "ESTIMATED"]),
        "2021-11-17": ("96200", None),
    }
    page = _page([
        _feature(t, v, qualifier=q) for t, (v, q) in crest.items()
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    by_date = {o["observed_at"].date().isoformat(): o for o in obs}
    assert by_date["2021-11-16"]["discharge"] == 119000.0
    assert by_date["2021-11-16"]["quality_code"] == "A, e, q"
    assert by_date["2021-11-13"]["quality_code"] == "A"


def test_null_and_unparseable_values_are_skipped_with_a_log(caplog):
    page = _page([
        _feature("2021-11-16", "119000"),
        _feature("2021-11-17", None),
        _feature("2021-11-18", "not-a-number"),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with caplog.at_level("WARNING"):
            obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert len(obs) == 1
    assert any("Unparseable" in r.message for r in caplog.records)


def test_empty_result_returns_empty_list():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))):
        assert USGSWaterDataClient().get_daily_mean("12200500", None) == []


# --- multi-series de-duplication (CRITICAL 1) -----------------------------

def _with_series(time, value, series_id, qualifier=None):
    feat = _feature(time, value, qualifier=qualifier)
    feat["properties"]["time_series_id"] = series_id
    return feat


def test_two_series_same_date_yields_exactly_one_observation_deterministically():
    feat_a = _with_series("2021-11-16", "100", "series-a")
    feat_b = _with_series("2021-11-16", "200", "series-b")

    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([feat_a, feat_b]))):
        obs_forward = USGSWaterDataClient().get_daily_mean("12200500", None)

    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([feat_b, feat_a]))):
        obs_reverse = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert len(obs_forward) == 1
    assert len(obs_reverse) == 1
    # "series-a" sorts before "series-b" lexicographically, so it wins
    # regardless of the order the API happened to return the features in.
    assert obs_forward[0]["discharge"] == obs_reverse[0]["discharge"] == 100.0


def test_two_series_different_dates_keeps_both():
    feat_a = _with_series("2021-11-15", "100", "series-a")
    feat_b = _with_series("2021-11-16", "200", "series-b")

    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([feat_a, feat_b]))):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert len(obs) == 2
    by_date = {o["observed_at"].date().isoformat(): o["discharge"] for o in obs}
    assert by_date["2021-11-15"] == 100.0
    assert by_date["2021-11-16"] == 200.0


def test_duplicate_date_logs_human_review_warning(caplog):
    feat_a = _with_series("2021-11-16", "100", "series-a")
    feat_b = _with_series("2021-11-16", "200", "series-b")

    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([feat_a, feat_b]))):
        with caplog.at_level("WARNING"):
            USGSWaterDataClient().get_daily_mean("12200500", None)

    assert any("human review" in r.message.lower() for r in caplog.records)
    assert any("multiple time series" in r.message.lower() for r in caplog.records)


# --- pagination -----------------------------------------------------------

def test_pagination_follows_next_link():
    page_1 = _page([_feature("2021-11-15", "94100")], next_url="http://next/page2")
    page_2 = _page([_feature("2021-11-16", "119000")])

    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               side_effect=[_FakeResponse(page_1), _FakeResponse(page_2)]) as g:
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert len(obs) == 2
    assert g.call_count == 2

    first_call, second_call = g.call_args_list
    # The second request must hit the `next` href, not re-request page one.
    assert second_call.args[0] == "http://next/page2"
    # The `next` href already carries the original query string, so the
    # follow-up request must not resend the original params (an
    # implementation that re-sent them, or re-requested page one twice,
    # would still pass a bare call_count == 2 assertion).
    assert second_call.kwargs["params"] == {}
    assert first_call.args[0] != second_call.args[0]


def test_pagination_stops_when_no_next_link():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               side_effect=[_FakeResponse(_page([_feature("2021-11-16", "1")]))]) as g:
        USGSWaterDataClient().get_daily_mean("12200500", None)
    assert g.call_count == 1


def test_pagination_cap_exceeded_raises_error():
    # Every page links to a `next`, so pagination never terminates on its
    # own; the client must give up at MAX_PAGES rather than return a
    # silently truncated series.
    endless_page = _page(
        [_feature("2021-01-01", "1")], next_url="http://next/page"
    )
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(endless_page)):
        with pytest.raises(USGSWaterDataError):
            USGSWaterDataClient().get_daily_mean("12200500", None)


# --- errors ---------------------------------------------------------------

def test_429_raises_transient_error():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=429,
                                          headers={"Retry-After": "1"})):
        with pytest.raises(USGSWaterDataTransientError):
            USGSWaterDataClient().get_daily_mean("12200500", None, _retries=0)


def test_503_raises_transient_error():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=503)):
        with pytest.raises(USGSWaterDataTransientError):
            USGSWaterDataClient().get_daily_mean("12200500", None, _retries=0)


def test_404_raises_permanent_error():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=404)):
        with pytest.raises(USGSWaterDataError):
            USGSWaterDataClient().get_daily_mean("12200500", None, _retries=0)


def test_undecodable_json_body_is_transient_not_permanent():
    # A 200 with a truncated/empty body ("Expecting value: line 1 column 1
    # (char 0)") is exactly the failure mode this client exists to fix on
    # the legacy endpoint, and it self-heals on retry — it must not be
    # classified as a permanent USGSWaterDataError.
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_BadJSONResponse({})):
        with pytest.raises(USGSWaterDataTransientError):
            USGSWaterDataClient().get_daily_mean("12200500", None, _retries=0)


# --- retry behaviour (IMPORTANT 7) ----------------------------------------

def test_503_then_200_succeeds_after_one_retry():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               side_effect=[_FakeResponse({}, status_code=503),
                            _FakeResponse(_page([_feature("2021-11-16", "1")]))]) as g, \
         patch("src.acquisition.usgs_waterdata_client._time.sleep") as sleep_mock:
        obs = USGSWaterDataClient().get_daily_mean("12200500", None, _retries=1)

    assert len(obs) == 1
    assert g.call_count == 2
    assert sleep_mock.call_count == 1


def test_retry_after_header_sets_the_sleep_delay():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               side_effect=[_FakeResponse({}, status_code=429,
                                          headers={"Retry-After": "1"}),
                            _FakeResponse(_page([]))]) as g, \
         patch("src.acquisition.usgs_waterdata_client._time.sleep") as sleep_mock:
        USGSWaterDataClient().get_daily_mean("12200500", None, _retries=1)

    assert g.call_count == 2
    sleep_mock.assert_called_once_with(1.0)


def test_retry_budget_exhausted_raises_after_exact_attempt_count():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=503)) as g, \
         patch("src.acquisition.usgs_waterdata_client._time.sleep") as sleep_mock:
        with pytest.raises(USGSWaterDataTransientError):
            USGSWaterDataClient().get_daily_mean("12200500", None, _retries=2)

    # Initial attempt + 2 retries = 3 requests, 2 sleeps.
    assert g.call_count == 3
    assert sleep_mock.call_count == 2


def test_network_exception_is_transient_and_retried():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               side_effect=[requests.ConnectionError("boom"),
                            _FakeResponse(_page([]))]) as g, \
         patch("src.acquisition.usgs_waterdata_client._time.sleep") as sleep_mock:
        USGSWaterDataClient().get_daily_mean("12200500", None, _retries=1)

    assert g.call_count == 2
    assert sleep_mock.call_count == 1


def test_404_is_never_retried():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=404)) as g, \
         patch("src.acquisition.usgs_waterdata_client._time.sleep") as sleep_mock:
        with pytest.raises(USGSWaterDataError):
            USGSWaterDataClient().get_daily_mean("12200500", None, _retries=3)

    assert g.call_count == 1
    sleep_mock.assert_not_called()


# --- request construction -------------------------------------------------

def test_request_filters_on_parameter_and_statistic():
    # statistic_id=00003 is what replaces the legacy discharge_cols[0] guess.
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        USGSWaterDataClient().get_daily_mean("12200500", None)

    params = g.call_args.kwargs["params"]
    assert params["monitoring_location_id"] == "USGS-12200500"
    assert params["parameter_code"] == "00060"
    assert params["statistic_id"] == "00003"
    assert params["skipGeometry"] == "true"


def test_date_range_is_sent_as_a_datetime_interval():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        USGSWaterDataClient().get_daily_mean(
            "12200500",
            datetime(2026, 10, 1, tzinfo=timezone.utc),
            datetime(2026, 11, 12, tzinfo=timezone.utc),
        )

    assert g.call_args.kwargs["params"]["datetime"] == "2026-10-01/2026-11-12"


def test_no_dates_sends_no_datetime_param():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        USGSWaterDataClient().get_daily_mean("12200500", None)

    assert "datetime" not in g.call_args.kwargs["params"]


def test_api_key_sent_as_header_when_configured():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        client = USGSWaterDataClient(api_key="secret-key")
        client.get_daily_mean("12200500", None)

    assert g.call_args.kwargs["headers"]["X-Api-Key"] == "secret-key"


def test_no_api_key_header_when_unset():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        client = USGSWaterDataClient(api_key="")
        client.get_daily_mean("12200500", None)

    assert "X-Api-Key" not in g.call_args.kwargs["headers"]


def test_multiple_time_series_are_logged(caplog):
    page = _page([
        _feature("2021-11-16", "119000"),
        {"properties": {**_feature("2021-11-16", "42")["properties"],
                        "time_series_id": "second-series"}},
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with caplog.at_level("WARNING"):
            USGSWaterDataClient().get_daily_mean("12200500", None)

    assert any("multiple time series" in r.message.lower()
               for r in caplog.records)


# --- provenance of returned features (B3) ---------------------------------
#
# OGC implementations commonly ignore query parameters they don't recognise.
# If USGS renamed a filter param, `limit=50000` would return an unfiltered
# slice of the `daily` collection and the backfill would write another
# station's — or another parameter's — values in as discharge.
# validate_observations only guards negatives, so stage or temperature values
# would pass straight through. The API echoes all four fields on every
# feature, so the check is cheap.


def _feature_with(prop, value):
    feat = _feature("2021-11-16", "119000")
    feat["properties"][prop] = value
    return feat


@pytest.mark.parametrize(
    "prop,value",
    [
        ("monitoring_location_id", "USGS-14306500"),
        ("parameter_code", "00065"),          # gage height, not discharge
        ("statistic_id", "00001"),            # daily maximum, not mean
        ("unit_of_measure", "ft"),            # stage units, not cfs
    ],
)
def test_feature_not_matching_our_filters_raises(prop, value):
    page = _page([_feature_with(prop, value)])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with pytest.raises(USGSWaterDataError, match=prop):
            USGSWaterDataClient().get_daily_mean("12200500", None)


def test_one_foreign_feature_among_good_ones_still_raises():
    # A nonzero skip count means the server is not honouring our filters, so
    # the whole response is untrustworthy — we must not keep the subset that
    # happened to match.
    page = _page([
        _feature("2021-11-15", "94100"),
        _feature_with("monitoring_location_id", "USGS-14306500"),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with pytest.raises(USGSWaterDataError, match="12200500"):
            USGSWaterDataClient().get_daily_mean("12200500", None)


def test_all_correct_provenance_parses_normally():
    page = _page([
        _feature("2021-11-15", "94100"),
        _feature("2021-11-16", "119000"),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert [o["discharge"] for o in obs] == [94100.0, 119000.0]


@pytest.mark.integration
def test_live_api_returns_the_skagit_crest():
    obs = USGSWaterDataClient().get_daily_mean(
        "12200500",
        datetime(2021, 11, 10, tzinfo=timezone.utc),
        datetime(2021, 11, 22, tzinfo=timezone.utc),
    )
    by_date = {o["observed_at"].date().isoformat(): o["discharge"] for o in obs}
    assert by_date["2021-11-16"] == 119000.0
    assert by_date["2021-11-15"] == 94100.0
