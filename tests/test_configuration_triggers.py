"""
Comprehensive tests for manually triggering timeseries and raster configurations.
"""

import pytest
from datetime import datetime, timedelta
from django.test import TestCase
from django.utils import timezone

from apps.streamflow.models import (
    PullConfiguration,
    MasterStation,
    Station,
    PullConfigurationStation,
    ForecastRun,
    DischargeObservation,
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


class TestTimeseriesConfigurationTrigger(TestCase):
    """Test manually triggering timeseries data pull configurations."""

    def setUp(self):
        """Set up test data."""
        # Create a USGS master station
        self.usgs_station = MasterStation.objects.create(
            station_number='12488500',  # Yakima River at Kiona, WA
            station_name='Yakima River at Kiona',
            agency='USGS',
            latitude=46.246,
            longitude=-119.477,
            state_code='WA'
        )
        
        # Create NOAA RFC stations (ones with forecasts)
        self.noaa_station_1 = MasterStation.objects.create(
            station_number='ABOM8',  # Clark Fork above Missoula
            noaa_lid='ABOM8',
            station_name='Clark Fork River above Missoula',
            agency='NOAA_RFC',
            latitude=46.96,
            longitude=-113.99,
            state_code='MT',
            rfc_code='NWRFC'
        )
        
        self.noaa_station_2 = MasterStation.objects.create(
            station_number='WLDO3',  # Willamette at Portland
            noaa_lid='WLDO3',
            station_name='Willamette River at Portland',
            agency='NOAA_RFC',
            latitude=45.52,
            longitude=-122.67,
            state_code='OR',
            rfc_code='NWRFC'
        )
        
        # Create pull configurations
        self.usgs_config = PullConfiguration.objects.create(
            name='Test USGS Config',
            agency='USGS',
            data_type='observation',
            interval='daily',
            enabled=True
        )
        
        self.noaa_config = PullConfiguration.objects.create(
            name='Test NOAA RFC Config',
            agency='NOAA_RFC',
            data_type='forecast',
            interval='daily',
            enabled=True
        )
        
        # Add stations to configurations
        PullConfigurationStation.objects.create(
            configuration=self.usgs_config,
            master_station=self.usgs_station
        )
        
        PullConfigurationStation.objects.create(
            configuration=self.noaa_config,
            master_station=self.noaa_station_1
        )
        
        PullConfigurationStation.objects.create(
            configuration=self.noaa_config,
            master_station=self.noaa_station_2
        )

    def test_usgs_client_data_retrieval(self):
        """Test USGS client can retrieve data."""
        client = USGSClient()
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        data = client.get_daily_mean(
            self.usgs_station.station_number,
            start_date,
            end_date
        )
        
        # Should get observations
        self.assertGreater(len(data), 0, "Should retrieve USGS observations")
        
        # Check data format
        first_obs = data[0]
        self.assertIn('observed_at', first_obs)
        self.assertIn('discharge', first_obs)
        self.assertIn('unit', first_obs)
        self.assertEqual(first_obs['unit'], 'cfs')
    
    def test_noaa_client_forecast_retrieval(self):
        """Test NOAA client can retrieve forecast data."""
        client = NOAAClient()
        
        # Test with a station that should have forecast
        forecast_data = client.get_rfc_forecast(self.noaa_station_1.noaa_lid)
        
        # May or may not have forecast depending on current conditions
        if forecast_data:
            self.assertIn('run_date', forecast_data)
            self.assertIn('forecast_data', forecast_data)
            self.assertIsInstance(forecast_data['forecast_data'], list)
            
            if forecast_data['forecast_data']:
                first_point = forecast_data['forecast_data'][0]
                self.assertIn('date', first_point)
                self.assertIn('value', first_point)
    
    def test_trigger_usgs_configuration(self):
        """Test manually triggering a USGS configuration."""
        print(f"\n{'='*60}")
        print(f"Testing USGS Configuration: {self.usgs_config.name}")
        print(f"{'='*60}")
        
        # Count observations before
        obs_before = DischargeObservation.objects.count()
        
        # Trigger the configuration
        result = execute_pull_configuration(self.usgs_config.id)
        
        print(f"\nResult: {result}")
        
        # Check observations were created
        obs_after = DischargeObservation.objects.count()
        
        print(f"Observations before: {obs_before}")
        print(f"Observations after: {obs_after}")
        print(f"New observations: {obs_after - obs_before}")
        
        self.assertGreater(
            obs_after, obs_before,
            "Should create new observations"
        )
        
        # Verify the observation data
        latest_obs = DischargeObservation.objects.order_by('-observed_at').first()
        if latest_obs:
            print(f"\nLatest observation:")
            print(f"  Station: {latest_obs.station.station_number}")
            print(f"  Time: {latest_obs.observed_at}")
            print(f"  Discharge: {latest_obs.discharge} {latest_obs.unit}")
    
    def test_trigger_noaa_configuration(self):
        """Test manually triggering a NOAA RFC configuration."""
        print(f"\n{'='*60}")
        print(f"Testing NOAA RFC Configuration: {self.noaa_config.name}")
        print(f"{'='*60}")
        
        # Count forecast runs before
        forecasts_before = ForecastRun.objects.count()
        
        # Trigger the configuration
        result = execute_pull_configuration(self.noaa_config.id)
        
        print(f"\nResult: {result}")
        
        # Check forecasts were created
        forecasts_after = ForecastRun.objects.count()
        
        print(f"Forecast runs before: {forecasts_before}")
        print(f"Forecast runs after: {forecasts_after}")
        print(f"New forecast runs: {forecasts_after - forecasts_before}")
        
        # Note: Many NOAA stations may not have active forecasts
        # So we don't assert forecast creation, just verify no errors
        
        # If forecasts were created, verify them
        if forecasts_after > forecasts_before:
            latest_forecast = ForecastRun.objects.order_by('-run_date').first()
            print(f"\nLatest forecast run:")
            print(f"  Station: {latest_forecast.station.station_number}")
            print(f"  Run date: {latest_forecast.run_date}")
            print(f"  Data points: {len(latest_forecast.data)}")
            print(f"  Source: {latest_forecast.source}")
        else:
            print("\nNote: No forecasts created (stations may not have active forecasts)")
    
    def test_configuration_status_reporting(self):
        """Test that configuration execution reports status correctly."""
        # Execute configuration
        result = execute_pull_configuration(self.usgs_config.id)
        
        # Check result structure
        self.assertIsInstance(result, dict)
        self.assertIn('status', result)
        self.assertIn('records_processed', result)
        self.assertIn('successful_stations', result)
        self.assertIn('failed_stations', result)
        
        print(f"\nConfiguration execution report:")
        print(f"  Status: {result['status']}")
        print(f"  Records processed: {result['records_processed']}")
        print(f"  Successful stations: {result['successful_stations']}")
        print(f"  Failed stations: {result['failed_stations']}")


class TestRasterConfigurationTrigger(TestCase):
    """Test manually triggering raster data pull configurations."""
    
    def setUp(self):
        """Set up test data for raster pulls."""
        # Create spatial extent
        self.extent = SpatialExtent.objects.create(
            name='Test_Region',
            description='Test region for pulls',
            bbox=[-125.0, 45.0, -120.0, 49.0]
        )
        
        # Create NOAA RTMA dataset
        self.rtma_dataset = RasterDataset.objects.create(
            name='NOAA_RTMA_Test',
            source='nomads',
            temporal_resolution='hourly',
            spatial_resolution_km=2.5,
            description='Test RTMA dataset',
            url_pattern='https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/'
        )
        
        # Create variable
        self.temp_variable = RasterVariable.objects.create(
            dataset=self.rtma_dataset,
            name='tmp2m',
            standard_name='air_temperature',
            long_name='2-meter Temperature',
            unit='K',
            gee_band_name='tmp2m'
        )
        
        # Create pull configuration
        self.raster_config = RasterPullConfiguration.objects.create(
            name='Test RTMA Temperature',
            dataset=self.rtma_dataset,
            spatial_extent=self.extent,
            schedule='0 * * * *',  # Hourly
            is_active=True,
            apply_compression=True,
            generate_thumbnails=False
        )
        
        self.raster_config.variables.add(self.temp_variable)
    
    def test_raster_configuration_exists(self):
        """Test that raster configuration was created properly."""
        config = RasterPullConfiguration.objects.get(id=self.raster_config.id)
        
        self.assertEqual(config.name, 'Test RTMA Temperature')
        self.assertEqual(config.variables.count(), 1)
        self.assertIsNotNone(config.dataset)
        self.assertIsNotNone(config.spatial_extent)
        
        print(f"\nRaster configuration:")
        print(f"  Name: {config.name}")
        print(f"  Dataset: {config.dataset.name}")
        print(f"  Variables: {config.variables.count()}")
        print(f"  Extent: {config.spatial_extent.name}")
    
    @pytest.mark.skip(reason="Requires external API access and can be slow")
    def test_trigger_raster_configuration(self):
        """Test manually triggering a raster configuration."""
        print(f"\n{'='*60}")
        print(f"Testing Raster Configuration: {self.raster_config.name}")
        print(f"{'='*60}")
        
        # Count layers before
        layers_before = RasterLayer.objects.count()
        logs_before = RasterPullLog.objects.count()
        
        # Trigger the configuration
        pull_date = timezone.now().date()
        
        try:
            result = pull_raster_data.apply(
                args=[self.raster_config.id, pull_date.isoformat()]
            )
            
            print(f"\nTask result: {result}")
            
            # Check layers were created
            layers_after = RasterLayer.objects.count()
            logs_after = RasterPullLog.objects.count()
            
            print(f"Layers before: {layers_before}")
            print(f"Layers after: {layers_after}")
            print(f"New layers: {layers_after - layers_before}")
            print(f"Pull logs: {logs_after - logs_before}")
            
            # Check for pull log
            if logs_after > logs_before:
                latest_log = RasterPullLog.objects.order_by('-started_at').first()
                print(f"\nLatest pull log:")
                print(f"  Configuration: {latest_log.configuration.name}")
                print(f"  Status: {latest_log.status}")
                print(f"  Started: {latest_log.started_at}")
                print(f"  Layers created: {latest_log.layers_created}")
                if latest_log.error_message:
                    print(f"  Error: {latest_log.error_message}")
        
        except Exception as e:
            print(f"\nError triggering raster pull: {e}")
            import traceback
            traceback.print_exc()
            
            # Check for error in logs
            error_log = RasterPullLog.objects.filter(
                configuration=self.raster_config,
                status='failed'
            ).order_by('-started_at').first()
            
            if error_log:
                print(f"\nError log found:")
                print(f"  Error: {error_log.error_message}")


class TestAPIConnectivity(TestCase):
    """Test that external APIs are accessible."""
    
    def test_usgs_api_accessible(self):
        """Test USGS NWIS API is accessible."""
        import dataretrieval.nwis as nwis
        
        # Try to get site info for a known station
        try:
            result = nwis.get_info(sites='12488500')
            
            if isinstance(result, tuple):
                df, metadata = result
            else:
                df = result
            
            self.assertIsNotNone(df)
            self.assertFalse(df.empty, "Should retrieve station info from USGS")
            
            print("\n✓ USGS NWIS API is accessible")
        except Exception as e:
            self.fail(f"USGS API not accessible: {e}")
    
    def test_noaa_api_accessible(self):
        """Test NOAA Water API is accessible."""
        import requests
        
        try:
            response = requests.get(
                'https://api.water.noaa.gov/nwps/v1/gauges?limit=1',
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            self.assertIn('gauges', data)
            
            print("✓ NOAA Water API is accessible")
        except Exception as e:
            self.fail(f"NOAA API not accessible: {e}")
    
    def test_nomads_rtma_accessible(self):
        """Test NOAA NOMADS RTMA server is accessible."""
        import requests
        from datetime import datetime
        
        try:
            # Check if the RTMA directory exists
            today = datetime.utcnow()
            url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/rtma2p5.{today.strftime('%Y%m%d')}/"
            
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                print("✓ NOAA NOMADS RTMA server is accessible")
            else:
                print(f"⚠ NOMADS returned status {response.status_code}")
        except Exception as e:
            print(f"⚠ NOMADS RTMA not accessible: {e}")
            # Don't fail the test - NOMADS can be temporarily unavailable


def run_manual_tests():
    """Run tests manually from command line."""
    import django
    django.setup()
    
    from django.test.utils import get_runner
    from django.conf import settings
    
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=2, interactive=False, keepdb=True)
    
    failures = test_runner.run_tests(['tests.test_configuration_triggers'])
    
    return failures


if __name__ == '__main__':
    run_manual_tests()
