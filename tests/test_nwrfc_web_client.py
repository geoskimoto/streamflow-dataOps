"""Unit tests for NWRFCWebClient."""

import pytest
from unittest.mock import patch, MagicMock
import requests

from src.acquisition.nwrfc_web_client import NWRFCWebClient


# Representative HTML matching the real textPlot.cgi table structure.
# Row 0: section headers ("Observed" / "Forecast/Trend Issued: ...")
# Row 1: column headers
# Rows 2+: data rows with up to 4 cells [obs_time, obs_val, fc_time, fc_val]
SAMPLE_HTML = """
<html><body>
<table border="0" cellspacing="5">
<tr><td colspan="2">Observed</td><td colspan="2">Forecast/Trend&nbsp;Issued:&nbsp;2026-06-01 10:00 PDT</td></tr>
<tr><td>Date/Time (PDT)</td><td>Discharge</td><td>Date/Time (PDT)</td><td>Discharge</td></tr>
<tr><td>2026-06-01 06:00</td><td>1250</td><td>2026-06-02 00:00</td><td>1480</td></tr>
<tr><td>2026-06-01 12:00</td><td>1310</td><td>2026-06-02 06:00</td><td>1520</td></tr>
<tr><td></td><td></td><td>2026-06-02 12:00</td><td>1550</td></tr>
</table>
</body></html>
"""

# Page with no data — should return empty list
NO_DATA_HTML = """
<head><pre>*** Please note: No data was found for this station. ***</pre></head>
"""


@pytest.fixture
def client():
    return NWRFCWebClient()


def test_parse_returns_list_of_dicts(client):
    rows = client.parse(SAMPLE_HTML)
    assert isinstance(rows, list)
    # 2 observed rows + 3 forecast rows = 5
    assert len(rows) == 5


def test_parse_row_has_required_keys(client):
    rows = client.parse(SAMPLE_HTML)
    for row in rows:
        assert 'date' in row
        assert 'value' in row
        assert 'is_forecast' in row


def test_parse_observed_rows_flagged_correctly(client):
    rows = client.parse(SAMPLE_HTML)
    observed = [r for r in rows if not r['is_forecast']]
    assert len(observed) == 2


def test_parse_forecast_rows_flagged_correctly(client):
    rows = client.parse(SAMPLE_HTML)
    forecast = [r for r in rows if r['is_forecast']]
    assert len(forecast) == 3


def test_parse_date_is_iso_utc_string(client):
    rows = client.parse(SAMPLE_HTML)
    for row in rows:
        assert row['date'].endswith('Z') or '+00:00' in row['date']


def test_parse_pdt_converted_to_utc(client):
    """PDT (UTC-7) timestamps should be stored as UTC."""
    rows = client.parse(SAMPLE_HTML)
    # 2026-06-01 06:00 PDT = 2026-06-01 13:00 UTC
    obs = [r for r in rows if not r['is_forecast']]
    assert obs[0]['date'] == '2026-06-01T13:00:00Z'


def test_parse_values_are_floats(client):
    rows = client.parse(SAMPLE_HTML)
    for row in rows:
        assert isinstance(row['value'], float)


def test_parse_observed_value_correct(client):
    """Values are CFS — no conversion applied."""
    rows = client.parse(SAMPLE_HTML)
    obs = [r for r in rows if not r['is_forecast']]
    assert obs[0]['value'] == pytest.approx(1250.0)


def test_parse_no_data_returns_empty(client):
    rows = client.parse(NO_DATA_HTML)
    assert rows == []


def test_fetch_raises_on_http_error(client):
    with patch('src.acquisition.nwrfc_web_client.requests.get') as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_resp
        with pytest.raises(requests.HTTPError, match="REVQ2"):
            client.fetch("REVQ2")


def test_fetch_and_parse_returns_list(client):
    with patch.object(client, 'fetch', return_value=SAMPLE_HTML):
        rows = client.fetch_and_parse("WTLO3")
    assert isinstance(rows, list)
    assert len(rows) == 5


@pytest.mark.integration
def test_live_fetch_wtlo3():
    """Live test for a US station with observed + forecast data."""
    client = NWRFCWebClient()
    rows = client.fetch_and_parse("WTLO3")
    assert len(rows) > 0
    assert all('date' in r and 'value' in r and 'is_forecast' in r for r in rows)
    assert any(r['is_forecast'] for r in rows)


@pytest.mark.integration
def test_live_fetch_tdao3():
    """Live test for The Dalles Dam — should have both observed and forecast."""
    client = NWRFCWebClient()
    rows = client.fetch_and_parse("TDAO3")
    assert len(rows) > 0
    obs = [r for r in rows if not r['is_forecast']]
    fcs = [r for r in rows if r['is_forecast']]
    assert len(obs) > 0
    assert len(fcs) > 0


# ── Dispatch integration test ─────────────────────────────────────────────────

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.test import TestCase
from unittest.mock import MagicMock


class TestNwrfcWebDispatch(TestCase):
    """_process_single_station with data_source='nwrfc_web' creates two ForecastRun
    records (observed + forecast) for the station."""

    def test_nwrfc_web_dispatch_saves_two_forecast_runs(self):
        from django.utils import timezone as dj_timezone
        from apps.streamflow.models import Station, ForecastRun
        from src.acquisition.tasks import _process_single_station
        from unittest.mock import patch

        station = Station.objects.get_or_create(
            station_number='REVQ2_TASK3',
            defaults={'name': 'Test REVQ2 Task3', 'agency': 'NOAA_RFC'},
        )[0]

        config = MagicMock()
        config.data_source = 'nwrfc_web'
        config.data_type = 'forecast'
        config.pull_start_date = dj_timezone.now()

        config_station = MagicMock()
        config_station.station_number = 'REVQ2_TASK3'
        config_station.station_name = 'Test REVQ2 Task3'

        sample_rows = [
            {'date': '2026-06-01T06:00:00Z', 'value': 12000.0, 'is_forecast': False},
            {'date': '2026-06-02T00:00:00Z', 'value': 14000.0, 'is_forecast': True},
        ]

        with patch('src.acquisition.tasks.NWRFCWebClient') as MockClient:
            MockClient.return_value.fetch_and_parse.return_value = sample_rows
            result = _process_single_station(config_station, config_id=99, config=config)

        self.assertTrue(result['success'])
        self.assertEqual(
            ForecastRun.objects.filter(station=station, source='nwrfc_web').count(), 2
        )
        self.assertEqual(
            ForecastRun.objects.filter(
                station=station, source='nwrfc_web', is_forecast=False
            ).count(), 1
        )
        self.assertEqual(
            ForecastRun.objects.filter(
                station=station, source='nwrfc_web', is_forecast=True
            ).count(), 1
        )
