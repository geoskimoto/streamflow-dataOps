"""
Management command: backfill_daily_percentiles

Populates the daily_flow_percentiles table for all historical dates using a
chunked window-function SQL approach — one PostgreSQL query per station chunk,
no per-station or per-date round-trips.

Usage examples
--------------
# Backfill all qualifying stations (default chunk size 100):
    python manage.py backfill_daily_percentiles

# Smaller chunks to reduce per-query memory:
    python manage.py backfill_daily_percentiles --batch-size 50

# Single station (useful for testing or re-processing):
    python manage.py backfill_daily_percentiles --station 12345678

# Limit to a specific date range (applied in Python after the SQL runs):
    python manage.py backfill_daily_percentiles --start-date 2020-01-01 --end-date 2023-12-31

# Dry run — report what would be inserted without writing anything:
    python manage.py backfill_daily_percentiles --dry-run
"""

import time
from datetime import date, datetime, timezone

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.streamflow.models import DailyFlowPercentile
from src.analytics.percentiles import (
    MIN_HISTORICAL_RECORDS,
    backfill_station_chunk,
    iter_station_id_chunks,
)

_INSERT_BATCH = 10_000  # rows per bulk_create call


class Command(BaseCommand):
    help = "Backfill daily_flow_percentiles for all historical daily_mean observations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of stations per SQL chunk (default: 100).",
        )
        parser.add_argument(
            "--station",
            type=str,
            default=None,
            help="Process only this station_number (useful for testing).",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            help="Only insert rows on or after this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help="Only insert rows on or before this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute but do not write to the database.",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            default=True,
            help=(
                "Skip station chunks that already have rows in daily_flow_percentiles "
                "(default: True — use upsert to overwrite instead)."
            ),
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        batch_size  = options["batch_size"]
        station_num = options["station"]
        start_date  = date.fromisoformat(options["start_date"]) if options["start_date"] else None
        end_date    = date.fromisoformat(options["end_date"])   if options["end_date"]   else None
        dry_run     = options["dry_run"]

        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("backfill_daily_percentiles"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no data will be written"))

        # Resolve station IDs
        station_ids = None
        if station_num:
            from apps.streamflow.models import Station
            try:
                sid = Station.objects.values_list("id", flat=True).get(
                    station_number=station_num
                )
                station_ids = [sid]
                self.stdout.write(f"Targeting station {station_num} (id={sid})")
            except Station.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Station {station_num} not found."))
                return

        computed_at = datetime.now(timezone.utc)
        total_rows_inserted = 0
        total_chunks        = 0
        t0                  = time.monotonic()

        for chunk_ids in iter_station_id_chunks(
            chunk_size=batch_size,
            station_ids=station_ids,
        ):
            total_chunks += 1
            chunk_t0 = time.monotonic()

            rows = backfill_station_chunk(chunk_ids, computed_at)

            # Apply date filters in Python (avoids extra SQL complexity)
            if start_date:
                rows = [r for r in rows if r["obs_date"] >= start_date]
            if end_date:
                rows = [r for r in rows if r["obs_date"] <= end_date]

            if not rows:
                continue

            if not dry_run:
                objs = [
                    DailyFlowPercentile(
                        station_id=r["station_id"],
                        date=r["obs_date"],
                        discharge=r["discharge"],
                        percentile_rank=r["percentile_rank"],
                        band=r["band"],
                        historical_record_count=r["historical_record_count"],
                        computed_at=r["computed_at"],
                    )
                    for r in rows
                ]
                for i in range(0, len(objs), _INSERT_BATCH):
                    DailyFlowPercentile.objects.bulk_create(
                        objs[i: i + _INSERT_BATCH],
                        update_conflicts=True,
                        unique_fields=["station", "date"],
                        update_fields=[
                            "discharge",
                            "percentile_rank",
                            "band",
                            "historical_record_count",
                            "computed_at",
                        ],
                    )

            total_rows_inserted += len(rows)
            elapsed = time.monotonic() - chunk_t0

            self.stdout.write(
                f"  chunk {total_chunks:4d} | stations {chunk_ids[0]}–{chunk_ids[-1]}"
                f" | rows {len(rows):7,d} | {elapsed:.1f}s"
            )

        total_elapsed = time.monotonic() - t0
        self.stdout.write(self.style.SUCCESS("=" * 70))
        action = "Would insert" if dry_run else "Inserted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {total_rows_inserted:,} rows across "
                f"{total_chunks} chunks in {total_elapsed:.0f}s "
                f"(min={MIN_HISTORICAL_RECORDS} records required)"
            )
        )
        self.stdout.write(self.style.SUCCESS("=" * 70))
