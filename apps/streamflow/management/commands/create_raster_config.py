"""Management command to create raster pull configurations."""

from django.core.management.base import BaseCommand

from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterPullConfiguration
)


class Command(BaseCommand):
    """Create raster pull configurations."""
    
    help = 'Create raster pull configuration for automated data pulls'
    
    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            '--name',
            type=str,
            required=True,
            help='Configuration name'
        )
        parser.add_argument(
            '--dataset',
            type=str,
            required=True,
            choices=['RTMA', 'SMAP_SPL4'],
            help='Dataset name'
        )
        parser.add_argument(
            '--variables',
            type=str,
            nargs='+',
            help='Variable names (space-separated)'
        )
        parser.add_argument(
            '--extents',
            type=str,
            nargs='+',
            default=['HUC_17'],
            help='Extent names (space-separated), default: HUC_17'
        )
        parser.add_argument(
            '--frequency',
            type=int,
            default=8,
            help='Pull frequency in hours (default: 8)'
        )
        parser.add_argument(
            '--lookback',
            type=int,
            default=7,
            help='Lookback days (default: 7)'
        )
        parser.add_argument(
            '--enabled',
            action='store_true',
            help='Enable scheduled pulls'
        )
    
    def handle(self, *args, **options):
        """Execute command."""
        name = options['name']
        dataset_name = options['dataset']
        variable_names = options['variables']
        extent_names = options['extents']
        frequency = options['frequency']
        lookback = options['lookback']
        enabled = options['enabled']
        
        self.stdout.write(f"Creating raster pull configuration: {name}")
        
        # Get dataset
        try:
            dataset = RasterDataset.objects.get(name=dataset_name)
        except RasterDataset.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"✗ Dataset not found: {dataset_name}"))
            self.stdout.write("  Run: python manage.py setup_raster_datasets")
            return
        
        # Get variables
        if variable_names:
            variables = []
            for var_name in variable_names:
                try:
                    var = RasterVariable.objects.get(dataset=dataset, name=var_name)
                    variables.append(var)
                except RasterVariable.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f"⚠ Variable not found: {var_name}"))
            
            if not variables:
                self.stdout.write(self.style.ERROR("✗ No valid variables specified"))
                return
        else:
            # Use all variables for dataset
            variables = list(RasterVariable.objects.filter(dataset=dataset))
            if not variables:
                self.stdout.write(self.style.ERROR(f"✗ No variables found for dataset: {dataset_name}"))
                return
        
        # Get extents
        extents = []
        for extent_name in extent_names:
            try:
                extent = SpatialExtent.objects.get(name=extent_name)
                extents.append(extent)
            except SpatialExtent.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"⚠ Extent not found: {extent_name}"))
        
        if not extents:
            self.stdout.write(self.style.ERROR("✗ No valid extents specified"))
            self.stdout.write("  Run: python manage.py setup_spatial_extents")
            return
        
        # Create configuration
        config, created = RasterPullConfiguration.objects.get_or_create(
            name=name,
            defaults={
                'dataset': dataset,
                'description': f'Pull {dataset_name} data every {frequency} hours',
                'schedule_enabled': enabled,
                'pull_frequency_hours': frequency,
                'lookback_days': lookback,
                'max_age_hours': 24 * lookback,
                'resampling_method': 'bilinear',
                'compression_enabled': True,
                'compression_method': 'LZW',
                'thumbnail_enabled': True,
            }
        )
        
        if created:
            # Add variables and extents
            config.variables.set(variables)
            config.extents.set(extents)
            config.save()
            
            self.stdout.write(self.style.SUCCESS(f"\n✓ Created configuration: {name}"))
            self.stdout.write(f"  Dataset: {dataset.name}")
            self.stdout.write(f"  Variables: {', '.join(v.name for v in variables)}")
            self.stdout.write(f"  Extents: {', '.join(e.name for e in extents)}")
            self.stdout.write(f"  Frequency: every {frequency} hours")
            self.stdout.write(f"  Lookback: {lookback} days")
            self.stdout.write(f"  Scheduled: {'Enabled' if enabled else 'Disabled'}")
            
            if not enabled:
                self.stdout.write(self.style.WARNING("\n⚠ Scheduled pulls are disabled"))
                self.stdout.write("  To enable, update the configuration in Django admin or run:")
                self.stdout.write(f"  RasterPullConfiguration.objects.filter(name='{name}').update(schedule_enabled=True)")
        else:
            self.stdout.write(self.style.WARNING(f"\n⚠ Configuration already exists: {name}"))
            self.stdout.write("  Use Django admin to modify existing configuration")
