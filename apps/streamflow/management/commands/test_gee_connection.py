"""Management command to test GEE connection."""

from django.core.management.base import BaseCommand
from django.conf import settings
from datetime import datetime, timedelta

from src.acquisition.gee_client import GEEClient, GEEAuthenticationError


class Command(BaseCommand):
    """Test Google Earth Engine connection and data availability."""
    
    help = 'Test GEE authentication and data availability'
    
    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            '--dataset',
            type=str,
            default='RTMA',
            choices=['RTMA', 'SMAP_SPL4'],
            help='Dataset to test'
        )
        parser.add_argument(
            '--days-back',
            type=int,
            default=7,
            help='Check availability for last N days'
        )
    
    def handle(self, *args, **options):
        """Execute command."""
        dataset = options['dataset']
        days_back = options['days_back']
        
        self.stdout.write("=" * 80)
        self.stdout.write(f"Testing Google Earth Engine Connection")
        self.stdout.write("=" * 80)
        
        # Initialize client
        try:
            client = GEEClient()
            self.stdout.write(self.style.SUCCESS("\n✓ GEE client initialized successfully"))
            
            if client.authenticated:
                self.stdout.write(self.style.SUCCESS("✓ GEE authentication successful"))
            else:
                self.stdout.write(self.style.ERROR("✗ GEE authentication failed"))
                return
        except GEEAuthenticationError as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Authentication error: {e}"))
            self.stdout.write("\nTroubleshooting:")
            self.stdout.write("  1. Check if GEE service account key is configured:")
            self.stdout.write(f"     GEE_SERVICE_ACCOUNT_KEY = {settings.GEE_SERVICE_ACCOUNT_KEY or 'Not set'}")
            self.stdout.write("  2. Try authenticating manually:")
            self.stdout.write("     earthengine authenticate")
            self.stdout.write("  3. Verify service account has GEE access")
            return
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Error: {e}"))
            return
        
        # Test data availability
        self.stdout.write(f"\nTesting {dataset} data availability...")
        
        collection_id = settings.GEE_DATASETS.get(dataset)
        if not collection_id:
            self.stdout.write(self.style.ERROR(f"✗ Dataset not found in settings: {dataset}"))
            return
        
        self.stdout.write(f"  Collection ID: {collection_id}")
        
        # Check recent data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        bbox = settings.HUC17_BBOX  # Use HUC17 for testing
        
        try:
            self.stdout.write(f"  Date range: {start_date.date()} to {end_date.date()}")
            self.stdout.write(f"  Bounding box: {bbox}")
            
            availability = client.check_data_availability(
                collection_id=collection_id,
                start_date=start_date,
                end_date=end_date,
                bbox=bbox
            )
            
            if availability['available']:
                self.stdout.write(self.style.SUCCESS(f"\n✓ Data is available"))
                self.stdout.write(f"  Image count: {availability['count']}")
                self.stdout.write(f"  First date: {availability['first_date']}")
                self.stdout.write(f"  Last date: {availability['last_date']}")
            else:
                self.stdout.write(self.style.WARNING(f"\n⚠ No data available for specified range"))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Error checking availability: {e}"))
            return
        
        # Test fetching a recent image
        if dataset == 'RTMA':
            self.stdout.write(f"\nTesting RTMA temperature image fetch...")
            try:
                # Try to fetch yesterday's data at noon
                test_time = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
                
                image = client.get_rtma_image(
                    variable='temperature',
                    timestamp=test_time,
                    bbox=bbox,
                    resolution=2500
                )
                
                if image:
                    self.stdout.write(self.style.SUCCESS(f"✓ Successfully fetched RTMA image for {test_time}"))
                    
                    # Get statistics
                    stats = client.get_image_statistics(image, bbox, scale=2500)
                    if stats:
                        self.stdout.write(f"  Temperature statistics:")
                        self.stdout.write(f"    Min: {stats['min']:.2f} K")
                        self.stdout.write(f"    Max: {stats['max']:.2f} K")
                        self.stdout.write(f"    Mean: {stats['mean']:.2f} K")
                        self.stdout.write(f"    Std Dev: {stats['std_dev']:.2f} K")
                else:
                    self.stdout.write(self.style.WARNING(f"⚠ No image found for {test_time}"))
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Error fetching image: {e}"))
        
        elif dataset == 'SMAP_SPL4':
            self.stdout.write(f"\nTesting SMAP soil moisture image fetch...")
            try:
                # Try to fetch yesterday's data
                test_date = (datetime.now() - timedelta(days=1)).date()
                
                image = client.get_smap_image(
                    variable='soil_moisture_surface',
                    date=test_date,
                    bbox=bbox,
                    resolution=9000
                )
                
                if image:
                    self.stdout.write(self.style.SUCCESS(f"✓ Successfully fetched SMAP image for {test_date}"))
                    
                    # Get statistics
                    stats = client.get_image_statistics(image, bbox, scale=9000)
                    if stats:
                        self.stdout.write(f"  Soil moisture statistics:")
                        self.stdout.write(f"    Min: {stats['min']:.3f} m³/m³")
                        self.stdout.write(f"    Max: {stats['max']:.3f} m³/m³")
                        self.stdout.write(f"    Mean: {stats['mean']:.3f} m³/m³")
                        self.stdout.write(f"    Std Dev: {stats['std_dev']:.3f} m³/m³")
                else:
                    self.stdout.write(self.style.WARNING(f"⚠ No image found for {test_date}"))
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Error fetching image: {e}"))
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("GEE connection test complete!"))
        self.stdout.write("=" * 80)
