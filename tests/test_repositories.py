"""Unit tests for repository pattern."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.connection import Base
from src.database.repositories import (
    StationRepository,
    DischargeObservationRepository,
    PullConfigurationRepository,
    PullStationProgressRepository,
    MasterStationRepository,
    StationMappingRepository,
)


@pytest.fixture
def test_db():
    """Create a test database in memory."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    yield db

    db.close()


def test_station_repository_create(test_db):
    """Test creating a station via repository."""
    repo = StationRepository(test_db)

    station_data = {
        "station_number": "01234567",
        "name": "Test Station",
        "agency": "USGS",
        "latitude": 45.1234,
        "longitude": -122.5678,
        "state": "OR",
        "huc_code": "17100101",
        "is_active": True,
    }

    station = repo.create(station_data)
    assert station.id is not None
    assert station.station_number == "01234567"


def test_station_repository_search(test_db):
    """Test station search."""
    repo = StationRepository(test_db)

    # Create test stations
    repo.create(
        {
            "station_number": "01234567",
            "name": "Oregon Test Station",
            "agency": "USGS",
            "state": "OR",
            "huc_code": "17100101",
        }
    )
    repo.create(
        {
            "station_number": "12345678",
            "name": "Washington Test Station",
            "agency": "USGS",
            "state": "WA",
            "huc_code": "17110101",
        }
    )

    # Search by state
    results = repo.search(state="OR")
    assert len(results) == 1
    assert results[0].state == "OR"

    # Search by query
    results = repo.search(query="Oregon")
    assert len(results) == 1

    # Search by HUC
    results = repo.search(huc_code="1710")
    assert len(results) == 1


def test_discharge_observation_repository_bulk_create(test_db):
    """Test bulk creating observations."""
    station_repo = StationRepository(test_db)
    obs_repo = DischargeObservationRepository(test_db)

    # Create station
    station = station_repo.create(
        {
            "station_number": "01234567",
            "name": "Test Station",
            "agency": "USGS",
            "state": "OR",
        }
    )

    # Bulk create observations
    observations = [
        {
            "station_id": station.id,
            "observed_at": datetime(2024, 1, 1, 12, 0, 0),
            "discharge": 1500.5,
            "unit": "cfs",
            "type": "realtime_15min",
        },
        {
            "station_id": station.id,
            "observed_at": datetime(2024, 1, 1, 13, 0, 0),
            "discharge": 1550.0,
            "unit": "cfs",
            "type": "realtime_15min",
        },
    ]

    count = obs_repo.bulk_create(observations)
    assert count == 2

    # Try to insert duplicate - should be ignored
    count = obs_repo.bulk_create(observations)
    assert count == 0


def test_discharge_observation_repository_get_latest(test_db):
    """Test getting latest observation."""
    station_repo = StationRepository(test_db)
    obs_repo = DischargeObservationRepository(test_db)

    station = station_repo.create(
        {
            "station_number": "01234567",
            "name": "Test Station",
            "agency": "USGS",
            "state": "OR",
        }
    )

    observations = [
        {
            "station_id": station.id,
            "observed_at": datetime(2024, 1, 1, 12, 0, 0),
            "discharge": 1500.5,
            "unit": "cfs",
            "type": "realtime_15min",
        },
        {
            "station_id": station.id,
            "observed_at": datetime(2024, 1, 2, 12, 0, 0),
            "discharge": 1550.0,
            "unit": "cfs",
            "type": "realtime_15min",
        },
    ]

    obs_repo.bulk_create(observations)

    latest = obs_repo.get_latest_observation(station.id, "realtime_15min")
    assert latest is not None
    assert latest.observed_at == datetime(2024, 1, 2, 12, 0, 0)
    assert float(latest.discharge) == 1550.0


def test_pull_configuration_repository(test_db):
    """Test pull configuration repository."""
    repo = PullConfigurationRepository(test_db)

    config_data = {
        "name": "Test Config",
        "description": "Test description",
        "data_type": "daily_mean",
        "data_strategy": "append",
        "pull_start_date": datetime(2024, 1, 1),
        "schedule_type": "daily",
        "schedule_value": "0 6 * * *",
        "is_enabled": True,
    }

    config = repo.create(config_data)
    assert config.id is not None

    # Add stations to config
    stations = [
        {"station_number": "01234567", "station_name": "Test 1", "state": "OR"},
        {"station_number": "12345678", "station_name": "Test 2", "state": "WA"},
    ]

    count = repo.add_stations(config.id, stations)
    assert count == 2

    # Get stations
    config_stations = repo.get_stations(config.id)
    assert len(config_stations) == 2


def test_pull_station_progress_repository(test_db):
    """Test Smart Append Logic progress tracking."""
    config_repo = PullConfigurationRepository(test_db)
    progress_repo = PullStationProgressRepository(test_db)

    # Create config
    config = config_repo.create(
        {
            "name": "Test Config",
            "data_type": "daily_mean",
            "data_strategy": "append",
            "pull_start_date": datetime(2024, 1, 1),
            "schedule_type": "daily",
            "is_enabled": True,
        }
    )

    # Update progress
    progress = progress_repo.update_progress(
        config.id, "01234567", datetime(2024, 6, 1)
    )

    assert progress.id is not None
    assert progress.last_successful_pull_date == datetime(2024, 6, 1)

    # Update again
    progress = progress_repo.update_progress(
        config.id, "01234567", datetime(2024, 6, 2)
    )

    assert progress.last_successful_pull_date == datetime(2024, 6, 2)

    # Get progress
    retrieved = progress_repo.get_progress(config.id, "01234567")
    assert retrieved is not None
    assert retrieved.last_successful_pull_date == datetime(2024, 6, 2)


def test_master_station_repository(test_db):
    """Test master station repository."""
    repo = MasterStationRepository(test_db)

    stations = [
        {
            "station_number": "01234567",
            "station_name": "Test Station 1",
            "latitude": 45.1234,
            "longitude": -122.5678,
            "state_code": "OR",
            "huc_code": "17100101",
            "agency": "USGS",
        },
        {
            "station_number": "12345678",
            "station_name": "Test Station 2",
            "latitude": 46.1234,
            "longitude": -123.5678,
            "state_code": "WA",
            "huc_code": "17110101",
            "agency": "USGS",
        },
    ]

    count = repo.bulk_upsert(stations)
    assert count == 2

    # Search
    results = repo.search(query="Test")
    assert len(results) == 2

    results = repo.search(state_code="OR")
    assert len(results) == 1


def test_station_mapping_repository(test_db):
    """Test station mapping repository."""
    repo = StationMappingRepository(test_db)

    # Create mapping
    mapping_data = {
        "source_agency": "USGS",
        "source_id": "01234567",
        "target_agency": "NOAA-HADS",
        "target_id": "TSTS1",
    }

    mapping = repo.create_mapping(mapping_data)
    assert mapping.id is not None

    # Get mapping
    target_id = repo.get_mapping("USGS", "01234567", "NOAA-HADS")
    assert target_id == "TSTS1"

    # Bulk create
    mappings = [
        {
            "source_agency": "USGS",
            "source_id": "12345678",
            "target_agency": "NOAA-HADS",
            "target_id": "TSTS2",
        },
        {
            "source_agency": "USGS",
            "source_id": "23456789",
            "target_agency": "NOAA-HADS",
            "target_id": "TSTS3",
        },
    ]

    count = repo.bulk_create(mappings)
    assert count == 2
