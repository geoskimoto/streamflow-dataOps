"""Management command: backfill NWM forcings for a historical date range.

Uses the public AWS S3 mirror (available from ~2018 onward). Downloads
and processes one day at a time to stay within temp disk budget.

Usage:
    python manage.py backfill_nwm_forcings --start 2024-10-01 --end 2025-06-01
    python manage.py backfill_nwm_forcings --start 2024-10-01 --end 2025-06-01 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import shutil
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.nwm_forcings.models import NWMIngestionLog
from apps.nwm_forcings.nwm_client import build_s3_url, download_file, NWMDownloadError
from apps.nwm_forcings.tasks import ingest_day

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill NWM Analysis Assim basin forcings from AWS S3 for a date range"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            type=str,
            required=True,
            help="Start date inclusive (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--end",
            type=str,
            required=True,
            help="End date inclusive (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print dates that would be processed without downloading",
        )
        parser.add_argument(
            "--skip-existing",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Skip dates that already have a success log entry (use --no-skip-existing to reprocess)",
        )

    def handle(self, *args, **options):
        start = date.fromisoformat(options["start"])
        end = date.fromisoformat(options["end"])
        dry_run = options["dry_run"]
        skip_existing = options["skip_existing"]

        existing_dates: set[date] = set()
        if skip_existing:
            existing_dates = set(
                NWMIngestionLog.objects.filter(
                    ingest_date__gte=start,
                    ingest_date__lte=end,
                    status="success",
                ).values_list("ingest_date", flat=True)
            )

        current = start
        processed = 0
        skipped = 0

        while current <= end:
            if current in existing_dates:
                self.stdout.write(f"  {current} SKIP (already ingested)")
                current += timedelta(days=1)
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  {current} DRY-RUN")
                current += timedelta(days=1)
                processed += 1
                continue

            self.stdout.write(f"Processing {current}...")
            temp_dir = Path(settings.NWM_TEMP_DIR) / current.strftime("%Y%m%d")
            temp_dir.mkdir(parents=True, exist_ok=True)
            downloaded = []
            failed_hours = []

            try:
                for hour in range(24):
                    url = build_s3_url(settings.NWM_S3_BASE, current, hour)
                    dest = temp_dir / f"nwm_t{hour:02d}z.nc"
                    try:
                        download_file(url, dest)
                        downloaded.append((hour, dest))
                    except Exception as exc:
                        logger.debug("Hour %02d failed: %s", hour, exc)
                        failed_hours.append(hour)

                if not downloaded:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  {current} — all 24 hours unavailable on S3, skipping"
                        )
                    )
                    current += timedelta(days=1)
                    continue

                dl_map = {h: p for h, p in downloaded}
                last_good = downloaded[0][1]
                ordered = []
                for h in range(24):
                    ordered.append(dl_map.get(h, last_good))
                    if h in dl_map:
                        last_good = dl_map[h]

                n = ingest_day(current, ordered)
                status = "success" if not failed_hours else "partial"
                NWMIngestionLog.objects.update_or_create(
                    ingest_date=current,
                    defaults={
                        "stations_updated": n,
                        "status": status,
                        "error_message": f"Missing hours: {failed_hours}" if failed_hours else "",
                    },
                )
                self.stdout.write(
                    self.style.SUCCESS(f"  {current} — {n} stations ({status})")
                )
                processed += 1

            except Exception as exc:
                logger.error("Failed to process %s: %s", current, exc)
                self.stdout.write(self.style.ERROR(f"  {current} — ERROR: {exc}"))
                NWMIngestionLog.objects.update_or_create(
                    ingest_date=current,
                    defaults={"stations_updated": 0, "status": "failed", "error_message": str(exc)},
                )

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

            current += timedelta(days=1)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nBackfill complete: {processed} processed, {skipped} skipped."
            )
        )
