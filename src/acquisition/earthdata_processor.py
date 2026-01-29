"""Raster data processor for NASA EarthData formats.

Handles conversion of HDF5, NetCDF4, and GRIB2 files to GeoTIFF.
Includes coordinate transformations, subsetting, and reprojection.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from datetime import datetime

import numpy as np
import xarray as xr
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.io import MemoryFile

logger = logging.getLogger(__name__)


class RasterProcessorError(Exception):
    """Base exception for raster processing errors."""
    pass


class EarthDataRasterProcessor:
    """Process NASA EarthData raster formats to GeoTIFF."""
    
    def __init__(self):
        """Initialize processor."""
        self.output_crs = CRS.from_epsg(4326)  # WGS84
    
    def process_smap_hdf5(
        self,
        input_path: Path,
        variable: str,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Process SMAP HDF5 to GeoTIFF.
        
        SMAP uses EASE-Grid 2.0 projection which needs reprojection to WGS84.
        
        Args:
            input_path: Path to SMAP HDF5 file
            variable: Variable name ('sm_surface' or 'sm_rootzone')
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat] in WGS84
            output_path: Output GeoTIFF path
            
        Returns:
            Metadata dict with statistics
        """
        try:
            # Open with xarray
            ds = xr.open_dataset(input_path, group='Geophysical_Data')
            
            # Get variable data
            var_data = ds[variable]
            
            # SMAP L4 has lat/lon coordinates
            if 'lat' in ds and 'lon' in ds:
                lats = ds['lat'].values
                lons = ds['lon'].values
                data = var_data.values
            else:
                # Older format - needs EASE-Grid handling
                raise RasterProcessorError("SMAP file missing lat/lon coordinates - EASE-Grid conversion needed")
            
            # Subset to bbox
            lat_mask = (lats >= bbox[1]) & (lats <= bbox[3])
            lon_mask = (lons >= bbox[0]) & (lons <= bbox[2])
            
            # Create 2D mask if needed
            if len(lats.shape) == 1 and len(lons.shape) == 1:
                lat_idx = np.where(lat_mask)[0]
                lon_idx = np.where(lon_mask)[0]
                if len(lat_idx) > 0 and len(lon_idx) > 0:
                    data_subset = data[lat_idx[0]:lat_idx[-1]+1, lon_idx[0]:lon_idx[-1]+1]
                    lats_subset = lats[lat_idx[0]:lat_idx[-1]+1]
                    lons_subset = lons[lon_idx[0]:lon_idx[-1]+1]
                else:
                    raise RasterProcessorError("No data in bounding box")
            else:
                # 2D lat/lon arrays
                mask_2d = np.outer(lat_mask, lon_mask)
                data_subset = np.where(mask_2d, data, np.nan)
                lats_subset = lats
                lons_subset = lons
            
            # Calculate statistics
            valid_data = data_subset[~np.isnan(data_subset)]
            stats = {
                'min': float(np.min(valid_data)) if len(valid_data) > 0 else None,
                'max': float(np.max(valid_data)) if len(valid_data) > 0 else None,
                'mean': float(np.mean(valid_data)) if len(valid_data) > 0 else None,
                'std': float(np.std(valid_data)) if len(valid_data) > 0 else None,
                'count': int(len(valid_data)),
                'units': var_data.attrs.get('units', 'm³/m³'),
                'long_name': var_data.attrs.get('long_name', variable),
            }
            
            # Write to GeoTIFF
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Calculate transform
            if len(lons_subset.shape) == 1:
                transform = from_bounds(
                    lons_subset[0], lats_subset[-1],
                    lons_subset[-1], lats_subset[0],
                    len(lons_subset), len(lats_subset)
                )
            else:
                # Use bbox for 2D arrays
                transform = from_bounds(
                    bbox[0], bbox[1], bbox[2], bbox[3],
                    data_subset.shape[1], data_subset.shape[0]
                )
            
            # Write GeoTIFF
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=data_subset.shape[0],
                width=data_subset.shape[1],
                count=1,
                dtype=data_subset.dtype,
                crs=self.output_crs,
                transform=transform,
                compress='lzw',
                nodata=np.nan
            ) as dst:
                dst.write(data_subset, 1)
                dst.update_tags(**{k: str(v) for k, v in stats.items()})
            
            logger.info(f"Processed SMAP {variable} to {output_path}")
            ds.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to process SMAP data: {e}")
            raise RasterProcessorError(f"SMAP processing failed: {e}")
    
    def process_gpm_netcdf(
        self,
        input_path: Path,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Process GPM NetCDF to GeoTIFF.
        
        GPM is already in WGS84, just needs subsetting and extraction.
        
        Args:
            input_path: Path to GPM NetCDF file
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            output_path: Output GeoTIFF path
            
        Returns:
            Metadata dict with statistics
        """
        try:
            # Open NetCDF with xarray
            ds = xr.open_dataset(input_path)
            
            # GPM structure: precipitation[time, lat, lon]
            precip = ds['precipitation']
            
            # Subset to bounding box
            precip_subset = precip.sel(
                lon=slice(bbox[0], bbox[2]),
                lat=slice(bbox[1], bbox[3])
            )
            
            # Get first time step if present
            if 'time' in precip_subset.dims:
                precip_subset = precip_subset.isel(time=0)
            
            # Extract data and coordinates
            data = precip_subset.values
            lats = precip_subset['lat'].values
            lons = precip_subset['lon'].values
            
            # Calculate statistics
            valid_data = data[~np.isnan(data)]
            stats = {
                'min': float(np.min(valid_data)) if len(valid_data) > 0 else None,
                'max': float(np.max(valid_data)) if len(valid_data) > 0 else None,
                'mean': float(np.mean(valid_data)) if len(valid_data) > 0 else None,
                'std': float(np.std(valid_data)) if len(valid_data) > 0 else None,
                'count': int(len(valid_data)),
                'units': precip.attrs.get('units', 'mm/day'),
                'long_name': precip.attrs.get('long_name', 'precipitation'),
            }
            
            # Write to GeoTIFF
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            transform = from_bounds(
                lons[0], lats[-1], lons[-1], lats[0],
                len(lons), len(lats)
            )
            
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=data.shape[0],
                width=data.shape[1],
                count=1,
                dtype=data.dtype,
                crs=self.output_crs,
                transform=transform,
                compress='lzw',
                nodata=np.nan
            ) as dst:
                dst.write(data, 1)
                dst.update_tags(**{k: str(v) for k, v in stats.items()})
            
            logger.info(f"Processed GPM precipitation to {output_path}")
            ds.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to process GPM data: {e}")
            raise RasterProcessorError(f"GPM processing failed: {e}")
    
    def process_modis_hdf4(
        self,
        input_path: Path,
        variable: str,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Process MODIS HDF4 to GeoTIFF.
        
        MODIS uses sinusoidal projection in tiles - needs reprojection.
        
        Args:
            input_path: Path to MODIS HDF4 file
            variable: Variable name (e.g., 'LST_Day_1km')
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            output_path: Output GeoTIFF path
            
        Returns:
            Metadata dict with statistics
        """
        try:
            # MODIS HDF4 requires special handling
            # For now, use gdal through rasterio
            
            # HDF4 subdataset path format
            subdataset = f'HDF4_EOS:EOS_GRID:"{input_path}":MODIS_Grid_Daily_1km_LST:{variable}'
            
            with rasterio.open(subdataset) as src:
                # Read data
                data = src.read(1)
                src_crs = src.crs
                src_transform = src.transform
                
                # Apply scale factor (MODIS LST is stored as Kelvin * 50)
                if 'LST' in variable:
                    data = data.astype(float) * 0.02  # Convert to Kelvin
                    data[data == 0] = np.nan  # Fill value
                
                # Calculate destination bounds
                dst_crs = self.output_crs
                
                # Reproject to WGS84
                transform, width, height = calculate_default_transform(
                    src_crs, dst_crs, src.width, src.height,
                    left=bbox[0], bottom=bbox[1],
                    right=bbox[2], top=bbox[3]
                )
                
                # Create output array
                dst_data = np.empty((height, width), dtype=np.float32)
                
                # Reproject
                reproject(
                    source=data,
                    destination=dst_data,
                    src_transform=src_transform,
                    src_crs=src_crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                    src_nodata=np.nan,
                    dst_nodata=np.nan
                )
                
                # Calculate statistics
                valid_data = dst_data[~np.isnan(dst_data)]
                stats = {
                    'min': float(np.min(valid_data)) if len(valid_data) > 0 else None,
                    'max': float(np.max(valid_data)) if len(valid_data) > 0 else None,
                    'mean': float(np.mean(valid_data)) if len(valid_data) > 0 else None,
                    'std': float(np.std(valid_data)) if len(valid_data) > 0 else None,
                    'count': int(len(valid_data)),
                    'units': 'Kelvin',
                    'long_name': variable,
                }
                
                # Write to GeoTIFF
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                with rasterio.open(
                    output_path,
                    'w',
                    driver='GTiff',
                    height=height,
                    width=width,
                    count=1,
                    dtype=dst_data.dtype,
                    crs=dst_crs,
                    transform=transform,
                    compress='lzw',
                    nodata=np.nan
                ) as dst:
                    dst.write(dst_data, 1)
                    dst.update_tags(**{k: str(v) for k, v in stats.items()})
                
                logger.info(f"Processed MODIS {variable} to {output_path}")
                
                return stats
                
        except Exception as e:
            logger.error(f"Failed to process MODIS data: {e}")
            raise RasterProcessorError(f"MODIS processing failed: {e}")
    
    def mosaic_modis_tiles(
        self,
        tile_paths: List[Path],
        variable: str,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Mosaic multiple MODIS HDF4 tiles into a single GeoTIFF.
        
        Args:
            tile_paths: List of paths to MODIS HDF4 files
            variable: Variable name (e.g., 'LST_Day_1km')
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            output_path: Output GeoTIFF path
            
        Returns:
            Metadata dict with statistics
        """
        try:
            from rasterio.merge import merge
            
            logger.info(f"Mosaicking {len(tile_paths)} MODIS tiles")
            
            # Open all tiles
            src_files = []
            subdatasets = []
            
            for tile_path in tile_paths:
                # Ensure Path object and file exists
                tile_path = Path(tile_path)
                if not tile_path.exists():
                    logger.warning(f"MODIS tile file not found: {tile_path}")
                    continue
                
                subdataset = f'HDF4_EOS:EOS_GRID:"{str(tile_path)}":MODIS_Grid_Daily_1km_LST:{variable}'
                logger.debug(f"Opening subdataset: {subdataset}")
                
                try:
                    src = rasterio.open(subdataset)
                    src_files.append(src)
                    subdatasets.append(subdataset)
                    logger.info(f"Successfully opened MODIS tile: {tile_path.name}")
                except Exception as e:
                    logger.error(f"Failed to open MODIS tile {tile_path}: {e}")
                    continue
            
            if not src_files:
                raise RasterProcessorError("No valid MODIS tiles to mosaic")
            
            # Merge tiles
            mosaic, mosaic_transform = merge(src_files, bounds=bbox)
            
            # Apply MODIS LST scale factor
            if 'LST' in variable:
                mosaic = mosaic.astype(float) * 0.02  # Convert to Kelvin
                mosaic[mosaic == 0] = np.nan  # Fill value
            
            # Close source files
            for src in src_files:
                src.close()
            
            # Get CRS from first tile
            with rasterio.open(subdatasets[0]) as src:
                src_crs = src.crs
            
            # Reproject to WGS84
            dst_crs = self.output_crs
            transform, width, height = calculate_default_transform(
                src_crs, dst_crs, mosaic.shape[2], mosaic.shape[1],
                left=bbox[0], bottom=bbox[1],
                right=bbox[2], top=bbox[3]
            )
            
            # Create output array
            dst_data = np.empty((height, width), dtype=np.float32)
            
            # Reproject
            reproject(
                source=mosaic[0],
                destination=dst_data,
                src_transform=mosaic_transform,
                src_crs=src_crs,
                dst_transform=transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
                src_nodata=np.nan,
                dst_nodata=np.nan
            )
            
            # Calculate statistics
            valid_data = dst_data[~np.isnan(dst_data)]
            stats = {
                'min': float(np.min(valid_data)) if len(valid_data) > 0 else None,
                'max': float(np.max(valid_data)) if len(valid_data) > 0 else None,
                'mean': float(np.mean(valid_data)) if len(valid_data) > 0 else None,
                'std': float(np.std(valid_data)) if len(valid_data) > 0 else None,
                'count': int(len(valid_data)),
                'tiles': len(tile_paths),
                'units': 'Kelvin',
                'long_name': variable,
            }
            
            # Write to GeoTIFF
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=height,
                width=width,
                count=1,
                dtype=dst_data.dtype,
                crs=dst_crs,
                transform=transform,
                compress='lzw',
                nodata=np.nan
            ) as dst:
                dst.write(dst_data, 1)
                dst.update_tags(**{k: str(v) for k, v in stats.items()})
            
            logger.info(f"Mosaicked {len(tile_paths)} MODIS tiles to {output_path}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to mosaic MODIS tiles: {e}")
            raise RasterProcessorError(f"MODIS mosaicking failed: {e}")
    
    def calculate_statistics(self, geotiff_path: Path) -> Dict:
        """
        Calculate statistics from a GeoTIFF file.
        
        Args:
            geotiff_path: Path to GeoTIFF
            
        Returns:
            Statistics dictionary
        """
        try:
            with rasterio.open(geotiff_path) as src:
                data = src.read(1, masked=True)
                
                stats = {
                    'min': float(data.min()) if data.count() > 0 else None,
                    'max': float(data.max()) if data.count() > 0 else None,
                    'mean': float(data.mean()) if data.count() > 0 else None,
                    'std': float(data.std()) if data.count() > 0 else None,
                    'count': int(data.count()),
                }
                
                return stats
                
        except Exception as e:
            logger.error(f"Failed to calculate statistics: {e}")
            return {}
