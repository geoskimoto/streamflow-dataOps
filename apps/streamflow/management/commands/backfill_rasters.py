"""Management command to backfill historical raster data."""

from django.core.management.base import BaseCommand
from datetime import datetime

from apps.streamflow.models import RasterPullConfiguration
from src.acquisition.raster_tasks import pull_raster_data


class Command(BaseCommand):
    """Backfill historical raster data."""
    
    help = 'Backfill historical raster data for a date range'
    
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
            '--start-date',
            type=str,
            required=True,
            help='Start date (ISO format: YYYY-MM-DD)'
        )
        parser.add_argument(
            '--end-date',
            type=str,
            required=True,
            help='End date (ISO format: YYYY-MM-DD)'
        )
        parser.add_argument(
            '--async',
            action='store_true',
            dest='async_mode',
            help='Run asynchronously via Celery (recommended for large backfills)'
        )
    
    def handle(self, *args, **options):
        """Execute command."""
        config_name = options['config']
        config_id = options['config_id']
        start_date = options['start_date']
        end_date = options['end_date']
        async_mode = options['async_mode']
        
        if not config_name and not config_id:
            self.stdout.write(self.style.ERROR("✗ Must specify --config or --config-id"))
            self.stdout.write("  Use: python manage.py pull_raster_data --list")
            return
        
        # Validate dates
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f"✗ Invalid date format: {e}"))
            self.stdout.write("  Use ISO format: YYYY-MM-DD")
            return
        
        if start_dt >= end_dt:
            self.stdout.write(self.style.ERROR("✗ Start date must be before end date"))
            return
        
        days = (end_dt - start_dt).days
        if days > 365:
            self.stdout.write(self.style.WARNING(f"⚠ Backfilling {days} days of data"))
            confirm = input("This may take a long time. Continue? (y/n): ")
            if confirm.lower() != 'y':
                self.stdout.write("Cancelled")
                return
        
        # Get configuration
        try:
            if config_id:
                config = RasterPullConfiguration.objects.get(id=config_id)
            else:
                config = RasterPullConfiguration.objects.get(name=config_name)
        except RasterPullConfiguration.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"✗ Configuration not found"))
            return
        
        self.stdout.write("=" * 80)
        self.stdout.write(f"Backfilling raster data: {config.name}")
        self.stdout.write("=" * 80)
        self.stdout.write(f"  Dataset: {config.dataset.name}")
        self.stdout.write(f"  Variables: {config.variables.count()}")
        self.stdout.write(f"  Extents: {config.extents.count()}")
        self.stdout.write(f"  Date range: {start_date} to {end_date} ({days} days)")
        
        # Estimate
        num_variables = config.variables.count()
        num_extents = config.extents.count()
        
        if config.dataset.temporal_resolution == 'hourly':
            estimated_layers = days * 24 * num_variables * num_extents
        else:
            estimated_layers = days * num_variables * num_extents
        
        self.stdout.write(f"  Estimated layers: ~{estimated_layers:,}")
        self.stdout.write(f"  Mode: {'Asynchronous (Celery)' if async_mode else 'Synchronous'}")
        
        if estimated_layers > 1000 and not async_mode:
            self.stdout.write(self.style.WARNING("\n⚠ Large backfill detected"))
            self.stdout.write("  Consider using --async for better performance")
        
        self.stdout.write("")
        
        # Run backfill
        if async_mode:
            # Queue task
            task = pull_raster_data.delay(config.id, start_date, end_date)
            self.stdout.write(self.style.SUCCESS(f"✓ Backfill task queued: {task.id}"))
            self.stdout.write(f"\nMonitor progress:")
            self.stdout.write(f"  - Celery logs: tail -f celery.log")
            self.stdout.write(f"  - Pull logs: RasterPullLog.objects.filter(celery_task_id='{task.id}')")
        else:
            # Run synchronously
            self.stdout.write("Running backfill (this will take a while)...")
            self.stdout.write("Press Ctrl+C to cancel (will stop gracefully)")
            
            try:
                result = pull_raster_data(config.id, start_date, end_date)
                
                if 'error' in result:
                    self.stdout.write(self.style.ERROR(f"\n✗ Error: {result['error']}"))
                else:
                    self.stdout.write("\n" + "=" * 80)
                    self.stdout.write(self.style.SUCCESS("Backfill complete!"))
                    self.stdout.write("=" * 80)
                    self.stdout.write(f"  Attempted: {result['attempted']}")
                    self.stdout.write(f"  Successful: {result['successful']}")
                    self.stdout.write(f"  Failed: {result['failed']}")
                    self.stdout.write(f"  Skipped: {result['skipped']}")
                    
                    success_rate = (result['successful'] / result['attempted'] * 100) if result['attempted'] > 0 else 0
                    self.stdout.write(f"  Success rate: {success_rate:.1f}%")
                    
                    if result.get('errors'):
                        self.stdout.write(f"\n  Recent errors:")
                        for error in result['errors'][-10:]:  # Show last 10 errors
                            self.stdout.write(f"    - {error}")
                            
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("\n\n⚠ Backfill cancelled by user"))
                self.stdout.write("  Partial data may have been pulled")
