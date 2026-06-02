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
from .processors import extract_hourly_basin_record, aggregate_hourly_to_daily
from .weights import load_weights

logger = logging.getLogger(__name__)


def ingest_day(
    ingest_date: date,
    hourly_files: Sequence[Path],
) -> int:
    """Process 24 hourly NWM files for *ingest_date* and write BasinForcing rows.

    Args:
        ingest_date: Calendar date the forcings represent.
        hourly_files: Sequence of 24 paths to hourly NetCDF files (hours 0–23).

    Returns:
        Number of BasinForcing rows upserted.
    """
    weights_dir = Path(settings.NWM_WEIGHTS_DIR)
    doy = ingest_date.timetuple().tm_yday
    updated = 0

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

        # Deduplicate by resolved path to avoid bias in mean calculations from fill-duplicated files
        seen_paths: set[str] = set()
        unique_files: list[Path] = []
        for p in hourly_files:
            key = str(p.resolve())
            if key not in seen_paths:
                seen_paths.add(key)
                unique_files.append(p)

        hourly_records = []
        for nc_path in unique_files:
            try:
                record = extract_hourly_basin_record(nc_path, basin_weights)
                hourly_records.append(record)
            except Exception as exc:
                logger.warning("Error extracting %s from %s: %s", usgs_id, nc_path.name, exc)

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
