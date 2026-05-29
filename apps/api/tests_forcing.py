"""Tests for the BasinForcing API endpoint."""
import datetime
from django.test import TestCase
from rest_framework.test import APIClient
from apps.streamflow.models import Station, BasinForcing


class BasinForcingAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.station = Station.objects.create(
            station_number="14178000", name="Test Station", agency="USGS"
        )
        for i in range(3):
            BasinForcing.objects.create(
                station=self.station,
                date=datetime.date(2026, 5, 27 + i),
                prcp_mm_day=float(i),
                tmax_c=20.0 + i, tmin_c=5.0 + i,
                srad_w_m2=200.0, vp_pa=900.0, dayl_s=43200.0,
                source="nwm",
            )

    def test_get_forcings_returns_200(self):
        resp = self.client.get("/api/v1/forcings/14178000/")
        self.assertEqual(resp.status_code, 200)

    def test_get_forcings_response_shape(self):
        resp = self.client.get("/api/v1/forcings/14178000/")
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)
        self.assertIn("date", data[0])
        self.assertIn("prcp_mm_day", data[0])
        self.assertIn("tmax_c", data[0])

    def test_get_forcings_missing_station_returns_404(self):
        resp = self.client.get("/api/v1/forcings/99999999/")
        self.assertEqual(resp.status_code, 404)

    def test_get_forcings_days_param(self):
        resp = self.client.get("/api/v1/forcings/14178000/?days=1")
        data = resp.json()
        self.assertEqual(len(data), 1)
