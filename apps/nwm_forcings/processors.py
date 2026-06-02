"""NWM variable extraction, unit conversion, derivation, and daily aggregation.

Processing chain per hourly file:
  1. Open NetCDF with xarray
  2. For each basin, index pre-computed grid cells → scalar values
  3. Derive vp_pa from Q2D + PSFC
  4. Accumulate hourly records

Aggregation for a full calendar day:
  prcp_mm_day  = mean(RAINRATE_mm_s) × 86400
  tmax_c       = max(T2D_K) − 273.15
  tmin_c       = min(T2D_K) − 273.15
  srad_w_m2    = mean(SWDOWN)
  vp_pa        = mean(vp_pa hourly)
  dayl_s       = daylight_seconds(centroid_lat, doy)
"""
from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def vapor_pressure_pa(q: float, psfc: float) -> float:
    """Compute actual vapor pressure (Pa) from specific humidity and surface pressure.

    Formula: e = (q * P) / (0.622 + 0.378 * q)
    where q = specific humidity (kg/kg), P = surface pressure (Pa).
    """
    return (q * psfc) / (0.622 + 0.378 * q)


def daylight_seconds(lat_deg: float, doy: int) -> float:
    """Compute daylight duration in seconds for a given latitude and day-of-year.

    Uses standard astronomical solar declination formula.
    """
    lat = math.radians(lat_deg)
    delta = math.radians(23.45 * math.sin(math.radians(360 / 365 * (doy - 81))))
    cos_ha = -math.tan(lat) * math.tan(delta)
    cos_ha = max(-1.0, min(1.0, cos_ha))
    ha = math.acos(cos_ha)
    return 2.0 * ha / (2.0 * math.pi) * 86400.0


def extract_basin_value(
    data: np.ndarray,
    y_indices: np.ndarray,
    x_indices: np.ndarray,
) -> float:
    """Return the mean of *data* at the given cell indices.

    Returns np.nan if indices are empty.
    """
    if len(y_indices) == 0:
        return float("nan")
    return float(data[y_indices, x_indices].mean())


def extract_all_basins_from_file(
    nc_path: Path,
    basin_weights_list: list[dict],
) -> list[dict]:
    """Open *nc_path* once and extract all basins in a single read pass.

    Reads each variable array once into memory, then indexes it for every
    basin — 37× faster than calling extract_hourly_basin_record per basin.

    Args:
        nc_path: Path to NWM Analysis Assim NetCDF file.
        basin_weights_list: List of weight dicts (from load_weights) for each basin.

    Returns:
        List of hourly record dicts aligned with basin_weights_list, each with
        keys: rainrate_mm_s, t2d_k, swdown_w_m2, vp_pa.

    Raises:
        Any xarray / file open exception — caller should catch and skip the file.
    """
    import xarray as xr

    ds = xr.open_dataset(nc_path, engine="netcdf4")
    try:
        rainrate_arr = ds["RAINRATE"].values[0]   # (ny, nx)
        t2d_arr = ds["T2D"].values[0]
        q2d_arr = ds["Q2D"].values[0]
        swdown_arr = ds["SWDOWN"].values[0]
        psfc_arr = ds["PSFC"].values[0]
    finally:
        ds.close()

    records = []
    for bw in basin_weights_list:
        y_idx = bw["y_indices"]
        x_idx = bw["x_indices"]
        records.append({
            "rainrate_mm_s": extract_basin_value(rainrate_arr, y_idx, x_idx),
            "t2d_k": extract_basin_value(t2d_arr, y_idx, x_idx),
            "swdown_w_m2": extract_basin_value(swdown_arr, y_idx, x_idx),
            "vp_pa": vapor_pressure_pa(
                extract_basin_value(q2d_arr, y_idx, x_idx),
                extract_basin_value(psfc_arr, y_idx, x_idx),
            ),
        })
    return records


def extract_hourly_basin_record(
    nc_path: Path,
    basin_weights: dict,
) -> dict:
    """Extract basin-averaged NWM forcing variables from one hourly NetCDF file.

    Args:
        nc_path: Path to NWM analysis_assim NetCDF file.
        basin_weights: Dict with keys y_indices, x_indices (from load_weights).

    Returns:
        dict with keys: rainrate_mm_s, t2d_k, swdown_w_m2, vp_pa
    """
    import xarray as xr

    y_idx = basin_weights["y_indices"]
    x_idx = basin_weights["x_indices"]

    ds = xr.open_dataset(nc_path, engine="netcdf4")
    try:
        rainrate = extract_basin_value(ds["RAINRATE"].values[0], y_idx, x_idx)
        t2d = extract_basin_value(ds["T2D"].values[0], y_idx, x_idx)
        q2d = extract_basin_value(ds["Q2D"].values[0], y_idx, x_idx)
        swdown = extract_basin_value(ds["SWDOWN"].values[0], y_idx, x_idx)
        psfc = extract_basin_value(ds["PSFC"].values[0], y_idx, x_idx)
    finally:
        ds.close()

    return {
        "rainrate_mm_s": rainrate,
        "t2d_k": t2d,
        "swdown_w_m2": swdown,
        "vp_pa": vapor_pressure_pa(q2d, psfc),
    }


def aggregate_hourly_to_daily(
    records: list[dict],
    centroid_lat: float,
    target_date_doy: int,
) -> dict:
    """Aggregate 24 hourly basin records into a single daily BasinForcing dict.

    Args:
        records: List of hourly dicts with keys:
                 rainrate_mm_s, t2d_k, swdown_w_m2, vp_pa
        centroid_lat: Basin centroid latitude in degrees (for dayl_s).
        target_date_doy: Day-of-year of the target date.

    Returns:
        dict with keys: prcp_mm_day, tmax_c, tmin_c, srad_w_m2, vp_pa, dayl_s
    """
    rainrates = [r["rainrate_mm_s"] for r in records]
    temps_k = [r["t2d_k"] for r in records]
    swdowns = [r["swdown_w_m2"] for r in records]
    vps = [r["vp_pa"] for r in records]

    return {
        "prcp_mm_day": float(np.mean(rainrates) * 86400.0),
        "tmax_c": float(max(temps_k) - 273.15),
        "tmin_c": float(min(temps_k) - 273.15),
        "srad_w_m2": float(np.mean(swdowns)),
        "vp_pa": float(np.mean(vps)),
        "dayl_s": daylight_seconds(centroid_lat, target_date_doy),
    }
