"""Management command to setup raster datasets in the database."""

from django.core.management.base import BaseCommand
from django.conf import settings

from apps.streamflow.models import RasterDataset, RasterVariable


class Command(BaseCommand):
    """Setup raster datasets and variables in database."""
    
    help = 'Setup raster datasets and variables from GEE configuration'
    
    def handle(self, *args, **options):
        """Execute command."""
        self.stdout.write("Setting up raster datasets and variables...")
        
        datasets_created = 0
        variables_created = 0
        
        # RTMA Dataset
        rtma, created = RasterDataset.objects.get_or_create(
            name='RTMA',
            defaults={
                'gee_collection_id': settings.GEE_DATASETS['RTMA'],
                'description': 'NOAA Real-Time Mesoscale Analysis - High-resolution meteorological analysis',
                'resolution_m': 2500,
                'temporal_resolution': 'hourly',
                'update_frequency': 'hourly',
                'is_active': True
            }
        )
        if created:
            datasets_created += 1
            self.stdout.write(self.style.SUCCESS(f"  ✓ Created dataset: RTMA"))
        else:
            self.stdout.write(f"  - Dataset already exists: RTMA")
        
        # RTMA Variables
        rtma_vars = [
            {
                'name': 'temperature',
                'gee_band_name': 'TMP',
                'unit': 'Kelvin',
                'description': '2-meter air temperature',
                'min_valid_value': 200.0,
                'max_valid_value': 350.0,
            },
            {
                'name': 'precipitation',
                'gee_band_name': 'APCP',
                'unit': 'kg/m^2',
                'description': 'Accumulated precipitation',
                'min_valid_value': 0.0,
                'max_valid_value': 1000.0,
            },
            {
                'name': 'wind_speed',
                'gee_band_name': 'WIND',
                'unit': 'm/s',
                'description': '10-meter wind speed',
                'min_valid_value': 0.0,
                'max_valid_value': 100.0,
            },
        ]
        
        for var_data in rtma_vars:
            var, created = RasterVariable.objects.get_or_create(
                dataset=rtma,
                name=var_data['name'],
                defaults=var_data
            )
            if created:
                variables_created += 1
                self.stdout.write(self.style.SUCCESS(f"    ✓ Created variable: {var_data['name']}"))
            else:
                self.stdout.write(f"    - Variable already exists: {var_data['name']}")
        
        # SMAP Dataset
        smap, created = RasterDataset.objects.get_or_create(
            name='SMAP_SPL4',
            defaults={
                'gee_collection_id': settings.GEE_DATASETS['SMAP_SPL4'],
                'description': 'NASA SMAP Level 4 Global 3-hourly Surface and Root Zone Soil Moisture',
                'resolution_m': 9000,
                'temporal_resolution': 'daily',
                'update_frequency': 'daily',
                'is_active': True
            }
        )
        if created:
            datasets_created += 1
            self.stdout.write(self.style.SUCCESS(f"  ✓ Created dataset: SMAP_SPL4"))
        else:
            self.stdout.write(f"  - Dataset already exists: SMAP_SPL4")
        
        # SMAP Variables
        smap_vars = [
            {
                'name': 'soil_moisture_surface',
                'gee_band_name': 'sm_surface',
                'unit': 'm^3/m^3',
                'description': 'Surface soil moisture (0-5cm)',
                'min_valid_value': 0.0,
                'max_valid_value': 1.0,
            },
            {
                'name': 'soil_moisture_rootzone',
                'gee_band_name': 'sm_rootzone',
                'unit': 'm^3/m^3',
                'description': 'Root zone soil moisture (0-100cm)',
                'min_valid_value': 0.0,
                'max_valid_value': 1.0,
            },
        ]
        
        for var_data in smap_vars:
            var, created = RasterVariable.objects.get_or_create(
                dataset=smap,
                name=var_data['name'],
                defaults=var_data
            )
            if created:
                variables_created += 1
                self.stdout.write(self.style.SUCCESS(f"    ✓ Created variable: {var_data['name']}"))
            else:
                self.stdout.write(f"    - Variable already exists: {var_data['name']}")
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS(
            f"Setup complete: {datasets_created} datasets, {variables_created} variables created"
        ))
