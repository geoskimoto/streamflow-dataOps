"""Tests for analytics-related REST API endpoints."""

from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from apps.analytics.models import StationMetadata
from apps.streamflow.models import Station


def make_station(number, agency='USGS', is_active=True):
    return Station.objects.create(
        station_number=number, name=f'Station {number}', agency=agency, is_active=is_active,
    )


class LastObservationEndpointTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        User.objects.create_user('tester', password='pass')
        self.client.login(username='tester', password='pass')

        self.s1 = make_station('01010001', 'USGS')
        self.s2 = make_station('01010002', 'EC')
        self.s3 = make_station('01010003', 'USGS', is_active=False)

        StationMetadata.objects.create(
            station=self.s1, last_observation_date=date(2025, 5, 1),
        )
        StationMetadata.objects.create(
            station=self.s2, last_observation_date=date(2024, 11, 15),
        )
        # s3 has no StationMetadata

    def test_endpoint_returns_all_stations(self):
        url = '/api/v1/stations/last-observation/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        numbers = [r['station_number'] for r in response.data]
        self.assertIn('01010001', numbers)
        self.assertIn('01010002', numbers)
        self.assertIn('01010003', numbers)

    def test_response_includes_last_observation_date(self):
        url = '/api/v1/stations/last-observation/'
        response = self.client.get(url)
        by_number = {r['station_number']: r for r in response.data}
        self.assertEqual(by_number['01010001']['last_observation_date'], '2025-05-01')
        self.assertEqual(by_number['01010002']['last_observation_date'], '2024-11-15')
        self.assertIsNone(by_number['01010003']['last_observation_date'])

    def test_response_includes_agency_and_is_active(self):
        url = '/api/v1/stations/last-observation/'
        response = self.client.get(url)
        by_number = {r['station_number']: r for r in response.data}
        self.assertEqual(by_number['01010001']['agency'], 'USGS')
        self.assertFalse(by_number['01010003']['is_active'])

    def test_station_serializer_includes_last_observation_date(self):
        url = f'/api/v1/stations/01010001/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('last_observation_date', response.data)
        self.assertEqual(response.data['last_observation_date'], '2025-05-01')

    def test_station_without_metadata_returns_null(self):
        url = f'/api/v1/stations/01010003/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['last_observation_date'])
