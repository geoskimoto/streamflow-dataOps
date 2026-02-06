"""
Comprehensive tests for Discharge Observation API endpoints.

Tests include CSV export, date filtering, pagination, and error handling.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from datetime import datetime, timedelta
from django.utils import timezone
import csv
from io import StringIO

from apps.streamflow.models import Station, DischargeObservation


class ObservationCSVExportTest(TestCase):
    """Test CSV export functionality for observations."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        # Create test station
        self.station = Station.objects.create(
            station_number='TEST_CSV_01',
            name='Test CSV Station',
            agency='USGS',
            latitude=40.0,
            longitude=-105.0,
        )
        
        # Create observations spanning multiple days
        base_date = timezone.now() - timedelta(days=10)
        for i in range(20):
            DischargeObservation.objects.create(
                station=self.station,
                observed_at=base_date + timedelta(days=i, hours=i),
                discharge=100.0 + i * 5,
                unit='cfs',
                type='daily_mean',
                quality_code='P'
            )
    
    def test_csv_export_requires_station_number(self):
        """Test that CSV export requires station_number parameter."""
        url = reverse('api:discharge-export-csv')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertIn('station_number', response.data['error'])
    
    def test_csv_export_success(self):
        """Test successful CSV export."""
        url = reverse('api:discharge-export-csv')
        response = self.client.get(url, {'station_number': 'TEST_CSV_01'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('TEST_CSV_01', response['Content-Disposition'])
    
    def test_csv_export_content_format(self):
        """Test CSV export content and format."""
        url = reverse('api:discharge-export-csv')
        response = self.client.get(url, {'station_number': 'TEST_CSV_01'})
        
        # Parse CSV content
        content = response.content.decode('utf-8')
        csv_reader = csv.reader(StringIO(content))
        rows = list(csv_reader)
        
        # Check header
        self.assertIn('Station Number', rows[0])
        self.assertIn('Observed At', rows[0])
        self.assertIn('Discharge', rows[0])
        self.assertIn('Unit', rows[0])
        
        # Check data rows (20 observations + 1 header)
        self.assertEqual(len(rows), 21)
        
        # Check first data row
        self.assertEqual(rows[1][0], 'TEST_CSV_01')
        self.assertIn('cfs', rows[1][3])
    
    def test_csv_export_with_date_filtering(self):
        """Test CSV export with date range filters."""
        url = reverse('api:discharge-export-csv')
        start_date = (timezone.now() - timedelta(days=5)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'TEST_CSV_01',
            'start_date': start_date
        })
        
        content = response.content.decode('utf-8')
        csv_reader = csv.reader(StringIO(content))
        rows = list(csv_reader)
        
        # Should have fewer rows due to date filter
        self.assertLess(len(rows), 21)
        self.assertGreater(len(rows), 1)
    
    def test_csv_export_nonexistent_station(self):
        """Test CSV export for station that doesn't exist."""
        url = reverse('api:discharge-export-csv')
        response = self.client.get(url, {'station_number': 'NONEXISTENT'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return empty CSV with just headers
        content = response.content.decode('utf-8')
        csv_reader = csv.reader(StringIO(content))
        rows = list(csv_reader)
        self.assertEqual(len(rows), 1)  # Only header


class ObservationDateFilteringTest(TestCase):
    """Test date range filtering for observations."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.station = Station.objects.create(
            station_number='TEST_FILTER_01',
            name='Test Filter Station',
            agency='USGS',
            latitude=40.0,
            longitude=-105.0,
        )
        
        # Create observations across 30 days
        base_date = timezone.now() - timedelta(days=30)
        self.observations = []
        for i in range(30):
            obs = DischargeObservation.objects.create(
                station=self.station,
                observed_at=base_date + timedelta(days=i),
                discharge=100.0 + i,
                unit='cfs',
                type='realtime_15min',
                quality_code='A'
            )
            self.observations.append(obs)
    
    def test_filter_by_start_date(self):
        """Test filtering observations by start date."""
        url = reverse('api:discharge-list')
        start_date = (timezone.now() - timedelta(days=10)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'TEST_FILTER_01',
            'start_date': start_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        
        # Should have ~10 days of observations
        self.assertGreater(len(results), 8)
        self.assertLess(len(results), 12)
    
    def test_filter_by_end_date(self):
        """Test filtering observations by end date."""
        url = reverse('api:discharge-list')
        end_date = (timezone.now() - timedelta(days=20)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'TEST_FILTER_01',
            'end_date': end_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        
        # Should have ~10 days of observations
        self.assertGreater(len(results), 8)
        self.assertLess(len(results), 12)
    
    def test_filter_by_date_range(self):
        """Test filtering observations by both start and end date."""
        url = reverse('api:discharge-list')
        start_date = (timezone.now() - timedelta(days=15)).isoformat()
        end_date = (timezone.now() - timedelta(days=10)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'TEST_FILTER_01',
            'start_date': start_date,
            'end_date': end_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        
        # Should have ~5 days of observations
        self.assertGreater(len(results), 3)
        self.assertLess(len(results), 7)
    
    def test_invalid_date_format(self):
        """Test handling of invalid date formats."""
        url = reverse('api:discharge-list')
        
        # Should not crash, just ignore invalid date
        response = self.client.get(url, {
            'station_number': 'TEST_FILTER_01',
            'start_date': 'invalid-date'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ObservationPaginationTest(TestCase):
    """Test pagination for observation endpoints."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.station = Station.objects.create(
            station_number='TEST_PAGE_01',
            name='Test Pagination Station',
            agency='USGS',
            latitude=40.0,
            longitude=-105.0,
        )
        
        # Create 100 observations
        base_date = timezone.now() - timedelta(days=100)
        for i in range(100):
            DischargeObservation.objects.create(
                station=self.station,
                observed_at=base_date + timedelta(days=i),
                discharge=100.0 + i,
                unit='cfs',
                type='realtime_15min',
                quality_code='P'
            )
    
    def test_default_pagination(self):
        """Test default pagination settings."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {'station_number': 'TEST_PAGE_01'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)
        self.assertIn('results', response.data)
        
        # Default page size should be less than total
        self.assertEqual(response.data['count'], 100)
        self.assertLess(len(response.data['results']), 100)
    
    def test_pagination_page_parameter(self):
        """Test pagination with page parameter."""
        url = reverse('api:discharge-list')
        
        # Get first page
        response1 = self.client.get(url, {
            'station_number': 'TEST_PAGE_01',
            'page': 1
        })
        
        # Get second page
        response2 = self.client.get(url, {
            'station_number': 'TEST_PAGE_01',
            'page': 2
        })
        
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        
        # Results should be different
        first_ids = [r['id'] for r in response1.data['results']]
        second_ids = [r['id'] for r in response2.data['results']]
        
        self.assertEqual(len(set(first_ids) & set(second_ids)), 0)
    
    def test_pagination_count_accuracy(self):
        """Test that pagination count is accurate."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {'station_number': 'TEST_PAGE_01'})
        
        self.assertEqual(response.data['count'], 100)


class ObservationStatisticsTest(TestCase):
    """Test statistics endpoint for observations."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.station = Station.objects.create(
            station_number='TEST_STATS_01',
            name='Test Statistics Station',
            agency='USGS',
            latitude=40.0,
            longitude=-105.0,
        )
        
        # Create observations with known statistics
        base_date = timezone.now() - timedelta(days=10)
        values = [50, 100, 150, 200, 250]  # Mean = 150, Min = 50, Max = 250
        for i, value in enumerate(values):
            DischargeObservation.objects.create(
                station=self.station,
                observed_at=base_date + timedelta(days=i),
                discharge=value,
                unit='cfs',
                type='daily_mean',
                quality_code='A'
            )
    
    def test_statistics_calculation(self):
        """Test that statistics are calculated correctly."""
        url = reverse('api:discharge-statistics')
        response = self.client.get(url, {'station_number': 'TEST_STATS_01'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.assertEqual(response.data['count'], 5)
        self.assertEqual(response.data['min_value'], 50.0)
        self.assertEqual(response.data['max_value'], 250.0)
        self.assertEqual(response.data['mean_value'], 150.0)
    
    def test_statistics_with_date_filter(self):
        """Test statistics with date range filtering."""
        url = reverse('api:discharge-statistics')
        start_date = (timezone.now() - timedelta(days=8)).isoformat()
        
        response = self.client.get(url, {
            'station_number': 'TEST_STATS_01',
            'start_date': start_date
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should have fewer observations in stats
        self.assertLess(response.data['count'], 5)


class ObservationErrorHandlingTest(TestCase):
    """Test error handling for observation endpoints."""
    
    def setUp(self):
        """Set up test client."""
        self.client = APIClient()
    
    def test_retrieve_nonexistent_observation(self):
        """Test retrieving observation that doesn't exist."""
        url = reverse('api:discharge-detail', args=[99999])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_filter_nonexistent_station(self):
        """Test filtering by station that doesn't exist."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {'station_number': 'NONEXISTENT'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 0)
    
    def test_statistics_empty_result(self):
        """Test statistics with no matching data."""
        url = reverse('api:discharge-statistics')
        response = self.client.get(url, {'station_number': 'NONEXISTENT'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertIsNone(response.data['min_value'])
        self.assertIsNone(response.data['max_value'])


class ObservationOrderingTest(TestCase):
    """Test ordering functionality for observations."""
    
    def setUp(self):
        """Set up test data."""
        self.client = APIClient()
        
        self.station = Station.objects.create(
            station_number='TEST_ORDER_01',
            name='Test Ordering Station',
            agency='USGS',
        )
        
        # Create observations with varying discharge values
        base_date = timezone.now() - timedelta(days=5)
        for i, discharge in enumerate([150, 50, 200, 100, 250]):
            DischargeObservation.objects.create(
                station=self.station,
                observed_at=base_date + timedelta(days=i),
                discharge=discharge,
                unit='cfs',
                type='realtime_15min',
            )
    
    def test_default_ordering(self):
        """Test default ordering (by observed_at descending)."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {'station_number': 'TEST_ORDER_01'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        
        # Should be ordered by observed_at descending (newest first)
        dates = [r['observed_at'] for r in results]
        self.assertEqual(dates, sorted(dates, reverse=True))
    
    def test_order_by_discharge(self):
        """Test ordering by discharge value."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {
            'station_number': 'TEST_ORDER_01',
            'ordering': 'discharge'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        
        # Should be ordered by discharge ascending
        discharges = [float(r['discharge']) for r in results]
        self.assertEqual(discharges, sorted(discharges))
    
    def test_order_by_discharge_descending(self):
        """Test ordering by discharge descending."""
        url = reverse('api:discharge-list')
        response = self.client.get(url, {
            'station_number': 'TEST_ORDER_01',
            'ordering': '-discharge'
        })
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data['results']
        
        # Should be ordered by discharge descending
        discharges = [float(r['discharge']) for r in results]
        self.assertEqual(discharges, sorted(discharges, reverse=True))
