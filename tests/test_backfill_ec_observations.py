"""Tests for the Environment Canada observation backfill command.

EC went through the same 5-sigma filter as USGS — it lived in DataProcessor,
which every source uses. Sampled 2026-11-13, 5 of 8 EC stations with long
records held a maximum between 0.48 and 0.82 of the true EC maximum.
"""

from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.streamflow.models import DischargeObservation, Station

PATCH = (
    "apps.streamflow.management.commands.backfill_ec_observations."
    "CanadaClient.get_daily_mean"
)

# Shape verified against the live EC API on 2026-11-13: midnight UTC,
# unit 'cms', plus an extra discharge_cfs key the processor ignores.
EC_ROWS = [
    {
        "observed_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "discharge": 173.0,
        "discharge_cfs": 6109.4431,
        "unit": "cms",
        "type": "daily_mean",
        "quality_code": "A",
    },
    {
        "observed_at": datetime(2020, 1, 2, tzinfo=timezone.utc),
        "discharge": 172.0,
        "discharge_cfs": 6074.1284,
        "unit": "cms",
        "type": "daily_mean",
        "quality_code": "A",
    },
]


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="08LE031", name="Test EC", agency="EC", is_active=True
    )


def test_writes_ec_rows_in_cms(station):
    with patch(PATCH, return_value=EC_ROWS):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--sleep", "0", stdout=StringIO())

    rows = DischargeObservation.objects.filter(station=station, type="daily_mean")
    assert rows.count() == 2
    assert {r.unit for r in rows} == {"cms"}, "EC must stay in cms, never converted"
    assert rows.get(observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc)).discharge \
        == Decimal("173.0000")


def test_observed_at_stays_midnight_utc(station):
    # All 11,733,533 existing EC rows are at 00:00:00 UTC; any other
    # time-of-day would duplicate rather than update.
    with patch(PATCH, return_value=EC_ROWS):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--sleep", "0", stdout=StringIO())

    for r in DischargeObservation.objects.filter(station=station):
        assert r.observed_at.utctimetuple()[3:6] == (0, 0, 0)


def test_truncated_peak_is_restored(station):
    DischargeObservation.objects.create(
        station=station, observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        discharge=Decimal("100.0000"), unit="cms", type="daily_mean",
        quality_code="A",
    )
    with patch(PATCH, return_value=EC_ROWS):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--sleep", "0", stdout=StringIO())

    rows = DischargeObservation.objects.filter(station=station)
    assert rows.count() == 2, "existing row must update in place, not duplicate"
    assert rows.get(observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc)).discharge \
        == Decimal("173.0000")


def test_dry_run_writes_nothing(station):
    with patch(PATCH, return_value=EC_ROWS):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--sleep", "0", "--dry-run", stdout=StringIO())

    assert DischargeObservation.objects.count() == 0


def test_a_usgs_station_is_not_processed(db):
    Station.objects.create(station_number="12200500", name="U", agency="USGS")
    out = StringIO()
    with patch(PATCH, return_value=EC_ROWS) as fetch:
        call_command("backfill_ec_observations", "--stations", "12200500",
                     "--sleep", "0", stdout=out)

    assert not fetch.called, "the EC command must not touch USGS stations"
    assert "12200500" in out.getvalue()


def test_requires_a_station_selection(db):
    with pytest.raises(CommandError):
        call_command("backfill_ec_observations", stdout=StringIO())


def test_end_without_start_is_rejected(station):
    with pytest.raises(CommandError):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--end", "2020-01-05", stdout=StringIO())
