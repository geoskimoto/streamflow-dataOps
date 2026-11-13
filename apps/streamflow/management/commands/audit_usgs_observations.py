"""Compare stored USGS daily means against the USGS Water Data API.

Run after a backfill to confirm no missing days or stale values remain. This is
the in-Django equivalent of the external audit_observation_gaps.py, which needs
sqlalchemy/psycopg2 and a DSN.

    venv/bin/python manage.py audit_usgs_observations \\
        --gage-list-csv streamflow-dataops-observation-issues/gage_gaps.csv \\
        --report data/audit_after_backfill.csv

Read-only: this command never writes to the database. It only reads
DischargeObservation rows and the live USGS Water Data API.

The comparison loop, tolerance, bounding rule, status vocabulary, and report
writing all live in ``apps/streamflow/management/audit_runner.py``, shared
with ``audit_ec_observations`` - see that module's docstring for the
properties it preserves (lower-bound-only missing-day accounting, the
missing_in_db_span/missing_after_db_last split, the five statuses, the
n_db/n_db_rows duplicate-row visibility, and the not-all-clear
CommandError raised after the report is written). Only ``unit="cfs"`` rows
are read from the DB here - the API returns ft^3/s, so a non-cfs row is not
a valid comparison and would otherwise show up as a spurious value
difference.
"""

import time  # noqa: F401 - unused here; see comment below

from django.core.management.base import BaseCommand
from django.db import connection  # noqa: F401 - unused here; see comment below

from apps.streamflow.management.audit_runner import run_audit
from apps.streamflow.management.gage_lists import resolve_gages
from src.acquisition.usgs_waterdata_client import USGSWaterDataClient

# time and connection above are not called directly in this module anymore -
# the audit loop that uses them moved to audit_runner.py. They stay imported
# here, unused, because tests/test_audit_usgs_observations.py (a pinned
# regression proof that must not be edited) patches them by this module's
# dotted path (e.g. "...audit_usgs_observations.connection.close"). Both
# names are the same singleton object wherever they're imported, so
# patching them here still intercepts the call made from audit_runner.py.


class Command(BaseCommand):
    help = "Audit stored USGS daily means against the USGS Water Data API."

    def add_arguments(self, parser):
        parser.add_argument("--gages", help="Comma-separated USGS site ids.")
        parser.add_argument(
            "--gage-list-csv", help="CSV with a 'usgs_id' column."
        )
        parser.add_argument("--report", help="Write a per-gage CSV report here.")
        parser.add_argument(
            "--sleep", type=float, default=1.0,
            help="Seconds between gages. Default 1.0.",
        )

    def handle(self, *args, **options):
        gages = resolve_gages(options)
        client = USGSWaterDataClient()

        def fetch(station_number):
            return client.get_daily_mean(station_number, None)

        run_audit(
            command=self,
            gages=gages,
            fetch=fetch,
            agency="USGS",
            unit="cfs",
            id_field="usgs_id",
            api_label="USGS API",
            options=options,
        )

    # Gage-list parsing is shared with backfill_usgs_observations; see
    # apps/streamflow/management/gage_lists.py. The comparison loop and
    # report writing are shared with audit_ec_observations; see
    # apps/streamflow/management/audit_runner.py.
