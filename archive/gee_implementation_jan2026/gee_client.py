"""Google Earth Engine client for fetching raster data."""

import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Union

import ee
from django.conf import settings

logger = logging.getLogger(__name__)


class GEEClientError(Exception):
    """Base exception for GEE client errors."""
    pass


class GEEAuthenticationError(GEEClientError):
    """Raised when GEE authentication fails."""
    pass


class GEEDataNotAvailableError(GEEClientError):
    """Raised when requested data is not available."""
    pass


class GEEClient:
    """Client for interacting with Google Earth Engine API."""

    def __init__(self):
        """Initialize GEE client."""
        self.authenticated = False
        self._initialize()

    def _initialize(self):
        """Initialize Earth Engine API."""
        try:
            # Try to authenticate with service account
            if hasattr(settings, 'GEE_SERVICE_ACCOUNT_KEY') and settings.GEE_SERVICE_ACCOUNT_KEY:
                credentials_path = settings.GEE_SERVICE_ACCOUNT_KEY
                if os.path.exists(credentials_path):
                    credentials = ee.ServiceAccountCredentials(
                        email=settings.GEE_SERVICE_ACCOUNT_EMAIL,
                        key_file=credentials_path
                    )
                    ee.Initialize(credentials)
                    self.authenticated = True
                    logger.info("GEE authenticated with service account")
                else:
                    logger.warning(f"GEE service account key not found at {credentials_path}")
            
            # Fall back to standard authentication
            if not self.authenticated:
                try:
                    ee.Initialize()
                    self.authenticated = True
                    logger.info("GEE authenticated with default credentials")
                except Exception as e:
                    logger.error(f"GEE initialization failed: {e}")
                    raise GEEAuthenticationError(f"Failed to authenticate with GEE: {e}")
                    
        except Exception as e:
            logger.error(f"GEE initialization error: {e}")
            raise GEEAuthenticationError(f"GEE initialization failed: {e}")

    def get_rtma_image(
        self,
        variable: str,
        timestamp: datetime,
        bbox: List[float],
        resolution: int = 2500
    ) -> Optional[ee.Image]:
        """
        Fetch RTMA image for a specific variable and time.
        
        Args:
            variable: Variable name ('temperature', 'precipitation', 'wind_speed')
            timestamp: Data timestamp (UTC)
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            resolution: Resolution in meters (default 2500)
            
        Returns:
            Earth Engine Image object or None if not available
        """
        if not self.authenticated:
            raise GEEAuthenticationError("GEE client not authenticated")
        
        # Map variable names to RTMA band names
        variable_bands = {
            'temperature': 'TMP',
            'precipitation': 'APCP',
            'wind_speed': 'WIND',
        }
        
        if variable not in variable_bands:
            raise ValueError(f"Unknown variable: {variable}. Must be one of {list(variable_bands.keys())}")
        
        band_name = variable_bands[variable]
        
        try:
            # RTMA collection
            collection = ee.ImageCollection('NOAA/NWS/RTMA')
            
            # Define time window (RTMA updates hourly, give 2-hour window)
            start_time = timestamp - timedelta(hours=1)
            end_time = timestamp + timedelta(hours=1)
            
            # Filter collection
            filtered = collection.filterDate(
                start_time.strftime('%Y-%m-%d %H:%M:%S'),
                end_time.strftime('%Y-%m-%d %H:%M:%S')
            ).filterBounds(ee.Geometry.Rectangle(bbox))
            
            # Get the closest image
            image_list = filtered.toList(10)
            count = image_list.size().getInfo()
            
            if count == 0:
                logger.warning(f"No RTMA data found for {timestamp}")
                return None
            
            # Get first image and select band
            image = ee.Image(image_list.get(0)).select(band_name)
            
            logger.info(f"Found RTMA {variable} image for {timestamp}")
            return image
            
        except Exception as e:
            logger.error(f"Error fetching RTMA data: {e}")
            raise GEEClientError(f"Failed to fetch RTMA data: {e}")

    def get_smap_image(
        self,
        variable: str,
        date: datetime,
        bbox: List[float],
        resolution: int = 9000
    ) -> Optional[ee.Image]:
        """
        Fetch SMAP SPL4 soil moisture image.
        
        Args:
            variable: Variable name ('soil_moisture_surface', 'soil_moisture_rootzone')
            date: Data date (SMAP is daily)
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            resolution: Resolution in meters (default 9000)
            
        Returns:
            Earth Engine Image object or None if not available
        """
        if not self.authenticated:
            raise GEEAuthenticationError("GEE client not authenticated")
        
        # Map variable names to SMAP band names
        variable_bands = {
            'soil_moisture_surface': 'sm_surface',
            'soil_moisture_rootzone': 'sm_rootzone',
        }
        
        if variable not in variable_bands:
            raise ValueError(f"Unknown variable: {variable}. Must be one of {list(variable_bands.keys())}")
        
        band_name = variable_bands[variable]
        
        try:
            # SMAP SPL4 collection
            collection = ee.ImageCollection('NASA/SMAP/SPL4SMGP/008')
            
            # Filter by date (SMAP is daily, 3-hour resolution)
            start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=1)
            
            filtered = collection.filterDate(
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d')
            ).filterBounds(ee.Geometry.Rectangle(bbox))
            
            # Get images
            image_list = filtered.toList(10)
            count = image_list.size().getInfo()
            
            if count == 0:
                logger.warning(f"No SMAP data found for {date.date()}")
                return None
            
            # Use the first image (noon time typically)
            image = ee.Image(image_list.get(0)).select(band_name)
            
            logger.info(f"Found SMAP {variable} image for {date.date()}")
            return image
            
        except Exception as e:
            logger.error(f"Error fetching SMAP data: {e}")
            raise GEEClientError(f"Failed to fetch SMAP data: {e}")

    def export_to_geotiff(
        self,
        image: ee.Image,
        output_path: Union[str, Path],
        bbox: List[float],
        scale: int,
        crs: str = 'EPSG:4326',
        max_pixels: int = 1e8
    ) -> Dict:
        """
        Export GEE image to GeoTIFF file.
        
        Args:
            image: Earth Engine Image to export
            output_path: Local path to save GeoTIFF
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            scale: Export resolution in meters
            crs: Coordinate reference system
            max_pixels: Maximum number of pixels to export
            
        Returns:
            Dictionary with export metadata
        """
        if not self.authenticated:
            raise GEEAuthenticationError("GEE client not authenticated")
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Define region
            region = ee.Geometry.Rectangle(bbox)
            
            # Get download URL
            url = image.getDownloadURL({
                'region': region,
                'scale': scale,
                'crs': crs,
                'format': 'GEO_TIFF',
                'maxPixels': max_pixels
            })
            
            # Download the file
            import requests
            response = requests.get(url, timeout=300)
            response.raise_for_status()
            
            # Save to file
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            file_size = output_path.stat().st_size
            
            logger.info(f"Exported GeoTIFF to {output_path} ({file_size} bytes)")
            
            return {
                'file_path': str(output_path),
                'file_size': file_size,
                'bbox': bbox,
                'scale': scale,
                'crs': crs,
            }
            
        except Exception as e:
            logger.error(f"Error exporting to GeoTIFF: {e}")
            if output_path.exists():
                output_path.unlink()
            raise GEEClientError(f"Failed to export GeoTIFF: {e}")

    def check_data_availability(
        self,
        collection_id: str,
        start_date: datetime,
        end_date: datetime,
        bbox: List[float]
    ) -> Dict:
        """
        Check data availability for a collection.
        
        Args:
            collection_id: GEE collection ID
            start_date: Start date
            end_date: End date
            bbox: Bounding box
            
        Returns:
            Dictionary with availability information
        """
        if not self.authenticated:
            raise GEEAuthenticationError("GEE client not authenticated")
        
        try:
            collection = ee.ImageCollection(collection_id)
            
            filtered = collection.filterDate(
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d')
            ).filterBounds(ee.Geometry.Rectangle(bbox))
            
            count = filtered.size().getInfo()
            
            # Get date range if available
            if count > 0:
                first = ee.Image(filtered.first())
                last = ee.Image(filtered.sort('system:time_start', False).first())
                
                first_date = datetime.fromtimestamp(
                    first.get('system:time_start').getInfo() / 1000
                )
                last_date = datetime.fromtimestamp(
                    last.get('system:time_start').getInfo() / 1000
                )
            else:
                first_date = None
                last_date = None
            
            return {
                'collection_id': collection_id,
                'count': count,
                'first_date': first_date,
                'last_date': last_date,
                'available': count > 0
            }
            
        except Exception as e:
            logger.error(f"Error checking data availability: {e}")
            return {
                'collection_id': collection_id,
                'count': 0,
                'available': False,
                'error': str(e)
            }

    def get_image_statistics(
        self,
        image: ee.Image,
        bbox: List[float],
        scale: int
    ) -> Dict:
        """
        Calculate statistics for an image.
        
        Args:
            image: Earth Engine Image
            bbox: Bounding box
            scale: Resolution for calculations
            
        Returns:
            Dictionary with min, max, mean, stddev
        """
        if not self.authenticated:
            raise GEEAuthenticationError("GEE client not authenticated")
        
        try:
            region = ee.Geometry.Rectangle(bbox)
            
            # Get statistics
            stats = image.reduceRegion(
                reducer=ee.Reducer.minMax().combine(
                    ee.Reducer.mean(), '', True
                ).combine(
                    ee.Reducer.stdDev(), '', True
                ),
                geometry=region,
                scale=scale,
                maxPixels=1e9
            ).getInfo()
            
            # Extract band name (assumes single band)
            band_names = list(stats.keys())
            base_band = band_names[0].split('_')[0] if band_names else 'band'
            
            return {
                'min': stats.get(f'{base_band}_min'),
                'max': stats.get(f'{base_band}_max'),
                'mean': stats.get(f'{base_band}_mean'),
                'std_dev': stats.get(f'{base_band}_stdDev'),
            }
            
        except Exception as e:
            logger.error(f"Error calculating statistics: {e}")
            return {}
