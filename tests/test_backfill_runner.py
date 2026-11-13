"""Tests for the shared, agency-agnostic backfill runner.

The runner owns everything the USGS command's review rounds established:
per-gage fault isolation with a connection reset, pacing on every path,
a crash-safe .done.txt sidecar, report-on-exception, and a no-write dry run.
Both the USGS and EC commands delegate to it.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.management.base import BaseCommand

from apps.streamflow.management.backfill_runner import run_backfill
from apps.streamflow.models import DischargeObservation, Station


@pytest.fixture
def stations(db):
    a = Station.objects.create(
        station_number="08LE031", name="EC One", agency="EC", is_active=True
    )
    b = Station.objects.create(
        station_number="08LD001", name="EC Two", agency="EC", is_active=True
    )
    return a, b


def _obs(day, value, unit="cms"):
    return {
        "observed_at": datetime(2020, 1, day, tzinfo=timezone.utc),
        "discharge": value,
        "unit": unit,
        "type": "daily_mean",
        "quality_code": "A",
    }


def _opts(**over):
    base = {
        "start": None, "end": None, "dry_run": False,
        "sleep": 0, "report": None, "skip_gages_file": None,
    }
    base.update(over)
    return base


def _run(gages, fetch, agency="EC", **over):
    return run_backfill(
        command=BaseCommand(), gages=gages, fetch=fetch,
        agency=agency, options=_opts(**over),
    )


def test_writes_observations_and_reports_ok(stations):
    rows = _run(["08LE031"], lambda s, a, b: [_obs(1, 173.0), _obs(2, 172.0)])

    assert rows[0]["status"] == "ok"
    assert rows[0]["fetched"] == 2
    assert DischargeObservation.objects.filter(
        station=stations[0], type="daily_mean"
    ).count() == 2


def test_dry_run_writes_nothing(stations):
    rows = _run(["08LE031"], lambda s, a, b: [_obs(1, 173.0)], dry_run=True)

    assert rows[0]["status"] == "dry_run"
    assert DischargeObservation.objects.count() == 0


def test_unknown_station_is_skipped_and_run_continues(stations):
    seen = []

    def fetch(s, a, b):
        seen.append(s)
        return [_obs(1, 173.0)]

    rows = _run(["99999999", "08LE031"], fetch)

    assert rows[0]["status"] == "not_in_db"
    assert rows[1]["status"] == "ok"
    assert seen == ["08LE031"]


def test_fetch_failure_isolated_to_one_gage(stations):
    def fetch(s, a, b):
        if s == "08LE031":
            raise RuntimeError("boom")
        return [_obs(1, 391.0)]

    # connection.close() is mocked because pytest-django's db fixture holds an
    # outer atomic block, where Django defers the close and poisons the rest of
    # the test. Production runs outside any atomic block, where close() resets
    # the connection as intended. See test_database_failure_isolated_and_
    # connection_reset, which asserts the close itself.
    with patch("apps.streamflow.management.backfill_runner.connection.close"):
        rows = _run(["08LE031", "08LD001"], fetch)

    assert rows[0]["status"].startswith("failed")
    assert rows[1]["status"] == "ok"
    assert DischargeObservation.objects.filter(station=stations[1]).count() == 1


def test_database_failure_isolated_and_connection_reset(stations):
    from django.db.utils import OperationalError

    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("server closed the connection unexpectedly")
        return 1

    with patch("apps.streamflow.management.backfill_runner.connection.close") as close, \
         patch("src.acquisition.data_processor.DataProcessor.process_observations",
               side_effect=flaky):
        rows = _run(["08LE031", "08LD001"], lambda s, a, b: [_obs(1, 1.0)])

    assert rows[0]["status"].startswith("failed")
    assert rows[1]["status"] == "ok"
    assert close.called, "the connection must be reset so the next gage reconnects"


def test_empty_fetch_is_no_data_not_ok(stations):
    rows = _run(["08LE031"], lambda s, a, b: [])
    assert rows[0]["status"] == "no_data"


def test_sleep_fires_on_every_path_including_failures(stations):
    def fetch(s, a, b):
        if s == "08LE031":
            raise RuntimeError("boom")
        return [_obs(1, 1.0)]

    with patch("apps.streamflow.management.backfill_runner.time.sleep") as sleep:
        _run(["08LE031", "08LD001"], fetch, sleep=1.0)

    assert sleep.called, "pacing must not be skipped on the failure path"


def test_done_sidecar_lists_only_ok_gages(stations, tmp_path):
    report = tmp_path / "r.csv"

    def fetch(s, a, b):
        return [] if s == "08LE031" else [_obs(1, 1.0)]

    _run(["08LE031", "08LD001"], fetch, report=str(report))

    sidecar = tmp_path / "r.csv.done.txt"
    assert sidecar.read_text().split() == ["08LD001"]


def test_report_is_written_even_when_the_loop_raises(stations, tmp_path):
    report = tmp_path / "r.csv"

    with patch("apps.streamflow.management.backfill_runner.time.sleep",
               side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            _run(["08LE031", "08LD001"], lambda s, a, b: [_obs(1, 1.0)],
                 report=str(report), sleep=1.0)

    assert "08LE031" in report.read_text()


def test_skip_file_excludes_listed_gages(stations, tmp_path):
    skip = tmp_path / "done.txt"
    skip.write_text("08LE031\n")
    seen = []

    _run(["08LE031", "08LD001"],
         lambda s, a, b: (seen.append(s), [_obs(1, 1.0)])[1],
         skip_gages_file=str(skip))

    assert seen == ["08LD001"]


def test_agency_scopes_the_station_lookup(stations):
    # An EC station must not be found when the runner is scoped to USGS.
    rows = _run(["08LE031"], lambda s, a, b: [_obs(1, 1.0)], agency="USGS")
    assert rows[0]["status"] == "not_in_db"


def test_raw_string_start_or_end_raises_typeerror(stations):
    """run_backfill expects options['start']/['end'] to already be parsed
    datetimes (or None) - never the raw --start/--end strings argparse
    hands the command. A command that forgets to parse and re-stash them
    before delegating here must fail loudly, not silently pass a string
    through to fetch()."""
    with pytest.raises(TypeError, match="start"):
        _run(["08LE031"], lambda s, a, b: [_obs(1, 1.0)], start="2020-01-01")

    with pytest.raises(TypeError, match="end"):
        _run(["08LE031"], lambda s, a, b: [_obs(1, 1.0)], end="2020-01-02")


def test_pinned_usgs_imports_are_present():
    """time, connection, and DataProcessor are imported-but-unused in
    backfill_usgs_observations.py purely so that three pinned tests in
    tests/test_backfill_usgs_observations.py can patch them by this
    module's dotted path (e.g.
    "...backfill_usgs_observations.connection.close"). mock.patch resolves
    that path via getattr on the module, so removing these imports - e.g.
    via an IDE "remove unused imports" action, which won't read the prose
    comment explaining why they're there - breaks those patches with an
    AttributeError raised in a different file. This test fails loudly and
    locally instead, right where the import would be removed."""
    import apps.streamflow.management.commands.backfill_usgs_observations as cmd_module

    assert hasattr(cmd_module, "time")
    assert hasattr(cmd_module, "connection")
    assert hasattr(cmd_module, "DataProcessor")
