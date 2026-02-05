"""
Comprehensive tests for Raster API endpoints.

Tests include raster datasets, variables, layers, configurations, and actions.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from datetime import datetime, timedelta
from django.utils import timezone

from apps.streamflow.models import (
    RasterDataset, RasterVariable, SpatialExtent, 
    RasterLayer, RasterPullConfiguration, RasterPullLog
)


class RasterDatasetAPITest(TestCase):
    """Test raster dataset endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        # Create spatial extent
        self.extent = SpatialExtent.objects.create(
            name='Western US',
            min_longitude=-125.0,
            max_longitude=-102.0,
            min_latitude=31.0,
            max_latitude=49.0
        )
        
        # Create raster dataset
        self.dataset = RasterDataset.objects.create(
            name='Test Snow Dataset',
            source='NOAA_SNODAS',
            spatial_extent=self.extent,
            description='Test dataset for snow data',
            temporal_resolution='daily',
            spatial_resolution=1000.0
        )
    
    def test_list_raster_datasets(self):
        """Test listing raster datasets."""
        url = reverse('api:rasterdataset-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_raster_dataset(self):
        """Test retrieving single raster dataset."""
        url = reverse('api:rasterdataset-detail', args=[self.dataset.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Test Snow Dataset')
        self.assertEqual(response.data['source'], 'NOAA_SNODAS')
    
    def test_raster_dataset_includes_extent(self):
        """Test that dataset includes spatial extent info."""
        url = reverse('api:rasterdataset-detail', args=[self.dataset.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('spatial_extent', response.data)
        self.assertEqual(response.data['spatial_extent']['name'], 'Western US')


class RasterVariableAPITest(TestCase):
    """Test raster variable endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.extent = SpatialExtent.objects.create(
            name='Test Extent',
            min_longitude=-120.0,
            max_longitude=-110.0,
            min_latitude=35.0,
            max_latitude=45.0
        )
        
        self.dataset = RasterDataset.objects.create(
            name='Test Dataset',
            source='NOAA_SNODAS',
            spatial_extent=self.extent,
            temporal_resolution='daily',
            spatial_resolution=1000.0
        )
        
        # Create raster variables
        self.variable1 = RasterVariable.objects.create(
            dataset=self.dataset,
            name='snow_depth',
            description='Snow depth in meters',
            unit='meters'
        )
        
        self.variable2 = RasterVariable.objects.create(
            dataset=self.dataset,
            name='snow_water_equivalent',
            description='SWE in mm',
            unit='mm'
        )
    
    def test_list_raster_variables(self):
        """Test listing raster variables."""
        url = reverse('api:rastervariable-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 2)
    
    def test_filter_variables_by_dataset(self):
        """Test filtering variables by dataset."""
        url = reverse('api:rastervariable-list')
        response = self.client.get(url, {'dataset': self.dataset.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
        
        # Check both variables are for this dataset
        for variable in response.data['results']:
            self.assertEqual(variable['dataset'], self.dataset.id)
    
    def test_variable_includes_metadata(self):
        """Test that variable includes name, description, and unit."""
        url = reverse('api:rastervariable-detail', args=[self.variable1.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'snow_depth')
        self.assertEqual(response.data['description'], 'Snow depth in meters')
        self.assertEqual(response.data['unit'], 'meters')


class RasterLayerAPITest(TestCase):
    """Test raster layer endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.extent = SpatialExtent.objects.create(
            name='Test Extent',
            min_longitude=-120.0,
            max_longitude=-110.0,
            min_latitude=35.0,
            max_latitude=45.0
        )
        
        self.dataset = RasterDataset.objects.create(
            name='Test Dataset',
            source='NOAA_SNODAS',
            spatial_extent=self.extent,
            temporal_resolution='daily',
            spatial_resolution=1000.0
        )
        
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='snow_depth',
            description='Snow depth',
            unit='meters'
        )
        
        # Create raster layers for different dates
        base_date = timezone.now().date()
        for i in range(10):
            RasterLayer.objects.create(
                variable=self.variable,
                date=base_date - timedelta(days=i),
                file_path=f'/data/snow_{i}.tif',
                file_size=1024 * 1024 * i
            )
    
    def test_list_raster_layers(self):
        """Test listing raster layers."""
        url = reverse('api:rasterlayer-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 10)
    
    def test_filter_layers_by_variable(self):
        """Test filtering layers by variable."""
        url = reverse('api:rasterlayer-list')
        response = self.client.get(url, {'variable': self.variable.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 10)
    
    def test_filter_layers_by_date(self):
        """Test filtering layers by date."""
        url = reverse('api:rasterlayer-list')
        target_date = (timezone.now() - timedelta(days=5)).date().isoformat()
        
        response = self.client.get(url, {'date': target_date})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have exactly 1 layer for this date
        self.assertEqual(len(response.data['results']), 1)
    
    def test_filter_layers_by_date_range(self):
        """Test filtering layers by date range."""
        url = reverse('api:rasterlayer-list')
        start_date = (timezone.now() - timedelta(days=7)).date().isoformat()
        end_date = (timezone.now() - timedelta(days=2)).date().isoformat()
        
        response = self.client.get(url, {
            'start_date': start_date,
            'end_date': end_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have 6 layers (days 2-7)
        self.assertEqual(len(response.data['results']), 6)
    
    def test_layer_includes_file_info(self):
        """Test that layer includes file path and size."""
        url = reverse('api:rasterlayer-list')
        response = self.client.get(url, {'variable': self.variable.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        layer = response.data['results'][0]
        
        self.assertIn('file_path', layer)
        self.assertIn('file_size', layer)
        self.assertIn('date', layer)
    
    def test_layers_ordered_by_date(self):
        """Test that layers are ordered by date descending."""
        url = reverse('api:rasterlayer-list')
        response = self.client.get(url, {'variable': self.variable.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        dates = [layer['date'] for layer in response.data['results']]
        self.assertEqual(dates, sorted(dates, reverse=True))


class RasterPullConfigurationAPITest(TestCase):
    """Test raster pull configuration endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.extent = SpatialExtent.objects.create(
            name='Test Extent',
            min_longitude=-120.0,
            max_longitude=-110.0,
            min_latitude=35.0,
            max_latitude=45.0
        )
        
        self.dataset = RasterDataset.objects.create(
            name='Test Dataset',
            source='NOAA_SNODAS',
            spatial_extent=self.extent,
            temporal_resolution='daily',
            spatial_resolution=1000.0
        )
        
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='snow_depth',
            description='Snow depth',
            unit='meters'
        )
        
        self.config = RasterPullConfiguration.objects.create(
            dataset=self.dataset,
            variable=self.variable,
            is_active=True,
            schedule_cron='0 6 * * *',
            retry_attempts=3,
            retry_delay_seconds=300
        )
    
    def test_list_raster_configurations(self):
        """Test listing raster pull configurations."""
        url = reverse('api:rasterpullconfiguration-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_configuration(self):
        """Test retrieving single configuration."""
        url = reverse('api:rasterpullconfiguration-detail', args=[self.config.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['is_active'], True)
        self.assertEqual(response.data['schedule_cron'], '0 6 * * *')
    
    def test_filter_configurations_by_dataset(self):
        """Test filtering configurations by dataset."""
        url = reverse('api:rasterpullconfiguration-list')
        response = self.client.get(url, {'dataset': self.dataset.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_filter_active_configurations(self):
        """Test filtering for active configurations."""
        url = reverse('api:rasterpullconfiguration-list')
        response = self.client.get(url, {'is_active': 'true'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # All results should be active
        for config in response.data['results']:
            self.assertTrue(config['is_active'])


class RasterPullLogAPITest(TestCase):
    """Test raster pull log endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.extent = SpatialExtent.objects.create(
            name='Test Extent',
            min_longitude=-120.0,
            max_longitude=-110.0,
            min_latitude=35.0,
            max_latitude=45.0
        )
        
        self.dataset = RasterDataset.objects.create(
            name='Test Dataset',
            source='NOAA_SNODAS',
            spatial_extent=self.extent,
            temporal_resolution='daily',
            spatial_resolution=1000.0
        )
        
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='snow_depth',
            description='Snow depth',
            unit='meters'
        )
        
        self.config = RasterPullConfiguration.objects.create(
            dataset=self.dataset,
            variable=self.variable,
            is_active=True,
            schedule_cron='0 6 * * *'
        )
        
        # Create logs with different statuses
        RasterPullLog.objects.create(
            configuration=self.config,
            status='success',
            records_pulled=100,
            started_at=timezone.now() - timedelta(hours=2),
            completed_at=timezone.now() - timedelta(hours=1)
        )
        
        RasterPullLog.objects.create(
            configuration=self.config,
            status='error',
            error_message='Connection timeout',
            started_at=timezone.now() - timedelta(hours=5),
            completed_at=timezone.now() - timedelta(hours=4)
        )
    
    def test_list_raster_logs(self):
        """Test listing raster pull logs."""
        url = reverse('api:rasterpulllog-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 2)
    
    def test_filter_logs_by_configuration(self):
        """Test filtering logs by configuration."""
        url = reverse('api:rasterpulllog-list')
        response = self.client.get(url, {'configuration': self.config.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)
    
    def test_filter_logs_by_status(self):
        """Test filtering logs by status."""
        url = reverse('api:rasterpulllog-list')
        response = self.client.get(url, {'status': 'success'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
        
        # All results should be success
        for log in response.data['results']:
            self.assertEqual(log['status'], 'success')
    
    def test_log_includes_timing_info(self):
        """Test that log includes started_at and completed_at."""
        url = reverse('api:rasterpulllog-list')
        response = self.client.get(url, {'configuration': self.config.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        log = response.data['results'][0]
        
        self.assertIn('started_at', log)
        self.assertIn('completed_at', log)
    
    def test_error_log_includes_message(self):
        """Test that error logs include error message."""
        url = reverse('api:rasterpulllog-list')
        response = self.client.get(url, {
            'configuration': self.config.id,
            'status': 'error'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
        
        error_log = response.data['results'][0]
        self.assertIn('error_message', error_log)
        self.assertIsNotNone(error_log['error_message'])


class SpatialExtentAPITest(TestCase):
    """Test spatial extent endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.extent = SpatialExtent.objects.create(
            name='Western US',
            min_longitude=-125.0,
            max_longitude=-102.0,
            min_latitude=31.0,
            max_latitude=49.0
        )
    
    def test_list_spatial_extents(self):
        """Test listing spatial extents."""
        url = reverse('api:spatialextent-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)
    
    def test_retrieve_spatial_extent(self):
        """Test retrieving single spatial extent."""
        url = reverse('api:spatialextent-detail', args=[self.extent.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Western US')
        self.assertEqual(response.data['min_longitude'], -125.0)
        self.assertEqual(response.data['max_longitude'], -102.0)
    
    def test_extent_includes_bbox(self):
        """Test that extent includes all bounding box coordinates."""
        url = reverse('api:spatialextent-detail', args=[self.extent.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('min_longitude', response.data)
        self.assertIn('max_longitude', response.data)
        self.assertIn('min_latitude', response.data)
        self.assertIn('max_latitude', response.data)


class RasterErrorHandlingTest(TestCase):
    """Test error handling for raster endpoints."""
    
    def setUp(self):
        """Set up test client."""
        self.client = APIClient()
    
    def test_retrieve_nonexistent_dataset(self):
        """Test retrieving dataset that doesn't exist."""
        url = reverse('api:rasterdataset-detail', args=[99999])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_retrieve_nonexistent_variable(self):
        """Test retrieving variable that doesn't exist."""
        url = reverse('api:rastervariable-detail', args=[99999])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_retrieve_nonexistent_layer(self):
        """Test retrieving layer that doesn't exist."""
        url = reverse('api:rasterlayer-detail', args=[99999])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_filter_invalid_date_format(self):
        """Test filtering with invalid date format."""
        url = reverse('api:rasterlayer-list')
        response = self.client.get(url, {'date': 'invalid-date'})
        
        # Should return 400 Bad Request for invalid date
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class RasterPaginationTest(TestCase):
    """Test pagination for raster endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.extent = SpatialExtent.objects.create(
            name='Test Extent',
            min_longitude=-120.0,
            max_longitude=-110.0,
            min_latitude=35.0,
            max_latitude=45.0
        )
        
        self.dataset = RasterDataset.objects.create(
            name='Test Dataset',
            source='NOAA_SNODAS',
            spatial_extent=self.extent,
            temporal_resolution='daily',
            spatial_resolution=1000.0
        )
        
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='snow_depth',
            description='Snow depth',
            unit='meters'
        )
        
        # Create 60 layers
        base_date = timezone.now().date()
        for i in range(60):
            RasterLayer.objects.create(
                variable=self.variable,
                date=base_date - timedelta(days=i),
                file_path=f'/data/snow_{i}.tif',
                file_size=1024 * i
            )
    
    def test_raster_layer_pagination(self):
        """Test that raster layer list is paginated."""
        url = reverse('api:rasterlayer-list')
        response = self.client.get(url, {'variable': self.variable.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)
        
        # Should have 60 total, but paginated results
        self.assertEqual(response.data['count'], 60)
        self.assertLess(len(response.data['results']), 60)
    
    def test_pagination_next_page(self):
        """Test navigating to next page."""
        url = reverse('api:rasterlayer-list')
        response = self.client.get(url, {'variable': self.variable.id})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data['next'])
        
        # Get second page
        next_response = self.client.get(response.data['next'])
        self.assertEqual(next_response.status_code, status.HTTP_200_OK)
        
        # Should have different results
        first_page_ids = [layer['id'] for layer in response.data['results']]
        second_page_ids = [layer['id'] for layer in next_response.data['results']]
        self.assertNotEqual(first_page_ids, second_page_ids)
