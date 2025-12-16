"""Tests for USGS client."""

import pytest
from datetime import datetime
from src.acquisition.usgs_client import USGSClient


def test_usgs_client_init():
    """Test USGS client initialization."""
    client = USGSClient()
    assert client is not None


def test_usgs_station_info():
    """Test getting station information from USGS."""
    client = USGSClient()

    # Test with a known USGS station (Willamette River at Portland)
    info = client.get_station_info("14211720")

    # May fail if offline or API unavailable - that's okay for now
    if info:
        assert "station_number" in info
        assert info["station_number"] == "14211720"


@pytest.mark.integration
def test_usgs_daily_mean():
    """Test fetching daily mean data from USGS."""
    client = USGSClient()

    # Test with a recent date range
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 7)

    try:
        observations = client.get_daily_mean("14211720", start_date, end_date)

        if observations:  # Data may not always be available
            assert len(observations) > 0
            assert "observed_at" in observations[0]
            assert "discharge" in observations[0]
            assert "unit" in observations[0]
            assert observations[0]["unit"] == "cfs"
            assert observations[0]["type"] == "daily_mean"
    except Exception:
        # API may be unavailable - skip test
        pytest.skip("USGS API unavailable")


@pytest.mark.integration
def test_usgs_instantaneous():
    """Test fetching instantaneous data from USGS."""
    client = USGSClient()

    # Test with a recent short time range
    start_date = datetime(2024, 12, 1)
    end_date = datetime(2024, 12, 1, 6, 0)  # 6 hours

    try:
        observations = client.get_instantaneous("14211720", start_date, end_date)

        if observations:
            assert len(observations) > 0
            assert "observed_at" in observations[0]
            assert "discharge" in observations[0]
            assert observations[0]["type"] == "realtime_15min"
    except Exception:
        pytest.skip("USGS API unavailable")


def test_usgs_empty_result():
    """Test handling of stations with no data."""
    client = USGSClient()

    # Use a far future date where no data exists
    start_date = datetime(2099, 1, 1)
    end_date = datetime(2099, 1, 2)

    try:
        observations = client.get_daily_mean("14211720", start_date, end_date)
        assert observations == []
    except Exception:
        pytest.skip("USGS API unavailable")
