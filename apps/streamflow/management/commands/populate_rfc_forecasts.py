"""
Django management command to populate historical RFC forecast data.

This command scrapes historical forecast runs from NOAA River Forecast Center (RFC)
websites and stores them in the database for model training and analysis.

Usage:
    python manage.py populate_rfc_forecasts --rfc NWRFC --forecast-type short
    python manage.py populate_rfc_forecasts --huc 17 --forecast-type medium --limit 10
    python manage.py populate_rfc_forecasts --station AAMC1 --station AGNO3 --dry-run
"""

from django.core.management.base import BaseCommand
from datetime import datetime, timedelta
import signal
import sys

from src.acquisition.rfc_forecast_population import RFCForecastPopulationService


class Command(BaseCommand):
    help = """
    Populate historical NOAA RFC forecast runs from RFC websites.
    
    This command scrapes historical forecast data for model training and error analysis.
    Note: The NOAA Water API only provides current forecasts, so historical data must
    be obtained by scraping RFC websites (currently only NWRFC is supported).
    
    Examples:
        # Populate short-range forecasts for all NWRFC stations
        python manage.py populate_rfc_forecasts --rfc NWRFC --forecast-type short
        
        # Populate medium-range forecasts for HUC 17 (limited for testing)
        python manage.py populate_rfc_forecasts --huc 17 --forecast-type medium --limit 10
        
        # Populate specific stations with custom date range
        python manage.py populate_rfc_forecasts --station AAMC1 --station AGNO3 \\
            --start-date 2025-10-01 --end-date 2026-01-29
        
        # Dry run to see what would be fetched
        python manage.py populate_rfc_forecasts --rfc NWRFC --forecast-type short --dry-run --limit 5
        
        # Force re-population even if data exists
        python manage.py populate_rfc_forecasts --rfc NWRFC --forecast-type short --force
    """

    def __init__(self):
        super().__init__()
        self.shutdown_requested = False

    def add_arguments(self, parser):
        # Station discovery options
        parser.add_argument(
            '--rfc',
            type=str,
            action='append',
            help='RFC code(s) to process (e.g., NWRFC, CNRFC). Can be specified multiple times.'
        )
        parser.add_argument(
            '--huc',
            type=str,
            action='append',
            help='HUC code(s) to filter by. Can be specified multiple times.'
        )
        parser.add_argument(
            '--station',
            type=str,
            action='append',
            help='Specific NOAA LID(s) to process. Can be specified multiple times.'
        )
        parser.add_argument(
            '--include-inactive',
            action='store_true',
            help='Include inactive stations (default: active only)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of stations to process (useful for testing)'
        )

        # Forecast parameters
        parser.add_argument(
            '--forecast-type',
            type=str,
            choices=['short', 'medium'],
            default='short',
            help='Forecast type to retrieve: short (3-7 days) or medium (up to 10 days). Default: short'
        )
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date for forecast retrieval (YYYY-MM-DD). Default: 90 days ago'
        )
        parser.add_argument(
            '--end-date',
            type=str,
            help='End date for forecast retrieval (YYYY-MM-DD). Default: today'
        )

        # Control options
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-populate forecasts even if station already has data'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fetched without actually saving to database'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=3.0,
            help='Delay in seconds between station requests (default: 3.0, be respectful!)'
        )

    def handle(self, *args, **options):
        # Setup graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Parse arguments
        rfc_codes = options.get('rfc')
        huc_codes = options.get('huc')
        station_lids = options.get('station')
        include_inactive = options.get('include_inactive', False)
        limit = options.get('limit')
        
        forecast_type = options.get('forecast_type', 'short')
        start_date = options.get('start_date')
        end_date = options.get('end_date')
        
        force = options.get('force', False)
        dry_run = options.get('dry_run', False)
        delay = options.get('delay', 3.0)

        # Validate inputs
        if not rfc_codes and not huc_codes and not station_lids:
            self.stdout.write(self.style.ERROR(
                'Error: Must specify at least one of --rfc, --huc, or --station'
            ))
            return

        # Parse dates
        parsed_start_date = None
        parsed_end_date = None
        
        if start_date:
            try:
                parsed_start_date = datetime.strptime(start_date, '%Y-%m-%d')
            except ValueError:
                self.stdout.write(self.style.ERROR(f'Invalid start date format: {start_date}'))
                return
        
        if end_date:
            try:
                parsed_end_date = datetime.strptime(end_date, '%Y-%m-%d')
            except ValueError:
                self.stdout.write(self.style.ERROR(f'Invalid end date format: {end_date}'))
                return

        # Set defaults
        if not parsed_end_date:
            parsed_end_date = datetime.now()
        if not parsed_start_date:
            parsed_start_date = parsed_end_date - timedelta(days=90)

        # Show configuration
        self.stdout.write(self.style.SUCCESS('\n' + '='*70))
        self.stdout.write(self.style.SUCCESS('RFC Historical Forecast Population'))
        self.stdout.write(self.style.SUCCESS('='*70))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n*** DRY RUN MODE - No data will be saved ***\n'))
        
        self.stdout.write(f'\nForecast Type: {forecast_type}')
        self.stdout.write(f'Date Range: {parsed_start_date.date()} to {parsed_end_date.date()}')
        
        if rfc_codes:
            self.stdout.write(f'RFC Codes: {", ".join(rfc_codes)}')
        if huc_codes:
            self.stdout.write(f'HUC Codes: {", ".join(huc_codes)}')
        if station_lids:
            self.stdout.write(f'Stations: {", ".join(station_lids)}')
        
        self.stdout.write(f'Include Inactive: {include_inactive}')
        if limit:
            self.stdout.write(f'Limit: {limit} stations')
        self.stdout.write(f'Force Re-population: {force}')
        self.stdout.write(f'Delay: {delay} seconds between stations')
        self.stdout.write('')

        # Initialize service
        service = RFCForecastPopulationService()

        # Discover stations
        self.stdout.write('Discovering stations...')
        stations = service.discover_stations(
            rfc_codes=rfc_codes,
            huc_codes=huc_codes,
            station_lids=station_lids,
            limit=limit,
            include_inactive=include_inactive
        )

        if not stations:
            self.stdout.write(self.style.ERROR('\nNo stations found matching criteria.'))
            return

        self.stdout.write(self.style.SUCCESS(f'Found {len(stations)} stations to process\n'))

        # Show warning for NWRFC limitation
        if rfc_codes and 'NWRFC' not in rfc_codes:
            self.stdout.write(self.style.WARNING(
                f'\nWarning: Historical forecast scraping is currently only implemented for NWRFC.'
            ))
            self.stdout.write(self.style.WARNING(
                f'Stations from other RFCs will be skipped.\n'
            ))

        # Confirm before proceeding
        if not dry_run and len(stations) > 10:
            self.stdout.write(self.style.WARNING(
                f'\nYou are about to scrape historical forecasts for {len(stations)} stations.'
            ))
            self.stdout.write(self.style.WARNING(
                'This may take a significant amount of time and makes HTTP requests to RFC websites.'
            ))
            response = input('Continue? (y/n): ')
            if response.lower() != 'y':
                self.stdout.write(self.style.WARNING('Operation cancelled.'))
                return

        # Process stations
        self.stdout.write('\n' + '-'*70)
        self.stdout.write('Processing Stations')
        self.stdout.write('-'*70 + '\n')

        results = {
            'success': 0,
            'skipped': 0,
            'not_supported': 0,
            'no_data': 0,
            'failed': 0,
            'total_forecasts': 0
        }

        for i, station in enumerate(stations, 1):
            if self.shutdown_requested:
                self.stdout.write(self.style.WARNING('\n\nShutdown requested. Stopping...'))
                break

            self.stdout.write(
                f'[{i}/{len(stations)}] {station.station_number} - {station.name}'
            )

            # Check RFC code from MasterStation
            try:
                from apps.streamflow.models import MasterStation
                from django.db.models import Q
                
                master = MasterStation.objects.filter(
                    Q(noaa_lid=station.station_number) | Q(station_number=station.station_number)
                ).first()
                
                rfc = master.rfc_code if master else 'Unknown'
            except Exception:
                rfc = 'Unknown'
            
            self.stdout.write(f'  RFC: {rfc}')

            # Populate station
            result = service.populate_station(
                station=station,
                forecast_type=forecast_type,
                start_date=parsed_start_date,
                end_date=parsed_end_date,
                force=force,
                dry_run=dry_run
            )

            status = result['status']
            
            # Update results
            if status in results:
                results[status] += 1
            results['total_forecasts'] += result.get('forecasts_saved', 0)

            # Display result
            if status == 'success':
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ Success: Retrieved {result['forecasts_retrieved']}, "
                    f"Saved {result['forecasts_saved']}"
                ))
            elif status == 'skipped':
                self.stdout.write(self.style.WARNING(
                    f"  ⊘ Skipped: {result['reason']} "
                    f"({result.get('existing_forecasts', 0)} existing forecasts)"
                ))
            elif status == 'not_supported':
                self.stdout.write(self.style.WARNING(
                    f"  ⊘ Not Supported: {result['error']}"
                ))
            elif status == 'no_data':
                self.stdout.write(self.style.WARNING(
                    f"  ⊘ No Data: {result['error']}"
                ))
            elif status == 'dry_run':
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ Dry Run: Would retrieve {result['forecasts_retrieved']} forecasts"
                ))
            else:  # failed
                self.stdout.write(self.style.ERROR(
                    f"  ✗ Failed: {result.get('error', 'Unknown error')}"
                ))

            self.stdout.write('')  # Blank line

        # Summary
        self.stdout.write('\n' + '='*70)
        self.stdout.write('Summary')
        self.stdout.write('='*70)
        self.stdout.write(f'\nTotal Stations Processed: {len(stations)}')
        self.stdout.write(f'  Success: {results["success"]}')
        self.stdout.write(f'  Skipped: {results["skipped"]}')
        self.stdout.write(f'  Not Supported: {results["not_supported"]}')
        self.stdout.write(f'  No Data: {results["no_data"]}')
        self.stdout.write(f'  Failed: {results["failed"]}')
        self.stdout.write(f'\nTotal Forecasts Saved: {results["total_forecasts"]}')
        
        if not dry_run and results['success'] > 0:
            self.stdout.write(self.style.SUCCESS('\n✓ Historical forecast population complete!'))
        elif dry_run:
            self.stdout.write(self.style.SUCCESS('\n✓ Dry run complete!'))
        else:
            self.stdout.write(self.style.WARNING('\n⚠ No forecasts were populated.'))

        self.stdout.write('')

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        if not self.shutdown_requested:
            self.shutdown_requested = True
            self.stdout.write(
                self.style.WARNING('\n\nReceived shutdown signal. Will stop after current station...')
            )
            self.stdout.write(
                self.style.WARNING('(Press Ctrl+C again to force quit)\n')
            )
        else:
            self.stdout.write(self.style.ERROR('\n\nForce quit!\n'))
            sys.exit(1)
