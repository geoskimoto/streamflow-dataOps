"""
Management command to load USGS-NOAA station mappings from HADS files.

HADS (Hydrometeorological Automated Data System) provides mappings between
USGS site numbers and NOAA Location IDs (LIDs).
"""

from django.core.management.base import BaseCommand
from apps.streamflow.models import MasterStation, StationMapping
import requests
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Load USGS-NOAA station mappings from HADS (Hydrometeorological Automated Data System)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--states',
            nargs='+',
            type=str,
            help='State codes to load (e.g., WA OR CA). If not specified, loads all available states.',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing mappings before loading',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be loaded without saving to database',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        clear_existing = options.get('clear', False)
        requested_states = options.get('states', None)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))

        if clear_existing and not dry_run:
            self.stdout.write('Clearing existing station mappings...')
            count = StationMapping.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'Deleted {count} mappings'))

        # HADS base URL
        base_url = "https://hads.ncep.noaa.gov/USGS/"
        
        # Define states to process
        if requested_states:
            states = requested_states
        else:
            # Common western states
            states = ['WA', 'OR', 'CA', 'ID', 'MT', 'NV', 'UT', 'WY', 'CO', 'AZ', 'NM']
        
        self.stdout.write(f"\nProcessing states: {', '.join(states)}")
        
        total_created = 0
        total_updated = 0
        total_skipped = 0
        
        for state in states:
            url = f"{base_url}{state}_USGS-HADS_SITES.txt"
            
            try:
                self.stdout.write(f"\n{'='*70}")
                self.stdout.write(f"Fetching {state} mappings from HADS...")
                
                response = requests.get(url, timeout=30)
                
                if response.status_code == 404:
                    self.stdout.write(self.style.WARNING(f"  No HADS file found for {state}"))
                    continue
                
                response.raise_for_status()
                
                lines = response.text.strip().split('\n')
                
                # Skip header lines (first 4 lines)
                data_lines = lines[4:]
                
                state_created = 0
                state_updated = 0
                state_skipped = 0
                
                for line in data_lines:
                    if not line.strip() or line.startswith('---'):
                        continue
                    
                    try:
                        # Parse fixed-width format
                        # IDENT(5) | STATION NUMBER(15) | GOES IDENTIFR(8) | NWS HSA(3) | LAT | LON | NAME
                        parts = [p.strip() for p in line.split('|')]
                        
                        if len(parts) < 7:
                            continue
                        
                        noaa_lid = parts[0].strip()
                        usgs_site = parts[1].strip()
                        goes_id = parts[2].strip()
                        nws_hsa = parts[3].strip()
                        latitude = parts[4].strip()
                        longitude = parts[5].strip()
                        location_name = parts[6].strip()
                        
                        if not noaa_lid or not usgs_site:
                            continue
                        
                        if dry_run:
                            self.stdout.write(
                                f"  [DRY RUN] Would map: {noaa_lid} <-> {usgs_site} ({location_name})"
                            )
                            state_created += 1
                            continue
                        
                        # Create bidirectional mappings using the existing schema
                        # USGS -> NOAA mapping
                        if usgs_site and noaa_lid:
                            mapping1, created1 = StationMapping.objects.update_or_create(
                                source_agency='USGS',
                                source_id=usgs_site,
                                target_agency='NOAA_RFC',
                                defaults={
                                    'target_id': noaa_lid,
                                }
                            )
                            
                            # NOAA -> USGS mapping (reverse)
                            mapping2, created2 = StationMapping.objects.update_or_create(
                                source_agency='NOAA_RFC',
                                source_id=noaa_lid,
                                target_agency='USGS',
                                defaults={
                                    'target_id': usgs_site,
                                }
                            )
                            
                            created = created1 or created2
                            
                            if created:
                                state_created += 1
                                self.stdout.write(
                                    f"  ✓ Created: {noaa_lid} <-> {usgs_site} ({location_name[:40]})"
                                )
                            else:
                                state_updated += 1
                                self.stdout.write(
                                    f"  ↻ Updated: {noaa_lid} <-> {usgs_site} ({location_name[:40]})"
                                )
                        else:
                            state_skipped += 1
                            if state_skipped <= 5:  # Only show first few
                                self.stdout.write(
                                    f"  - Skipped: {noaa_lid} <-> {usgs_site} (no IDs)"
                                )
                    
                    except Exception as e:
                        logger.error(f"Error parsing line: {line[:100]} - {e}")
                        continue
                
                # State summary
                self.stdout.write(f"\n{state} Summary:")
                self.stdout.write(f"  Created: {state_created}")
                self.stdout.write(f"  Updated: {state_updated}")
                if state_skipped > 0:
                    self.stdout.write(f"  Skipped: {state_skipped}")
                
                total_created += state_created
                total_updated += state_updated
                total_skipped += state_skipped
            
            except requests.exceptions.RequestException as e:
                self.stderr.write(f"  ✗ Error fetching {state}: {e}")
                continue
            except Exception as e:
                self.stderr.write(f"  ✗ Error processing {state}: {e}")
                logger.exception(f"Error processing {state}")
                continue
        
        # Overall summary
        self.stdout.write(f"\n{'='*70}")
        self.stdout.write(self.style.SUCCESS('HADS Mapping Load Complete!'))
        self.stdout.write(f"\nOverall Summary:")
        self.stdout.write(f"  States Processed: {len(states)}")
        self.stdout.write(f"  Mappings Created: {total_created}")
        self.stdout.write(f"  Mappings Updated: {total_updated}")
        if total_skipped > 0:
            self.stdout.write(f"  Entries Skipped: {total_skipped} (no matching MasterStation records)")
        self.stdout.write(f"\nTotal Active Mappings: {StationMapping.objects.count()}")
        self.stdout.write('='*70)
        
        # Provide next steps
        if total_skipped > 0 and not dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nNote: {total_skipped} entries were skipped because no matching MasterStation was found."
                )
            )
            self.stdout.write("To load missing stations, run:")
            self.stdout.write("  python manage.py load_master_stations --state WA")
            self.stdout.write("  python manage.py import_noaa_rfc_stations --states WA OR")
