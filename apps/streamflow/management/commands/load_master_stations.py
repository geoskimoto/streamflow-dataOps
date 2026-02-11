"""Django management command to load master station data from USGS."""

from django.core.management.base import BaseCommand
from apps.streamflow.models import MasterStation
import dataretrieval.nwis as nwis
import logging

logger = logging.getLogger(__name__)

# FIPS numeric code -> 2-letter state abbreviation
FIPS_TO_STATE = {
    '1': 'AL', '2': 'AK', '4': 'AZ', '5': 'AR', '6': 'CA',
    '8': 'CO', '9': 'CT', '10': 'DE', '11': 'DC', '12': 'FL',
    '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN',
    '19': 'IA', '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME',
    '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN', '28': 'MS',
    '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH',
    '34': 'NJ', '35': 'NM', '36': 'NY', '37': 'NC', '38': 'ND',
    '39': 'OH', '40': 'OK', '41': 'OR', '42': 'PA', '44': 'RI',
    '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT',
    '50': 'VT', '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI',
    '56': 'WY',
    '60': 'AS', '66': 'GU', '69': 'MP', '72': 'PR', '78': 'VI',
}


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
            
            for idx, row in sites_df.iterrows():
                try:
                    import math
                    
                    # Helper function to handle NaN values
                    def clean_decimal(value):
                        if value is None or (isinstance(value, float) and math.isnan(value)):
                            return None
                        return value
                    
                    # Get the actual USGS site number from the row data
                    site_no = row.get('site_no', '')
                    if not site_no:
                        continue
                    
                    station_data = {
                        'station_name': row.get('station_nm', ''),
                        'latitude': clean_decimal(row.get('dec_lat_va')),
                        'longitude': clean_decimal(row.get('dec_long_va')),
                        'state_code': FIPS_TO_STATE.get(str(row.get('state_cd', '')).strip(), row.get('state_cd', '')),
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
