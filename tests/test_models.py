"""Unit tests for database models."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.connection import Base
from src.database.models import (
    Station,
    DischargeObservation,
    PullConfiguration,
    PullStationProgress,
    MasterStation,
    StationMapping,
)


# Test database setup
@pytest.fixture
def test_db():
    """Create a test database in memory."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    yield db

    db.close()


def test_create_station(test_db):
    """Test creating a station."""
    station = Station(
        station_number="01234567",
        name="Test Station",
        agency="USGS",
        latitude=45.1234,
        longitude=-122.5678,
        state="OR",
        huc_code="17100101",
        is_active=True,
    )

    test_db.add(station)
    test_db.commit()

    retrieved = test_db.query(Station).filter_by(station_number="01234567").first()
    assert retrieved is not None
    assert retrieved.name == "Test Station"
    assert retrieved.agency == "USGS"
    assert float(retrieved.latitude) == 45.1234


def test_create_discharge_observation(test_db):
    """Test creating a discharge observation."""
    # Create station first
    station = Station(
        station_number="01234567", name="Test Station", agency="USGS", state="OR"
    )
    test_db.add(station)
    test_db.commit()

    # Create observation
    obs = DischargeObservation(
        station_id=station.id,
        observed_at=datetime(2024, 1, 1, 12, 0, 0),
        discharge=1500.5,
        unit="cfs",
        type="realtime_15min",
        quality_code="P",
    )
    test_db.add(obs)
    test_db.commit()

    retrieved = (
        test_db.query(DischargeObservation).filter_by(station_id=station.id).first()
    )
    assert retrieved is not None
    assert float(retrieved.discharge) == 1500.5
    assert retrieved.unit == "cfs"


def test_unique_observation_constraint(test_db):
    """Test that duplicate observations are prevented."""
    station = Station(
        station_number="01234567", name="Test Station", agency="USGS", state="OR"
    )
    test_db.add(station)
    test_db.commit()

    # Create first observation
    obs1 = DischargeObservation(
        station_id=station.id,
        observed_at=datetime(2024, 1, 1, 12, 0, 0),
        discharge=1500.5,
        unit="cfs",
        type="realtime_15min",
    )
    test_db.add(obs1)
    test_db.commit()

    # Try to create duplicate
    obs2 = DischargeObservation(
        station_id=station.id,
        observed_at=datetime(2024, 1, 1, 12, 0, 0),
        discharge=1600.0,
        unit="cfs",
        type="realtime_15min",
    )
    test_db.add(obs2)

    with pytest.raises(Exception):  # Should raise IntegrityError
        test_db.commit()


def test_pull_configuration(test_db):
    """Test creating a pull configuration."""
    config = PullConfiguration(
        name="Test Config",
        description="Test description",
        data_type="daily_mean",
        data_strategy="append",
        pull_start_date=datetime(2024, 1, 1),
        schedule_type="daily",
        schedule_value="0 6 * * *",
        is_enabled=True,
    )
    test_db.add(config)
    test_db.commit()

    retrieved = test_db.query(PullConfiguration).filter_by(name="Test Config").first()
    assert retrieved is not None
    assert retrieved.data_type == "daily_mean"
    assert retrieved.is_enabled is True


def test_pull_station_progress(test_db):
    """Test the Smart Append Logic progress tracking."""
    config = PullConfiguration(
        name="Test Config",
        data_type="daily_mean",
        data_strategy="append",
        pull_start_date=datetime(2024, 1, 1),
        schedule_type="daily",
        is_enabled=True,
    )
    test_db.add(config)
    test_db.commit()

    # Create progress record
    progress = PullStationProgress(
        config_id=config.id,
        station_number="01234567",
        last_successful_pull_date=datetime(2024, 6, 1),
    )
    test_db.add(progress)
    test_db.commit()

    retrieved = (
        test_db.query(PullStationProgress)
        .filter_by(config_id=config.id, station_number="01234567")
        .first()
    )

    assert retrieved is not None
    assert retrieved.last_successful_pull_date.year == 2024
    assert retrieved.last_successful_pull_date.month == 6


def test_master_station(test_db):
    """Test creating a master station from CSV data."""
    master = MasterStation(
        station_number="01234567",
        station_name="Test Station",
        latitude=45.1234,
        longitude=-122.5678,
        state_code="OR",
        huc_code="17100101",
        altitude_ft=1250.5,
        drainage_area_sqmi=125.3,
        agency="USGS",
    )
    test_db.add(master)
    test_db.commit()

    retrieved = (
        test_db.query(MasterStation).filter_by(station_number="01234567").first()
    )
    assert retrieved is not None
    assert retrieved.station_name == "Test Station"
    assert float(retrieved.drainage_area_sqmi) == 125.3


def test_station_mapping(test_db):
    """Test station ID mapping."""
    mapping = StationMapping(
        source_agency="USGS",
        source_id="01234567",
        target_agency="NOAA-HADS",
        target_id="TSTS1",
    )
    test_db.add(mapping)
    test_db.commit()

    retrieved = (
        test_db.query(StationMapping)
        .filter_by(source_agency="USGS", source_id="01234567")
        .first()
    )

    assert retrieved is not None
    assert retrieved.target_id == "TSTS1"


def test_station_relationships(test_db):
    """Test relationships between models."""
    station = Station(
        station_number="01234567", name="Test Station", agency="USGS", state="OR"
    )
    test_db.add(station)
    test_db.commit()

    # Add observations
    obs1 = DischargeObservation(
        station_id=station.id,
        observed_at=datetime(2024, 1, 1, 12, 0, 0),
        discharge=1500.5,
        unit="cfs",
        type="realtime_15min",
    )
    obs2 = DischargeObservation(
        station_id=station.id,
        observed_at=datetime(2024, 1, 1, 13, 0, 0),
        discharge=1550.0,
        unit="cfs",
        type="realtime_15min",
    )
    test_db.add(obs1)
    test_db.add(obs2)
    test_db.commit()

    # Test relationship
    station = test_db.query(Station).filter_by(station_number="01234567").first()
    assert len(station.discharge_observations) == 2
    assert station.discharge_observations[0].discharge in [1500.5, 1550.0]
