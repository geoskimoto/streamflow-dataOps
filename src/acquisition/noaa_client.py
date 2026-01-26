"""NOAA River Forecast Center (RFC) data acquisition client."""

import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class NOAAClient:
    """Client for retrieving NOAA River Forecast Center data."""

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

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def get_gauges_by_states(self, states: List[str], limit: int = 10000) -> List[Dict]:
        """
        Retrieve all gauges for specified states.

        Args:
            states: List of state abbreviations (e.g., ['CA', 'OR', 'WA'])
            limit: Maximum number of results to return

        Returns:
            List of gauge dictionaries with metadata
        """
        all_gauges = []
        
        # Query each state separately to avoid API timeout
        for state in states:
            try:
                endpoint = f"{self.base_url}/gauges"
                params = {"state": state, "limit": limit}
                
                self.logger.info(f"Fetching gauges for state: {state}")
                
                response = requests.get(endpoint, params=params, timeout=90)
                response.raise_for_status()
                
                data = response.json()
                gauges = data.get("gauges", [])
                
                self.logger.info(f"Retrieved {len(gauges)} gauges for {state}")
                all_gauges.extend(gauges)
                
            except requests.exceptions.RequestException as e:
                self.logger.error(f"HTTP error fetching gauges for {state}: {e}")
                continue
            except Exception as e:
                self.logger.error(f"Error fetching gauges for {state}: {e}")
                continue
        
        self.logger.info(f"Total gauges retrieved: {len(all_gauges)}")
        return all_gauges

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def get_gauges_by_rfc(self, rfc_code: str, limit: int = 10000) -> List[Dict]:
        """
        Retrieve all gauges for a specific River Forecast Center.

        Args:
            rfc_code: RFC abbreviation (e.g., 'NWRFC', 'CNRFC')
            limit: Maximum number of results to return

        Returns:
            List of gauge dictionaries with metadata
        """
        try:
            endpoint = f"{self.base_url}/gauges"
            params = {"rfc": rfc_code, "limit": limit}
            
            self.logger.info(f"Fetching gauges for RFC: {rfc_code}")
            
            response = requests.get(endpoint, params=params, timeout=120)
            response.raise_for_status()
            
            data = response.json()
            gauges = data.get("gauges", [])
            
            self.logger.info(f"Retrieved {len(gauges)} gauges for {rfc_code}")
            return gauges
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error fetching gauges for RFC {rfc_code}: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error fetching gauges for RFC {rfc_code}: {e}")
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True,
    )
    def get_rfc_forecast(self, lid: str) -> Optional[Dict]:
        """
        Retrieve forecast data from NOAA River Forecast Center for a gauge.

        Args:
            lid: NOAA Location ID (e.g., 'AAMC1')

        Returns:
            Dictionary with forecast run data:
            {
                'run_date': datetime,
                'forecast_data': [{'date': str, 'value': float}, ...],
                'rmse': float or None
            }
            Returns None if no forecast available
        """
        try:
            endpoint = f"{self.base_url}/gauges/{lid}/stageflow"
            
            self.logger.info(f"Fetching RFC forecast for LID: {lid}")
            
            response = requests.get(endpoint, timeout=60)
            response.raise_for_status()
            
            data = response.json()
            
            if not data:
                self.logger.warning(f"No data returned for LID {lid}")
                return None
            
            # Check if forecast data exists
            forecast = data.get("forecast", {})
            if not forecast or forecast.get("floodCategory") == "fcst_not_current":
                self.logger.info(f"No current forecast available for {lid}")
                return None
            
            # Get the issue time (run_date)
            issue_time = forecast.get("issueTime")
            if issue_time:
                try:
                    run_date = datetime.fromisoformat(issue_time.replace('Z', '+00:00'))
                except:
                    run_date = datetime.now(timezone.utc)
            else:
                run_date = datetime.now(timezone.utc)
            
            # Extract forecast time series
            forecast_data = []
            forecast_values = forecast.get("data", [])
            
            for point in forecast_values:
                valid_time = point.get("validTime")
                # Get flow value - convert from kcfs to cfs
                flow_kcfs = point.get("secondary")  # secondary is typically flow
                
                if valid_time and flow_kcfs is not None and flow_kcfs > -999:
                    # Convert kcfs (thousands of cfs) to cfs
                    flow_cfs = flow_kcfs * 1000
                    
                    forecast_data.append({
                        "date": valid_time,
                        "value": flow_cfs
                    })
            
            if not forecast_data:
                self.logger.warning(f"Forecast exists but no valid data points for {lid}")
                return None
            
            result = {
                "run_date": run_date,
                "forecast_data": forecast_data,
                "rmse": forecast.get("rmse")
            }
            
            self.logger.info(f"Retrieved forecast with {len(forecast_data)} points for {lid}")
            return result
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP error fetching forecast for {lid}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching forecast for {lid}: {e}")
            return None
