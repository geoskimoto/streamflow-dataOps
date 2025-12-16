"""Django management command to load Environment Canada stations."""

from django.core.management.base import BaseCommand
from apps.streamflow.models import MasterStation
import requests
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Load master station list from Environment Canada (British Columbia)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--province',
            type=str,
            default='BC',
            help='Province code (default: BC for British Columbia)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing EC stations before loading',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing Environment Canada stations...')
            count = MasterStation.objects.filter(agency='EC').delete()[0]
            self.stdout.write(self.style.SUCCESS(f'Deleted {count} EC stations'))

        province = options['province']
        
        self.stdout.write(
            self.style.WARNING(
                f'\nNOTE: Environment Canada station loading requires manual data.\n'
                f'The EC web services have changed and may require specific API access.\n\n'
                f'To load BC stations, you have two options:\n\n'
                f'1. Download station list from: https://wateroffice.ec.gc.ca/\n'
                f'   - Click "Station Search"\n'
                f'   - Select Province: British Columbia\n'
                f'   - Download the station list as CSV\n'
                f'   - Load using: python manage.py load_ec_stations_csv --csv-file <file>\n\n'
                f'2. Use the Canada dataRetrieval package (if available):\n'
                f'   - pip install dataretrieval\n'
                f'   - This command will be updated to use it\n\n'
                f'For now, here are some major BC stations you can add manually:\n'
            )
        )
        
        # Sample major BC stations (add these manually or via CSV)
        sample_stations = [
            {
                'station_number': '08MF005',
                'station_name': 'FRASER RIVER AT HOPE',
                'latitude': 49.3833,
                'longitude': -121.4500,
                'state_code': 'BC',
                'agency': 'EC',
            },
            {
                'station_number': '08GA010',
                'station_name': 'CAMPBELL RIVER NEAR CAMPBELL RIVER',
                'latitude': 50.0167,
                'longitude': -125.3333,
                'state_code': 'BC',
                'agency': 'EC',
            },
            {
                'station_number': '08HB002',
                'station_name': 'COLUMBIA RIVER AT NICHOLSON',
                'latitude': 50.5500,
                'longitude': -116.4667,
                'state_code': 'BC',
                'agency': 'EC',
            },
        ]
        
        self.stdout.write('\nSample major BC stations:\n')
        for station in sample_stations:
            self.stdout.write(
                f"  {station['station_number']}: {station['station_name']}"
            )
        
        # Ask if user wants to add these sample stations
        self.stdout.write('\n')
        response = input('Would you like to add these sample BC stations? (yes/no): ')
        
        if response.lower() in ['yes', 'y']:
            created_count = 0
            for station_data in sample_stations:
                station, created = MasterStation.objects.update_or_create(
                    station_number=station_data['station_number'],
                    defaults=station_data
                )
                if created:
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  ✓ Added {station_data['station_number']}"
                        )
                    )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nSuccessfully added {created_count} BC stations'
                )
            )
        else:
            self.stdout.write('Skipped adding sample stations.')
