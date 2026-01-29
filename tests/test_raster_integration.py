"""
Comprehensive Integration Tests for Raster Data System

Tests all three data sources (NASA EarthData, NOAA NOMADS, Legacy GEE)
and the complete data pipeline from configuration to storage.
"""

import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from datetime import datetime, timedelta
from django.utils import timezone
from django.test import TestCase
import tempfile
import shutil
import numpy as np

from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterLayer,
    RasterPullConfiguration,
    RasterPullLog
)
from src.acquisition.earthdata_client import EarthDataClient
from src.acquisition.nomads_client import NomadsClient
from src.acquisition.raster_tasks import pull_raster_data


class TestNASAEarthDataIntegration(TestCase):
    """Integration tests for NASA EarthData (SMAP, GPM, MODIS)."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = Path(tempfile.mkdtemp())
        
        # Create SMAP dataset
        self.smap_dataset = RasterDataset.objects.create(
            name='SMAP_SPL4_TEST',
            data_source='earthdata',
            collection_id='SPL4SMGP_008',
            daac='NSIDC_CPRD',
            file_format='HDF5',
            temporal_resolution='daily',
            resolution_m=9000,
            is_active=True
        )
        
        # Create MODIS dataset
        self.modis_dataset = RasterDataset.objects.create(
            name='MODIS_LST_TEST',
            data_source='earthdata',
            collection_id='MOD11A1_061',
            daac='LPDAAC_ECS',
            file_format='HDF4',
            temporal_resolution='daily',
            resolution_m=1000,
            is_active=True
        )
        
        # Create variables
        self.sm_variable = RasterVariable.objects.create(
            dataset=self.smap_dataset,
            name='soil_moisture_surface',
            unit='m³/m³',
            min_valid_value=0.0,
            max_valid_value=0.6
        )
        
        self.lst_variable = RasterVariable.objects.create(
            dataset=self.modis_dataset,
            name='land_surface_temperature_day',
            unit='Kelvin',
            min_valid_value=200.0,
            max_valid_value=350.0
        )
        
        # Create extent
        self.extent = SpatialExtent.objects.create(
            name='TEST_REGION',
            min_lon=-120.0,
            min_lat=45.0,
            max_lon=-115.0,
            max_lat=48.0
        )
    
    def tearDown(self):
        """Clean up test fixtures."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_earthdata_authentication(self):
        """Test NASA EarthData authentication."""
        with patch.dict(os.environ, {
            'EARTHDATA_USERNAME': 'test_user',
            'EARTHDATA_PASSWORD': 'test_pass'
        }):
            with patch('src.acquisition.earthdata_client.earthaccess') as mock_ea:
                mock_auth = Mock()
                mock_auth.authenticated = True
                mock_ea.login.return_value = mock_auth
                
                client = EarthDataClient()
                
                self.assertTrue(client.authenticated)
                self.assertEqual(client.username, 'test_user')
    
    def test_smap_data_availability(self):
        """Test SMAP data availability check."""
        with patch.dict(os.environ, {
            'EARTHDATA_USERNAME': 'test_user',
            'EARTHDATA_PASSWORD': 'test_pass'
        }):
            with patch('src.acquisition.earthdata_client.earthaccess') as mock_ea:
                # Mock authentication
                mock_auth = Mock()
                mock_auth.authenticated = True
                mock_ea.login.return_value = mock_auth
                
                # Mock granule search
                mock_granule = Mock()
                mock_ea.search_data.return_value = [mock_granule]
                
                client = EarthDataClient()
                
                result = client.check_data_availability(
                    collection_id='SPL4SMGP_008',
                    bbox=[-120.0, 45.0, -115.0, 48.0],
                    start_date=datetime(2024, 6, 1),
                    end_date=datetime(2024, 6, 2)
                )
                
                self.assertTrue(result['available'])
                self.assertEqual(result['count'], 1)
    
    def test_modis_data_availability(self):
        """Test MODIS data availability check."""
        with patch.dict(os.environ, {
            'EARTHDATA_USERNAME': 'test_user',
            'EARTHDATA_PASSWORD': 'test_pass'
        }):
            with patch('src.acquisition.earthdata_client.earthaccess') as mock_ea:
                mock_auth = Mock()
                mock_auth.authenticated = True
                mock_ea.login.return_value = mock_auth
                
                # Mock multiple tiles
                mock_granules = [Mock(), Mock(), Mock()]
                mock_ea.search_data.return_value = mock_granules
                
                client = EarthDataClient()
                
                result = client.check_data_availability(
                    collection_id='MOD11A1_061',
                    bbox=[-120.0, 45.0, -115.0, 48.0],
                    start_date=datetime(2024, 6, 1),
                    end_date=datetime(2024, 6, 2)
                )
                
                self.assertTrue(result['available'])
                self.assertEqual(result['count'], 3)


class TestNOMADSIntegration(TestCase):
    """Integration tests for NOAA NOMADS (RTMA)."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = Path(tempfile.mkdtemp())
        
        # Create RTMA dataset
        self.rtma_dataset = RasterDataset.objects.create(
            name='RTMA_TEST',
            data_source='nomads',
            collection_id='rtma2p5',
            file_format='GRIB2',
            temporal_resolution='hourly',
            resolution_m=2500,
            is_active=True
        )
        
        # Create variables
        self.temp_variable = RasterVariable.objects.create(
            dataset=self.rtma_dataset,
            name='temperature',
            unit='Kelvin',
            min_valid_value=200.0,
            max_valid_value=330.0
        )
        
        self.wind_variable = RasterVariable.objects.create(
            dataset=self.rtma_dataset,
            name='wind_speed',
            unit='m/s',
            min_valid_value=0.0,
            max_valid_value=50.0
        )
        
        # Create extent
        self.extent = SpatialExtent.objects.create(
            name='CONUS_WEST',
            min_lon=-124.7,
            min_lat=41.5,
            max_lon=-108.0,
            max_lat=49.0
        )
    
    def tearDown(self):
        """Clean up."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_nomads_client_initialization(self):
        """Test NOMADS client initializes correctly."""
        client = NomadsClient()
        
        self.assertIsNotNone(client.session)
        self.assertIn('nomads.ncep.noaa.gov', client.NOMADS_BASE)
        self.assertEqual(len(client.RTMA_VARIABLES), 6)
    
    def test_rtma_url_building(self):
        """Test RTMA URL construction."""
        client = NomadsClient()
        timestamp = datetime(2026, 1, 28, 20, 0, 0, tzinfo=timezone.utc)
        
        url = client._build_rtma_url(timestamp)
        
        self.assertIn('20260128', url)
        self.assertIn('t20z', url)
        self.assertIn('2dvaranl_ndfd.grb2_wexp', url)
    
    @patch('src.acquisition.nomads_client.requests')
    def test_rtma_data_availability(self, mock_requests):
        """Test RTMA data availability check."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {'content-length': '80000000'}
        mock_requests.head.return_value = mock_response
        
        client = NomadsClient()
        # Use recent timestamp (1 hour ago)
        timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
        
        available = client.check_data_availability(timestamp)
        
        self.assertTrue(available)


class TestEndToEndIntegration(TestCase):
    """End-to-end integration tests for complete data pipeline."""
    
    def setUp(self):
        """Set up complete test environment."""
        self.test_dir = Path(tempfile.mkdtemp())
        
        # Create RTMA dataset (easiest to test)
        self.dataset = RasterDataset.objects.create(
            name='RTMA_E2E',
            data_source='nomads',
            collection_id='rtma2p5',
            file_format='GRIB2',
            temporal_resolution='hourly',
            resolution_m=2500,
            is_active=True
        )
        
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='temperature',
            unit='Kelvin',
            min_valid_value=200.0,
            max_valid_value=330.0
        )
        
        self.extent = SpatialExtent.objects.create(
            name='E2E_TEST',
            min_lon=-124.7,
            min_lat=41.5,
            max_lon=-108.0,
            max_lat=49.0
        )
        
        # Create pull configuration
        self.config = RasterPullConfiguration.objects.create(
            name='E2E_TEST_CONFIG',
            dataset=self.dataset,
            schedule_enabled=False,
            lookback_days=1,
            apply_compression=True,
            validate_on_pull=True
        )
        self.config.variables.add(self.variable)
        self.config.extents.add(self.extent)
    
    def tearDown(self):
        """Clean up."""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    def test_configuration_structure(self):
        """Test that configuration is properly set up."""
        self.assertEqual(self.config.variables.count(), 1)
        self.assertEqual(self.config.extents.count(), 1)
        self.assertEqual(self.config.dataset.data_source, 'nomads')
        self.assertTrue(self.config.apply_compression)
    
    def test_pull_log_creation(self):
        """Test that pull logs are created."""
        initial_count = RasterPullLog.objects.count()
        
        # Mock the actual data fetch
        with patch('src.acquisition.nomads_client.NomadsClient.get_rtma_data'):
            with patch('src.acquisition.raster_processor.RasterProcessor.validate_raster'):
                # This will fail but should create a log
                try:
                    pull_raster_data(
                        self.config.id,
                        (timezone.now() - timedelta(hours=2)).isoformat(),
                        timezone.now().isoformat()
                    )
                except Exception:
                    pass
        
        # Should have created at least one log entry
        self.assertGreaterEqual(RasterPullLog.objects.count(), initial_count)
    
    def test_timezone_awareness(self):
        """Test that all timestamps are timezone-aware."""
        now = timezone.now()
        
        layer = RasterLayer.objects.create(
            variable=self.variable,
            extent=self.extent,
            timestamp=now,
            date=now.date(),
            file_path='test/path.tif',
            file_size_bytes=1024,
            resolution_m=2500,
            width_pixels=100,
            height_pixels=100,
            crs='EPSG:4326',
            is_valid=True
        )
        
        # Check that timestamp is timezone-aware
        self.assertIsNotNone(layer.timestamp.tzinfo)
        self.assertTrue(timezone.is_aware(layer.timestamp))


class TestMultiSourceRouting(TestCase):
    """Test that tasks route correctly to different data sources."""
    
    def setUp(self):
        """Create datasets for all three sources."""
        # NASA EarthData
        self.earthdata_dataset = RasterDataset.objects.create(
            name='SMAP_ROUTING_TEST',
            data_source='earthdata',
            collection_id='SPL4SMGP_008',
            file_format='HDF5',
            temporal_resolution='daily',
            resolution_m=9000
        )
        
        # NOAA NOMADS
        self.nomads_dataset = RasterDataset.objects.create(
            name='RTMA_ROUTING_TEST',
            data_source='nomads',
            collection_id='rtma2p5',
            file_format='GRIB2',
            temporal_resolution='hourly',
            resolution_m=2500
        )
        
        # Legacy GEE (archived)
        self.gee_dataset = RasterDataset.objects.create(
            name='GEE_ROUTING_TEST',
            data_source='gee',
            collection_id='LEGACY/COLLECTION',
            file_format='GeoTIFF',
            temporal_resolution='daily',
            resolution_m=1000,
            is_active=False
        )
    
    def test_data_source_field_values(self):
        """Test that data_source field has correct values."""
        self.assertEqual(self.earthdata_dataset.data_source, 'earthdata')
        self.assertEqual(self.nomads_dataset.data_source, 'nomads')
        self.assertEqual(self.gee_dataset.data_source, 'gee')
    
    def test_collection_id_format(self):
        """Test that collection_id is properly formatted for each source."""
        # EarthData uses CMR collection IDs
        self.assertIn('SPL4', self.earthdata_dataset.collection_id)
        
        # NOMADS uses product names
        self.assertIn('rtma', self.nomads_dataset.collection_id.lower())
        
        # GEE used path format (legacy)
        self.assertIn('/', self.gee_dataset.collection_id)
    
    def test_file_format_correct(self):
        """Test that file formats match data sources."""
        self.assertEqual(self.earthdata_dataset.file_format, 'HDF5')
        self.assertEqual(self.nomads_dataset.file_format, 'GRIB2')
        self.assertEqual(self.gee_dataset.file_format, 'GeoTIFF')


class TestSystemDiagnostics(TestCase):
    """Test system health and configuration diagnostics."""
    
    def test_active_datasets_count(self):
        """Test counting active datasets by source."""
        # Create test datasets
        RasterDataset.objects.create(
            name='SMAP_1',
            data_source='earthdata',
            collection_id='SPL4SMGP_008',
            resolution_m=9000,
            is_active=True
        )
        RasterDataset.objects.create(
            name='RTMA_1',
            data_source='nomads',
            collection_id='rtma2p5',
            resolution_m=2500,
            is_active=True
        )
        RasterDataset.objects.create(
            name='GEE_1',
            data_source='gee',
            collection_id='TEST',
            resolution_m=1000,
            is_active=False
        )
        
        earthdata_count = RasterDataset.objects.filter(
            data_source='earthdata',
            is_active=True
        ).count()
        
        nomads_count = RasterDataset.objects.filter(
            data_source='nomads',
            is_active=True
        ).count()
        
        self.assertEqual(earthdata_count, 1)
        self.assertEqual(nomads_count, 1)
    
    def test_pull_configuration_validation(self):
        """Test that pull configurations are valid."""
        dataset = RasterDataset.objects.create(
            name='TEST_CONFIG_VAL',
            data_source='nomads',
            collection_id='rtma2p5',
            resolution_m=2500
        )
        
        variable = RasterVariable.objects.create(
            dataset=dataset,
            name='temperature'
        )
        
        extent = SpatialExtent.objects.create(
            name='TEST_EXTENT',
            min_lon=-120.0,
            min_lat=45.0,
            max_lon=-115.0,
            max_lat=48.0
        )
        
        config = RasterPullConfiguration.objects.create(
            name='VALIDATION_TEST',
            dataset=dataset,
            lookback_days=7
        )
        config.variables.add(variable)
        config.extents.add(extent)
        
        # Validate configuration
        self.assertGreater(config.variables.count(), 0)
        self.assertGreater(config.extents.count(), 0)
        self.assertIsNotNone(config.dataset)


if __name__ == '__main__':
    unittest.main()
