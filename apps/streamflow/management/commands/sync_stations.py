"""Management command to create Station records for all configured stations."""

from django.core.management.base import BaseCommand
from apps.streamflow.models import (
    PullConfiguration,
    PullConfigurationStation,
    MasterStation,
    Station
)


class Command(BaseCommand):
    help = 'Create Station records for all configured stations from MasterStation data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            type=str,
            help='Specific configuration name to process',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        config_name = options.get('config')

        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS('SYNC STATION RECORDS'))
        if dry_run:
            self.stdout.write(self.style.WARNING('(DRY RUN - No changes will be made)'))
        self.stdout.write(self.style.SUCCESS('=' * 80))

        # Get configurations to process
        if config_name:
            configs = PullConfiguration.objects.filter(name=config_name)
            if not configs.exists():
                self.stdout.write(self.style.ERROR(f'Configuration "{config_name}" not found'))
                return
        else:
            configs = PullConfiguration.objects.all()

        total_checked = 0
        total_created = 0
        total_existing = 0

        for config in configs:
            self.stdout.write(f'\n{config.name}:')
            config_stations = config.configuration_stations.all()
            
            created_count = 0
            existing_count = 0
            
            for config_station in config_stations:
                total_checked += 1
                
                # Check if Station already exists
                if Station.objects.filter(station_number=config_station.station_number).exists():
                    existing_count += 1
                    total_existing += 1
                    continue
                
                # Get info from MasterStation
                master = MasterStation.objects.filter(
                    station_number=config_station.station_number
                ).first()
                
                if master:
                    # Create from MasterStation
                    if not dry_run:
                        Station.objects.create(
                            station_number=config_station.station_number,
                            name=master.station_name,
                            agency=master.agency,
                            latitude=master.latitude,
                            longitude=master.longitude,
                            state=master.state_code or '',
                            huc_code=master.huc_code or '',
                            is_active=True
                        )
                    created_count += 1
                    total_created += 1
                else:
                    # Create minimal record from config_station
                    if not dry_run:
                        Station.objects.create(
                            station_number=config_station.station_number,
                            name=config_station.station_name or f"Station {config_station.station_number}",
                            agency=config.data_source,
                            is_active=True
                        )
                    created_count += 1
                    total_created += 1
            
            self.stdout.write(f'  Total stations: {config_stations.count()}')
            self.stdout.write(f'  Already exist: {existing_count}')
            if created_count > 0:
                if dry_run:
                    self.stdout.write(self.style.WARNING(f'  Would create: {created_count}'))
                else:
                    self.stdout.write(self.style.SUCCESS(f'  Created: {created_count}'))

        self.stdout.write('\n' + '=' * 80)
        self.stdout.write(f'Total stations checked: {total_checked}')
        self.stdout.write(f'Already existed: {total_existing}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f'Would create: {total_created}'))
            self.stdout.write(self.style.WARNING('\nRun without --dry-run to actually create stations'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Created: {total_created}'))
        
        self.stdout.write('=' * 80)
