"""Data processor for validation and storage of acquired data."""

from typing import List, Dict
from datetime import datetime
import logging
from sqlalchemy.orm import Session
from src.database.repositories import StationRepository, DischargeObservationRepository
from src.database.models import ForecastRun

logger = logging.getLogger(__name__)


class DataProcessor:
    """Process, validate, and store raw data before database insertion."""

    def __init__(self, db: Session):
        self.db = db
        self.station_repo = StationRepository(db)
        self.obs_repo = DischargeObservationRepository(db)
        self.logger = logging.getLogger(__name__)

    def process_observations(
        self, station_number: str, observations: List[Dict], validate: bool = True
    ) -> int:
        """
        Process and store discharge observations.

        Args:
            station_number: Station identifier
            observations: List of observation dictionaries
            validate: Whether to validate data before insertion

        Returns:
            Count of successfully inserted records
        """
        if not observations:
            self.logger.info(f"No observations to process for station {station_number}")
            return 0

        # Get station from database
        station = self.station_repo.get_by_station_number(station_number)
        if not station:
            self.logger.error(f"Station {station_number} not found in database")
            return 0

        # Validate if requested
        if validate:
            observations = self.validate_observations(observations)

        # Add station_id to each observation
        for obs in observations:
            obs["station_id"] = station.id

            # Ensure observed_at is datetime
            if not isinstance(obs["observed_at"], datetime):
                try:
                    obs["observed_at"] = datetime.fromisoformat(str(obs["observed_at"]))
                except (ValueError, TypeError) as e:
                    self.logger.warning(
                        f"Invalid date format: {obs['observed_at']}, error: {e}"
                    )
                    obs["observed_at"] = datetime.utcnow()

        # Bulk insert with duplicate handling
        inserted_count = self.obs_repo.bulk_create(observations)

        self.logger.info(
            f"Inserted {inserted_count} of {len(observations)} observations "
            f"for station {station_number}"
        )
        return inserted_count

    def validate_observations(self, observations: List[Dict]) -> List[Dict]:
        """
        Validate observation data quality.

        Checks:
        - Required fields present
        - Non-negative discharge values
        - Reasonable ranges (< 1,000,000 cfs for safety)
        - Valid timestamps

        Args:
            observations: List of observation dictionaries

        Returns:
            Filtered list of valid observations
        """
        valid_observations = []

        for obs in observations:
            # Check required fields
            if not all(k in obs for k in ["observed_at", "discharge", "unit", "type"]):
                self.logger.warning(f"Missing required fields in observation: {obs}")
                continue

            # Check discharge value
            if obs["discharge"] is None:
                continue

            try:
                discharge = float(obs["discharge"])
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid discharge value: {obs['discharge']}")
                continue

            if discharge < 0:
                self.logger.warning(f"Negative discharge value: {discharge}")
                continue

            # Check for unreasonably high values (likely data errors)
            if discharge > 1_000_000:  # 1 million cfs
                self.logger.warning(f"Unreasonably high discharge value: {discharge}")
                continue

            # Validate timestamp
            try:
                if isinstance(obs["observed_at"], str):
                    datetime.fromisoformat(obs["observed_at"])
            except ValueError:
                self.logger.warning(f"Invalid timestamp: {obs['observed_at']}")
                continue

            valid_observations.append(obs)

        removed_count = len(observations) - len(valid_observations)
        if removed_count > 0:
            self.logger.info(
                f"Removed {removed_count} invalid observations during validation"
            )

        return valid_observations

    def process_forecast(self, station_number: str, forecast_data: Dict) -> bool:
        """
        Process and store forecast data.

        Args:
            station_number: Station identifier
            forecast_data: Dictionary with forecast information

        Returns:
            True if successfully stored, False otherwise
        """
        if not forecast_data or not forecast_data.get("data"):
            self.logger.info(
                f"No forecast data to process for station {station_number}"
            )
            return False

        # Get station from database
        station = self.station_repo.get_by_station_number(station_number)
        if not station:
            self.logger.error(f"Station {station_number} not found in database")
            return False

        try:
            # Create forecast run entry
            forecast_run = ForecastRun(
                station_id=station.id,
                source=forecast_data.get("source", "UNKNOWN"),
                run_date=forecast_data.get("run_date", datetime.utcnow()),
                data=forecast_data.get("data", []),
                rmse=forecast_data.get("rmse"),
            )

            self.db.add(forecast_run)
            self.db.commit()

            self.logger.info(
                f"Stored forecast run for station {station_number} "
                f"with {len(forecast_data.get('data', []))} data points"
            )
            return True

        except Exception as e:
            self.logger.error(f"Error storing forecast data: {e}")
            self.db.rollback()
            return False

    def get_data_quality_summary(self, observations: List[Dict]) -> Dict:
        """
        Generate a quality summary of observation data.

        Args:
            observations: List of observation dictionaries

        Returns:
            Dictionary with quality statistics
        """
        if not observations:
            return {
                "total_records": 0,
                "valid_records": 0,
                "null_values": 0,
                "negative_values": 0,
                "min_discharge": None,
                "max_discharge": None,
                "mean_discharge": None,
            }

        total = len(observations)
        valid = len(self.validate_observations(observations.copy()))
        null_count = sum(1 for obs in observations if obs.get("discharge") is None)
        negative_count = sum(
            1
            for obs in observations
            if obs.get("discharge") is not None and obs["discharge"] < 0
        )

        valid_discharges = [
            obs["discharge"]
            for obs in observations
            if obs.get("discharge") is not None and obs["discharge"] >= 0
        ]

        return {
            "total_records": total,
            "valid_records": valid,
            "null_values": null_count,
            "negative_values": negative_count,
            "min_discharge": min(valid_discharges) if valid_discharges else None,
            "max_discharge": max(valid_discharges) if valid_discharges else None,
            "mean_discharge": (
                sum(valid_discharges) / len(valid_discharges)
                if valid_discharges
                else None
            ),
        }
