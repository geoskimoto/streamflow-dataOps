"""
API Tests for Streamflow DataOps REST API

Tests all API endpoints with real data from the database.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from datetime import datetime, timedelta
from django.utils import timezone

from apps.streamflow.models import (
    Station,
    PullConfiguration,
    DischargeObservation,
    ForecastRun,
    DataPullLog,
)


class APITestCase(TestCase):
    """Base test case with common setup."""
    
    def setUp(self):
        """Set up test client and sample data."""
        self.client = APIClient()
        
        # Create test station
        self.station = Station.objects.create(
            station_number='TEST001',
            name='Test Station',
            agency='USGS',
            latitude=40.0,
            longitude=-105.0,
            is_active=True
        )
        
        # Create test configuration
        self.config = PullConfiguration.objects.create(
            name='Test Config',
            data_source='USGS',
            data_type='daily_mean',
            data_strategy='append',
            pull_start_date=timezone.now() - timedelta(days=30),
            schedule_type='daily',
            is_enabled=True
        )
        
        # Create test observations
        self.observations = []
        base_date = timezone.now() - timedelta(days=5)
        for i in range(5):
            obs = DischargeObservation.objects.create(
                station=self.station,
                observed_at=base_date + timedelta(days=i),
                discharge=100.0 + i * 10,
                unit='cfs',
                type='daily_mean',
                quality_code='P'
            )
            self.observations.append(obs)
        
        # Create test forecast
        forecast_data = [
            {'date': (timezone.now() + timedelta(days=i)).isoformat(), 'value': 200.0 + i * 5}
            for i in range(10)
        ]
        self.forecast = ForecastRun.objects.create(
            station=self.station,
            source='NOAA_RFC',
            run_date=timezone.now(),
            data=forecast_data,
            rmse=5.5
        )
        
        # Create test log
        self.log = DataPullLog.objects.create(
            configuration=self.config,
            status='success',
            records_processed=100,
            start_time=timezone.now() - timedelta(hours=1),
            end_time=timezone.now()
        )


class StationAPITest(APITestCase):
    """Test Station API endpoints."""
    
    def test_list_stations(self):
        """Test listing all stations."""
        url = reverse('api:station-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertTrue(len(response.data['results']) > 0)
    
    def test_retrieve_station(self):
        """Test retrieving a specific station."""
        url = reverse('api:station-detail', args=[self.station.station_number])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['station_number'], 'TEST001')
        self.assertEqual(response.data['name'], 'Test Station')
        self.assertEqual(response.data['agency'], 'USGS')


class ObservationAPITest(APITestCase):
    """Test Discharge Observation API endpoints."""
    
    def test_list_observations(self):
        """Test listing all observations."""
        url = reverse('api:discharge-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
    
    def test_retrieve_observation(self):
        """Test retrieving a specific observation."""
        url = reverse('api:discharge-detail', args=[self.observations[0].id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['station_number'], 'TEST001')
        self.assertIn('discharge', response.data)
    
    def test_filter_observations_by_station(self):
        """Test filtering observations by station."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {'station_number': 'TEST001'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 5)
    
    def test_observation_statistics(self):
        """Test observation statistics endpoint."""
        url = reverse('api:discharge-statistics')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertGreater(response.data['count'], 0)


class ForecastAPITest(APITestCase):
    """Test Forecast API endpoints."""
    
    def test_list_forecasts(self):
        """Test listing all forecasts."""
        url = reverse('api:forecast-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertTrue(len(response.data['results']) > 0)
    
    def test_retrieve_forecast(self):
        """Test retrieving a specific forecast with full data."""
        url = reverse('api:forecast-detail', args=[self.forecast.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['station_number'], 'TEST001')
        self.assertEqual(response.data['source'], 'NOAA_RFC')
        self.assertIn('data', response.data)
        self.assertEqual(len(response.data['data']), 10)
    
    def test_filter_forecasts_by_station(self):
        """Test filtering forecasts by station number."""
        url = reverse('api:forecast-list')
        response = self.client.get(url, {'station_number': 'TEST001'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data['results']) > 0)
    
    def test_forecast_statistics(self):
        """Test forecast statistics endpoint."""
        url = reverse('api:forecast-statistics')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('total_forecast_points', response.data)
    
    def test_forecast_by_station(self):
        """Test getting forecasts for a specific station."""
        url = reverse('api:forecast-by-station', args=['TEST001'])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
    
    def test_latest_forecast(self):
        """Test getting the latest forecast."""
        url = reverse('api:forecast-latest')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('station_number', response.data)


class ConfigurationAPITest(APITestCase):
    """Test Pull Configuration API endpoints."""
    
    def test_list_configurations(self):
        """Test listing all configurations."""
        url = reverse('api:configuration-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
    
    def test_retrieve_configuration(self):
        """Test retrieving a specific configuration."""
        url = reverse('api:configuration-detail', args=[self.config.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Test Config')


class LogAPITest(APITestCase):
    """Test Data Pull Log API endpoints."""
    
    def test_list_logs(self):
        """Test listing all logs."""
        url = reverse('api:log-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
    
    def test_retrieve_log(self):
        """Test retrieving a specific log."""
        url = reverse('api:log-detail', args=[self.log.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'success')
        self.assertEqual(response.data['records_processed'], 100)


class RealDataAPITest(TestCase):
    """Test API with real data from the database."""
    
    def setUp(self):
        """Set up test client."""
        self.client = APIClient()
    
    def test_list_real_stations(self):
        """Test listing actual stations from database."""
        url = reverse('api:station-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if Station.objects.exists():
            self.assertGreater(len(response.data['results']), 0)
            # Check first station has required fields
            first_station = response.data['results'][0]
            self.assertIn('station_number', first_station)
            self.assertIn('name', first_station)
            self.assertIn('agency', first_station)
    
    def test_list_real_observations(self):
        """Test listing actual observations from database."""
        url = reverse('api:discharge-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if DischargeObservation.objects.exists():
            self.assertGreater(len(response.data['results']), 0)
            # Check observation structure
            first_obs = response.data['results'][0]
            self.assertIn('discharge', first_obs)
            self.assertIn('observed_at', first_obs)
            self.assertIn('station_number', first_obs)
    
    def test_list_real_forecasts(self):
        """Test listing actual forecasts from database."""
        url = reverse('api:forecast-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        if ForecastRun.objects.exists():
            self.assertGreater(len(response.data['results']), 0)
            # Check forecast structure (list view - no full data)
            first_forecast = response.data['results'][0]
            self.assertIn('station_number', first_forecast)
            self.assertIn('run_date', first_forecast)
            self.assertIn('forecast_point_count', first_forecast)
    
    def test_retrieve_real_forecast_with_data(self):
        """Test retrieving a real forecast with full data array."""
        # Get first forecast
        forecast = ForecastRun.objects.first()
        if not forecast:
            self.skipTest('No forecasts in database')
        
        url = reverse('api:forecast-detail', args=[forecast.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.data)
        self.assertIsInstance(response.data['data'], list)
        if response.data['data']:
            # Check data point structure
            first_point = response.data['data'][0]
            self.assertIn('date', first_point)
            self.assertIn('value', first_point)
    
    def test_real_observation_statistics(self):
        """Test observation statistics with real data."""
        if not DischargeObservation.objects.exists():
            self.skipTest('No observations in database')
        
        url = reverse('api:discharge-statistics')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(response.data['count'], 0)
    
    def test_real_forecast_statistics(self):
        """Test forecast statistics with real data."""
        if not ForecastRun.objects.exists():
            self.skipTest('No forecasts in database')
        
        url = reverse('api:forecast-statistics')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(response.data['count'], 0)
        self.assertGreater(response.data['total_forecast_points'], 0)
    
    def test_filter_real_data_by_station(self):
        """Test filtering real observations by station."""
        # Get a station with observations
        station = Station.objects.filter(
            discharge_observations__isnull=False
        ).first()
        
        if not station:
            self.skipTest('No stations with observations')
        
        url = reverse('api:discharge-list')
        response = self.client.get(url, {'station_number': station.station_number})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data['results']), 0)
        # Verify all returned observations are for the requested station
        for obs in response.data['results']:
            self.assertEqual(obs['station_number'], station.station_number)
    
    def test_api_documentation_accessible(self):
        """Test that API documentation is accessible."""
        swagger_url = reverse('api:swagger-ui')
        redoc_url = reverse('api:redoc')
        schema_url = reverse('api:schema')
        
        # These should all return 200
        self.assertEqual(self.client.get(swagger_url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(redoc_url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(schema_url).status_code, status.HTTP_200_OK)
