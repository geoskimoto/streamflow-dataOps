"""Unit tests for NWRFCWebClient."""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import requests

from src.acquisition.nwrfc_web_client import NWRFCWebClient


# Minimal representative HTML from textPlot.cgi
# The page returns a PRE block with space-aligned date/time/value columns.
# First two rows are past (observed), last two are future (forecast).
SAMPLE_HTML = """
<html><body><pre>
   DATE/TIME         FLOW(KCFS)
-------------------------------------------------------------------
  06/01/2026 06:00      12.50
  06/01/2026 12:00      13.10
  06/02/2026 00:00      14.80
  06/02/2026 06:00       ---
  06/02/2026 12:00      15.20
</pre></body></html>
"""

# Scrape time lands between the second and third row
SCRAPE_TIME = datetime(2026, 6, 1, 18, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def client():
    return NWRFCWebClient()


def test_parse_returns_list_of_dicts(client):
    rows = client.parse(SAMPLE_HTML, SCRAPE_TIME)
    assert isinstance(rows, list)
    assert len(rows) == 4  # row with "---" is skipped


def test_parse_row_has_required_keys(client):
    rows = client.parse(SAMPLE_HTML, SCRAPE_TIME)
    for row in rows:
        assert 'date' in row
        assert 'value' in row
        assert 'is_forecast' in row


def test_parse_missing_value_rows_skipped(client):
    rows = client.parse(SAMPLE_HTML, SCRAPE_TIME)
    values = [r['value'] for r in rows]
    assert None not in values


def test_parse_observed_rows_flagged_correctly(client):
    rows = client.parse(SAMPLE_HTML, SCRAPE_TIME)
    observed = [r for r in rows if not r['is_forecast']]
    # 06/01 06:00 and 06/01 12:00 are before scrape_time
    assert len(observed) == 2


def test_parse_forecast_rows_flagged_correctly(client):
    rows = client.parse(SAMPLE_HTML, SCRAPE_TIME)
    forecast = [r for r in rows if r['is_forecast']]
    # 06/02 00:00 and 06/02 12:00 are after scrape_time (06/02 06:00 had ---)
    assert len(forecast) == 2


def test_parse_date_is_iso_utc_string(client):
    rows = client.parse(SAMPLE_HTML, SCRAPE_TIME)
    for row in rows:
        assert row['date'].endswith('Z') or '+00:00' in row['date']


def test_parse_value_is_cfs_float(client):
    """Values in KCFS on the page are converted to CFS."""
    rows = client.parse(SAMPLE_HTML, SCRAPE_TIME)
    # 12.50 KCFS → 12500.0 CFS
    first_observed = [r for r in rows if not r['is_forecast']][0]
    assert first_observed['value'] == pytest.approx(12500.0)


def test_fetch_raises_on_http_error(client):
    with patch('requests.get') as mock_get:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_get.return_value = mock_resp
        with pytest.raises(requests.HTTPError, match="REVQ2"):
            client.fetch("REVQ2")


def test_fetch_and_parse_returns_list(client):
    with patch.object(client, 'fetch', return_value=SAMPLE_HTML):
        rows = client.fetch_and_parse("REVQ2")
    assert isinstance(rows, list)
    assert len(rows) == 4


@pytest.mark.integration
def test_live_fetch_revq2():
    """Live test — requires internet. Marked integration, off by default."""
    client = NWRFCWebClient()
    rows = client.fetch_and_parse("REVQ2")
    assert len(rows) > 0
    assert all('date' in r and 'value' in r and 'is_forecast' in r for r in rows)


@pytest.mark.integration
def test_live_fetch_daid1():
    """Live test for a US station."""
    client = NWRFCWebClient()
    rows = client.fetch_and_parse("DAID1")
    assert len(rows) > 0
