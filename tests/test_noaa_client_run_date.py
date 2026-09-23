"""Tests for issuance-time derivation in NOAAClient.get_rfc_forecast.

The NWPS stageflow endpoint returns the issuance timestamp under the key
"issuedTime". Reading "issueTime" (no 'd') silently yields None, which is how
68,057 forecast_runs rows ended up keyed on fetch time instead of issuance
time. These tests pin the field name and forbid the now() fallback.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.acquisition.noaa_client import NOAAClient


def _payload(forecast_overrides=None):
    """Minimal stageflow payload shaped like the real API response."""
    forecast = {
        "issuedTime": "2026-09-22T15:26:00Z",
        "pedts": "QRIFF",
        "wfo": "PQR",
        "timeZone": "PST8PDT",
        "secondaryUnits": "kcfs",
        "data": [
            {"validTime": "2026-09-22T18:00:00Z", "primary": 3.31, "secondary": 1.34},
            {"validTime": "2026-09-23T00:00:00Z", "primary": 3.29, "secondary": 1.32},
        ],
    }
    if forecast_overrides is not None:
        forecast.update(forecast_overrides)
    return {"forecast": forecast}


@pytest.fixture
def client():
    return NOAAClient()


def _mock_get(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return patch("src.acquisition.noaa_client.requests.get", return_value=resp)


def test_run_date_reads_issuedTime(client):
    """run_date comes from 'issuedTime' — the actual NWPS field name."""
    with _mock_get(_payload()):
        result = client.get_rfc_forecast("WTLO3")
    assert result is not None
    assert result["run_date"] == datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)


def test_run_date_is_not_fetch_time(client):
    """Regression guard: run_date must never be a now() stand-in.

    The defect produced microsecond-precision timestamps; a real issuance
    time is minute-precision.
    """
    with _mock_get(_payload()):
        result = client.get_rfc_forecast("WTLO3")
    assert result["run_date"].second == 0
    assert result["run_date"].microsecond == 0


def test_falls_back_to_legacy_issueTime_key(client):
    """Tolerate the legacy spelling if some endpoint still emits it."""
    payload = _payload({"issuedTime": None, "issueTime": "2026-09-22T15:26:00Z"})
    with _mock_get(payload):
        result = client.get_rfc_forecast("WTLO3")
    assert result["run_date"] == datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)


def test_returns_none_when_issuance_time_missing(client):
    """No issuance time -> skip the run rather than invent a key."""
    payload = _payload({"issuedTime": None})
    with _mock_get(payload):
        result = client.get_rfc_forecast("WTLO3")
    assert result is None


def test_returns_none_when_issuance_time_malformed(client):
    """Unparseable issuance time -> skip, do not substitute now()."""
    payload = _payload({"issuedTime": "not-a-timestamp"})
    with _mock_get(payload):
        result = client.get_rfc_forecast("WTLO3")
    assert result is None


def test_malformed_issuance_time_is_logged(client, caplog):
    """The old bare `except:` hid this for months. It must be visible."""
    payload = _payload({"issuedTime": "not-a-timestamp"})
    with _mock_get(payload):
        with caplog.at_level("WARNING"):
            client.get_rfc_forecast("WTLO3")
    assert "not-a-timestamp" in caplog.text


def test_naive_issued_time_is_coerced_to_utc(client):
    """A NWPS 'issuedTime' with no UTC offset must not be interpreted in the
    project TIME_ZONE by Django. fromisoformat() alone would return a naive
    datetime here, producing a run_date hours off from the archive.
    """
    payload = _payload({"issuedTime": "2026-09-22T15:26:00"})  # no trailing 'Z'/offset
    with _mock_get(payload):
        result = client.get_rfc_forecast("WTLO3")
    assert result["run_date"] == datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    assert result["run_date"].tzinfo is not None


def test_forecast_data_still_converts_kcfs_to_cfs(client):
    """Guard the surrounding behaviour we are not changing."""
    with _mock_get(_payload()):
        result = client.get_rfc_forecast("WTLO3")
    assert result["forecast_data"][0]["value"] == 1340.0
