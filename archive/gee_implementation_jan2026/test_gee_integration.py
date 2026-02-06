"""Integration tests for Google Earth Engine data pulls."""

import os
import django
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import TestCase
from django.conf import settings
from django.utils import timezone

from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterLayer,
    RasterPullConfiguration,
    RasterPullLog
)
from src.acquisition.gee_client import GEEClient, GEEAuthenticationError
from src.acquisition.raster_processor import RasterProcessor


class GEEAuthenticationTest(TestCase):
    """Test Google Earth Engine authentication."""
    
    def test_gee_client_initialization(self):
        """Test that GEE client can be initialized."""
        try:
            client = GEEClient()
            self.assertIsNotNone(client)
        except GEEAuthenticationError as e:
            self.fail(f"GEE authentication failed: {e}")
    
    def test_gee_client_authenticated(self):
        """Test that GEE client is authenticated."""
        client = GEEClient()
        self.assertTrue(client.authenticated, "GEE client should be authenticated")
    
    def test_service_account_key_exists(self):
        """Test that service account key file exists."""
        key_path = settings.GEE_SERVICE_ACCOUNT_KEY
        self.assertTrue(os.path.exists(key_path), 
                       f"Service account key not found at: {key_path}")
    
    def test_service_account_email_configured(self):
        """Test that service account email is configured."""
        email = settings.GEE_SERVICE_ACCOUNT_EMAIL
        self.assertIsNotNone(email)
        self.assertIn('@', email)
        self.assertIn('.iam.gserviceaccount.com', email)


class GEEDataAvailabilityTest(TestCase):
    """Test data availability checks."""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = GEEClient()
        cls.bbox = settings.HUC17_BBOX
    
    def test_rtma_data_available(self):
        """Test that RTMA data is available."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        availability = self.client.check_data_availability(
            collection_id=settings.GEE_DATASETS['RTMA'],
            start_date=start_date,
            end_date=end_date,
            bbox=self.bbox
        )
        
        self.assertTrue(availability['available'], 
                       "RTMA data should be available")
        self.assertGreater(availability['count'], 0,
                          "RTMA should have images in the date range")
    
    def test_smap_data_available(self):
        """Test that SMAP data is available."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        availability = self.client.check_data_availability(
            collection_id=settings.GEE_DATASETS['SMAP_SPL4'],
            start_date=start_date,
            end_date=end_date,
            bbox=self.bbox
        )
        
        self.assertTrue(availability['available'], 
                       "SMAP data should be available")
        self.assertGreater(availability['count'], 0,
                          "SMAP should have images in the date range")


class RTMADataPullTest(TestCase):
    """Test RTMA data pulling."""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = GEEClient()
        cls.bbox = settings.HUC17_BBOX
    
    def test_fetch_rtma_temperature(self):
        """Test fetching RTMA temperature data."""
        # Try to fetch yesterday's data at noon
        test_time = datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        
        image = self.client.get_rtma_image(
            variable='temperature',
            timestamp=test_time,
            bbox=self.bbox,
            resolution=2500
        )
        
        self.assertIsNotNone(image, 
                           f"Should fetch RTMA temperature for {test_time}")
    
    def test_fetch_rtma_precipitation(self):
        """Test fetching RTMA precipitation data."""
        test_time = datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        
        image = self.client.get_rtma_image(
            variable='precipitation',
            timestamp=test_time,
            bbox=self.bbox,
            resolution=2500
        )
        
        self.assertIsNotNone(image,
                           f"Should fetch RTMA precipitation for {test_time}")
    
    def test_fetch_rtma_wind_speed(self):
        """Test fetching RTMA wind speed data."""
        test_time = datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        
        image = self.client.get_rtma_image(
            variable='wind_speed',
            timestamp=test_time,
            bbox=self.bbox,
            resolution=2500
        )
        
        self.assertIsNotNone(image,
                           f"Should fetch RTMA wind speed for {test_time}")
    
    def test_rtma_statistics(self):
        """Test getting statistics from RTMA image."""
        test_time = datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        
        image = self.client.get_rtma_image(
            variable='temperature',
            timestamp=test_time,
            bbox=self.bbox,
            resolution=2500
        )
        
        if image:
            stats = self.client.get_image_statistics(
                image, self.bbox, scale=2500
            )
            
            self.assertIsNotNone(stats)
            self.assertIn('min', stats)
            self.assertIn('max', stats)
            self.assertIn('mean', stats)
            self.assertIn('std_dev', stats)
            
            # Temperature should be in reasonable range (Kelvin)
            self.assertGreater(stats['min'], 200)
            self.assertLess(stats['max'], 350)


class SMAPDataPullTest(TestCase):
    """Test SMAP data pulling."""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = GEEClient()
        cls.bbox = settings.HUC17_BBOX
    
    def test_fetch_smap_surface(self):
        """Test fetching SMAP surface soil moisture."""
        test_date = (datetime.now() - timedelta(days=2)).date()
        
        image = self.client.get_smap_image(
            variable='soil_moisture_surface',
            date=test_date,
            bbox=self.bbox,
            resolution=9000
        )
        
        self.assertIsNotNone(image,
                           f"Should fetch SMAP surface for {test_date}")
    
    def test_fetch_smap_rootzone(self):
        """Test fetching SMAP root zone soil moisture."""
        test_date = (datetime.now() - timedelta(days=2)).date()
        
        image = self.client.get_smap_image(
            variable='soil_moisture_rootzone',
            date=test_date,
            bbox=self.bbox,
            resolution=9000
        )
        
        self.assertIsNotNone(image,
                           f"Should fetch SMAP rootzone for {test_date}")
    
    def test_smap_statistics(self):
        """Test getting statistics from SMAP image."""
        test_date = (datetime.now() - timedelta(days=2)).date()
        
        image = self.client.get_smap_image(
            variable='soil_moisture_surface',
            date=test_date,
            bbox=self.bbox,
            resolution=9000
        )
        
        if image:
            stats = self.client.get_image_statistics(
                image, self.bbox, scale=9000
            )
            
            self.assertIsNotNone(stats)
            self.assertIn('min', stats)
            self.assertIn('max', stats)
            self.assertIn('mean', stats)
            
            # Soil moisture should be 0-1 range
            self.assertGreaterEqual(stats['min'], 0)
            self.assertLessEqual(stats['max'], 1)


class GeoTIFFExportTest(TestCase):
    """Test GeoTIFF export functionality."""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = GEEClient()
        cls.bbox = settings.HUC17_BBOX
        cls.output_dir = Path(settings.RASTER_ROOT) / 'test'
        cls.output_dir.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        # Clean up test files
        if cls.output_dir.exists():
            for file in cls.output_dir.glob('*.tif'):
                file.unlink()
    
    def test_export_rtma_geotiff(self):
        """Test exporting RTMA data to GeoTIFF."""
        test_time = datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        
        image = self.client.get_rtma_image(
            variable='temperature',
            timestamp=test_time,
            bbox=self.bbox,
            resolution=2500
        )
        
        if image:
            output_path = self.output_dir / 'test_rtma_temp.tif'
            
            metadata = self.client.export_to_geotiff(
                image=image,
                output_path=output_path,
                bbox=self.bbox,
                scale=2500
            )
            
            self.assertTrue(output_path.exists(),
                          "GeoTIFF file should be created")
            self.assertGreater(output_path.stat().st_size, 0,
                             "GeoTIFF file should not be empty")
            self.assertIn('file_path', metadata)
            self.assertIn('file_size', metadata)
    
    def test_export_smap_geotiff(self):
        """Test exporting SMAP data to GeoTIFF."""
        test_date = (datetime.now() - timedelta(days=2)).date()
        
        image = self.client.get_smap_image(
            variable='soil_moisture_surface',
            date=test_date,
            bbox=self.bbox,
            resolution=9000
        )
        
        if image:
            output_path = self.output_dir / 'test_smap_surface.tif'
            
            metadata = self.client.export_to_geotiff(
                image=image,
                output_path=output_path,
                bbox=self.bbox,
                scale=9000
            )
            
            self.assertTrue(output_path.exists(),
                          "GeoTIFF file should be created")
            self.assertGreater(output_path.stat().st_size, 0,
                             "GeoTIFF file should not be empty")


class RasterProcessingTest(TestCase):
    """Test raster processing functionality."""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.processor = RasterProcessor()
        cls.client = GEEClient()
        cls.bbox = settings.HUC17_BBOX
        cls.test_dir = Path(settings.RASTER_ROOT) / 'test'
        cls.test_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a test raster
        test_time = datetime.now().replace(
            hour=12, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        
        image = cls.client.get_rtma_image(
            variable='temperature',
            timestamp=test_time,
            bbox=cls.bbox,
            resolution=2500
        )
        
        if image:
            cls.test_file = cls.test_dir / 'test_process.tif'
            cls.client.export_to_geotiff(
                image=image,
                output_path=cls.test_file,
                bbox=cls.bbox,
                scale=2500
            )
    
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if cls.test_dir.exists():
            for file in cls.test_dir.glob('*'):
                file.unlink()
    
    def test_calculate_statistics(self):
        """Test calculating raster statistics."""
        if hasattr(self.__class__, 'test_file') and self.test_file.exists():
            stats = self.processor.calculate_statistics(self.test_file)
            
            self.assertIn('width', stats)
            self.assertIn('height', stats)
            self.assertIn('min_value', stats)
            self.assertIn('max_value', stats)
            self.assertIn('mean_value', stats)
            self.assertIn('std_dev', stats)
    
    def test_validate_raster(self):
        """Test raster validation."""
        if hasattr(self.__class__, 'test_file') and self.test_file.exists():
            is_valid, errors = self.processor.validate_raster(
                self.test_file,
                expected_bbox=self.bbox,
                expected_crs='EPSG:4326'
            )
            
            self.assertTrue(is_valid, f"Raster should be valid: {errors}")
    
    def test_generate_thumbnail(self):
        """Test thumbnail generation."""
        if hasattr(self.__class__, 'test_file') and self.test_file.exists():
            thumb_path = self.test_file.with_suffix('.thumb.png')
            
            result = self.processor.generate_thumbnail(
                self.test_file,
                thumb_path
            )
            
            self.assertTrue(result.exists(),
                          "Thumbnail should be created")
            self.assertGreater(result.stat().st_size, 0,
                             "Thumbnail should not be empty")


class DatabaseModelsTest(TestCase):
    """Test raster database models."""
    
    def setUp(self):
        """Set up test data."""
        # Create dataset
        self.dataset = RasterDataset.objects.create(
            name='TEST_RTMA',
            gee_collection_id='TEST/COLLECTION',
            resolution_m=2500,
            temporal_resolution='hourly'
        )
        
        # Create variable
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='test_temperature',
            gee_band_name='TMP',
            unit='Kelvin',
            min_valid_value=200.0,
            max_valid_value=350.0
        )
        
        # Create extent
        self.extent = SpatialExtent.objects.create(
            name='TEST_HUC17',
            min_lon=-124.7,
            min_lat=41.5,
            max_lon=-108.0,
            max_lat=49.0
        )
    
    def test_create_raster_layer(self):
        """Test creating a raster layer."""
        layer = RasterLayer.objects.create(
            variable=self.variable,
            extent=self.extent,
            timestamp=timezone.now(),
            date=timezone.now().date(),
            file_path='test/path.tif',
            file_size_bytes=1024,
            resolution_m=2500,
            width_pixels=100,
            height_pixels=100,
            crs='EPSG:4326',
            is_valid=True
        )
        
        self.assertIsNotNone(layer.id)
        self.assertEqual(layer.variable, self.variable)
        self.assertEqual(layer.extent, self.extent)
    
    def test_create_pull_configuration(self):
        """Test creating a pull configuration."""
        config = RasterPullConfiguration.objects.create(
            name='Test Config',
            dataset=self.dataset,
            pull_frequency_hours=8,
            lookback_days=7
        )
        
        config.variables.add(self.variable)
        config.extents.add(self.extent)
        
        self.assertIsNotNone(config.id)
        self.assertEqual(config.variables.count(), 1)
        self.assertEqual(config.extents.count(), 1)
    
    def test_create_pull_log(self):
        """Test creating a pull log."""
        config = RasterPullConfiguration.objects.create(
            name='Test Config',
            dataset=self.dataset,
            pull_frequency_hours=8
        )
        
        log = RasterPullLog.objects.create(
            configuration=config,
            status='success',
            started_at=timezone.now(),
            completed_at=timezone.now(),
            layers_attempted=10,
            layers_successful=10,
            layers_failed=0
        )
        
        self.assertIsNotNone(log.id)
        self.assertEqual(log.status, 'success')
        log.calculate_duration()
        self.assertIsNotNone(log.duration_seconds)


class EndToEndPullTest(TestCase):
    """End-to-end test of complete data pull workflow."""
    
    def setUp(self):
        """Set up test configuration."""
        # Create dataset
        self.dataset = RasterDataset.objects.create(
            name='RTMA',
            gee_collection_id=settings.GEE_DATASETS['RTMA'],
            resolution_m=2500,
            temporal_resolution='hourly'
        )
        
        # Create variable
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='temperature',
            gee_band_name='TMP',
            unit='Kelvin',
            min_valid_value=200.0,
            max_valid_value=350.0
        )
        
        # Create extent
        self.extent = SpatialExtent.objects.create(
            name='HUC_17',
            min_lon=-124.7,
            min_lat=41.5,
            max_lon=-108.0,
            max_lat=49.0
        )
        
        # Create configuration
        self.config = RasterPullConfiguration.objects.create(
            name='Test E2E Config',
            dataset=self.dataset,
            pull_frequency_hours=8,
            lookback_days=1,
            compression_enabled=True,
            thumbnail_enabled=True
        )
        
        self.config.variables.add(self.variable)
        self.config.extents.add(self.extent)
    
    def test_full_pull_workflow(self):
        """Test complete pull workflow from config to database."""
        from src.acquisition.raster_tasks import pull_raster_data
        
        # Define small date range for testing
        end_date = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        start_date = end_date - timedelta(hours=2)
        
        # Run pull
        result = pull_raster_data(
            self.config.id,
            start_date.isoformat(),
            end_date.isoformat()
        )
        
        # Check results
        self.assertNotIn('error', result, 
                        f"Pull should not have errors: {result.get('error')}")
        self.assertGreater(result['attempted'], 0,
                         "Should attempt to pull data")
        
        # Check that layers were created
        layers = RasterLayer.objects.filter(
            variable=self.variable,
            extent=self.extent
        )
        
        self.assertGreater(layers.count(), 0,
                         "Should create raster layers")
        
        # Check pull log was created
        logs = RasterPullLog.objects.filter(configuration=self.config)
        self.assertEqual(logs.count(), 1, "Should create pull log")
        
        log = logs.first()
        self.assertIn(log.status, ['success', 'partial'],
                     f"Pull should succeed or partially succeed: {log.status}")
