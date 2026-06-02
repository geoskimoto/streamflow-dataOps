"""Basin spatial weight computation and I/O.

Weights are stored per basin as numpy .npz files containing the integer
y and x grid-cell indices of all NWM cells whose center falls within the
basin polygon, plus the basin centroid lat/lon for dayl_s computation.
"""
from __future__ import annotations
import logging
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


def find_cells_in_polygon(
    lats: np.ndarray,
    lons: np.ndarray,
    polygon_coords: list[tuple[float, float]],
) -> tuple[np.ndarray, np.ndarray]:
    """Return (y_indices, x_indices) of grid cells whose center is inside polygon.

    Args:
        lats: 2D array (ny, nx) of cell-center latitudes.
        lons: 2D array (ny, nx) of cell-center longitudes.
        polygon_coords: List of (lon, lat) tuples forming a closed ring.

    Returns:
        Tuple of 1D int32 arrays (y_indices, x_indices).
    """
    from shapely.geometry import Point, Polygon

    poly = Polygon(polygon_coords)
    ny, nx = lats.shape

    y_list, x_list = [], []
    # Restrict search to bounding box first for speed
    lons_arr = np.asarray(polygon_coords)[:, 0]
    lats_arr = np.asarray(polygon_coords)[:, 1]
    lon_min, lon_max = lons_arr.min(), lons_arr.max()
    lat_min, lat_max = lats_arr.min(), lats_arr.max()

    mask_y, mask_x = np.where(
        (lats >= lat_min) & (lats <= lat_max) &
        (lons >= lon_min) & (lons <= lon_max)
    )
    for yi, xi in zip(mask_y.tolist(), mask_x.tolist()):
        if poly.contains(Point(float(lons[yi, xi]), float(lats[yi, xi]))):
            y_list.append(yi)
            x_list.append(xi)

    return (
        np.array(y_list, dtype=np.int32),
        np.array(x_list, dtype=np.int32),
    )


def save_weights(
    path: Path,
    y_indices: np.ndarray,
    x_indices: np.ndarray,
    centroid_lat: float,
    centroid_lon: float,
) -> None:
    """Save basin weight indices to a .npz file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        y_indices=y_indices,
        x_indices=x_indices,
        centroid_lat=np.float64(centroid_lat),
        centroid_lon=np.float64(centroid_lon),
    )
    logger.debug("Saved weights for %s: %d cells", path.stem, len(y_indices))


def load_weights(path: Path) -> dict:
    """Load basin weight indices from a .npz file.

    Returns dict with keys: y_indices, x_indices, centroid_lat, centroid_lon.
    Raises FileNotFoundError if path does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Weight file not found: {path}")
    data = np.load(path)
    return {
        "y_indices": data["y_indices"],
        "x_indices": data["x_indices"],
        "centroid_lat": float(data["centroid_lat"]),
        "centroid_lon": float(data["centroid_lon"]),
    }
