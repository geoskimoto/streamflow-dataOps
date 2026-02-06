"""NASA EarthData client for downloading satellite/raster data.

This module provides a unified interface for accessing NASA EarthData datasets:
- SMAP soil moisture (SPL4SMGP_008)
- GPM precipitation (GPM_3IMERGDF_07)
- MODIS land surface temperature (MOD11A1_061, MYD11A1_061)
"""

import os
import logging
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
from urllib.parse import urlparse

import earthaccess
import h5py
import xarray as xr
import numpy as np
from rasterio.transform import from_bounds
from rasterio import MemoryFile
from rasterio.crs import CRS

from src.acquisition.earthdata_processor import EarthDataRasterProcessor

logger = logging.getLogger(__name__)


class EarthDataError(Exception):
    """Base exception for EarthData client errors."""
    pass


class EarthDataAuthenticationError(EarthDataError):
    """Raised when authentication fails."""
    pass


class EarthDataClient:
    """Client for interacting with NASA EarthData API."""
    
    # Collection IDs (short names for CMR API)
    COLLECTIONS = {
        'SMAP_SPL4': 'SPL4SMGP',  # SMAP L4 Global Soil Moisture
        'GPM_IMERG': 'GPM_3IMERGDF',  # GPM IMERG Final Daily
        'MODIS_LST_TERRA': 'MOD11A1',  # MODIS Terra LST Daily
        'MODIS_LST_AQUA': 'MYD11A1',  # MODIS Aqua LST Daily
    }
    
    # DAAC providers
    DAACS = {
        'SMAP_SPL4': 'NSIDC_CPRD',
        'GPM_IMERG': 'GES_DISC',
        'MODIS_LST_TERRA': 'LPDAAC_ECS',
        'MODIS_LST_AQUA': 'LPDAAC_ECS',
    }

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None):
        """
        Initialize EarthData client.
        
        Args:
            username: EarthData username (reads from .netrc if not provided)
            password: EarthData password (reads from .netrc if not provided)
        """
        self.username = username or os.getenv('EARTHDATA_USERNAME')
        self.password = password or os.getenv('EARTHDATA_PASSWORD')
        
        if not self.username or not self.password:
            raise EarthDataAuthenticationError(
                "NASA EarthData credentials not provided. "
                "Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD environment variables "
                "or pass username/password parameters."
            )
        
        self.authenticated = False
        self.auth = None
        self.processor = EarthDataRasterProcessor()
        self._initialize()
    
    def _initialize(self):
        """Initialize authentication with EarthData."""
        try:
            # Set environment variables for earthaccess
            if self.username:
                os.environ['EARTHDATA_USERNAME'] = self.username
            if self.password:
                os.environ['EARTHDATA_PASSWORD'] = self.password
            
            # earthaccess will use environment variables
            self.auth = earthaccess.login(
                strategy="environment",
                persist=False
            )
            
            if self.auth:
                self.authenticated = True
                logger.info("Successfully authenticated with NASA EarthData")
            else:
                raise EarthDataAuthenticationError("Failed to authenticate with EarthData")
                
        except Exception as e:
            logger.error(f"EarthData authentication failed: {e}")
            raise EarthDataAuthenticationError(f"Authentication failed: {e}")
    
    def find_latest_available_date(
        self,
        collection_id: str,
        bbox: List[float],
        days_back: int = 14
    ) -> Optional[datetime]:
        """
        Find the most recent date with available data by searching backwards.
        
        Args:
            collection_id: Collection short name (e.g., 'SPL4SMGP_008')
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            days_back: How many days back to search (default: 14)
            
        Returns:
            Most recent date with data, or None if no data found
        """
        if not self.authenticated:
            raise EarthDataAuthenticationError("Not authenticated")
        
        try:
            from datetime import timedelta
            
            # Search from today backwards
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            logger.info(f"Searching for latest {collection_id} data from {start_date.date()} to {end_date.date()}")
            
            # Search with wider date range
            results = earthaccess.search_data(
                short_name=collection_id,
                bounding_box=tuple(bbox),
                temporal=(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')),
                count=50  # Get recent granules
            )
            
            if not results:
                logger.warning(f"No data found for {collection_id} in last {days_back} days")
                return None
            
            # Extract dates from granules and find most recent
            dates = []
            for granule in results:
                try:
                    # Get temporal extent from granule metadata
                    temporal = granule.get('umm', {}).get('TemporalExtent', {})
                    range_dt = temporal.get('RangeDateTime', {})
                    if range_dt and 'BeginningDateTime' in range_dt:
                        date_str = range_dt['BeginningDateTime']
                        date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        dates.append(date)
                except Exception as e:
                    logger.debug(f"Could not parse date from granule: {e}")
                    continue
            
            if dates:
                latest = max(dates)
                logger.info(f"Latest available data for {collection_id}: {latest.date()}")
                return latest
            else:
                logger.warning(f"Could not determine dates for {collection_id} granules")
                return None
                
        except Exception as e:
            logger.error(f"Failed to find latest date: {e}")
            return None
    
    def search_granules(
        self,
        collection_id: str,
        bbox: List[float],
        start_date: datetime,
        end_date: datetime,
        limit: int = 10
    ) -> List[Dict]:
        """
        Search for data granules matching criteria.
        
        Args:
            collection_id: Collection short name (e.g., 'SPL4SMGP_008')
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            start_date: Start date for search
            end_date: End date for search
            limit: Maximum number of results
            
        Returns:
            List of granule metadata dictionaries
        """
        if not self.authenticated:
            raise EarthDataAuthenticationError("Not authenticated")
        
        try:
            # Search using earthaccess
            results = earthaccess.search_data(
                short_name=collection_id,
                bounding_box=tuple(bbox),
                temporal=(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')),
                count=limit
            )
            
            logger.info(f"Found {len(results)} granules for {collection_id}")
            return results
            
        except Exception as e:
            logger.error(f"Granule search failed: {e}")
            raise EarthDataError(f"Search failed: {e}")
    
    def download_granule(
        self,
        granule,
        output_dir: Path,
        timeout: int = 300,
        max_retries: int = 3
    ) -> Path:
        """
        Download a single granule with retry logic.
        
        Args:
            granule: Granule object from search_granules()
            output_dir: Directory to save downloaded file
            timeout: Download timeout in seconds
            max_retries: Maximum retry attempts
            
        Returns:
            Path to downloaded file
        """
        if not self.authenticated:
            raise EarthDataAuthenticationError("Not authenticated")
        
        for attempt in range(max_retries):
            try:
                output_dir = Path(output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                
                # Download using earthaccess
                files = earthaccess.download(
                    granules=[granule],
                    local_path=str(output_dir)
                )
                
                if files and len(files) > 0:
                    downloaded_file = Path(files[0])
                    logger.info(f"Downloaded: {downloaded_file.name} (attempt {attempt+1}/{max_retries})")
                    return downloaded_file
                else:
                    raise EarthDataError("Download failed - no files returned")
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(f"Download attempt {attempt+1} failed: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Download failed after {max_retries} attempts: {e}")
                    raise EarthDataError(f"Download failed after {max_retries} attempts: {e}")
    
    def get_smap_data(
        self,
        variable: str,
        date: datetime,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Fetch SMAP soil moisture data.
        
        Args:
            variable: Variable name ('soil_moisture_surface' or 'soil_moisture_rootzone')
            date: Date to fetch (SMAP is 3-hourly, will get closest)
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            output_path: Path to save GeoTIFF
            
        Returns:
            Dictionary with metadata (min, max, mean, std, units)
        """
        # Map variable names to SMAP band names
        variable_map = {
            'soil_moisture_surface': 'sm_surface',
            'soil_moisture_rootzone': 'sm_rootzone',
        }
        
        if variable not in variable_map:
            raise ValueError(f"Unknown variable: {variable}")
        
        band_name = variable_map[variable]
        
        try:
            # Search for granules
            granules = self.search_granules(
                collection_id=self.COLLECTIONS['SMAP_SPL4'],
                bbox=bbox,
                start_date=date,
                end_date=date + timedelta(days=1),
                limit=8  # Get all 3-hourly for the day
            )
            
            if not granules:
                logger.warning(f"No SMAP data found for {date.date()}")
                return None
            
            # Download first granule (or find closest to target time)
            temp_dir = output_path.parent / 'temp'
            downloaded = self.download_granule(granules[0], temp_dir)
            
            # Process HDF5 to GeoTIFF
            metadata = self.processor.process_smap_hdf5(
                input_path=downloaded,
                variable=band_name,
                bbox=bbox,
                output_path=output_path
            )
            
            # Cleanup temp file
            if downloaded.exists():
                downloaded.unlink()
            if temp_dir.exists() and not list(temp_dir.iterdir()):
                temp_dir.rmdir()
            
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to get SMAP data: {e}")
            raise EarthDataError(f"SMAP data fetch failed: {e}")
    
    def _extract_smap_to_geotiff(
        self,
        hdf5_path: Path,
        band_name: str,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Extract SMAP data from HDF5 and convert to GeoTIFF.
        
        Args:
            hdf5_path: Path to downloaded HDF5 file
            band_name: Band to extract (e.g., 'sm_surface')
            bbox: Bounding box for subsetting
            output_path: Output GeoTIFF path
            
        Returns:
            Metadata dictionary
        """
        try:
            # Open HDF5 file
            with h5py.File(hdf5_path, 'r') as f:
                # SMAP structure: /Geophysical_Data/sm_surface, etc.
                data_group = f['Geophysical_Data']
                
                # Extract variable data
                sm_data = data_group[band_name][:]
                
                # Get coordinates (SMAP uses EASE-Grid 2.0)
                # For simplicity, we'll use xarray to handle this
                pass
            
            # Use xarray for easier coordinate handling
            ds = xr.open_dataset(hdf5_path, group='Geophysical_Data')
            
            # Get variable
            var_data = ds[band_name]
            
            # Subset to bounding box
            # Note: SMAP coordinates need special handling
            # For now, extract full array and subset later
            data_array = var_data.values
            
            # Get lat/lon grids
            lats = ds['lat'].values if 'lat' in ds else None
            lons = ds['lon'].values if 'lon' in ds else None
            
            # Calculate statistics
            valid_data = data_array[~np.isnan(data_array)]
            stats = {
                'min': float(np.min(valid_data)) if len(valid_data) > 0 else None,
                'max': float(np.max(valid_data)) if len(valid_data) > 0 else None,
                'mean': float(np.mean(valid_data)) if len(valid_data) > 0 else None,
                'std': float(np.std(valid_data)) if len(valid_data) > 0 else None,
                'units': var_data.attrs.get('units', 'm³/m³'),
                'long_name': var_data.attrs.get('long_name', band_name),
            }
            
            # TODO: Convert to GeoTIFF with proper georeferencing
            # This requires reprojection from EASE-Grid to WGS84
            # For now, we'll save as NetCDF and handle conversion separately
            
            logger.info(f"Extracted SMAP {band_name}: {stats}")
            
            ds.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to extract SMAP data: {e}")
            raise EarthDataError(f"SMAP extraction failed: {e}")
    
    def get_gpm_data(
        self,
        date: datetime,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Fetch GPM IMERG daily precipitation data.
        
        Args:
            date: Date to fetch
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            output_path: Path to save GeoTIFF
            
        Returns:
            Dictionary with metadata
        """
        try:
            # Search for granules
            granules = self.search_granules(
                collection_id=self.COLLECTIONS['GPM_IMERG'],
                bbox=bbox,
                start_date=date,
                end_date=date + timedelta(days=1),
                limit=1
            )
            
            if not granules:
                logger.warning(f"No GPM data found for {date.date()}")
                return None
            
            # Download granule
            temp_dir = output_path.parent / 'temp'
            downloaded = self.download_granule(granules[0], temp_dir)
            
            # Process NetCDF to GeoTIFF
            metadata = self.processor.process_gpm_netcdf(
                input_path=downloaded,
                bbox=bbox,
                output_path=output_path
            )
            
            # Cleanup
            if downloaded.exists():
                downloaded.unlink()
            if temp_dir.exists() and not list(temp_dir.iterdir()):
                temp_dir.rmdir
            if downloaded.exists():
                downloaded.unlink()
            
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to get GPM data: {e}")
            raise EarthDataError(f"GPM data fetch failed: {e}")
    
    def get_modis_data(
        self,
        product: str,
        variable: str,
        date: datetime,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Fetch MODIS Land Surface Temperature data.
        
        MODIS data comes in tiles using sinusoidal projection.
        Multiple tiles may be needed to cover the bbox.
        
        Args:
            product: Product name ('MOD11A1' for Terra, 'MYD11A1' for Aqua)
            variable: Variable name ('LST_Day_1km' or 'LST_Night_1km')
            date: Date to fetch
            bbox: Bounding box [min_lon, min_lat, max_lon, max_lat]
            output_path: Path to save GeoTIFF
            
        Returns:
            Dictionary with metadata
        """
        # Map product to collection ID
        collection_map = {
            'MOD11A1': self.COLLECTIONS['MODIS_LST_TERRA'],
            'MYD11A1': self.COLLECTIONS['MODIS_LST_AQUA'],
        }
        
        if product not in collection_map:
            raise ValueError(f"Unknown MODIS product: {product}")
        
        collection_id = collection_map[product]
        
        try:
            # Search for granules
            # MODIS tiles cover the bbox - may need multiple tiles
            granules = self.search_granules(
                collection_id=collection_id,
                bbox=bbox,
                start_date=date,
                end_date=date + timedelta(days=1),
                limit=10  # May need multiple tiles
            )
            
            if not granules:
                logger.warning(f"No MODIS data found for {date.date()}")
                return None
            
            logger.info(f"Found {len(granules)} MODIS tiles for {date.date()}")
            
            # Download all tiles
            temp_dir = output_path.parent / 'temp'
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            tile_paths = []
            for granule in granules:
                try:
                    downloaded = self.download_granule(granule, temp_dir)
                    tile_paths.append(downloaded)
                except Exception as e:
                    logger.warning(f"Failed to download MODIS tile: {e}")
                    continue
            
            if not tile_paths:
                raise EarthDataError("Failed to download any MODIS tiles")
            
            # Process tiles to GeoTIFF
            if len(tile_paths) == 1:
                # Single tile - direct processing
                metadata = self.processor.process_modis_hdf4(
                    input_path=tile_paths[0],
                    variable=variable,
                    bbox=bbox,
                    output_path=output_path
                )
            else:
                # Multiple tiles - mosaic them
                metadata = self.processor.mosaic_modis_tiles(
                    tile_paths=tile_paths,
                    variable=variable,
                    bbox=bbox,
                    output_path=output_path
                )
            
            # Cleanup temp files
            for tile_path in tile_paths:
                if tile_path.exists():
                    tile_path.unlink()
            if temp_dir.exists() and not list(temp_dir.iterdir()):
                temp_dir.rmdir()
            
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to get MODIS data: {e}")
            raise EarthDataError(f"MODIS data fetch failed: {e}")
    
    def _extract_gpm_to_geotiff(
        self,
        nc_path: Path,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Extract GPM precipitation from NetCDF and convert to GeoTIFF.
        
        Args:
            nc_path: Path to downloaded NetCDF file
            bbox: Bounding box for subsetting
            output_path: Output GeoTIFF path
            
        Returns:
            Metadata dictionary
        """
        try:
            # Open NetCDF with xarray
            ds = xr.open_dataset(nc_path)
            
            # GPM structure: precipitation[time, lat, lon]
            precip = ds['precipitation']
            
            # Subset to bounding box
            lon_slice = slice(bbox[0], bbox[2])
            lat_slice = slice(bbox[1], bbox[3])
            
            precip_subset = precip.sel(lon=lon_slice, lat=lat_slice)
            
            # Get first time step (daily data)
            if 'time' in precip_subset.dims:
                precip_subset = precip_subset.isel(time=0)
            
            # Calculate statistics
            data = precip_subset.values
            valid_data = data[~np.isnan(data)]
            
            stats = {
                'min': float(np.min(valid_data)) if len(valid_data) > 0 else None,
                'max': float(np.max(valid_data)) if len(valid_data) > 0 else None,
                'mean': float(np.mean(valid_data)) if len(valid_data) > 0 else None,
                'std': float(np.std(valid_data)) if len(valid_data) > 0 else None,
                'units': precip.attrs.get('units', 'mm/day'),
                'long_name': precip.attrs.get('long_name', 'precipitation'),
            }
            
            # TODO: Convert to GeoTIFF
            # GPM is already in WGS84, so this is straightforward
            
            logger.info(f"Extracted GPM precipitation: {stats}")
            
            ds.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to extract GPM data: {e}")
            raise EarthDataError(f"GPM extraction failed: {e}")
    
    def check_data_availability(
        self,
        collection_id: str,
        bbox: List[float],
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """
        Check if data is available for given parameters.
        
        Args:
            collection_id: Collection short name
            bbox: Bounding box
            start_date: Start date
            end_date: End date
            
        Returns:
            Dictionary with availability info: {available: bool, count: int, message: str}
        """
        if not self.authenticated:
            raise EarthDataAuthenticationError("Not authenticated")
        
        try:
            results = self.search_granules(
                collection_id=collection_id,
                bbox=bbox,
                start_date=start_date,
                end_date=end_date,
                limit=1
            )
            
            available = len(results) > 0
            
            return {
                'available': available,
                'count': len(results),
                'message': f"Found {len(results)} granules" if available else "No data available"
            }
            
        except Exception as e:
            return {
                'available': False,
                'count': 0,
                'message': f"Error checking availability: {e}"
            }
