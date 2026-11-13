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


# -- N1: intra-batch duplicate keys must not abort the station's write ------
#
# With update_conflicts=True PostgreSQL raises "ON CONFLICT DO UPDATE command
# cannot affect row a second time" on an intra-batch duplicate key, inside
# transaction.atomic() — losing the whole station's batch. Under the old
# ignore_conflicts the duplicate was absorbed. Only the Water Data client
# dedupes its own output; EC's paginated fetch and USGSClient.get_instantaneous
# do not, so process_observations is the choke point that must guarantee it.


def test_duplicate_key_in_one_batch_writes_one_row_without_raising(station):
    processor = DataProcessor()

    written = processor.process_observations(
        station_number=station.station_number,
        observations=[_obs(95000.0, "P"), _obs(119000.0, "A, e")],
    )

    rows = DischargeObservation.objects.filter(station=station)
    assert rows.count() == 1
    # Last occurrence wins: sources page oldest-first, so the later entry
    # carries the fresher value.
    assert rows.get().discharge == Decimal("119000.0000")
    assert rows.get().quality_code == "A, e"
    assert written == 1


def test_collapsed_duplicate_is_logged_with_station_and_count(station, caplog):
    processor = DataProcessor()

    with caplog.at_level("WARNING"):
        processor.process_observations(
            station_number=station.station_number,
            observations=[_obs(95000.0, "P"), _obs(119000.0, "A, e")],
        )

    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "Collapsed 1 duplicate" in m and station.station_number in m
        for m in messages
    ), messages


def test_same_timestamp_different_type_is_not_collapsed(station):
    processor = DataProcessor()
    daily = _obs(119000.0, "A")
    instant = dict(_obs(118500.0, "P"), type="realtime_15min")

    processor.process_observations(
        station_number=station.station_number,
        observations=[daily, instant],
    )

    assert DischargeObservation.objects.filter(station=station).count() == 2


# -- T3: an unparseable date must be skipped, never fabricated -------------


def test_unparseable_observed_at_is_skipped_and_logged(station, caplog):
    """Substituting datetime.utcnow() produced a naive timestamp at the
    current time-of-day, which can never match an existing
    (station, observed_at, type) key — so a malformed date created an orphan
    row instead of correcting one, violating the midnight-UTC invariant the
    upsert depends on.

    A non-string observed_at (here None, as emitted when an upstream
    omits the timestamp) is used because validate_observations' own
    timestamp check only inspects str values; a non-str reaches the
    coercion block in process_observations, the code path under test.
    """
    processor = DataProcessor()
    bad = dict(_obs(119000.0, "A"), observed_at=None)

    with caplog.at_level("WARNING"):
        written = processor.process_observations(
            station_number=station.station_number, observations=[bad]
        )

    assert written == 0
    assert DischargeObservation.objects.filter(station=station).count() == 0
    assert any(
        "unparseable observed_at" in r.getMessage() for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_unparseable_observed_at_skipped_with_validation_off(station, caplog):
    # validate=False bypasses validate_observations entirely, so this is the
    # only guard left on the timestamp.
    processor = DataProcessor()
    bad = dict(_obs(119000.0, "A"), observed_at="not-a-date")

    with caplog.at_level("WARNING"):
        written = processor.process_observations(
            station_number=station.station_number,
            observations=[bad],
            validate=False,
        )

    assert written == 0
    assert DischargeObservation.objects.filter(station=station).count() == 0
    assert any(
        "unparseable observed_at" in r.getMessage() for r in caplog.records
    )


def test_unparseable_date_does_not_block_the_rest_of_the_batch(station):
    processor = DataProcessor()
    good = _obs(119000.0, "A")
    bad = dict(_obs(94100.0, "A"), observed_at=None)

    processor.process_observations(
        station_number=station.station_number, observations=[good, bad]
    )

    rows = DischargeObservation.objects.filter(station=station)
    assert rows.count() == 1
    assert rows.get().discharge == Decimal("119000.0000")


# -- N5: quality_code must never be None ----------------------------------


def test_explicit_none_quality_code_is_stored_as_empty_string(station):
    # The legacy clients emit the key with an explicit None; the field is a
    # non-nullable CharField(blank=True), so obs.get("quality_code", "")
    # would have handed None to the ORM.
    processor = DataProcessor()
    processor.process_observations(
        station_number=station.station_number,
        observations=[_obs(119000.0, None)],
    )

    assert DischargeObservation.objects.get(station=station).quality_code == ""
