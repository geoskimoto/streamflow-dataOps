"""Django management command to load station ID mappings (USGS <-> NOAA-HADS)."""

from django.core.management.base import BaseCommand
from apps.streamflow.models import StationMapping
import requests
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Load station ID mappings between USGS and NOAA-HADS'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-file',
            type=str,
            help='Path to CSV file with mapping data (columns: usgs_id, hads_id)',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing mappings before loading',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing station mappings...')
            count = StationMapping.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(f'Deleted {count} mappings'))

        if not options['csv_file']:
            self.stdout.write(
                self.style.WARNING(
                    'No CSV file specified. You can provide a CSV file with columns: '
                    'usgs_id, hads_id'
                )
            )
            self.stdout.write(
                '\nExample CSV format:\n'
                'usgs_id,hads_id\n'
                '01646500,WASW2\n'
                '01638500,SENM2\n'
            )
            return

        # Load from CSV
        import csv
        
        try:
            created_count = 0
            updated_count = 0
            
            with open(options['csv_file'], 'r') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    try:
                        usgs_id = row['usgs_id'].strip()
                        hads_id = row['hads_id'].strip()
                        
                        if not usgs_id or not hads_id:
                            continue
                        
                        mapping, created = StationMapping.objects.update_or_create(
                            source_agency='USGS',
                            source_id=usgs_id,
                            target_agency='NOAA-HADS',
                            defaults={'target_id': hads_id}
                        )
                        
                        if created:
                            created_count += 1
                        else:
                            updated_count += 1
                    
                    except KeyError as e:
                        self.stdout.write(
                            self.style.WARNING(f'Missing column in CSV: {e}')
                        )
                        continue
                    except Exception as e:
                        self.stdout.write(
                            self.style.WARNING(f'Error loading mapping: {e}')
                        )
                        continue
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully loaded {created_count} new mappings, '
                    f'updated {updated_count} existing mappings'
                )
            )
        
        except FileNotFoundError:
            self.stdout.write(
                self.style.ERROR(f'File not found: {options["csv_file"]}')
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error loading mappings: {e}'))
            raise
