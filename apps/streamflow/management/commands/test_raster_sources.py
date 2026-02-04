"""
Management command to test all raster data sources.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    RasterPullConfiguration,
    RasterLayer,
    SpatialExtent
)
from src.acquisition.raster_tasks import pull_raster_data


class Command(BaseCommand):
    help = 'Test all raster data sources by creating test configs and pulling data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Clean up test configurations after running',
        )
        parser.add_argument(
            '--dataset',
            type=str,
            help='Test only a specific dataset by name',
        )

    def create_test_extent(self):
        """Create or get a small test extent."""
        extent, created = SpatialExtent.objects.get_or_create(
            name="Test_PNW_Small",
            defaults={
                'description': 'Small test extent for automated testing',
                'min_lon': -125.0,
                'max_lon': -120.0,
                'min_lat': 45.0,
                'max_lat': 48.0
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created test extent: {extent.name}'))
        return extent

    def clean_test_configs(self):
        """Remove any existing test configurations."""
        count = RasterPullConfiguration.objects.filter(name__startswith='TEST_').delete()[0]
        if count > 0:
            self.stdout.write(self.style.SUCCESS(f'Cleaned up {count} test configurations'))

    def create_test_config(self, dataset, extent):
        """Create a test configuration for a dataset."""
        variables = RasterVariable.objects.filter(dataset=dataset)
        
        if not variables.exists():
            self.stdout.write(self.style.WARNING(f'  No variables found for {dataset.name}'))
            return None
        
        config = RasterPullConfiguration.objects.create(
            name=f"TEST_{dataset.name}",
            dataset=dataset,
            description=f"Automated test configuration for {dataset.name}",
            lookback_days=5,
            apply_compression=True,
            generate_thumbnails=False,
            target_resolution_m=None,
            schedule_enabled=True,
            is_active=True
        )
        
        config.variables.set(variables)
        config.extents.add(extent)
        
        self.stdout.write(f'  Created config with {variables.count()} variables')
        return config

    def test_dataset(self, dataset, extent):
        """Test a single dataset."""
        self.stdout.write(self.style.HTTP_INFO(f'\n{"="*60}'))
        self.stdout.write(self.style.HTTP_INFO(f'Testing: {dataset.name}'))
        self.stdout.write(f'  Source: {dataset.data_source}')
        self.stdout.write(f'  Collection: {dataset.collection_id}')
        self.stdout.write(f'  Resolution: {dataset.temporal_resolution}')
        self.stdout.write(self.style.HTTP_INFO('='*60))
        
        # Determine appropriate date range based on data source and resolution
        # Different sources have different data retention policies:
        # - NOMADS: Only keeps last 2-3 days
        # - EarthData: Has indefinite retention but 2-3 day processing lag
        #
        # IMPORTANT: We're in 2025 but Django is configured for 2026.
        # NASA EarthData doesn't have 2026 data yet, so use fixed 2025 dates.
        
        if dataset.data_source == 'nomads':
            # NOMADS only has recent data (last 1-2 days)
            end_date = timezone.now() - timedelta(hours=6)  # 6 hours ago
            if dataset.temporal_resolution == 'hourly':
                # For hourly data (RTMA, Stage IV), pull just 2 hours
                start_date = end_date - timedelta(hours=2)
            else:
                start_date = end_date - timedelta(days=1)
        else:
            # EarthData products: Use early January 2026 for SMAP/MODIS
            # SMAP has data up to Jan 3, 2026; MODIS up to late December 2024
            # For MODIS, use December 2024; for SMAP/GPM use early January 2026
            
            if 'MODIS' in dataset.name:
                # MODIS: Use December 2024 (confirmed available)
                end_date = datetime(2024, 12, 20, 0, 0, tzinfo=timezone.utc)
            else:
                # SMAP/GPM: Use early January 2026 (SMAP confirmed available)
                end_date = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
            
            if dataset.temporal_resolution == 'hourly':
                start_date = end_date - timedelta(hours=2)
            elif dataset.temporal_resolution == 'daily':
                # For daily data, pull just 1 day to keep test fast
                start_date = end_date - timedelta(days=1)
            else:
                start_date = end_date - timedelta(days=1)
        
        self.stdout.write(f'\nDate range: {start_date.strftime("%Y-%m-%d %H:%M")} to {end_date.strftime("%Y-%m-%d %H:%M")}')
        
        # Create config
        config = self.create_test_config(dataset, extent)
        if not config:
            return {
                'dataset': dataset.name,
                'status': 'skipped',
                'reason': 'No variables configured'
            }
        
        # Run pull
        self.stdout.write('\nExecuting pull...')
        try:
            result = pull_raster_data(
                config.id,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
            
            self.stdout.write('\nResults:')
            self.stdout.write(f'  Attempted: {result.get("attempted", 0)}')
            self.stdout.write(f'  Successful: {result.get("successful", 0)}')
            self.stdout.write(f'  Failed: {result.get("failed", 0)}')
            self.stdout.write(f'  Skipped: {result.get("skipped", 0)}')
            
            if result.get('errors'):
                self.stdout.write(self.style.WARNING('  Errors:'))
                for error in result.get('errors', [])[:5]:
                    self.stdout.write(self.style.WARNING(f'    - {error}'))
            
            # Check created layers
            variables = config.variables.all()
            total_layers = 0
            for var in variables:
                layers = RasterLayer.objects.filter(
                    variable=var,
                    timestamp__gte=start_date,
                    timestamp__lte=end_date
                )
                layer_count = layers.count()
                total_layers += layer_count
                if layer_count > 0:
                    self.stdout.write(self.style.SUCCESS(f'  {var.name}: {layer_count} layers created'))
            
            # Determine status
            if result.get('successful', 0) > 0:
                status = 'success'
            elif result.get('attempted', 0) == result.get('skipped', 0) and result.get('skipped', 0) > 0:
                status = 'all_skipped'
            elif 'error' in result:
                status = 'error'
            else:
                status = 'failed'
            
            return {
                'dataset': dataset.name,
                'status': status,
                'attempted': result.get('attempted', 0),
                'successful': result.get('successful', 0),
                'failed': result.get('failed', 0),
                'skipped': result.get('skipped', 0),
                'layers_created': total_layers,
                'errors': result.get('errors', [])[:5]
            }
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Exception: {e}'))
            import traceback
            traceback.print_exc()
            return {
                'dataset': dataset.name,
                'status': 'exception',
                'error': str(e)
            }

    def print_summary(self, results):
        """Print summary of all tests."""
        self.stdout.write(self.style.HTTP_INFO(f'\n\n{"="*60}'))
        self.stdout.write(self.style.HTTP_INFO('TEST SUMMARY'))
        self.stdout.write(self.style.HTTP_INFO('='*60 + '\n'))
        
        success_count = sum(1 for r in results if r['status'] == 'success')
        failed_count = sum(1 for r in results if r['status'] in ['failed', 'error', 'exception'])
        skipped_count = sum(1 for r in results if r['status'] in ['skipped', 'all_skipped'])
        
        self.stdout.write(f'Total datasets tested: {len(results)}')
        self.stdout.write(self.style.SUCCESS(f'  ✓ Successful: {success_count}'))
        self.stdout.write(self.style.WARNING(f'  ⚠️  All skipped: {skipped_count}'))
        self.stdout.write(self.style.ERROR(f'  ❌ Failed: {failed_count}'))
        self.stdout.write('')
        
        for result in results:
            if result['status'] == 'success':
                self.stdout.write(self.style.SUCCESS(
                    f"✓ {result['dataset']:30} Status: {result['status']}"
                ))
                self.stdout.write(f"    Layers created: {result.get('layers_created', 0)}")
                self.stdout.write(f"    Success rate: {result.get('successful', 0)}/{result.get('attempted', 0)}")
            
            elif result['status'] == 'all_skipped':
                self.stdout.write(self.style.WARNING(
                    f"⚠️  {result['dataset']:30} Status: {result['status']}"
                ))
                self.stdout.write(f"    All {result.get('skipped', 0)} attempts skipped")
            
            else:
                self.stdout.write(self.style.ERROR(
                    f"❌ {result['dataset']:30} Status: {result['status']}"
                ))
                if result.get('error'):
                    self.stdout.write(f"    Error: {result['error']}")
            
            if result.get('errors'):
                for error in result['errors'][:3]:
                    self.stdout.write(self.style.WARNING(f"      - {error}"))
            
            self.stdout.write('')

    def handle(self, *args, **options):
        self.stdout.write(self.style.HTTP_INFO('='*60))
        self.stdout.write(self.style.HTTP_INFO('RASTER DATA SOURCE COMPREHENSIVE TEST'))
        self.stdout.write(self.style.HTTP_INFO('='*60))
        
        # Create test extent
        extent = self.create_test_extent()
        
        # Clean old configs
        self.clean_test_configs()
        
        # Get datasets
        if options['dataset']:
            datasets = RasterDataset.objects.filter(name=options['dataset'])
            if not datasets.exists():
                self.stdout.write(self.style.ERROR(f'Dataset "{options["dataset"]}" not found'))
                return
        else:
            datasets = RasterDataset.objects.all().order_by('name')
        
        self.stdout.write(self.style.SUCCESS(f'Found {datasets.count()} dataset(s) to test\n'))
        
        if datasets.count() == 0:
            self.stdout.write(self.style.ERROR('No datasets found!'))
            return
        
        # Test each dataset
        results = []
        for dataset in datasets:
            result = self.test_dataset(dataset, extent)
            results.append(result)
        
        # Print summary
        self.print_summary(results)
        
        # Cleanup
        if options['cleanup']:
            self.stdout.write('\nCleaning up test configurations...')
            self.clean_test_configs()
            self.stdout.write(self.style.SUCCESS('✓ Done'))
