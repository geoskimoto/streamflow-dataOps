"""Re-fetch and upsert USGS daily-mean discharge, restoring dropped peaks.

A 5-sigma batch filter in DataProcessor.validate_observations discarded real
flood peaks, and inserts used ignore_conflicts so provisional values were never
revised. Both are fixed, but existing rows stay wrong until re-fetched. This
command re-reads whole records from the USGS Water Data API and upserts them.

It is idempotent and safe to re-run. Runs can take a long time — use nohup:

    nohup venv/bin/python manage.py backfill_usgs_observations \\
        --gage-list-csv streamflow-dataops-observation-issues/gage_gaps.csv \\
        --report data/backfill_stage_a.csv \\
        > data/backfill_stage_a.log 2>&1 &

Crash/resume: while a non-dry-run with --report is active, every gage that
completes with status "ok" is appended, flushed, to a sidecar file
``<report>.done.txt`` (one id per line) as it happens — not just at the end.
The main report CSV is also always (re)written on exit, including on
exception or Ctrl-C, from whatever rows were collected so far. Feed
``<report>.done.txt`` straight back in as ``--skip-gages-file`` to resume;
it contains only gages that succeeded, so failed/not-found gages are retried.
"""

import time  # noqa: F401 - unused here; see comment below
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import connection  # noqa: F401 - unused here; see comment below

from apps.streamflow.management.backfill_runner import run_backfill
from apps.streamflow.management.gage_lists import resolve_gages
from src.acquisition.data_processor import DataProcessor  # noqa: F401 - unused here; see comment below
from src.acquisition.usgs_waterdata_client import USGSWaterDataClient

# time, connection, and DataProcessor above are not called directly in this
# module anymore - the run loop that uses them moved to backfill_runner.py.
# They stay imported here, unused, because
# tests/test_backfill_usgs_observations.py patches them by this module's
# dotted path (e.g. "...backfill_usgs_observations.connection.close"). That
# test file is a pinned regression proof and must not be edited, and
# mock.patch resolves its target via getattr on this module, so removing
# these imports breaks the patch with AttributeError even though the real
# call now happens in backfill_runner. All three names are the same
# singleton object/class/module wherever they're imported, so patching them
# here still intercepts the call made from backfill_runner.py.


class Command(BaseCommand):
    help = (
        "Re-fetch USGS daily-mean discharge from the Water Data API and upsert "
        "it, restoring peaks dropped by the old 5-sigma filter."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--gages",
            help="Comma-separated USGS site ids.",
        )
        parser.add_argument(
            "--gage-list-csv",
            help=(
                "CSV with a 'usgs_id' column, e.g. "
                "streamflow-dataops-observation-issues/gage_gaps.csv (285 "
                "NWRFC-mapped gages)."
            ),
        )
        parser.add_argument(
            "--all-usgs",
            action="store_true",
            help="Every Station with agency='USGS'.",
        )
        parser.add_argument(
            "--start",
            help="Inclusive start date YYYY-MM-DD. Omit for the full record.",
        )
        parser.add_argument(
            "--end",
            help=(
                "Inclusive end date YYYY-MM-DD. Requires --start: the client "
                "ignores an end date on its own."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Fetch and report, but make no database writes. --report is "
                "still produced if given; no '<report>.done.txt' resume "
                "sidecar is written during a dry run."
            ),
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=1.0,
            help=(
                "Seconds between gages. Without a USGS_API_KEY, USGS "
                "degrades silently under bursts (empty bodies, truncated "
                "gzip) rather than returning 429 - pacing avoids that. The "
                "API key's 1,000 requests/hour budget is the separate 429 "
                "risk. Default 1.0."
            ),
        )
        parser.add_argument(
            "--report",
            help=(
                "Write a per-gage CSV report to this path. The file is "
                "overwritten on every run (the '.done.txt' sidecar next to "
                "it is appended, not overwritten) - use a new path for a "
                "resumed run if the earlier report needs keeping."
            ),
        )
        parser.add_argument(
            "--skip-gages-file",
            help=(
                "File with one already-completed USGS id per line; those "
                "gages are skipped. Point this at the '<report>.done.txt' "
                "sidecar written next to --report by a previous run - it "
                "contains only gages that completed successfully (status "
                "'ok'), so failed and not-found gages are retried "
                "automatically. A raw copy of the --report CSV will not "
                "work here: load_skip_file matches whole stripped lines, "
                "and a CSV row like '12200500,ok,13,13,...' matches nothing."
            ),
        )

    def handle(self, *args, **options):
        gages = resolve_gages(options)

        start = self._parse_date(options.get("start"))
        end = self._parse_date(options.get("end"))
        if end and not start:
            # The client ignores end_date unless start_date is set, so an
            # operator scoping a run to old dates with --end alone would
            # instead get a full-record overwrite up to today.
            raise CommandError(
                "--end requires --start; the USGS Water Data client ignores "
                "an end date on its own, so this would silently re-fetch and "
                "overwrite the entire record instead of the range you asked "
                "for."
            )
        if start and end and start > end:
            raise CommandError(
                f"--start {options['start']} is after --end {options['end']}"
            )

        # The runner reads start/end back out of options via .get(), so the
        # already-validated, already-parsed datetimes replace the raw
        # strings here rather than being re-parsed downstream.
        options["start"] = start
        options["end"] = end

        client = USGSWaterDataClient()

        def fetch(station_number, start_date, end_date):
            return client.get_daily_mean(station_number, start_date, end_date)

        run_backfill(
            command=self, gages=gages, fetch=fetch,
            agency="USGS", options=options,
        )

    # -- helpers ---------------------------------------------------------
    # Gage-list parsing lives in apps/streamflow/management/gage_lists.py,
    # shared with audit_usgs_observations. The run loop, report, and resume
    # sidecar live in apps/streamflow/management/backfill_runner.py, shared
    # with the EC backfill command.

    @staticmethod
    def _parse_date(value):
        if not value:
            return None

        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise CommandError(f"Bad date {value!r}, expected YYYY-MM-DD") from exc
        return parsed.replace(tzinfo=timezone.utc)
