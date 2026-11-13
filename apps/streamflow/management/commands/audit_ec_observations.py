"""Compare stored Environment Canada daily means against the MSC GeoMet API.

Run after `backfill_ec_observations` to confirm no missing days or stale
values remain - the EC analogue of `audit_usgs_observations`, verifying the
EC repair the way Stage A/B were verified for USGS.

    venv/bin/python manage.py audit_ec_observations --all-ec \\
        --report data/audit_ec_after_backfill.csv

Read-only: this command never writes to the database. It only reads
DischargeObservation rows and the live MSC GeoMet API.

The comparison loop, tolerance, bounding rule, status vocabulary, and report
writing all live in ``apps/streamflow/management/audit_runner.py``, shared
with ``audit_usgs_observations`` - see that module's docstring for the
properties it preserves. Only ``unit="cms"`` rows are read from the DB here -
EC discharge is stored in cms and must never be compared against a
differently-unit'd row.

``CanadaClient.get_daily_mean`` requires a non-``None`` start date (unlike
the USGS client's "omit for full record" shorthand), so the fetch closure
below always passes a fixed earliest-possible date, exactly as
``backfill_ec_observations`` does.
"""

from datetime import datetime, timezone

from django.core.management.base import BaseCommand

from apps.streamflow.management.audit_runner import ABS_TOLERANCE_CMS, run_audit
from apps.streamflow.management.gage_lists import resolve_gages
from src.acquisition.canada_client import CanadaClient

# CanadaClient.get_daily_mean() requires a non-None start_date - unlike the
# USGS client, it has no "full record" shorthand - so the fetch closure below
# always passes this instead of None.
_EARLIEST_START = datetime(1850, 1, 1, tzinfo=timezone.utc)


class Command(BaseCommand):
    help = "Audit stored Environment Canada daily means against the MSC GeoMet API."

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
        parser.add_argument("--report", help="Write a per-station CSV report here.")
        parser.add_argument(
            "--sleep", type=float, default=1.0,
            help="Seconds between stations. Default 1.0.",
        )
        parser.add_argument(
            "--max-tail-staleness-days", type=int, default=7,
            help=(
                "A station whose latest API date is more than this many "
                "days past its last stored date fails the all-clear gate "
                "(tail staleness - the source is publishing data we don't "
                "have). Default 7, which absorbs normal publication lag."
            ),
        )
        parser.add_argument(
            "--allow-stale-tail", action="store_true",
            help=(
                "Suppress only the tail-staleness part of the all-clear "
                "gate. In-span missing days and value differences still "
                "raise regardless of this flag."
            ),
        )

    def handle(self, *args, **options):
        # resolve_gages() reads 'gages'/'gage_list_csv'/'all_ec' - map this
        # command's EC-flavored flag names onto that shared contract without
        # touching gage_lists.py's own option names, and so the
        # no-selection error names this command's own flags rather than the
        # USGS command's --gages/--gage-list-csv.
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

        client = CanadaClient()

        def fetch(station_number):
            return client.get_daily_mean(station_number, _EARLIEST_START)

        run_audit(
            command=self,
            gages=gages,
            fetch=fetch,
            agency="EC",
            unit="cms",
            id_field="station_number",
            api_label="EC API",
            abs_tolerance=ABS_TOLERANCE_CMS,
            options=options,
        )

    # Gage-list parsing is shared with backfill_ec_observations; see
    # apps/streamflow/management/gage_lists.py. The comparison loop and
    # report writing are shared with audit_usgs_observations; see
    # apps/streamflow/management/audit_runner.py.
