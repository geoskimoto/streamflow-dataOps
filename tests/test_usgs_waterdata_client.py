"""Tests for the USGS Water Data OGC API daily-mean client.

All HTTP is mocked. The live-API test is marked `integration` and skipped by
default, matching tests/test_usgs_client.py.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

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
    assert build_quality_code("Approved", ["EQUIP", "ESTIMATED"]) == "A, q, e"


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
    assert by_date["2021-11-16"]["quality_code"] == "A, q, e"
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


# --- pagination -----------------------------------------------------------

def test_pagination_follows_next_link():
    page_1 = _page([_feature("2021-11-15", "94100")], next_url="http://next/page2")
    page_2 = _page([_feature("2021-11-16", "119000")])

    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               side_effect=[_FakeResponse(page_1), _FakeResponse(page_2)]) as g:
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert len(obs) == 2
    assert g.call_count == 2


def test_pagination_stops_when_no_next_link():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               side_effect=[_FakeResponse(_page([_feature("2021-11-16", "1")]))]) as g:
        USGSWaterDataClient().get_daily_mean("12200500", None)
    assert g.call_count == 1


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
