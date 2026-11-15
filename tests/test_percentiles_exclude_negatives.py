"""Negative discharge must never influence percentile ranks or qualification.

Negative daily-mean discharge is physically real at tidally-influenced and
canal gages (e.g. FEEDER CANAL AT GRAND COULEE, NEHALEM RIVER AT NEHALEM near
the estuary) and is now stored rather than dropped (see
tests/test_data_processor_validation.py, N5). But negative flow breaks log
transforms and percentile-rank math, so src/analytics/percentiles.py excludes
it from every SQL site that builds a ranked population or a qualification
count.

compute_percentile_for_date() is chosen here because it is the most directly
testable entry point: a single call, a plain list-of-dicts return value, no
ORM-side mapping tables to build (unlike compute_forecast_percentiles) and no
chunking plumbing (unlike backfill_station_chunk / iter_station_id_chunks).
These tests pin that its result is identical whether negative rows are
present or physically absent from the table, and that a station cannot reach
MIN_HISTORICAL_RECORDS by counting negative rows.
"""

from datetime import date, datetime, timedelta, timezone as dt_timezone

import pytest

from apps.streamflow.models import DischargeObservation, Station
from src.analytics.percentiles import MIN_HISTORICAL_RECORDS, compute_percentile_for_date

EPOCH = datetime(2020, 1, 1, tzinfo=dt_timezone.utc)


def _make_station(number):
    return Station.objects.create(station_number=number, name=f"Test {number}", agency="USGS")


def _bulk_obs(station, values, start=EPOCH):
    DischargeObservation.objects.bulk_create([
        DischargeObservation(
            station=station,
            observed_at=start + timedelta(days=i),
            discharge=v,
            unit="cfs",
            type="daily_mean",
            quality_code="A",
        )
        for i, v in enumerate(values)
    ])


@pytest.fixture
def db_ready(db):
    return None


def test_negative_rows_do_not_shift_percentile_rank(db_ready):
    """Same station, same positive record. One version also has negative
    rows scattered through the record; the other does not. The percentile
    rank and historical_record_count for a fixed target date must be
    identical either way, proving negatives never enter the ranked
    population.
    """
    target_date = (EPOCH + timedelta(days=20)).date()

    clean_station = _make_station("CLEAN001")
    _bulk_obs(clean_station, [float(v) for v in range(1, 41)])  # 40 positive days, 1..40

    dirty_station = _make_station("DIRTY001")
    _bulk_obs(dirty_station, [float(v) for v in range(1, 41)])
    # Negative rows on separate dates, appended after the clean record so
    # they don't collide with existing (station, observed_at, type) rows.
    _bulk_obs(
        dirty_station,
        [-6700.0, -1500.0, -300.0, -0.1, -42.0],
        start=EPOCH + timedelta(days=41),
    )

    clean_result = {
        r["station_id"]: r
        for r in compute_percentile_for_date(target_date, station_ids=[clean_station.id])
    }
    dirty_result = {
        r["station_id"]: r
        for r in compute_percentile_for_date(target_date, station_ids=[dirty_station.id])
    }

    assert clean_station.id in clean_result
    assert dirty_station.id in dirty_result

    clean_row = clean_result[clean_station.id]
    dirty_row = dirty_result[dirty_station.id]

    assert clean_row["percentile_rank"] == dirty_row["percentile_rank"]
    assert clean_row["historical_record_count"] == dirty_row["historical_record_count"]
    assert clean_row["band"] == dirty_row["band"]


def test_station_below_minimum_excluding_negatives_does_not_qualify(db_ready):
    """25 positive daily_mean rows plus 10 negative rows gives 35 raw rows —
    above MIN_HISTORICAL_RECORDS (30) if negatives were counted, but only 25
    once they're excluded. The station must not qualify, i.e. it must not
    appear in compute_percentile_for_date results at all.
    """
    assert MIN_HISTORICAL_RECORDS == 30, (
        "test assumes the documented minimum; update the fixture sizes if this changes"
    )

    station = _make_station("UNDERMIN001")
    target_date = (EPOCH + timedelta(days=5)).date()

    _bulk_obs(station, [float(v) for v in range(1, 26)])  # 25 positive days
    _bulk_obs(
        station,
        [-1.0] * 10,  # 10 negative days -> 35 raw rows, only 25 valid
        start=EPOCH + timedelta(days=26),
    )

    results = compute_percentile_for_date(target_date, station_ids=[station.id])

    assert results == [], (
        "station reached 30 raw rows only by counting negatives and must not qualify"
    )
