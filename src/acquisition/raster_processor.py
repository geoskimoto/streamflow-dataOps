"""Raster data processing utilities."""

import os
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from datetime import datetime

import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
from rasterio.io import MemoryFile
import numpy as np
from PIL import Image

from django.conf import settings

logger = logging.getLogger(__name__)


class RasterProcessorError(Exception):
    """Base exception for raster processor errors."""
    pass


class RasterValidationError(RasterProcessorError):
    """Raised when raster validation fails."""
    pass


class RasterProcessor:
    """Processes and validates raster files."""

    def __init__(self):
        """Initialize raster processor."""
        self.raster_root = getattr(settings, 'RASTER_ROOT', Path('data/rasters'))
        self.compression = getattr(settings, 'RASTER_DEFAULT_COMPRESSION', 'LZW')
        self.thumbnail_size = getattr(settings, 'RASTER_THUMBNAIL_SIZE', (256, 256))
        self.max_file_size_mb = getattr(settings, 'RASTER_MAX_FILE_SIZE_MB', 500)

    def validate_raster(
        self,
        file_path: Path,
        expected_bbox: Optional[List[float]] = None,
        expected_crs: str = 'EPSG:4326',
        min_value: Optional[float] = None,
        max_value: Optional[float] = None
    ) -> Tuple[bool, List[str]]:
        """
        Validate a raster file.
        
        Args:
            file_path: Path to raster file
            expected_bbox: Expected bounding box [min_lon, min_lat, max_lon, max_lat]
            expected_crs: Expected coordinate reference system
            min_value: Minimum valid data value
            max_value: Maximum valid data value
            
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        
        try:
            if not file_path.exists():
                errors.append(f"File does not exist: {file_path}")
                return False, errors
            
            # Check file size
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            if file_size_mb > self.max_file_size_mb:
                errors.append(f"File size ({file_size_mb:.1f} MB) exceeds maximum ({self.max_file_size_mb} MB)")
            
            # Open and validate raster
            with rasterio.open(file_path) as src:
                # Check CRS
                if src.crs is None:
                    errors.append("Raster has no CRS defined")
                elif expected_crs and str(src.crs) != expected_crs:
                    errors.append(f"CRS mismatch: expected {expected_crs}, got {src.crs}")
                
                # Check bounds
                if expected_bbox:
                    bounds = src.bounds
                    tolerance = 0.1  # Allow small differences
                    if (abs(bounds.left - expected_bbox[0]) > tolerance or
                        abs(bounds.bottom - expected_bbox[1]) > tolerance or
                        abs(bounds.right - expected_bbox[2]) > tolerance or
                        abs(bounds.top - expected_bbox[3]) > tolerance):
                        errors.append(f"Bounds mismatch: expected {expected_bbox}, got {list(bounds)}")
                
                # Check data validity
                data = src.read(1, masked=True)
                
                if data.size == 0:
                    errors.append("Raster contains no data")
                elif np.all(data.mask):
                    errors.append("All raster values are masked/nodata")
                else:
                    valid_data = data.compressed()
                    
                    if len(valid_data) == 0:
                        errors.append("No valid data values found")
                    else:
                        # Check value ranges
                        data_min = float(valid_data.min())
                        data_max = float(valid_data.max())
                        
                        if min_value is not None and data_min < min_value:
                            errors.append(f"Minimum value ({data_min}) below valid range ({min_value})")
                        
                        if max_value is not None and data_max > max_value:
                            errors.append(f"Maximum value ({data_max}) above valid range ({max_value})")
                        
                        # Check for NaN or Inf
                        if np.any(np.isnan(valid_data)):
                            errors.append("Data contains NaN values")
                        if np.any(np.isinf(valid_data)):
                            errors.append("Data contains Inf values")
            
            is_valid = len(errors) == 0
            
            if is_valid:
                logger.info(f"Raster validation passed: {file_path}")
            else:
                logger.warning(f"Raster validation failed: {file_path} - {errors}")
            
            return is_valid, errors
            
        except Exception as e:
            error_msg = f"Error during validation: {str(e)}"
            errors.append(error_msg)
            logger.error(f"Validation error for {file_path}: {e}")
            return False, errors

    def calculate_statistics(self, file_path: Path) -> Dict:
        """
        Calculate raster statistics.
        
        Args:
            file_path: Path to raster file
            
        Returns:
            Dictionary with statistics (min, max, mean, std_dev, etc.)
        """
        try:
            with rasterio.open(file_path) as src:
                data = src.read(1, masked=True)
                
                # Get metadata
                metadata = {
                    'width': src.width,
                    'height': src.height,
                    'crs': str(src.crs) if src.crs else None,
                    'bounds': list(src.bounds),
                    'resolution': src.res,
                    'nodata': src.nodata,
                }
                
                # Calculate statistics on valid data
                if data.size > 0 and not np.all(data.mask):
                    valid_data = data.compressed()
                    
                    metadata.update({
                        'min_value': float(valid_data.min()),
                        'max_value': float(valid_data.max()),
                        'mean_value': float(valid_data.mean()),
                        'std_dev': float(valid_data.std()),
                        'count_valid': int(len(valid_data)),
                        'count_total': int(data.size),
                        'percent_valid': float(len(valid_data) / data.size * 100),
                    })
                else:
                    metadata.update({
                        'min_value': None,
                        'max_value': None,
                        'mean_value': None,
                        'std_dev': None,
                        'count_valid': 0,
                        'count_total': int(data.size),
                        'percent_valid': 0.0,
                    })
                
                logger.debug(f"Calculated statistics for {file_path}")
                return metadata
                
        except Exception as e:
            logger.error(f"Error calculating statistics for {file_path}: {e}")
            raise RasterProcessorError(f"Failed to calculate statistics: {e}")

    def compress_raster(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        compression: Optional[str] = None
    ) -> Path:
        """
        Compress raster file.
        
        Args:
            input_path: Input raster file
            output_path: Output path (default: overwrite input)
            compression: Compression method (default: from settings)
            
        Returns:
            Path to compressed file
        """
        compression = compression or self.compression
        output_path = output_path or input_path
        
        try:
            with rasterio.open(input_path) as src:
                profile = src.profile.copy()
                profile.update(
                    compress=compression,
                    predictor=2,  # Horizontal differencing for better compression
                    tiled=True,
                    blockxsize=256,
                    blockysize=256
                )
                
                # Write to temporary file first
                temp_path = output_path.with_suffix('.tmp.tif')
                
                with rasterio.open(temp_path, 'w', **profile) as dst:
                    for i in range(1, src.count + 1):
                        data = src.read(i)
                        dst.write(data, i)
                
                # Replace original
                if temp_path != output_path:
                    if output_path.exists():
                        output_path.unlink()
                    temp_path.rename(output_path)
                
                original_size = input_path.stat().st_size if input_path.exists() else 0
                compressed_size = output_path.stat().st_size
                ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
                
                logger.info(f"Compressed raster: {input_path.name} ({original_size} -> {compressed_size} bytes, {ratio:.1f}% reduction)")
                
                return output_path
                
        except Exception as e:
            logger.error(f"Error compressing raster {input_path}: {e}")
            if temp_path.exists():
                temp_path.unlink()
            raise RasterProcessorError(f"Failed to compress raster: {e}")

    def generate_thumbnail(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        size: Optional[Tuple[int, int]] = None
    ) -> Path:
        """
        Generate thumbnail image from raster.
        
        Args:
            input_path: Input raster file
            output_path: Output thumbnail path (default: input_path with .png)
            size: Thumbnail size (default: from settings)
            
        Returns:
            Path to thumbnail file
        """
        size = size or self.thumbnail_size
        output_path = output_path or input_path.with_suffix('.png')
        
        try:
            with rasterio.open(input_path) as src:
                # Read and normalize data
                data = src.read(1, masked=True)
                
                if np.all(data.mask):
                    # Create blank thumbnail
                    img = Image.new('RGB', size, color='white')
                else:
                    # Normalize to 0-255
                    valid_data = data.compressed()
                    vmin, vmax = valid_data.min(), valid_data.max()
                    
                    if vmax > vmin:
                        normalized = ((data - vmin) / (vmax - vmin) * 255).astype(np.uint8)
                        normalized = np.ma.filled(normalized, 255)  # Fill masked with white
                    else:
                        normalized = np.zeros_like(data, dtype=np.uint8)
                    
                    # Create PIL image and resize
                    img = Image.fromarray(normalized, mode='L')
                    img = img.resize(size, Image.Resampling.LANCZOS)
                
                # Save thumbnail
                output_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(output_path, 'PNG', optimize=True)
                
                logger.debug(f"Generated thumbnail: {output_path}")
                return output_path
                
        except Exception as e:
            logger.error(f"Error generating thumbnail for {input_path}: {e}")
            raise RasterProcessorError(f"Failed to generate thumbnail: {e}")

    def calculate_checksum(self, file_path: Path) -> str:
        """
        Calculate MD5 checksum of file.
        
        Args:
            file_path: Path to file
            
        Returns:
            MD5 checksum hex string
        """
        try:
            md5 = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5.update(chunk)
            checksum = md5.hexdigest()
            logger.debug(f"Calculated checksum for {file_path}: {checksum}")
            return checksum
        except Exception as e:
            logger.error(f"Error calculating checksum for {file_path}: {e}")
            return ''

    def extract_point_values(
        self,
        file_path: Path,
        coordinates: List[Tuple[float, float]]
    ) -> List[Optional[float]]:
        """
        Extract raster values at specific coordinates.
        
        Args:
            file_path: Path to raster file
            coordinates: List of (lon, lat) tuples
            
        Returns:
            List of values (None if outside bounds or nodata)
        """
        try:
            with rasterio.open(file_path) as src:
                values = []
                for lon, lat in coordinates:
                    # Convert coordinates to pixel indices
                    py, px = src.index(lon, lat)
                    
                    # Check if within bounds
                    if 0 <= py < src.height and 0 <= px < src.width:
                        data = src.read(1, masked=True)
                        value = data[py, px]
                        
                        # Return None if masked/nodata
                        if np.ma.is_masked(value):
                            values.append(None)
                        else:
                            values.append(float(value))
                    else:
                        values.append(None)
                
                return values
                
        except Exception as e:
            logger.error(f"Error extracting point values from {file_path}: {e}")
            return [None] * len(coordinates)

    def resample_raster(
        self,
        input_path: Path,
        output_path: Path,
        target_resolution: int,
        resampling_method: str = 'bilinear'
    ) -> Path:
        """
        Resample raster to different resolution.
        
        Args:
            input_path: Input raster file
            output_path: Output raster file
            target_resolution: Target resolution in meters
            resampling_method: Resampling method ('nearest', 'bilinear', 'cubic')
            
        Returns:
            Path to resampled file
        """
        resampling_map = {
            'nearest': Resampling.nearest,
            'bilinear': Resampling.bilinear,
            'cubic': Resampling.cubic,
            'average': Resampling.average,
        }
        
        resampling = resampling_map.get(resampling_method, Resampling.bilinear)
        
        try:
            with rasterio.open(input_path) as src:
                # Calculate new dimensions
                scale_factor = src.res[0] / target_resolution
                new_width = int(src.width * scale_factor)
                new_height = int(src.height * scale_factor)
                
                # Calculate transform
                transform, width, height = calculate_default_transform(
                    src.crs, src.crs, new_width, new_height,
                    *src.bounds, resolution=target_resolution
                )
                
                # Update profile
                profile = src.profile.copy()
                profile.update({
                    'width': width,
                    'height': height,
                    'transform': transform
                })
                
                # Resample
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with rasterio.open(output_path, 'w', **profile) as dst:
                    for i in range(1, src.count + 1):
                        reproject(
                            source=rasterio.band(src, i),
                            destination=rasterio.band(dst, i),
                            src_transform=src.transform,
                            src_crs=src.crs,
                            dst_transform=transform,
                            dst_crs=src.crs,
                            resampling=resampling
                        )
                
                logger.info(f"Resampled raster: {input_path.name} ({src.width}x{src.height} -> {width}x{height})")
                return output_path
                
        except Exception as e:
            logger.error(f"Error resampling raster {input_path}: {e}")
            if output_path.exists():
                output_path.unlink()
            raise RasterProcessorError(f"Failed to resample raster: {e}")
