"""
Parquet Forecast Importer Service.

Imports NWRFC 6-hourly forecast runs from a parquet file into the ForecastRun table.
Parquet schema: lid, issuance_time, sim_time, simulation (cfs)

Handles:
- Station resolution: matches lid → Station.station_number, creates missing records
  from MasterStation or the NOAA Water API.
- forecast_type inference: derived from actual horizon of each run.
- Upsert semantics: parquet is treated as source of truth; existing DB records are
  overwritten when (station, source, run_date, forecast_type, is_forecast) matches.
- Bulk inserts in configurable batches to keep memory bounded.
"""

import logging
from datetime import datetime, timezone
from typing import IO, Dict, List, Optional, Tuple

import pandas as pd
import pyarrow.parquet as pq
import requests
from django.db import transaction

from apps.streamflow.models import ForecastRun, MasterStation, Station

logger = logging.getLogger(__name__)

NOAA_API_BASE = "https://api.water.noaa.gov/nwps/v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def infer_forecast_type(horizon_hours: float) -> str:
    """Map a forecast horizon (hours) to a ForecastRun.forecast_type choice."""
    if horizon_hours <= 7 * 24:
        return "short"
    elif horizon_hours <= 10 * 24:
        return "medium"
    return "long"


def iter_forecast_runs(parquet_path: str):
    """
    Stream (lid, issuance_time, data_points, forecast_type) tuples.

    Reads one row group at a time so a 144M-row file never lands in memory.
    A single (lid, issuance_time) group can straddle a row-group boundary,
    so the last issuance_time seen is held back until a later row group
    proves it complete. The file is ordered by issuance_time, which is what
    makes that single-key carry sufficient — verified across all 1,487 row
    groups of the WY2006-2026 archive, and re-checked here per row group so
    a future unsorted file fails loudly instead of silently splitting runs.
    """
    pf = pq.ParquetFile(parquet_path)
    carry = {}  # (lid, issuance_time) -> list[(sim_time, value)]
    prev_max_iss = None

    for rg in range(pf.metadata.num_row_groups):
        table = pf.read_row_groups([rg])
        lids = table.column("lid").to_pylist()
        issuances = table.column("issuance_time").to_pylist()
        sim_times = table.column("sim_time").to_pylist()
        values = table.column("simulation (cfs)").to_pylist()

        if prev_max_iss is not None and min(issuances) < prev_max_iss:
            raise ValueError(
                f"{parquet_path} is not sorted by issuance_time at row group "
                f"{rg} (min {min(issuances)} < previous max {prev_max_iss}); "
                "the streaming buffer would split runs"
            )

        buckets = dict(carry)
        carry = {}
        for lid, iss, st, val in zip(lids, issuances, sim_times, values):
            buckets.setdefault((lid, iss), []).append((st, val))

        # Hold back every group at the highest issuance_time in this row
        # group — those may continue into the next one.
        max_iss = max(issuances)
        prev_max_iss = max_iss
        for key in list(buckets):
            if key[1] == max_iss:
                carry[key] = buckets.pop(key)

        for key, points in buckets.items():
            yield _build_run(key, points)

    for key, points in carry.items():
        yield _build_run(key, points)


def _build_run(key, points):
    """Turn a buffered group into (lid, issuance_utc, data_points, forecast_type)."""
    lid, issuance = key
    points.sort(key=lambda p: p[0])
    horizon_hours = (points[-1][0] - issuance).total_seconds() / 3600
    data = [
        {"date": st.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": float(val)}
        for st, val in points
    ]
    if issuance.tzinfo is None:
        issuance = issuance.replace(tzinfo=timezone.utc)
    return lid, issuance, data, infer_forecast_type(horizon_hours)


def _fetch_gauge_metadata(lid: str) -> Optional[Dict]:
    """
    Fetch gauge metadata from the NOAA Water API for a single LID.

    Tries the direct gauge endpoint first; if that returns 404 (common for
    Canadian/BC stations in NWRFC), falls back to searching the full NWRFC
    gauge list.

    Returns a dict with keys: name, latitude, longitude, state_code, rfc_code
    or None if the gauge cannot be found.
    """
    # --- Direct lookup ---
    url = f"{NOAA_API_BASE}/gauges/{lid}"
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "name": data.get("name", f"NOAA Station {lid}"),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "state_code": (data.get("state") or {}).get("abbreviation", ""),
                "rfc_code": (data.get("rfc") or {}).get("abbreviation", "NWRFC"),
            }
        if resp.status_code != 404:
            resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("NOAA API direct lookup error for %s: %s", lid, exc)
        return None

    # --- Fallback: search NWRFC gauge list (catches BC/Canadian stations) ---
    logger.info("Direct lookup returned 404 for %s; searching NWRFC gauge list…", lid)
    try:
        resp = requests.get(
            f"{NOAA_API_BASE}/gauges",
            params={"rfc": "NWRFC", "limit": 10000},
            timeout=60,
        )
        resp.raise_for_status()
        gauges = resp.json().get("gauges", [])
        for gauge in gauges:
            if gauge.get("lid") == lid:
                return {
                    "name": gauge.get("name", f"NOAA Station {lid}"),
                    "latitude": gauge.get("latitude"),
                    "longitude": gauge.get("longitude"),
                    "state_code": (gauge.get("state") or {}).get("abbreviation", ""),
                    "rfc_code": (gauge.get("rfc") or {}).get("abbreviation", "NWRFC"),
                }
        logger.warning("NOAA API: gauge %s not found in NWRFC gauge list", lid)
    except requests.exceptions.Timeout:
        logger.warning(
            "NOAA API timed out searching NWRFC gauge list for %s. "
            "The station may be Canadian/BC — add it manually via the Django admin "
            "or re-run import_noaa_rfc_stations --rfc NWRFC when the API is available.",
            lid,
        )
    except requests.RequestException as exc:
        logger.error("NOAA API NWRFC list error while searching for %s: %s", lid, exc)

    return None


def _create_station_from_metadata(lid: str, meta: Dict) -> Tuple[Station, bool]:
    """
    Ensure MasterStation and Station exist for a LID given API metadata.

    Returns (station, created) like update_or_create.
    """
    MasterStation.objects.update_or_create(
        noaa_lid=lid,
        defaults={
            "station_number": lid,
            "station_name": meta["name"],
            "agency": "NOAA_RFC",
            "latitude": meta["latitude"],
            "longitude": meta["longitude"],
            "state_code": meta["state_code"],
            "rfc_code": meta["rfc_code"],
            "huc_code": "",
        },
    )
    station, created = Station.objects.update_or_create(
        station_number=lid,
        defaults={
            "name": meta["name"],
            "agency": "NOAA_RFC",
            "latitude": meta["latitude"],
            "longitude": meta["longitude"],
            "state": meta["state_code"],
            # New archive-only gauges are created inactive so they do not join
            # pull configurations or active-station counts. NWRFC configs must
            # keep skip_inactive_stations off, or they would filter these out.
            "is_active": False,
        },
    )
    return station, created


def _create_station_from_master(lid: str, master: MasterStation) -> Station:
    """Promote an existing MasterStation record into the Station table."""
    station, _ = Station.objects.update_or_create(
        station_number=lid,
        defaults={
            "name": master.station_name,
            "agency": "NOAA_RFC",
            "latitude": master.latitude,
            "longitude": master.longitude,
            "state": master.state_code,
            # New archive-only gauges are created inactive so they do not join
            # pull configurations or active-station counts. NWRFC configs must
            # keep skip_inactive_stations off, or they would filter these out.
            "is_active": False,
        },
    )
    return station


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class ParquetForecastImporter:
    """Import 6-hourly NWRFC forecast runs from a parquet file."""

    def __init__(self, stdout: IO, stderr: IO, style):
        self.stdout = stdout
        self.stderr = stderr
        self.style = style

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        parquet_path: str,
        dry_run: bool = False,
        filter_lids: Optional[List[str]] = None,
        batch_size: int = 500,
    ) -> Dict:
        """
        Execute the full import pipeline.

        Returns a summary dict with counts of created/updated/skipped/failed runs.
        """
        self._log(f"Scanning LIDs in {parquet_path}…")
        pf = pq.ParquetFile(parquet_path)
        self._validate_schema(pf.schema_arrow.names)
        lids = set()
        for rg in range(pf.metadata.num_row_groups):
            lids.update(pf.read_row_groups([rg], columns=["lid"]).column("lid").to_pylist())
        lids = sorted(lids)
        if filter_lids:
            lids = [l for l in lids if l in set(filter_lids)]
        self._log(f"Found {len(lids)} unique LID(s)")

        station_map, skipped_lids = self._resolve_stations(lids, dry_run)
        skipped = set(skipped_lids)
        wanted = set(filter_lids) if filter_lids else None

        totals = {"created": 0, "updated": 0, "failed": 0, "anomalies": 0}
        batch = []
        for idx, (lid, issuance, data, ftype) in enumerate(
            iter_forecast_runs(parquet_path), 1
        ):
            if wanted is not None and lid not in wanted:
                continue
            if lid in skipped:
                totals["failed"] += 1
                continue

            last = datetime.strptime(data[-1]["date"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if last < issuance:
                totals["anomalies"] += 1
                self._warn(
                    f"  Negative horizon for {lid} @ {issuance.isoformat()} "
                    f"(last point {data[-1]['date']}) — importing as-is"
                )
            elif len(data) == 1:
                totals["anomalies"] += 1

            if dry_run:
                totals["created"] += 1
            else:
                batch.append(ForecastRun(
                    station=station_map[lid], source="NOAA_RFC", run_date=issuance,
                    forecast_type=ftype, is_forecast=True, data=data,
                ))
                if len(batch) >= batch_size:
                    c, u = self._flush_batch(batch, dry_run)
                    totals["created"] += c
                    totals["updated"] += u
                    batch = []

            if idx % 100000 == 0:
                self._log(f"  {idx:,} runs processed…")

        if batch and not dry_run:
            c, u = self._flush_batch(batch, dry_run)
            totals["created"] += c
            totals["updated"] += u

        if dry_run:
            self._log(
                self.style.SUCCESS(
                    f"\nDry run complete — would process {totals['created']:,} forecast run(s) "
                    f"across {len(station_map)} station(s). "
                    f"Anomalies: {totals['anomalies']:,}. "
                    f"Nothing was written to the database."
                )
            )
        else:
            self._log(
                self.style.SUCCESS(
                    f"\nImport complete — "
                    f"upserted: {totals['created']:,}  "
                    f"failed: {totals['failed']:,}  "
                    f"anomalies: {totals['anomalies']:,}"
                )
            )
        return totals

    # ------------------------------------------------------------------
    # Station resolution
    # ------------------------------------------------------------------

    def _resolve_stations(
        self, lids: List[str], dry_run: bool
    ) -> Tuple[Dict[str, Station], List[str]]:
        """
        For each LID: find existing Station, promote MasterStation, or fetch from API.

        Returns (station_map, skipped_lids).
        """
        station_map: Dict[str, Station] = {}
        skipped: List[str] = []

        existing = {s.station_number: s for s in Station.objects.filter(station_number__in=lids)}
        masters = {m.noaa_lid: m for m in MasterStation.objects.filter(noaa_lid__in=lids)}

        for lid in lids:
            if lid in existing:
                station_map[lid] = existing[lid]
                continue

            # Try to promote from MasterStation
            if lid in masters:
                if dry_run:
                    self._log(f"  [DRY RUN] Would create Station from MasterStation: {lid}")
                    station_map[lid] = None  # placeholder — won't be flushed in dry run
                else:
                    station = _create_station_from_master(lid, masters[lid])
                    station_map[lid] = station
                    self._log(self.style.SUCCESS(f"  Created Station from MasterStation: {lid}"))
                continue

            # Fall back to NOAA API
            self._log(f"  Fetching metadata from NOAA API for {lid}…")
            meta = _fetch_gauge_metadata(lid)
            if meta is None:
                self._warn(f"  Could not resolve station {lid} — will skip.")
                skipped.append(lid)
                continue

            if dry_run:
                self._log(
                    f"  [DRY RUN] Would create Station + MasterStation from API: "
                    f"{lid} - {meta['name']} (RFC: {meta['rfc_code']})"
                )
                station_map[lid] = None
            else:
                station, _ = _create_station_from_metadata(lid, meta)
                station_map[lid] = station
                self._log(self.style.SUCCESS(f"  Created Station from NOAA API: {lid} - {meta['name']}"))

        return station_map, skipped

    # ------------------------------------------------------------------
    # Build & flush
    # ------------------------------------------------------------------

    def _build_forecast_run(
        self,
        station: Station,
        issuance_time,
        group: pd.DataFrame,
    ) -> Optional[ForecastRun]:
        """Build an unsaved ForecastRun from a grouped DataFrame slice."""
        try:
            group_sorted = group.sort_values("sim_time")

            # Compute horizon in hours to infer type
            horizon_hours = (
                group_sorted["sim_time"].iloc[-1] - issuance_time
            ).total_seconds() / 3600
            forecast_type = infer_forecast_type(horizon_hours)

            # Build data array matching existing format: {date: ISO-Z, value: float}
            data = [
                {
                    "date": row["sim_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "value": float(row["simulation (cfs)"]),
                }
                for _, row in group_sorted.iterrows()
            ]

            # Convert issuance_time to Python datetime with UTC tz
            run_date = issuance_time.to_pydatetime()
            if run_date.tzinfo is None:
                run_date = run_date.replace(tzinfo=timezone.utc)

            return ForecastRun(
                station=station,
                source="NOAA_RFC",
                run_date=run_date,
                forecast_type=forecast_type,
                data=data,
            )
        except Exception as exc:
            logger.error(
                "Failed to build ForecastRun for %s @ %s: %s",
                station.station_number,
                issuance_time,
                exc,
            )
            return None

    def _flush_batch(self, batch, dry_run):
        """
        Upsert a batch of ForecastRun objects. Parquet is source of truth.

        Exceptions propagate. A swallowed failure here previously reported
        "upserted: 0, failed: 0", making a total failure indistinguishable
        from a successful no-op.
        """
        if dry_run:
            return 0, 0

        with transaction.atomic():
            results = ForecastRun.objects.bulk_create(
                batch,
                update_conflicts=True,
                update_fields=["data"],
                unique_fields=[
                    "station", "source", "run_date", "forecast_type", "is_forecast"
                ],
            )
        return len(results), 0

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_schema(self, columns) -> None:
        required = {"lid", "issuance_time", "sim_time", "simulation (cfs)"}
        missing = required - set(columns)
        if missing:
            raise ValueError(f"Parquet missing required columns: {missing}")

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        self.stdout.write(msg)

    def _warn(self, msg: str) -> None:
        self.stderr.write(self.style.WARNING(msg))
