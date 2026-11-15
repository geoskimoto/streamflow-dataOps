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
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DISCHARGE_PARAMETER_CODE = "00060"
DAILY_MEAN_STATISTIC_ID = "00003"

# Measured 2026-11-15: the `continuous` collection carries discharge under
# statistic_id 00011 ("instantaneous"), not 00003 (daily mean).
CONTINUOUS_STATISTIC_ID = "00011"

# A 15-minute series is ~35,040 points per year and `limit` caps at 50,000,
# so a multi-year request must be split. 180 days is ~17,280 points at 15-min
# resolution, which leaves generous headroom — but a 5-minute series is
# ~51,840 points per 180 days, which *already* exceeds the 50,000 cap and is
# only recovered by `next`-link pagination. Widening the window would make
# that worse (more pages per window, not fewer requests overall, since the
# page cap — not the window — is what forces pagination once density rises).
# Do not raise this without re-deriving the pagination math for the densest
# series actually seen.
INSTANTANEOUS_WINDOW_DAYS = 180

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

    def get_instantaneous(
        self,
        station_number: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        _retries: int = DEFAULT_RETRIES,
    ) -> List[Dict]:
        """Return instantaneous (realtime_15min) discharge for one station.

        Unlike ``get_daily_mean``, ``start_date`` is required and an explicit
        ``datetime`` range is always sent: the ``continuous`` collection
        silently returns only the most recent ~1 year of data when no
        ``datetime`` filter is given, which would truncate a historical pull
        without any error. ``end_date`` defaults to now (UTC) rather than
        being omitted, for the same reason.

        The range is split into windows of at most
        ``INSTANTANEOUS_WINDOW_DAYS`` days — a multi-year 15-minute series
        would otherwise exceed the API's 50,000-row page cap — and fetched
        one paginated request-chain per window.

        Request volume: windows are ``ceil(days / INSTANTANEOUS_WINDOW_DAYS)``
        requests per station. For a historical backfill across the ~36
        CAMELS-overlap stations that is roughly 252 requests for 3 years, 756
        for 10 years, and ~2,200 for 30 years, against a 1,000
        requests/hour API key budget. This method does no pacing of its
        own — a multi-year, multi-station historical pull must be paced by
        the caller (a ``SOURCE_PACING``-style entry, or a chunked backfill
        spread over time), the same as any other bulk USGS pull.

        ``start_date`` and ``end_date`` are normalised to tz-aware UTC
        internally, so a naive input is accepted (treated as already UTC)
        rather than raising deep inside window computation. ``end_date``
        before ``start_date`` raises ``ValueError`` before any request is
        issued — some OGC servers silently ignore a malformed ``datetime``
        interval and fall back to the default ~1-year window, a truncation
        the provenance guard cannot detect since station/parameter/statistic/
        unit all still match. ``end_date == start_date`` is accepted, not an
        error: it is a well-defined (if trivial) single zero-width-window
        request, not a sign of a reversed-argument bug.

        Args:
            station_number: bare USGS site id, e.g. ``"12200500"``.
            start_date: inclusive start (required).
            end_date: inclusive end, or ``None`` for "up to now".
            _retries: retry budget for transient failures; 0 disables retrying.

        Returns:
            Observation dicts with keys ``observed_at`` (full tz-aware UTC
            timestamp — never truncated to midnight, unlike daily_mean),
            ``discharge`` (cfs, float), ``unit``, ``type``, ``quality_code``.
            Exactly one observation per ``observed_at`` is returned even if
            the station has multiple time series for this parameter/statistic.

        Raises:
            ValueError: if ``end_date`` is given and is earlier than
                ``start_date``.
        """
        start = self._normalize_utc(start_date)
        stop = (
            self._normalize_utc(end_date)
            if end_date is not None
            else datetime.now(timezone.utc)
        )

        if stop < start:
            raise ValueError(
                f"get_instantaneous for station {station_number}: end_date "
                f"({stop.isoformat()}) is before start_date "
                f"({start.isoformat()}); refusing to issue a reversed range."
            )

        windows = self._windows(start, stop, INSTANTANEOUS_WINDOW_DAYS)

        self.logger.info(
            "Fetching USGS instantaneous discharge for %s across %d "
            "window(s) (%s to %s)",
            station_number,
            len(windows),
            start,
            stop,
        )

        features: List[Dict] = []
        for window_start, window_end in windows:
            params = {
                "monitoring_location_id": f"USGS-{station_number}",
                "parameter_code": DISCHARGE_PARAMETER_CODE,
                "statistic_id": CONTINUOUS_STATISTIC_ID,
                "limit": PAGE_LIMIT,
                "skipGeometry": "true",
                "datetime": (
                    f"{self._as_iso(window_start)}/{self._as_iso(window_end)}"
                ),
            }
            features.extend(
                self._fetch_all_pages(
                    params, _retries, station_number, collection="continuous"
                )
            )

        observations = self._parse_instantaneous(features, station_number)

        self.logger.info(
            "Retrieved %d instantaneous records for %s",
            len(observations),
            station_number,
        )
        return observations

    # -- internals --------------------------------------------------------

    @staticmethod
    def _normalize_utc(value: datetime) -> datetime:
        """Coerce a naive or differently-offset datetime to tz-aware UTC.

        A naive value is treated as already being UTC (not localised),
        matching how the rest of this client treats naive input. Applied to
        ``start_date``/``end_date`` up front in ``get_instantaneous`` so a
        naive ``start_date`` is accepted consistently regardless of whether
        ``end_date`` is also given — before this normalisation lived here,
        a naive ``start_date`` with a defaulted (aware) ``end_date`` raised
        ``TypeError`` inside ``_windows`` (naive/aware datetimes are not
        comparable), which meant a differently-shaped failure depending on
        argument order.
        """
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _as_iso(value: datetime) -> str:
        """Format a datetime as a full UTC ISO-8601 timestamp.

        Unlike ``_as_date`` (daily-mean, date-only), the instantaneous path
        must never drop the time component.
        """
        return USGSWaterDataClient._normalize_utc(value).isoformat()

    @staticmethod
    def _windows(
        start: datetime, end: datetime, window_days: int
    ) -> List[Tuple[datetime, datetime]]:
        """Split ``[start, end]`` into consecutive windows of at most
        ``window_days``, covering the range with no gap and no overlap.

        Precondition: ``start <= end`` and both tz-aware. ``get_instantaneous``
        enforces both — normalising naive input and rejecting ``end < start``
        — before calling this; this method does not re-check either.

        Adjacent windows share their boundary instant (window N's end equals
        window N+1's start) rather than leaving a gap. A point that lands
        exactly on a boundary may be returned by both requests; that is
        resolved by ``_dedupe_by_timestamp`` downstream, not here.
        """
        step = timedelta(days=window_days)
        windows: List[Tuple[datetime, datetime]] = []
        cursor = start
        while cursor < end:
            window_end = min(cursor + step, end)
            windows.append((cursor, window_end))
            cursor = window_end
        return windows or [(start, end)]

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
        self,
        params: Dict,
        retries: int,
        station_number: str,
        collection: str = "daily",
    ) -> List[Dict]:
        url = f"{self.base_url}/collections/{collection}/items"
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

    def _parse_instantaneous(
        self, features: List[Dict], station_number: str
    ) -> List[Dict]:
        """Parse ``continuous`` collection features into observation dicts.

        Mirrors ``_parse`` (daily-mean): same provenance guard, same
        ``build_quality_code`` mapping, same null/unparseable-value
        skipping. Differs only in the fields that must differ — the
        expected ``statistic_id``, and ``observed_at`` carrying the full
        timestamp instead of being truncated to midnight.
        """
        parsed: List[Dict] = []
        series_ids = set()
        skipped = 0
        mismatches: Dict[str, set] = {}

        expected = {
            "monitoring_location_id": f"USGS-{station_number}",
            "parameter_code": DISCHARGE_PARAMETER_CODE,
            "statistic_id": CONTINUOUS_STATISTIC_ID,
            "unit_of_measure": DISCHARGE_UNIT_OF_MEASURE,
        }

        for feature in features:
            props = feature.get("properties") or {}
            series_id = props.get("time_series_id")
            if series_id is not None:
                series_ids.add(series_id)

            # Provenance check — see `_parse` for the full rationale. Same
            # guard, parameterised to this collection/statistic's expected
            # values.
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
                    "Unparseable USGS instantaneous record for %s at %s: "
                    "value=%r",
                    station_number,
                    raw_time,
                    raw_value,
                )
                continue

            try:
                discharge = float(raw_value)
            except (TypeError, ValueError):
                self.logger.warning(
                    "Unparseable USGS instantaneous discharge for %s at %s: %r",
                    station_number,
                    raw_time,
                    raw_value,
                )
                continue

            try:
                # fromisoformat handles the "+00:00" offset the API emits;
                # a hardcoded strptime format would break the moment USGS
                # varies precision (e.g. adds fractional seconds).
                observed_at = datetime.fromisoformat(str(raw_time))
            except ValueError:
                self.logger.warning(
                    "Unparseable USGS instantaneous timestamp for %s: %r",
                    station_number,
                    raw_time,
                )
                continue

            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            else:
                observed_at = observed_at.astimezone(timezone.utc)

            parsed.append(
                {
                    "observed_at": observed_at,
                    "discharge": discharge,
                    "unit": "cfs",
                    "type": "realtime_15min",
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
                "Each timestamp keeps exactly one deterministic value; see "
                "any duplicate-timestamp warning below for how ties were "
                "resolved.",
                station_number,
                DISCHARGE_PARAMETER_CODE,
                CONTINUOUS_STATISTIC_ID,
                sorted(series_ids),
            )

        observations = self._dedupe_by_timestamp(parsed, station_number)
        observations.sort(key=lambda o: o["observed_at"])
        return observations

    def _dedupe_by_timestamp(
        self, parsed: List[Dict], station_number: str
    ) -> List[Dict]:
        """Guarantee exactly one observation per ``observed_at``.

        Mirrors ``_dedupe_by_date``: two time series sharing a timestamp —
        or two adjacent request windows both covering their shared boundary
        instant — would otherwise produce two dicts with the same
        ``observed_at``, and ``bulk_create(update_conflicts=True)`` would
        raise "ON CONFLICT DO UPDATE command cannot affect row a second
        time". Resolution is deterministic: sort by ``(observed_at,
        time_series_id)`` and keep the first occurrence per timestamp, so
        repeated calls on the same input always pick the same winner
        regardless of feature order.
        """
        parsed_sorted = sorted(
            parsed, key=lambda o: (o["observed_at"], o.get("_series_id") or "")
        )

        kept: Dict[datetime, Dict] = {}
        duplicate_timestamps = 0
        ambiguous_series = set()

        for obs in parsed_sorted:
            when = obs["observed_at"]
            if when not in kept:
                kept[when] = obs
                continue

            duplicate_timestamps += 1
            for candidate in (kept[when], obs):
                series_id = candidate.get("_series_id")
                if series_id is not None:
                    ambiguous_series.add(series_id)

        if duplicate_timestamps:
            self.logger.warning(
                "Station %s has %d duplicate timestamp(s) across time "
                "series %s; kept the value from the lexicographically "
                "first time_series_id per timestamp.",
                station_number,
                duplicate_timestamps,
                sorted(ambiguous_series),
            )

        return [
            {k: v for k, v in obs.items() if k != "_series_id"}
            for obs in kept.values()
        ]
