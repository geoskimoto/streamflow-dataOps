"""
Management command to sync Station.is_active based on recent discharge observations.

A station is Active if it has any discharge observation within the last 6 months.
All other stations (no observations, or last observation > 6 months ago) are Inactive.

This command is lightweight — it uses the (station_id, observed_at, type) index and
runs a single SQL UPDATE rather than per-station queries. Typically completes in < 10s.

Run daily via Celery beat. Also callable directly for immediate one-off fixes.
"""

from django.core.management.base import BaseCommand
from django.db import connection


MONTHS_BACK = 6


class Command(BaseCommand):
    help = "Sync Station.is_active from discharge_observations (last 6 months)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without updating the database",
        )
        parser.add_argument(
            "--months",
            type=int,
            default=MONTHS_BACK,
            help=f"Months to look back for recent observations (default: {MONTHS_BACK})",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        months = options["months"]

        self.stdout.write("=" * 60)
        self.stdout.write("SYNC STATION ACTIVITY")
        if dry_run:
            self.stdout.write(self.style.WARNING("(DRY RUN — no changes made)"))
        self.stdout.write("=" * 60)

        with connection.cursor() as cursor:
            # Count what would change before touching anything
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN would_be_active AND NOT is_active THEN 1 ELSE 0 END) AS to_activate,
                    SUM(CASE WHEN NOT would_be_active AND is_active THEN 1 ELSE 0 END)  AS to_deactivate,
                    SUM(CASE WHEN would_be_active THEN 1 ELSE 0 END)                    AS total_active,
                    SUM(CASE WHEN NOT would_be_active THEN 1 ELSE 0 END)                AS total_inactive
                FROM (
                    SELECT
                        s.id,
                        s.is_active,
                        EXISTS (
                            SELECT 1 FROM discharge_observations o
                            WHERE o.station_id = s.id
                              AND o.observed_at >= NOW() - INTERVAL %(months)s
                        ) AS would_be_active
                    FROM stations s
                ) sub
            """, {"months": f"{months} months"})

            row = cursor.fetchone()
            to_activate, to_deactivate, total_active, total_inactive = row

        self.stdout.write(f"Stations that would become Active:   {to_activate}")
        self.stdout.write(f"Stations that would become Inactive: {to_deactivate}")
        self.stdout.write(f"Total Active after sync:             {total_active}")
        self.stdout.write(f"Total Inactive after sync:           {total_inactive}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run complete — no changes made."))
            self.stdout.write("Run without --dry-run to apply.")
            return

        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE stations s
                SET is_active = EXISTS (
                    SELECT 1 FROM discharge_observations o
                    WHERE o.station_id = s.id
                      AND o.observed_at >= NOW() - INTERVAL %(months)s
                )
            """, {"months": f"{months} months"})
            updated = cursor.rowcount

        self.stdout.write(self.style.SUCCESS(f"\nUpdated {updated} station records."))
        self.stdout.write("=" * 60)
