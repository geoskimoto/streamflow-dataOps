"""Management command to populate StationMapping table with Station to MasterStation lookups."""

from django.core.management.base import BaseCommand
from django.db import transaction
from apps.streamflow.models import Station, MasterStation, StationMapping
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create StationMapping records linking Station to MasterStation for RFC lookups"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing StationMapping records before populating",
        )

    def handle(self, *args, **options):
        clear_existing = options["clear"]

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*70}\n"
                f"Populating StationMapping Table\n"
                f"{'='*70}\n"
            )
        )

        # Clear existing mappings if requested
        if clear_existing:
            existing_count = StationMapping.objects.count()
            StationMapping.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f"✓ Cleared {existing_count} existing mappings")
            )

        # Get all Station records
        stations = Station.objects.all()
        total_stations = stations.count()

        self.stdout.write(f"\nProcessing {total_stations} Station records...")

        created_count = 0
        already_exists_count = 0
        no_match_count = 0
        no_match_stations = []

        with transaction.atomic():
            for station in stations:
                try:
                    # Try to find matching MasterStation by station_number
                    master_station = MasterStation.objects.filter(
                        station_number=station.station_number
                    ).first()

                    if not master_station:
                        no_match_count += 1
                        no_match_stations.append(
                            f"{station.station_number} ({station.agency})"
                        )
                        continue

                    # Create mapping using agency:id format
                    # Source = Station (working data), Target = MasterStation (catalog)
                    mapping, created = StationMapping.objects.get_or_create(
                        source_agency="STATION",
                        source_id=station.station_number,
                        target_agency="MASTER",
                        defaults={
                            "target_id": master_station.station_number,
                        }
                    )

                    if created:
                        created_count += 1
                        if created_count % 50 == 0:
                            self.stdout.write(f"  ... {created_count} mappings created")
                    else:
                        already_exists_count += 1

                except Exception as e:
                    logger.error(
                        f"Error creating mapping for {station.station_number}: {e}"
                    )
                    continue

        # Print summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*70}\n"
                f"StationMapping Summary\n"
                f"{'='*70}\n"
                f"✓ Created: {created_count} new mappings\n"
                f"  Already existed: {already_exists_count} mappings\n"
            )
        )

        if no_match_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"  No match: {no_match_count} stations (no MasterStation found)"
                )
            )

            if no_match_count <= 20:
                self.stdout.write("\nStations without MasterStation match:")
                for station_info in no_match_stations:
                    self.stdout.write(f"  • {station_info}")
            else:
                self.stdout.write(
                    f"\nFirst 20 stations without MasterStation match:"
                )
                for station_info in no_match_stations[:20]:
                    self.stdout.write(f"  • {station_info}")
                self.stdout.write(
                    f"  ... and {no_match_count - 20} more (run with --clear to see all)"
                )

        # Show current totals
        total_mappings = StationMapping.objects.count()
        total_source_mapped = (
            StationMapping.objects.filter(
                source_agency="STATION"
            ).values("source_id").distinct().count()
        )
        total_target_mapped = (
            StationMapping.objects.filter(
                target_agency="MASTER"
            ).values("target_id").distinct().count()
        )

        self.stdout.write(
            f"\nStationMapping table now contains:\n"
            f"  • {total_mappings} total mappings\n"
            f"  • {total_source_mapped} unique Station records mapped\n"
            f"  • {total_target_mapped} unique MasterStation records mapped\n"
        )

        # Show RFC distribution by joining with MasterStation
        self.stdout.write("\nRFC code distribution in mapped stations:")
        
        rfc_stats = {}
        for mapping in StationMapping.objects.filter(target_agency="MASTER"):
            master = MasterStation.objects.filter(
                station_number=mapping.target_id
            ).first()
            if master:
                rfc = master.rfc_code or "None"
                rfc_stats[rfc] = rfc_stats.get(rfc, 0) + 1

        for rfc, count in sorted(rfc_stats.items(), key=lambda x: x[1], reverse=True):
            self.stdout.write(f"  • {rfc}: {count} stations")

        if created_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Successfully populated StationMapping table!\n"
                    f"  The RFC filter should now work correctly.\n"
                )
            )
