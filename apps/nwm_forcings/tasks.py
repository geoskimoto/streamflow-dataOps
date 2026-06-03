"""Celery tasks for NWM Analysis Assim daily forcing ingestion."""
from __future__ import annotations

import logging
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

from celery import shared_task
from django.conf import settings

from apps.streamflow.models import BasinForcing, Station
from .constants import EA_LSTM_USGS_IDS
from .models import NWMIngestionLog
from .nwm_client import build_nomads_url, download_file
from .processors import extract_all_basins_from_file, aggregate_hourly_to_daily
from .weights import load_weights

logger = logging.getLogger(__name__)


def ingest_day(
    ingest_date: date,
    hourly_files: Sequence[Path],
) -> int:
    """Process 24 hourly NWM files for *ingest_date* and write BasinForcing rows.

    Opens each unique file exactly once and extracts all basin values in a
    single read pass (O(n_files) I/O rather than O(n_files × n_stations)).

    Args:
        ingest_date: Calendar date the forcings represent.
        hourly_files: Sequence of 24 paths to hourly NetCDF files (hours 0–23).

    Returns:
        Number of BasinForcing rows upserted.
    """
    weights_dir = Path(settings.NWM_WEIGHTS_DIR)
    doy = ingest_date.timetuple().tm_yday

    # --- Step 1: pre-load all valid stations (weights + DB lookup) ---
    valid_stations: list[tuple[str, object, dict]] = []
    for usgs_id in EA_LSTM_USGS_IDS:
        weight_path = weights_dir / f"{usgs_id}.npz"
        if not weight_path.exists():
            logger.warning("No weight file for %s — skipping", usgs_id)
            continue
        try:
            basin_weights = load_weights(weight_path)
        except Exception as exc:
            logger.warning("Failed to load weights for %s: %s", usgs_id, exc)
            continue
        try:
            station = Station.objects.get(station_number=usgs_id, agency="USGS")
        except Station.DoesNotExist:
            logger.warning("Station %s not in DB — skipping", usgs_id)
            continue
        valid_stations.append((usgs_id, station, basin_weights))

    if not valid_stations:
        return 0

    # --- Step 2: deduplicate files (avoid mean bias from fill-duplicated paths) ---
    seen_paths: set[str] = set()
    unique_files: list[Path] = []
    for p in hourly_files:
        key = str(p.resolve())
        if key not in seen_paths:
            seen_paths.add(key)
            unique_files.append(p)

    # --- Step 3: open each file once, extract all basins in a single read pass ---
    basin_weights_list = [bw for _, _, bw in valid_stations]
    hourly_records_by_station: dict[str, list[dict]] = {uid: [] for uid, _, _ in valid_stations}

    for nc_path in unique_files:
        try:
            all_records = extract_all_basins_from_file(nc_path, basin_weights_list)
            for (usgs_id, _, _), record in zip(valid_stations, all_records):
                hourly_records_by_station[usgs_id].append(record)
        except Exception as exc:
            logger.warning("Error extracting from %s: %s", nc_path.name, exc)

    # --- Step 4: aggregate and write one DB row per station ---
    updated = 0
    for usgs_id, station, basin_weights in valid_stations:
        hourly_records = hourly_records_by_station[usgs_id]
        if len(hourly_records) < 20:
            logger.warning(
                "Only %d/24 hours for %s on %s — skipping",
                len(hourly_records), usgs_id, ingest_date,
            )
            continue
        daily = aggregate_hourly_to_daily(hourly_records, basin_weights["centroid_lat"], doy)
        BasinForcing.objects.update_or_create(
            station=station,
            date=ingest_date,
            source="nwm",
            defaults={
                "prcp_mm_day": daily["prcp_mm_day"],
                "tmax_c": daily["tmax_c"],
                "tmin_c": daily["tmin_c"],
                "srad_w_m2": daily["srad_w_m2"],
                "vp_pa": daily["vp_pa"],
                "dayl_s": daily["dayl_s"],
            },
        )
        updated += 1

    return updated


@shared_task(name="apps.nwm_forcings.tasks.ingest_nwm_forcings_daily")
def ingest_nwm_forcings_daily() -> dict:
    """Download and ingest yesterday's NWM Analysis Assim forcings.

    Returns summary dict: {"date": str, "stations_updated": int, "status": str}
    """
    yesterday = date.today() - timedelta(days=1)
    temp_dir = Path(settings.NWM_TEMP_DIR) / yesterday.strftime("%Y%m%d")
    temp_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[tuple[int, Path]] = []
    failed_hours: list[int] = []

    try:
        for hour in range(24):
            url = build_nomads_url(settings.NWM_NOMADS_BASE, yesterday, hour)
            dest = temp_dir / f"nwm_t{hour:02d}z.nc"
            try:
                download_file(url, dest)
                downloaded.append((hour, dest))
            except Exception as exc:
                logger.warning("Hour %02d download failed: %s", hour, exc)
                failed_hours.append(hour)

        if not downloaded:
            msg = f"All 24 files failed to download for {yesterday}"
            logger.error(msg)
            NWMIngestionLog.objects.update_or_create(
                ingest_date=yesterday,
                defaults={"stations_updated": 0, "status": "failed", "error_message": msg},
            )
            return {"date": str(yesterday), "stations_updated": 0, "status": "failed"}

        # Fill missing hours with nearest available file
        dl_map = {h: p for h, p in downloaded}
        last_good = downloaded[0][1]
        ordered = []
        for h in range(24):
            ordered.append(dl_map.get(h, last_good))
            if h in dl_map:
                last_good = dl_map[h]

        stations_updated = ingest_day(yesterday, ordered)
        if stations_updated == 0:
            status = "failed"
            error_msg = "No stations updated — check weight files and station DB entries"
        elif failed_hours:
            status = "partial"
            error_msg = f"Missing hours: {failed_hours}"
        else:
            status = "success"
            error_msg = ""

        NWMIngestionLog.objects.update_or_create(
            ingest_date=yesterday,
            defaults={
                "stations_updated": stations_updated,
                "status": status,
                "error_message": error_msg,
            },
        )
        return {"date": str(yesterday), "stations_updated": stations_updated, "status": status}

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
