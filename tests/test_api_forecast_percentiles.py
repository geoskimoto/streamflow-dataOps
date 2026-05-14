"""Tests for forecast percentile API endpoints."""

from datetime import date, timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.streamflow.models import Station, ForecastPercentile

User = get_user_model()


class ForecastPercentileBandsEndpointTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser_bands', password='testpass')
        self.client.force_authenticate(user=self.user)
        self.station = Station.objects.create(
            station_number='API001',
            name='API Test Station',
            agency='NOAA_RFC',
        )
        self.tomorrow = date.today() + timedelta(days=1)
        self.day2     = date.today() + timedelta(days=2)
        now = timezone.now()

        ForecastPercentile.objects.create(
            station=self.station,
            target_date=self.tomorrow,
            source='NWRFC',
            forecast_run_date=now,
            forecast_discharge=4820.0,
            percentile_rank=72.4,
            band='p51_75',
            historical_record_count=8431,
            computed_at=now,
        )
        ForecastPercentile.objects.create(
            station=self.station,
            target_date=self.day2,
            source='NWRFC',
            forecast_run_date=now,
            forecast_discharge=3200.0,
            percentile_rank=40.0,
            band='p26_50',
            historical_record_count=8431,
            computed_at=now,
        )

    def _url(self):
        return '/api/v1/forecasts/discharge/percentile-bands/'

    def test_returns_200_with_date_param(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_response_structure(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        data = response.json()
        self.assertIn('date', data)
        self.assertIn('source', data)
        self.assertIn('forecast_run_date', data)
        self.assertIn('computed_at', data)
        self.assertIn('count', data)
        self.assertIn('results', data)

    def test_returns_correct_station_data(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        data = response.json()
        self.assertEqual(data['count'], 1)
        result = data['results'][0]
        self.assertEqual(result['station_number'], 'API001')
        self.assertAlmostEqual(result['forecast_discharge'], 4820.0, places=1)
        self.assertEqual(result['band'], 'p51_75')

    def test_date_param_filters_correctly(self):
        response = self.client.get(self._url(), {'date': self.day2.isoformat()})
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertAlmostEqual(data['results'][0]['forecast_discharge'], 3200.0, places=1)

    def test_invalid_date_returns_400(self):
        response = self.client.get(self._url(), {'date': 'not-a-date'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_station_filter(self):
        other = Station.objects.create(
            station_number='API002', name='Other', agency='NOAA_RFC'
        )
        ForecastPercentile.objects.create(
            station=other,
            target_date=self.tomorrow,
            source='NWRFC',
            forecast_run_date=timezone.now(),
            forecast_discharge=100.0,
            percentile_rank=10.0,
            band='p5_10',
            historical_record_count=500,
            computed_at=timezone.now(),
        )
        response = self.client.get(self._url(), {
            'date': self.tomorrow.isoformat(),
            'station': 'API001',
        })
        data = response.json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['station_number'], 'API001')

    def test_source_param_defaults_to_nwrfc(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        self.assertEqual(response.json()['source'], 'NWRFC')

    def test_no_data_for_date_returns_zero_count(self):
        far_future = date.today() + timedelta(days=100)
        response = self.client.get(self._url(), {'date': far_future.isoformat()})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 0)

    def test_no_caching_headers(self):
        response = self.client.get(self._url(), {'date': self.tomorrow.isoformat()})
        self.assertNotIn('Cache-Control', response)


class ForecastPercentileDateRangeEndpointTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='testuser_range', password='testpass')
        self.client.force_authenticate(user=self.user)
        self.station = Station.objects.create(
            station_number='RNG001',
            name='Range Test',
            agency='NOAA_RFC',
        )
        now = timezone.now()
        for days in [1, 2, 3, 4, 5]:
            ForecastPercentile.objects.create(
                station=self.station,
                target_date=date.today() + timedelta(days=days),
                source='NWRFC',
                forecast_run_date=now,
                forecast_discharge=1000.0,
                percentile_rank=50.0,
                band='p26_50',
                historical_record_count=500,
                computed_at=now,
            )

    def _url(self):
        return '/api/v1/forecasts/discharge/percentile-date-range/'

    def test_returns_200(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_response_structure(self):
        data = self.client.get(self._url()).json()
        self.assertIn('source', data)
        self.assertIn('min_date', data)
        self.assertIn('max_date', data)
        self.assertIn('forecast_run_date', data)

    def test_correct_date_range(self):
        data = self.client.get(self._url()).json()
        self.assertEqual(data['min_date'], (date.today() + timedelta(days=1)).isoformat())
        self.assertEqual(data['max_date'], (date.today() + timedelta(days=5)).isoformat())

    def test_cache_control_header_set(self):
        response = self.client.get(self._url())
        self.assertIn('Cache-Control', response)
        self.assertIn('max-age=3600', response['Cache-Control'])

    def test_empty_when_no_data(self):
        ForecastPercentile.objects.all().delete()
        data = self.client.get(self._url()).json()
        self.assertIsNone(data['min_date'])
        self.assertIsNone(data['max_date'])
