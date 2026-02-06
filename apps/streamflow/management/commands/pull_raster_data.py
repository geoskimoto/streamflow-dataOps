"""Management command to manually pull raster data."""

from django.core.management.base import BaseCommand

from apps.streamflow.models import RasterPullConfiguration
from src.acquisition.raster_tasks import pull_raster_data


class Command(BaseCommand):
    """Manually trigger raster data pull."""
    
    help = 'Manually pull raster data for a configuration'
    
    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            '--config',
            type=str,
            help='Configuration name'
        )
        parser.add_argument(
            '--config-id',
            type=int,
            help='Configuration ID'
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='List available configurations'
        )
        parser.add_argument(
            '--async',
            action='store_true',
            dest='async_mode',
            help='Run asynchronously via Celery (default: synchronous)'
        )
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date (ISO format: YYYY-MM-DD)'
        )
        parser.add_argument(
            '--end-date',
            type=str,
            help='End date (ISO format: YYYY-MM-DD)'
        )
    
    def handle(self, *args, **options):
        """Execute command."""
        if options['list']:
            self._list_configurations()
            return
        
        config_name = options['config']
        config_id = options['config_id']
        async_mode = options['async_mode']
        start_date = options['start_date']
        end_date = options['end_date']
        
        if not config_name and not config_id:
            self.stdout.write(self.style.ERROR("✗ Must specify --config or --config-id"))
            self.stdout.write("  Use --list to see available configurations")
            return
        
        # Get configuration
        try:
            if config_id:
                config = RasterPullConfiguration.objects.get(id=config_id)
            else:
                config = RasterPullConfiguration.objects.get(name=config_name)
        except RasterPullConfiguration.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"✗ Configuration not found"))
            self.stdout.write("  Use --list to see available configurations")
            return
        
        self.stdout.write("=" * 80)
        self.stdout.write(f"Pulling raster data: {config.name}")
        self.stdout.write("=" * 80)
        self.stdout.write(f"  Dataset: {config.dataset.name}")
        self.stdout.write(f"  Variables: {config.variables.count()}")
        self.stdout.write(f"  Extents: {config.extents.count()}")
        if start_date and end_date:
            self.stdout.write(f"  Date range: {start_date} to {end_date}")
        else:
            self.stdout.write(f"  Lookback: {config.lookback_days} days")
        self.stdout.write(f"  Mode: {'Asynchronous (Celery)' if async_mode else 'Synchronous'}")
        self.stdout.write("")
        
        # Run pull
        if async_mode:
            # Queue task
            task = pull_raster_data.delay(config.id, start_date, end_date)
            self.stdout.write(self.style.SUCCESS(f"✓ Task queued: {task.id}"))
            self.stdout.write(f"  Check status: python manage.py celery_task_status {task.id}")
        else:
            # Run synchronously
            self.stdout.write("Running pull (this may take a while)...")
            result = pull_raster_data(config.id, start_date, end_date)
            
            if 'error' in result:
                self.stdout.write(self.style.ERROR(f"\n✗ Error: {result['error']}"))
            else:
                self.stdout.write("\n" + "=" * 80)
                self.stdout.write(self.style.SUCCESS("Pull complete!"))
                self.stdout.write("=" * 80)
                self.stdout.write(f"  Attempted: {result['attempted']}")
                self.stdout.write(f"  Successful: {result['successful']}")
                self.stdout.write(f"  Failed: {result['failed']}")
                self.stdout.write(f"  Skipped: {result['skipped']}")
                
                if result.get('errors'):
                    self.stdout.write(f"\n  Errors:")
                    for error in result['errors'][:10]:  # Show first 10 errors
                        self.stdout.write(f"    - {error}")
    
    def _list_configurations(self):
        """List available configurations."""
        configs = RasterPullConfiguration.objects.all()
        
        if not configs.exists():
            self.stdout.write(self.style.WARNING("No configurations found"))
            self.stdout.write("  Create one with: python manage.py create_raster_config")
            return
        
        self.stdout.write("=" * 80)
        self.stdout.write("Available Raster Pull Configurations")
        self.stdout.write("=" * 80)
        
        for config in configs:
            status = "✓ Enabled" if config.schedule_enabled else "○ Disabled"
            self.stdout.write(f"\n{status} {config.name} (ID: {config.id})")
            self.stdout.write(f"  Dataset: {config.dataset.name}")
            self.stdout.write(f"  Variables: {', '.join(v.name for v in config.variables.all())}")
            self.stdout.write(f"  Extents: {', '.join(e.name for e in config.extents.all())}")
            self.stdout.write(f"  Frequency: every {config.pull_frequency_hours} hours")
            
            if config.last_successful_pull:
                self.stdout.write(f"  Last pull: {config.last_successful_pull}")
