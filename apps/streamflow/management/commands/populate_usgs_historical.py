"""Management command to populate historical USGS discharge data."""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
import signal
import sys

from src.acquisition.historical_population import HistoricalPopulationService


class Command(BaseCommand):
    help = 'Populate complete historical USGS discharge data for stations by HUC, state, or station number'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.interrupted = False

    def add_arguments(self, parser):
        parser.add_argument(
            '--huc',
            action='append',
            help='HUC code(s) to process (e.g., --huc 17). Can be specified multiple times.'
        )
        parser.add_argument(
            '--state',
            action='append',
            help='State code(s) to process (e.g., --state WA). Can be specified multiple times.'
        )
        parser.add_argument(
            '--station',
            action='append',
            help='Specific station number(s). Can be specified multiple times.'
        )
        parser.add_argument(
            '--include-inactive',
            action='store_true',
            help='Include inactive stations (default: active only)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually fetching/inserting data'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of stations to process (for testing)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-populate even if station already has complete historical data'
        )
        parser.add_argument(
            '--start-date',
            help='Override start date (YYYY-MM-DD). Default: use station record_start_date'
        )
        parser.add_argument(
            '--end-date',
            help='Override end date (YYYY-MM-DD). Default: today'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Number of records per bulk insert (default: 1000)'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='Seconds to wait between stations (default: 1.0)'
        )

    def handle(self, *args, **options):
        """Execute command."""
        # Set up signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)

        # Validate arguments
        if not options['huc'] and not options['state'] and not options['station']:
            self.stdout.write(self.style.ERROR('Must specify at least one of: --huc, --state, or --station'))
            return

        # Parse dates if provided
        start_date = None
        end_date = None

        if options['start_date']:
            try:
                start_date = datetime.strptime(options['start_date'], '%Y-%m-%d')
                start_date = timezone.make_aware(start_date)
            except ValueError:
                self.stdout.write(self.style.ERROR(f'Invalid start date format: {options["start_date"]}'))
                return

        if options['end_date']:
            try:
                end_date = datetime.strptime(options['end_date'], '%Y-%m-%d')
                end_date = timezone.make_aware(end_date)
            except ValueError:
                self.stdout.write(self.style.ERROR(f'Invalid end date format: {options["end_date"]}'))
                return

        # Print header
        self.stdout.write('=' * 70)
        self.stdout.write(self.style.SUCCESS('USGS HISTORICAL DATA POPULATION'))
        self.stdout.write('=' * 70)

        # Show configuration
        mode_parts = []
        if options['huc']:
            mode_parts.append(f"HUC {', '.join(options['huc'])}")
        if options['state']:
            mode_parts.append(f"State {', '.join(options['state'])}")
        if options['station']:
            mode_parts.append(f"Stations: {', '.join(options['station'])}")

        self.stdout.write(f"Mode: {' + '.join(mode_parts)}")
        self.stdout.write(f"Include Inactive: {options['include_inactive']}")
        self.stdout.write(f"Date Range: {options['start_date'] or 'station default'} to {options['end_date'] or 'today'}")
        self.stdout.write(f"Batch Size: {options['batch_size']} records")
        self.stdout.write(f"Delay: {options['delay']} seconds between stations")
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No data will be written'))
        if options['force']:
            self.stdout.write(self.style.WARNING('FORCE MODE - Will re-populate existing data'))
        self.stdout.write('')

        # Initialize service
        service = HistoricalPopulationService(
            batch_size=options['batch_size'],
            delay=options['delay']
        )

        # Discover stations
        self.stdout.write('Discovering stations...')
        stations = service.discover_stations(
            huc_codes=options['huc'],
            state_codes=options['state'],
            station_numbers=options['station'],
            include_inactive=options['include_inactive']
        )

        if not stations:
            self.stdout.write(self.style.ERROR('No stations found matching criteria'))
            return

        self.stdout.write(f"  Found {len(stations)} USGS stations")

        # Check how many already populated
        already_complete = sum(1 for s in stations if s.historical_data_populated_at and not options['force'])
        not_started = len(stations) - already_complete

        self.stdout.write(f"  Already complete: {already_complete}")
        self.stdout.write(f"  Need population: {not_started}")

        # Apply limit
        if options['limit']:
            stations = stations[:options['limit']]
            self.stdout.write(self.style.WARNING(f"  Limited to first {options['limit']} stations"))

        self.stdout.write(f"\nStations to process: {len(stations)}")
        self.stdout.write('')

        # Process stations
        for i, station in enumerate(stations, 1):
            if self.interrupted:
                self.stdout.write(self.style.WARNING('\n\nInterrupted by user'))
                break

            self.stdout.write('=' * 70)
            self.stdout.write(self.style.SUCCESS(f'STATION {i}/{len(stations)}: {station.station_number} - {station.name}'))
            self.stdout.write('=' * 70)

            # Check current status
            status = service.check_station_status(station)

            if status['expected_start'] and status['expected_end']:
                years = (status['expected_end'] - status['expected_start']).days / 365.25
                self.stdout.write(f"  Record Period: {status['expected_start'].date()} to {status['expected_end'].date()} ({years:.1f} years)")
            else:
                self.stdout.write(f"  Record Period: Unknown")

            self.stdout.write(f"  Existing Records: {status['record_count']}")

            # Check if should skip
            if not options['force'] and station.historical_data_populated_at:
                if status['is_complete']:
                    self.stdout.write(self.style.SUCCESS('  ✓ Records complete, skipping'))
                    self.stdout.write('')
                    continue
                else:
                    self.stdout.write(f"  Checking for gaps... (missing ~{status['missing_days']} days)")

            # Populate
            if options['dry_run']:
                self.stdout.write(self.style.WARNING('  [DRY RUN] Would fetch data'))
            else:
                self.stdout.write('  Fetching data... ⏳')

            result = service.populate_station(
                station=station,
                start_date=start_date,
                end_date=end_date,
                force=options['force'],
                dry_run=options['dry_run']
            )

            # Display result
            if result['status'] == 'success':
                self.stdout.write(self.style.SUCCESS(f"  ✓ Fetched {result['records_fetched']} records"))
                self.stdout.write(self.style.SUCCESS(f"  ✓ Inserted {result['records_inserted']} new records"))
                self.stdout.write(f"  ⏱ Time: {result['duration_seconds']:.1f} seconds")
            elif result['status'] == 'skipped':
                self.stdout.write(self.style.SUCCESS('  ✓ Already complete, skipped'))
                self.stdout.write(f"  ⏱ Time: {result['duration_seconds']:.1f} seconds")
            elif result['status'] == 'dry_run':
                self.stdout.write(self.style.WARNING('  [DRY RUN] Skipped'))
            elif result['status'] == 'failed':
                self.stdout.write(self.style.ERROR(f"  ✗ Failed: {result['error']}"))
                self.stdout.write(f"  ⏱ Time: {result['duration_seconds']:.1f} seconds")

            self.stdout.write('')

        # Final summary
        if not self.interrupted:
            self.stdout.write('=' * 70)
            self.stdout.write(self.style.SUCCESS('POPULATION COMPLETE'))
            self.stdout.write('=' * 70)

            # Gather final statistics
            summary = service.populate_bulk(
                stations=[],  # Already processed
                dry_run=True  # Just to get structure
            )

            # Count actual results
            successful = sum(1 for s in stations if s.historical_data_populated_at)
            total_records = sum(s.historical_record_count for s in stations)

            self.stdout.write(f"  Total Stations: {len(stations)}")
            self.stdout.write(f"  Successfully Populated: {successful}")
            self.stdout.write(f"  Total Historical Records: {total_records:,}")
            self.stdout.write('')

            if not options['dry_run']:
                self.stdout.write(self.style.SUCCESS('✓ Historical population complete!'))
                self.stdout.write('')
                self.stdout.write('Next steps:')
                self.stdout.write('  1. Set up PullConfiguration for ongoing appends')
                self.stdout.write('  2. Verify data quality in Django admin or via API')
            else:
                self.stdout.write(self.style.WARNING('DRY RUN complete - no data was written'))

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        self.stdout.write(self.style.WARNING('\n\nReceived interrupt signal...'))
        self.stdout.write('Finishing current station and exiting...')
        self.interrupted = True
