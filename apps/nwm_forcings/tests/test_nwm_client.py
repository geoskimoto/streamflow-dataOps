"""Tests for NWM file download client."""
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_build_nomads_url():
    from apps.nwm_forcings.nwm_client import build_nomads_url

    url = build_nomads_url(
        base="https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod",
        dt=date(2026, 6, 1),
        hour=3,
    )
    assert url == (
        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod"
        "/nwm.20260601/forcing_analysis_assim"
        "/nwm.t03z.analysis_assim.forcing.tm00.conus.nc"
    )


def test_build_s3_url():
    from apps.nwm_forcings.nwm_client import build_s3_url

    url = build_s3_url(
        base="https://noaa-nwm-pds.s3.amazonaws.com",
        dt=date(2025, 11, 15),
        hour=22,
    )
    assert url == (
        "https://noaa-nwm-pds.s3.amazonaws.com"
        "/nwm.20251115/forcing_analysis_assim"
        "/nwm.t22z.analysis_assim.forcing.tm00.conus.nc"
    )


def test_download_file_success(tmp_path):
    from apps.nwm_forcings.nwm_client import download_file

    fake_content = b"FAKE_NC_DATA" * 100
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.iter_content = MagicMock(return_value=[fake_content])

    with patch("requests.Session.get", return_value=mock_resp):
        out_path = tmp_path / "test.nc"
        result = download_file("https://example.com/test.nc", out_path)

    assert result == out_path
    assert out_path.read_bytes() == fake_content


def test_download_file_http_error(tmp_path):
    from apps.nwm_forcings.nwm_client import NWMDownloadError, download_file

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 404
    mock_resp.iter_content = MagicMock(return_value=[])

    with patch("requests.Session.get", return_value=mock_resp):
        out_path = tmp_path / "test.nc"
        with pytest.raises(NWMDownloadError, match="404"):
            download_file("https://example.com/missing.nc", out_path)


def test_list_day_urls_nomads():
    from apps.nwm_forcings.nwm_client import list_day_urls

    urls = list_day_urls(
        base="https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod",
        dt=date(2026, 1, 15),
        source="nomads",
    )
    assert len(urls) == 24
    assert urls[0].endswith("nwm.t00z.analysis_assim.forcing.tm00.conus.nc")
    assert urls[23].endswith("nwm.t23z.analysis_assim.forcing.tm00.conus.nc")
    assert "20260115" in urls[0]
