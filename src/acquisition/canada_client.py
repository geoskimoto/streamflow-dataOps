"""Environment Canada data acquisition client."""

import requests
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional
import logging
import pytz
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class CanadaClient:
    """Client for retrieving Environment Canada streamflow data via MSC GeoMet API."""

    # Conversion factor from cubic meters per second to cubic feet per second
    CMS_TO_CFS = 35.3147

    def __init__(self):
        self.base_url = "https://api.weather.gc.ca"
        self.realtime_endpoint = f"{self.base_url}/collections/hydrometric-realtime/items"
        self.daily_endpoint = f"{self.base_url}/collections/hydrometric-daily-mean/items"
        self.stations_endpoint = f"{self.base_url}/collections/hydrometric-stations/items"
        self.logger = logging.getLogger(__name__)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def get_realtime_data(
        self,
        station_number: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Retrieve real-time discharge data from Environment Canada MSC GeoMet API.

        Args:
            station_number: EC station ID (e.g., '08MF005')
            start_date: Start date for data retrieval
            end_date: End date (defaults to now if None)

        Returns:
            List of dictionaries with discharge observations in CMS (with CFS conversion available)
        """
        if end_date is None:
            end_date = datetime.utcnow()

        try:
            # Build request parameters - keep it simple to avoid API 500 errors
            params = {
                "STATION_NUMBER": station_number,
                "f": "json",
                "limit": 10000,  # EC typically provides 5-15 minute intervals
            }

            self.logger.info(
                f"Fetching EC real-time data for {station_number} "
                f"from {start_date.date()} to {end_date.date()}"
            )

            response = requests.get(self.realtime_endpoint, params=params, timeout=60)
            response.raise_for_status()
            
            data = response.json()
            features = data.get("features", [])

            if not features:
                self.logger.warning(f"No real-time data returned for EC station {station_number}")
                return []

            # Transform to our format and filter by date range
            observations = []
            for feature in features:
                props = feature.get("properties", {})
                
                try:
                    # Parse datetime (already in UTC)
                    observed_at_str = props.get("DATETIME")
                    if not observed_at_str:
                        continue
                        
                    observed_at_utc = pd.to_datetime(observed_at_str).replace(tzinfo=pytz.UTC)
                    
                    # Filter by date range (since API doesn't always respect date filters)
                    if observed_at_utc < start_date.replace(tzinfo=pytz.UTC):
                        continue
                    if observed_at_utc > end_date.replace(tzinfo=pytz.UTC):
                        continue
                    
                    # Get discharge value (in cubic meters per second)
                    discharge_cms = props.get("DISCHARGE")
                    if discharge_cms is None:
                        continue
                    
                    discharge_cms = float(discharge_cms)
                    
                    # Store in CMS but provide CFS as derived attribute
                    obs = {
                        "observed_at": observed_at_utc,
                        "discharge": discharge_cms,
                        "discharge_cfs": discharge_cms * self.CMS_TO_CFS,  # Derived attribute
                        "unit": "cms",  # Primary unit is metric
                        "type": "realtime_15min",
                        "quality_code": props.get("DISCHARGE_SYMBOL_EN", "A"),
                    }

                    observations.append(obs)
                    
                except Exception as e:
                    self.logger.warning(f"Error parsing feature: {e}")
                    continue

            self.logger.info(f"Retrieved {len(observations)} EC real-time records")
            return observations

        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error fetching EC data for {station_number}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error fetching EC data for {station_number}: {e}")
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def get_daily_mean(
        self,
        station_number: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Retrieve daily mean discharge data from Environment Canada MSC GeoMet API.

        Args:
            station_number: EC station ID
            start_date: Start date for data retrieval
            end_date: End date (defaults to now if None)

        Returns:
            List of dictionaries with daily mean discharge observations in CMS (with CFS conversion)
        """
        if end_date is None:
            end_date = datetime.utcnow()

        try:
            # Build request parameters - simplified to avoid API 500 errors
            params = {
                "STATION_NUMBER": station_number,
                "f": "json",
                "limit": 10000,
            }

            self.logger.info(
                f"Fetching EC daily mean data for {station_number} "
                f"from {start_date.date()} to {end_date.date()}"
            )

            response = requests.get(self.daily_endpoint, params=params, timeout=60)
            response.raise_for_status()
            
            data = response.json()
            features = data.get("features", [])

            if not features:
                self.logger.warning(f"No daily mean data returned for EC station {station_number}")
                return []

            # Transform to our format and filter by date range
            observations = []
            for feature in features:
                props = feature.get("properties", {})
                
                try:
                    # Parse date
                    date_str = props.get("DATE")
                    if not date_str:
                        continue
                    
                    # Convert date to datetime at midnight UTC
                    observed_at_utc = datetime.strptime(date_str, "%Y-%m-%d").replace(
                        hour=0, minute=0, second=0, tzinfo=pytz.UTC
                    )
                    
                    # Filter by date range (since API doesn't always respect date filters)
                    if observed_at_utc.date() < start_date.date():
                        continue
                    if observed_at_utc.date() > end_date.date():
                        continue
                    
                    # Get discharge value (in cubic meters per second)
                    discharge_cms = props.get("DISCHARGE")
                    if discharge_cms is None:
                        continue
                    
                    discharge_cms = float(discharge_cms)
                    
                    # Store in CMS but provide CFS as derived attribute
                    obs = {
                        "observed_at": observed_at_utc,
                        "discharge": discharge_cms,
                        "discharge_cfs": discharge_cms * self.CMS_TO_CFS,  # Derived attribute
                        "unit": "cms",  # Primary unit is metric
                        "type": "daily_mean",
                        "quality_code": props.get("DISCHARGE_SYMBOL_EN", "A"),
                    }

                    observations.append(obs)
                    
                except Exception as e:
                    self.logger.warning(f"Error parsing feature: {e}")
                    continue

            self.logger.info(
                f"Retrieved {len(observations)} daily mean records from EC"
            )
            return observations

        except requests.exceptions.RequestException as e:
            self.logger.error(
                f"HTTP error fetching EC daily mean data for {station_number}: {e}"
            )
            raise
        except Exception as e:
            self.logger.error(
                f"Error fetching EC daily mean data for {station_number}: {e}"
            )
            raise

    def get_station_info(self, station_number: str) -> Optional[Dict]:
        """
        Get station metadata from Environment Canada MSC GeoMet API.

        Args:
            station_number: EC station ID (e.g., '08MF005')

        Returns:
            Dictionary with station metadata or None
        """
        try:
            params = {
                "STATION_NUMBER": station_number,
                "f": "json",
            }

            self.logger.info(f"Fetching station info for EC {station_number}")

            response = requests.get(self.stations_endpoint, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            features = data.get("features", [])

            if not features:
                self.logger.warning(f"No station info found for {station_number}")
                return None

            # Get first matching station
            feature = features[0]
            props = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            coords = geometry.get("coordinates", [None, None])

            return {
                "station_number": station_number,
                "name": props.get("STATION_NAME", ""),
                "longitude": coords[0],
                "latitude": coords[1],
                "state": props.get("PROV_TERR_STATE_LOC", ""),
                "drainage_area": props.get("DRAINAGE_AREA_GROSS"),
                "status": props.get("STATUS_EN", ""),
                "real_time": props.get("REAL_TIME", 0),
            }
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error fetching station info for {station_number}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching station info for {station_number}: {e}")
            return None

    def get_stations_by_province(self, province_code: str, limit: int = 5000) -> List[Dict]:
        """
        Get list of all stations for a given province/territory.

        Args:
            province_code: Province/territory code (e.g., 'BC', 'AB', 'ON')
            limit: Maximum number of stations to retrieve

        Returns:
            List of station metadata dictionaries
        """
        try:
            params = {
                "PROV_TERR_STATE_LOC": province_code,
                "f": "json",
                "limit": limit,
            }

            self.logger.info(f"Fetching all {province_code} stations from EC")

            response = requests.get(self.stations_endpoint, params=params, timeout=60)
            response.raise_for_status()
            
            data = response.json()
            features = data.get("features", [])

            stations = []
            for feature in features:
                props = feature.get("properties", {})
                geometry = feature.get("geometry", {})
                coords = geometry.get("coordinates", [None, None])

                station = {
                    "station_number": props.get("STATION_NUMBER"),
                    "name": props.get("STATION_NAME", ""),
                    "longitude": coords[0],
                    "latitude": coords[1],
                    "state": props.get("PROV_TERR_STATE_LOC", ""),
                    "drainage_area": props.get("DRAINAGE_AREA_GROSS"),
                    "status": props.get("STATUS_EN", ""),
                    "real_time": props.get("REAL_TIME", 0),
                }
                stations.append(station)

            self.logger.info(f"Retrieved {len(stations)} {province_code} stations from EC")
            return stations

        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error fetching {province_code} stations: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error fetching {province_code} stations: {e}")
            raise
