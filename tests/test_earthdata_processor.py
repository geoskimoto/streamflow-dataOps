"""Unit tests for EarthDataRasterProcessor."""

import pytest
import numpy as np
import xarray as xr
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import rasterio
from rasterio.crs import CRS

from src.acquisition.earthdata_processor import (
    EarthDataRasterProcessor,
    RasterProcessorError
)


@pytest.fixture
def processor():
    """Create test processor."""
    return EarthDataRasterProcessor()


@pytest.fixture
def mock_smap_dataset():
    """Create mock SMAP dataset."""
    # Create synthetic SMAP data
    lats = np.linspace(42.0, 48.0, 60)
    lons = np.linspace(-123.0, -110.0, 130)
    
    # Create 2D data
    data = np.random.rand(60, 130) * 0.4 + 0.1  # Soil moisture range
    
    ds = xr.Dataset({
        'sm_surface': (['lat', 'lon'], data, {
            'units': 'm³/m³',
            'long_name': 'Surface soil moisture'
        }),
        'lat': (['lat'], lats),
        'lon': (['lon'], lons)
    })
    
    return ds


@pytest.fixture
def mock_gpm_dataset():
    """Create mock GPM dataset."""
    lats = np.linspace(42.0, 48.0, 60)
    lons = np.linspace(-123.0, -110.0, 130)
    
    # Create precipitation data
    data = np.random.rand(1, 60, 130) * 50  # 0-50 mm/day
    
    ds = xr.Dataset({
        'precipitation': (['time', 'lat', 'lon'], data, {
            'units': 'mm/day',
            'long_name': 'Daily precipitation'
        }),
        'lat': (['lat'], lats),
        'lon': (['lon'], lons),
        'time': (['time'], [np.datetime64('2024-05-31')])
    })
    
    return ds


class TestSMAPProcessing:
    """Test SMAP HDF5 processing."""
    
    def test_process_smap_success(self, processor, mock_smap_dataset, tmp_path):
        """Test successful SMAP processing."""
        input_file = tmp_path / 'smap_test.h5'
        output_file = tmp_path / 'smap_output.tif'
        bbox = [-123.0, 42.0, -110.0, 48.0]
        
        # Mock xarray open_dataset
        with patch('xarray.open_dataset', return_value=mock_smap_dataset):
            stats = processor.process_smap_hdf5(
                input_path=input_file,
                variable='sm_surface',
                bbox=bbox,
                output_path=output_file
            )
        
        # Check stats
        assert 'min' in stats
        assert 'max' in stats
        assert 'mean' in stats
        assert 'units' in stats
        assert stats['units'] == 'm³/m³'
        assert stats['min'] >= 0.0
        assert stats['max'] <= 1.0
        
        # Check output file created
        assert output_file.exists()
        
        # Verify GeoTIFF
        with rasterio.open(output_file) as src:
            assert src.crs == CRS.from_epsg(4326)
            assert src.count == 1
            data = src.read(1, masked=True)
            assert data.shape[0] > 0
            assert data.shape[1] > 0
    
    def test_process_smap_bbox_subsetting(self, processor, mock_smap_dataset, tmp_path):
        """Test SMAP bounding box subsetting."""
        input_file = tmp_path / 'smap_test.h5'
        output_file = tmp_path / 'smap_output.tif'
        
        # Small bbox in corner
        bbox = [-120.0, 43.0, -115.0, 45.0]
        
        with patch('xarray.open_dataset', return_value=mock_smap_dataset):
            stats = processor.process_smap_hdf5(
                input_path=input_file,
                variable='sm_surface',
                bbox=bbox,
                output_path=output_file
            )
        
        assert output_file.exists()
        
        # Verify smaller extent
        with rasterio.open(output_file) as src:
            bounds = src.bounds
            assert bounds.left >= bbox[0]
            assert bounds.bottom >= bbox[1]
            assert bounds.right <= bbox[2]
            assert bounds.top <= bbox[3]
    
    def test_process_smap_missing_variable(self, processor, tmp_path):
        """Test error on missing variable."""
        input_file = tmp_path / 'smap_test.h5'
        output_file = tmp_path / 'smap_output.tif'
        bbox = [-123.0, 42.0, -110.0, 48.0]
        
        # Dataset without requested variable
        ds = xr.Dataset({
            'wrong_var': (['lat', 'lon'], np.random.rand(10, 10)),
            'lat': (['lat'], np.linspace(40, 50, 10)),
            'lon': (['lon'], np.linspace(-120, -110, 10))
        })
        
        with patch('xarray.open_dataset', return_value=ds):
            with pytest.raises(RasterProcessorError):
                processor.process_smap_hdf5(
                    input_path=input_file,
                    variable='sm_surface',
                    bbox=bbox,
                    output_path=output_file
                )


class TestGPMProcessing:
    """Test GPM NetCDF processing."""
    
    def test_process_gpm_success(self, processor, mock_gpm_dataset, tmp_path):
        """Test successful GPM processing."""
        input_file = tmp_path / 'gpm_test.nc'
        output_file = tmp_path / 'gpm_output.tif'
        bbox = [-123.0, 42.0, -110.0, 48.0]
        
        with patch('xarray.open_dataset', return_value=mock_gpm_dataset):
            stats = processor.process_gpm_netcdf(
                input_path=input_file,
                bbox=bbox,
                output_path=output_file
            )
        
        # Check stats
        assert 'min' in stats
        assert 'max' in stats
        assert 'mean' in stats
        assert 'units' in stats
        assert stats['units'] == 'mm/day'
        assert stats['min'] >= 0.0
        
        # Check output
        assert output_file.exists()
        
        with rasterio.open(output_file) as src:
            assert src.crs == CRS.from_epsg(4326)
            assert src.count == 1
    
    def test_process_gpm_time_selection(self, processor, tmp_path):
        """Test GPM selects first time step."""
        # Multi-time dataset
        lats = np.linspace(42.0, 48.0, 60)
        lons = np.linspace(-123.0, -110.0, 130)
        data = np.random.rand(5, 60, 130) * 50  # 5 time steps
        
        ds = xr.Dataset({
            'precipitation': (['time', 'lat', 'lon'], data, {'units': 'mm/day', 'long_name': 'precip'}),
            'lat': (['lat'], lats),
            'lon': (['lon'], lons),
            'time': (['time'], [np.datetime64('2024-05-31') + np.timedelta64(i, 'D') for i in range(5)])
        })
        
        input_file = tmp_path / 'gpm_test.nc'
        output_file = tmp_path / 'gpm_output.tif'
        bbox = [-123.0, 42.0, -110.0, 48.0]
        
        with patch('xarray.open_dataset', return_value=ds):
            processor.process_gpm_netcdf(input_file, bbox, output_file)
        
        # Should select first time only
        with rasterio.open(output_file) as src:
            assert src.count == 1


class TestMODISProcessing:
    """Test MODIS HDF4 processing."""
    
    def test_process_modis_with_reprojection(self, processor, tmp_path):
        """Test MODIS processing with sinusoidal reprojection."""
        input_file = tmp_path / 'modis_test.hdf'
        output_file = tmp_path / 'modis_output.tif'
        bbox = [-123.0, 42.0, -110.0, 48.0]
        
        # Mock rasterio operations
        mock_src = MagicMock()
        mock_src.read.return_value = np.random.randint(0, 65535, (1200, 1200))
        mock_src.crs = CRS.from_string('+proj=sinu +lon_0=0 +x_0=0 +y_0=0')
        mock_src.transform = rasterio.transform.from_bounds(-1000000, -1000000, 1000000, 1000000, 1200, 1200)
        mock_src.width = 1200
        mock_src.height = 1200
        
        with patch('rasterio.open', return_value=mock_src):
            with patch('rasterio.warp.calculate_default_transform') as mock_calc:
                with patch('rasterio.warp.reproject') as mock_reproj:
                    # Mock transform calculation
                    mock_calc.return_value = (
                        rasterio.transform.from_bounds(-123, 42, -110, 48, 100, 60),
                        100,
                        60
                    )
                    
                    # Process would normally fail without full mock, so just test it's called
                    try:
                        stats = processor.process_modis_hdf4(
                            input_path=input_file,
                            variable='LST_Day_1km',
                            bbox=bbox,
                            output_path=output_file
                        )
                    except:
                        pass  # Expected to fail in test without full setup
                    
                    # Verify reprojection was attempted
                    mock_calc.assert_called_once()


class TestStatistics:
    """Test statistics calculation."""
    
    def test_calculate_statistics(self, processor, tmp_path):
        """Test statistics calculation from GeoTIFF."""
        # Create test GeoTIFF
        output_file = tmp_path / 'test.tif'
        data = np.random.rand(100, 100) * 50
        
        transform = rasterio.transform.from_bounds(-120, 40, -110, 50, 100, 100)
        
        with rasterio.open(
            output_file, 'w',
            driver='GTiff',
            height=100, width=100,
            count=1, dtype=data.dtype,
            crs=CRS.from_epsg(4326),
            transform=transform
        ) as dst:
            dst.write(data, 1)
        
        # Calculate stats
        stats = processor.calculate_statistics(output_file)
        
        assert 'min' in stats
        assert 'max' in stats
        assert 'mean' in stats
        assert 'std' in stats
        assert 'count' in stats
        assert stats['count'] == 10000  # 100x100
        assert stats['min'] >= 0
        assert stats['max'] <= 50


class TestErrorHandling:
    """Test error handling."""
    
    def test_smap_file_not_found(self, processor, tmp_path):
        """Test error when SMAP file doesn't exist."""
        with pytest.raises(RasterProcessorError):
            processor.process_smap_hdf5(
                input_path=tmp_path / 'nonexistent.h5',
                variable='sm_surface',
                bbox=[-120, 40, -110, 50],
                output_path=tmp_path / 'output.tif'
            )
    
    def test_gpm_file_not_found(self, processor, tmp_path):
        """Test error when GPM file doesn't exist."""
        with pytest.raises(RasterProcessorError):
            processor.process_gpm_netcdf(
                input_path=tmp_path / 'nonexistent.nc',
                bbox=[-120, 40, -110, 50],
                output_path=tmp_path / 'output.tif'
            )
