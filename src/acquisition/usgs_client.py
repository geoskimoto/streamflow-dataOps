"""USGS data acquisition client."""
import dataretrieval.nwis as nwis
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class USGSClient:
    """Client for retrieving USGS streamflow data using dataretrieval library."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True
    )
    def get_daily_mean(self, 
                       station_number: str, 
                       start_date: datetime, 
                       end_date: Optional[datetime] = None) -> List[Dict]:
        """
        Retrieve daily mean discharge data from USGS.
        
        Args:
            station_number: USGS station ID (e.g., '01010000')
            start_date: Start date for data retrieval
            end_date: End date (defaults to today if None)
        
        Returns:
            List of dictionaries with discharge observations
        """
        if end_date is None:
            end_date = datetime.utcnow()
        
        try:
            self.logger.info(
                f"Fetching USGS daily mean data for {station_number} "
                f"from {start_date.date()} to {end_date.date()}"
            )
            
            # Use dataRetrieval library for USGS data
            df, metadata = nwis.get_dv(
                sites=station_number,
                parameterCd='00060',  # Discharge parameter code
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d')
            )
            
            if df.empty:
                self.logger.warning(f"No data returned for {station_number}")
                return []
            
            # Transform to our format
            observations = []
            for index, row in df.iterrows():
                # Get the discharge value column (usually ends with '_00060_00003')
                discharge_cols = [col for col in df.columns if '_00060_00003' in col and not col.endswith('_cd')]
                quality_cols = [col for col in df.columns if '_00060_00003_cd' in col]
                
                if not discharge_cols:
                    continue
                
                discharge_col = discharge_cols[0]
                quality_col = quality_cols[0] if quality_cols else None
                
                obs = {
                    'observed_at': index,
                    'discharge': float(row[discharge_col]) if pd.notna(row[discharge_col]) else None,
                    'unit': 'cfs',  # USGS default unit
                    'type': 'daily_mean',
                    'quality_code': row[quality_col] if quality_col and pd.notna(row[quality_col]) else None
                }
                
                if obs['discharge'] is not None:
                    observations.append(obs)
            
            self.logger.info(f"Retrieved {len(observations)} daily mean records for {station_number}")
            return observations
            
        except Exception as e:
            self.logger.error(f"Error fetching USGS daily mean data for {station_number}: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True
    )
    def get_instantaneous(self,
                          station_number: str,
                          start_date: datetime,
                          end_date: Optional[datetime] = None) -> List[Dict]:
        """
        Retrieve instantaneous (real-time) discharge data from USGS.
        
        Args:
            station_number: USGS station ID
            start_date: Start date for data retrieval
            end_date: End date (defaults to now if None)
        
        Returns:
            List of dictionaries with discharge observations
        """
        if end_date is None:
            end_date = datetime.utcnow()
        
        try:
            self.logger.info(
                f"Fetching USGS instantaneous data for {station_number} "
                f"from {start_date} to {end_date}"
            )
            
            df, metadata = nwis.get_iv(
                sites=station_number,
                parameterCd='00060',
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d')
            )
            
            if df.empty:
                self.logger.warning(f"No instantaneous data for {station_number}")
                return []
            
            observations = []
            for index, row in df.iterrows():
                # Find discharge column
                discharge_cols = [col for col in df.columns if '_00060' in col and not col.endswith('_cd')]
                quality_cols = [col for col in df.columns if '_00060' in col and col.endswith('_cd')]
                
                if not discharge_cols:
                    continue
                
                discharge_col = discharge_cols[0]
                quality_col = quality_cols[0] if quality_cols else None
                
                obs = {
                    'observed_at': index,
                    'discharge': float(row[discharge_col]) if pd.notna(row[discharge_col]) else None,
                    'unit': 'cfs',
                    'type': 'realtime_15min',
                    'quality_code': row[quality_col] if quality_col and pd.notna(row[quality_col]) else None
                }
                
                if obs['discharge'] is not None:
                    observations.append(obs)
            
            self.logger.info(f"Retrieved {len(observations)} instantaneous records for {station_number}")
            return observations
            
        except Exception as e:
            self.logger.error(f"Error fetching instantaneous USGS data for {station_number}: {e}")
            raise
    
    def get_station_info(self, station_number: str) -> Optional[Dict]:
        """
        Get station metadata from USGS.
        
        Args:
            station_number: USGS station ID
        
        Returns:
            Dictionary with station metadata or None
        """
        try:
            info, _ = nwis.get_info(sites=station_number)
            
            if info.empty:
                return None
            
            row = info.iloc[0]
            return {
                'station_number': station_number,
                'name': row.get('station_nm', ''),
                'latitude': float(row.get('dec_lat_va', 0)),
                'longitude': float(row.get('dec_long_va', 0)),
                'state': row.get('state_cd', ''),
                'huc_code': row.get('huc_cd', ''),
                'drainage_area': float(row.get('drain_area_va', 0)) if pd.notna(row.get('drain_area_va')) else None
            }
        except Exception as e:
            self.logger.error(f"Error fetching station info for {station_number}: {e}")
            return None
