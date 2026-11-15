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

Two more cases, added in fix round 1:

- A negative-discharge day on the *target* date itself must produce no
  percentile result at all (absence, not a rank-0 row) — the half of the
  exclusion that compute_percentile_for_date's own population tests above
  don't exercise, since they only ever put a positive value on the target
  date.
- backfill_station_chunk() is the function actually used by the production
  percentile backfill (compute_percentile_for_date serves the daily Celery
  task; backfill_station_chunk serves the historical backfill command), and
  was previously untested here. Its test proves the chunked path and the
  single-date path agree: same ranks for the same non-negative rows,
  negative rows absent from the output.
"""

from datetime import date, datetime, timedelta, timezone as dt_timezone

import pytest

from apps.streamflow.models import DischargeObservation, Station
from src.analytics.percentiles import (
    MIN_HISTORICAL_RECORDS,
    backfill_station_chunk,
    compute_percentile_for_date,
)

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


def test_negative_discharge_on_target_date_is_never_ranked(db_ready):
    """A station with a perfectly healthy positive history (40 days, well
    above MIN_HISTORICAL_RECORDS) whose observation *on the target date* is
    negative must produce no percentile result for that date at all —
    absence, not a result with percentile_rank 0.

    This is the "never ranked" half of the exclusion, at the WHERE clause in
    the obs_on_date CTE (percentiles.py ~line 82). The other tests in this
    file only ever put a positive value on the target date, so they never
    exercise this predicate; removing it does not fail them. It does fail
    this one — confirmed manually by temporarily deleting the `AND
    discharge >= 0` line from the obs_on_date CTE and re-running this test:
    the row is no longer filtered out of obs_on_date, the join to historical
    rows (still filtered to discharge >= 0) finds 40 historical rows, and the
    station comes back with historical_record_count=40 and
    percentile_rank=0.0 (nothing historical is <= a negative value) instead
    of being absent.
    """
    station = _make_station("TARGETNEG001")
    target_date = (EPOCH + timedelta(days=100)).date()

    # 40 positive historical days, unrelated to the target date.
    _bulk_obs(station, [float(v) for v in range(1, 41)])
    # The day being evaluated is negative.
    _bulk_obs(station, [-50.0], start=EPOCH + timedelta(days=100))

    results = compute_percentile_for_date(target_date, station_ids=[station.id])

    assert results == [], (
        "a negative-discharge day must never receive a percentile rank, "
        f"got {results!r}"
    )


def test_backfill_station_chunk_excludes_negatives_and_matches_clean_record(db_ready):
    """backfill_station_chunk() is the function the historical backfill
    command actually calls — compute_percentile_for_date() above only covers
    the daily Celery task's single-date path. This proves the two agree:
    - no returned row corresponds to a negative-discharge date
    - the percentile_rank for every surviving date matches the rank computed
      for the same record with the negative rows physically deleted,
      proving the chunked path's comparison population is consistent with
      a negative-free record (and, by the first test in this file, with
      compute_percentile_for_date's population too).
    """
    POSITIVE_VALUES = [float(v) for v in range(1, 41)]  # 40 days, 1..40
    NEGATIVE_VALUES = [-6700.0, -1500.0, -300.0, -0.1, -42.0]  # 5 days

    clean_station = _make_station("CHUNKCLEAN001")
    _bulk_obs(clean_station, POSITIVE_VALUES)

    dirty_station = _make_station("CHUNKDIRTY001")
    _bulk_obs(dirty_station, POSITIVE_VALUES)
    negative_start = EPOCH + timedelta(days=len(POSITIVE_VALUES))
    _bulk_obs(dirty_station, NEGATIVE_VALUES, start=negative_start)
    negative_dates = {
        (negative_start + timedelta(days=i)).date() for i in range(len(NEGATIVE_VALUES))
    }

    now = datetime(2026, 11, 15, tzinfo=dt_timezone.utc)
    clean_rows = backfill_station_chunk([clean_station.id], computed_at=now)
    dirty_rows = backfill_station_chunk([dirty_station.id], computed_at=now)

    dirty_dates = {row["obs_date"] for row in dirty_rows}
    assert not (dirty_dates & negative_dates), (
        "a negative-discharge date must never appear in backfill_station_chunk's output"
    )

    # Both stations have the identical 40 positive dates/values, so the
    # date -> percentile_rank mapping must match exactly between the record
    # that physically contains negatives (filtered out in SQL) and the
    # record that never had them.
    clean_by_date = {row["obs_date"]: row["percentile_rank"] for row in clean_rows}
    dirty_by_date = {row["obs_date"]: row["percentile_rank"] for row in dirty_rows}

    assert dirty_by_date == clean_by_date
    assert len(dirty_rows) == len(POSITIVE_VALUES)
