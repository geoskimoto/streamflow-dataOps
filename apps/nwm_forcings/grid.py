"""NWM grid coordinate utilities."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
import numpy as np

logger = logging.getLogger(__name__)


def extract_grid_coords_from_arrays(
    lats: np.ndarray,
    lons: np.ndarray,
) -> dict[str, Any]:
    """Return grid metadata dict from pre-loaded XLAT_M / XLONG_M arrays.

    Args:
        lats: 2D float array (ny, nx) of latitude values in degrees.
        lons: 2D float array (ny, nx) of longitude values in degrees.

    Returns:
        dict with keys: lats, lons, ny, nx
    """
    assert lats.ndim == 2, f"Expected 2D lats, got shape {lats.shape}"
    assert lats.shape == lons.shape, "lats/lons shape mismatch"
    ny, nx = lats.shape
    return {"lats": lats, "lons": lons, "ny": ny, "nx": nx}


def load_grid_from_file(nc_path: Path) -> dict[str, Any]:
    """Open a NWM NetCDF forcing file and extract the grid coordinate arrays.

    Args:
        nc_path: Path to a NWM Analysis Assim NetCDF file.

    Returns:
        dict with keys: lats, lons, ny, nx
    """
    import xarray as xr

    ds = xr.open_dataset(nc_path, engine="netcdf4")
    try:
        lats = ds["XLAT_M"].values[0]   # shape (ny, nx) after dropping Time dim
        lons = ds["XLONG_M"].values[0]
    finally:
        ds.close()

    return extract_grid_coords_from_arrays(lats, lons)
