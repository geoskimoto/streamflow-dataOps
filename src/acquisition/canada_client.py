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

    # Map EC DISCHARGE_SYMBOL_EN values to short codes that fit the DB
    # quality_code field (max_length=10).
    _EC_QUALITY_MAP = {
        "Partial Day": "P",
        "Estimated": "E",
        "Ice Conditions": "I",
        "Dry": "D",
        "Revised": "R",
    }

    def __init__(self):
        self.base_url = "https://api.weather.gc.ca"
        self.realtime_endpoint = f"{self.base_url}/collections/hydrometric-realtime/items"
        self.daily_endpoint = f"{self.base_url}/collections/hydrometric-daily-mean/items"
        self.stations_endpoint = f"{self.base_url}/collections/hydrometric-stations/items"
        self.logger = logging.getLogger(__name__)

    def _map_quality_code(self, symbol_en: Optional[str]) -> str:
        """Map an EC DISCHARGE_SYMBOL_EN value to a short code."""
        if not symbol_en:
            return "A"
        return self._EC_QUALITY_MAP.get(symbol_en, symbol_en[:10])

    # Maximum records per API request (EC GeoMet hard limit)
    PAGE_SIZE = 10000

    def _paginated_fetch(self, endpoint: str, params: dict, timeout: int = 60) -> List[dict]:
        """Fetch all pages of results from an EC GeoMet API endpoint.

        The API returns at most ``limit`` features per request.  When
        ``numberMatched`` exceeds the page size we issue follow-up requests
        with increasing ``offset`` until all records have been retrieved.

        Note: The EC GeoMet API reports unreliable ``numberMatched`` values
        at offsets > 0, so we capture the total from the first request only.

        Args:
            endpoint: Full URL of the API endpoint.
            params: Query parameters (must already include ``limit``).
            timeout: HTTP timeout per request in seconds.

        Returns:
            Aggregated list of GeoJSON feature dicts.
        """
        all_features: List[dict] = []
        offset = 0
        page_limit = int(params.get("limit", self.PAGE_SIZE))
        total = None  # Will be set from the first request's numberMatched

        while True:
            params["offset"] = offset
            response = requests.get(endpoint, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()

            features = data.get("features", [])
            all_features.extend(features)

            number_returned = data.get("numberReturned", len(features))

            # Only trust numberMatched from the first request
            if total is None:
                total = data.get("numberMatched", 0)

            self.logger.debug(
                f"Page offset={offset}: returned={number_returned}, "
                f"total={total}, accumulated={len(all_features)}"
            )

            # Stop when we've collected everything or the page was empty
            if not features or len(all_features) >= total:
                break

            offset += number_returned

        return all_features

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
            # Ensure timezone-aware dates for comparison
            start_tz = start_date if start_date.tzinfo else start_date.replace(tzinfo=pytz.UTC)
            end_tz = end_date if end_date.tzinfo else end_date.replace(tzinfo=pytz.UTC)

            # Build the OGC datetime range filter for server-side filtering
            dt_start = start_tz.strftime("%Y-%m-%dT%H:%M:%SZ")
            dt_end = end_tz.strftime("%Y-%m-%dT%H:%M:%SZ")

            params = {
                "STATION_NUMBER": station_number,
                "f": "json",
                "limit": self.PAGE_SIZE,
                "datetime": f"{dt_start}/{dt_end}",
            }

            self.logger.info(
                f"Fetching EC real-time data for {station_number} "
                f"from {start_date.date()} to {end_date.date()}"
            )

            features = self._paginated_fetch(self.realtime_endpoint, params)

            if not features:
                self.logger.warning(f"No real-time data returned for EC station {station_number}")
                return []

            # Transform to our format
            observations = []
            for feature in features:
                props = feature.get("properties", {})

                try:
                    # Parse datetime (already in UTC)
                    observed_at_str = props.get("DATETIME")
                    if not observed_at_str:
                        continue

                    observed_at_utc = pd.to_datetime(observed_at_str).replace(tzinfo=pytz.UTC)

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
                        "quality_code": self._map_quality_code(props.get("DISCHARGE_SYMBOL_EN")),
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
            # Ensure timezone-aware dates for comparison
            start_tz = start_date if start_date.tzinfo else start_date.replace(tzinfo=pytz.UTC)
            end_tz = end_date if end_date.tzinfo else end_date.replace(tzinfo=pytz.UTC)

            # Build the OGC datetime range filter for server-side filtering
            dt_start = start_tz.strftime("%Y-%m-%d")
            dt_end = end_tz.strftime("%Y-%m-%d")

            params = {
                "STATION_NUMBER": station_number,
                "f": "json",
                "limit": self.PAGE_SIZE,
                "datetime": f"{dt_start}/{dt_end}",
            }

            self.logger.info(
                f"Fetching EC daily mean data for {station_number} "
                f"from {start_date.date()} to {end_date.date()}"
            )

            features = self._paginated_fetch(self.daily_endpoint, params)

            if not features:
                self.logger.warning(f"No daily mean data returned for EC station {station_number}")
                return []

            # Transform to our format
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
                        "quality_code": self._map_quality_code(props.get("DISCHARGE_SYMBOL_EN")),
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
