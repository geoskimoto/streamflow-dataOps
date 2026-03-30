"""
Tests for MasterStation API endpoints.

Covers list, retrieve, filtering, search, and the lookup action.
"""

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from apps.streamflow.models import MasterStation


class MasterStationSetup(TestCase):
    """Shared setUp for all MasterStation test cases."""

    def setUp(self):
        self.client = APIClient()
        user = User.objects.create_user(username='testuser', password='testpass')
        self.client.force_authenticate(user=user)

        self.patw1 = MasterStation.objects.create(
            station_number='12149000',
            noaa_lid='PATW1',
            rfc_code='NWRFC',
            station_name='Methow River at Pateros WA',
            agency='USGS',
            state_code='WA',
            huc_code='17020009',
            latitude=48.0534,
            longitude=-119.9018,
            drainage_area_sqmi=2800.0,
        )

        self.pesw1 = MasterStation.objects.create(
            station_number='12189500',
            noaa_lid='PESW1',
            rfc_code='NWRFC',
            station_name='Nooksack River near Peshastin WA',
            agency='USGS',
            state_code='WA',
            huc_code='17110005',
            latitude=48.5912,
            longitude=-122.0123,
            drainage_area_sqmi=1450.0,
        )

        self.orfi1 = MasterStation.objects.create(
            station_number='14103000',
            noaa_lid='ORFI1',
            rfc_code='NWRFC',
            station_name='Deschutes River at Fishers Landing OR',
            agency='USGS',
            state_code='OR',
            huc_code='17070301',
            latitude=45.6234,
            longitude=-121.8765,
            drainage_area_sqmi=10130.0,
        )

        # Station with no noaa_lid (edge case)
        self.no_lid = MasterStation.objects.create(
            station_number='99999999',
            noaa_lid=None,
            rfc_code='NWRFC',
            station_name='Station Without NOAA LID',
            agency='USGS',
            state_code='WA',
            huc_code='17020001',
        )


class MasterStationListTest(MasterStationSetup):
    """Tests for GET /api/master-stations/"""

    def test_list_returns_all_records(self):
        response = self.client.get(reverse('api:master-station-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 4)

    def test_list_contains_expected_fields(self):
        response = self.client.get(reverse('api:master-station-list'))
        first = response.data['results'][0]
        for field in ('station_number', 'noaa_lid', 'rfc_code', 'station_name',
                      'agency', 'state_code', 'huc_code', 'latitude', 'longitude'):
            self.assertIn(field, first)

    def test_filter_by_state(self):
        response = self.client.get(reverse('api:master-station-list'), {'state_code': 'OR'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['state_code'], 'OR')

    def test_filter_by_rfc_code(self):
        response = self.client.get(reverse('api:master-station-list'), {'rfc_code': 'NWRFC'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 4)

    def test_search_by_station_name(self):
        response = self.client.get(reverse('api:master-station-list'), {'search': 'Methow'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['noaa_lid'], 'PATW1')

    def test_search_by_noaa_lid(self):
        response = self.client.get(reverse('api:master-station-list'), {'search': 'PESW1'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_list_is_readonly(self):
        response = self.client.post(reverse('api:master-station-list'), {})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class MasterStationRetrieveTest(MasterStationSetup):
    """Tests for GET /api/master-stations/{pk}/"""

    def test_retrieve_by_pk(self):
        response = self.client.get(
            reverse('api:master-station-detail', kwargs={'pk': self.patw1.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['noaa_lid'], 'PATW1')
        self.assertEqual(response.data['station_number'], '12149000')

    def test_retrieve_nonexistent_returns_404(self):
        response = self.client.get(
            reverse('api:master-station-detail', kwargs={'pk': 99999})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class MasterStationLookupTest(MasterStationSetup):
    """Tests for GET /api/master-stations/lookup/?id=<value>"""

    def test_lookup_by_noaa_lid(self):
        response = self.client.get(
            reverse('api:master-station-lookup'), {'id': 'PATW1'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['station_number'], '12149000')
        self.assertEqual(response.data['noaa_lid'], 'PATW1')
        self.assertEqual(response.data['rfc_code'], 'NWRFC')

    def test_lookup_by_station_number(self):
        response = self.client.get(
            reverse('api:master-station-lookup'), {'id': '12149000'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['noaa_lid'], 'PATW1')

    def test_lookup_is_case_insensitive(self):
        response = self.client.get(
            reverse('api:master-station-lookup'), {'id': 'patw1'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['noaa_lid'], 'PATW1')

    def test_lookup_missing_id_param_returns_400(self):
        response = self.client.get(reverse('api:master-station-lookup'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)

    def test_lookup_unknown_id_returns_404(self):
        response = self.client.get(
            reverse('api:master-station-lookup'), {'id': 'ZZZZZ'}
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('error', response.data)

    def test_lookup_response_includes_all_id_fields(self):
        response = self.client.get(
            reverse('api:master-station-lookup'), {'id': 'PATW1'}
        )
        for field in ('station_number', 'noaa_lid', 'rfc_code'):
            self.assertIn(field, response.data)

    def test_lookup_station_without_noaa_lid_by_station_number(self):
        response = self.client.get(
            reverse('api:master-station-lookup'), {'id': '99999999'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['noaa_lid'])
