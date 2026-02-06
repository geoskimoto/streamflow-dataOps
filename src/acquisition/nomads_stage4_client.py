"""NOAA NCEP Stage IV QPE client for downloading precipitation data.

Stage IV provides quality-controlled, mosaicked Quantitative Precipitation
Estimate (QPE) data across CONUS at 4km resolution.

Real-time access: NOMADS (2-3 day retention)
Archive access: water.noaa.gov (since 2016)
"""

import os
import logging
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from urllib.parse import urljoin

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform, reproject, Resampling

logger = logging.getLogger(__name__)


class Stage4Error(Exception):
    """Base exception for Stage IV client errors."""
    pass


class Stage4QPEClient:
    """Client for accessing NCEP Stage IV QPE data."""
    
    # NOMADS real-time access (2-3 day retention)
    NOMADS_BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/pcpanl/prod/"
    
    # Archive access (since 2016)
    ARCHIVE_BASE = "https://water.noaa.gov/resources/downloads/precip/stageIV/"
    
    # Stage IV metadata
    RESOLUTION_KM = 4  # 4km HRAP grid
    CONUS_BBOX = [-130.0, 20.0, -60.0, 55.0]  # Approximate CONUS bounds
    
    def __init__(self):
        """Initialize Stage IV client."""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'StreamflowDataOps/1.0'
        })
        logger.info("Stage IV QPE client initialized")
    
    def get_available_dates(self, days_back: int = 2) -> List[datetime]:
        """
        Query available dates on NOMADS server.
        
        Args:
            days_back: Number of days to look back
            
        Returns:
            List of available dates
        """
        available_dates = []
        
        for i in range(days_back + 1):
            check_date = datetime.utcnow() - timedelta(days=i)
            date_str = check_date.strftime('%Y%m%d')
            
            # Check if directory exists
            dir_url = f"{self.NOMADS_BASE}pcpanl.{date_str}/"
            
            try:
                response = self.session.head(dir_url, timeout=10)
                if response.status_code == 200:
                    available_dates.append(check_date.replace(hour=0, minute=0, second=0, microsecond=0))
                    logger.debug(f"Found Stage IV data for {date_str}")
            except Exception as e:
                logger.debug(f"No Stage IV data for {date_str}: {e}")
        
        return sorted(available_dates)
    
    def get_hourly_precip(
        self,
        timestamp: datetime,
        bbox: List[float],
        output_path: Path,
        timeout: int = 300
    ) -> Optional[Dict]:
        """
        Fetch hourly QPE accumulation and convert to GeoTIFF.
        
        File pattern: st4_conus.YYYYMMDDHH.01h.grb2
        
        Args:
            timestamp: Timestamp for data (will be rounded to hour)
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat] in WGS84
            output_path: Path to save output GeoTIFF
            timeout: Download timeout in seconds
            
        Returns:
            Metadata dictionary with statistics, or None if data unavailable
        """
        # Round to nearest hour
        timestamp = timestamp.replace(minute=0, second=0, microsecond=0)
        
        # Build GRIB2 file URL
        url = self._build_stage4_url(timestamp, period='01h')
        
        # Download and process
        return self._download_and_process(
            url=url,
            bbox=bbox,
            output_path=output_path,
            timestamp=timestamp,
            period='1-hour',
            timeout=timeout
        )
    
    def get_6hourly_precip(
        self,
        timestamp: datetime,
        bbox: List[float],
        output_path: Path,
        timeout: int = 300
    ) -> Optional[Dict]:
        """
        Fetch 6-hourly QPE accumulation and convert to GeoTIFF.
        
        File pattern: st4_conus.YYYYMMDDHH.06h.grb2
        
        Args:
            timestamp: Timestamp for data (will be rounded to 6-hour interval)
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat] in WGS84
            output_path: Path to save output GeoTIFF
            timeout: Download timeout in seconds
            
        Returns:
            Metadata dictionary with statistics, or None if data unavailable
        """
        # Round to 6-hour interval (00, 06, 12, 18 UTC)
        hour = (timestamp.hour // 6) * 6
        timestamp = timestamp.replace(hour=hour, minute=0, second=0, microsecond=0)
        
        # Build GRIB2 file URL
        url = self._build_stage4_url(timestamp, period='06h')
        
        # Download and process
        return self._download_and_process(
            url=url,
            bbox=bbox,
            output_path=output_path,
            timestamp=timestamp,
            period='6-hour',
            timeout=timeout
        )
    
    def _build_stage4_url(self, timestamp: datetime, period: str = '01h') -> str:
        """
        Build URL for Stage IV GRIB2 file.
        
        NOMADS URL format:
        https://nomads.ncep.noaa.gov/pub/data/nccf/com/pcpanl/prod/
        pcpanl.YYYYMMDD/st4_conus.YYYYMMDDHH.{period}.grb2
        
        Args:
            timestamp: Datetime for file
            period: Accumulation period ('01h' or '06h')
            
        Returns:
            Full URL to GRIB2 file
        """
        date_str = timestamp.strftime('%Y%m%d')
        datetime_str = timestamp.strftime('%Y%m%d%H')
        
        # Stage IV file path
        file_path = f"pcpanl.{date_str}/st4_conus.{datetime_str}.{period}.grb2"
        
        url = urljoin(self.NOMADS_BASE, file_path)
        return url
    
    def _download_and_process(
        self,
        url: str,
        bbox: List[float],
        output_path: Path,
        timestamp: datetime,
        period: str,
        timeout: int = 300,
        max_retries: int = 3
    ) -> Optional[Dict]:
        """
        Download GRIB2 file and convert to GeoTIFF with subsetting.
        
        Args:
            url: GRIB2 file URL
            bbox: Bounding box for subsetting
            output_path: Output GeoTIFF path
            timestamp: Data timestamp
            period: Accumulation period label
            timeout: Download timeout
            max_retries: Maximum retry attempts
            
        Returns:
            Metadata dictionary or None if unavailable
        """
        temp_dir = output_path.parent / 'temp'
        temp_dir.mkdir(parents=True, exist_ok=True)
        grib_path = temp_dir / f"stage4_{timestamp.strftime('%Y%m%d_%H')}_{period.replace('-', '')}.grb2"
        
        try:
            # Download GRIB2 file
            if not self._download_file(url, grib_path, timeout, max_retries):
                logger.warning(f"Stage IV data not available for {timestamp} ({period})")
                return None
            
            # Check file size
            file_size_mb = grib_path.stat().st_size / (1024 * 1024)
            logger.info(f"Downloaded Stage IV GRIB2: {file_size_mb:.2f} MB")
            
            # Process GRIB2 to GeoTIFF
            metadata = self._process_grib2_to_geotiff(
                grib_path=grib_path,
                bbox=bbox,
                output_path=output_path
            )
            
            # Add metadata
            metadata['timestamp'] = timestamp.isoformat()
            metadata['variable'] = f'precipitation_{period}'
            metadata['accumulation_period'] = period
            metadata['file_size_mb'] = file_size_mb
            
            logger.info(f"Successfully processed Stage IV {period} QPE for {timestamp}")
            return metadata
            
        except Exception as e:
            logger.error(f"Error processing Stage IV data: {e}", exc_info=True)
            raise Stage4Error(f"Failed to process Stage IV data: {e}")
            
        finally:
            # Cleanup temp file
            if grib_path.exists():
                grib_path.unlink()
                logger.debug(f"Cleaned up temp file: {grib_path}")
    
    def _download_file(
        self,
        url: str,
        output_path: Path,
        timeout: int = 300,
        max_retries: int = 3
    ) -> bool:
        """
        Download file with retry logic.
        
        Args:
            url: File URL
            output_path: Where to save file
            timeout: Request timeout
            max_retries: Maximum retry attempts
            
        Returns:
            True if successful, False if file not available
        """
        for attempt in range(max_retries):
            try:
                logger.info(f"Downloading Stage IV (attempt {attempt + 1}/{max_retries}): {url}")
                
                response = self.session.get(url, timeout=timeout, stream=True)
                
                # Check if file exists (404 means data not available)
                if response.status_code == 404:
                    logger.debug(f"Stage IV file not found: {url}")
                    return False
                
                response.raise_for_status()
                
                # Stream to file
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                logger.info(f"Downloaded: {output_path.name} ({output_path.stat().st_size / 1024:.1f} KB)")
                return True
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    return False
                logger.warning(f"HTTP error on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    raise Stage4Error(f"Failed to download after {max_retries} attempts: {e}")
                
            except Exception as e:
                logger.warning(f"Download error on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    raise Stage4Error(f"Failed to download after {max_retries} attempts: {e}")
        
        return False
    
    def _process_grib2_to_geotiff(
        self,
        grib_path: Path,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Extract precipitation from GRIB2 and convert to GeoTIFF with subsetting.
        
        Args:
            grib_path: Input GRIB2 file
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            output_path: Output GeoTIFF path
            
        Returns:
            Dictionary with processing metadata and statistics
        """
        try:
            # Open GRIB2 file with rasterio
            # Stage IV GRIB2 typically has precipitation in band 1
            with rasterio.open(grib_path) as src:
                logger.info(f"GRIB2 bands: {src.count}, CRS: {src.crs}, Shape: {src.shape}")
                
                # Read precipitation band (usually band 1: Total Precipitation)
                # Check band descriptions to find the right one
                band_idx = 1
                if hasattr(src, 'descriptions') and src.descriptions:
                    for i, desc in enumerate(src.descriptions, 1):
                        if desc and 'precip' in desc.lower():
                            band_idx = i
                            logger.info(f"Found precipitation in band {i}: {desc}")
                            break
                
                # Read data
                precip_data = src.read(band_idx)
                src_crs = src.crs
                src_transform = src.transform
                
                # Handle nodata values
                nodata = src.nodata
                if nodata is not None:
                    precip_data = np.ma.masked_equal(precip_data, nodata)
                
                # Convert units if needed (GRIB2 usually in kg/m^2 which equals mm)
                # Stage IV should already be in mm, but verify
                precip_mm = precip_data
                
                # Calculate destination transform for bbox
                # Subset to bounding box in source CRS
                min_lon, min_lat, max_lon, max_lat = bbox
                
                # Transform bbox to source CRS if needed
                if src_crs != CRS.from_epsg(4326):
                    from rasterio.warp import transform_bounds
                    bbox_src = transform_bounds(CRS.from_epsg(4326), src_crs, *bbox)
                else:
                    bbox_src = bbox
                
                # Get window for bbox
                from rasterio.windows import from_bounds as window_from_bounds
                window = window_from_bounds(*bbox_src, transform=src_transform)
                
                # Read subset
                precip_subset = src.read(band_idx, window=window)
                subset_transform = src.window_transform(window)
                
                # Reproject to WGS84 if needed
                if src_crs != CRS.from_epsg(4326):
                    dst_crs = CRS.from_epsg(4326)
                    dst_transform, dst_width, dst_height = calculate_default_transform(
                        src_crs, dst_crs,
                        window.width, window.height,
                        *bbox_src
                    )
                    
                    precip_reprojected = np.zeros((dst_height, dst_width), dtype=precip_subset.dtype)
                    
                    reproject(
                        source=precip_subset,
                        destination=precip_reprojected,
                        src_transform=subset_transform,
                        src_crs=src_crs,
                        dst_transform=dst_transform,
                        dst_crs=dst_crs,
                        resampling=Resampling.bilinear,
                        src_nodata=nodata,
                        dst_nodata=nodata
                    )
                    
                    precip_final = precip_reprojected
                    final_transform = dst_transform
                    final_crs = dst_crs
                else:
                    precip_final = precip_subset
                    final_transform = subset_transform
                    final_crs = src_crs
                
                # Write GeoTIFF
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                with rasterio.open(
                    output_path,
                    'w',
                    driver='GTiff',
                    height=precip_final.shape[0],
                    width=precip_final.shape[1],
                    count=1,
                    dtype=precip_final.dtype,
                    crs=final_crs,
                    transform=final_transform,
                    nodata=nodata,
                    compress='lzw'
                ) as dst:
                    dst.write(precip_final, 1)
                    dst.set_band_description(1, 'Total Precipitation (mm)')
                    
                    # Add metadata
                    dst.update_tags(
                        source='NCEP Stage IV QPE',
                        units='millimeters',
                        variable='precipitation',
                        resolution_km='4'
                    )
                
                # Calculate statistics (excluding nodata)
                valid_data = precip_final[precip_final != nodata] if nodata is not None else precip_final
                
                stats = {
                    'min': float(np.min(valid_data)) if valid_data.size > 0 else None,
                    'max': float(np.max(valid_data)) if valid_data.size > 0 else None,
                    'mean': float(np.mean(valid_data)) if valid_data.size > 0 else None,
                    'std': float(np.std(valid_data)) if valid_data.size > 0 else None,
                    'valid_pixels': int(valid_data.size),
                    'total_pixels': int(precip_final.size),
                    'coverage_pct': float(valid_data.size / precip_final.size * 100) if precip_final.size > 0 else 0,
                    'units': 'mm',
                    'output_shape': precip_final.shape,
                    'output_crs': str(final_crs)
                }
                
                # Log statistics safely (handle None values)
                if stats['min'] is not None and stats['max'] is not None and stats['mean'] is not None:
                    logger.info(f"Stage IV statistics: {stats['min']:.2f} - {stats['max']:.2f} mm, "
                              f"mean: {stats['mean']:.2f} mm, coverage: {stats['coverage_pct']:.1f}%")
                else:
                    logger.info(f"Stage IV statistics: No valid data pixels, coverage: {stats['coverage_pct']:.1f}%")
                
                return stats
                
        except Exception as e:
            logger.error(f"Error processing GRIB2 to GeoTIFF: {e}", exc_info=True)
            raise Stage4Error(f"Failed to process GRIB2: {e}")
