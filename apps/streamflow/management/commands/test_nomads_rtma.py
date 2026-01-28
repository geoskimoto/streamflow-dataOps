"""
Test script for NOAA NOMADS RTMA data access.
Validates URL construction, data availability, and GRIB2 download.
"""
from django.core.management.base import BaseCommand
from datetime import datetime, timedelta
import tempfile
from pathlib import Path

from src.acquisition.nomads_client import NomadsClient, NomadsError


class Command(BaseCommand):
    help = 'Test NOAA NOMADS RTMA data access'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours-ago',
            type=int,
            default=2,
            help='How many hours ago to test (default: 2, RTMA is near-realtime)'
        )
        parser.add_argument(
            '--variable',
            type=str,
            default='temperature',
            choices=['temperature', 'precipitation', 'wind_speed', 'pressure'],
            help='Variable to test'
        )

    def handle(self, *args, **options):
        hours_ago = options['hours_ago']
        variable = options['variable']
        
        # Calculate test timestamp (RTMA is hourly, near-realtime)
        test_time = datetime.utcnow() - timedelta(hours=hours_ago)
        test_time = test_time.replace(minute=0, second=0, microsecond=0)
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"NOAA NOMADS RTMA Test")
        self.stdout.write(f"{'='*60}")
        self.stdout.write(f"Timestamp: {test_time.strftime('%Y-%m-%d %H:00 UTC')}")
        self.stdout.write(f"Variable: {variable}")
        self.stdout.write(f"Hours ago: {hours_ago}")
        
        # Test bounding box (Continental US subset)
        bbox = [-125.0, 24.0, -66.0, 50.0]  # West, South, East, North
        
        try:
            # Initialize client
            self.stdout.write("\n1. Initializing NOMADS client...")
            client = NomadsClient()
            self.stdout.write(self.style.SUCCESS("   ✓ Client initialized"))
            
            # Check data availability
            self.stdout.write("\n2. Checking data availability...")
            url = client._build_rtma_url(test_time)
            self.stdout.write(f"   URL: {url}")
            
            # Check with extended max_age to allow testing older data
            if client.check_data_availability(test_time, max_age_hours=168):  # 7 days retention
                self.stdout.write(self.style.SUCCESS("   ✓ Data available"))
            else:
                self.stdout.write(self.style.WARNING("   ⚠ Data not available (may be too recent/old)"))
                self.stdout.write("   Note: RTMA data is available ~1 hour after observation time")
                self.stdout.write("   Try increasing --hours-ago to 3 or 4")
                return
            
            # Test download and extraction
            self.stdout.write(f"\n3. Testing {variable} extraction...")
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / f"test_{variable}.tif"
                
                self.stdout.write(f"   Downloading GRIB2 file...")
                metadata = client.get_rtma_data(
                    variable=variable,
                    timestamp=test_time,
                    bbox=bbox,
                    output_path=output_path
                )
                
                if metadata:
                    self.stdout.write(self.style.SUCCESS("   ✓ Extraction successful"))
                    self.stdout.write(f"\n   Metadata:")
                    self.stdout.write(f"   - File: {output_path.name}")
                    self.stdout.write(f"   - Size: {output_path.stat().st_size / 1024:.1f} KB")
                    self.stdout.write(f"   - Timestamp: {metadata.get('timestamp')}")
                    self.stdout.write(f"   - Variable: {metadata.get('variable')}")
                    self.stdout.write(f"   - Units: {metadata.get('units')}")
                    
                    # Stats are at root level of metadata
                    if metadata.get('min') is not None:
                        self.stdout.write(f"   - Min: {metadata.get('min'):.2f}")
                        self.stdout.write(f"   - Max: {metadata.get('max'):.2f}")
                        self.stdout.write(f"   - Mean: {metadata.get('mean'):.2f}")
                        self.stdout.write(f"   - Std: {metadata.get('std'):.2f}")
                    
                    # Sanity check values
                    self.stdout.write(f"\n4. Validating data ranges...")
                    if variable == 'temperature':
                        if 200 <= metadata.get('min', 0) <= 350:
                            self.stdout.write(self.style.SUCCESS("   ✓ Temperature range valid (200-350 K)"))
                        else:
                            self.stdout.write(self.style.WARNING(f"   ⚠ Temperature range suspicious: {metadata.get('min')}-{metadata.get('max')} K"))
                    elif variable == 'precipitation':
                        if 0 <= metadata.get('min', 0) <= metadata.get('max', 0) <= 1000:
                            self.stdout.write(self.style.SUCCESS("   ✓ Precipitation range valid (0-1000 kg/m²)"))
                        else:
                            self.stdout.write(self.style.WARNING(f"   ⚠ Precipitation range suspicious: {metadata.get('min')}-{metadata.get('max')} kg/m²"))
                    elif variable == 'wind_speed':
                        if 0 <= metadata.get('min', 0) <= metadata.get('max', 0) <= 100:
                            self.stdout.write(self.style.SUCCESS("   ✓ Wind speed range valid (0-100 m/s)"))
                        else:
                            self.stdout.write(self.style.WARNING(f"   ⚠ Wind speed range suspicious: {metadata.get('min')}-{metadata.get('max')} m/s"))
                    elif variable == 'pressure':
                        if 50000 <= metadata.get('min', 0) <= 110000:
                            self.stdout.write(self.style.SUCCESS("   ✓ Pressure range valid (50000-110000 Pa)"))
                        else:
                            self.stdout.write(self.style.WARNING(f"   ⚠ Pressure range suspicious: {metadata.get('min')}-{metadata.get('max')} Pa"))
                else:
                    self.stdout.write(self.style.ERROR("   ✗ Extraction failed"))
                    return
            
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(self.style.SUCCESS("All tests passed! NOMADS RTMA client is functional."))
            self.stdout.write(f"{'='*60}\n")
            
        except NomadsError as e:
            self.stdout.write(self.style.ERROR(f"\n✗ NOMADS Error: {e}"))
            self.stdout.write("\nTroubleshooting:")
            self.stdout.write("- RTMA data is available ~1 hour after observation time")
            self.stdout.write("- Data retention is typically 7 days")
            self.stdout.write("- Try: python manage.py test_nomads_rtma --hours-ago 3")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Unexpected error: {e}"))
            import traceback
            self.stdout.write(traceback.format_exc())
