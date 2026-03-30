"""
Parquet Forecast Importer Service.

Imports NWRFC 6-hourly forecast runs from a parquet file into the ForecastRun table.
Parquet schema: lid, issuance_time, sim_time, simulation (cfs)

Handles:
- Station resolution: matches lid → Station.station_number, creates missing records
  from MasterStation or the NOAA Water API.
- forecast_type inference: derived from actual horizon of each run.
- Upsert semantics: parquet is treated as source of truth; existing DB records are
  overwritten when (station, source, run_date, forecast_type) matches.
- Bulk inserts in configurable batches to keep memory bounded.
"""

import logging
from datetime import timezone
from typing import IO, Dict, List, Optional, Tuple

import pandas as pd
import requests
from django.db import transaction

from apps.streamflow.models import ForecastRun, MasterStation, Station

logger = logging.getLogger(__name__)

NOAA_API_BASE = "https://api.water.noaa.gov/nwps/v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_forecast_type(horizon_hours: float) -> str:
    """Map a forecast horizon (hours) to a ForecastRun.forecast_type choice."""
    if horizon_hours <= 7 * 24:
        return "short"
    elif horizon_hours <= 10 * 24:
        return "medium"
    return "long"


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
            "is_active": True,
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
            "is_active": True,
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
        self._log(f"Loading parquet: {parquet_path}")
        df = pd.read_parquet(parquet_path)
        self._validate_schema(df)

        if filter_lids:
            df = df[df["lid"].isin(filter_lids)]
            self._log(f"Filtered to {len(filter_lids)} station(s): {filter_lids}")

        lids = df["lid"].unique().tolist()
        self._log(f"Found {len(lids)} unique LID(s) in parquet")

        # --- Resolve stations ---
        station_map, skipped_lids = self._resolve_stations(lids, dry_run)
        if skipped_lids:
            self._warn(f"Skipping {len(skipped_lids)} unresolvable LID(s): {skipped_lids}")
            df = df[~df["lid"].isin(skipped_lids)]

        if df.empty:
            self._warn("No rows to import after station resolution.")
            return {"created": 0, "updated": 0, "skipped": 0, "failed": 0}

        # --- Make timestamps UTC-aware ---
        if df["issuance_time"].dt.tz is None:
            df["issuance_time"] = df["issuance_time"].dt.tz_localize("UTC")
        if df["sim_time"].dt.tz is None:
            df["sim_time"] = df["sim_time"].dt.tz_localize("UTC")

        # --- Build ForecastRun objects grouped by (lid, issuance_time) ---
        totals = {"created": 0, "updated": 0, "failed": 0}
        batch: List[ForecastRun] = []

        groups = df.groupby(["lid", "issuance_time"], sort=False)
        total_groups = len(groups)
        self._log(f"Processing {total_groups:,} forecast run groups…")

        for idx, ((lid, issuance_time), group) in enumerate(groups, 1):
            station = station_map.get(lid)
            # In dry-run, station may be None (placeholder); count as would-process
            if station is None and not dry_run:
                totals["failed"] += 1
                continue

            if dry_run:
                # Count without building real objects (station may be None placeholder)
                totals["created"] += 1
            else:
                run_obj = self._build_forecast_run(station, issuance_time, group)
                if run_obj is None:
                    totals["failed"] += 1
                    continue
                batch.append(run_obj)

                if len(batch) >= batch_size:
                    c, u = self._flush_batch(batch, dry_run)
                    totals["created"] += c
                    totals["updated"] += u
                    batch = []

            if idx % 5000 == 0:
                self._log(f"  {idx:,}/{total_groups:,} groups processed…")

        # Flush remainder
        if batch and not dry_run:
            c, u = self._flush_batch(batch, dry_run)
            totals["created"] += c
            totals["updated"] += u

        if dry_run:
            self._log(
                self.style.SUCCESS(
                    f"\nDry run complete — would process {totals['created']:,} forecast run(s) "
                    f"across {len(station_map)} station(s). "
                    f"Nothing was written to the database."
                )
            )
        else:
            self._log(
                self.style.SUCCESS(
                    f"\nImport complete — "
                    f"upserted: {totals['created']:,}  "
                    f"failed: {totals['failed']:,}"
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
            forecast_type = _infer_forecast_type(horizon_hours)

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

    def _flush_batch(
        self, batch: List[ForecastRun], dry_run: bool
    ) -> Tuple[int, int]:
        """
        Upsert a batch of ForecastRun objects.

        Parquet is source of truth: existing records are overwritten.
        Returns (created_count, updated_count).
        """
        if dry_run:
            return 0, 0

        try:
            with transaction.atomic():
                results = ForecastRun.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    update_fields=["data"],
                    unique_fields=["station", "source", "run_date", "forecast_type"],
                )
            # Django sets pk on created rows but not on updated rows when using
            # update_conflicts; count rows without pk as updated.
            created = sum(1 for r in results if r._state.adding is False and r.pk)
            # Simpler: use len(results) for total, can't easily split created vs updated
            # via bulk_create. We'll report total as created+updated combined.
            return len(results), 0
        except Exception as exc:
            logger.error("Batch flush failed: %s", exc)
            return 0, 0

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_schema(self, df: pd.DataFrame) -> None:
        required = {"lid", "issuance_time", "sim_time", "simulation (cfs)"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Parquet missing required columns: {missing}")

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        self.stdout.write(msg)

    def _warn(self, msg: str) -> None:
        self.stderr.write(self.style.WARNING(msg))
