"""Re-fetch and upsert Environment Canada daily-mean discharge.

EC passed through the same DataProcessor 5-sigma filter as USGS, so its records
are truncated the same way: sampled 2026-11-13, 5 of 8 EC stations with long
records held a maximum between 0.48 and 0.82 of the true EC maximum.

EC discharge is stored in cms and must never be converted. Unlike the USGS API,
the MSC GeoMet endpoint needs no key and has no hourly request budget, but keep
the default pacing so it is not hammered.

    nohup venv/bin/python manage.py backfill_ec_observations --all-ec \\
        --report data/backfill_stage_c.csv \\
        > data/backfill_stage_c.log 2>&1 &
"""

from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from apps.streamflow.management.backfill_runner import run_backfill
# The full-record sentinel is shared with audit_ec_observations - the two
# must always agree on the span, so it is defined once in ec_constants.
from apps.streamflow.management.ec_constants import EC_EARLIEST_START
from apps.streamflow.management.gage_lists import resolve_gages
from src.acquisition.canada_client import CanadaClient


class Command(BaseCommand):
    help = (
        "Re-fetch Environment Canada daily-mean discharge from the MSC "
        "GeoMet API and upsert it, restoring peaks dropped by the old "
        "5-sigma filter."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--stations",
            help="Comma-separated EC station numbers.",
        )
        parser.add_argument(
            "--station-list-csv",
            help=(
                "CSV with a 'station_number' or 'usgs_id' column "
                "('station_number' wins if both are present)."
            ),
        )
        parser.add_argument(
            "--all-ec",
            action="store_true",
            help="Every Station with agency='EC'.",
        )
        parser.add_argument(
            "--start",
            help=(
                "Inclusive start date YYYY-MM-DD. Omit for the full record "
                f"- CanadaClient.get_daily_mean requires a start date, so "
                f"omitting this passes {EC_EARLIEST_START.date()} instead "
                "of None."
            ),
        )
        parser.add_argument(
            "--end",
            help=(
                "Inclusive end date YYYY-MM-DD. Requires --start: the "
                "client ignores an end date on its own."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Fetch and report, but make no database writes. --report "
                "is still produced if given; no '<report>.done.txt' "
                "resume sidecar is written during a dry run."
            ),
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=1.0,
            help=(
                "Seconds between stations. The MSC GeoMet endpoint needs "
                "no key and has no documented hourly budget, but pacing "
                "stays on by default so it is never hammered. Default 1.0."
            ),
        )
        parser.add_argument(
            "--report",
            help=(
                "Write a per-station CSV report to this path. The file is "
                "overwritten on every run (the '.done.txt' sidecar next "
                "to it is appended, not overwritten) - use a new path for "
                "a resumed run if the earlier report needs keeping."
            ),
        )
        parser.add_argument(
            "--skip-gages-file",
            help=(
                "File with one already-completed EC station number per "
                "line; those stations are skipped. Point this at the "
                "'<report>.done.txt' sidecar written next to --report by "
                "a previous run - it contains only stations that "
                "completed successfully (status 'ok'), so failed and "
                "not-found stations are retried automatically."
            ),
        )

    def handle(self, *args, **options):
        # resolve_gages() reads 'gages'/'gage_list_csv'/'all_usgs' - map
        # this command's EC-flavored flag names onto that shared contract
        # without touching gage_lists.py's own option names.
        gages = resolve_gages(
            {
                "gages": options.get("stations"),
                "gage_list_csv": options.get("station_list_csv"),
                "all_ec": options.get("all_ec"),
            },
            selector_names={
                "gages": "--stations",
                "gage_list_csv": "--station-list-csv",
            },
        )

        start = self._parse_date(options.get("start"))
        end = self._parse_date(options.get("end"))
        if end and not start:
            # get_daily_mean() ignores end_date unless start_date is set
            # too (see CanadaClient), so an operator scoping a run to old
            # dates with --end alone would instead get a full-record
            # overwrite up to today.
            raise CommandError(
                "--end requires --start; the EC client ignores an end "
                "date on its own, so this would silently re-fetch and "
                "overwrite the entire record instead of the range you "
                "asked for."
            )
        if start and end and start > end:
            raise CommandError(
                f"--start {options['start']} is after --end {options['end']}"
            )

        # CanadaClient.get_daily_mean() requires a non-None start_date,
        # unlike the USGS client - an omitted --start means "the full
        # record", so it becomes EC_EARLIEST_START rather than None.
        options["start"] = start or EC_EARLIEST_START
        options["end"] = end

        client = CanadaClient()

        def fetch(station_number, start_date, end_date):
            return client.get_daily_mean(station_number, start_date, end_date)

        run_backfill(
            command=self, gages=gages, fetch=fetch,
            agency="EC", options=options,
        )

    # -- helpers ---------------------------------------------------------
    # Gage-list parsing lives in apps/streamflow/management/gage_lists.py,
    # shared with backfill_usgs_observations. The run loop, report, and
    # resume sidecar live in apps/streamflow/management/backfill_runner.py,
    # also shared with the USGS command.

    @staticmethod
    def _parse_date(value):
        if not value:
            return None

        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise CommandError(f"Bad date {value!r}, expected YYYY-MM-DD") from exc
        return parsed.replace(tzinfo=timezone.utc)
