"""Tests for the USGS observation backfill command."""

from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.utils import OperationalError

from apps.streamflow.management.commands.backfill_usgs_observations import Command
from apps.streamflow.models import DischargeObservation, Station


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500",
        name="SKAGIT RIVER NEAR MOUNT VERNON, WA",
        agency="USGS",
        is_active=True,
    )


@pytest.fixture
def other_station(db):
    return Station.objects.create(
        station_number="13317000",
        name="WHITE RIVER NEAR BUCKLEY, WA",
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
            "--sleep", "0",
            stdout=out,
        )

    assert "99999999" in out.getvalue()
    assert DischargeObservation.objects.filter(station=station).count() == 2


def test_fetch_failure_does_not_abort_remaining_gages(station, other_station):
    """A fetch failure on one gage must not prevent a later gage's rows
    from landing — a single-gage run can't distinguish "continued" from
    "there was nothing after it to abort".

    connection.close() (added for Important 9) is mocked out here: under
    pytest-django's atomic-wrapped `db` fixture, a real close() mid-test
    marks the connection closed_in_transaction rather than resetting it
    (Django only nulls `self.connection` outside an atomic block), so the
    next real query in the *same test* raises InterfaceError. That is a
    test-isolation artifact, not a production bug — see
    test_dropped_connection_is_reset_so_the_next_gage_reconnects, which
    exercises the real close() call directly. This test's own focus is
    failure isolation, not the reconnect mechanism.
    """
    out = StringIO()
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        side_effect=[RuntimeError("boom"), CREST],
    ), patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "connection.close",
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", f"{station.station_number},{other_station.station_number}",
            "--sleep", "0",
            stdout=out,
        )

    assert "boom" in out.getvalue()
    assert DischargeObservation.objects.filter(station=other_station).count() == 2


def test_process_observations_failure_does_not_abort_remaining_gages(
    station, other_station
):
    """A DB error raised from process_observations (e.g. a dropped
    connection) on one gage must not abort the remaining gages.

    connection.close() is mocked out for the same reason documented in
    test_fetch_failure_does_not_abort_remaining_gages above: a real close()
    mid-test breaks pytest-django's atomic-wrapped `db` fixture, not the
    command. The reconnect mechanism itself has its own dedicated test.
    """
    out = StringIO()
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ), patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "DataProcessor.process_observations",
        side_effect=[RuntimeError("db boom"), 2],
    ), patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "connection.close",
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", f"{station.station_number},{other_station.station_number}",
            "--sleep", "0",
            stdout=out,
        )

    assert "db boom" in out.getvalue()
    assert f"{other_station.station_number}: fetched 2, wrote 2" in out.getvalue()
    assert "Done. 2 gages processed, 1 failed." in out.getvalue()


def test_dropped_connection_is_reset_so_the_next_gage_reconnects(
    station, other_station
):
    """A real OperationalError (dropped connection) on one gage must not
    poison every remaining gage with InterfaceError: connection.close()
    has to run so Django reconnects lazily on the next query.

    process_observations is only faked for the failing first call; the
    second call runs the real method (via a throwaway DataProcessor
    instance, since the patch target isn't bound to `self`) so the test can
    assert the second gage's rows actually land in the database rather than
    asserting against a mocked return value.
    """
    from src.acquisition.data_processor import DataProcessor as RealDataProcessor

    real_process_observations = RealDataProcessor.process_observations
    call_count = {"n": 0}

    def flaky(*, station_number, observations, validate=True):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OperationalError("server closed the connection unexpectedly")
        return real_process_observations(
            RealDataProcessor(),
            station_number=station_number,
            observations=observations,
            validate=validate,
        )

    out = StringIO()
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ), patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "DataProcessor.process_observations",
        side_effect=flaky,
    ), patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "connection.close",
    ) as mock_close:
        call_command(
            "backfill_usgs_observations",
            "--gages", f"{station.station_number},{other_station.station_number}",
            "--sleep", "0",
            stdout=out,
        )

    assert mock_close.called
    assert "server closed the connection unexpectedly" in out.getvalue()
    assert DischargeObservation.objects.filter(station=other_station).count() == 2


def test_sleep_fires_on_the_failure_path_too(station, other_station):
    """Pins Important 4's fix: a failed gage must still pace before moving
    on, not just a successful one."""
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        side_effect=[RuntimeError("boom"), CREST],
    ), patch(
        "apps.streamflow.management.commands.backfill_usgs_observations.time.sleep"
    ) as mock_sleep:
        call_command(
            "backfill_usgs_observations",
            "--gages", f"{station.station_number},{other_station.station_number}",
            stdout=StringIO(),
        )

    mock_sleep.assert_called_once_with(1.0)


def test_requires_a_gage_selection(db):
    with pytest.raises(CommandError):
        call_command("backfill_usgs_observations", stdout=StringIO())


def test_report_written_even_on_crash_or_interrupt(station, other_station, tmp_path):
    """The report must reflect whatever completed before an interrupt, not
    just a clean end-of-loop exit — it's the only resume state a multi-hour
    unattended run has."""
    report_path = tmp_path / "report.csv"
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ), patch(
        "apps.streamflow.management.commands.backfill_usgs_observations.time.sleep",
        side_effect=KeyboardInterrupt,
    ):
        with pytest.raises(KeyboardInterrupt):
            call_command(
                "backfill_usgs_observations",
                "--gages",
                f"{station.station_number},{other_station.station_number}",
                "--report", str(report_path),
                stdout=StringIO(),
            )

    assert report_path.exists()
    content = report_path.read_text()
    assert station.station_number in content
    # The interrupt fired in the pacing sleep after gage 1 completed and
    # before gage 2 was attempted.
    assert other_station.station_number not in content


def test_done_sidecar_contains_only_successfully_completed_gages(
    station, other_station, tmp_path
):
    """connection.close() is mocked out for the same pytest-django
    atomic-block reason documented above; this test's focus is the
    .done.txt sidecar contents, not the reconnect mechanism."""
    report_path = tmp_path / "report.csv"
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        side_effect=[RuntimeError("boom"), CREST],
    ), patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "connection.close",
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", f"{station.station_number},{other_station.station_number}",
            "--report", str(report_path),
            "--sleep", "0",
            stdout=StringIO(),
        )

    done_path = Path(f"{report_path}.done.txt")
    assert done_path.exists()
    assert done_path.read_text().splitlines() == [other_station.station_number]


def test_dry_run_does_not_create_done_sidecar(station, tmp_path):
    report_path = tmp_path / "report.csv"
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", station.station_number,
            "--report", str(report_path),
            "--dry-run",
            stdout=StringIO(),
        )

    assert not Path(f"{report_path}.done.txt").exists()


def test_fetch_with_no_observations_is_reported_as_no_data(station, tmp_path):
    report_path = tmp_path / "report.csv"
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=[],
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            "--report", str(report_path),
            stdout=StringIO(),
        )

    content = report_path.read_text()
    assert "no_data" in content
    assert DischargeObservation.objects.filter(station=station).count() == 0


def test_parse_date_valid():
    assert Command._parse_date("2021-11-16") == datetime(
        2021, 11, 16, tzinfo=timezone.utc
    )


def test_parse_date_malformed_raises():
    with pytest.raises(CommandError, match="Bad date"):
        Command._parse_date("11/16/2021")


def test_end_without_start_raises(station):
    """N2: --end alone was accepted but ignored by the client, so an
    operator scoping a run to old dates would get a full-record overwrite up
    to today instead."""
    with pytest.raises(CommandError, match="--end requires --start"):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            "--end", "2021-11-20",
            stdout=StringIO(),
        )


def test_start_without_end_is_allowed(station):
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            "--start", "2021-11-01",
            stdout=StringIO(),
        )

    assert DischargeObservation.objects.filter(station=station).count() == 2


def test_start_after_end_raises(station):
    with pytest.raises(CommandError, match="--start"):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            "--start", "2021-11-20",
            "--end", "2021-11-10",
            stdout=StringIO(),
        )
