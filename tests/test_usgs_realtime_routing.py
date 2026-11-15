"""realtime_15min must come from the Water Data `continuous` collection.

The feature currently stores no rows — the data was removed under storage
pressure and will return for a few dozen stations — so this routing is
verified by behaviour, not by stored data.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from apps.streamflow.models import (
    PullConfiguration,
    PullConfigurationStation,
    Station,
)
from src.acquisition.tasks import _process_single_station

NEW_INSTANT = "src.acquisition.tasks.USGSWaterDataClient.get_instantaneous"
NEW_DAILY = "src.acquisition.tasks.USGSWaterDataClient.get_daily_mean"
LEGACY_INSTANT = "src.acquisition.usgs_client.USGSClient.get_instantaneous"


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500", name="Skagit", agency="USGS", is_active=True
    )


def _config(data_type):
    return PullConfiguration.objects.create(
        name=f"Test {data_type}",
        data_source="USGS",
        data_type=data_type,
        data_strategy="append",
        schedule_type="custom",
        schedule_value="*/15 * * * *",
        pull_start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )


def _cs(config, station):
    return PullConfigurationStation.objects.create(
        configuration=config, station_number=station.station_number,
        station_name=station.name,
    )


def test_realtime_routes_to_the_new_client(station):
    config = _config("realtime_15min")
    cs = _cs(config, station)

    with patch(NEW_INSTANT, return_value=[]) as new, \
         patch(LEGACY_INSTANT, return_value=[]) as legacy:
        result = _process_single_station(cs, config.id, config)

    assert new.called, "realtime_15min must use USGSWaterDataClient"
    assert not legacy.called, "the legacy NWIS path must no longer be used"
    assert result["success"] is True


def test_daily_mean_still_routes_to_the_new_client(station):
    config = _config("daily_mean")
    cs = _cs(config, station)

    with patch(NEW_DAILY, return_value=[]) as daily, \
         patch(NEW_INSTANT, return_value=[]) as instant:
        result = _process_single_station(cs, config.id, config)

    assert daily.called
    assert not instant.called
    assert result["success"] is True


def test_realtime_receives_the_smart_append_window(station):
    config = _config("realtime_15min")
    cs = _cs(config, station)

    with patch(NEW_INSTANT, return_value=[]) as new:
        _process_single_station(cs, config.id, config)

    kwargs = new.call_args.kwargs
    assert kwargs["station_number"] == "12200500"
    assert kwargs["start_date"] is not None
    assert kwargs["end_date"] is not None


def test_realtime_is_not_given_the_180_day_rewind(station):
    # Gating the rewind to daily_mean/ec_realtime_daily is load-bearing:
    # otherwise every realtime config would re-pull 180 days of 15-minute
    # data on every 5-minute dispatch.
    from src.acquisition.smart_append import REFETCH_WINDOW_DATA_TYPES

    assert "realtime_15min" not in REFETCH_WINDOW_DATA_TYPES
