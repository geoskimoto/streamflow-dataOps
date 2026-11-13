"""Re-pulling a day must overwrite its value, not silently keep the old one.

USGS publishes provisional daily values and revises them for months. With
ignore_conflicts the first provisional value was kept forever, leaving 49,523
gage-days stale against USGS.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from apps.streamflow.models import DischargeObservation, Station
from src.acquisition.data_processor import DataProcessor


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500",
        name="SKAGIT RIVER NEAR MOUNT VERNON, WA",
        agency="USGS",
        is_active=True,
    )


def _obs(value, quality_code):
    return {
        "observed_at": datetime(2021, 11, 16, tzinfo=timezone.utc),
        "discharge": value,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": quality_code,
    }


def test_revised_value_replaces_provisional(station):
    processor = DataProcessor()

    processor.process_observations(
        station_number=station.station_number, observations=[_obs(95000.0, "P")]
    )
    processor.process_observations(
        station_number=station.station_number, observations=[_obs(119000.0, "A, e")]
    )

    rows = DischargeObservation.objects.filter(
        station=station, type="daily_mean"
    )
    assert rows.count() == 1, "upsert must not create a duplicate row"
    row = rows.get()
    assert row.discharge == Decimal("119000.0000")
    assert row.quality_code == "A, e"


def test_repulling_identical_data_does_not_duplicate(station):
    processor = DataProcessor()
    for _ in range(3):
        processor.process_observations(
            station_number=station.station_number, observations=[_obs(119000.0, "A")]
        )

    assert DischargeObservation.objects.filter(station=station).count() == 1


def test_distinct_days_both_stored(station):
    processor = DataProcessor()
    observations = [
        {
            "observed_at": datetime(2021, 11, day, tzinfo=timezone.utc),
            "discharge": value,
            "unit": "cfs",
            "type": "daily_mean",
            "quality_code": "A",
        }
        for day, value in ((15, 94100.0), (16, 119000.0))
    ]

    processor.process_observations(
        station_number=station.station_number, observations=observations
    )

    assert DischargeObservation.objects.filter(station=station).count() == 2
