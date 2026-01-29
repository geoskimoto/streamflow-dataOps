"""
Management command to initialize raster datasets and configurations.

Creates database records for all supported data sources:
- NOAA NOMADS RTMA (hourly temperature, pressure, wind)
- NASA SMAP (daily soil moisture)
- NASA MODIS (daily land surface temperature - Terra & Aqua)
- NASA GPM (daily precipitation)
"""

from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Polygon
from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterPullConfiguration
)


class Command(BaseCommand):
    help = 'Initialize raster datasets, variables, extents, and pull configurations'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Overwrite existing datasets',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without creating it',
        )
    
    def handle(self, *args, **options):
        overwrite = options['overwrite']
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
        
        # Define spatial extents
        extents_data = [
            {
                'name': 'Western_US',
                'description': 'Western United States',
                'bbox': [-125.0, 31.0, -102.0, 49.0],
            },
            {
                'name': 'Pacific_Northwest',
                'description': 'Pacific Northwest (WA, OR, ID)',
                'bbox': [-125.0, 42.0, -111.0, 49.0],
            },
            {
                'name': 'Columbia_River_Basin',
                'description': 'Columbia River Basin (HUC 17)',
                'bbox': [-124.7, 41.5, -108.0, 49.0],
            },
        ]
        
        # Define datasets
        datasets_data = [
            {
                'name': 'NOAA_RTMA',
                'data_source': 'nomads',
                'collection_id': 'ds084.1',
                'description': 'NOAA Real-Time Mesoscale Analysis - Hourly temperature, pressure, wind',
                'resolution_m': 2500,
                'temporal_resolution': 'hourly',
                'update_frequency': 'hourly',
                'file_format': 'GRIB2',
                'is_active': True,
                'variables': [
                    {'name': 'tmp2m', 'description': '2-meter Air Temperature', 'units': 'K', 'standard_name': 'air_temperature'},
                    {'name': 'dpt2m', 'description': '2-meter Dewpoint Temperature', 'units': 'K', 'standard_name': 'dew_point_temperature'},
                    {'name': 'ugrd10m', 'description': '10-meter U-Wind Component', 'units': 'm/s', 'standard_name': 'eastward_wind'},
                    {'name': 'vgrd10m', 'description': '10-meter V-Wind Component', 'units': 'm/s', 'standard_name': 'northward_wind'},
                    {'name': 'wind10m', 'description': '10-meter Wind Speed', 'units': 'm/s', 'standard_name': 'wind_speed'},
                    {'name': 'pres', 'description': 'Surface Pressure', 'units': 'Pa', 'standard_name': 'surface_air_pressure'},
                ]
            },
            {
                'name': 'NASA_SMAP_L4',
                'data_source': 'earthdata',
                'collection_id': 'SPL4SMGP_008',
                'daac': 'NSIDC_CPRD',
                'description': 'NASA SMAP Level-4 Global Soil Moisture - Daily soil moisture analysis',
                'resolution_m': 9000,
                'temporal_resolution': 'daily',
                'update_frequency': 'daily',
                'file_format': 'NetCDF',
                'is_active': True,
                'variables': [
                    {'name': 'sm_surface', 'description': 'Surface Soil Moisture (0-5cm)', 'units': 'm³/m³', 'standard_name': 'volume_fraction_of_condensed_water_in_soil'},
                    {'name': 'sm_rootzone', 'description': 'Root Zone Soil Moisture (0-100cm)', 'units': 'm³/m³', 'standard_name': 'volume_fraction_of_condensed_water_in_soil'},
                    {'name': 'sm_profile', 'description': 'Profile Soil Moisture (0-200cm)', 'units': 'm³/m³', 'standard_name': 'volume_fraction_of_condensed_water_in_soil'},
                ]
            },
            {
                'name': 'MODIS_LST_Terra',
                'data_source': 'earthdata',
                'collection_id': 'MOD11A1',
                'daac': 'LPDAAC_ECS',
                'description': 'MODIS/Terra Land Surface Temperature (MOD11A1) - Daily 1km LST',
                'resolution_m': 1000,
                'temporal_resolution': 'daily',
                'update_frequency': 'daily',
                'file_format': 'HDF4',
                'is_active': True,
                'variables': [
                    {'name': 'LST_Day_1km', 'description': 'Daytime Land Surface Temperature', 'units': 'K', 'standard_name': 'surface_temperature'},
                    {'name': 'LST_Night_1km', 'description': 'Nighttime Land Surface Temperature', 'units': 'K', 'standard_name': 'surface_temperature'},
                    {'name': 'QC_Day', 'description': 'Daytime LST Quality Control', 'units': 'bit_field', 'standard_name': 'quality_flag'},
                    {'name': 'QC_Night', 'description': 'Nighttime LST Quality Control', 'units': 'bit_field', 'standard_name': 'quality_flag'},
                ]
            },
            {
                'name': 'MODIS_LST_Aqua',
                'data_source': 'earthdata',
                'collection_id': 'MYD11A1',
                'daac': 'LPDAAC_ECS',
                'description': 'MODIS/Aqua Land Surface Temperature (MYD11A1) - Daily 1km LST',
                'resolution_m': 1000,
                'temporal_resolution': 'daily',
                'update_frequency': 'daily',
                'file_format': 'HDF4',
                'is_active': True,
                'variables': [
                    {'name': 'LST_Day_1km', 'description': 'Daytime Land Surface Temperature', 'units': 'K', 'standard_name': 'surface_temperature'},
                    {'name': 'LST_Night_1km', 'description': 'Nighttime Land Surface Temperature', 'units': 'K', 'standard_name': 'surface_temperature'},
                    {'name': 'QC_Day', 'description': 'Daytime LST Quality Control', 'units': 'bit_field', 'standard_name': 'quality_flag'},
                    {'name': 'QC_Night', 'description': 'Nighttime LST Quality Control', 'units': 'bit_field', 'standard_name': 'quality_flag'},
                ]
            },
            {
                'name': 'NASA_GPM_IMERG',
                'data_source': 'earthdata',
                'collection_id': 'GPM_3IMERGDF_07',
                'daac': 'GES_DISC',
                'description': 'GPM IMERG Final Precipitation - Daily 0.1° global precipitation',
                'resolution_m': 11000,
                'temporal_resolution': 'daily',
                'update_frequency': 'daily',
                'file_format': 'NetCDF',
                'is_active': True,
                'variables': [
                    {'name': 'precipitation', 'description': 'Precipitation Rate', 'units': 'mm/hr', 'standard_name': 'precipitation_flux'},
                    {'name': 'precipitationCal', 'description': 'Calibrated Precipitation', 'units': 'mm/hr', 'standard_name': 'precipitation_flux'},
                    {'name': 'randomError', 'description': 'Random Error Estimate', 'units': 'mm/hr', 'standard_name': 'precipitation_flux'},
                ]
            },
            {
                'name': 'NCEP_StageIV_QPE',
                'data_source': 'nomads',
                'collection_id': 'pcpanl/prod',
                'description': 'NCEP Stage IV Quantitative Precipitation Estimate - quality-controlled CONUS mosaic',
                'resolution_m': 4000,
                'temporal_resolution': 'hourly',
                'update_frequency': 'hourly',
                'file_format': 'GRIB2',
                'is_active': True,
                'variables': [
                    {'name': 'precip_1hr', 'description': '1-hour accumulated precipitation', 'units': 'mm', 'standard_name': 'precipitation_amount', 'gee_band_name': 'apcp'},
                    {'name': 'precip_6hr', 'description': '6-hour accumulated precipitation', 'units': 'mm', 'standard_name': 'precipitation_amount', 'gee_band_name': 'apcp'},
                ]
            },
        ]
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write("RASTER DATASET INITIALIZATION")
        self.stdout.write("="*80 + "\n")
        
        # Create spatial extents
        self.stdout.write("\n📍 Creating Spatial Extents...")
        extent_objects = {}
        for extent_data in extents_data:
            name = extent_data['name']
            
            if not dry_run:
                bbox = extent_data['bbox']
                polygon = Polygon.from_bbox(bbox)
                
                extent, created = SpatialExtent.objects.get_or_create(
                    name=name,
                    defaults={
                        'description': extent_data['description'],
                        'min_lon': bbox[0],
                        'min_lat': bbox[1],
                        'max_lon': bbox[2],
                        'max_lat': bbox[3],
                        'geometry': polygon,
                    }
                )
                extent_objects[name] = extent
                
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Created: {name}"))
                else:
                    self.stdout.write(f"  - Exists: {name}")
            else:
                self.stdout.write(f"  [DRY RUN] Would create: {name}")
        
        # Create datasets and variables
        self.stdout.write("\n📦 Creating Datasets and Variables...")
        for dataset_data in datasets_data:
            name = dataset_data['name']
            variables_data = dataset_data.pop('variables')
            
            self.stdout.write(f"\n  Dataset: {name}")
            
            if not dry_run:
                # Create or update dataset
                if overwrite:
                    RasterDataset.objects.filter(name=name).delete()
                
                dataset, created = RasterDataset.objects.get_or_create(
                    name=name,
                    defaults=dataset_data
                )
                
                if created:
                    self.stdout.write(self.style.SUCCESS(f"    ✓ Created dataset"))
                else:
                    self.stdout.write(f"    - Dataset exists")
                
                # Create variables
                for var_data in variables_data:
                    variable, var_created = RasterVariable.objects.get_or_create(
                        dataset=dataset,
                        name=var_data['name'],
                        defaults={
                            'description': var_data['description'],
                            'unit': var_data['units'],
                            'gee_band_name': var_data.get('gee_band_name', var_data['name'])
                        }
                    )
                    
                    if var_created:
                        self.stdout.write(self.style.SUCCESS(f"      ✓ Variable: {var_data['name']}"))
                    else:
                        self.stdout.write(f"      - Variable exists: {var_data['name']}")
            else:
                self.stdout.write(f"    [DRY RUN] Would create dataset with {len(variables_data)} variables")
        
        # Create pull configurations
        if not dry_run:
            self.stdout.write("\n⚙️  Creating Pull Configurations...")
            
            # RTMA hourly configuration
            rtma_dataset = RasterDataset.objects.get(name='NOAA_RTMA')
            rtma_config, created = RasterPullConfiguration.objects.get_or_create(
                name='RTMA_Hourly_Western_US',
                dataset=rtma_dataset,
                defaults={
                    'description': 'Hourly RTMA temperature and wind for Western US',
                    'pull_frequency_hours': 1,
                    'lookback_days': 1,
                    'is_active': True
                }
            )
            if created:
                # Add all RTMA variables except QC
                rtma_config.variables.add(*rtma_dataset.variables.all())
                # Add Western US extent
                rtma_config.extents.add(extent_objects['Western_US'])
                self.stdout.write(self.style.SUCCESS("  ✓ RTMA hourly configuration"))
            
            # SMAP daily configuration
            smap_dataset = RasterDataset.objects.get(name='NASA_SMAP_L4')
            smap_config, created = RasterPullConfiguration.objects.get_or_create(
                name='SMAP_Daily_PNW',
                dataset=smap_dataset,
                defaults={
                    'description': 'Daily SMAP soil moisture for Pacific Northwest',
                    'pull_frequency_hours': 24,
                    'lookback_days': 2,
                    'is_active': True
                }
            )
            if created:
                smap_config.variables.add(*smap_dataset.variables.all())
                smap_config.extents.add(extent_objects['Pacific_Northwest'])
                self.stdout.write(self.style.SUCCESS("  ✓ SMAP daily configuration"))
            
            # MODIS Terra configuration
            modis_terra_dataset = RasterDataset.objects.get(name='MODIS_LST_Terra')
            modis_terra_config, created = RasterPullConfiguration.objects.get_or_create(
                name='MODIS_Terra_Daily_Western_US',
                dataset=modis_terra_dataset,
                defaults={
                    'description': 'Daily MODIS Terra LST for Western US',
                    'pull_frequency_hours': 24,
                    'lookback_days': 3,
                    'is_active': True
                }
            )
            if created:
                modis_terra_config.variables.add(*modis_terra_dataset.variables.filter(name__contains='LST'))
                modis_terra_config.extents.add(extent_objects['Western_US'])
                self.stdout.write(self.style.SUCCESS("  ✓ MODIS Terra daily configuration"))
            
            # Stage IV hourly configuration
            try:
                stage4_dataset = RasterDataset.objects.get(name='NCEP_StageIV_QPE')
                stage4_config, created = RasterPullConfiguration.objects.get_or_create(
                    name='StageIV_Hourly_Western_US',
                    dataset=stage4_dataset,
                    defaults={
                        'description': 'Hourly Stage IV QPE precipitation for Western US',
                        'pull_frequency_hours': 1,
                        'lookback_days': 1,
                        'is_active': True
                    }
                )
                if created:
                    # Add 1-hour precipitation variable
                    stage4_config.variables.add(*stage4_dataset.variables.filter(name='precip_1hr'))
                    stage4_config.extents.add(extent_objects['Western_US'])
                    self.stdout.write(self.style.SUCCESS("  ✓ Stage IV hourly configuration"))
            except RasterDataset.DoesNotExist:
                self.stdout.write(self.style.WARNING("  ! Stage IV dataset not found, skipping configuration"))
        
        # Summary
        if not dry_run:
            self.stdout.write("\n" + "="*80)
            self.stdout.write("SUMMARY")
            self.stdout.write("="*80)
            self.stdout.write(f"\n  Spatial Extents: {SpatialExtent.objects.count()}")
            self.stdout.write(f"  Datasets: {RasterDataset.objects.count()}")
            self.stdout.write(f"  Variables: {RasterVariable.objects.count()}")
            self.stdout.write(f"  Pull Configurations: {RasterPullConfiguration.objects.count()}")
            self.stdout.write("\n" + self.style.SUCCESS("✓ Initialization complete!"))
            self.stdout.write("\nNext steps:")
            self.stdout.write("  1. Start Celery worker: celery -A config worker -l info")
            self.stdout.write("  2. Start Celery beat: celery -A config beat -l info")
            self.stdout.write("  3. Monitor with Flower: celery -A config flower")
        else:
            self.stdout.write("\n" + self.style.WARNING("DRY RUN COMPLETE - No changes made"))
            self.stdout.write("\nRun without --dry-run to create datasets")
