"""Tests for ResidCast settings integration."""
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.conf import settings
from rest_framework.test import APIClient

from apps.streamflow.models import Station, StationMapping


class ResidCastSettingsTest(TestCase):
    def test_residcast_api_base_setting_exists(self):
        self.assertTrue(hasattr(settings, "RESIDCAST_API_BASE"))
        self.assertIsInstance(settings.RESIDCAST_API_BASE, str)
        self.assertTrue(settings.RESIDCAST_API_BASE.startswith("http"))

    def test_residcast_api_token_setting_exists(self):
        self.assertTrue(hasattr(settings, "RESIDCAST_API_TOKEN"))
        self.assertIsInstance(settings.RESIDCAST_API_TOKEN, str)


class PrecipForecastProxyViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("testuser", password="pw")
        self.client.force_authenticate(user=self.user)
        self.station = Station.objects.create(
            station_number="14159500", name="Test Basin", agency="USGS"
        )
        StationMapping.objects.create(
            source_agency="USGS",
            source_id="14159500",
            target_agency="HADS",
            target_id="ARGW1",
        )

    def _mock_residcast(self, status_code=200, json_data=None, exc=None):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data or []
        mock_resp.ok = status_code < 400
        if exc:
            return patch("apps.api.views.precip_proxy.requests.get", side_effect=exc)
        return patch("apps.api.views.precip_proxy.requests.get", return_value=mock_resp)

    def test_returns_200_with_forecast_data(self):
        forecast = [{"issued_at": "2026-06-03T00:00:00Z", "model_name": "ealstm",
                     "predictions": [{"lead_date": "2026-06-04", "predicted_flow_cfs": 1234.5}]}]
        with self._mock_residcast(200, forecast):
            resp = self.client.get("/api/v1/precip-forecasts/14159500/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["model_name"], "ealstm")

    def test_no_station_mapping_returns_404(self):
        resp = self.client.get("/api/v1/precip-forecasts/99999999/")
        self.assertEqual(resp.status_code, 404)

    def test_residcast_404_returns_404(self):
        with self._mock_residcast(404):
            resp = self.client.get("/api/v1/precip-forecasts/14159500/")
        self.assertEqual(resp.status_code, 404)

    def test_residcast_connection_error_returns_502(self):
        import requests as req_lib
        with self._mock_residcast(exc=req_lib.ConnectionError("down")):
            resp = self.client.get("/api/v1/precip-forecasts/14159500/")
        self.assertEqual(resp.status_code, 502)

    def test_residcast_timeout_returns_502(self):
        import requests as req_lib
        with self._mock_residcast(exc=req_lib.Timeout("timeout")):
            resp = self.client.get("/api/v1/precip-forecasts/14159500/")
        self.assertEqual(resp.status_code, 502)

    def test_residcast_500_returns_502(self):
        with self._mock_residcast(500):
            resp = self.client.get("/api/v1/precip-forecasts/14159500/")
        self.assertEqual(resp.status_code, 502)

    def test_bearer_token_sent_to_residcast(self):
        forecast = [{"issued_at": "2026-06-03T00:00:00Z", "model_name": "ealstm", "predictions": []}]
        with patch("apps.api.views.precip_proxy.requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.ok = True
            mock_resp.json.return_value = forecast
            mock_get.return_value = mock_resp
            with self.settings(RESIDCAST_API_TOKEN="test-token-abc"):
                self.client.get("/api/v1/precip-forecasts/14159500/")
            headers = mock_get.call_args.kwargs.get("headers", {})
            self.assertEqual(headers.get("Authorization"), "Bearer test-token-abc")


from apps.streamflow.views import StationDetailView  # noqa: F401 (used indirectly)


class StationDetailEALSTMContextTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pw")
        self.station = Station.objects.create(
            station_number="14159500", name="EA Station", agency="USGS", is_active=True
        )
        self.station_no_mapping = Station.objects.create(
            station_number="99999998", name="Non-EA Station", agency="USGS", is_active=True
        )
        StationMapping.objects.create(
            source_agency="USGS",
            source_id="14159500",
            target_agency="HADS",
            target_id="ARGW1",
        )
        self.client.force_login(self.user)

    def test_ealstm_available_true_for_mapped_station(self):
        resp = self.client.get("/stations/14159500/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["ealstm_available"])
        self.assertEqual(resp.context["nwrfc_id"], "ARGW1")

    def test_ealstm_available_false_for_unmapped_station(self):
        resp = self.client.get("/stations/99999998/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["ealstm_available"])
        self.assertIsNone(resp.context["nwrfc_id"])
