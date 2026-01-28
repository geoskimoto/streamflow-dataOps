"""Test EarthData integration with raster tasks."""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterPullConfiguration
)


class Command(BaseCommand):
    help = 'Test EarthData integration by checking dataset routing'

    def handle(self, *args, **options):
        self.stdout.write("=" * 70)
        self.stdout.write("EARTHDATA INTEGRATION TEST")
        self.stdout.write("=" * 70)
        
        # Check datasets
        self.stdout.write("\n1. Checking RasterDataset records:")
        self.stdout.write("-" * 70)
        
        datasets = RasterDataset.objects.all()
        if not datasets.exists():
            self.stdout.write(self.style.WARNING("  No datasets found!"))
            self.stdout.write("  Run: python manage.py setup_raster_datasets")
            return
        
        for ds in datasets:
            self.stdout.write(f"\n  Dataset: {ds.name}")
            self.stdout.write(f"    Data Source: {ds.data_source}")
            self.stdout.write(f"    Collection ID: {ds.collection_id}")
            if ds.daac:
                self.stdout.write(f"    DAAC: {ds.daac}")
            if ds.file_format:
                self.stdout.write(f"    Format: {ds.file_format}")
            
            # Check variables
            variables = ds.variables.all()
            if variables.exists():
                self.stdout.write(f"    Variables: {', '.join([v.name for v in variables])}")
            else:
                self.stdout.write(self.style.WARNING("    No variables configured"))
        
        # Check extents
        self.stdout.write("\n\n2. Checking SpatialExtent records:")
        self.stdout.write("-" * 70)
        
        extents = SpatialExtent.objects.all()
        if not extents.exists():
            self.stdout.write(self.style.WARNING("  No spatial extents found!"))
        else:
            for extent in extents:
                self.stdout.write(f"  {extent.name}: {extent.bbox}")
        
        # Check configurations
        self.stdout.write("\n\n3. Checking RasterPullConfiguration records:")
        self.stdout.write("-" * 70)
        
        configs = RasterPullConfiguration.objects.all()
        if not configs.exists():
            self.stdout.write(self.style.WARNING("  No pull configurations found!"))
            self.stdout.write("\n  To create a test configuration:")
            self.stdout.write("  1. Access Django admin: http://localhost:8000/admin/")
            self.stdout.write("  2. Create RasterPullConfiguration")
            self.stdout.write("  3. Link variables and extents")
        else:
            for config in configs:
                self.stdout.write(f"\n  Config: {config.name}")
                self.stdout.write(f"    Active: {config.is_active}")
                self.stdout.write(f"    Lookback: {config.lookback_days} days")
                self.stdout.write(f"    Variables: {config.variables.count()}")
                self.stdout.write(f"    Extents: {config.extents.count()}")
                
                if config.last_successful_pull:
                    self.stdout.write(f"    Last Pull: {config.last_successful_pull}")
        
        # Check EarthData credentials
        self.stdout.write("\n\n4. Checking EarthData credentials:")
        self.stdout.write("-" * 70)
        
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        username = os.getenv('EARTHDATA_USERNAME')
        password = os.getenv('EARTHDATA_PASSWORD')
        
        if username and password:
            self.stdout.write(self.style.SUCCESS(f"  ✓ Credentials found (username: {username})"))
        else:
            self.stdout.write(self.style.WARNING("  ✗ Credentials missing!"))
            self.stdout.write("    Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD in .env")
        
        # Test client initialization
        self.stdout.write("\n\n5. Testing client initialization:")
        self.stdout.write("-" * 70)
        
        earthdata_datasets = RasterDataset.objects.filter(data_source='earthdata')
        if earthdata_datasets.exists():
            try:
                from src.acquisition.earthdata_client import EarthDataClient
                client = EarthDataClient()
                self.stdout.write(self.style.SUCCESS("  ✓ EarthDataClient initialized successfully"))
                self.stdout.write(f"    Authenticated: {client.authenticated}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Failed to initialize EarthDataClient: {e}"))
        else:
            self.stdout.write("  No EarthData datasets configured, skipping")
        
        gee_datasets = RasterDataset.objects.filter(data_source='gee')
        if gee_datasets.exists():
            try:
                from src.acquisition.gee_client import GEEClient
                client = GEEClient()
                self.stdout.write(self.style.SUCCESS("  ✓ GEEClient initialized successfully"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  ⚠ GEEClient initialization: {e}"))
                self.stdout.write("    (This is expected if GEE is deprecated)")
        
        # Summary
        self.stdout.write("\n\n" + "=" * 70)
        self.stdout.write("SUMMARY")
        self.stdout.write("=" * 70)
        
        earthdata_count = RasterDataset.objects.filter(data_source='earthdata').count()
        gee_count = RasterDataset.objects.filter(data_source='gee').count()
        nomads_count = RasterDataset.objects.filter(data_source='nomads').count()
        
        self.stdout.write(f"\nDatasets by source:")
        self.stdout.write(f"  EarthData: {earthdata_count}")
        self.stdout.write(f"  NOMADS: {nomads_count}")
        self.stdout.write(f"  GEE (legacy): {gee_count}")
        
        self.stdout.write(f"\nTotal configurations: {configs.count()}")
        
        if configs.exists() and username and password:
            self.stdout.write(self.style.SUCCESS("\n✓ System ready for EarthData pulls!"))
            self.stdout.write("\nTo test a pull:")
            config = configs.first()
            self.stdout.write(f"  python manage.py shell")
            self.stdout.write(f"  >>> from src.acquisition.raster_tasks import pull_raster_data")
            self.stdout.write(f"  >>> pull_raster_data({config.id})")
        else:
            self.stdout.write(self.style.WARNING("\n⚠ Setup incomplete"))
            self.stdout.write("  Complete setup steps above to enable pulls")
        
        self.stdout.write("\n")
