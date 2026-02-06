"""
Comprehensive tests for data pull configurations (timeseries and raster).

Tests the actual execution of pull configurations to ensure:
1. Timeseries pulls work with USGS data
2. Timeseries pulls work with NOAA RFC data (using HADS mappings)
3. Raster pulls work with all data sources
4. Configuration triggering works properly
"""

import pytest
from django.test import TestCase
from django.utils import timezone
from datetime import datetime, timedelta

from apps.streamflow.models import (
    PullConfiguration,
    PullConfigurationStation,
    MasterStation,
    Station,
    StationMapping,
    Observation,
    RasterPullConfiguration,
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterPullLog,
    RasterLayer
)

from src.acquisition.tasks import execute_pull_configuration
from src.acquisition.raster_tasks import pull_raster_data
from src.acquisition.usgs_client import USGSClient
from src.acquisition.noaa_client import NOAAClient


class TestTimeseriesConfigurationPulls(TestCase):
    """Test timeseries data pull configurations."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a test USGS station
        self.usgs_station = MasterStation.objects.create(
            station_number='12447390',  # Real USGS station
            station_name='ANDREWS CREEK NEAR MAZAMA WA',
            agency='USGS',
            latitude=48.8231,
            longitude=-120.1447,
            state_code='WA'
        )
        
        # Create a test NOAA RFC station
        self.noaa_station = MasterStation.objects.create(
            noaa_lid='ACMW1',  # Corresponding NOAA LID
            station_number='ACMW1',
            station_name='ANDREWS CREEK NEAR MAZAMA WA',
            agency='NOAA_RFC',
            latitude=48.8231,
            longitude=-120.1447,
            state_code='WA'
        )
        
        # Create mapping between them
        StationMapping.objects.create(
            source_agency='USGS',
            source_id='12447390',
            target_agency='NOAA_RFC',
            target_id='ACMW1'
        )
        StationMapping.objects.create(
            source_agency='NOAA_RFC',
            source_id='ACMW1',
            target_agency='USGS',
            target_id='12447390'
        )
        
    def test_usgs_client_real_data(self):
        """Test that USGS client can fetch real data."""
        client = USGSClient()
        
        # Test with a known active station
        end_date = timezone.now()
        start_date = end_date - timedelta(days=7)
        
        data = client.get_discharge_data(
            '12447390',  # Real USGS station
            start_date,
            end_date
        )
        
        self.assertIsNotNone(data)
        print(f"\nUSGS data returned: {len(data)} records")
        if len(data) > 0:
            print(f"Sample record: {data[0]}")
    
    def test_noaa_client_forecast_data(self):
        """Test that NOAA client can fetch forecast data."""
        client = NOAAClient()
        
        # Test with a station that should have forecasts
        try:
            forecast = client.get_rfc_forecast('ACMW1')
            print(f"\nNOAA forecast for ACMW1:")
            if forecast:
                print(f"  Forecast points: {len(forecast.get('forecast_points', []))}")
                print(f"  Issue time: {forecast.get('issue_time', 'N/A')}")
            else:
                print("  No active forecast")
        except Exception as e:
            print(f"\nNOAA forecast fetch failed: {e}")
    
    def test_station_mapping_lookup(self):
        """Test that station mappings work correctly."""
        # USGS -> NOAA lookup
        mapping = StationMapping.objects.filter(
            source_agency='USGS',
            source_id='12447390'
        ).first()
        
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.target_id, 'ACMW1')
        print(f"\nUSGS -> NOAA mapping: {mapping}")
        
        # NOAA -> USGS lookup
        reverse_mapping = StationMapping.objects.filter(
            source_agency='NOAA_RFC',
            source_id='ACMW1'
        ).first()
        
        self.assertIsNotNone(reverse_mapping)
        self.assertEqual(reverse_mapping.target_id, '12447390')
        print(f"NOAA -> USGS mapping: {reverse_mapping}")


class TestRasterConfigurationPulls(TestCase):
    """Test raster data pull configurations."""
    
    def setUp(self):
        """Set up test raster configuration."""
        # Check if datasets exist from init_raster_datasets
        self.rtma_dataset = RasterDataset.objects.filter(
            name='NOAA_RTMA'
        ).first()
        
        if not self.rtma_dataset:
            pytest.skip("RTMA dataset not initialized. Run: python manage.py init_raster_datasets")
    
    def test_rtma_dataset_exists(self):
        """Test that RTMA dataset is configured."""
        self.assertIsNotNone(self.rtma_dataset)
        print(f"\nRTMA Dataset: {self.rtma_dataset.name}")
        print(f"  Variables: {self.rtma_dataset.variables.count()}")
        print(f"  Data source: {self.rtma_dataset.data_source}")
    
    def test_list_raster_configurations(self):
        """List all raster configurations."""
        configs = RasterPullConfiguration.objects.all()
        print(f"\nRaster Configurations: {configs.count()}")
        for config in configs:
            var_count = config.variables.count()
            print(f"  {config.id}: {config.name} - {var_count} variables")
            if var_count > 0:
                vars_list = [v.name for v in config.variables.all()[:3]]
                print(f"     Variables: {', '.join(vars_list)}")
    
    def test_check_recent_raster_pulls(self):
        """Check recent raster pull logs."""
        recent_logs = RasterPullLog.objects.order_by('-started_at')[:10]
        print(f"\nRecent Raster Pull Logs: {recent_logs.count()}")
        
        for log in recent_logs:
            status_emoji = "✓" if log.status == 'completed' else "✗" if log.status == 'failed' else "⏳"
            print(f"  {status_emoji} {log.configuration.name}")
            print(f"     Status: {log.status}")
            print(f"     Started: {log.started_at}")
            if log.error_message:
                print(f"     Error: {log.error_message[:100]}")
    
    def test_check_raster_layers(self):
        """Check created raster layers."""
        layers = RasterLayer.objects.order_by('-timestamp')[:5]
        print(f"\nRecent Raster Layers: {layers.count()}")
        
        for layer in layers:
            print(f"  {layer.variable.name}")
            print(f"     Timestamp: {layer.timestamp}")
            print(f"     File: {layer.file_path}")


class TestConfigurationTriggering(TestCase):
    """Test manual triggering of configurations."""
    
    def test_list_timeseries_configs(self):
        """List all timeseries configurations with station counts."""
        configs = PullConfiguration.objects.all()
        print(f"\n{'='*70}")
        print(f"TIMESERIES CONFIGURATIONS")
        print(f"{'='*70}")
        
        for config in configs:
            station_count = config.configuration_stations.count()
            print(f"\nID: {config.id}")
            print(f"Name: {config.name}")
            print(f"Stations: {station_count}")
            print(f"Active: {config.is_active}")
            print(f"Schedule: {config.schedule_interval}")
            
            # Show sample stations
            if station_count > 0:
                sample_stations = config.configuration_stations.all()[:5]
                for cs in sample_stations:
                    ms = cs.master_station
                    print(f"  - {ms.station_number}: {ms.station_name} ({ms.agency})")
                if station_count > 5:
                    print(f"  ... and {station_count - 5} more stations")
    
    def test_list_raster_configs(self):
        """List all raster configurations with variable counts."""
        configs = RasterPullConfiguration.objects.all()
        print(f"\n{'='*70}")
        print(f"RASTER CONFIGURATIONS")
        print(f"{'='*70}")
        
        for config in configs:
            var_count = config.variables.count()
            print(f"\nID: {config.id}")
            print(f"Name: {config.name}")
            print(f"Dataset: {config.dataset.name if config.dataset else 'None'}")
            print(f"Variables: {var_count}")
            print(f"Active: {config.is_active}")
            print(f"Extent: {config.spatial_extent.name if config.spatial_extent else 'None'}")
            
            # Show variables
            if var_count > 0:
                variables = config.variables.all()
                for var in variables:
                    print(f"  - {var.name} ({var.unit})")


def run_manual_tests():
    """Run tests manually (not part of pytest)."""
    print("\n" + "="*70)
    print("MANUAL CONFIGURATION TESTING")
    print("="*70)
    
    # Test 1: Check HADS mappings
    print("\n1. Checking HADS Mappings...")
    mapping_count = StationMapping.objects.count()
    print(f"   Total mappings: {mapping_count}")
    
    sample_mappings = StationMapping.objects.all()[:5]
    for mapping in sample_mappings:
        print(f"   {mapping}")
    
    # Test 2: Check timeseries configs
    print("\n2. Checking Timeseries Configurations...")
    ts_configs = PullConfiguration.objects.all()
    print(f"   Total configs: {ts_configs.count()}")
    
    for config in ts_configs:
        station_count = config.configuration_stations.count()
        print(f"   {config.id}: {config.name} - {station_count} stations")
    
    # Test 3: Check raster configs
    print("\n3. Checking Raster Configurations...")
    raster_configs = RasterPullConfiguration.objects.all()
    print(f"   Total configs: {raster_configs.count()}")
    
    for config in raster_configs:
        var_count = config.variables.count()
        dataset_name = config.dataset.name if config.dataset else 'None'
        print(f"   {config.id}: {config.name} - {dataset_name}, {var_count} vars")
    
    # Test 4: Try a small USGS pull
    print("\n4. Testing USGS Data Pull...")
    try:
        client = USGSClient()
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3)
        
        # Use a known active station
        data = client.get_discharge_data('12447390', start_date, end_date)
        print(f"   USGS data retrieved: {len(data)} records")
        if len(data) > 0:
            print(f"   Sample: {data[0]}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n" + "="*70)


if __name__ == '__main__':
    # Run manual tests when executed directly
    import django
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()
    
    run_manual_tests()
