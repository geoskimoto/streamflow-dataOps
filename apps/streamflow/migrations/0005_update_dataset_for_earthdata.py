# Generated migration for EarthData integration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('streamflow', '0004_auto_20250117_1805'),
    ]

    operations = [
        # Rename gee_collection_id to collection_id (more generic)
        migrations.RenameField(
            model_name='rasterdataset',
            old_name='gee_collection_id',
            new_name='collection_id',
        ),
        
        # Add data_source field
        migrations.AddField(
            model_name='rasterdataset',
            name='data_source',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('earthdata', 'NASA EarthData'),
                    ('nomads', 'NOAA NOMADS'),
                    ('gee', 'Google Earth Engine (deprecated)'),
                ],
                default='earthdata',
                help_text='Data source provider'
            ),
        ),
        
        # Add DAAC field (for EarthData)
        migrations.AddField(
            model_name='rasterdataset',
            name='daac',
            field=models.CharField(
                max_length=50,
                blank=True,
                null=True,
                help_text='NASA DAAC archive (e.g., NSIDC_CPRD, GES_DISC)'
            ),
        ),
        
        # Add file_format field
        migrations.AddField(
            model_name='rasterdataset',
            name='file_format',
            field=models.CharField(
                max_length=20,
                blank=True,
                null=True,
                help_text='Native file format (HDF5, NetCDF4, GRIB2, GeoTIFF)'
            ),
        ),
        
        # Add access_url_pattern field
        migrations.AddField(
            model_name='rasterdataset',
            name='access_url_pattern',
            field=models.CharField(
                max_length=500,
                blank=True,
                null=True,
                help_text='URL pattern for direct access (NOMADS, etc.)'
            ),
        ),
        
        # Update existing data - set defaults
        migrations.RunPython(
            update_existing_datasets,
            reverse_code=migrations.RunPython.noop,
        ),
    ]


def update_existing_datasets(apps, schema_editor):
    """Update existing RasterDataset records with new field values."""
    RasterDataset = apps.get_model('streamflow', 'RasterDataset')
    
    # Update SMAP dataset
    smap = RasterDataset.objects.filter(name='SMAP_L4_Soil_Moisture').first()
    if smap:
        smap.data_source = 'earthdata'
        smap.collection_id = 'SPL4SMGP_008'
        smap.daac = 'NSIDC_CPRD'
        smap.file_format = 'HDF5'
        smap.save()
    
    # Update GPM dataset (if exists)
    gpm = RasterDataset.objects.filter(name__icontains='GPM').first()
    if gpm:
        gpm.data_source = 'earthdata'
        gpm.collection_id = 'GPM_3IMERGDF_07'
        gpm.daac = 'GES_DISC'
        gpm.file_format = 'NetCDF4'
        gpm.save()
    
    # Update RTMA dataset
    rtma = RasterDataset.objects.filter(name__icontains='RTMA').first()
    if rtma:
        rtma.data_source = 'nomads'
        rtma.collection_id = 'rtma2p5'
        rtma.file_format = 'GRIB2'
        rtma.access_url_pattern = 'https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/'
        rtma.save()
