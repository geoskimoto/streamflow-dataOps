"""Management command to create PullConfigurations for EC WaterOffice gap fill."""

from django.core.management.base import BaseCommand
from django.db.models import OuterRef, Subquery
from django.utils import timezone as dj_timezone
from datetime import datetime, date
import pytz

from apps.streamflow.models import (
    Station,
    DischargeObservation,
    PullConfiguration,
    PullConfigurationStation,
)


class Command(BaseCommand):
    help = (
        "Create PullConfigurations to back-fill the EC HYDAT data gap (2025-01-01 → today) "
        "and keep EC daily data current via a recurring job."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be done without writing to the database.",
        )
        parser.add_argument(
            "--gap-date",
            type=str,
            default="2024-12-31",
            help=(
                "The last date for which HYDAT data exists (YYYY-MM-DD). "
                "Stations whose latest daily_mean observation falls on this date "
                "will be enrolled. Default: 2024-12-31"
            ),
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default="2025-01-01",
            help=(
                "Start date for the gap-fill pull (YYYY-MM-DD). "
                "Default: 2025-01-01"
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        gap_date = date.fromisoformat(options["gap_date"])
        start_date = datetime.fromisoformat(options["start_date"]).replace(
            hour=0, minute=0, second=0, tzinfo=pytz.UTC
        )
        today = datetime.now(pytz.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily_start = today - __import__("datetime").timedelta(days=2)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*70}\n"
                f"EC WaterOffice Gap Fill Configuration Creator\n"
                f"{'='*70}\n"
                f"  Gap date   : {gap_date}\n"
                f"  Start date : {start_date.date()}\n"
                f"  Dry run    : {dry_run}\n"
                f"{'='*70}\n"
            )
        )

        # ── 1. Discover gap stations ─────────────────────────────────────────
        self.stdout.write("Discovering EC stations whose last daily_mean = gap_date ...")

        latest_obs_sq = (
            DischargeObservation.objects.filter(
                station=OuterRef("pk"), type="daily_mean"
            )
            .order_by("-observed_at")
            .values("observed_at")[:1]
        )

        stations = list(
            Station.objects.filter(agency="EC")
            .annotate(last_obs_at=Subquery(latest_obs_sq))
            .filter(last_obs_at__date=gap_date)
        )

        self.stdout.write(
            self.style.SUCCESS(f"  Found {len(stations)} stations with last obs on {gap_date}")
        )

        if not stations:
            self.stdout.write(
                self.style.WARNING(
                    "No stations found — nothing to do. "
                    "Check that EC HYDAT daily_mean data has been loaded and that "
                    "--gap-date matches the last populated date."
                )
            )
            return

        if dry_run:
            self.stdout.write("\nStation list (dry run — first 20 shown):")
            for s in stations[:20]:
                self.stdout.write(f"  {s.station_number}  {s.name}")
            if len(stations) > 20:
                self.stdout.write(f"  ... and {len(stations) - 20} more")
            self.stdout.write(
                self.style.WARNING(
                    "\nDry run complete — no changes written. "
                    "Re-run without --dry-run to create configurations."
                )
            )
            return

        # ── 2. Create gap-fill configuration ────────────────────────────────
        gap_config, gap_created = PullConfiguration.objects.get_or_create(
            name="EC Gap Fill 2025+ (BC)",
            defaults={
                "data_source": "EC",
                "data_type": "ec_realtime_daily",
                "data_strategy": "append",
                "pull_start_date": start_date,
                "is_enabled": True,
                "schedule_type": "custom",
                "schedule_value": "0 6 * * *",
                "next_run_at": None,  # fires immediately on first dispatcher tick
            },
        )
        action = "Created" if gap_created else "Already exists"
        self.stdout.write(
            self.style.SUCCESS(
                f"  {action}: 'EC Gap Fill 2025+ (BC)'  (id={gap_config.pk})"
            )
        )

        # ── 3. Create daily current configuration ───────────────────────────
        daily_config, daily_created = PullConfiguration.objects.get_or_create(
            name="EC Daily Current (BC)",
            defaults={
                "data_source": "EC",
                "data_type": "ec_realtime_daily",
                "data_strategy": "append",
                "pull_start_date": daily_start,
                "is_enabled": True,
                "schedule_type": "custom",
                "schedule_value": "0 6 * * *",
                "next_run_at": None,
            },
        )
        action = "Created" if daily_created else "Already exists"
        self.stdout.write(
            self.style.SUCCESS(
                f"  {action}: 'EC Daily Current (BC)'    (id={daily_config.pk})"
            )
        )

        # ── 4. Enroll stations in both configurations ────────────────────────
        self.stdout.write(
            f"\nEnrolling {len(stations)} stations in both configurations ..."
        )

        gap_added = 0
        daily_added = 0

        for station in stations:
            station_kwargs = {
                "station_number": station.station_number,
                "station_name": station.name or "",
                "state": station.state or "",
                "huc_code": station.huc_code or "",
            }

            _, created = PullConfigurationStation.objects.get_or_create(
                configuration=gap_config,
                station_number=station.station_number,
                defaults=station_kwargs,
            )
            if created:
                gap_added += 1

            _, created = PullConfigurationStation.objects.get_or_create(
                configuration=daily_config,
                station_number=station.station_number,
                defaults=station_kwargs,
            )
            if created:
                daily_added += 1

        # ── 5. Print summary ─────────────────────────────────────────────────
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*70}\n"
                f"Summary\n"
                f"{'='*70}\n"
                f"  Gap-fill config  (id={gap_config.pk}): "
                f"{gap_added} stations added\n"
                f"  Daily config     (id={daily_config.pk}): "
                f"{daily_added} stations added\n"
                f"\nNext steps:\n"
                f"  1. The Celery dispatcher (scheduled_streamflow_pulls) runs every\n"
                f"     5 minutes. 'EC Gap Fill 2025+ (BC)' will fire automatically\n"
                f"     within the next 5 minutes (next_run_at=NULL).\n"
                f"  2. Monitor progress: Django admin > Data Pull Logs\n"
                f"  3. After gap-fill completes, disable 'EC Gap Fill 2025+ (BC)'\n"
                f"     in Django admin to prevent repeated re-runs.\n"
                f"  4. 'EC Daily Current (BC)' will continue to run at 06:00 UTC daily.\n"
                f"{'='*70}\n"
            )
        )
