"""Management command to import British Columbia stations from Environment Canada into MasterStation table."""

from django.core.management.base import BaseCommand
from django.db import transaction
from apps.streamflow.models import MasterStation
from src.acquisition.canada_client import CanadaClient
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import British Columbia hydrometric stations from Environment Canada API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--province",
            type=str,
            default="BC",
            help="Province code to import (default: BC)",
        )
        parser.add_argument(
            "--active-only",
            action="store_true",
            help="Only import stations with REAL_TIME=1 (active real-time monitoring)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=5000,
            help="Maximum number of stations to fetch (default: 5000)",
        )

    def handle(self, *args, **options):
        province = options["province"]
        active_only = options["active_only"]
        limit = options["limit"]

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*70}\n"
                f"Importing {province} stations from Environment Canada\n"
                f"{'='*70}\n"
            )
        )

        client = CanadaClient()

        try:
            # Fetch all stations for the province
            self.stdout.write(f"Fetching stations from API (limit={limit})...")
            stations = client.get_stations_by_province(province, limit=limit)

            if not stations:
                self.stdout.write(
                    self.style.WARNING(f"No stations found for province {province}")
                )
                return

            self.stdout.write(
                self.style.SUCCESS(f"✓ Fetched {len(stations)} stations from API")
            )

            # Filter active stations if requested
            if active_only:
                stations = [s for s in stations if s.get("real_time") == 1]
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Filtered to {len(stations)} active real-time stations"
                    )
                )

            # Import stations into MasterStation table
            created_count = 0
            updated_count = 0
            skipped_count = 0
            error_count = 0

            self.stdout.write("\nImporting stations into MasterStation table...")

            with transaction.atomic():
                for station_data in stations:
                    try:
                        station_number = station_data.get("station_number")
                        if not station_number:
                            skipped_count += 1
                            continue

                        # Check if station already exists
                        master_station, created = MasterStation.objects.get_or_create(
                            station_number=station_number,
                            defaults={
                                "station_name": station_data.get("name", "")[:255],
                                "latitude": station_data.get("latitude"),
                                "longitude": station_data.get("longitude"),
                                "state_code": station_data.get("state", ""),
                                "drainage_area_sqmi": (
                                    # EC provides drainage area in sq km, convert to sq mi
                                    float(station_data["drainage_area"]) * 0.386102
                                    if station_data.get("drainage_area")
                                    else None
                                ),
                                "agency": "EC",  # Environment Canada
                            },
                        )

                        if created:
                            created_count += 1
                            if created_count % 100 == 0:
                                self.stdout.write(f"  ... {created_count} stations created")
                        else:
                            # Update existing station with latest data
                            updated = False
                            
                            if master_station.station_name != station_data.get("name", "")[:255]:
                                master_station.station_name = station_data.get("name", "")[:255]
                                updated = True
                            
                            if station_data.get("latitude") and master_station.latitude != station_data["latitude"]:
                                master_station.latitude = station_data["latitude"]
                                updated = True
                            
                            if station_data.get("longitude") and master_station.longitude != station_data["longitude"]:
                                master_station.longitude = station_data["longitude"]
                                updated = True
                            
                            if station_data.get("state") and master_station.state_code != station_data["state"]:
                                master_station.state_code = station_data["state"]
                                updated = True
                            
                            drainage_area_sqmi = (
                                float(station_data["drainage_area"]) * 0.386102
                                if station_data.get("drainage_area")
                                else None
                            )
                            if drainage_area_sqmi and master_station.drainage_area_sqmi != drainage_area_sqmi:
                                master_station.drainage_area_sqmi = drainage_area_sqmi
                                updated = True
                            
                            if updated:
                                master_station.save()
                                updated_count += 1

                    except Exception as e:
                        error_count += 1
                        logger.error(f"Error importing station {station_number}: {e}")
                        continue

            # Print summary
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n{'='*70}\n"
                    f"Import Summary\n"
                    f"{'='*70}\n"
                    f"✓ Created: {created_count} new stations\n"
                    f"✓ Updated: {updated_count} existing stations\n"
                    f"  Skipped: {skipped_count} stations (missing data)\n"
                )
            )

            if error_count > 0:
                self.stdout.write(
                    self.style.WARNING(f"  Errors: {error_count} stations failed")
                )

            # Show current totals
            total_ec = MasterStation.objects.filter(agency="EC").count()
            total_bc = MasterStation.objects.filter(
                agency="EC", state_code=province
            ).count()
            total_all = MasterStation.objects.count()

            self.stdout.write(
                f"\nMasterStation table now contains:\n"
                f"  • {total_bc} {province} stations (EC)\n"
                f"  • {total_ec} total EC stations\n"
                f"  • {total_all} total stations (all agencies)\n"
            )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"\n✗ Error: {e}")
            )
            logger.exception("Error importing BC stations")
            raise
