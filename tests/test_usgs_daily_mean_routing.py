"""Scheduled USGS daily-mean pulls must use the Water Data API client.

The legacy WaterServices path is being retired and was the source of the
gzip-decode and empty-body failures in config 9. These tests pin the routing
behaviour — which client is actually called for which data_type — not merely
that the import exists.

Model field names were verified on 2026-11-13: PullConfiguration uses
`data_source` (not `agency`), and requires `data_strategy` and
`schedule_type`. Station uses `agency`.
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

NEW_CLIENT = "src.acquisition.tasks.USGSWaterDataClient.get_daily_mean"
LEGACY_DAILY = "src.acquisition.usgs_client.USGSClient.get_daily_mean"
LEGACY_INSTANT = "src.acquisition.usgs_client.USGSClient.get_instantaneous"


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500", name="Skagit", agency="USGS", is_active=True
    )


def _config(data_type):
    return PullConfiguration.objects.create(
        name=f"Test USGS {data_type} Pull",
        data_source="USGS",
        data_type=data_type,
        data_strategy="append",
        schedule_type="custom",
        schedule_value="0 */12 * * *",
        pull_start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )


def _config_station(config, station):
    return PullConfigurationStation.objects.create(
        configuration=config,
        station_number=station.station_number,
        station_name=station.name,
    )


def test_daily_mean_routes_to_waterdata_client(station):
    config = _config("daily_mean")
    cs = _config_station(config, station)

    # Both clients return no observations, so the write path is not exercised;
    # this test is only about which client gets called.
    with patch(NEW_CLIENT, return_value=[]) as new_client, \
         patch(LEGACY_DAILY, return_value=[]) as legacy_daily:
        result = _process_single_station(cs, config.id, config)

    assert new_client.called, "daily_mean must go through USGSWaterDataClient"
    assert not legacy_daily.called, (
        "daily_mean must no longer use the legacy USGSClient.get_daily_mean"
    )
    assert result["success"] is True


def test_realtime_still_routes_to_legacy_client(station):
    # realtime_15min is deliberately left on the legacy client; migrating it
    # is separate work.
    config = _config("realtime_15min")
    cs = _config_station(config, station)

    with patch(NEW_CLIENT, return_value=[]) as new_client, \
         patch(LEGACY_INSTANT, return_value=[]) as legacy_instant:
        result = _process_single_station(cs, config.id, config)

    assert legacy_instant.called, "realtime_15min must use the legacy client"
    assert not new_client.called
    assert result["success"] is True


def test_daily_mean_passes_the_smart_append_start_date(station):
    # The rolling window from Task 4 must reach the new client, otherwise
    # late-published values are still never re-fetched.
    config = _config("daily_mean")
    cs = _config_station(config, station)

    with patch(NEW_CLIENT, return_value=[]) as new_client:
        _process_single_station(cs, config.id, config)

    kwargs = new_client.call_args.kwargs
    assert kwargs["station_number"] == "12200500"
    assert kwargs["start_date"] is not None
    assert kwargs["end_date"] is not None


def test_unknown_data_type_still_reports_failure(station):
    config = _config("daily_mean")
    config.data_type = "something_unsupported"
    config.save(update_fields=["data_type"])
    cs = _config_station(config, station)

    result = _process_single_station(cs, config.id, config)

    assert result["success"] is False
    assert "something_unsupported" in (result["error"] or "")
