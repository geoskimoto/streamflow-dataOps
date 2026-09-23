"""Tests for storing live NOAA_RFC forecast pulls.

Two behaviours are pinned: re-pulling the same issuance updates in place
rather than inserting a duplicate, and forecast_type reflects the actual
horizon instead of always defaulting to 'short'.
"""

from datetime import datetime, timezone

import pytest

from apps.streamflow.models import ForecastRun, Station
from src.acquisition.parquet_forecast_importer import infer_forecast_type
from src.acquisition.tasks import store_rfc_forecast


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="WTLO3", name="Test Gauge", agency="NOAA_RFC", is_active=True
    )


def _payload(run_date, points, rmse=None):
    return {"run_date": run_date, "forecast_data": points, "rmse": rmse}


def test_repeat_issuance_updates_instead_of_duplicating(station):
    """The old create() inserted a second row for the same issuance."""
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    store_rfc_forecast(station, _payload(
        run_date, [{"date": "2026-09-22T18:00:00Z", "value": 1340.0}]))
    run, created = store_rfc_forecast(station, _payload(
        run_date, [{"date": "2026-09-22T18:00:00Z", "value": 1350.0}]))

    assert created is False
    runs = ForecastRun.objects.filter(station=station, source="NOAA_RFC")
    assert runs.count() == 1
    assert runs.first().data[0]["value"] == 1350.0


def test_ten_day_forecast_is_not_labelled_short(station):
    """The live path hardcoded 'short' by falling back to the model default.

    Horizon here is 224.57 h (9.36 days): past the 7-day 'short' cutoff and
    within the 10-day 'medium' one. Keep the last point inside 240 h of the
    issuance or this becomes a 'long' run and stops testing what it names.
    """
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    run, _ = store_rfc_forecast(station, _payload(run_date, [
        {"date": "2026-09-22T18:00:00Z", "value": 1340.0},
        {"date": "2026-10-02T00:00:00Z", "value": 1200.0},
    ]))
    assert run.forecast_type == "medium"


def test_short_horizon_is_labelled_short(station):
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    run, _ = store_rfc_forecast(station, _payload(run_date, [
        {"date": "2026-09-22T18:00:00Z", "value": 1340.0},
        {"date": "2026-09-25T18:00:00Z", "value": 1200.0},
    ]))
    assert run.forecast_type == "short"


def test_unordered_points_still_yield_correct_forecast_type(station):
    """The NWPS `data` array is not guaranteed chronological.

    points[-1] would pick the horizon based on array order rather than the
    actual last valid time; max() must be used instead so an out-of-order
    response is still classified correctly and doesn't collide with the
    correctly-ordered row on the unique key.
    """
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    # Last element in the array is NOT the chronologically last point.
    run, _ = store_rfc_forecast(station, _payload(run_date, [
        {"date": "2026-10-02T00:00:00Z", "value": 1200.0},  # actual last (9.36 days out)
        {"date": "2026-09-22T18:00:00Z", "value": 1340.0},  # array-last, but earliest in time
    ]))
    assert run.forecast_type == "medium"


def test_differing_horizons_do_not_collide(station):
    """Same issuance, different horizon -> distinct rows, per the unique key."""
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    store_rfc_forecast(station, _payload(run_date, [
        {"date": "2026-09-25T18:00:00Z", "value": 1.0}]))
    store_rfc_forecast(station, _payload(run_date, [
        {"date": "2026-10-02T18:00:00Z", "value": 2.0}]))
    assert ForecastRun.objects.filter(station=station).count() == 2


def test_rmse_is_persisted(station):
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    run, _ = store_rfc_forecast(station, _payload(
        run_date, [{"date": "2026-09-23T18:00:00Z", "value": 1.0}], rmse=0.25))
    assert float(run.rmse) == 0.25


@pytest.mark.parametrize(
    "horizon_hours,expected",
    [
        (24.0, "short"),
        (7 * 24, "short"),        # boundary: exactly 7 days is short
        (7 * 24 + 0.1, "medium"),
        (10 * 24, "medium"),      # boundary: exactly 10 days is medium
        (10 * 24 + 0.1, "long"),
        (30 * 24, "long"),
    ],
)
def test_forecast_type_follows_horizon(horizon_hours, expected):
    assert infer_forecast_type(horizon_hours) == expected
