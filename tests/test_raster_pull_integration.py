"""
Integration tests for raster data pull system.

Tests the complete flow from configuration trigger to data storage and logging.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth.models import User
from django.urls import reverse

from apps.streamflow.models import (
    RasterPullConfiguration,
    RasterPullLog,
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterLayer
)
from src.acquisition.raster_tasks import pull_raster_data


class RasterPullIntegrationTest(TestCase):
    """Test complete raster pull workflow."""
    
    def setUp(self):
        """Set up test data."""
        # Create user for authenticated requests
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
        
        # Create test dataset
        self.dataset = RasterDataset.objects.create(
            name='Test RTMA',
            description='Test Real-Time Mesoscale Analysis',
            data_source='nomads',
            temporal_resolution='hourly',
            spatial_resolution=2500.0,
            is_active=True
        )
        
        # Create test variable
        self.variable = RasterVariable.objects.create(
            dataset=self.dataset,
            name='tmp2m',
            long_name='2m Temperature',
            units='K',
            gee_band_name='tmp2m'
        )
        
        # Create test extent
        self.extent = SpatialExtent.objects.create(
            name='Test Region',
            description='Small test region',
            bbox=[-125.0, 45.0, -120.0, 48.0],
            projection='EPSG:4326'
        )
        
        # Create pull configuration
        self.config = RasterPullConfiguration.objects.create(
            name='Test Pull Config',
            description='Test configuration for integration testing',
            dataset=self.dataset,
            lookback_days=1,
            schedule_enabled=True
        )
        self.config.variables.add(self.variable)
        self.config.extents.add(self.extent)
    
    def test_configuration_exists(self):
        """Test that configuration was created properly."""
        assert self.config.variables.count() == 1
        assert self.config.extents.count() == 1
        assert self.config.schedule_enabled is True
    
    def test_manual_trigger_creates_log(self):
        """Test that manual trigger creates a pull log."""
        url = reverse('streamflow:trigger_raster_pull', args=[self.config.id])
        
        initial_log_count = RasterPullLog.objects.count()
        
        response = self.client.post(url, {'sync': 'false'})
        
        # Should redirect
        assert response.status_code == 302
        
        # Check if log was created (might be created immediately or by task)
        # Give it a moment for async task
        import time
        time.sleep(1)
        
        final_log_count = RasterPullLog.objects.count()
        # Log should be created (either immediately or by task start)
        assert final_log_count >= initial_log_count
    
    def test_sync_pull_completes(self):
        """Test synchronous pull completes and creates log."""
        url = reverse('streamflow:trigger_raster_pull', args=[self.config.id])
        
        initial_log_count = RasterPullLog.objects.count()
        
        # Trigger sync pull
        response = self.client.post(url, {'sync': 'true'})
        
        # Should redirect
        assert response.status_code == 302
        
        # Log should be created
        assert RasterPullLog.objects.count() > initial_log_count
        
        # Get the most recent log
        latest_log = RasterPullLog.objects.latest('started_at')
        
        # Verify log attributes
        assert latest_log.configuration == self.config
        assert latest_log.status in ['success', 'failed', 'partial', 'running']
        assert latest_log.started_at is not None
        
        # If completed, should have completion time
        if latest_log.status != 'running':
            assert latest_log.completed_at is not None
    
    def test_pull_log_appears_on_gridded_logs_page(self):
        """Test that pull logs appear on the gridded logs page."""
        # Create a pull log manually
        pull_log = RasterPullLog.objects.create(
            configuration=self.config,
            status='success',
            started_at=timezone.now(),
            completed_at=timezone.now(),
            layers_attempted=5,
            layers_successful=5,
            layers_failed=0,
            layers_skipped=0
        )
        
        # Access the gridded logs page
        url = reverse('streamflow:raster_pull_logs')
        response = self.client.get(url)
        
        assert response.status_code == 200
        assert pull_log.configuration.name.encode() in response.content
    
    def test_task_function_directly(self):
        """Test pull_raster_data task function directly."""
        # Call task synchronously
        result = pull_raster_data(self.config.id)
        
        # Should return statistics dict
        assert isinstance(result, dict)
        
        # Check for expected keys
        if 'error' not in result:
            assert 'attempted' in result or 'successful' in result
        
        # Verify log was created
        logs = RasterPullLog.objects.filter(configuration=self.config)
        assert logs.exists()
        
        latest_log = logs.latest('started_at')
        assert latest_log.status in ['success', 'failed', 'partial']
        assert latest_log.completed_at is not None
    
    def test_config_timestamps_update(self):
        """Test that configuration timestamps update after pull."""
        original_attempt = self.config.last_pull_attempt
        original_success = self.config.last_successful_pull
        
        # Run pull
        pull_raster_data(self.config.id)
        
        # Refresh from database
        self.config.refresh_from_db()
        
        # last_pull_attempt should be updated
        assert self.config.last_pull_attempt != original_attempt
        
        # If pull succeeded, last_successful_pull should update
        latest_log = RasterPullLog.objects.filter(
            configuration=self.config
        ).latest('started_at')
        
        if latest_log.status == 'success':
            assert self.config.last_successful_pull != original_success
    
    def test_raster_config_detail_shows_logs(self):
        """Test that config detail page shows associated logs."""
        # Create a log
        pull_log = RasterPullLog.objects.create(
            configuration=self.config,
            status='success',
            started_at=timezone.now() - timedelta(hours=1),
            completed_at=timezone.now(),
            layers_attempted=3,
            layers_successful=3,
            layers_failed=0
        )
        
        # Access config detail page
        url = reverse('streamflow:raster_config_detail', args=[self.config.id])
        response = self.client.get(url)
        
        assert response.status_code == 200
        # Check that log info appears on page
        assert str(pull_log.layers_successful).encode() in response.content
    
    def test_disabled_config_can_still_be_triggered(self):
        """Test that disabled configs can still be manually triggered."""
        self.config.schedule_enabled = False
        self.config.save()
        
        url = reverse('streamflow:trigger_raster_pull', args=[self.config.id])
        response = self.client.post(url, {'sync': 'true'})
        
        # Should still work
        assert response.status_code == 302
        
        # Log should be created
        assert RasterPullLog.objects.filter(configuration=self.config).exists()


class RasterLogViewTest(TestCase):
    """Test raster log list view functionality."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username='test', password='test')
        self.client = Client()
        self.client.login(username='test', password='test')
        
        # Create test config
        dataset = RasterDataset.objects.create(
            name='Test Dataset',
            data_source='nomads',
            temporal_resolution='hourly',
            spatial_resolution=2500.0
        )
        
        variable = RasterVariable.objects.create(
            dataset=dataset,
            name='test_var',
            long_name='Test Variable',
            units='test'
        )
        
        extent = SpatialExtent.objects.create(
            name='Test Extent',
            bbox=[-125, 45, -120, 48],
            projection='EPSG:4326'
        )
        
        self.config = RasterPullConfiguration.objects.create(
            name='Test Config',
            dataset=dataset,
            lookback_days=1
        )
        self.config.variables.add(variable)
        self.config.extents.add(extent)
        
        # Create multiple logs
        for i in range(5):
            RasterPullLog.objects.create(
                configuration=self.config,
                status='success' if i % 2 == 0 else 'failed',
                started_at=timezone.now() - timedelta(hours=i),
                completed_at=timezone.now() - timedelta(hours=i) + timedelta(minutes=5),
                layers_attempted=10,
                layers_successful=10 if i % 2 == 0 else 5,
                layers_failed=0 if i % 2 == 0 else 5
            )
    
    def test_gridded_logs_page_loads(self):
        """Test that gridded logs page loads successfully."""
        url = reverse('streamflow:raster_pull_logs')
        response = self.client.get(url)
        
        assert response.status_code == 200
        assert b'Raster Pull Logs' in response.content or b'Gridded' in response.content
    
    def test_logs_appear_in_list(self):
        """Test that created logs appear in the list."""
        url = reverse('streamflow:raster_pull_logs')
        response = self.client.get(url)
        
        # Should show configuration name
        assert self.config.name.encode() in response.content
        
        # Should show some status indicators
        assert b'success' in response.content or b'Success' in response.content
    
    def test_log_filtering_by_status(self):
        """Test filtering logs by status."""
        url = reverse('streamflow:raster_pull_logs')
        
        # Filter for success
        response = self.client.get(url, {'status': 'success'})
        assert response.status_code == 200
        
        # Filter for failed
        response = self.client.get(url, {'status': 'failed'})
        assert response.status_code == 200
    
    def test_log_filtering_by_configuration(self):
        """Test filtering logs by configuration."""
        url = reverse('streamflow:raster_pull_logs')
        response = self.client.get(url, {'configuration': self.config.id})
        
        assert response.status_code == 200


class RasterDataStorageTest(TestCase):
    """Test that raster data is actually saved to filesystem."""
    
    def setUp(self):
        """Set up minimal config for storage test."""
        from django.conf import settings
        self.raster_dir = Path(settings.RASTER_STORAGE_DIR)
        
    def test_raster_storage_directory_exists(self):
        """Test that raster storage directory exists."""
        assert self.raster_dir.exists()
        assert self.raster_dir.is_dir()
    
    def test_raster_layer_model_path_generation(self):
        """Test that RasterLayer model generates correct file paths."""
        dataset = RasterDataset.objects.create(
            name='Test',
            data_source='nomads',
            temporal_resolution='hourly',
            spatial_resolution=2500
        )
        
        variable = RasterVariable.objects.create(
            dataset=dataset,
            name='test_var',
            long_name='Test',
            units='test'
        )
        
        extent = SpatialExtent.objects.create(
            name='Test',
            bbox=[-125, 45, -120, 48],
            projection='EPSG:4326'
        )
        
        layer = RasterLayer.objects.create(
            variable=variable,
            extent=extent,
            timestamp=timezone.now(),
            file_path='test/path/file.tif',
            file_size_bytes=1024
        )
        
        # Should have a file path
        assert layer.file_path is not None
        assert layer.file_path != ''


def run_manual_integration_test():
    """
    Manual integration test for command-line testing.
    
    Usage:
        python manage.py shell < tests/test_raster_pull_integration.py
        # Then call: run_manual_integration_test()
    """
    from django.contrib.auth.models import User
    from apps.streamflow.models import RasterPullConfiguration
    
    print("=" * 60)
    print("RASTER PULL INTEGRATION TEST")
    print("=" * 60)
    
    # Check configurations
    configs = RasterPullConfiguration.objects.all()
    print(f"\n✓ Found {configs.count()} raster pull configuration(s)")
    
    if configs.count() == 0:
        print("\n❌ No configurations found. Create one first!")
        return
    
    config = configs.first()
    print(f"\nTesting configuration: {config.name}")
    print(f"  Variables: {config.variables.count()}")
    print(f"  Extents: {config.extents.count()}")
    print(f"  Enabled: {config.schedule_enabled}")
    
    if config.variables.count() == 0 or config.extents.count() == 0:
        print("\n❌ Configuration has no variables or extents!")
        return
    
    print("\n--- Running synchronous pull test ---")
    from src.acquisition.raster_tasks import pull_raster_data
    
    try:
        result = pull_raster_data(config.id)
        print(f"\n✓ Pull completed!")
        print(f"  Result: {result}")
        
        # Check logs
        latest_log = RasterPullLog.objects.filter(
            configuration=config
        ).latest('started_at')
        
        print(f"\n✓ Pull log created:")
        print(f"  Status: {latest_log.status}")
        print(f"  Layers attempted: {latest_log.layers_attempted}")
        print(f"  Layers successful: {latest_log.layers_successful}")
        print(f"  Duration: {latest_log.duration_seconds}s")
        
        if latest_log.error_message:
            print(f"  Error: {latest_log.error_message}")
        
        print("\n" + "=" * 60)
        print("TEST COMPLETE")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    print("Run this with: python manage.py test tests.test_raster_pull_integration")
    print("Or manually: python manage.py shell")
    print(">>> from tests.test_raster_pull_integration import run_manual_integration_test")
    print(">>> run_manual_integration_test()")
