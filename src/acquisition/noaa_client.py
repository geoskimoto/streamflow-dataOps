"""NOAA National Water Model forecast data acquisition client."""

import requests
from datetime import datetime
from typing import List, Dict, Optional
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class NOAAClient:
    """Client for retrieving NOAA National Water Model forecast data."""

    def __init__(self):
        self.base_url = "https://api.water.noaa.gov/nwps/v1"
        self.logger = logging.getLogger(__name__)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def get_forecast(
        self, hads_id: str, forecast_type: str = "short"
    ) -> Optional[Dict]:
        """
        Retrieve forecast data from NOAA NWM.

        Args:
            hads_id: NOAA HADS station ID (NOT USGS ID - must be translated first via StationMapping)
            forecast_type: 'short' (18hr), 'medium' (10day), or 'long' (30day)

        Returns:
            Dictionary with forecast data or None if not available
        """
        try:
            endpoint = f"{self.base_url}/gauges/{hads_id}/stageflow"

            params = {"forecast": forecast_type}

            self.logger.info(
                f"Fetching NOAA {forecast_type} forecast for HADS ID {hads_id}"
            )

            response = requests.get(endpoint, params=params, timeout=60)
            response.raise_for_status()

            data = response.json()

            if not data:
                self.logger.warning(f"No forecast data for HADS ID {hads_id}")
                return None

            # Extract forecast time series
            forecast_data = []
            if "forecast" in data and "data" in data["forecast"]:
                for point in data["forecast"]["data"]:
                    forecast_data.append(
                        {
                            "date": point.get("validTime", ""),
                            "value": point.get("flow", 0),  # Discharge value
                        }
                    )

            result = {
                "source": "NOAA_NWM",
                "run_date": datetime.utcnow(),
                "data": forecast_data,
                "rmse": data.get("forecast", {}).get("rmse", None),
            }

            self.logger.info(f"Retrieved forecast with {len(forecast_data)} points")
            return result

        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error fetching NOAA forecast for {hads_id}: {e}")
            # Don't raise - forecasts may not be available for all stations
            return None
        except Exception as e:
            self.logger.error(f"Error fetching NOAA forecast for {hads_id}: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def get_observed_data(
        self, hads_id: str, start_date: datetime, end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Retrieve observed discharge data from NOAA.

        Note: NOAA primarily provides forecast data. For observed data,
        prefer using USGS client with the original USGS station ID.

        Args:
            hads_id: NOAA HADS station ID
            start_date: Start date for data retrieval
            end_date: End date (defaults to now if None)

        Returns:
            List of dictionaries with discharge observations
        """
        if end_date is None:
            end_date = datetime.utcnow()

        try:
            endpoint = f"{self.base_url}/gauges/{hads_id}/stageflow"

            params = {
                "startDate": start_date.strftime("%Y-%m-%dT%H:%M:%S"),
                "endDate": end_date.strftime("%Y-%m-%dT%H:%M:%S"),
            }

            self.logger.info(
                f"Fetching NOAA observed data for HADS ID {hads_id} "
                f"from {start_date.date()} to {end_date.date()}"
            )

            response = requests.get(endpoint, params=params, timeout=60)
            response.raise_for_status()

            data = response.json()

            if not data or "observed" not in data:
                self.logger.warning(f"No observed data for HADS ID {hads_id}")
                return []

            # Parse observed data
            observations = []
            for point in data["observed"].get("data", []):
                obs = {
                    "observed_at": datetime.fromisoformat(point.get("validTime", "")),
                    "discharge": float(point.get("flow", 0)),
                    "unit": "cfs",  # NOAA typically uses cfs
                    "type": "realtime_15min",
                    "quality_code": point.get("qualityCode", None),
                }

                if obs["discharge"] is not None and obs["discharge"] >= 0:
                    observations.append(obs)

            self.logger.info(f"Retrieved {len(observations)} NOAA observed records")
            return observations

        except requests.exceptions.RequestException as e:
            self.logger.error(
                f"HTTP error fetching NOAA observed data for {hads_id}: {e}"
            )
            return []
        except Exception as e:
            self.logger.error(f"Error fetching NOAA observed data for {hads_id}: {e}")
            return []

    def translate_usgs_to_hads(self, usgs_id: str) -> Optional[str]:
        """
        Helper method to remind developers to use StationMapping table.

        Args:
            usgs_id: USGS station ID

        Returns:
            None - actual implementation should query StationMapping table
        """
        self.logger.warning(
            f"USGS ID {usgs_id} needs to be translated to HADS ID using StationMapping table. "
            "Use StationMappingRepository.get_mapping('USGS', usgs_id, 'NOAA-HADS')"
        )
        return None
