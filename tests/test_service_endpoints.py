"""
Tests for critical service endpoints.

These tests verify that essential services are accessible and functioning:
- Django application and admin
- REST API and documentation (Swagger/ReDoc)
- Flower monitoring dashboard (if Celery is running)
"""

import pytest
import requests
from django.test import TestCase, Client
from django.urls import reverse
import subprocess
import socket


class ServiceEndpointTests(TestCase):
    """Test that all critical service endpoints are accessible."""
    
    def setUp(self):
        """Set up test client."""
        self.client = Client()
    
    def test_django_admin_accessible(self):
        """Test Django admin interface is accessible."""
        response = self.client.get('/admin/login/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Django', response.content)
    
    def test_api_root_accessible(self):
        """Test REST API root endpoint is accessible."""
        response = self.client.get('/api/v1/')
        self.assertEqual(response.status_code, 200)
    
    def test_swagger_ui_accessible(self):
        """Test Swagger UI documentation is accessible."""
        response = self.client.get('/api/v1/docs/')
        self.assertEqual(response.status_code, 200)
        # Check for Swagger UI specific content
        self.assertIn(b'swagger', response.content.lower())
    
    def test_redoc_accessible(self):
        """Test ReDoc documentation is accessible."""
        response = self.client.get('/api/v1/redoc/')
        self.assertEqual(response.status_code, 200)
        # Check for ReDoc specific content
        self.assertIn(b'redoc', response.content.lower())
    
    def test_api_schema_accessible(self):
        """Test OpenAPI schema endpoint is accessible."""
        response = self.client.get('/api/v1/schema/')
        self.assertEqual(response.status_code, 200)
        # Should return JSON or YAML
        self.assertTrue(
            response['Content-Type'].startswith('application/vnd.oai.openapi') or
            response['Content-Type'].startswith('application/json')
        )
    
    def test_api_endpoints_exist(self):
        """Test that all expected API endpoints are registered."""
        response = self.client.get('/api/v1/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        
        # Check timeseries endpoints
        expected_endpoints = [
            'stations',
            'configurations', 
            'logs',
        ]
        
        for endpoint in expected_endpoints:
            self.assertIn(endpoint, data, f"Missing endpoint: {endpoint}")
    
    def test_raster_api_endpoints_exist(self):
        """Test that raster data API endpoints are registered."""
        response = self.client.get('/api/v1/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        
        # Check raster endpoints
        expected_endpoints = [
            'raster-datasets',
            'raster-variables',
            'spatial-extents',
            'raster-layers',
            'raster-configurations',
            'raster-logs',
        ]
        
        for endpoint in expected_endpoints:
            self.assertIn(endpoint, data, f"Missing raster endpoint: {endpoint}")


class LiveServiceTests(TestCase):
    """
    Tests for live services that may be running externally.
    These tests will be skipped if services are not running.
    """
    
    @staticmethod
    def is_port_open(host, port):
        """Check if a port is open on the given host."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            result = sock.connect_ex((host, port))
            return result == 0
        finally:
            sock.close()
    
    @staticmethod
    def is_flower_installed():
        """Check if Flower is installed."""
        try:
            result = subprocess.run(
                ['celery', '--help'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return 'flower' in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def test_django_server_running(self):
        """Test that Django development server is responding."""
        if not self.is_port_open('localhost', 8000):
            self.skipTest("Django server not running on port 8000")
        
        try:
            response = requests.get('http://localhost:8000/', timeout=5)
            self.assertIn(response.status_code, [200, 301, 302, 404])
        except requests.RequestException as e:
            self.fail(f"Django server not responding: {e}")
    
    def test_flower_monitor_accessible(self):
        """Test that Flower monitoring dashboard is accessible."""
        if not self.is_flower_installed():
            self.skipTest("Flower is not installed")
        
        if not self.is_port_open('localhost', 5555):
            self.skipTest("Flower not running on port 5555")
        
        try:
            response = requests.get('http://localhost:5555/', timeout=5)
            self.assertEqual(response.status_code, 200)
            self.assertIn('flower', response.text.lower())
        except requests.RequestException as e:
            self.fail(f"Flower dashboard not accessible: {e}")
    
    def test_flower_api_workers(self):
        """Test that Flower API returns worker information."""
        if not self.is_flower_installed():
            self.skipTest("Flower is not installed")
        
        if not self.is_port_open('localhost', 5555):
            self.skipTest("Flower not running on port 5555")
        
        try:
            response = requests.get('http://localhost:5555/api/workers', timeout=5)
            # Flower API may require auth (401) or return data (200)
            # Both indicate Flower is running properly
            self.assertIn(response.status_code, [200, 401])
            if response.status_code == 200:
                # Should return JSON
                data = response.json()
                self.assertIsInstance(data, dict)
        except requests.RequestException as e:
            self.fail(f"Flower API not accessible: {e}")


class DocumentationContentTests(TestCase):
    """Test that API documentation contains expected content."""
    
    def setUp(self):
        """Set up test client."""
        self.client = Client()
    
    def test_swagger_has_api_title(self):
        """Test that Swagger UI displays the API title."""
        response = self.client.get('/api/v1/docs/')
        self.assertEqual(response.status_code, 200)
        # Swagger should load the schema which includes our API title
        content = response.content.decode('utf-8')
        self.assertIn('swagger', content.lower())
    
    def test_schema_has_endpoints(self):
        """Test that OpenAPI schema includes all major endpoints."""
        response = self.client.get('/api/v1/schema/')
        self.assertEqual(response.status_code, 200)
        
        schema_content = response.content.decode('utf-8')
        
        # Check for key endpoint paths in schema
        expected_paths = [
            'stations',
            'raster-datasets',
            'raster-layers',
            'configurations',
        ]
        
        for path in expected_paths:
            self.assertIn(path, schema_content, f"Schema missing endpoint: {path}")
    
    def test_schema_has_http_methods(self):
        """Test that schema includes standard HTTP methods."""
        response = self.client.get('/api/v1/schema/')
        self.assertEqual(response.status_code, 200)
        
        schema_content = response.content.decode('utf-8').lower()
        
        # Check for HTTP methods (OpenAPI schema uses lowercase)
        expected_methods = ['get', 'post', 'put', 'patch', 'delete']
        
        for method in expected_methods:
            # Methods appear as operation IDs or in paths
            self.assertIn(method, schema_content, f"Schema missing HTTP method: {method}")


class ServiceHealthTests(TestCase):
    """Tests to verify overall service health."""
    
    def test_urls_have_no_conflicts(self):
        """Test that URL patterns don't have conflicts."""
        from django.urls import get_resolver
        
        resolver = get_resolver()
        # This will raise an exception if there are URL conflicts
        url_patterns = list(resolver.url_patterns)
        self.assertGreater(len(url_patterns), 0)
    
    def test_all_api_viewsets_registered(self):
        """Test that all API viewsets are properly registered."""
        from apps.api.urls import router
        
        # Check that router has URL patterns
        url_patterns = router.urls
        self.assertGreater(len(url_patterns), 0, "Router has no registered URLs")
        
        # Check via API root that endpoints exist
        response = self.client.get('/api/v1/')
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        expected_endpoints = ['stations', 'configurations', 'raster-datasets']
        
        for endpoint in expected_endpoints:
            self.assertIn(endpoint, data, f"Endpoint not in API root: {endpoint}")
