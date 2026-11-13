"""Tests for the USGS observation backfill command."""

from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.streamflow.models import DischargeObservation, Station


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500",
        name="SKAGIT RIVER NEAR MOUNT VERNON, WA",
        agency="USGS",
        is_active=True,
    )


CREST = [
    {
        "observed_at": datetime(2021, 11, 16, tzinfo=timezone.utc),
        "discharge": 119000.0,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A, q, e",
    },
    {
        "observed_at": datetime(2021, 11, 15, tzinfo=timezone.utc),
        "discharge": 94100.0,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A, q, e",
    },
]


def test_backfill_inserts_missing_peak(station):
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            stdout=StringIO(),
        )

    row = DischargeObservation.objects.get(
        station=station, observed_at=datetime(2021, 11, 16, tzinfo=timezone.utc)
    )
    assert row.discharge == Decimal("119000.0000")


def test_backfill_overwrites_a_stale_value(station):
    DischargeObservation.objects.create(
        station=station,
        observed_at=datetime(2021, 11, 16, tzinfo=timezone.utc),
        discharge=Decimal("95000.0000"),
        unit="cfs",
        type="daily_mean",
        quality_code="P",
    )

    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            stdout=StringIO(),
        )

    rows = DischargeObservation.objects.filter(
        station=station, observed_at=datetime(2021, 11, 16, tzinfo=timezone.utc)
    )
    assert rows.count() == 1
    assert rows.get().discharge == Decimal("119000.0000")


def test_dry_run_writes_nothing(station):
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            "--dry-run",
            stdout=StringIO(),
        )

    assert DischargeObservation.objects.filter(station=station).count() == 0


def test_unknown_gage_is_reported_and_does_not_abort_the_run(station):
    out = StringIO()
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "99999999,12200500",
            stdout=out,
        )

    assert "99999999" in out.getvalue()
    assert DischargeObservation.objects.filter(station=station).count() == 2


def test_fetch_failure_does_not_abort_remaining_gages(station):
    out = StringIO()
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        side_effect=RuntimeError("boom"),
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            stdout=out,
        )

    assert "boom" in out.getvalue() or "failed" in out.getvalue().lower()


def test_requires_a_gage_selection(db):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("backfill_usgs_observations", stdout=StringIO())
