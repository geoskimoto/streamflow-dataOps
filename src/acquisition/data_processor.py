"""Data processor for validation and storage of acquired data."""

import os
import sys
import django

# Setup Django
if 'DJANGO_SETTINGS_MODULE' not in os.environ:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

from typing import List, Dict
from datetime import datetime
import logging
from django.db import transaction
from apps.streamflow.models import Station, DischargeObservation, ForecastRun, MasterStation

logger = logging.getLogger(__name__)

# Discharge values beyond this many standard deviations of the batch mean are
# logged for review but never dropped. Streamflow is heavy-tailed, so real
# flood peaks exceed any fixed z-score. A previous version dropped them, which
# removed flood peaks at 271 of 285 audited gages — see
# docs/superpowers/plans/2026-11-13-usgs-observation-ingest-remediation.md
OUTLIER_LOG_Z_SCORE = 5.0

# A *review* threshold, not a rejection threshold. Discharge above this is
# logged at WARNING and retained. The Columbia at The Dalles peaks near
# 1,240,000 cfs, so dropping on magnitude would silently discard real
# mainstem peaks — the same failure the z-score filter caused, and contrary
# to this project's "log data quality issues rather than silently dropping
# records" convention.
IMPLAUSIBLE_DISCHARGE_CFS = 1_000_000


class DataProcessor:
    """Process, validate, and store raw data before database insertion."""

    def __init__(self):
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

        # Get or create station from database
        try:
            station = Station.objects.get(station_number=station_number)
        except Station.DoesNotExist:
            # Auto-create Station from MasterStation catalog
            try:
                master = MasterStation.objects.get(station_number=station_number)
                station = Station.objects.create(
                    station_number=master.station_number,
                    name=master.station_name,
                    agency=master.agency,
                    latitude=master.latitude,
                    longitude=master.longitude,
                    huc_code=master.huc_code or "",
                    state=master.state_code or "",
                )
                self.logger.info(f"Auto-created Station record for {station_number} from MasterStation")
            except MasterStation.DoesNotExist:
                self.logger.error(
                    f"Station {station_number} not found in Station or MasterStation table"
                )
                return 0

        # Validate if requested
        if validate:
            observations = self.validate_observations(observations)

        # Add station to each observation, dropping any whose timestamp
        # cannot be parsed. Substituting datetime.utcnow() here (as an
        # earlier version did) fabricates a naive datetime at the current
        # time-of-day, which can never match an existing
        # (station, observed_at, type) key: a malformed date would create an
        # orphan row instead of correcting one, and would violate the
        # midnight-UTC invariant the upsert depends on. Same mistake the
        # project already warns about for forecast run_date.
        dated_observations = []
        for obs in observations:
            obs["station"] = station

            # Ensure observed_at is datetime
            if not isinstance(obs["observed_at"], datetime):
                try:
                    obs["observed_at"] = datetime.fromisoformat(str(obs["observed_at"]))
                except (ValueError, TypeError) as e:
                    self.logger.warning(
                        f"Skipping observation for station {station_number} "
                        f"with unparseable observed_at "
                        f"{obs['observed_at']!r}: {e}"
                    )
                    continue

            dated_observations.append(obs)

        observations = self._dedupe_by_key(station_number, dated_observations)

        # Bulk insert with duplicate handling using Django
        observation_objects = []
        for obs in observations:
            observation_objects.append(
                DischargeObservation(
                    station=obs["station"],
                    observed_at=obs["observed_at"],
                    discharge=obs["discharge"],
                    unit=obs["unit"],
                    type=obs["type"],
                    # `or ""` not a get() default: the legacy clients emit
                    # the key with an explicit None, and quality_code is a
                    # non-nullable CharField(blank=True).
                    quality_code=obs.get("quality_code") or "",
                )
            )

        # Upsert on unique_observation_idx (station, observed_at, type). USGS
        # revises provisional daily values for months, so a re-pulled day must
        # overwrite the stored value rather than be ignored.
        with transaction.atomic():
            written = DischargeObservation.objects.bulk_create(
                observation_objects,
                batch_size=5000,
                update_conflicts=True,
                update_fields=["discharge", "quality_code"],
                unique_fields=["station", "observed_at", "type"],
            )
            inserted_count = len(written)

        self.logger.info(
            f"Wrote {inserted_count} of {len(observations)} observations "
            f"for station {station_number}"
        )
        return inserted_count

    def _dedupe_by_key(
        self, station_number: str, observations: List[Dict]
    ) -> List[Dict]:
        """Collapse observations sharing an ``(observed_at, type)`` key.

        The whole batch goes to one ``bulk_create(update_conflicts=True)``.
        PostgreSQL raises "ON CONFLICT DO UPDATE command cannot affect row a
        second time" on an intra-batch duplicate key, which fails inside
        ``transaction.atomic()`` and loses the *entire* station's batch.
        Under the old ``ignore_conflicts`` a duplicate was simply absorbed,
        so this is the choke point that has to guarantee uniqueness: the
        Water Data client dedupes its own output, but EC's paginated fetch
        and ``USGSClient.get_instantaneous`` do not.

        The last occurrence per key wins (sources list pages oldest-first,
        so a later page carries the fresher value), and any collapse is
        logged at WARNING — a duplicate key from an upstream is a data
        quality issue, not routine.
        """
        deduped: Dict = {}
        for obs in observations:
            deduped[(obs["observed_at"], obs["type"])] = obs

        collapsed = len(observations) - len(deduped)
        if collapsed:
            self.logger.warning(
                "Collapsed %d duplicate (observed_at, type) observation(s) "
                "for station %s; kept the last occurrence of each. An "
                "intra-batch duplicate key would otherwise abort this "
                "station's entire upsert.",
                collapsed,
                station_number,
            )

        return list(deduped.values())

    def validate_observations(self, observations: List[Dict]) -> List[Dict]:
        """
        Validate observation data quality.

        Checks (rejection):
        - Required fields present
        - Non-negative, parseable discharge values
        - Valid timestamps

        Logged and RETAINED, never dropped:
        - Statistical outliers (>5 std deviations of the batch mean) — real
          flood peaks routinely exceed any fixed z-score
        - Implausibly high magnitudes (> IMPLAUSIBLE_DISCHARGE_CFS)

        Args:
            observations: List of observation dictionaries

        Returns:
            Filtered list of valid observations
        """
        valid_observations = []
        
        # First pass: basic validation
        basic_valid = []
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

            # Flag implausibly high values for review, but keep them. Real
            # mainstem peaks exceed 1,000,000 cfs (Columbia at The Dalles
            # ~1,240,000); dropping them here would re-create the bug the
            # z-score fix just removed.
            if discharge > IMPLAUSIBLE_DISCHARGE_CFS:
                self.logger.warning(
                    "Implausibly high discharge retained for review: "
                    "discharge=%s observed_at=%s (review threshold %s cfs)",
                    discharge,
                    obs.get("observed_at"),
                    IMPLAUSIBLE_DISCHARGE_CFS,
                )

            # Validate timestamp
            try:
                if isinstance(obs["observed_at"], str):
                    datetime.fromisoformat(obs["observed_at"])
            except ValueError:
                self.logger.warning(f"Invalid timestamp: {obs['observed_at']}")
                continue

            basic_valid.append(obs)
        
        # Second pass: flag statistical outliers for review. Never drop them.
        valid_observations = basic_valid

        if len(valid_observations) > 3:
            discharges = [float(obs["discharge"]) for obs in valid_observations]
            mean = sum(discharges) / len(discharges)
            variance = sum((x - mean) ** 2 for x in discharges) / len(discharges)
            std_dev = variance ** 0.5

            if std_dev > 0:
                for obs in valid_observations:
                    z_score = abs((float(obs["discharge"]) - mean) / std_dev)
                    if z_score > OUTLIER_LOG_Z_SCORE:
                        self.logger.info(
                            "High-z discharge retained: discharge=%s z_score=%.2f "
                            "observed_at=%s",
                            obs["discharge"],
                            z_score,
                            obs["observed_at"],
                        )

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
