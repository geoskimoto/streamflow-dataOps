"""Tests for NWM grid loading and basin weight computation."""
import numpy as np
import pytest
from pathlib import Path


def make_synthetic_grid(ny=50, nx=60):
    """Return synthetic XLAT_M, XLONG_M arrays for a PNW-like region."""
    lats = np.linspace(44.0, 50.0, ny)
    lons = np.linspace(-125.0, -110.0, nx)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    return lat_grid.astype(np.float32), lon_grid.astype(np.float32)


def test_extract_grid_coords_shape():
    from apps.nwm_forcings.grid import extract_grid_coords_from_arrays

    lats, lons = make_synthetic_grid(50, 60)
    result = extract_grid_coords_from_arrays(lats, lons)
    assert result["lats"].shape == (50, 60)
    assert result["lons"].shape == (50, 60)
    assert result["ny"] == 50
    assert result["nx"] == 60


def test_find_cells_in_polygon_returns_indices():
    from apps.nwm_forcings.weights import find_cells_in_polygon

    lats, lons = make_synthetic_grid(50, 60)
    # Simple rectangular polygon covering central part of grid
    polygon_coords = [
        (-120.0, 46.0), (-115.0, 46.0),
        (-115.0, 48.0), (-120.0, 48.0),
        (-120.0, 46.0),
    ]
    y_idx, x_idx = find_cells_in_polygon(lats, lons, polygon_coords)
    assert len(y_idx) > 0
    assert len(x_idx) > 0
    assert len(y_idx) == len(x_idx)
    assert np.all(lats[y_idx, x_idx] >= 46.0)
    assert np.all(lats[y_idx, x_idx] <= 48.0)
    assert np.all(lons[y_idx, x_idx] >= -120.0)
    assert np.all(lons[y_idx, x_idx] <= -115.0)


def test_find_cells_in_polygon_empty_polygon():
    from apps.nwm_forcings.weights import find_cells_in_polygon

    lats, lons = make_synthetic_grid(50, 60)
    polygon_coords = [
        (10.0, 0.0), (11.0, 0.0), (11.0, 1.0), (10.0, 1.0), (10.0, 0.0)
    ]
    y_idx, x_idx = find_cells_in_polygon(lats, lons, polygon_coords)
    assert len(y_idx) == 0


def test_save_and_load_weights(tmp_path):
    from apps.nwm_forcings.weights import save_weights, load_weights

    y_idx = np.array([10, 11, 12, 13], dtype=np.int32)
    x_idx = np.array([20, 21, 22, 23], dtype=np.int32)
    centroid_lat = 47.5
    centroid_lon = -117.3

    weights_path = tmp_path / "12010000.npz"
    save_weights(weights_path, y_idx, x_idx, centroid_lat, centroid_lon)

    loaded = load_weights(weights_path)
    np.testing.assert_array_equal(loaded["y_indices"], y_idx)
    np.testing.assert_array_equal(loaded["x_indices"], x_idx)
    assert loaded["centroid_lat"] == pytest.approx(centroid_lat)
    assert loaded["centroid_lon"] == pytest.approx(centroid_lon)


def test_load_weights_missing_file():
    from apps.nwm_forcings.weights import load_weights

    with pytest.raises(FileNotFoundError):
        load_weights(Path("/nonexistent/path/12010000.npz"))
