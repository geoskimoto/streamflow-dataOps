"""NWM Analysis Assim forcing file download client.

Downloads hourly NetCDF forcing files from NOAA NOMADS (recent data,
< 3 days) or the public AWS S3 mirror (historical data).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

_FILE_PATTERN = (
    "{base}/nwm.{date_str}/forcing_analysis_assim"
    "/nwm.t{hour:02d}z.analysis_assim.forcing.tm00.conus.nc"
)


class NWMDownloadError(Exception):
    """Raised when an NWM file cannot be downloaded."""


class NWMTransientError(NWMDownloadError):
    """Raised for transient server errors (5xx) that warrant retry."""


def build_nomads_url(base: str, dt: date, hour: int) -> str:
    """Return the NOMADS URL for a specific NWM analysis forcing file."""
    return _FILE_PATTERN.format(
        base=base.rstrip("/"),
        date_str=dt.strftime("%Y%m%d"),
        hour=hour,
    )


def build_s3_url(base: str, dt: date, hour: int) -> str:
    """Return the S3 URL for a specific NWM analysis forcing file."""
    return _FILE_PATTERN.format(
        base=base.rstrip("/"),
        date_str=dt.strftime("%Y%m%d"),
        hour=hour,
    )


def list_day_urls(base: str, dt: date, source: str = "nomads") -> list[str]:
    """Return the 24 hourly URLs for a full calendar day.

    Args:
        base: NOMADS base URL or S3 base URL.
        dt: The date to retrieve.
        source: 'nomads' or 's3'.
    """
    builder = build_nomads_url if source == "nomads" else build_s3_url
    return [builder(base, dt, hour) for hour in range(24)]


@retry(
    retry=retry_if_exception_type((requests.RequestException, NWMTransientError)),
    wait=wait_exponential(multiplier=2, min=4, max=60),
    stop=stop_after_attempt(3),
    reraise=True,
)
def download_file(url: str, dest: Path) -> Path:
    """Download *url* to *dest*, streaming in 1 MB chunks.

    Args:
        url: Direct HTTP URL of a NWM NetCDF file.
        dest: Destination file path (parent must exist).

    Returns:
        dest path on success.

    Raises:
        NWMDownloadError: On non-2xx HTTP response after retries.
        requests.RequestException: On network error after retries.
    """
    session = requests.Session()
    resp = session.get(url, timeout=120, stream=True)
    if not resp.ok:
        if resp.status_code >= 500:
            raise NWMTransientError(f"HTTP {resp.status_code} downloading {url}")
        raise NWMDownloadError(f"HTTP {resp.status_code} downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            fh.write(chunk)
    return dest
