"""Incremental pulls must rewind, so late-published values are picked up.

USGS fills in ice-affected and equipment-affected days afterwards as estimated
values ("A, e"). Starting every pull at last_successful_pull_date meant those
days were never fetched: the two largest missing days at 12200500 (2021-11-15
= 94,100 cfs and 2021-11-16 = 119,000 cfs) are both "A,e".
"""

from datetime import datetime, timedelta, timezone

import pytest
from django.conf import settings

from apps.streamflow.models import (
    PullConfiguration,
    PullStationProgress,
    Station,
)
from src.acquisition.smart_append import SmartAppendLogic


CONFIG_START = datetime(1900, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def config(db):
    # Field names and values verified against the model and real config 9
    # ("USGS Daily Mean Pull") on 2026-11-13. The source field is
    # `data_source`, NOT `agency` — `agency` lives on Station, not on
    # PullConfiguration. `data_strategy` and `schedule_type` are required.
    return PullConfiguration.objects.create(
        name="Test USGS Daily Mean Pull",
        data_source="USGS",
        data_type="daily_mean",
        data_strategy="append",
        schedule_type="custom",
        schedule_value="0 */12 * * *",
        pull_start_date=CONFIG_START,
    )


def test_first_pull_uses_config_start_date(config):
    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=CONFIG_START,
    )
    assert start == CONFIG_START


def test_subsequent_pull_rewinds_by_the_window(config):
    last = datetime(2026, 11, 10, tzinfo=timezone.utc)
    PullStationProgress.objects.create(
        configuration=config,
        station_number="12200500",
        last_successful_pull_date=last,
    )

    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=CONFIG_START,
        data_type="daily_mean",
    )

    expected = last - timedelta(days=settings.OBSERVATION_REFETCH_WINDOW_DAYS)
    assert start == expected


def test_rewind_never_predates_config_start_date(config):
    # A config that only wants 2026 onward must not be rewound into 2025.
    config_start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    PullStationProgress.objects.create(
        configuration=config,
        station_number="12200500",
        last_successful_pull_date=datetime(2026, 11, 10, tzinfo=timezone.utc),
    )

    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=config_start,
        data_type="daily_mean",
    )

    assert start == config_start


# -- B1: the rewind is for daily means only ---------------------------------
#
# get_pull_start_date is the single code path for every pull. A 180-day
# rewind on a realtime_15min config would request ~17,280 instantaneous
# points per station on every 5-minute dispatch cycle, permanently, because
# the watermark is re-rewound each run.

LAST_PULL = datetime(2026, 11, 10, tzinfo=timezone.utc)


def _config_for(data_type):
    return PullConfiguration.objects.create(
        name=f"Test {data_type} Pull",
        data_source="USGS",
        data_type=data_type,
        data_strategy="append",
        schedule_type="custom",
        schedule_value="*/5 * * * *",
        pull_start_date=CONFIG_START,
    )


def _progress(config):
    PullStationProgress.objects.create(
        configuration=config,
        station_number="12200500",
        last_successful_pull_date=LAST_PULL,
    )


def test_realtime_15min_is_not_rewound(db):
    config = _config_for("realtime_15min")
    _progress(config)

    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=CONFIG_START,
        data_type="realtime_15min",
    )

    assert start == LAST_PULL


def test_ec_realtime_daily_is_rewound(db):
    config = _config_for("ec_realtime_daily")
    _progress(config)

    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=CONFIG_START,
        data_type="ec_realtime_daily",
    )

    assert start == LAST_PULL - timedelta(
        days=settings.OBSERVATION_REFETCH_WINDOW_DAYS
    )


def test_omitting_data_type_does_not_rewind(config):
    # A caller that does not say what it is pulling gets the conservative
    # pre-rewind behaviour, not a 180-day window.
    _progress(config)

    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=CONFIG_START,
    )

    assert start == LAST_PULL


def test_forecast_data_type_is_not_rewound(db):
    config = _config_for("forecast")
    _progress(config)

    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=CONFIG_START,
        data_type="forecast",
    )

    assert start == LAST_PULL


def test_scheduled_pull_passes_the_config_data_type(db):
    """The rewind gate is only effective if the sole caller actually passes
    data_type — tasks._process_single_station must forward config.data_type."""
    from unittest.mock import patch

    from apps.streamflow.models import PullConfigurationStation, Station
    from src.acquisition import tasks

    Station.objects.create(
        station_number="12200500", name="Skagit", agency="USGS", is_active=True
    )
    config = _config_for("realtime_15min")
    config_station = PullConfigurationStation.objects.create(
        configuration=config,
        station_number="12200500",
        station_name="Skagit",
    )

    with patch.object(
        tasks.SmartAppendLogic, "get_pull_start_date", return_value=CONFIG_START
    ) as mock_start, patch(
        "src.acquisition.usgs_client.USGSClient.get_instantaneous",
        return_value=[],
    ):
        tasks._process_single_station(config_station, config.id, config)

    assert mock_start.call_args.kwargs["data_type"] == "realtime_15min"
