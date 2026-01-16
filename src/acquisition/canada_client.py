"""Environment Canada data acquisition client."""

import requests
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional
import logging
import pytz
from io import StringIO
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class CanadaClient:
    """Client for retrieving Environment Canada streamflow data."""

    def __init__(self):
        self.base_url = (
            "https://wateroffice.ec.gc.ca/services/real_time_data/csv/inline"
        )
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
        Retrieve real-time discharge data from Environment Canada.

        Args:
            station_number: EC station ID (e.g., '01AP004')
            start_date: Start date for data retrieval
            end_date: End date (defaults to now if None)

        Returns:
            List of dictionaries with discharge observations
        """
        if end_date is None:
            end_date = datetime.utcnow()

        try:
            # Build request URL
            params = {
                "stations[]": station_number,
                "parameters[]": "47",  # Discharge parameter code
                "start_date": start_date.strftime("%Y-%m-%d"),
                "end_date": end_date.strftime("%Y-%m-%d"),
            }

            self.logger.info(
                f"Fetching EC real-time data for {station_number} "
                f"from {start_date.date()} to {end_date.date()}"
            )

            response = requests.get(self.base_url, params=params, timeout=60)
            response.raise_for_status()

            # Parse CSV response
            df = pd.read_csv(StringIO(response.text))

            if df.empty:
                self.logger.warning(f"No data returned for EC station {station_number}")
                return []

            # Transform to our format
            observations = []
            for _, row in df.iterrows():
                # Convert from LST to UTC
                # EC data is in Local Standard Time
                # Note: This is simplified - actual timezone would depend on station location
                try:
                    local_tz = pytz.timezone("America/Toronto")
                    observed_at_local = pd.to_datetime(row["Date"])

                    # Localize to local timezone then convert to UTC
                    if observed_at_local.tzinfo is None:
                        observed_at_utc = local_tz.localize(
                            observed_at_local
                        ).astimezone(pytz.UTC)
                    else:
                        observed_at_utc = observed_at_local.astimezone(pytz.UTC)

                    obs = {
                        "observed_at": observed_at_utc,
                        "discharge": (
                            float(row["Value"]) if pd.notna(row["Value"]) else None
                        ),
                        "unit": "cms",  # EC uses cubic meters per second
                        "type": "realtime_15min",
                        "quality_code": row.get("Quality", None),
                    }

                    if obs["discharge"] is not None:
                        observations.append(obs)
                except Exception as e:
                    self.logger.warning(f"Error parsing row: {e}")
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
        Retrieve daily mean discharge data from Environment Canada.

        Note: EC's API primarily provides real-time data. Daily means may need
        to be calculated from hourly/15-minute data or fetched from archived data.

        Args:
            station_number: EC station ID
            start_date: Start date for data retrieval
            end_date: End date (defaults to now if None)

        Returns:
            List of dictionaries with discharge observations
        """
        if end_date is None:
            end_date = datetime.utcnow()

        try:
            self.logger.info(
                f"Fetching EC daily mean data for {station_number} "
                f"(using real-time endpoint with aggregation)"
            )

            # Get real-time data
            realtime_data = self.get_realtime_data(station_number, start_date, end_date)

            if not realtime_data:
                return []

            # Convert to DataFrame for aggregation
            df = pd.DataFrame(realtime_data)
            df["observed_at"] = pd.to_datetime(df["observed_at"])
            df["date"] = df["observed_at"].dt.date

            # Calculate daily mean
            daily_means = df.groupby("date")["discharge"].mean().reset_index()

            observations = []
            for _, row in daily_means.iterrows():
                obs = {
                    "observed_at": datetime.combine(
                        row["date"], datetime.min.time()
                    ).replace(tzinfo=pytz.UTC),
                    "discharge": float(row["discharge"]),
                    "unit": "cms",
                    "type": "daily_mean",
                    "quality_code": "A",  # Aggregated
                }
                observations.append(obs)

            self.logger.info(
                f"Calculated {len(observations)} daily mean records from EC data"
            )
            return observations

        except Exception as e:
            self.logger.error(
                f"Error fetching EC daily mean data for {station_number}: {e}"
            )
            raise
