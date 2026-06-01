"""
Comprehensive tests for Forecast API endpoints.

Tests include latest forecast, by-station queries, filtering, and error handling.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from datetime import datetime, timedelta
from django.utils import timezone

from apps.streamflow.models import Station, ForecastRun


class ForecastLatestEndpointTest(TestCase):
    """Test the latest forecast endpoint."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        # Create test stations
        self.station1 = Station.objects.create(
            station_number='FCST_01',
            name='Forecast Test Station 1',
            agency='NOAA_RFC',
        )
        
        self.station2 = Station.objects.create(
            station_number='FCST_02',
            name='Forecast Test Station 2',
            agency='NOAA_RFC',
        )
        
        # Create older forecast
        ForecastRun.objects.create(
            station=self.station1,
            source='NOAA_RFC',
            run_date=timezone.now() - timedelta(days=2),
            forecast_type='short',
            data=[
                {'date': '2026-02-01T00:00:00Z', 'value': 100.0},
                {'date': '2026-02-02T00:00:00Z', 'value': 110.0},
            ]
        )
        
        # Create latest forecast
        self.latest_forecast = ForecastRun.objects.create(
            station=self.station1,
            source='NOAA_RFC',
            run_date=timezone.now(),
            forecast_type='short',
            data=[
                {'date': '2026-02-04T00:00:00Z', 'value': 200.0},
                {'date': '2026-02-05T00:00:00Z', 'value': 210.0},
            ]
        )
    
    def test_latest_forecast_returns_most_recent(self):
        """Test that latest endpoint returns the most recent forecast."""
        url = reverse('api:forecast-latest')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.latest_forecast.id)
        self.assertEqual(response.data['station_number'], 'FCST_01')
    
    def test_latest_forecast_includes_full_data(self):
        """Test that latest forecast includes full data array."""
        url = reverse('api:forecast-latest')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('data', response.data)
        self.assertIsInstance(response.data['data'], list)
        self.assertEqual(len(response.data['data']), 2)
        self.assertEqual(response.data['data'][0]['value'], 200.0)
    
    def test_latest_forecast_with_no_forecasts(self):
        """Test latest forecast when no forecasts exist."""
        # Delete all forecasts
        ForecastRun.objects.all().delete()
        
        url = reverse('api:forecast-latest')
        response = self.client.get(url)
        
        # Should return 404 or empty response
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_204_NO_CONTENT])


class ForecastByStationEndpointTest(TestCase):
    """Test the by-station forecast endpoint."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        # Create test station
        self.station = Station.objects.create(
            station_number='FCST_STATION_01',
            name='Forecast Station Test',
            agency='NOAA_RFC',
        )
        
        # Create another station
        self.other_station = Station.objects.create(
            station_number='FCST_STATION_02',
            name='Other Station',
            agency='NOAA_RFC',
        )
        
        # Create multiple forecasts for main station
        for i in range(5):
            ForecastRun.objects.create(
                station=self.station,
                source='NOAA_RFC',
                run_date=timezone.now() - timedelta(days=i),
                forecast_type='short',
                data=[{'date': f'2026-02-0{i+1}T00:00:00Z', 'value': 100.0 + i * 10}]
            )
        
        # Create forecast for other station
        ForecastRun.objects.create(
            station=self.other_station,
            source='NOAA_RFC',
            run_date=timezone.now(),
            forecast_type='short',
            data=[{'date': '2026-02-04T00:00:00Z', 'value': 500.0}]
        )
    
    def test_by_station_returns_only_station_forecasts(self):
        """Test that by-station endpoint returns only that station's forecasts."""
        url = reverse('api:forecast-by-station', args=['FCST_STATION_01'])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        
        # Should have 5 forecasts for this station
        self.assertEqual(len(response.data['results']), 5)
        
        # All should be for the requested station
        for forecast in response.data['results']:
            self.assertEqual(forecast['station_number'], 'FCST_STATION_01')
    
    def test_by_station_ordered_by_run_date(self):
        """Test that by-station forecasts are ordered by run_date descending."""
        url = reverse('api:forecast-by-station', args=['FCST_STATION_01'])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        run_dates = [f['run_date'] for f in response.data['results']]
        self.assertEqual(run_dates, sorted(run_dates, reverse=True))
    
    def test_by_station_nonexistent_station(self):
        """Test by-station endpoint with nonexistent station."""
        url = reverse('api:forecast-by-station', args=['NONEXISTENT'])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)


class ForecastFilteringTest(TestCase):
    """Test filtering options for forecast endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.station = Station.objects.create(
            station_number='FCST_FILTER_01',
            name='Filter Test Station',
            agency='NOAA_RFC',
        )
        
        # Create forecasts with different sources and types
        ForecastRun.objects.create(
            station=self.station,
            source='NOAA_RFC',
            run_date=timezone.now() - timedelta(days=5),
            forecast_type='short',
            data=[{'date': '2026-02-01T00:00:00Z', 'value': 100.0}]
        )
        
        ForecastRun.objects.create(
            station=self.station,
            source='NOAA_RFC',
            run_date=timezone.now() - timedelta(days=2),
            forecast_type='medium',
            data=[{'date': '2026-02-02T00:00:00Z', 'value': 150.0}]
        )
        
        ForecastRun.objects.create(
            station=self.station,
            source='NOAA_RFC',
            run_date=timezone.now(),
            forecast_type='short',
            data=[{'date': '2026-02-04T00:00:00Z', 'value': 200.0}]
        )
    
    def test_filter_by_source(self):
        """Test filtering forecasts by source."""
        url = reverse('api:forecast-list')
        response = self.client.get(url, {
            'station_number': 'FCST_FILTER_01',
            'source': 'NOAA_RFC'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 3)
    
    def test_filter_by_forecast_type(self):
        """Test filtering forecasts by forecast type."""
        url = reverse('api:forecast-list')
        response = self.client.get(url, {
            'station_number': 'FCST_FILTER_01',
            'forecast_type': 'short'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have 2 short-range forecasts
        self.assertEqual(len(response.data['results']), 2)
        
        for forecast in response.data['results']:
            self.assertEqual(forecast.get('forecast_type'), 'short')
    
    def test_filter_by_start_date(self):
        """Test filtering forecasts by start date."""
        url = reverse('api:forecast-list')
        start_date = (timezone.now() - timedelta(days=3)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'FCST_FILTER_01',
            'start_date': start_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have 2 forecasts (within last 3 days)
        self.assertEqual(len(response.data['results']), 2)
    
    def test_filter_by_end_date(self):
        """Test filtering forecasts by end date."""
        url = reverse('api:forecast-list')
        end_date = (timezone.now() - timedelta(days=3)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'FCST_FILTER_01',
            'end_date': end_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have 1 forecast (older than 3 days)
        self.assertEqual(len(response.data['results']), 1)
    
    def test_filter_by_date_range(self):
        """Test filtering forecasts by date range."""
        url = reverse('api:forecast-list')
        start_date = (timezone.now() - timedelta(days=4)).isoformat()
        end_date = (timezone.now() - timedelta(days=1)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'FCST_FILTER_01',
            'start_date': start_date,
            'end_date': end_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have 1 forecast in the middle
        self.assertEqual(len(response.data['results']), 1)


class ForecastStatisticsTest(TestCase):
    """Test forecast statistics endpoint."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.station = Station.objects.create(
            station_number='FCST_STATS_01',
            name='Statistics Test Station',
            agency='NOAA_RFC',
        )
        
        # Create forecasts with varying data
        for i in range(5):
            ForecastRun.objects.create(
                station=self.station,
                source='NOAA_RFC',
                run_date=timezone.now() - timedelta(days=i),
                forecast_type='short',
                rmse=float(5 + i),
                data=[
                    {'date': f'2026-02-0{j+1}T00:00:00Z', 'value': 100.0 + j * 10}
                    for j in range(10)  # 10 forecast points each
                ]
            )
    
    def test_statistics_calculation(self):
        """Test that forecast statistics are calculated correctly."""
        url = reverse('api:forecast-statistics')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Should have stats for all forecasts
        self.assertIn('count', response.data)
        self.assertIn('total_forecast_points', response.data)
        self.assertGreaterEqual(response.data['count'], 5)
        self.assertGreaterEqual(response.data['total_forecast_points'], 50)
    
    def test_statistics_with_source_filter(self):
        """Test statistics with source filtering."""
        url = reverse('api:forecast-statistics')
        response = self.client.get(url, {'source': 'NOAA_RFC'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(response.data['count'], 0)


class ForecastResponseFormatTest(TestCase):
    """Test forecast response format and data structure."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.station = Station.objects.create(
            station_number='FCST_FORMAT_01',
            name='Format Test Station',
            agency='NOAA_RFC',
        )
        
        self.forecast = ForecastRun.objects.create(
            station=self.station,
            source='NOAA_RFC',
            run_date=timezone.now(),
            forecast_type='short',
            rmse=5.5,
            data=[
                {'date': '2026-02-05T00:00:00Z', 'value': 1820.0},
                {'date': '2026-02-06T00:00:00Z', 'value': 1850.0},
                {'date': '2026-02-07T00:00:00Z', 'value': 1880.0},
            ]
        )
    
    def test_list_response_lightweight(self):
        """Test that list response uses lightweight serializer."""
        url = reverse('api:forecast-list')
        response = self.client.get(url, {'station_number': 'FCST_FORMAT_01'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        forecast = response.data['results'][0]
        
        # Should have basic fields
        self.assertIn('id', forecast)
        self.assertIn('station_number', forecast)
        self.assertIn('source', forecast)
        self.assertIn('run_date', forecast)
        self.assertIn('forecast_type', forecast)
        self.assertIn('forecast_point_count', forecast)
        
        # Should NOT have full data array in list view
        self.assertNotIn('data', forecast)
    
    def test_detail_response_includes_full_data(self):
        """Test that detail response includes full data array."""
        url = reverse('api:forecast-detail', args=[self.forecast.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Should have full data array
        self.assertIn('data', response.data)
        self.assertIsInstance(response.data['data'], list)
        self.assertEqual(len(response.data['data']), 3)
        
        # Check data point structure
        first_point = response.data['data'][0]
        self.assertIn('date', first_point)
        self.assertIn('value', first_point)
        self.assertEqual(first_point['value'], 1820.0)
    
    def test_forecast_point_count_accuracy(self):
        """Test that forecast_point_count is accurate."""
        url = reverse('api:forecast-list')
        response = self.client.get(url, {'station_number': 'FCST_FORMAT_01'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        forecast = response.data['results'][0]
        
        self.assertEqual(forecast['forecast_point_count'], 3)


class ForecastErrorHandlingTest(TestCase):
    """Test error handling for forecast endpoints."""
    
    def setUp(self):
        """Set up test client."""
        self.client = APIClient()
    
    def test_retrieve_nonexistent_forecast(self):
        """Test retrieving forecast that doesn't exist."""
        url = reverse('api:forecast-detail', args=[99999])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_by_station_invalid_station(self):
        """Test by-station with invalid station number."""
        url = reverse('api:forecast-by-station', args=['INVALID_123'])
        response = self.client.get(url)
        
        # Should return empty results, not error
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)
    
    def test_statistics_with_no_forecasts(self):
        """Test statistics endpoint with no forecast data."""
        url = reverse('api:forecast-statistics')
        response = self.client.get(url, {'source': 'NONEXISTENT_SOURCE'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)


class ForecastPaginationTest(TestCase):
    """Test pagination for forecast endpoints."""

    def setUp(self):
        """Set up test data."""
        self.client = APIClient()

        self.station = Station.objects.create(
            station_number='FCST_PAGE_01',
            name='Pagination Test Station',
            agency='NOAA_RFC',
        )

        # Create 50 forecasts
        for i in range(50):
            ForecastRun.objects.create(
                station=self.station,
                source='NOAA_RFC',
                run_date=timezone.now() - timedelta(days=i),
                forecast_type='short',
                data=[{'date': f'2026-02-04T00:00:00Z', 'value': 100.0}]
            )

    def test_forecast_pagination(self):
        """Test that forecast list is paginated."""
        url = reverse('api:forecast-list')
        response = self.client.get(url, {'station_number': 'FCST_PAGE_01'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)

        # Should have 50 total, but paginated results
        self.assertEqual(response.data['count'], 50)
        self.assertLess(len(response.data['results']), 50)


class ForecastRunNwrfcWebModelTest(TestCase):
    """Test ForecastRun model supports nwrfc_web source and is_forecast field."""

    def setUp(self):
        self.station = Station.objects.create(
            station_number='REVQ2',
            name='Revelstoke Web Test',
            agency='NOAA_RFC',
        )

    def test_nwrfc_web_source_accepted(self):
        run = ForecastRun(
            station=self.station,
            source='nwrfc_web',
            run_date=timezone.now(),
            forecast_type='medium',
            is_forecast=True,
            data=[{'date': '2026-06-02T00:00:00Z', 'value': 5000.0}],
        )
        run.full_clean()  # raises if 'nwrfc_web' is not a valid choice
        run.save()
        self.assertEqual(ForecastRun.objects.filter(source='nwrfc_web').count(), 1)

    def test_two_records_per_scrape_observed_and_forecast(self):
        """Observed (is_forecast=False) and forecast (is_forecast=True) can coexist."""
        now = timezone.now()
        ForecastRun.objects.create(
            station=self.station, source='nwrfc_web', run_date=now,
            forecast_type='medium', is_forecast=False,
            data=[{'date': '2026-06-01T18:00:00Z', 'value': 4800.0}],
        )
        ForecastRun.objects.create(
            station=self.station, source='nwrfc_web', run_date=now,
            forecast_type='medium', is_forecast=True,
            data=[{'date': '2026-06-02T00:00:00Z', 'value': 5100.0}],
        )
        self.assertEqual(ForecastRun.objects.filter(source='nwrfc_web').count(), 2)
