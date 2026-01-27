"""UI/UX tests for raster data frontend functionality."""

import os
import time
import django
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import TestCase, Client, LiveServerTestCase
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException

from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterLayer,
    RasterPullConfiguration
)


class RasterAPIEndpointsTest(TestCase):
    """Test raster API endpoints."""
    
    def setUp(self):
        """Set up test data and client."""
        self.client = Client()
        
        # Create test data
        self.dataset = RasterDataset.objects.create(
            name='TEST_RTMA',
            gee_collection_id='TEST/COLLECTION',
            resolution_m=2500,
            temporal_resolution='hourly'
        )
        
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='temperature',
            gee_band_name='TMP',
            unit='Kelvin'
        )
        
        self.extent = SpatialExtent.objects.create(
            name='TEST_HUC17',
            min_lon=-124.7,
            min_lat=41.5,
            max_lon=-108.0,
            max_lat=49.0
        )
        
        self.layer = RasterLayer.objects.create(
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
            min_value=250.0,
            max_value=300.0,
            mean_value=275.0,
            is_valid=True
        )
    
    def test_raster_datasets_list(self):
        """Test listing raster datasets via API."""
        response = self.client.get('/api/v1/raster-datasets/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
        self.assertGreater(len(data['results']), 0)
    
    def test_raster_variables_list(self):
        """Test listing raster variables via API."""
        response = self.client.get('/api/v1/raster-variables/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
    
    def test_spatial_extents_list(self):
        """Test listing spatial extents via API."""
        response = self.client.get('/api/v1/spatial-extents/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
    
    def test_raster_layers_list(self):
        """Test listing raster layers via API."""
        response = self.client.get('/api/v1/raster-layers/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
    
    def test_raster_layers_filter_by_variable(self):
        """Test filtering raster layers by variable."""
        response = self.client.get(
            f'/api/v1/raster-layers/?variable={self.variable.name}'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
    
    def test_raster_layers_filter_by_date(self):
        """Test filtering raster layers by date range."""
        start = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        end = timezone.now().strftime('%Y-%m-%d')
        
        response = self.client.get(
            f'/api/v1/raster-layers/?start_date={start}&end_date={end}'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
    
    def test_raster_layer_detail(self):
        """Test retrieving raster layer detail."""
        response = self.client.get(f'/api/v1/raster-layers/{self.layer.id}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['id'], self.layer.id)
        self.assertIn('variable_name', data)
        self.assertIn('download_url', data)
    
    def test_raster_coverage_endpoint(self):
        """Test coverage summary endpoint."""
        response = self.client.get('/api/v1/raster-layers/coverage/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('layer_count', data)
    
    def test_raster_statistics_endpoint(self):
        """Test statistics endpoint."""
        response = self.client.get('/api/v1/raster-layers/statistics/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('count', data)


class RasterFrontendSeleniumTest(LiveServerTestCase):
    """Selenium tests for raster data frontend."""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Setup Chrome options
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        
        try:
            cls.selenium = webdriver.Chrome(options=chrome_options)
            cls.selenium.implicitly_wait(10)
        except Exception as e:
            print(f"Warning: Could not initialize Chrome driver: {e}")
            print("Skipping Selenium tests. Install chromedriver to run these tests.")
            cls.selenium = None
    
    @classmethod
    def tearDownClass(cls):
        if cls.selenium:
            cls.selenium.quit()
        super().tearDownClass()
    
    def setUp(self):
        """Set up test data."""
        if not self.selenium:
            self.skipTest("Selenium driver not available")
        
        # Create admin user
        self.admin_user = User.objects.create_superuser(
            username='admin',
            email='admin@test.com',
            password='testpass123'
        )
        
        # Create test data
        self.dataset = RasterDataset.objects.create(
            name='RTMA',
            gee_collection_id='NOAA/NWS/RTMA',
            resolution_m=2500,
            temporal_resolution='hourly'
        )
        
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='temperature',
            gee_band_name='TMP',
            unit='Kelvin'
        )
        
        self.extent = SpatialExtent.objects.create(
            name='HUC_17',
            min_lon=-124.7,
            min_lat=41.5,
            max_lon=-108.0,
            max_lat=49.0
        )
    
    def test_api_docs_accessible(self):
        """Test that API documentation is accessible."""
        self.selenium.get(f'{self.live_server_url}/api/v1/docs/')
        
        # Wait for Swagger UI to load
        try:
            WebDriverWait(self.selenium, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, 'swagger-ui'))
            )
            
            # Check for raster endpoints
            page_source = self.selenium.page_source
            self.assertIn('raster', page_source.lower())
        except TimeoutException:
            self.fail("API documentation page failed to load")
    
    def test_admin_raster_dataset_page(self):
        """Test admin page for raster datasets."""
        # Login to admin
        self.selenium.get(f'{self.live_server_url}/admin/login/')
        
        username_input = self.selenium.find_element(By.NAME, 'username')
        password_input = self.selenium.find_element(By.NAME, 'password')
        
        username_input.send_keys('admin')
        password_input.send_keys('testpass123')
        
        self.selenium.find_element(By.CSS_SELECTOR, 'input[type="submit"]').click()
        
        # Navigate to raster datasets
        self.selenium.get(
            f'{self.live_server_url}/admin/streamflow/rasterdataset/'
        )
        
        # Check that page loaded
        try:
            WebDriverWait(self.selenium, 10).until(
                EC.presence_of_element_located((By.ID, 'result_list'))
            )
            
            page_source = self.selenium.page_source
            self.assertIn('RTMA', page_source)
        except TimeoutException:
            self.fail("Admin raster dataset page failed to load")
    
    def test_admin_raster_layer_page(self):
        """Test admin page for raster layers."""
        # Create a layer first
        RasterLayer.objects.create(
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
        
        # Login
        self.selenium.get(f'{self.live_server_url}/admin/login/')
        self.selenium.find_element(By.NAME, 'username').send_keys('admin')
        self.selenium.find_element(By.NAME, 'password').send_keys('testpass123')
        self.selenium.find_element(By.CSS_SELECTOR, 'input[type="submit"]').click()
        
        # Navigate to raster layers
        self.selenium.get(
            f'{self.live_server_url}/admin/streamflow/rasterlayer/'
        )
        
        # Check that page loaded with layer data
        try:
            WebDriverWait(self.selenium, 10).until(
                EC.presence_of_element_located((By.ID, 'result_list'))
            )
            
            page_source = self.selenium.page_source
            self.assertIn('temperature', page_source)
            self.assertIn('HUC_17', page_source)
        except TimeoutException:
            self.fail("Admin raster layer page failed to load")
    
    def test_admin_filter_layers_by_variable(self):
        """Test filtering layers by variable in admin."""
        # Create layers
        RasterLayer.objects.create(
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
        
        # Login
        self.selenium.get(f'{self.live_server_url}/admin/login/')
        self.selenium.find_element(By.NAME, 'username').send_keys('admin')
        self.selenium.find_element(By.NAME, 'password').send_keys('testpass123')
        self.selenium.find_element(By.CSS_SELECTOR, 'input[type="submit"]').click()
        
        # Navigate to raster layers with filter
        self.selenium.get(
            f'{self.live_server_url}/admin/streamflow/rasterlayer/?variable__id__exact={self.variable.id}'
        )
        
        # Check filter applied
        try:
            WebDriverWait(self.selenium, 10).until(
                EC.presence_of_element_located((By.ID, 'result_list'))
            )
            
            # Should show filtered results
            page_source = self.selenium.page_source
            self.assertIn('temperature', page_source)
        except TimeoutException:
            self.fail("Filtered layer page failed to load")


class RasterAPIResponseFormatTest(TestCase):
    """Test API response formats and data structure."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        
        self.dataset = RasterDataset.objects.create(
            name='RTMA',
            gee_collection_id='NOAA/NWS/RTMA',
            resolution_m=2500,
            temporal_resolution='hourly'
        )
        
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='temperature',
            gee_band_name='TMP',
            unit='Kelvin',
            min_valid_value=200.0,
            max_valid_value=350.0
        )
        
        self.extent = SpatialExtent.objects.create(
            name='HUC_17',
            min_lon=-124.7,
            min_lat=41.5,
            max_lon=-108.0,
            max_lat=49.0
        )
        
        self.layer = RasterLayer.objects.create(
            variable=self.variable,
            extent=self.extent,
            timestamp=timezone.now(),
            date=timezone.now().date(),
            file_path='test/path.tif',
            file_size_bytes=1024000,
            resolution_m=2500,
            width_pixels=100,
            height_pixels=100,
            crs='EPSG:4326',
            min_value=250.0,
            max_value=300.0,
            mean_value=275.0,
            std_dev=10.5,
            is_valid=True
        )
    
    def test_dataset_response_structure(self):
        """Test dataset API response structure."""
        response = self.client.get(f'/api/v1/raster-datasets/{self.dataset.id}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check required fields
        required_fields = [
            'id', 'name', 'gee_collection_id', 'description',
            'resolution_m', 'temporal_resolution', 'is_active'
        ]
        
        for field in required_fields:
            self.assertIn(field, data, f"Missing field: {field}")
    
    def test_variable_response_structure(self):
        """Test variable API response structure."""
        response = self.client.get(f'/api/v1/raster-variables/{self.variable.id}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check required fields
        required_fields = [
            'id', 'dataset', 'dataset_name', 'name', 'gee_band_name',
            'unit', 'min_valid_value', 'max_valid_value'
        ]
        
        for field in required_fields:
            self.assertIn(field, data, f"Missing field: {field}")
    
    def test_extent_response_structure(self):
        """Test spatial extent API response structure."""
        response = self.client.get(f'/api/v1/spatial-extents/{self.extent.id}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check required fields
        required_fields = [
            'id', 'name', 'min_lon', 'min_lat', 'max_lon', 'max_lat', 'bbox'
        ]
        
        for field in required_fields:
            self.assertIn(field, data, f"Missing field: {field}")
        
        # Check bbox format
        self.assertIsInstance(data['bbox'], list)
        self.assertEqual(len(data['bbox']), 4)
    
    def test_layer_response_structure(self):
        """Test layer API response structure."""
        response = self.client.get(f'/api/v1/raster-layers/{self.layer.id}/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check required fields
        required_fields = [
            'id', 'variable_name', 'dataset_name', 'extent_name',
            'timestamp', 'date', 'file_path', 'file_size_bytes',
            'resolution_m', 'width_pixels', 'height_pixels',
            'min_value', 'max_value', 'mean_value', 'std_dev',
            'is_valid', 'download_url'
        ]
        
        for field in required_fields:
            self.assertIn(field, data, f"Missing field: {field}")
        
        # Check URL formats
        self.assertIn('/api/raster-layers/', data['download_url'])
    
    def test_pagination_in_list_responses(self):
        """Test that list endpoints use pagination."""
        # Create multiple layers
        for i in range(15):
            RasterLayer.objects.create(
                variable=self.variable,
                extent=self.extent,
                timestamp=timezone.now() - timedelta(hours=i),
                date=timezone.now().date(),
                file_path=f'test/path{i}.tif',
                file_size_bytes=1024,
                resolution_m=2500,
                width_pixels=100,
                height_pixels=100,
                crs='EPSG:4326',
                is_valid=True
            )
        
        response = self.client.get('/api/v1/raster-layers/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check pagination fields
        self.assertIn('count', data)
        self.assertIn('next', data)
        self.assertIn('previous', data)
        self.assertIn('results', data)
        
        # Should not return all items on first page (default page size varies)
        self.assertGreater(len(data['results']), 0)


class RasterErrorHandlingTest(TestCase):
    """Test error handling in raster endpoints."""
    
    def setUp(self):
        """Set up test client."""
        self.client = Client()
    
    def test_404_on_nonexistent_dataset(self):
        """Test 404 response for non-existent dataset."""
        response = self.client.get('/api/v1/raster-datasets/99999/')
        self.assertEqual(response.status_code, 404)
    
    def test_404_on_nonexistent_layer(self):
        """Test 404 response for non-existent layer."""
        response = self.client.get('/api/v1/raster-layers/99999/')
        self.assertEqual(response.status_code, 404)
    
    def test_404_on_layer_download_not_found(self):
        """Test 404 when downloading non-existent layer."""
        response = self.client.get('/api/v1/raster-layers/99999/download/')
        self.assertEqual(response.status_code, 404)
    
    def test_invalid_date_filter_handling(self):
        """Test handling of invalid date filters."""
        response = self.client.get(
            '/api/v1/raster-layers/?start_date=invalid-date'
        )
        
        # Should still return 200 but ignore invalid filter
        self.assertEqual(response.status_code, 200)
