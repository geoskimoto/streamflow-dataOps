"""Tests for data processor."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.connection import Base
from src.database.models import Station
from src.acquisition.data_processor import DataProcessor


@pytest.fixture
def test_db():
    """Create a test database in memory."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    # Create a test station
    station = Station(
        station_number="01234567", name="Test Station", agency="USGS", state="OR"
    )
    db.add(station)
    db.commit()

    yield db

    db.close()


def test_validate_observations_valid(test_db):
    """Test validation of valid observations."""
    processor = DataProcessor(test_db)

    observations = [
        {
            "observed_at": datetime(2024, 1, 1, 12, 0),
            "discharge": 1500.5,
            "unit": "cfs",
            "type": "daily_mean",
        },
        {
            "observed_at": datetime(2024, 1, 2, 12, 0),
            "discharge": 1600.0,
            "unit": "cfs",
            "type": "daily_mean",
        },
    ]

    valid = processor.validate_observations(observations)
    assert len(valid) == 2


def test_validate_observations_negative_discharge(test_db):
    """Test that negative discharge values are filtered out."""
    processor = DataProcessor(test_db)

    observations = [
        {
            "observed_at": datetime(2024, 1, 1, 12, 0),
            "discharge": 1500.5,
            "unit": "cfs",
            "type": "daily_mean",
        },
        {
            "observed_at": datetime(2024, 1, 2, 12, 0),
            "discharge": -100.0,  # Negative value
            "unit": "cfs",
            "type": "daily_mean",
        },
    ]

    valid = processor.validate_observations(observations)
    assert len(valid) == 1
    assert valid[0]["discharge"] == 1500.5


def test_validate_observations_missing_fields(test_db):
    """Test that observations with missing fields are filtered out."""
    processor = DataProcessor(test_db)

    observations = [
        {
            "observed_at": datetime(2024, 1, 1, 12, 0),
            "discharge": 1500.5,
            "unit": "cfs",
            "type": "daily_mean",
        },
        {
            # Missing 'unit' and 'type'
            "observed_at": datetime(2024, 1, 2, 12, 0),
            "discharge": 1600.0,
        },
    ]

    valid = processor.validate_observations(observations)
    assert len(valid) == 1


def test_validate_observations_null_discharge(test_db):
    """Test that null discharge values are filtered out."""
    processor = DataProcessor(test_db)

    observations = [
        {
            "observed_at": datetime(2024, 1, 1, 12, 0),
            "discharge": 1500.5,
            "unit": "cfs",
            "type": "daily_mean",
        },
        {
            "observed_at": datetime(2024, 1, 2, 12, 0),
            "discharge": None,  # Null value
            "unit": "cfs",
            "type": "daily_mean",
        },
    ]

    valid = processor.validate_observations(observations)
    assert len(valid) == 1


def test_validate_observations_unreasonably_high(test_db):
    """Test that unreasonably high discharge values are filtered out."""
    processor = DataProcessor(test_db)

    observations = [
        {
            "observed_at": datetime(2024, 1, 1, 12, 0),
            "discharge": 1500.5,
            "unit": "cfs",
            "type": "daily_mean",
        },
        {
            "observed_at": datetime(2024, 1, 2, 12, 0),
            "discharge": 2_000_000.0,  # Unreasonably high
            "unit": "cfs",
            "type": "daily_mean",
        },
    ]

    valid = processor.validate_observations(observations)
    assert len(valid) == 1


def test_process_observations_success(test_db):
    """Test successful processing of observations."""
    processor = DataProcessor(test_db)

    observations = [
        {
            "observed_at": datetime(2024, 1, 1, 12, 0),
            "discharge": 1500.5,
            "unit": "cfs",
            "type": "daily_mean",
        }
    ]

    count = processor.process_observations("01234567", observations)
    assert count == 1


def test_process_observations_station_not_found(test_db):
    """Test processing observations for non-existent station."""
    processor = DataProcessor(test_db)

    observations = [
        {
            "observed_at": datetime(2024, 1, 1, 12, 0),
            "discharge": 1500.5,
            "unit": "cfs",
            "type": "daily_mean",
        }
    ]

    count = processor.process_observations("99999999", observations)
    assert count == 0


def test_get_data_quality_summary(test_db):
    """Test data quality summary generation."""
    processor = DataProcessor(test_db)

    observations = [
        {
            "observed_at": datetime(2024, 1, 1, 12, 0),
            "discharge": 1500.0,
            "unit": "cfs",
            "type": "daily_mean",
        },
        {
            "observed_at": datetime(2024, 1, 2, 12, 0),
            "discharge": 2000.0,
            "unit": "cfs",
            "type": "daily_mean",
        },
        {
            "observed_at": datetime(2024, 1, 3, 12, 0),
            "discharge": None,  # Null
            "unit": "cfs",
            "type": "daily_mean",
        },
        {
            "observed_at": datetime(2024, 1, 4, 12, 0),
            "discharge": -100.0,  # Negative
            "unit": "cfs",
            "type": "daily_mean",
        },
    ]

    summary = processor.get_data_quality_summary(observations)

    assert summary["total_records"] == 4
    assert summary["valid_records"] == 2
    assert summary["null_values"] == 1
    assert summary["negative_values"] == 1
    assert summary["min_discharge"] == 1500.0
    assert summary["max_discharge"] == 2000.0
    assert summary["mean_discharge"] == 1750.0


def test_get_data_quality_summary_empty(test_db):
    """Test data quality summary with empty observations."""
    processor = DataProcessor(test_db)

    summary = processor.get_data_quality_summary([])

    assert summary["total_records"] == 0
    assert summary["valid_records"] == 0
    assert summary["null_values"] == 0
    assert summary["negative_values"] == 0
    assert summary["min_discharge"] is None
    assert summary["max_discharge"] is None
    assert summary["mean_discharge"] is None
