"""Tests for map_nwrfc_to_ec_stations management command."""

import math
from io import StringIO
from unittest.mock import patch

from django.test import TestCase
from django.core.management import call_command

from apps.streamflow.models import Station, StationMapping


def _dist(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


class DistanceHelperTest(TestCase):
    def test_same_point_is_zero(self):
        self.assertEqual(_dist(49.0, -118.0, 49.0, -118.0), 0.0)

    def test_distance_is_symmetric(self):
        self.assertAlmostEqual(
            _dist(49.0, -118.0, 50.0, -117.0),
            _dist(50.0, -117.0, 49.0, -118.0),
        )


class MapNwrfcToEcCommandTest(TestCase):
    """Test the map_nwrfc_to_ec_stations command with mocked EC API."""

    def setUp(self):
        # REVQ2 at Revelstoke, BC
        self.revq2 = Station.objects.create(
            station_number='REVQ2',
            name='Revelstoke NWRFC',
            agency='NOAA_RFC',
            latitude=50.999,
            longitude=-118.183,
        )

    @patch('apps.streamflow.management.commands.map_nwrfc_to_ec_stations.CanadaClient')
    def test_dry_run_creates_no_mappings(self, MockClient):
        MockClient.return_value.get_stations_by_province.return_value = [
            {'station_number': '08NE006', 'name': 'Columbia River at Revelstoke',
             'latitude': 50.998, 'longitude': -118.182},
        ]
        out = StringIO()
        call_command('map_nwrfc_to_ec_stations', '--dry-run', stdout=out)
        self.assertEqual(StationMapping.objects.count(), 0)
        self.assertIn('REVQ2', out.getvalue())

    @patch('apps.streamflow.management.commands.map_nwrfc_to_ec_stations.CanadaClient')
    def test_match_within_threshold_creates_mapping(self, MockClient):
        MockClient.return_value.get_stations_by_province.return_value = [
            {'station_number': '08NE006', 'name': 'Columbia River at Revelstoke',
             'latitude': 50.998, 'longitude': -118.182},
        ]
        call_command('map_nwrfc_to_ec_stations', stdout=StringIO())
        self.assertEqual(StationMapping.objects.filter(
            source_agency='NOAA_RFC', source_id='REVQ2',
            target_agency='EC', target_id='08NE006',
        ).count(), 1)

    @patch('apps.streamflow.management.commands.map_nwrfc_to_ec_stations.CanadaClient')
    def test_station_beyond_threshold_not_mapped(self, MockClient):
        MockClient.return_value.get_stations_by_province.return_value = [
            {'station_number': '08XX999', 'name': 'Far Away Station',
             'latitude': 55.0, 'longitude': -125.0},
        ]
        out = StringIO()
        call_command('map_nwrfc_to_ec_stations', stdout=out)
        self.assertEqual(StationMapping.objects.count(), 0)
        self.assertIn('unresolved', out.getvalue().lower())
