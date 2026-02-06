"""
Management command to add HUC17 stations to a configuration.
"""

from django.core.management.base import BaseCommand
from apps.streamflow.models import (
    PullConfiguration,
    Station,
    PullConfigurationStation,
    MasterStation
)


class Command(BaseCommand):
    help = 'Add HUC17 (Columbia River Basin) stations to a configuration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--config-id',
            type=int,
            help='ID of the configuration to add stations to'
        )
        parser.add_argument(
            '--config-name',
            type=str,
            help='Name of the configuration (searches for substring)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of stations to add (for testing)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing stations from configuration first'
        )

    def handle(self, *args, **options):
        # Find configuration
        if options['config_id']:
            try:
                config = PullConfiguration.objects.get(id=options['config_id'])
            except PullConfiguration.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Configuration with ID {options["config_id"]} not found'))
                return
        elif options['config_name']:
            configs = PullConfiguration.objects.filter(name__icontains=options['config_name'])
            if not configs.exists():
                self.stdout.write(self.style.ERROR(f'No configuration found matching "{options["config_name"]}"'))
                return
            elif configs.count() > 1:
                self.stdout.write(self.style.WARNING(f'Multiple configurations found:'))
                for c in configs:
                    self.stdout.write(f'  ID {c.id}: {c.name}')
                self.stdout.write(self.style.WARNING('Please specify --config-id'))
                return
            config = configs.first()
        else:
            # Try to find HUC17 configuration
            configs = PullConfiguration.objects.filter(name__icontains='HUC 17')
            if not configs.exists():
                self.stdout.write(self.style.ERROR('No HUC17 configuration found. Use --config-id or --config-name'))
                self.stdout.write('\nAvailable configurations:')
                for c in PullConfiguration.objects.all():
                    self.stdout.write(f'  ID {c.id}: {c.name}')
                return
            config = configs.first()

        self.stdout.write(f'\nConfiguration: {config.name} (ID: {config.id})')
        self.stdout.write(f'Data Source: {config.data_source}')

        # Clear existing if requested
        if options['clear']:
            existing_count = config.configuration_stations.count()
            if existing_count > 0:
                config.configuration_stations.all().delete()
                self.stdout.write(self.style.WARNING(f'Cleared {existing_count} existing stations'))

        # Find HUC17 stations
        self.stdout.write('\nSearching for HUC17 stations...')
        
        # Get stations from Station table (working stations)
        huc17_stations = Station.objects.filter(
            huc_code__startswith='17',
            agency='USGS',
            is_active=True
        ).order_by('station_number')

        if options['limit']:
            huc17_stations = huc17_stations[:options['limit']]

        total_found = huc17_stations.count()
        self.stdout.write(f'Found {total_found} HUC17 USGS stations')

        if total_found == 0:
            self.stdout.write(self.style.ERROR('No HUC17 stations found!'))
            self.stdout.write('\nYou may need to import stations from MasterStation first.')
            
            # Check MasterStation
            master_count = MasterStation.objects.filter(
                huc_code__startswith='17',
                agency='USGS'
            ).count()
            self.stdout.write(f'MasterStation has {master_count} HUC17 USGS stations')
            
            if master_count > 0:
                self.stdout.write('\nTo import from MasterStation to Station:')
                self.stdout.write('  1. Use the web interface: /stations/ -> Import from Master')
                self.stdout.write('  2. Or create stations programmatically')
            return

        # Add stations to configuration
        self.stdout.write(f'\nAdding stations to configuration...')
        added = 0
        skipped = 0
        
        for station in huc17_stations:
            # Check if already exists
            exists = PullConfigurationStation.objects.filter(
                configuration=config,
                station_number=station.station_number
            ).exists()
            
            if exists:
                skipped += 1
                continue
                
            # Create configuration station
            PullConfigurationStation.objects.create(
                configuration=config,
                station_number=station.station_number,
                station_name=station.name,
                huc_code=station.huc_code,
                state=station.state
            )
            added += 1
            
            if added % 10 == 0:
                self.stdout.write(f'  Added {added} stations...')

        self.stdout.write(self.style.SUCCESS(f'\n✅ Complete!'))
        self.stdout.write(f'  Added: {added} stations')
        self.stdout.write(f'  Skipped: {skipped} (already in configuration)')
        self.stdout.write(f'  Total in configuration: {config.configuration_stations.count()}')
        
        # Show sample stations
        self.stdout.write(f'\nSample stations in configuration:')
        for pcs in config.configuration_stations.all()[:5]:
            self.stdout.write(f'  {pcs.station_number}: {pcs.station_name}')
        
        self.stdout.write(self.style.SUCCESS(f'\nConfiguration ready! Data pulls will now process these stations.'))
