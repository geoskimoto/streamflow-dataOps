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

The comparison deliberately bounds the "missing" count on the lower end only
(from the earliest stored date) and not on the upper end. A two-sided bound
would define "complete" as "everything up to whatever we already have",
which scores a backfill that wrote nothing recent as missing=0 - exactly the
failure mode this command exists to catch. Because of that, the total
`n_missing` this command reports is NOT directly comparable to the
46,701-gage-day pre-backfill baseline, which was produced with two-sided
bounding. `n_missing_in_db_span` (gaps strictly between the first and last
stored date) is the figure comparable to that baseline; `n_missing_after_db_last`
(API dates after the last stored date - tail staleness, e.g. a gage that
stopped updating) is reported separately so the two are never silently
summed into a misleadingly large or small total.

A per-gage "no data" condition has two distinct causes, reported separately:
`no_db_data` (nothing stored for this station) and `no_api_data` (the API
returned nothing for this station). Only `type="daily_mean", unit="cfs"` rows
are read from the DB - the API returns ft^3/s, so a non-cfs row is not a
valid comparison and would otherwise show up as a spurious value difference.
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
        total_missing_in_span = total_missing_after_last = total_diff = 0

        try:
            for index, gage in enumerate(gages, start=1):
                try:
                    station = Station.objects.filter(
                        station_number=gage, agency="USGS"
                    ).first()
                    if station is None:
                        self.stdout.write(
                            self.style.WARNING(
                                f"[{index}/{len(gages)}] {gage}: not in stations table"
                            )
                        )
                        rows.append({"usgs_id": gage, "status": "not_in_db"})
                        continue

                    api_rows = client.get_daily_mean(gage, None)

                    api_by_date = {
                        o["observed_at"].date(): float(o["discharge"])
                        for o in api_rows
                    }
                    # Only cfs rows are comparable to the API, which returns
                    # ft^3/s; a non-cfs daily_mean row would otherwise be
                    # flagged as a spurious value difference.
                    db_by_date = {
                        observed_at.date(): float(discharge)
                        for observed_at, discharge in (
                            DischargeObservation.objects.filter(
                                station=station, type="daily_mean", unit="cfs"
                            ).values_list("observed_at", "discharge")
                        )
                    }

                    if not db_by_date:
                        self.stdout.write(
                            self.style.WARNING(
                                f"[{index}/{len(gages)}] {gage}: no stored "
                                f"cfs daily-mean observations"
                            )
                        )
                        rows.append({"usgs_id": gage, "status": "no_db_data"})
                        continue
                    if not api_by_date:
                        self.stdout.write(
                            self.style.WARNING(
                                f"[{index}/{len(gages)}] {gage}: USGS API "
                                f"returned no data"
                            )
                        )
                        rows.append({"usgs_id": gage, "status": "no_api_data"})
                        continue

                    # Only judge from the earliest date the DB actually
                    # covers, as the original audit did - otherwise every
                    # day before the first stored row is reported as
                    # "missing". Deliberately unbounded on the upper end for
                    # the total: a two-sided bound would define "complete"
                    # as "everything up to whatever we already have", hiding
                    # a backfill that wrote nothing recent. The split below
                    # keeps that tail staleness visible without conflating
                    # it with the in-span gaps the original audit measured.
                    lo, hi = min(db_by_date), max(db_by_date)
                    in_span = {d: v for d, v in api_by_date.items() if d >= lo}

                    missing_in_db_span = sorted(
                        d for d in in_span if d <= hi and d not in db_by_date
                    )
                    missing_after_db_last = sorted(d for d in in_span if d > hi)
                    missing = missing_in_db_span + missing_after_db_last

                    diffs = [
                        d
                        for d, api_value in in_span.items()
                        if d in db_by_date
                        and abs(api_value - db_by_date[d])
                        > max(ABS_TOLERANCE_CFS, REL_TOLERANCE * api_value)
                    ]

                    total_missing_in_span += len(missing_in_db_span)
                    total_missing_after_last += len(missing_after_db_last)
                    total_diff += len(diffs)

                    record = {
                        "usgs_id": gage,
                        "status": "ok",
                        "n_db": len(db_by_date),
                        "n_api_in_span": len(in_span),
                        "n_missing": len(missing),
                        "n_missing_in_db_span": len(missing_in_db_span),
                        "n_missing_after_db_last": len(missing_after_db_last),
                        "n_value_diff": len(diffs),
                        "db_max": max(db_by_date.values()),
                        "api_max": max(api_by_date.values()),
                        "first_missing": missing[0].isoformat() if missing else "",
                    }
                    rows.append(record)
                    self.stdout.write(
                        f"[{index}/{len(gages)}] {gage}: missing={len(missing)} "
                        f"(in_span={len(missing_in_db_span)} "
                        f"after_last={len(missing_after_db_last)}) "
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

        counts = self._status_counts(rows)
        all_ok = len(rows) > 0 and counts["ok"] == len(rows)
        summary = (
            f"Audited {len(rows)} gages: {counts['ok']} ok, "
            f"{counts['failed']} failed, {counts['no_db_data']} no_db_data, "
            f"{counts['no_api_data']} no_api_data, "
            f"{counts['not_in_db']} not_in_db ("
            f"{total_missing_in_span} missing_in_db_span, "
            f"{total_missing_after_last} missing_after_db_last, "
            f"{total_diff} value differences — totals cover 'ok' gages only)."
        )
        style = self.style.SUCCESS if all_ok else self.style.WARNING
        self.stdout.write(style(summary))

    # Gage-list parsing is shared with backfill_usgs_observations; see
    # apps/streamflow/management/gage_lists.py.

    @staticmethod
    def _status_counts(rows):
        """Tally outcomes so the summary can never read as clean success
        when some gages failed, were skipped, or had no data - a dynamic
        "failed: {exc}" status string is matched by prefix, mirroring
        backfill_usgs_observations' own failed-count logic."""
        counts = {
            "ok": 0,
            "failed": 0,
            "no_db_data": 0,
            "no_api_data": 0,
            "not_in_db": 0,
        }
        for row in rows:
            status = str(row.get("status", ""))
            if status.startswith("failed"):
                counts["failed"] += 1
            elif status in counts:
                counts[status] += 1
        return counts

    def _write_report(self, path, rows):
        fields = [
            "usgs_id", "status", "n_db", "n_api_in_span", "n_missing",
            "n_missing_in_db_span", "n_missing_after_db_last", "n_value_diff",
            "db_max", "api_max", "first_missing",
        ]
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fields})
        self.stdout.write(f"Report written to {target}")
