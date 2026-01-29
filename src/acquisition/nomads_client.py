"""NOAA NOMADS client for downloading RTMA and other GRIB2 data.

NOMADS (NOAA Operational Model Archive and Distribution System) provides
direct HTTP access to real-time weather data in GRIB2 format.

RTMA (Real-Time Mesoscale Analysis): 2.5km resolution, hourly updates
- Temperature (2m)
- Precipitation 
- Wind speed/direction
- Pressure
"""

import os
import logging
import time
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple
from urllib.parse import urljoin

import numpy as np
import pygrib
import rasterio
from rasterio.transform import from_bounds
from rasterio.crs import CRS
from rasterio.warp import calculate_default_transform, reproject, Resampling

logger = logging.getLogger(__name__)


class NomadsError(Exception):
    """Base exception for NOMADS client errors."""
    pass


class NomadsClient:
    """Client for accessing NOAA NOMADS data."""
    
    # NOMADS base URLs
    NOMADS_BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/"
    
    # RTMA paths and configuration
    RTMA_PATH = "rtma/prod/"
    RTMA_RESOLUTION = 2500  # meters
    
    # URMA paths and configuration
    URMA_PATH = "urma/prod/"
    URMA_RESOLUTION = 2500  # meters (same as RTMA)
    
    # Variable mappings (shared between RTMA and URMA)
    RTMA_VARIABLES = {
        'temperature': {
            'grib_name': '2t',
            'level': '2 m above ground',
            'units': 'K',
            'description': '2-meter temperature'
        },
        'precipitation': {
            'grib_name': 'tp',
            'level': 'surface',
            'units': 'kg m-2',
            'description': 'Total precipitation'
        },
        'wind_speed': {
            'grib_name': ['10u', '10v'],
            'level': '10 m above ground',
            'units': 'm s-1',
            'description': '10-meter wind speed'
        },
        'wind_u': {
            'grib_name': '10u',
            'level': '10 m above ground',
            'units': 'm s-1',
            'description': 'U-component of wind'
        },
        'wind_v': {
            'grib_name': '10v',
            'level': '10 m above ground',
            'units': 'm s-1',
            'description': 'V-component of wind'
        },
        'pressure': {
            'grib_name': 'sp',
            'level': 'surface',
            'units': 'Pa',
            'description': 'Surface pressure'
        }
    }
    
    def __init__(self):
        """Initialize NOMADS client."""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'StreamflowDataOps/1.0'
        })
        logger.info("NOMADS client initialized")
    
    def get_rtma_data(
        self,
        variable: str,
        timestamp: datetime,
        bbox: List[float],
        output_path: Path,
        timeout: int = 300
    ) -> Dict:
        """
        Fetch RTMA data and convert to GeoTIFF.
        
        Args:
            variable: Variable name ('temperature', 'precipitation', 'wind_speed')
            timestamp: Timestamp for data (hourly)
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat] in WGS84
            output_path: Path to save output GeoTIFF
            timeout: Download timeout in seconds
            
        Returns:
            Metadata dictionary with statistics
        """
        if variable not in self.RTMA_VARIABLES:
            raise NomadsError(f"Unknown RTMA variable: {variable}")
        
        # Round to nearest hour
        timestamp = timestamp.replace(minute=0, second=0, microsecond=0)
        
        # Build GRIB2 file URL
        url = self._build_rtma_url(timestamp)
        
        # Download GRIB2 file
        temp_dir = output_path.parent / 'temp'
        temp_dir.mkdir(parents=True, exist_ok=True)
        grib_path = temp_dir / f"rtma_{timestamp.strftime('%Y%m%d_%H')}00.grib2"
        
        try:
            self._download_file(url, grib_path, timeout=timeout)
            
            # Extract variable and convert to GeoTIFF
            metadata = self._extract_rtma_to_geotiff(
                grib_path=grib_path,
                variable=variable,
                bbox=bbox,
                output_path=output_path
            )
            
            # Add timestamp and variable to metadata
            metadata['timestamp'] = timestamp.isoformat()
            metadata['variable'] = variable
            
            return metadata
            
        finally:
            # Cleanup temp file
            if grib_path.exists():
                grib_path.unlink()
            if temp_dir.exists() and not list(temp_dir.iterdir()):
                temp_dir.rmdir()
    
    def _build_rtma_url(self, timestamp: datetime) -> str:
        """
        Build URL for RTMA GRIB2 file.
        
        RTMA URL format:
        https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/
        rtma2p5.YYYYMMDD/rtma2p5.tHHz.2dvaranl_ndfd.grb2_wexp
        
        Note: RTMA files have _wexp suffix (weather experiment)
        """
        date_str = timestamp.strftime('%Y%m%d')
        hour_str = timestamp.strftime('%H')
        
        # RTMA file path with _wexp suffix
        file_path = f"rtma2p5.{date_str}/rtma2p5.t{hour_str}z.2dvaranl_ndfd.grb2_wexp"
        
        url = urljoin(self.NOMADS_BASE + self.RTMA_PATH, file_path)
        return url
    
    def _download_file(
        self,
        url: str,
        output_path: Path,
        timeout: int = 300,
        max_retries: int = 3
    ) -> None:
        """
        Download file with retry logic.
        
        Args:
            url: File URL
            output_path: Where to save file
            timeout: Request timeout
            max_retries: Maximum retry attempts
        """
        for attempt in range(max_retries):
            try:
                logger.info(f"Downloading: {url}")
                
                response = self.session.get(url, timeout=timeout, stream=True)
                response.raise_for_status()
                
                # Stream to file
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                file_size = output_path.stat().st_size
                logger.info(f"Downloaded: {output_path.name} ({file_size:,} bytes)")
                return
                
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Download attempt {attempt+1} failed: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    raise NomadsError(f"Download failed after {max_retries} attempts: {e}")
    
    def _extract_rtma_to_geotiff(
        self,
        grib_path: Path,
        variable: str,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Extract variable from RTMA GRIB2 and convert to GeoTIFF.
        
        RTMA uses Lambert Conformal projection - needs reprojection to WGS84.
        """
        try:
            var_config = self.RTMA_VARIABLES[variable]
            grib_name = var_config['grib_name']
            
            # Handle wind speed (needs both U and V components)
            if variable == 'wind_speed':
                return self._extract_wind_speed(grib_path, bbox, output_path)
            
            # Open GRIB2 with pygrib
            logger.info(f"Opening GRIB file {grib_path} for variable {variable} (GRIB: {grib_name})")
            
            grbs = pygrib.open(str(grib_path))
            
            # Parse level information
            level_str = var_config['level']
            
            # Find the matching GRIB message
            grb = None
            if 'above ground' in level_str:
                # Extract height value (e.g., "2 m above ground" -> 2)
                import re
                match = re.search(r'(\d+)\s*m', level_str)
                height = int(match.group(1)) if match else None
                
                # Search for message with matching name and level
                for msg in grbs:
                    if msg.shortName == grib_name and hasattr(msg, 'level') and msg.level == height:
                        grb = msg
                        logger.info(f"Found {grib_name} at {height}m: {msg.name}")
                        break
            else:
                # Surface level
                for msg in grbs:
                    if msg.shortName == grib_name and (not hasattr(msg, 'level') or msg.typeOfLevel == 'surface'):
                        grb = msg
                        logger.info(f"Found surface {grib_name}: {msg.name}")
                        break
            
            if grb is None:
                grbs.close()
                raise NomadsError(f"Could not find {grib_name} in GRIB file")
            
            # Extract data and coordinates
            data = grb.values
            lats, lons = grb.latlons()
            
            # Get projection info from GRIB
            proj_params = grb.projparams
            logger.info(f"GRIB projection params: {proj_params}")
            
            # RTMA uses Lambert Conformal Conic projection
            # Build CRS from GRIB parameters
            if 'proj' in proj_params and proj_params['proj'] == 'lcc':
                src_crs = CRS.from_proj4(
                    f"+proj=lcc +lat_1={proj_params.get('lat_1', 25)} "
                    f"+lat_2={proj_params.get('lat_2', 25)} "
                    f"+lat_0={proj_params.get('lat_0', 25)} "
                    f"+lon_0={proj_params.get('lon_0', -95)} "
                    f"+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
                )
            else:
                # Fallback: Standard RTMA Lambert Conformal
                src_crs = CRS.from_proj4(
                    '+proj=lcc +lat_1=25 +lat_2=25 +lat_0=25 +lon_0=-95 '
                    '+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs'
                )
            
            logger.info(f"Source CRS: {src_crs}")
            
            # Create source transform from lat/lon bounds
            # Get bounds in WGS84
            lat_min, lat_max = lats.min(), lats.max()
            lon_min, lon_max = lons.min(), lons.max()
            
            logger.info(f"Data bounds: lon [{lon_min}, {lon_max}], lat [{lat_min}, {lat_max}]")
            logger.info(f"Data shape: {data.shape}")
            
            # Since we have lat/lon for each pixel, we can directly work in WGS84
            # Create a transform based on the lat/lon grid
            dst_crs = CRS.from_epsg(4326)  # WGS84
            
            # Calculate transform for the output in WGS84
            # Crop to bbox
            mask_lat = (lats >= bbox[1]) & (lats <= bbox[3])
            mask_lon = (lons >= bbox[0]) & (lons <= bbox[2])
            mask = mask_lat & mask_lon
            
            if not mask.any():
                grbs.close()
                raise NomadsError(f"No data in bbox {bbox}")
            
            # Find the bounding box of valid data
            rows, cols = np.where(mask)
            row_min, row_max = rows.min(), rows.max()
            col_min, col_max = cols.min(), cols.max()
            
            # Crop data and coordinates
            data_crop = data[row_min:row_max+1, col_min:col_max+1]
            lats_crop = lats[row_min:row_max+1, col_min:col_max+1]
            lons_crop = lons[row_min:row_max+1, col_min:col_max+1]
            
            # Create transform from cropped lat/lon
            height, width = data_crop.shape
            transform = from_bounds(
                lons_crop.min(), lats_crop.min(),
                lons_crop.max(), lats_crop.max(),
                width, height
            )
            
            # Calculate statistics
            valid_data = data_crop[~np.isnan(data_crop)]
            stats = {
                'min': float(np.min(valid_data)) if len(valid_data) > 0 else None,
                'max': float(np.max(valid_data)) if len(valid_data) > 0 else None,
                'mean': float(np.mean(valid_data)) if len(valid_data) > 0 else None,
                'std': float(np.std(valid_data)) if len(valid_data) > 0 else None,
                'count': int(len(valid_data)),
                'units': var_config['units'],
                'description': var_config['description']
            }
            
            logger.info(f"Statistics: {stats}")
            
            # Write to GeoTIFF
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=height,
                width=width,
                count=1,
                dtype=data_crop.dtype,
                crs=dst_crs,
                transform=transform,
                compress='lzw'
            ) as dst:
                dst.write(data_crop, 1)
                dst.update_tags(**{k: str(v) for k, v in stats.items()})
            
            logger.info(f"Converted RTMA {variable} to {output_path}")
            grbs.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to extract RTMA data: {e}")
            raise NomadsError(f"RTMA extraction failed: {e}")
    
    def _extract_wind_speed(
        self,
        grib_path: Path,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Calculate wind speed from U and V components.
        
        Wind speed = sqrt(U² + V²)
        """
        try:
            logger.info(f"Extracting wind speed from {grib_path}")
            
            # Open GRIB2 with pygrib
            grbs = pygrib.open(str(grib_path))
            
            # Find U and V components at 10m
            grb_u = None
            grb_v = None
            
            for msg in grbs:
                if msg.shortName == '10u' and hasattr(msg, 'level') and msg.level == 10:
                    grb_u = msg
                    logger.info(f"Found U component: {msg.name}")
                elif msg.shortName == '10v' and hasattr(msg, 'level') and msg.level == 10:
                    grb_v = msg
                    logger.info(f"Found V component: {msg.name}")
                
                if grb_u and grb_v:
                    break
            
            if grb_u is None or grb_v is None:
                grbs.close()
                raise NomadsError("Could not find U and V wind components at 10m")
            
            # Extract data and coordinates
            u_data = grb_u.values
            v_data = grb_v.values
            lats, lons = grb_u.latlons()
            
            # Calculate wind speed
            wind_speed = np.sqrt(u_data**2 + v_data**2)
            
            logger.info(f"Calculated wind speed, shape: {wind_speed.shape}")
            
            # Crop to bbox
            mask_lat = (lats >= bbox[1]) & (lats <= bbox[3])
            mask_lon = (lons >= bbox[0]) & (lons <= bbox[2])
            mask = mask_lat & mask_lon
            
            if not mask.any():
                grbs.close()
                raise NomadsError(f"No data in bbox {bbox}")
            
            # Find bounding box of valid data
            rows, cols = np.where(mask)
            row_min, row_max = rows.min(), rows.max()
            col_min, col_max = cols.min(), cols.max()
            
            # Crop data and coordinates
            data_crop = wind_speed[row_min:row_max+1, col_min:col_max+1]
            lats_crop = lats[row_min:row_max+1, col_min:col_max+1]
            lons_crop = lons[row_min:row_max+1, col_min:col_max+1]
            
            # Create transform
            height, width = data_crop.shape
            transform = from_bounds(
                lons_crop.min(), lats_crop.min(),
                lons_crop.max(), lats_crop.max(),
                width, height
            )
            
            # Calculate statistics
            valid_data = data_crop[~np.isnan(data_crop)]
            stats = {
                'min': float(np.min(valid_data)) if len(valid_data) > 0 else None,
                'max': float(np.max(valid_data)) if len(valid_data) > 0 else None,
                'mean': float(np.mean(valid_data)) if len(valid_data) > 0 else None,
                'std': float(np.std(valid_data)) if len(valid_data) > 0 else None,
                'count': int(len(valid_data)),
                'units': 'm s-1',
                'description': '10-meter wind speed'
            }
            
            logger.info(f"Wind speed statistics: {stats}")
            
            # Write to GeoTIFF
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=height,
                width=width,
                count=1,
                dtype=data_crop.dtype,
                crs=CRS.from_epsg(4326),
                transform=transform,
                compress='lzw'
            ) as dst:
                dst.write(data_crop, 1)
                dst.update_tags(**{k: str(v) for k, v in stats.items()})
            
            logger.info(f"Converted wind speed to {output_path}")
            grbs.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to extract wind speed: {e}")
            raise NomadsError(f"Wind speed extraction failed: {e}")
    
    def check_data_availability(
        self,
        timestamp: datetime,
        max_age_hours: int = 6
    ) -> bool:
        """
        Check if RTMA data is available for given timestamp.
        
        RTMA is typically available within 1-2 hours of observation time.
        
        Args:
            timestamp: Desired data timestamp
            max_age_hours: Maximum age in hours to check back
            
        Returns:
            True if data is available
        """
        # Round to hour
        timestamp = timestamp.replace(minute=0, second=0, microsecond=0)
        
        # RTMA data is near-real-time, check if timestamp is recent enough
        now = datetime.now(timezone.utc)
        # Make sure timestamp is timezone-aware for comparison
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_hours = (now - timestamp).total_seconds() / 3600
        
        if age_hours > max_age_hours:
            logger.warning(f"Requested data is {age_hours:.1f} hours old (max: {max_age_hours})")
            return False
        
        # Check if URL exists
        url = self._build_rtma_url(timestamp)
        
        try:
            response = self.session.head(url, timeout=10)
            available = response.status_code == 200
            
            if available:
                logger.info(f"RTMA data available for {timestamp}")
            else:
                logger.info(f"RTMA data not yet available for {timestamp} (status: {response.status_code})")
            
            return available
            
        except Exception as e:
            logger.error(f"Failed to check RTMA availability: {e}")
            return False
    
    def get_urma_data(
        self,
        variable: str,
        timestamp: datetime,
        bbox: List[float],
        output_path: Path,
        timeout: int = 300
    ) -> Dict:
        """
        Fetch URMA data and convert to GeoTIFF.
        
        URMA (UnRestricted Mesoscale Analysis) is similar to RTMA but uses
        only unrestricted data sources.
        
        Args:
            variable: Variable name ('temperature', 'precipitation', 'wind_speed')
            timestamp: Timestamp for data (hourly)
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat] in WGS84
            output_path: Path to save output GeoTIFF
            timeout: Download timeout in seconds
            
        Returns:
            Metadata dictionary with statistics
        """
        if variable not in self.RTMA_VARIABLES:  # URMA uses same variables as RTMA
            raise NomadsError(f"Unknown URMA variable: {variable}")
        
        # Round to nearest hour
        timestamp = timestamp.replace(minute=0, second=0, microsecond=0)
        
        # Build GRIB2 file URL
        url = self._build_urma_url(timestamp)
        
        # Download GRIB2 file
        temp_dir = output_path.parent / 'temp'
        temp_dir.mkdir(parents=True, exist_ok=True)
        grib_path = temp_dir / f"urma_{timestamp.strftime('%Y%m%d_%H')}00.grib2"
        
        try:
            self._download_file(url, grib_path, timeout=timeout)
            
            # Extract variable and convert to GeoTIFF (same as RTMA)
            metadata = self._extract_rtma_to_geotiff(
                grib_path=grib_path,
                variable=variable,
                bbox=bbox,
                output_path=output_path
            )
            
            # Add timestamp and variable to metadata
            metadata['timestamp'] = timestamp.isoformat()
            metadata['variable'] = variable
            metadata['source'] = 'URMA'
            
            return metadata
            
        finally:
            # Cleanup temp file
            if grib_path.exists():
                grib_path.unlink()
            if temp_dir.exists() and not list(temp_dir.iterdir()):
                temp_dir.rmdir()
    
    def _build_urma_url(self, timestamp: datetime) -> str:
        """
        Build URL for URMA GRIB2 file.
        
        URMA URL format:
        https://nomads.ncep.noaa.gov/pub/data/nccf/com/urma/prod/
        urma2p5.YYYYMMDD/urma2p5.tHHz.2dvaranl_ndfd.grb2_wexp
        
        Note: URMA files use same naming as RTMA (with _wexp suffix)
        """
        date_str = timestamp.strftime('%Y%m%d')
        hour_str = timestamp.strftime('%H')
        
        # URMA file path with _wexp suffix (same format as RTMA)
        file_path = f"urma2p5.{date_str}/urma2p5.t{hour_str}z.2dvaranl_ndfd.grb2_wexp"
        
        url = urljoin(self.NOMADS_BASE + self.URMA_PATH, file_path)
        return url
    
    def check_urma_availability(
        self,
        timestamp: datetime,
        max_age_hours: int = 48
    ) -> bool:
        """
        Check if URMA data is available for given timestamp.
        
        URMA is typically available within 1-2 hours of observation time,
        similar to RTMA.
        
        Args:
            timestamp: Desired data timestamp
            max_age_hours: Maximum age in hours to check back
            
        Returns:
            True if data is available
        """
        # Round to hour
        timestamp = timestamp.replace(minute=0, second=0, microsecond=0)
        
        # URMA data is near-real-time, check if timestamp is recent enough
        now = datetime.now(timezone.utc)
        # Make sure timestamp is timezone-aware for comparison
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_hours = (now - timestamp).total_seconds() / 3600
        
        if age_hours > max_age_hours:
            logger.warning(f"Requested data is {age_hours:.1f} hours old (max: {max_age_hours})")
            return False
        
        # Check if URL exists
        url = self._build_urma_url(timestamp)
        
        try:
            response = self.session.head(url, timeout=10)
            available = response.status_code == 200
            
            if available:
                logger.info(f"URMA data available for {timestamp}")
            else:
                logger.info(f"URMA data not yet available for {timestamp} (status: {response.status_code})")
            
            return available
            
        except Exception as e:
            logger.error(f"Failed to check URMA availability: {e}")
            return False
