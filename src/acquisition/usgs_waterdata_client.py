"""USGS Water Data OGC API client for daily-mean discharge.

Replaces the legacy NWIS WaterServices path (``dataretrieval.nwis.get_dv``)
for daily means. USGS is retiring the legacy service, and at scale it returned
undecodable gzip bodies and empty responses — config 9 "USGS Daily Mean Pull"
logged 101 failed runs in August 2026 alone.

Two things this client does that the legacy path could not:

* filters on ``statistic_id="00003"`` so the daily-mean series is selected
  explicitly, instead of guessing with ``discharge_cols[0]`` and silently
  dropping any other series;
* surfaces ``approval_status`` and ``qualifier`` per value, so revised and
  estimated values are distinguishable.

Emitted observation dicts match the legacy client's shape exactly, so
``DataProcessor`` needs no changes.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DISCHARGE_PARAMETER_CODE = "00060"
DAILY_MEAN_STATISTIC_ID = "00003"

# 50,000 is the API's hard maximum ("Limit of 50000 exceeded" above it) and is
# deliberately used in full: the longest record among the 285 NWRFC-mapped
# gages is 49,486 days, so one request covers one gage. At limit=10000 the
# backfill would need 939 requests instead of 285, and backfill plus audit
# would blow the API key's 1,000 requests/hour budget.
PAGE_LIMIT = 50000

# Guard against a malformed `next` chain looping forever.
MAX_PAGES = 200

REQUEST_TIMEOUT_SECONDS = 180
DEFAULT_RETRIES = 3

# approval_status -> legacy NWIS base code, preserving the quality_code
# vocabulary already stored in discharge_observations ('A', 'P').
APPROVAL_CODES = {"Approved": "A", "Provisional": "P"}

# qualifier -> legacy NWIS suffix letter. 'e' (estimated) and 'R' (revised)
# reproduce the existing 'A, e' / 'A, R' codes. The rest had no legacy
# single-letter form; these are chosen to stay inside
# DischargeObservation.quality_code's max_length=10.
QUALIFIER_CODES = {
    "ESTIMATED": "e",
    "REVISED": "R",
    "ICE": "i",
    "EQUIP": "q",
    "MAINT": "m",
    "BACKWATER": "b",
}

QUALITY_CODE_MAX_LENGTH = 10


class USGSWaterDataError(Exception):
    """A non-retryable failure (4xx other than 429, malformed payload)."""


class USGSWaterDataTransientError(Exception):
    """A retryable failure (429, 5xx, network error)."""


def build_quality_code(
    approval_status: Optional[str], qualifier: Optional[list]
) -> str:
    """Render approval status and qualifiers as a legacy-style quality code.

    ``("Approved", ["EQUIP", "ESTIMATED"])`` -> ``"A, q, e"``. Unknown
    qualifiers are ignored rather than raising, so a new USGS vocabulary entry
    cannot break ingestion. The result is truncated to the model's
    ``max_length=10``.
    """
    base = APPROVAL_CODES.get(approval_status or "", "")
    parts = [base] if base else []

    for item in qualifier or []:
        code = QUALIFIER_CODES.get(str(item).upper())
        if code is None:
            logger.debug("Unmapped USGS qualifier %r ignored", item)
            continue
        if code not in parts:
            parts.append(code)

    return ", ".join(parts)[:QUALITY_CODE_MAX_LENGTH]


class USGSWaterDataClient:
    """Reads daily-mean discharge from the USGS Water Data OGC API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.base_url = (
            base_url
            if base_url is not None
            else getattr(
                settings,
                "USGS_WATERDATA_BASE",
                "https://api.waterdata.usgs.gov/ogcapi/v1",
            )
        ).rstrip("/")
        self.api_key = (
            api_key
            if api_key is not None
            else getattr(settings, "USGS_API_KEY", "")
        )
        self.logger = logging.getLogger(__name__)

    # -- public API -------------------------------------------------------

    def get_daily_mean(
        self,
        station_number: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime] = None,
        _retries: int = DEFAULT_RETRIES,
    ) -> List[Dict]:
        """Return daily-mean discharge observations for one USGS station.

        Args:
            station_number: bare USGS site id, e.g. ``"12200500"``.
            start_date: inclusive start, or ``None`` for the full record.
            end_date: inclusive end. Ignored unless ``start_date`` is given.
            _retries: retry budget for transient failures; 0 disables retrying.

        Returns:
            Observation dicts with keys ``observed_at`` (midnight UTC),
            ``discharge`` (cfs, float), ``unit``, ``type``, ``quality_code``.
        """
        params = {
            "monitoring_location_id": f"USGS-{station_number}",
            "parameter_code": DISCHARGE_PARAMETER_CODE,
            "statistic_id": DAILY_MEAN_STATISTIC_ID,
            "limit": PAGE_LIMIT,
            "skipGeometry": "true",
        }
        if start_date is not None:
            stop = end_date or datetime.now(timezone.utc)
            params["datetime"] = (
                f"{self._as_date(start_date)}/{self._as_date(stop)}"
            )

        self.logger.info(
            "Fetching USGS daily mean for %s (%s)",
            station_number,
            params.get("datetime", "full record"),
        )

        features = self._fetch_all_pages(params, _retries)
        observations = self._parse(features, station_number)

        self.logger.info(
            "Retrieved %d daily mean records for %s",
            len(observations),
            station_number,
        )
        return observations

    # -- internals --------------------------------------------------------

    @staticmethod
    def _as_date(value) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)[:10]

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/geo+json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    def _fetch_all_pages(self, params: Dict, retries: int) -> List[Dict]:
        url = f"{self.base_url}/collections/daily/items"
        features: List[Dict] = []
        pages = 0

        while url and pages < MAX_PAGES:
            payload = self._get(url, params, retries)
            features.extend(payload.get("features") or [])
            pages += 1

            url = next(
                (
                    link.get("href")
                    for link in payload.get("links") or []
                    if link.get("rel") == "next"
                ),
                None,
            )
            # `next` is absolute and already carries the query string.
            params = {}

        if pages >= MAX_PAGES and url:
            self.logger.warning(
                "Stopped paginating after %d pages; result may be truncated",
                MAX_PAGES,
            )

        return features

    def _get(self, url: str, params: Dict, retries: int) -> Dict:
        attempt = 0
        while True:
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=self._headers(),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                error: Exception = USGSWaterDataTransientError(str(exc))
            else:
                error = self._classify(response)
                if error is None:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise USGSWaterDataError(
                            f"Malformed JSON from {url}: {exc}"
                        ) from exc

            if isinstance(error, USGSWaterDataTransientError) and attempt < retries:
                delay = self._retry_delay(locals().get("response"), attempt)
                self.logger.warning(
                    "Transient USGS Water Data failure (%s); retry %d/%d in %.1fs",
                    error,
                    attempt + 1,
                    retries,
                    delay,
                )
                _time.sleep(delay)
                attempt += 1
                continue

            raise error

    @staticmethod
    def _classify(response) -> Optional[Exception]:
        status = response.status_code
        if status == 200:
            return None
        if status == 429 or status >= 500:
            return USGSWaterDataTransientError(f"HTTP {status}")
        return USGSWaterDataError(f"HTTP {status}")

    @staticmethod
    def _retry_delay(response, attempt: int) -> float:
        # Honour Retry-After when the API sends it; otherwise back off.
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(float(retry_after), 120.0)
                except (TypeError, ValueError):
                    pass
        return min(2.0 ** (attempt + 1), 60.0)

    def _parse(self, features: List[Dict], station_number: str) -> List[Dict]:
        observations: List[Dict] = []
        series_ids = set()

        for feature in features:
            props = feature.get("properties") or {}
            series_ids.add(props.get("time_series_id"))

            raw_value = props.get("value")
            raw_time = props.get("time")

            if raw_value is None or raw_time is None:
                self.logger.warning(
                    "Unparseable USGS record for %s at %s: value=%r",
                    station_number,
                    raw_time,
                    raw_value,
                )
                continue

            try:
                discharge = float(raw_value)
            except (TypeError, ValueError):
                self.logger.warning(
                    "Unparseable USGS discharge for %s at %s: %r",
                    station_number,
                    raw_time,
                    raw_value,
                )
                continue

            try:
                day = date.fromisoformat(str(raw_time)[:10])
            except ValueError:
                self.logger.warning(
                    "Unparseable USGS date for %s: %r", station_number, raw_time
                )
                continue

            observations.append(
                {
                    # Midnight UTC: matches all 25.3M existing USGS daily_mean
                    # rows, so upserts update instead of duplicating.
                    "observed_at": datetime(
                        day.year, day.month, day.day, tzinfo=timezone.utc
                    ),
                    "discharge": discharge,
                    "unit": "cfs",
                    "type": "daily_mean",
                    "quality_code": build_quality_code(
                        props.get("approval_status"), props.get("qualifier")
                    ),
                }
            )

        if len(series_ids) > 1:
            self.logger.warning(
                "Station %s returned multiple time series for %s/%s: %s. All "
                "values kept; the last one per date wins on upsert.",
                station_number,
                DISCHARGE_PARAMETER_CODE,
                DAILY_MEAN_STATISTIC_ID,
                sorted(s for s in series_ids if s),
            )

        observations.sort(key=lambda o: o["observed_at"])
        return observations
