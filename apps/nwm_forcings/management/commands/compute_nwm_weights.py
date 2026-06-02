"""One-time management command: compute and save NWM basin spatial weights.

Steps:
  1. Download a single NWM sample file to get the grid coordinates.
  2. For each of the 37 EA-LSTM basins, fetch the USGS watershed polygon
     from the NLDI API.
  3. Find all NWM grid cells inside each polygon.
  4. Save y/x indices + centroid to data/nwm_weights/{usgs_id}.npz.

Usage:
    python manage.py compute_nwm_weights
    python manage.py compute_nwm_weights --sample-file /path/to/existing.nc
"""
from __future__ import annotations

import logging
import tempfile
from datetime import date, timedelta
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.nwm_forcings.constants import EA_LSTM_USGS_IDS
from apps.nwm_forcings.grid import load_grid_from_file
from apps.nwm_forcings.weights import find_cells_in_polygon, save_weights

logger = logging.getLogger(__name__)

NLDI_BASIN_URL = (
    "https://api.water.usgs.gov/nldi/linked-data"
    "/nwissite/USGS-{usgs_id}/basin?f=json"
)


def _fetch_basin_polygon(usgs_id: str) -> list[tuple[float, float]] | None:
    """Return exterior ring coordinates [(lon, lat), ...] from NLDI."""
    url = NLDI_BASIN_URL.format(usgs_id=usgs_id)
    try:
        resp = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        logger.warning("NLDI request failed for %s: %s", usgs_id, exc)
        return None
    if not resp.ok:
        logger.warning("NLDI HTTP %s for %s", resp.status_code, usgs_id)
        return None
    geojson = resp.json()
    features = geojson.get("features", [])
    if not features:
        logger.warning("No NLDI features for %s", usgs_id)
        return None
    geom = features[0]["geometry"]
    if geom["type"] == "Polygon":
        return geom["coordinates"][0]
    if geom["type"] == "MultiPolygon":
        rings = [p[0] for p in geom["coordinates"]]
        return max(rings, key=len)
    logger.warning("Unexpected geometry type %s for %s", geom["type"], usgs_id)
    return None


def _basin_centroid(coords: list[tuple[float, float]]) -> tuple[float, float]:
    """Return (lat, lon) centroid from ring coordinates."""
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _download_sample_file(nomads_base: str) -> Path:
    """Download the most recent available NWM analysis file to a temp path."""
    _tmp_fd = tempfile.NamedTemporaryFile(delete=False, suffix=".nc")
    tmp = Path(_tmp_fd.name)
    _tmp_fd.close()
    for days_back in range(1, 4):
        target_date = date.today() - timedelta(days=days_back)
        date_str = target_date.strftime("%Y%m%d")
        url = (
            f"{nomads_base}/nwm.{date_str}/forcing_analysis_assim"
            f"/nwm.t00z.analysis_assim.forcing.tm00.conus.nc"
        )
        try:
            resp = requests.get(url, timeout=120, stream=True)
        except requests.RequestException:
            continue
        if resp.ok:
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    fh.write(chunk)
            logger.info("Downloaded sample file from %s", url)
            return tmp
    raise RuntimeError("Could not download any sample NWM file from NOMADS")


class Command(BaseCommand):
    help = "Compute and save NWM basin spatial weight indices (one-time setup)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--sample-file",
            type=str,
            default=None,
            help="Path to an existing NWM NetCDF file (skips download)",
        )
        parser.add_argument(
            "--usgs-id",
            type=str,
            default=None,
            help="Compute weights for a single station only (for testing)",
        )

    def handle(self, *args, **options):
        weights_dir = Path(settings.NWM_WEIGHTS_DIR)
        weights_dir.mkdir(parents=True, exist_ok=True)

        sample_path = None
        downloaded = False
        try:
            if options["sample_file"]:
                sample_path = Path(options["sample_file"])
                self.stdout.write(f"Using provided sample file: {sample_path}")
            else:
                self.stdout.write("Downloading sample NWM file for grid coordinates...")
                sample_path = _download_sample_file(settings.NWM_NOMADS_BASE)
                downloaded = True

            self.stdout.write("Loading NWM grid coordinates...")
            grid = load_grid_from_file(sample_path)
            self.stdout.write(
                f"Grid shape: {grid['ny']} x {grid['nx']} "
                f"({grid['ny'] * grid['nx']:,} cells)"
            )

            station_ids = (
                [options["usgs_id"]]
                if options["usgs_id"]
                else EA_LSTM_USGS_IDS
            )

            success = 0
            for usgs_id in station_ids:
                self.stdout.write(f"  {usgs_id}: fetching NLDI basin polygon...", ending="")
                coords = _fetch_basin_polygon(usgs_id)
                if coords is None:
                    self.stdout.write(self.style.WARNING(" SKIPPED (no polygon)"))
                    continue

                y_idx, x_idx = find_cells_in_polygon(grid["lats"], grid["lons"], coords)
                if len(y_idx) == 0:
                    self.stdout.write(self.style.WARNING(" SKIPPED (0 cells in polygon)"))
                    continue

                centroid_lat, centroid_lon = _basin_centroid(coords)
                out_path = weights_dir / f"{usgs_id}.npz"
                save_weights(out_path, y_idx, x_idx, centroid_lat, centroid_lon)
                self.stdout.write(
                    self.style.SUCCESS(f" {len(y_idx)} cells -> {out_path.name}")
                )
                success += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDone: {success}/{len(station_ids)} stations weighted."
                )
            )

        finally:
            if downloaded and sample_path and sample_path.exists():
                sample_path.unlink()
