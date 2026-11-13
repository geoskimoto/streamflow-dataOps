"""Tests for the observation audit command."""

from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.streamflow.models import DischargeObservation, Station

API_ROWS = [
    {
        "observed_at": datetime(2021, 11, 15, tzinfo=timezone.utc),
        "discharge": 94100.0,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A, q, e",
    },
    {
        "observed_at": datetime(2021, 11, 16, tzinfo=timezone.utc),
        "discharge": 119000.0,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A, q, e",
    },
]

PATCH_TARGET = (
    "apps.streamflow.management.commands.audit_usgs_observations."
    "USGSWaterDataClient.get_daily_mean"
)


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500", name="Skagit", agency="USGS", is_active=True
    )


def _row(station, day, value, quality_code="A"):
    return DischargeObservation.objects.create(
        station=station,
        observed_at=datetime(2021, 11, day, tzinfo=timezone.utc),
        discharge=Decimal(str(value)),
        unit="cfs",
        type="daily_mean",
        quality_code=quality_code,
    )


def test_reports_missing_days(station):
    _row(station, 15, 94100.0)
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "missing=1" in out.getvalue()


def test_reports_value_differences(station):
    _row(station, 15, 94100.0)
    _row(station, 16, 95000.0)
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "missing=0" in out.getvalue()
    assert "diff=1" in out.getvalue()


def test_clean_gage_reports_no_problems(station):
    _row(station, 15, 94100.0)
    _row(station, 16, 119000.0)
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "missing=0" in out.getvalue()
    assert "diff=0" in out.getvalue()


def test_report_csv_is_written(station, tmp_path):
    _row(station, 15, 94100.0)
    report = tmp_path / "audit.csv"
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=StringIO(),
        )

    text = report.read_text()
    assert "usgs_id" in text
    assert "12200500" in text


def test_bare_invocation_raises_command_error(db):
    """No --gages/--gage-list-csv means resolve_gages raises; --all-usgs is
    not a supported flag for this command."""
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("audit_usgs_observations", stdout=StringIO())


def test_fetch_failure_does_not_abort_remaining_gages(station):
    """Lesson 1: one bad gage must not abort the run - a fetch failure on one
    gage is reported and the next gage is still audited.

    connection.close() is mocked out here for the same reason it is in
    test_backfill_usgs_observations.py: under pytest-django's atomic-wrapped
    `db` fixture, a real close() mid-test marks the connection
    closed_in_transaction (Django only nulls the connection outside an
    atomic block), so the next real query in the *same test* raises
    InterfaceError - a test-isolation artifact, not a production bug.
    """
    other = Station.objects.create(
        station_number="99999999", name="Other", agency="USGS", is_active=True
    )
    _row(other, 15, 94100.0)

    out = StringIO()
    with patch(
        PATCH_TARGET, side_effect=[RuntimeError("boom"), API_ROWS]
    ), patch(
        "apps.streamflow.management.commands.audit_usgs_observations.connection.close"
    ):
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500,99999999",
            "--sleep", "0",
            stdout=out,
        )

    output = out.getvalue()
    assert "12200500" in output and "failed" in output
    assert "missing=" in output  # the second, healthy gage still got audited


def test_sleep_fires_on_failure_and_skip_paths(station):
    """Lesson 2: the inter-gage pacing sleep must fire on every path -
    failures and skips (not-in-db) alike - not just on success.

    connection.close() is mocked out for the same pytest-django
    atomic-block reason as test_fetch_failure_does_not_abort_remaining_gages
    above.
    """
    unknown_gage = "00000000"  # not in DB -> "not in stations table" skip

    with patch(
        PATCH_TARGET, side_effect=RuntimeError("boom")
    ), patch(
        "apps.streamflow.management.commands.audit_usgs_observations.connection.close"
    ), patch(
        "apps.streamflow.management.commands.audit_usgs_observations.time.sleep"
    ) as mock_sleep:
        call_command(
            "audit_usgs_observations",
            "--gages", f"12200500,{unknown_gage}",
            "--sleep", "2.5",
            stdout=StringIO(),
        )

    # Two gages, sleep fires between them regardless of outcome.
    assert mock_sleep.call_count == 1
    mock_sleep.assert_called_with(2.5)


def test_report_written_when_loop_raises(station, tmp_path):
    """Lesson 3: with --report given, the report must still be written if the
    loop exits early via an exception (try/finally), so a long run's partial
    results are not lost."""
    report = tmp_path / "audit.csv"

    def side_effect(station_number, start_date, *args, **kwargs):
        raise KeyboardInterrupt("simulated ctrl-c")

    with pytest.raises(KeyboardInterrupt):
        with patch(PATCH_TARGET, side_effect=side_effect):
            call_command(
                "audit_usgs_observations",
                "--gages", "12200500",
                "--report", str(report),
                stdout=StringIO(),
            )

    text = report.read_text()
    assert "usgs_id" in text
