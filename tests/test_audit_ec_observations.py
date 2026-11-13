"""Tests for the Environment Canada observation audit command.

Mirrors tests/test_audit_usgs_observations.py (a pinned regression proof
that must not be edited), but against the EC command: unit="cms", the
CanadaClient patch target, and the --stations/--station-list-csv/--all-ec
flag names. The shared comparison/reporting core lives in
apps/streamflow/management/audit_runner.py and is exercised identically by
both test files; this file does not re-derive that core, only pins the EC
command's own wiring (unit filter, fetch closure, flag names) plus a
representative slice of the shared behaviour so a regression in either
command's wiring is caught from this side too.
"""

import csv
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.streamflow.models import DischargeObservation, Station


def not_all_clear():
    """The command exits nonzero unless the run is genuinely clean."""
    return pytest.raises(CommandError, match="not all-clear")


API_ROWS = [
    {
        "observed_at": datetime(2021, 11, 15, tzinfo=timezone.utc),
        "discharge": 941.0,
        "unit": "cms",
        "type": "daily_mean",
        "quality_code": "A",
    },
    {
        "observed_at": datetime(2021, 11, 16, tzinfo=timezone.utc),
        "discharge": 1190.0,
        "unit": "cms",
        "type": "daily_mean",
        "quality_code": "A",
    },
]

PATCH_TARGET = (
    "apps.streamflow.management.commands.audit_ec_observations."
    "CanadaClient.get_daily_mean"
)


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="08MF005", name="Fraser", agency="EC", is_active=True
    )


def _row(station, day, value, unit="cms", quality_code="A"):
    return DischargeObservation.objects.create(
        station=station,
        observed_at=datetime(2021, 11, day, tzinfo=timezone.utc),
        discharge=Decimal(str(value)),
        unit=unit,
        type="daily_mean",
        quality_code=quality_code,
    )


def _api_row(day, value):
    return {
        "observed_at": datetime(2021, 11, day, tzinfo=timezone.utc),
        "discharge": value,
        "unit": "cms",
        "type": "daily_mean",
        "quality_code": "A",
    }


def test_clean_station_reports_no_problems_and_does_not_raise(station):
    _row(station, 15, 941.0)
    _row(station, 16, 1190.0)
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command("audit_ec_observations", "--stations", "08MF005", stdout=out)

    assert "missing=0" in out.getvalue()
    assert "diff=0" in out.getvalue()


def test_in_span_missing_day_is_counted_and_raises(station, tmp_path):
    _row(station, 14, 900.0)
    _row(station, 16, 1190.0)
    api_rows = [_api_row(14, 900.0), _api_row(15, 941.0), _api_row(16, 1190.0)]
    report = tmp_path / "audit.csv"

    with patch(PATCH_TARGET, return_value=api_rows), not_all_clear():
        call_command(
            "audit_ec_observations",
            "--stations", "08MF005",
            "--report", str(report),
            stdout=StringIO(),
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert rows[0]["n_missing_in_db_span"] == "1"
    assert rows[0]["n_missing_after_db_last"] == "0"
    assert rows[0]["n_missing"] == "1"


def test_day_after_last_stored_row_lands_in_missing_after_db_last(station, tmp_path):
    """Mirrors audit_usgs_observations'
    test_bounding_excludes_dates_before_db_min_includes_after_db_max: tail
    staleness (missing_after_db_last) alone does not fail all_ok - only an
    in-span gap or a value difference does - so this run does not raise."""
    _row(station, 15, 941.0)
    api_rows = [_api_row(15, 941.0), _api_row(16, 1190.0)]
    report = tmp_path / "audit.csv"

    with patch(PATCH_TARGET, return_value=api_rows):
        call_command(
            "audit_ec_observations",
            "--stations", "08MF005",
            "--report", str(report),
            stdout=StringIO(),
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert rows[0]["n_missing_in_db_span"] == "0"
    assert rows[0]["n_missing_after_db_last"] == "1"
    assert rows[0]["n_missing"] == "1"


def test_value_difference_beyond_tolerance_is_counted(station):
    """A difference beyond max(0.5, 0.5%) of the source value: at 1190 cms
    the relative threshold is 5.95 cms, so a 6 cms difference exceeds it."""
    _row(station, 15, 941.0)
    _row(station, 16, 1184.0)  # API says 1190.0 - a 6 cms difference
    with patch(PATCH_TARGET, return_value=API_ROWS), not_all_clear():
        out = StringIO()
        call_command("audit_ec_observations", "--stations", "08MF005", stdout=out)

    assert "diff=1" in out.getvalue()


def test_value_difference_inside_tolerance_is_not_counted(station):
    """A 5 cms difference at 1190 cms is inside the 5.95 cms (0.5%)
    tolerance and must not count."""
    _row(station, 15, 941.0)
    _row(station, 16, 1185.0)  # API says 1190.0 - a 5 cms difference
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command("audit_ec_observations", "--stations", "08MF005", stdout=out)

    assert "diff=0" in out.getvalue()


def test_cfs_unit_row_is_excluded_by_the_unit_filter(station, tmp_path):
    """The unit="cms" filter is load-bearing - a cfs row compared against a
    cms API value would read as a false value difference and corrupt the
    verdict. This is the EC analogue of the USGS audit's
    test_non_cfs_row_is_not_counted_as_a_value_difference, and must
    genuinely fail if the unit filter in audit_runner.run_audit is removed
    or widened.

    The cfs row sits on day 15, between two cms rows, so it is inside the
    comparison span. unique_observation_idx is (station, observed_at,
    type), so a cms and a cfs row cannot share a date - day 15 has only the
    cfs row. With the filter, day 15 is simply absent from the DB side and
    shows up as one in-span missing day; without it, day 15 would compare
    33,230 (cfs, 941 cms * 35.3147) against 941 (cms) and read as a huge
    value difference instead.
    """
    _row(station, 14, 900.0)
    _row(station, 16, 1190.0)
    DischargeObservation.objects.create(
        station=station,
        observed_at=datetime(2021, 11, 15, tzinfo=timezone.utc),
        discharge=Decimal("33230.0"),  # 941 cms expressed in cfs
        unit="cfs",
        type="daily_mean",
        quality_code="A",
    )

    report = tmp_path / "audit.csv"
    out = StringIO()
    api_rows = [_api_row(14, 900.0), _api_row(15, 941.0), _api_row(16, 1190.0)]
    with patch(PATCH_TARGET, return_value=api_rows), not_all_clear():
        call_command(
            "audit_ec_observations",
            "--stations", "08MF005",
            "--report", str(report),
            stdout=out,
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert rows[0]["n_value_diff"] == "0", "a cfs row must never be compared"
    assert rows[0]["n_missing_in_db_span"] == "1"
    assert rows[0]["n_db_rows"] == "2"
    assert "duplicate" not in out.getvalue()


def test_report_is_written_when_the_run_ends_in_commanderror(station, tmp_path):
    """The report must be written inside the finally even when the run ends
    in CommandError (the not-all-clear exit), not only on a clean exit."""
    _row(station, 14, 900.0)
    _row(station, 16, 1190.0)
    api_rows = [_api_row(14, 900.0), _api_row(15, 941.0), _api_row(16, 1190.0)]
    report = tmp_path / "audit.csv"

    with patch(PATCH_TARGET, return_value=api_rows), not_all_clear():
        call_command(
            "audit_ec_observations",
            "--stations", "08MF005",
            "--report", str(report),
            stdout=StringIO(),
        )

    text = report.read_text()
    assert "station_number" in text
    assert "08MF005" in text


def test_bare_invocation_names_ec_flags(db):
    """No --stations/--station-list-csv/--all-ec means resolve_gages raises,
    and the error must name this command's own flags rather than the USGS
    command's --gages/--gage-list-csv."""
    with pytest.raises(CommandError, match="--stations"):
        call_command("audit_ec_observations", stdout=StringIO())


def test_not_in_db_station_csv_contents(db, tmp_path):
    report = tmp_path / "audit.csv"
    with not_all_clear():
        call_command(
            "audit_ec_observations",
            "--stations", "00NOTREAL",
            "--report", str(report),
            stdout=StringIO(),
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert len(rows) == 1
    assert rows[0]["station_number"] == "00NOTREAL"
    assert rows[0]["status"] == "not_in_db"
