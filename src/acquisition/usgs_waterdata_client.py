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

# The API echoes unit_of_measure on every feature. Checked per feature along
# with the three filter fields: a stage (ft) or temperature (degC) value that
# slipped past a dropped server-side filter would pass validate_observations
# unchallenged and be written in as discharge.
DISCHARGE_UNIT_OF_MEASURE = "ft^3/s"

# 50,000 is the API's hard maximum ("Limit of 50000 exceeded" above it) and is
# deliberately used in full: the longest record among the 285 NWRFC-mapped
# gages is 49,486 days, so one request covers one gage. At limit=10000 the
# backfill would need 939 requests instead of 285, and backfill plus audit
# would blow the API key's 1,000 requests/hour budget.
PAGE_LIMIT = 50000

# Guard against a malformed `next` chain looping forever. Exceeding this is
# treated as an error, not a warning — a silently truncated series is
# indistinguishable from a complete one and would be recorded as a success.
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
#
# Declaration order here is also the canonical output order used by
# build_quality_code, so the emitted code never depends on the order the API
# returned qualifiers in (a dict-order-dependent code would churn
# quality_code on every re-pull and produce pointless updates).
QUALIFIER_CODES = {
    "ESTIMATED": "e",
    "REVISED": "R",
    "ICE": "i",
    "EQUIP": "q",
    "MAINT": "m",
    "BACKWATER": "b",
}

QUALIFIER_ORDER = tuple(QUALIFIER_CODES.keys())

QUALITY_CODE_MAX_LENGTH = 10


class USGSWaterDataError(Exception):
    """A non-retryable failure (4xx other than 429, malformed payload)."""


class USGSWaterDataTransientError(Exception):
    """A retryable failure (429, 5xx, undecodable body, network error)."""


def _join_within_limit(parts: List[str], max_length: int) -> str:
    """Join ``parts`` with ``", "``, keeping only whole tokens that fit.

    Never returns a trailing separator or a half-written token — truncation
    always lands on a token boundary.
    """
    result = ""
    for i in range(len(parts)):
        candidate = ", ".join(parts[: i + 1])
        if len(candidate) > max_length:
            break
        result = candidate
    return result


def build_quality_code(
    approval_status: Optional[str], qualifier: Optional[list]
) -> str:
    """Render approval status and qualifiers as a legacy-style quality code.

    ``("Approved", ["EQUIP", "ESTIMATED"])`` -> ``"A, e, q"``. Qualifiers are
    always emitted in ``QUALIFIER_ORDER`` (not input order), so the same
    semantic state always produces the same code regardless of how the API
    ordered the list — otherwise re-pulls would churn ``quality_code`` and
    produce pointless updates. Unknown qualifiers are ignored (logged at
    DEBUG) rather than raising, so a new USGS vocabulary entry cannot break
    ingestion.

    An unmapped *non-empty* ``approval_status`` raises
    ``USGSWaterDataError``. ``DataProcessor`` has ``quality_code`` in its
    upsert ``update_fields`` and the backfill defaults to the whole record,
    so a single USGS vocabulary change (``"Approved"`` -> ``"approved"``)
    would otherwise overwrite ~10M stored ``A`` / ``A, e`` codes with an
    empty string behind one warning in a multi-hour log. Failing the gage
    loudly — it is then recorded as ``failed`` and retried — is the only safe
    behaviour. An empty or ``None`` status stays lenient: it simply yields no
    base letter.

    The result is truncated to the model's ``max_length=10`` at a token
    boundary.
    """
    if approval_status and approval_status not in APPROVAL_CODES:
        raise USGSWaterDataError(
            f"Unmapped USGS approval_status {approval_status!r}; refusing to "
            f"write an empty quality_code over existing values. Known "
            f"statuses: {sorted(APPROVAL_CODES)}."
        )
    base = APPROVAL_CODES.get(approval_status or "", "")

    present = set()
    for item in qualifier or []:
        name = str(item).upper()
        if name in QUALIFIER_CODES:
            present.add(name)
        else:
            logger.debug("Unmapped USGS qualifier %r ignored", item)

    parts = [base] if base else []
    for name in QUALIFIER_ORDER:
        if name in present:
            parts.append(QUALIFIER_CODES[name])

    return _join_within_limit(parts, QUALITY_CODE_MAX_LENGTH)


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
            Exactly one observation per ``observed_at`` is returned even if
            the station has multiple time series for this parameter/statistic.
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

        features = self._fetch_all_pages(params, _retries, station_number)
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

    def _fetch_all_pages(
        self, params: Dict, retries: int, station_number: str
    ) -> List[Dict]:
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
            # A partially-fetched series is indistinguishable from a
            # complete one once returned, so a backfill would record it as a
            # success and the verification step would never catch it. Fail
            # loudly instead of returning silently truncated data.
            raise USGSWaterDataError(
                f"Station {station_number} exceeded the {MAX_PAGES}-page "
                "pagination cap; aborting rather than returning a silently "
                "truncated series."
            )

        return features

    def _get(self, url: str, params: Dict, retries: int) -> Dict:
        attempt = 0
        while True:
            response = None
            cause: Optional[BaseException] = None
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=self._headers(),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                error: Exception = USGSWaterDataTransientError(str(exc))
                cause = exc
            else:
                error = self._classify(response)
                if error is None:
                    try:
                        return response.json()
                    except ValueError as exc:
                        # A 200 with a truncated/empty body ("Expecting value:
                        # line 1 column 1 (char 0)") is exactly the failure
                        # mode this client replaces the legacy endpoint for,
                        # and it self-heals on retry — classify it as
                        # transient, not permanent.
                        error = USGSWaterDataTransientError(
                            f"Malformed JSON from {url}: {exc}"
                        )
                        cause = exc

            if isinstance(error, USGSWaterDataTransientError) and attempt < retries:
                # `response` reflects only this attempt (reset to None at the
                # top of the loop each time), so a stale Retry-After from an
                # earlier attempt can never leak into this delay.
                delay = self._retry_delay(response, attempt)
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

            if cause is not None:
                raise error from cause
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
        parsed: List[Dict] = []
        series_ids = set()
        mismatches: Dict[str, set] = {}
        skipped = 0

        expected = {
            "monitoring_location_id": f"USGS-{station_number}",
            "parameter_code": DISCHARGE_PARAMETER_CODE,
            "statistic_id": DAILY_MEAN_STATISTIC_ID,
            "unit_of_measure": DISCHARGE_UNIT_OF_MEASURE,
        }

        for feature in features:
            props = feature.get("properties") or {}
            series_id = props.get("time_series_id")
            if series_id is not None:
                series_ids.add(series_id)

            # Provenance check. OGC implementations commonly ignore query
            # parameters they don't recognise, so if USGS renames a filter
            # param the `limit=50000` request would return an unfiltered
            # slice of the `daily` collection — another station's values, or
            # stage/temperature — and validate_observations would pass them
            # straight through as discharge. The API echoes all four fields
            # on every feature, so this is cheap. Any mismatch at all means
            # the server is not honouring our filters, so the whole response
            # is untrustworthy and we raise after the loop rather than
            # quietly keeping the subset that happened to match.
            bad_field = next(
                (
                    field
                    for field, want in expected.items()
                    if props.get(field) != want
                ),
                None,
            )
            if bad_field is not None:
                skipped += 1
                mismatches.setdefault(bad_field, set()).add(
                    repr(props.get(bad_field))
                )
                continue

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

            parsed.append(
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
                    "_series_id": series_id,
                }
            )

        if skipped:
            detail = "; ".join(
                f"{field}: expected {expected[field]!r}, saw "
                f"{', '.join(sorted(values))}"
                for field, values in sorted(mismatches.items())
            )
            raise USGSWaterDataError(
                f"Station {station_number}: the USGS Water Data API returned "
                f"{skipped} feature(s) that do not match the requested "
                f"filters — {detail}. "
                "The server is not honouring our query parameters, so the "
                "whole response is untrustworthy; aborting this station."
            )

        if len(series_ids) > 1:
            self.logger.warning(
                "Station %s returned multiple time series for %s/%s: %s. "
                "Each date keeps exactly one deterministic value; see any "
                "duplicate-date warning above for how ties were resolved.",
                station_number,
                DISCHARGE_PARAMETER_CODE,
                DAILY_MEAN_STATISTIC_ID,
                sorted(series_ids),
            )

        observations = self._dedupe_by_date(parsed, station_number)
        observations.sort(key=lambda o: o["observed_at"])
        return observations

    def _dedupe_by_date(
        self, parsed: List[Dict], station_number: str
    ) -> List[Dict]:
        """Guarantee exactly one observation per ``observed_at``.

        Two time series covering the same date would otherwise produce two
        dicts with the same ``observed_at``; ``DataProcessor`` passes the
        whole batch to one ``bulk_create(update_conflicts=True)``, and
        PostgreSQL raises "ON CONFLICT DO UPDATE command cannot affect row a
        second time" — failing that station's entire write inside
        ``transaction.atomic()``.

        Resolution is deterministic: sort by ``(observed_at, time_series_id)``
        and keep the first occurrence per date, so repeated calls on the same
        input always pick the same winner regardless of feature order.
        """
        parsed_sorted = sorted(
            parsed, key=lambda o: (o["observed_at"], o.get("_series_id") or "")
        )

        kept: Dict[datetime, Dict] = {}
        duplicate_dates = 0
        ambiguous_series = set()

        for obs in parsed_sorted:
            when = obs["observed_at"]
            if when not in kept:
                kept[when] = obs
                continue

            duplicate_dates += 1
            for candidate in (kept[when], obs):
                series_id = candidate.get("_series_id")
                if series_id is not None:
                    ambiguous_series.add(series_id)

        if duplicate_dates:
            self.logger.warning(
                "Station %s has %d duplicate date(s) across time series %s; "
                "kept the value from the lexicographically first "
                "time_series_id per date. This needs human review — the "
                "primary series is ambiguous.",
                station_number,
                duplicate_dates,
                sorted(ambiguous_series),
            )

        return [
            {k: v for k, v in obs.items() if k != "_series_id"}
            for obs in kept.values()
        ]
