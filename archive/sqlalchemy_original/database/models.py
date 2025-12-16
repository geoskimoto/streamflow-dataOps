"""SQLAlchemy models for the streamflow database."""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    Numeric,
    ForeignKey,
    UniqueConstraint,
    Index,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.database.connection import Base


class Station(Base):
    """Stores station metadata."""

    __tablename__ = "stations"

    id = Column(Integer, primary_key=True, index=True)
    station_number = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(Text, nullable=False)
    agency = Column(String(50), nullable=False)  # 'USGS', 'EC'

    # Geographic Information
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    timezone = Column(String(50), default="UTC")

    # Hydrological Attributes
    huc_code = Column(String(20), index=True)
    basin = Column(String(100))
    state = Column(String(50), index=True)
    catchment_area = Column(Numeric)  # sq km

    # Record Statistics
    years_of_record = Column(Numeric)
    record_start_date = Column(DateTime(timezone=True))
    record_end_date = Column(DateTime(timezone=True))

    # Status
    is_active = Column(Boolean, default=True)
    last_updated = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    discharge_observations = relationship(
        "DischargeObservation", back_populates="station"
    )
    forecast_runs = relationship("ForecastRun", back_populates="station")


class DischargeObservation(Base):
    """Stores time series discharge observations."""

    __tablename__ = "discharge_observations"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    observed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    discharge = Column(Numeric, nullable=False)
    unit = Column(String(10), nullable=False)  # 'cfs', 'cms'
    type = Column(String(20), nullable=False)  # 'realtime_15min', 'daily_mean'
    quality_code = Column(String(10))  # 'P' (Provisional), 'A' (Approved)

    # Relationships
    station = relationship("Station", back_populates="discharge_observations")

    # Unique constraint to prevent duplicates
    __table_args__ = (
        UniqueConstraint(
            "station_id", "observed_at", "type", name="unique_observation_idx"
        ),
        Index("idx_station_observed_type", "station_id", "observed_at", "type"),
    )


class ForecastRun(Base):
    """Stores forecast data."""

    __tablename__ = "forecast_runs"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    source = Column(String(50), nullable=False)  # 'NOAA_RFC'
    run_date = Column(DateTime(timezone=True), nullable=False, index=True)
    data = Column(JSON, nullable=False)  # Array of { date: string, value: number }
    rmse = Column(Numeric)  # Accuracy metric

    # Relationships
    station = relationship("Station", back_populates="forecast_runs")

    __table_args__ = (Index("idx_station_run_date", "station_id", "run_date"),)


class PullConfiguration(Base):
    """Stores data pull job configurations."""

    __tablename__ = "pull_configurations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    data_type = Column(String(20), nullable=False)  # 'realtime_15min', 'daily_mean'
    data_strategy = Column(String(20), nullable=False)  # 'append', 'overwrite'
    pull_start_date = Column(DateTime(timezone=True), nullable=False)
    is_enabled = Column(Boolean, default=True)

    # Schedule (cron-like)
    schedule_type = Column(String(20), nullable=False)  # 'hourly', 'daily', 'weekly'
    schedule_value = Column(String(50))  # e.g., '0 */6 * * *' for cron

    last_run_at = Column(DateTime(timezone=True))
    next_run_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    configuration_stations = relationship(
        "PullConfigurationStation", back_populates="configuration"
    )
    logs = relationship("DataPullLog", back_populates="configuration")
    progress_records = relationship(
        "PullStationProgress", back_populates="configuration"
    )


class PullConfigurationStation(Base):
    """Junction table linking configurations to stations."""

    __tablename__ = "pull_configuration_stations"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(
        Integer, ForeignKey("pull_configurations.id"), nullable=False, index=True
    )
    station_number = Column(String(50), nullable=False)
    station_name = Column(Text)
    huc_code = Column(String(20))
    state = Column(String(50))

    # Relationships
    configuration = relationship(
        "PullConfiguration", back_populates="configuration_stations"
    )


class DataPullLog(Base):
    """Tracks data pull job execution history."""

    __tablename__ = "data_pull_logs"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(
        Integer, ForeignKey("pull_configurations.id"), nullable=False, index=True
    )
    status = Column(String(20), nullable=False)  # 'success', 'failed', 'running'
    records_processed = Column(Integer)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True))
    error_message = Column(Text)

    # Relationships
    configuration = relationship("PullConfiguration", back_populates="logs")

    __table_args__ = (Index("idx_config_start_time", "config_id", "start_time"),)


class PullStationProgress(Base):
    """Tracks the progress of each station within a configuration (Smart Append Logic)."""

    __tablename__ = "pull_station_progress"

    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(
        Integer, ForeignKey("pull_configurations.id"), nullable=False, index=True
    )
    station_number = Column(String(50), nullable=False)

    # CRUCIAL FIELD FOR SMART LOGIC
    last_successful_pull_date = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    configuration = relationship("PullConfiguration", back_populates="progress_records")

    __table_args__ = (
        UniqueConstraint("config_id", "station_number", name="unique_progress_idx"),
    )


class MasterStation(Base):
    """Master station list (from CSV import)."""

    __tablename__ = "master_stations"

    id = Column(Integer, primary_key=True, index=True)
    station_number = Column(String(50), unique=True, nullable=False, index=True)
    station_name = Column(Text, nullable=False)
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    state_code = Column(String(10), index=True)
    huc_code = Column(String(20), index=True)
    altitude_ft = Column(Numeric)
    drainage_area_sqmi = Column(Numeric)
    agency = Column(String(20), default="USGS")


class StationMapping(Base):
    """Stores mappings between different network IDs."""

    __tablename__ = "station_mappings"

    id = Column(Integer, primary_key=True, index=True)
    source_agency = Column(String(50), nullable=False)  # e.g., 'USGS'
    source_id = Column(String(50), nullable=False, index=True)
    target_agency = Column(String(50), nullable=False)  # e.g., 'NOAA-HADS'
    target_id = Column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source_agency", "source_id", "target_agency", name="unique_mapping_idx"
        ),
        Index("idx_source_lookup", "source_agency", "source_id"),
    )
