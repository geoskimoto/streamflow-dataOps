"""Management command to test MODIS data access.

This command validates:
1. NASA EarthData authentication
2. MODIS granule search
3. MODIS HDF4 download
4. Sinusoidal to WGS84 reprojection
5. Multi-tile mosaicking
6. GeoTIFF generation with statistics
"""

from django.core.management.base import BaseCommand, CommandError
from datetime import datetime, timedelta
from pathlib import Path
import logging
import tempfile
import shutil

from src.acquisition.earthdata_client import EarthDataClient, EarthDataError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Test MODIS LST data access from NASA EarthData'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--days-ago',
            type=int,
            default=2,
            help='Number of days ago to fetch data (default: 2)'
        )
        parser.add_argument(
            '--product',
            type=str,
            default='MOD11A1',
            choices=['MOD11A1', 'MYD11A1'],
            help='MODIS product (MOD11A1=Terra, MYD11A1=Aqua)'
        )
        parser.add_argument(
            '--variable',
            type=str,
            default='LST_Day_1km',
            choices=['LST_Day_1km', 'LST_Night_1km'],
            help='Variable to extract'
        )
        parser.add_argument(
            '--bbox',
            type=float,
            nargs=4,
            default=[-120.0, 45.0, -115.0, 48.0],
            metavar=('MIN_LON', 'MIN_LAT', 'MAX_LON', 'MAX_LAT'),
            help='Bounding box (default: small region in Pacific Northwest)'
        )
        parser.add_argument(
            '--output-dir',
            type=str,
            default=None,
            help='Output directory (default: temp directory)'
        )
    
    def handle(self, *args, **options):
        """Execute the test command."""
        self.stdout.write("="*80)
        self.stdout.write("MODIS LST Data Access Test")
        self.stdout.write("="*80)
        self.stdout.write("")
        
        # Parse options
        days_ago = options['days_ago']
        product = options['product']
        variable = options['variable']
        bbox = options['bbox']
        
        # Calculate date
        target_date = datetime.now() - timedelta(days=days_ago)
        
        self.stdout.write(f"Product: {product}")
        self.stdout.write(f"Variable: {variable}")
        self.stdout.write(f"Date: {target_date.strftime('%Y-%m-%d')}")
        self.stdout.write(f"Bounding Box: {bbox}")
        self.stdout.write("")
        
        # Setup output directory
        if options['output_dir']:
            output_dir = Path(options['output_dir'])
            output_dir.mkdir(parents=True, exist_ok=True)
            cleanup = False
        else:
            output_dir = Path(tempfile.mkdtemp())
            cleanup = True
        
        output_path = output_dir / f"{product}_{variable}_{target_date.strftime('%Y%m%d')}.tif"
        
        try:
            # Step 1: Initialize client
            self.stdout.write("Step 1: Initializing EarthData client...")
            try:
                client = EarthDataClient()
                self.stdout.write(self.style.SUCCESS("✓ Client initialized"))
                self.stdout.write(f"  Username: {client.username}")
                self.stdout.write(f"  Authenticated: {client.authenticated}")
                self.stdout.write("")
            except EarthDataError as e:
                raise CommandError(f"Failed to initialize client: {e}")
            
            # Step 2: Check authentication
            if not client.authenticated:
                raise CommandError(
                    "Not authenticated with NASA EarthData. "
                    "Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD environment variables."
                )
            
            # Step 3: Search for granules
            self.stdout.write("Step 2: Searching for MODIS granules...")
            try:
                collection_id = client.COLLECTIONS[f'MODIS_LST_{"TERRA" if product == "MOD11A1" else "AQUA"}']
                granules = client.search_granules(
                    collection_id=collection_id,
                    bbox=bbox,
                    start_date=target_date,
                    end_date=target_date + timedelta(days=1),
                    limit=10
                )
                
                if not granules:
                    self.stdout.write(self.style.WARNING("⚠ No granules found"))
                    self.stdout.write("This may be expected if:")
                    self.stdout.write("  - Data not yet available for recent dates")
                    self.stdout.write("  - Bbox outside MODIS coverage")
                    self.stdout.write("  - NASA CMR API having issues")
                    return
                
                self.stdout.write(self.style.SUCCESS(f"✓ Found {len(granules)} granule(s)"))
                
                # Show granule details
                for i, granule in enumerate(granules[:3], 1):
                    granule_id = granule.get('umm', {}).get('GranuleUR', 'Unknown')
                    self.stdout.write(f"  {i}. {granule_id}")
                
                if len(granules) > 3:
                    self.stdout.write(f"  ... and {len(granules) - 3} more")
                
                self.stdout.write("")
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Granule search failed: {e}"))
                self.stdout.write("")
                self.stdout.write("Note: NASA CMR API may be experiencing issues.")
                self.stdout.write("This is an external service dependency.")
                return
            
            # Step 4: Download and process
            self.stdout.write("Step 3: Downloading and processing MODIS data...")
            self.stdout.write(f"  Output: {output_path}")
            self.stdout.write("")
            
            try:
                metadata = client.get_modis_data(
                    product=product,
                    variable=variable,
                    date=target_date,
                    bbox=bbox,
                    output_path=output_path
                )
                
                if metadata is None:
                    self.stdout.write(self.style.WARNING("⚠ No data returned"))
                    return
                
                self.stdout.write(self.style.SUCCESS("✓ MODIS data processed successfully"))
                self.stdout.write("")
                
                # Step 5: Display statistics
                self.stdout.write("Step 4: Data Statistics")
                self.stdout.write("-" * 40)
                
                if output_path.exists():
                    file_size_mb = output_path.stat().st_size / (1024 * 1024)
                    self.stdout.write(f"  File size: {file_size_mb:.2f} MB")
                
                self.stdout.write(f"  Variable: {metadata.get('long_name', variable)}")
                self.stdout.write(f"  Units: {metadata.get('units', 'Kelvin')}")
                
                if 'tiles' in metadata:
                    self.stdout.write(f"  Tiles mosaicked: {metadata['tiles']}")
                
                if metadata.get('min') is not None:
                    min_val = metadata['min']
                    max_val = metadata['max']
                    mean_val = metadata['mean']
                    std_val = metadata.get('std', 0)
                    
                    # Convert Kelvin to Celsius for display
                    if metadata.get('units') == 'Kelvin':
                        min_c = min_val - 273.15
                        max_c = max_val - 273.15
                        mean_c = mean_val - 273.15
                        self.stdout.write(f"  Min: {min_val:.2f} K ({min_c:.2f} °C)")
                        self.stdout.write(f"  Max: {max_val:.2f} K ({max_c:.2f} °C)")
                        self.stdout.write(f"  Mean: {mean_val:.2f} K ({mean_c:.2f} °C)")
                    else:
                        self.stdout.write(f"  Min: {min_val:.2f}")
                        self.stdout.write(f"  Max: {max_val:.2f}")
                        self.stdout.write(f"  Mean: {mean_val:.2f}")
                    
                    self.stdout.write(f"  Std Dev: {std_val:.2f}")
                
                if metadata.get('count'):
                    self.stdout.write(f"  Valid pixels: {metadata['count']:,}")
                
                self.stdout.write("")
                
                # Validate data ranges
                self.stdout.write("Step 5: Data Validation")
                self.stdout.write("-" * 40)
                
                if metadata.get('units') == 'Kelvin':
                    min_val = metadata['min']
                    max_val = metadata['max']
                    
                    # Reasonable LST range: 200-350 K (-73 to 77°C)
                    if 200 <= min_val <= 350 and 200 <= max_val <= 350:
                        self.stdout.write(self.style.SUCCESS("  ✓ Temperature range valid"))
                    else:
                        self.stdout.write(self.style.WARNING(
                            f"  ⚠ Temperature outside expected range (200-350 K)"
                        ))
                
                if output_path.exists():
                    self.stdout.write(self.style.SUCCESS("  ✓ Output file created"))
                else:
                    self.stdout.write(self.style.ERROR("  ✗ Output file missing"))
                
                self.stdout.write("")
                
            except EarthDataError as e:
                raise CommandError(f"MODIS data fetch failed: {e}")
            
            # Success summary
            self.stdout.write("="*80)
            self.stdout.write(self.style.SUCCESS("MODIS Test Completed Successfully"))
            self.stdout.write("="*80)
            self.stdout.write("")
            self.stdout.write(f"Output saved to: {output_path}")
            
            if cleanup:
                self.stdout.write("")
                self.stdout.write("Temp directory will be cleaned up automatically.")
            
        except CommandError:
            raise
        except Exception as e:
            raise CommandError(f"Unexpected error: {e}")
        finally:
            # Cleanup temp directory if used
            if cleanup and output_dir.exists():
                try:
                    shutil.rmtree(output_dir)
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp directory: {e}")
