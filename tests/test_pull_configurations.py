"""
Tests for PullConfiguration deployment and data collection.

These tests verify that all deployed configurations are correctly set up
and can successfully collect data from their respective sources.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase

from apps.streamflow.models import (
    PullConfiguration,
    PullConfigurationStation,
    Station,
    DischargeObservation,
    ForecastRun
)
from src.acquisition.usgs_client import USGSClient
from src.acquisition.noaa_client import NOAAClient


class PullConfigurationDeploymentTests(TestCase):
    """Test that all configurations are properly deployed."""

    def test_nwrfc_short_forecast_config_exists(self):
        """Verify NWRFC short-range forecast config is deployed."""
        config = PullConfiguration.objects.get(
            name="NWRFC Short-Range Forecast Collection"
        )
        
        # Verify configuration settings
        self.assertEqual(config.data_source, "NOAA_RFC")
        self.assertEqual(config.data_type, "forecast")
        self.assertEqual(config.forecast_type, "short")
        self.assertEqual(config.data_strategy, "append")
        self.assertEqual(config.schedule_type, "daily")
        self.assertEqual(config.schedule_value, "30 16 * * *")  # 8:30 AM PST
        self.assertTrue(config.is_enabled)
        
        # Verify stations are linked
        station_count = config.configuration_stations.count()
        self.assertEqual(station_count, 78, 
                        f"Expected 78 NWRFC stations, found {station_count}")

    def test_nwrfc_medium_forecast_config_exists(self):
        """Verify NWRFC medium-range forecast config is deployed."""
        config = PullConfiguration.objects.get(
            name="NWRFC Medium-Range Forecast Collection"
        )
        
        # Verify configuration settings
        self.assertEqual(config.data_source, "NOAA_RFC")
        self.assertEqual(config.data_type, "forecast")
        self.assertEqual(config.forecast_type, "medium")
        self.assertEqual(config.data_strategy, "append")
        self.assertEqual(config.schedule_type, "daily")
        self.assertEqual(config.schedule_value, "30 16 * * *")  # 8:30 AM PST
        self.assertTrue(config.is_enabled)
        
        # Verify stations are linked
        station_count = config.configuration_stations.count()
        self.assertEqual(station_count, 78,
                        f"Expected 78 NWRFC stations, found {station_count}")

    def test_pnw_daily_mean_config_exists(self):
        """Verify PNW daily mean discharge config is deployed."""
        config = PullConfiguration.objects.get(
            name="PNW USGS Daily Mean Discharge"
        )
        
        # Verify configuration settings
        self.assertEqual(config.data_source, "USGS")
        self.assertEqual(config.data_type, "observed")
        self.assertEqual(config.data_strategy, "replace")
        self.assertEqual(config.schedule_type, "daily")
        self.assertEqual(config.schedule_value, "0 17 * * *")  # 9:00 AM PST
        self.assertTrue(config.is_enabled)
        
        # Verify stations are linked
        station_count = config.configuration_stations.count()
        self.assertEqual(station_count, 2890,
                        f"Expected 2890 PNW USGS stations, found {station_count}")

    def test_pnw_realtime_config_exists(self):
        """Verify PNW real-time config is deployed."""
        config = PullConfiguration.objects.get(
            name="PNW USGS Real-time 7-Day Window"
        )
        
        # Verify configuration settings
        self.assertEqual(config.data_source, "USGS")
        self.assertEqual(config.data_type, "realtime")
        self.assertEqual(config.data_strategy, "overwrite")
        self.assertEqual(config.schedule_type, "custom")
        self.assertEqual(config.schedule_value, "0 */4 * * *")  # Every 4 hours
        self.assertTrue(config.is_enabled)
        
        # Verify stations are linked
        station_count = config.configuration_stations.count()
        self.assertEqual(station_count, 2890,
                        f"Expected 2890 PNW USGS stations, found {station_count}")

    def test_all_configs_have_valid_stations(self):
        """Verify all configurations have valid active stations."""
        configs = PullConfiguration.objects.all()
        
        for config in configs:
            station_numbers = config.configuration_stations.values_list(
                'station_number', flat=True
            )
            
            # Verify all station numbers reference actual stations
            actual_stations = Station.objects.filter(
                station_number__in=station_numbers,
                is_active=True
            ).count()
            
            expected_stations = len(station_numbers)
            self.assertEqual(
                actual_stations, 
                expected_stations,
                f"Config '{config.name}' has invalid stations. "
                f"Expected {expected_stations}, found {actual_stations}"
            )

    def test_no_duplicate_stations_within_config(self):
        """Verify no configuration has duplicate station assignments."""
        configs = PullConfiguration.objects.all()
        
        for config in configs:
            station_numbers = list(
                config.configuration_stations.values_list('station_number', flat=True)
            )
            
            unique_count = len(set(station_numbers))
            total_count = len(station_numbers)
            
            self.assertEqual(
                unique_count,
                total_count,
                f"Config '{config.name}' has duplicate stations. "
                f"Total: {total_count}, Unique: {unique_count}"
            )


class USGSDailyMeanDataCollectionTests(TestCase):
    """Test USGS daily mean data collection."""

    @classmethod
    def setUpTestData(cls):
        """Create test station."""
        cls.station = Station.objects.create(
            station_number="12345678",
            name="Test Station",
            agency="USGS",
            huc_code="17010101",
            is_active=True
        )

    @patch('dataretrieval.nwis.get_dv')
    def test_usgs_daily_mean_collection(self, mock_get_dv):
        """Test that daily mean data can be collected from USGS."""
        # Mock USGS dataretrieval response
        import pandas as pd
        mock_df = pd.DataFrame({
            '00060_Mean': [100.5],
            '00060_Mean_cd': ['A']
        }, index=[pd.Timestamp('2026-02-03')])
        
        mock_metadata = {'site_code': ['12345678']}
        mock_get_dv.return_value = (mock_df, mock_metadata)

        # Initialize client and fetch data
        client = USGSClient()
        start_date = datetime(2026, 2, 3)
        end_date = datetime(2026, 2, 3)
        
        data = client.get_daily_mean(
            station_number=self.station.station_number,
            start_date=start_date,
            end_date=end_date
        )

        # Verify data was returned
        self.assertIsNotNone(data)
        self.assertGreater(len(data), 0)
        self.assertEqual(data[0]['discharge'], 100.5)
        self.assertEqual(data[0]['type'], 'daily_mean')
        
        # Verify API was called correctly
        mock_get_dv.assert_called_once()
        call_args = mock_get_dv.call_args
        self.assertEqual(call_args[1]['sites'], self.station.station_number)
        self.assertEqual(call_args[1]['parameterCd'], '00060')

    def test_daily_mean_observation_storage(self):
        """Test that daily mean observations can be stored."""
        observation = DischargeObservation.objects.create(
            station=self.station,
            observed_at=datetime(2026, 2, 3, tzinfo=timezone.utc),
            discharge=100.5,
            unit="cfs",
            type="daily_mean",
            quality_code="A"
        )
        
        # Verify storage
        self.assertIsNotNone(observation.id)
        
        # Verify retrieval
        retrieved = DischargeObservation.objects.get(id=observation.id)
        self.assertEqual(retrieved.discharge, 100.5)
        self.assertEqual(retrieved.type, "daily_mean")


class USGSRealtimeDataCollectionTests(TestCase):
    """Test USGS real-time data collection."""

    @classmethod
    def setUpTestData(cls):
        """Create test station."""
        cls.station = Station.objects.create(
            station_number="12345679",
            name="Test Realtime Station",
            agency="USGS",
            huc_code="17010101",
            is_active=True
        )

    @patch('dataretrieval.nwis.get_iv')
    def test_usgs_realtime_collection(self, mock_get_iv):
        """Test that real-time 15-min data can be collected from USGS."""
        # Mock USGS dataretrieval response
        import pandas as pd
        mock_df = pd.DataFrame({
            '_00060': [95.2, 95.5],  # Column name format from dataretrieval
            '_00060_cd': ['P', 'P']
        }, index=[
            pd.Timestamp('2026-02-03 10:00:00'),
            pd.Timestamp('2026-02-03 10:15:00')
        ])
        
        mock_metadata = {'site_code': ['12345679']}
        mock_get_iv.return_value = (mock_df, mock_metadata)

        # Initialize client and fetch data
        client = USGSClient()
        
        # Get last 7 days (rolling window)
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=7)
        
        data = client.get_instantaneous(
            station_number=self.station.station_number,
            start_date=start_date,
            end_date=end_date
        )

        # Verify data was returned
        self.assertIsNotNone(data)
        self.assertGreater(len(data), 0)
        self.assertEqual(data[0]['discharge'], 95.2)
        self.assertEqual(data[0]['type'], 'realtime_15min')
        
        # Verify API was called
        mock_get_iv.assert_called_once()
        call_args = mock_get_iv.call_args
        self.assertEqual(call_args[1]['sites'], self.station.station_number)
        self.assertEqual(call_args[1]['parameterCd'], '00060')

    def test_realtime_observation_storage(self):
        """Test that real-time observations can be stored."""
        observation = DischargeObservation.objects.create(
            station=self.station,
            observed_at=datetime(2026, 2, 3, 10, 15, tzinfo=timezone.utc),
            discharge=95.5,
            unit="cfs",
            type="realtime_15min",
            quality_code="P"
        )
        
        # Verify storage
        self.assertIsNotNone(observation.id)
        
        # Verify retrieval
        retrieved = DischargeObservation.objects.get(id=observation.id)
        self.assertEqual(retrieved.discharge, 95.5)
        self.assertEqual(retrieved.type, "realtime_15min")


class NOAARFCForecastCollectionTests(TestCase):
    """Test NOAA RFC forecast data collection."""

    @classmethod
    def setUpTestData(cls):
        """Create test NOAA station."""
        cls.station = Station.objects.create(
            station_number="PTAO3",
            name="Test NOAA Station",
            agency="NOAA_RFC",
            is_active=True
        )

    @patch('src.acquisition.noaa_client.requests.get')
    def test_noaa_short_forecast_collection(self, mock_get):
        """Test that short-range (18hr) forecasts can be collected."""
        # Mock NOAA API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'forecast': {
                'data': [
                    {'validTime': '2026-02-03T09:00:00Z', 'flow': 100.0},
                    {'validTime': '2026-02-03T10:00:00Z', 'flow': 101.5}
                ],
                'rmse': 5.2
            }
        }
        mock_get.return_value = mock_response

        # Initialize client
        client = NOAAClient()
        
        # Fetch short-range forecast
        data = client.get_forecast(
            hads_id=self.station.station_number,
            forecast_type='short'
        )

        # Verify data was returned
        self.assertIsNotNone(data)
        self.assertIn('data', data)
        self.assertEqual(len(data['data']), 2)
        
        # Verify API was called
        mock_get.assert_called_once()

    @patch('src.acquisition.noaa_client.requests.get')
    def test_noaa_medium_forecast_collection(self, mock_get):
        """Test that medium-range (10-day) forecasts can be collected."""
        # Mock NOAA API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'forecast': {
                'data': [
                    {'validTime': f'2026-02-{3+i:02d}T00:00:00Z', 'flow': 100.0 + i}
                    for i in range(10)
                ],
                'rmse': 8.5
            }
        }
        mock_get.return_value = mock_response

        # Initialize client
        client = NOAAClient()
        
        # Fetch medium-range forecast
        data = client.get_forecast(
            hads_id=self.station.station_number,
            forecast_type='medium'
        )

        # Verify data was returned
        self.assertIsNotNone(data)
        self.assertIn('data', data)
        self.assertEqual(len(data['data']), 10)

    def test_forecast_run_storage(self):
        """Test that forecast runs can be stored with proper structure."""
        forecast_data = {
            'issue_time': '2026-02-03T08:30:00Z',
            'forecast_type': 'medium',
            'timeseries': [
                {'datetime': '2026-02-04T00:00:00Z', 'value': 100.0},
                {'datetime': '2026-02-05T00:00:00Z', 'value': 101.0}
            ]
        }
        
        forecast_run = ForecastRun.objects.create(
            station=self.station,
            source="NOAA_RFC",
            run_date=datetime(2026, 2, 3, 8, 30, tzinfo=timezone.utc),
            forecast_type="medium",
            data=forecast_data
        )
        
        # Verify storage
        self.assertIsNotNone(forecast_run.id)
        
        # Verify unique constraint (can't insert duplicate)
        with self.assertRaises(Exception):
            ForecastRun.objects.create(
                station=self.station,
                source="NOAA_RFC",
                run_date=datetime(2026, 2, 3, 8, 30, tzinfo=timezone.utc),
                forecast_type="medium",
                data=forecast_data
            )

    def test_append_strategy_preserves_historical_runs(self):
        """Test that append strategy preserves multiple forecast runs."""
        # Create first forecast run
        forecast1 = ForecastRun.objects.create(
            station=self.station,
            source="NOAA_RFC",
            run_date=datetime(2026, 2, 3, 8, 30, tzinfo=timezone.utc),
            forecast_type="medium",
            data={'issue_time': '2026-02-03T08:30:00Z', 'timeseries': []}
        )
        
        # Create second forecast run (next day)
        forecast2 = ForecastRun.objects.create(
            station=self.station,
            source="NOAA_RFC",
            run_date=datetime(2026, 2, 4, 8, 30, tzinfo=timezone.utc),
            forecast_type="medium",
            data={'issue_time': '2026-02-04T08:30:00Z', 'timeseries': []}
        )
        
        # Verify both runs are preserved
        total_runs = ForecastRun.objects.filter(
            station=self.station,
            forecast_type="medium"
        ).count()
        
        self.assertEqual(total_runs, 2, "Both forecast runs should be preserved")


class ConfigurationIntegrationTests(TestCase):
    """Integration tests for complete data collection workflows."""

    def test_all_configs_have_unique_names(self):
        """Verify no duplicate configuration names."""
        configs = PullConfiguration.objects.all()
        names = [config.name for config in configs]
        unique_names = set(names)
        
        self.assertEqual(
            len(names),
            len(unique_names),
            f"Found duplicate configuration names: {len(names)} total, {len(unique_names)} unique"
        )

    def test_schedule_values_are_valid_cron(self):
        """Verify all schedule values are valid cron expressions."""
        configs = PullConfiguration.objects.exclude(schedule_type='custom')
        
        for config in configs:
            # Basic validation: should have 5 parts (min hour day month dow)
            parts = config.schedule_value.strip().split()
            self.assertEqual(
                len(parts),
                5,
                f"Config '{config.name}' has invalid cron: '{config.schedule_value}'"
            )

    def test_data_strategies_match_data_types(self):
        """Verify data strategies are appropriate for data types."""
        configs = PullConfiguration.objects.all()
        
        for config in configs:
            # Forecasts should use append to preserve historical runs
            if config.data_type == 'forecast':
                self.assertEqual(
                    config.data_strategy,
                    'append',
                    f"Forecast config '{config.name}' should use 'append' strategy"
                )
            
            # Real-time data should use overwrite for storage management
            if config.data_type == 'realtime':
                self.assertEqual(
                    config.data_strategy,
                    'overwrite',
                    f"Real-time config '{config.name}' should use 'overwrite' strategy"
                )

    def test_nwrfc_stations_are_noaa_agency(self):
        """Verify all NWRFC stations have correct agency."""
        # Get NWRFC config
        config = PullConfiguration.objects.get(
            name="NWRFC Short-Range Forecast Collection"
        )
        
        station_numbers = config.configuration_stations.values_list(
            'station_number', flat=True
        )
        
        # Verify all are NOAA_RFC agency
        non_noaa = Station.objects.filter(
            station_number__in=station_numbers
        ).exclude(agency='NOAA_RFC').count()
        
        self.assertEqual(
            non_noaa,
            0,
            f"Found {non_noaa} NWRFC stations with non-NOAA_RFC agency"
        )

    def test_pnw_stations_are_usgs_agency(self):
        """Verify all PNW stations have correct agency."""
        # Get PNW config
        config = PullConfiguration.objects.get(
            name="PNW USGS Daily Mean Discharge"
        )
        
        station_numbers = config.configuration_stations.values_list(
            'station_number', flat=True
        )
        
        # Verify all are USGS agency
        non_usgs = Station.objects.filter(
            station_number__in=station_numbers
        ).exclude(agency='USGS').count()
        
        self.assertEqual(
            non_usgs,
            0,
            f"Found {non_usgs} PNW stations with non-USGS agency"
        )
