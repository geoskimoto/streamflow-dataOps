"""Django management command to load master station data from USGS."""

from django.core.management.base import BaseCommand
from apps.streamflow.models import MasterStation
import dataretrieval.nwis as nwis
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Load master station list from USGS by state or HUC'

    def add_arguments(self, parser):
        parser.add_argument(
            '--state',
            type=str,
            help='State code (e.g., VA, DC, MD)',
        )
        parser.add_argument(
            '--huc',
            type=str,
            help='HUC code (e.g., 02070010 for 8-digit HUC)',
        )
        parser.add_argument(
            '--site-type',
            type=str,
            default='ST',
            help='Site type code (default: ST for stream)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing stations before loading',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing master stations...')
            count = MasterStation.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'Deleted {count} stations'))

        # Build query parameters
        if not options['state'] and not options['huc']:
            self.stdout.write(
                self.style.ERROR('Must specify either --state or --huc')
            )
            return

        self.stdout.write('Fetching stations from USGS...')
        
        try:
            # Get sites using dataretrieval
            kwargs = {
                'parameterCd': '00060',  # Discharge
                'siteType': options['site_type'],
                'hasDataTypeCd': 'dv',  # Daily values
            }
            
            if options['state']:
                kwargs['stateCd'] = options['state']
                self.stdout.write(f"Querying for state: {options['state']}")
            
            if options['huc']:
                kwargs['huc'] = options['huc']
                self.stdout.write(f"Querying for HUC: {options['huc']}")
            
            # Fetch site info - get_info returns a tuple (dataframe, metadata)
            result = nwis.get_info(**kwargs)
            if isinstance(result, tuple):
                sites_df, metadata = result
            else:
                sites_df = result
            
            if sites_df is None or sites_df.empty:
                self.stdout.write(self.style.WARNING('No stations found'))
                return
            
            self.stdout.write(f'Found {len(sites_df)} stations')
            
            # Load into database
            created_count = 0
            updated_count = 0
            
            for site_no, row in sites_df.iterrows():
                try:
                    import math
                    
                    # Helper function to handle NaN values
                    def clean_decimal(value):
                        if value is None or (isinstance(value, float) and math.isnan(value)):
                            return None
                        return value
                    
                    station_data = {
                        'station_name': row.get('station_nm', ''),
                        'latitude': clean_decimal(row.get('dec_lat_va')),
                        'longitude': clean_decimal(row.get('dec_long_va')),
                        'state_code': row.get('state_cd', ''),
                        'huc_code': row.get('huc_cd', ''),
                        'altitude_ft': clean_decimal(row.get('alt_va')),
                        'drainage_area_sqmi': clean_decimal(row.get('drain_area_va')),
                        'agency': 'USGS',
                    }
                    
                    station, created = MasterStation.objects.update_or_create(
                        station_number=site_no,
                        defaults=station_data
                    )
                    
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                
                except Exception as e:
                    self.stdout.write(
                        self.style.WARNING(f'Error loading station {site_no}: {e}')
                    )
                    continue
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully loaded {created_count} new stations, '
                    f'updated {updated_count} existing stations'
                )
            )
        
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error fetching stations: {e}'))
            raise
