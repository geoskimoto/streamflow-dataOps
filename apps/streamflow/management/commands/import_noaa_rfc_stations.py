"""Django management command to import NOAA RFC stations from API."""

from django.core.management.base import BaseCommand
from apps.streamflow.models import MasterStation
from src.acquisition.noaa_client import NOAAClient
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Import NOAA River Forecast Center stations from API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--states',
            nargs='+',
            type=str,
            help='State codes to import (e.g., CA OR WA ID MT WY NV UT AZ NM)',
        )
        parser.add_argument(
            '--rfc',
            type=str,
            help='Specific RFC code to import (e.g., NWRFC, CNRFC)',
        )
        parser.add_argument(
            '--include-bc',
            action='store_true',
            help='Include British Columbia stations from NWRFC',
        )
        parser.add_argument(
            '--forecasts-only',
            action='store_true',
            default=True,
            help='Only import gauges with active forecasts (default: True)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing NOAA_RFC stations before loading',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without saving to database',
        )

    def handle(self, *args, **options):
        client = NOAAClient()
        
        if options['clear']:
            self.stdout.write('Clearing existing NOAA_RFC stations...')
            count = MasterStation.objects.filter(agency='NOAA_RFC').delete()[0]
            self.stdout.write(self.style.SUCCESS(f'Deleted {count} stations'))

        all_gauges = []
        requested_states = set()
        
        # Import by states
        if options['states']:
            states = options['states']
            requested_states = set(states)
            self.stdout.write(f"Fetching gauges for states: {', '.join(states)}")
            
            gauges = client.get_gauges_by_states(states)
            
            # Filter to only requested states
            filtered_gauges = [
                g for g in gauges
                if g.get('state', {}).get('abbreviation') in requested_states
            ]
            
            self.stdout.write(f"  Found {len(filtered_gauges)} gauges in requested states")
            all_gauges.extend(filtered_gauges)
        
        # Import by RFC
        elif options['rfc']:
            rfc_code = options['rfc']
            self.stdout.write(f"Fetching gauges for RFC: {rfc_code}")
            gauges = client.get_gauges_by_rfc(rfc_code)
            self.stdout.write(f"  Found {len(gauges)} gauges")
            all_gauges.extend(gauges)
        
        # Include British Columbia via NWRFC
        if options['include_bc']:
            self.stdout.write("Fetching British Columbia gauges from NWRFC...")
            nwrfc_gauges = client.get_gauges_by_rfc('NWRFC')
            # Filter for BC/Canada stations
            bc_gauges = [
                g for g in nwrfc_gauges 
                if g.get('state', {}).get('abbreviation') in ['BC', 'CANADA']
                or 'British Columbia' in g.get('state', {}).get('name', '')
            ]
            self.stdout.write(f"  Found {len(bc_gauges)} BC gauges")
            all_gauges.extend(bc_gauges)
        
        if not all_gauges:
            self.stdout.write(self.style.WARNING('No gauges found. Specify --states or --rfc'))
            return
        
        # Remove duplicates by LID
        unique_gauges = {}
        for gauge in all_gauges:
            lid = gauge.get('lid')
            if lid and lid not in unique_gauges:
                unique_gauges[lid] = gauge
        
        all_gauges = list(unique_gauges.values())
        self.stdout.write(f"\nTotal unique gauges: {len(all_gauges)}")
        
        # Filter for forecasts only
        if options['forecasts_only']:
            forecasted_gauges = []
            for gauge in all_gauges:
                forecast_status = gauge.get('status', {}).get('forecast', {})
                flood_category = forecast_status.get('floodCategory', 'fcst_not_current')
                
                # Include if forecast is current (not "fcst_not_current")
                if flood_category != 'fcst_not_current':
                    forecasted_gauges.append(gauge)
            
            self.stdout.write(f"Filtered to {len(forecasted_gauges)} gauges with active forecasts")
            all_gauges = forecasted_gauges
        
        if not all_gauges:
            self.stdout.write(self.style.WARNING('No gauges with forecasts found'))
            return
        
        # Import stations
        created_count = 0
        updated_count = 0
        skipped_count = 0
        
        for gauge in all_gauges:
            lid = gauge.get('lid')
            name = gauge.get('name', '')
            
            # Get geographic data
            lat = gauge.get('latitude')
            lon = gauge.get('longitude')
            
            # Get state
            state_info = gauge.get('state', {})
            state_code = state_info.get('abbreviation', '')
            
            # Get RFC
            rfc_info = gauge.get('rfc', {})
            rfc_code = rfc_info.get('abbreviation', '')
            
            if not lid:
                skipped_count += 1
                continue
            
            if options['dry_run']:
                self.stdout.write(
                    f"[DRY RUN] Would import: {lid} - {name} "
                    f"(RFC: {rfc_code}, State: {state_code})"
                )
                created_count += 1
                continue
            
            try:
                station, created = MasterStation.objects.update_or_create(
                    noaa_lid=lid,
                    defaults={
                        'station_number': lid,
                        'station_name': name or f"NOAA Station {lid}",
                        'agency': 'NOAA_RFC',
                        'latitude': lat,
                        'longitude': lon,
                        'state_code': state_code,
                        'rfc_code': rfc_code,
                        'huc_code': '',  # NOAA API doesn't provide HUC
                    }
                )
                
                if created:
                    created_count += 1
                    self.stdout.write(
                        f"  ✓ Created: {lid} - {name[:50]} (RFC: {rfc_code})"
                    )
                else:
                    updated_count += 1
                    self.stdout.write(
                        f"  ↻ Updated: {lid} - {name[:50]} (RFC: {rfc_code})"
                    )
                    
            except Exception as e:
                self.stderr.write(f"  ✗ Error importing {lid}: {e}")
                skipped_count += 1
        
        # Summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS(f'Import complete!'))
        self.stdout.write(f"  Created: {created_count}")
        self.stdout.write(f"  Updated: {updated_count}")
        if skipped_count > 0:
            self.stdout.write(self.style.WARNING(f"  Skipped: {skipped_count}"))
        self.stdout.write('='*60)
