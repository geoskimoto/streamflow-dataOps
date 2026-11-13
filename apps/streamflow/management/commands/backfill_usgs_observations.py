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

import csv
import time
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from apps.streamflow.management.gage_lists import load_skip_file, resolve_gages
from apps.streamflow.models import DischargeObservation, Station
from src.acquisition.data_processor import DataProcessor
from src.acquisition.usgs_waterdata_client import USGSWaterDataClient


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
        parser.add_argument("--end", help="Inclusive end date YYYY-MM-DD.")
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
            help="Write a per-gage CSV report to this path.",
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
        skip = load_skip_file(options.get("skip_gages_file"))
        if skip:
            gages = [g for g in gages if g not in skip]
            self.stdout.write(f"Skipping {len(skip)} already-completed gages")

        start = self._parse_date(options.get("start"))
        end = self._parse_date(options.get("end"))
        if start and end and start > end:
            raise CommandError(
                f"--start {options['start']} is after --end {options['end']}"
            )

        dry_run = options["dry_run"]
        sleep_seconds = options["sleep"]
        report_path = options.get("report")

        client = USGSWaterDataClient()
        processor = DataProcessor()
        rows = []

        self.stdout.write(
            f"Backfilling {len(gages)} gages "
            f"({'dry run' if dry_run else 'writing'})"
        )

        done_handle = None
        if report_path and not dry_run:
            done_path = Path(f"{report_path}.done.txt")
            done_path.parent.mkdir(parents=True, exist_ok=True)
            done_handle = done_path.open("a")

        try:
            for index, gage in enumerate(gages, start=1):
                try:
                    station = Station.objects.filter(
                        station_number=gage, agency="USGS"
                    ).first()
                    if station is None:
                        self.stdout.write(
                            self.style.WARNING(
                                f"[{index}/{len(gages)}] {gage}: not in "
                                f"stations table, skipped"
                            )
                        )
                        rows.append({"usgs_id": gage, "status": "not_in_db"})
                        continue

                    # Both the "before" and "after" reads, and the upsert
                    # itself, sit inside this try: a dropped DB connection
                    # (OperationalError/InterfaceError) mid-run must be
                    # recorded as a failed gage, not abort the remaining
                    # gages.
                    before = self._max_discharge(station)
                    observations = client.get_daily_mean(gage, start, end)

                    written = 0
                    if observations and not dry_run:
                        written = processor.process_observations(
                            station_number=gage, observations=observations
                        )

                    after = self._max_discharge(station)

                    if dry_run:
                        status = "dry_run"
                    elif not observations:
                        status = "no_data"
                    else:
                        status = "ok"

                    rows.append(
                        {
                            "usgs_id": gage,
                            "status": status,
                            "fetched": len(observations),
                            "written": written,
                            "db_max_before": before,
                            "db_max_after": after,
                        }
                    )
                    self.stdout.write(
                        f"[{index}/{len(gages)}] {gage}: fetched "
                        f"{len(observations)}, wrote {written}, max "
                        f"{before} -> {after}"
                    )

                    if status == "ok" and done_handle:
                        done_handle.write(f"{gage}\n")
                        done_handle.flush()

                except Exception as exc:  # noqa: BLE001 - one bad gage must never abort the run
                    self.stdout.write(
                        self.style.ERROR(
                            f"[{index}/{len(gages)}] {gage}: failed: {exc}"
                        )
                    )
                    rows.append({"usgs_id": gage, "status": f"failed: {exc}"})
                finally:
                    # Pacing applies on every path - success, not-in-db, and
                    # failure alike - so a run of failures doesn't hammer a
                    # struggling upstream back-to-back.
                    if sleep_seconds and index < len(gages):
                        time.sleep(sleep_seconds)
        finally:
            # Always write what we have, even on exception or Ctrl-C, so a
            # multi-hour run against production never loses its resume state.
            if report_path:
                self._write_report(report_path, rows)
            if done_handle:
                done_handle.close()

        failed = [r for r in rows if str(r.get("status", "")).startswith("failed")]
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {len(rows)} gages processed, {len(failed)} failed."
            )
        )

    # -- helpers ---------------------------------------------------------
    # Gage-list parsing lives in apps/streamflow/management/gage_lists.py,
    # shared with audit_usgs_observations.

    @staticmethod
    def _parse_date(value):
        if not value:
            return None

        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise CommandError(f"Bad date {value!r}, expected YYYY-MM-DD") from exc
        return parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _max_discharge(station):
        return DischargeObservation.objects.filter(
            station=station, type="daily_mean"
        ).aggregate(m=Max("discharge"))["m"]

    def _write_report(self, path, rows):
        fields = [
            "usgs_id",
            "status",
            "fetched",
            "written",
            "db_max_before",
            "db_max_after",
        ]
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fields})
        self.stdout.write(f"Report written to {target}")
