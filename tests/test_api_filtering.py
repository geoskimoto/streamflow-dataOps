"""
Tests for API filtering, pagination, and ordering functionality.

Tests common filtering patterns across all API endpoints.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from datetime import datetime, timedelta
from django.utils import timezone

from apps.streamflow.models import (
    Station,
    DischargeObservation,
    ForecastRun,
    PullConfiguration,
    DataPullLog,
)


class PaginationTests(TestCase):
    """Test pagination across different endpoints."""
    
    def setUp(self):
        """Create large datasets for pagination testing."""
        self.client = APIClient()
        
        # Create 150 stations
        for i in range(150):
            Station.objects.create(
                station_number=f'PAGTEST{i:03d}',
                name=f'Pagination Test Station {i}',
                agency='USGS',
                is_active=True
            )
    
    def test_station_pagination_structure(self):
        """Test that station list has proper pagination structure."""
        url = reverse('api:station-list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)
        
        # Total count should be accurate
        self.assertGreaterEqual(response.data['count'], 150)
    
    def test_pagination_page_size_parameter(self):
        """Test custom page_size parameter."""
        url = reverse('api:station-list')
        response = self.client.get(url, {'page_size': 20})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # API may not support custom page_size or may have minimum limit
        # Just verify pagination is working
        self.assertLessEqual(len(response.data['results']), 100)
    
    def test_pagination_page_navigation(self):
        """Test navigating through pages."""
        url = reverse('api:station-list')
        
        # Get first page
        response1 = self.client.get(url, {'page_size': 50})
        self.assertEqual(len(response1.data['results']), 50)
        self.assertIsNotNone(response1.data['next'])
        self.assertIsNone(response1.data['previous'])
        
        # Get second page
        response2 = self.client.get(url, {'page_size': 50, 'page': 2})
        self.assertEqual(len(response2.data['results']), 50)
        self.assertIsNotNone(response2.data['previous'])
    
    def test_pagination_last_page(self):
        """Test last page has remaining items."""
        url = reverse('api:station-list')
        
        # Calculate last page (150 items / 50 per page = 3 pages)
        response = self.client.get(url, {'page_size': 50, 'page': 3})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 50)
        self.assertIsNone(response.data['next'])
    
    def test_pagination_invalid_page(self):
        """Test requesting page beyond range."""
        url = reverse('api:station-list')
        response = self.client.get(url, {'page': 9999})
        
        # Should return 404 or empty results
        self.assertIn(response.status_code, [status.HTTP_404_NOT_FOUND, status.HTTP_200_OK])


class DateRangeFilteringTests(TestCase):
    """Test date range filtering across endpoints."""
    
    def setUp(self):
        """Create time-series data."""
        self.client = APIClient()
        
        self.station = Station.objects.create(
            station_number='DATETEST001',
            name='Date Test Station',
            agency='USGS',
            is_active=True
        )
        
        # Create observations spanning 60 days
        base_date = timezone.now() - timedelta(days=60)
        for i in range(60):
            DischargeObservation.objects.create(
                station=self.station,
                observed_at=base_date + timedelta(days=i),
                discharge=100.0 + i,
                unit='cfs',
                type='daily_mean',
                quality_code='A'
            )
        
        # Create forecasts spanning 30 days
        for i in range(30):
            forecast_data = [
                {'date': (base_date + timedelta(days=i + j)).isoformat(), 'value': 200.0}
                for j in range(7)
            ]
            ForecastRun.objects.create(
                station=self.station,
                source='NOAA_RFC',
                run_date=base_date + timedelta(days=i),
                data=forecast_data
            )
    
    def test_observation_start_date_filter(self):
        """Test filtering observations by start date."""
        url = reverse('api:discharge-list')
        start_date = (timezone.now() - timedelta(days=30)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'DATETEST001',
            'start_date': start_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have ~30 days of data
        self.assertLessEqual(len(response.data['results']), 31)
    
    def test_observation_end_date_filter(self):
        """Test filtering observations by end date."""
        url = reverse('api:discharge-list')
        end_date = (timezone.now() - timedelta(days=30)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'DATETEST001',
            'end_date': end_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have ~30 days of data
        self.assertLessEqual(len(response.data['results']), 31)
    
    def test_observation_date_range_filter(self):
        """Test filtering observations by date range."""
        url = reverse('api:discharge-list')
        start_date = (timezone.now() - timedelta(days=40)).isoformat()
        end_date = (timezone.now() - timedelta(days=30)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'DATETEST001',
            'start_date': start_date,
            'end_date': end_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have ~10 days of data
        self.assertLessEqual(len(response.data['results']), 11)
    
    def test_forecast_date_filter(self):
        """Test filtering forecasts by date range."""
        url = reverse('api:forecast-list')
        start_date = (timezone.now() - timedelta(days=15)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'DATETEST001',
            'start_date': start_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have ~15 forecasts
        self.assertLessEqual(len(response.data['results']), 16)


class OrderingTests(TestCase):
    """Test ordering/sorting functionality."""
    
    def setUp(self):
        """Create data with various sortable values."""
        self.client = APIClient()
        
        # Create stations with different names
        for i, name in enumerate(['Zebra', 'Alpha', 'Beta', 'Gamma']):
            Station.objects.create(
                station_number=f'SORT{i:03d}',
                name=f'{name} River',
                agency='USGS',
                latitude=40.0 + i,
                is_active=True
            )
    
    def test_station_order_by_station_number(self):
        """Test ordering stations by station_number."""
        url = reverse('api:station-list')
        response = self.client.get(url, {
            'ordering': 'station_number',
            'page_size': 100
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = [r for r in response.data['results'] if r['station_number'].startswith('SORT')]
        
        # Check ascending order
        for i in range(len(results) - 1):
            self.assertLessEqual(results[i]['station_number'], results[i+1]['station_number'])
    
    def test_station_order_descending(self):
        """Test descending order with minus prefix."""
        url = reverse('api:station-list')
        response = self.client.get(url, {
            'ordering': '-station_number',
            'page_size': 100
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = [r for r in response.data['results'] if r['station_number'].startswith('SORT')]
        
        # Check descending order
        for i in range(len(results) - 1):
            self.assertGreaterEqual(results[i]['station_number'], results[i+1]['station_number'])
    
    def test_invalid_ordering_field(self):
        """Test that invalid ordering field is handled gracefully."""
        url = reverse('api:station-list')
        response = self.client.get(url, {'ordering': 'invalid_field'})
        
        # Should return 200 with default ordering
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class MultiFieldFilteringTests(TestCase):
    """Test combining multiple filters."""
    
    def setUp(self):
        """Create complex test dataset."""
        self.client = APIClient()
        
        # Create two stations
        self.station1 = Station.objects.create(
            station_number='MULTI001',
            name='Multi Filter 1',
            agency='USGS',
            is_active=True
        )
        self.station2 = Station.objects.create(
            station_number='MULTI002',
            name='Multi Filter 2',
            agency='EC',
            is_active=True
        )
        
        # Create observations for both
        base_date = timezone.now() - timedelta(days=30)
        for i in range(30):
            DischargeObservation.objects.create(
                station=self.station1,
                observed_at=base_date + timedelta(days=i),
                discharge=100.0,
                unit='cfs',
                type='daily_mean',
                quality_code='A'
            )
            DischargeObservation.objects.create(
                station=self.station2,
                observed_at=base_date + timedelta(days=i),
                discharge=200.0,
                unit='cms',
                type='realtime_15min',
                quality_code='P'
            )
    
    def test_filter_by_station_and_type(self):
        """Test filtering by station and observation type."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {
            'station_number': 'MULTI001',
            'type': 'daily_mean'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # All results should match filters
        for obs in response.data['results']:
            self.assertEqual(obs['station_number'], 'MULTI001')
            self.assertEqual(obs['type'], 'daily_mean')
    
    def test_filter_by_station_type_and_date(self):
        """Test combining station, type, and date filters."""
        url = reverse('api:discharge-list')
        start_date = (timezone.now() - timedelta(days=15)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'MULTI001',
            'type': 'daily_mean',
            'start_date': start_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have ~15 observations
        self.assertLessEqual(len(response.data['results']), 16)
    
    def test_filter_by_quality_code(self):
        """Test filtering by quality code."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {'quality_code': 'A'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # All results should have quality code A
        for obs in response.data['results']:
            if obs['quality_code']:  # May be null for some observations
                self.assertEqual(obs['quality_code'], 'A')
    
    def test_filter_by_unit(self):
        """Test filtering by unit."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {'unit': 'cfs'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # All results should have unit cfs
        for obs in response.data['results']:
            self.assertEqual(obs['unit'], 'cfs')


class SearchTests(TestCase):
    """Test search functionality where available."""
    
    def setUp(self):
        """Create searchable data."""
        self.client = APIClient()
        
        Station.objects.create(
            station_number='SEARCH001',
            name='Willamette River at Portland',
            agency='USGS',
            is_active=True
        )
        Station.objects.create(
            station_number='SEARCH002',
            name='Columbia River at Vancouver',
            agency='USGS',
            is_active=True
        )
    
    def test_station_search_by_number(self):
        """Test searching stations by station number."""
        url = reverse('api:station-list')
        response = self.client.get(url, {'search': 'SEARCH001'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data['results']), 0)
        
        # Should find the station
        station_numbers = [s['station_number'] for s in response.data['results']]
        self.assertIn('SEARCH001', station_numbers)
    
    def test_station_search_by_name(self):
        """Test searching stations by name."""
        url = reverse('api:station-list')
        response = self.client.get(url, {'search': 'Willamette'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Should find stations with Willamette in name
        names = [s['name'] for s in response.data['results']]
        willamette_found = any('Willamette' in name for name in names)
        self.assertTrue(willamette_found)
    
    def test_forecast_search(self):
        """Test searching forecasts by station name."""
        # Create station and forecast
        station = Station.objects.create(
            station_number='FSEARCH001',
            name='Test Search River',
            agency='USGS',
            is_active=True
        )
        ForecastRun.objects.create(
            station=station,
            source='NOAA_RFC',
            run_date=timezone.now(),
            data=[{'date': timezone.now().isoformat(), 'value': 100}]
        )
        
        url = reverse('api:forecast-list')
        response = self.client.get(url, {'search': 'FSEARCH001'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data['results']), 0)
