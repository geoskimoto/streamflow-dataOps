"""Compare stored USGS daily means against the USGS Water Data API.

Run after a backfill to confirm no missing days or stale values remain. This is
the in-Django equivalent of the external audit_observation_gaps.py, which needs
sqlalchemy/psycopg2 and a DSN.

    venv/bin/python manage.py audit_usgs_observations \\
        --gage-list-csv streamflow-dataops-observation-issues/gage_gaps.csv \\
        --report data/audit_after_backfill.csv

Read-only: this command never writes to the database. It only reads
DischargeObservation rows and the live USGS Water Data API.

Mirrors backfill_usgs_observations' error handling: one bad gage (a DB error
or a fetch failure) is reported and skipped rather than aborting the run, the
inter-gage pacing sleep fires on every path (success, skip, and failure
alike), and when --report is given the report is always written on exit -
including on an exception or Ctrl-C - via try/finally, so a long run's
progress is not lost.
"""

import csv
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection

from apps.streamflow.management.gage_lists import resolve_gages
from apps.streamflow.models import DischargeObservation, Station
from src.acquisition.usgs_waterdata_client import USGSWaterDataClient

# A value counts as different if it is off by more than 0.5 cfs and 0.5%,
# matching the tolerance used by the original audit.
ABS_TOLERANCE_CFS = 0.5
REL_TOLERANCE = 0.005


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
        rows = []
        total_missing = total_diff = 0

        try:
            for index, gage in enumerate(gages, start=1):
                try:
                    station = Station.objects.filter(
                        station_number=gage, agency="USGS"
                    ).first()
                    if station is None:
                        self.stdout.write(
                            self.style.WARNING(f"{gage}: not in stations table")
                        )
                        rows.append({"usgs_id": gage, "status": "not_in_db"})
                        continue

                    api_rows = client.get_daily_mean(gage, None)

                    api_by_date = {
                        o["observed_at"].date(): float(o["discharge"])
                        for o in api_rows
                    }
                    db_by_date = {
                        observed_at.date(): float(discharge)
                        for observed_at, discharge in (
                            DischargeObservation.objects.filter(
                                station=station, type="daily_mean"
                            ).values_list("observed_at", "discharge")
                        )
                    }

                    if not db_by_date or not api_by_date:
                        rows.append({"usgs_id": gage, "status": "no_data"})
                        continue

                    # Only judge from the earliest date the DB actually
                    # covers, as the original audit did - otherwise every
                    # day before the first stored row is reported as
                    # "missing". Deliberately unbounded on the upper end:
                    # the whole point of the audit is to catch the DB
                    # falling behind the API's latest days, which a
                    # max(db_by_date) ceiling would hide.
                    lo = min(db_by_date)
                    in_span = {d: v for d, v in api_by_date.items() if d >= lo}

                    missing = sorted(d for d in in_span if d not in db_by_date)
                    diffs = [
                        d
                        for d, api_value in in_span.items()
                        if d in db_by_date
                        and abs(api_value - db_by_date[d])
                        > max(ABS_TOLERANCE_CFS, REL_TOLERANCE * api_value)
                    ]

                    total_missing += len(missing)
                    total_diff += len(diffs)

                    record = {
                        "usgs_id": gage,
                        "status": "ok",
                        "n_db": len(db_by_date),
                        "n_api_in_span": len(in_span),
                        "n_missing": len(missing),
                        "n_value_diff": len(diffs),
                        "db_max": max(db_by_date.values()),
                        "api_max": max(api_by_date.values()),
                        "first_missing": missing[0].isoformat() if missing else "",
                    }
                    rows.append(record)
                    self.stdout.write(
                        f"[{index}/{len(gages)}] {gage}: missing={len(missing)} "
                        f"diff={len(diffs)} db_max={record['db_max']:.0f} "
                        f"api_max={record['api_max']:.0f}"
                    )

                except Exception as exc:  # noqa: BLE001 - one bad gage must never abort the run
                    # Reset a possibly-dead connection so the next gage can
                    # reconnect, mirroring backfill_usgs_observations.
                    connection.close()
                    self.stdout.write(
                        self.style.ERROR(f"[{index}/{len(gages)}] {gage}: failed: {exc}")
                    )
                    rows.append({"usgs_id": gage, "status": f"failed: {exc}"})
                finally:
                    # Pacing applies on every path - success, not-in-db, and
                    # failure alike - so a run of failures doesn't hammer a
                    # struggling upstream back-to-back.
                    if options["sleep"] and index < len(gages):
                        time.sleep(options["sleep"])
        finally:
            # Always write what we have, even on exception or Ctrl-C, so a
            # long audit against production never loses its progress.
            if options.get("report"):
                self._write_report(options["report"], rows)

        self.stdout.write(
            self.style.SUCCESS(
                f"Audited {len(rows)} gages: {total_missing} missing days, "
                f"{total_diff} value differences."
            )
        )

    # Gage-list parsing is shared with backfill_usgs_observations; see
    # apps/streamflow/management/gage_lists.py.

    def _write_report(self, path, rows):
        fields = [
            "usgs_id", "status", "n_db", "n_api_in_span", "n_missing",
            "n_value_diff", "db_max", "api_max", "first_missing",
        ]
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fields})
        self.stdout.write(f"Report written to {target}")
