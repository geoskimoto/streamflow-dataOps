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
    )

    assert start == config_start
