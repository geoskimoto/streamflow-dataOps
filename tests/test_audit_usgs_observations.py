"""Tests for the observation audit command."""

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
    """B4: the command exits nonzero unless the run is genuinely clean.

    Every test below whose scenario has a failure, a skip, a missing in-span
    day, or a value difference wraps its call in this, so the nonzero exit is
    asserted everywhere it is expected rather than only in one place.
    """
    return pytest.raises(CommandError, match="not all-clear")

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


def _api_row(day, value):
    return {
        "observed_at": datetime(2021, 11, day, tzinfo=timezone.utc),
        "discharge": value,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A",
    }


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
    with patch(PATCH_TARGET, return_value=API_ROWS), not_all_clear():
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
    ), not_all_clear():
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
    ) as mock_sleep, not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", f"12200500,{unknown_gage}",
            "--sleep", "2.5",
            stdout=StringIO(),
        )

    # Two gages, sleep fires between them regardless of outcome.
    assert mock_sleep.call_count == 1
    mock_sleep.assert_called_with(2.5)


# -- Fix round 1 -------------------------------------------------------------
#
# Review findings on the first pass:
#   Important 1 - the summary line could print in style.SUCCESS even when
#       every gage failed, since `rows` includes failed/skipped entries.
#   Important 2 - the "no data" branch was silent per gage and conflated two
#       distinct causes (nothing stored vs. API returned nothing).
#   Design improvement - split "missing" into n_missing_in_db_span (the
#       figure comparable to the 46,701 pre-backfill baseline, which used a
#       two-sided bound) and n_missing_after_db_last (tail staleness, which
#       the lower-bound-only design intentionally surfaces).
#   Minor 3 - the DB query didn't filter unit="cfs", so a non-cfs daily_mean
#       row could be compared against a cfs API value.
#   Untested branches - the bounding rule itself, the tolerance boundaries,
#       mixed-outcome summaries, and not_in_db CSV contents.


def test_all_gages_failed_summary_is_not_success_styled(station):
    """Important 1: a run where the only gage fails must not print a
    success-styled clean summary, and must surface the failure count.

    force_color=True is passed so style.SUCCESS/WARNING/ERROR render real
    ANSI codes we can assert on directly - Django's color_style(force_color
    =True) renders SUCCESS as '\\x1b[32;1m...\\x1b[0m' (green) and WARNING as
    '\\x1b[33;1m...\\x1b[0m' (yellow); without force_color, style methods are
    no-ops under a non-tty stdout and the distinction would be invisible to
    this test.

    connection.close() is mocked for the same pytest-django atomic-block
    reason documented on the other failure-path tests in this file.
    """
    out = StringIO()
    with patch(PATCH_TARGET, side_effect=RuntimeError("boom")), patch(
        "apps.streamflow.management.commands.audit_usgs_observations.connection.close"
    ), not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--sleep", "0",
            stdout=out,
            force_color=True,
        )

    output = out.getvalue()
    assert "1 failed" in output
    assert "\x1b[32;1m" not in output  # SUCCESS green must not wrap this summary
    assert "\x1b[33;1m" in output  # WARNING yellow wraps it instead


def test_mixed_outcome_summary_counts(station):
    """Important 1 (continued): the summary tallies every outcome, not just
    ok/failed - a realistic multi-gage run mixes ok, failed, no_db_data, and
    not_in_db."""
    no_db_station = Station.objects.create(
        station_number="11111111", name="NoDbData", agency="USGS", is_active=True
    )
    failing_station = Station.objects.create(
        station_number="33333333", name="Failing", agency="USGS", is_active=True
    )
    _row(station, 15, 94100.0)
    _row(failing_station, 15, 1.0)

    def side_effect(station_number, start_date, *args, **kwargs):
        if station_number == "33333333":
            raise RuntimeError("boom")
        return API_ROWS

    out = StringIO()
    with patch(PATCH_TARGET, side_effect=side_effect), patch(
        "apps.streamflow.management.commands.audit_usgs_observations.connection.close"
    ), not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500,11111111,22222222,33333333",
            "--sleep", "0",
            stdout=out,
        )

    output = out.getvalue()
    assert "1 ok" in output
    assert "1 failed" in output
    assert "1 no_db_data" in output
    assert "1 not_in_db" in output


def test_no_db_data_is_reported_per_gage(station, tmp_path):
    """Important 2: a station with nothing stored must print a per-gage
    line (not stay silent like the old combined "no_data" branch did), and
    the report must label the cause distinctly as no_db_data."""
    report = tmp_path / "audit.csv"
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS), not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=out,
        )

    assert "no stored" in out.getvalue()
    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert rows[0]["status"] == "no_db_data"


def test_no_api_data_is_reported_per_gage(station, tmp_path):
    """Important 2 (continued): the API returning nothing is a distinct
    cause from no_db_data and must be labelled no_api_data."""
    _row(station, 15, 94100.0)
    report = tmp_path / "audit.csv"
    out = StringIO()
    with patch(PATCH_TARGET, return_value=[]), not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=out,
        )

    assert "USGS API returned no data" in out.getvalue()
    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert rows[0]["status"] == "no_api_data"


def test_not_in_db_gage_csv_contents(db, tmp_path):
    """Untested branch (c): a not_in_db gage's CSV row carries only usgs_id
    and status - no stale numeric fields from a comparison that never ran."""
    report = tmp_path / "audit.csv"
    with not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", "00000000",
            "--report", str(report),
            stdout=StringIO(),
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert len(rows) == 1
    assert rows[0]["usgs_id"] == "00000000"
    assert rows[0]["status"] == "not_in_db"
    assert rows[0]["n_missing"] == ""


def test_missing_days_split_into_in_span_and_after_last(station, tmp_path):
    """Design improvement: an in-span gap (between the first and last stored
    date) and a post-last-row gap (tail staleness) must land in different
    columns, with n_missing equal to their sum."""
    _row(station, 10, 100.0)
    _row(station, 12, 100.0)
    api_rows = [
        _api_row(10, 100.0),
        _api_row(11, 100.0),  # gap inside the db span [10, 12]
        _api_row(12, 100.0),
        _api_row(14, 100.0),  # gap after the db's last row (12)
    ]
    report = tmp_path / "audit.csv"
    with patch(PATCH_TARGET, return_value=api_rows), not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=StringIO(),
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    row = rows[0]
    assert row["n_missing_in_db_span"] == "1"
    assert row["n_missing_after_db_last"] == "1"
    assert row["n_missing"] == "2"


def test_bounding_excludes_dates_before_db_min_includes_after_db_max(
    station, tmp_path
):
    """Untested branch (a): deleting the lower-bound condition leaves the
    other tests green, so this pins both halves directly - a date earlier
    than the DB's only stored date must not be counted at all, while a date
    later must be counted in n_missing_after_db_last."""
    _row(station, 15, 94100.0)
    api_rows = [_api_row(14, 90000.0), _api_row(16, 95000.0)]
    report = tmp_path / "audit.csv"
    with patch(PATCH_TARGET, return_value=api_rows):
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=StringIO(),
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    row = rows[0]
    # Day 14 (before db min) contributes nothing; only day 16 (after db max)
    # is counted, and only in the after-last-row column.
    assert row["n_missing"] == "1"
    assert row["n_missing_in_db_span"] == "0"
    assert row["n_missing_after_db_last"] == "1"
    assert row["first_missing"] == "2021-11-16"


def test_tolerance_abs_floor_low_flow_not_counted(station):
    """Untested branch (b): at low flow the 0.5 cfs absolute floor dominates
    the 0.5% relative threshold - a 0.4 cfs difference must not count."""
    _row(station, 15, 2.4)
    with patch(PATCH_TARGET, return_value=[_api_row(15, 2.0)]):
        out = StringIO()
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "diff=0" in out.getvalue()


def test_tolerance_abs_floor_low_flow_counted(station):
    """Untested branch (b): a 0.6 cfs difference at the same low flow must
    count, since it exceeds the 0.5 cfs absolute floor."""
    _row(station, 15, 2.6)
    with patch(PATCH_TARGET, return_value=[_api_row(15, 2.0)]), not_all_clear():
        out = StringIO()
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "diff=1" in out.getvalue()


def test_tolerance_relative_threshold_high_flow_just_under_not_counted(station):
    """Untested branch (b): at high flow (100,000 cfs) the 0.5% relative
    threshold is 500 cfs; a 499 cfs difference must not count."""
    _row(station, 15, 100000.0 - 499.0)
    with patch(PATCH_TARGET, return_value=[_api_row(15, 100000.0)]):
        out = StringIO()
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "diff=0" in out.getvalue()


def test_tolerance_relative_threshold_high_flow_just_over_counted(station):
    """Untested branch (b): a 501 cfs difference at the same high flow must
    count, since it exceeds the 500 cfs relative threshold."""
    _row(station, 15, 100000.0 - 501.0)
    with patch(PATCH_TARGET, return_value=[_api_row(15, 100000.0)]), not_all_clear():
        out = StringIO()
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "diff=1" in out.getvalue()


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


# -- Fix round 2 (final whole-branch review) ---------------------------------


def test_zero_discrepancy_run_is_success_styled_and_does_not_raise(station):
    """B4: `all_ok` was `counts["ok"] == len(rows)`, so a gage with 5,000
    missing days and 3,000 value differences still printed a green SUCCESS
    summary. Only a genuinely clean run may be SUCCESS-styled - and it must
    not raise."""
    _row(station, 15, 94100.0)
    _row(station, 16, 119000.0)
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            stdout=out,
            force_color=True,
        )

    output = out.getvalue()
    assert "\x1b[32;1m" in output  # SUCCESS green
    assert "\x1b[33;1m" not in output


def test_in_span_missing_days_are_not_success_styled_and_raise(station, tmp_path):
    """B4: an in-span gap is a failed restoration, not a clean audit."""
    _row(station, 14, 90000.0)
    _row(station, 16, 119000.0)
    report = tmp_path / "audit.csv"
    out = StringIO()
    api_rows = [_api_row(14, 90000.0), _api_row(15, 94100.0), _api_row(16, 119000.0)]

    with patch(PATCH_TARGET, return_value=api_rows), not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=out,
            force_color=True,
        )

    output = out.getvalue()
    assert "\x1b[32;1m" not in output  # never SUCCESS green
    # The report is written inside the finally, before the raise, so a
    # wrapper script can gate on the exit code and still read the report.
    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert rows[0]["n_missing_in_db_span"] == "1"


def test_value_differences_alone_raise(station, tmp_path):
    """B4: zero missing days but stale values is still a failed
    restoration."""
    _row(station, 15, 94100.0)
    _row(station, 16, 95000.0)  # stale: API says 119000
    report = tmp_path / "audit.csv"

    with patch(PATCH_TARGET, return_value=API_ROWS), not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=StringIO(),
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert rows[0]["n_missing_in_db_span"] == "0"
    assert rows[0]["n_value_diff"] == "1"


def test_duplicate_non_midnight_rows_are_reported(station, tmp_path):
    """N3: db_by_date is keyed on date, so duplicate rows at a non-midnight
    time collapse and the audit would report clean - blind to the exact
    corruption the midnight-UTC invariant exists to prevent. n_db_rows must
    exceed n_db and a WARNING must name the excess. It does not fail the
    gage, so the raise here comes from the extra API day, not the
    duplicate."""
    _row(station, 15, 94100.0)
    DischargeObservation.objects.create(
        station=station,
        observed_at=datetime(2021, 11, 15, 12, 30, tzinfo=timezone.utc),
        discharge=Decimal("94100.0"),
        unit="cfs",
        type="daily_mean",
        quality_code="A",
    )
    report = tmp_path / "audit.csv"
    out = StringIO()
    with patch(PATCH_TARGET, return_value=[_api_row(15, 94100.0)]):
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=out,
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert rows[0]["n_db"] == "1"
    assert rows[0]["n_db_rows"] == "2"
    assert int(rows[0]["n_db_rows"]) > int(rows[0]["n_db"])
    assert "duplicate" in out.getvalue()
    assert "12200500" in out.getvalue()


def test_non_cfs_row_is_not_counted_as_a_value_difference(station, tmp_path):
    """T8: the unit="cfs" filter is load-bearing - a cms row compared against
    a cfs API value reads as a false value difference and corrupts the
    verdict. Every other fixture in this file hardcodes unit="cfs", so
    deleting the filter would otherwise go undetected.

    The cms row sits on day 15, between two cfs rows, so it is inside the
    comparison span. unique_observation_idx is (station, observed_at, type),
    so a cfs and a cms row cannot share a date - day 15 has only the cms
    row. With the filter, day 15 is simply absent from the DB side and shows
    up as one in-span missing day; without it, day 15 would compare 2,665
    (cms) against 94,100 (cfs) and read as a value difference instead.
    """
    _row(station, 14, 90000.0)
    _row(station, 16, 119000.0)
    DischargeObservation.objects.create(
        station=station,
        observed_at=datetime(2021, 11, 15, tzinfo=timezone.utc),
        discharge=Decimal("2665.0"),  # 94,100 cfs expressed in cms
        unit="cms",
        type="daily_mean",
        quality_code="A",
    )

    report = tmp_path / "audit.csv"
    out = StringIO()
    api_rows = [
        _api_row(14, 90000.0),
        _api_row(15, 94100.0),
        _api_row(16, 119000.0),
    ]
    with patch(PATCH_TARGET, return_value=api_rows), not_all_clear():
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=out,
        )

    rows = list(csv.DictReader(report.read_text().splitlines()))
    assert rows[0]["n_value_diff"] == "0", "a cms row must never be compared"
    assert rows[0]["n_missing_in_db_span"] == "1"
    # The cms row must also not inflate the raw row count or trip the N3
    # duplicate warning - it is filtered out before either is computed.
    assert rows[0]["n_db_rows"] == "2"
    assert "duplicate" not in out.getvalue()
