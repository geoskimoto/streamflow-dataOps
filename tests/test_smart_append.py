"""Tests for Smart Append Logic."""
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.connection import Base
from src.database.models import PullConfiguration, PullStationProgress
from src.acquisition.smart_append import SmartAppendLogic


@pytest.fixture
def test_db():
    """Create a test database in memory."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()
    
    yield db
    
    db.close()


def test_smart_append_first_pull(test_db):
    """Test Smart Append Logic for first pull (no progress record)."""
    # Create a configuration
    config = PullConfiguration(
        name="Test Config",
        data_type="daily_mean",
        data_strategy="append",
        pull_start_date=datetime(2020, 1, 1),
        schedule_type="daily",
        is_enabled=True
    )
    test_db.add(config)
    test_db.commit()
    
    # Test first pull
    smart_append = SmartAppendLogic(test_db)
    start_date = smart_append.get_pull_start_date(
        config_id=config.id,
        station_number='01234567',
        config_start_date=config.pull_start_date
    )
    
    # Should return config start date (first pull)
    assert start_date == datetime(2020, 1, 1)


def test_smart_append_subsequent_pull(test_db):
    """Test Smart Append Logic for subsequent pull (with progress record)."""
    # Create a configuration
    config = PullConfiguration(
        name="Test Config",
        data_type="daily_mean",
        data_strategy="append",
        pull_start_date=datetime(2020, 1, 1),
        schedule_type="daily",
        is_enabled=True
    )
    test_db.add(config)
    test_db.commit()
    
    # Create progress record (simulating previous pull)
    progress = PullStationProgress(
        config_id=config.id,
        station_number='01234567',
        last_successful_pull_date=datetime(2024, 6, 1)
    )
    test_db.add(progress)
    test_db.commit()
    
    # Test subsequent pull
    smart_append = SmartAppendLogic(test_db)
    start_date = smart_append.get_pull_start_date(
        config_id=config.id,
        station_number='01234567',
        config_start_date=config.pull_start_date
    )
    
    # Should return last pull date (subsequent pull)
    assert start_date == datetime(2024, 6, 1)


def test_smart_append_update_progress(test_db):
    """Test updating progress after successful pull."""
    # Create a configuration
    config = PullConfiguration(
        name="Test Config",
        data_type="daily_mean",
        data_strategy="append",
        pull_start_date=datetime(2020, 1, 1),
        schedule_type="daily",
        is_enabled=True
    )
    test_db.add(config)
    test_db.commit()
    
    # Update progress
    smart_append = SmartAppendLogic(test_db)
    smart_append.update_pull_progress(
        config_id=config.id,
        station_number='01234567',
        successful_pull_date=datetime(2024, 6, 15)
    )
    
    # Verify progress was created/updated
    progress = test_db.query(PullStationProgress).filter_by(
        config_id=config.id,
        station_number='01234567'
    ).first()
    
    assert progress is not None
    assert progress.last_successful_pull_date == datetime(2024, 6, 15)


def test_smart_append_multiple_stations(test_db):
    """Test Smart Append Logic with multiple stations."""
    # Create a configuration
    config = PullConfiguration(
        name="Test Config",
        data_type="daily_mean",
        data_strategy="append",
        pull_start_date=datetime(2020, 1, 1),
        schedule_type="daily",
        is_enabled=True
    )
    test_db.add(config)
    test_db.commit()
    
    # Create progress for multiple stations
    smart_append = SmartAppendLogic(test_db)
    
    smart_append.update_pull_progress(config.id, '01234567', datetime(2024, 6, 1))
    smart_append.update_pull_progress(config.id, '12345678', datetime(2024, 5, 15))
    smart_append.update_pull_progress(config.id, '23456789', datetime(2024, 6, 10))
    
    # Test each station gets correct start date
    date1 = smart_append.get_pull_start_date(config.id, '01234567', config.pull_start_date)
    date2 = smart_append.get_pull_start_date(config.id, '12345678', config.pull_start_date)
    date3 = smart_append.get_pull_start_date(config.id, '23456789', config.pull_start_date)
    
    assert date1 == datetime(2024, 6, 1)
    assert date2 == datetime(2024, 5, 15)
    assert date3 == datetime(2024, 6, 10)


def test_smart_append_get_all_progress(test_db):
    """Test getting all progress records for a configuration."""
    # Create a configuration
    config = PullConfiguration(
        name="Test Config",
        data_type="daily_mean",
        data_strategy="append",
        pull_start_date=datetime(2020, 1, 1),
        schedule_type="daily",
        is_enabled=True
    )
    test_db.add(config)
    test_db.commit()
    
    # Add progress for multiple stations
    smart_append = SmartAppendLogic(test_db)
    smart_append.update_pull_progress(config.id, '01234567', datetime(2024, 6, 1))
    smart_append.update_pull_progress(config.id, '12345678', datetime(2024, 6, 2))
    
    # Get all progress
    all_progress = smart_append.get_all_progress(config.id)
    
    assert len(all_progress) == 2
    station_numbers = [p.station_number for p in all_progress]
    assert '01234567' in station_numbers
    assert '12345678' in station_numbers


def test_smart_append_reset_progress(test_db):
    """Test resetting progress for a station."""
    # Create configuration and progress
    config = PullConfiguration(
        name="Test Config",
        data_type="daily_mean",
        data_strategy="append",
        pull_start_date=datetime(2020, 1, 1),
        schedule_type="daily",
        is_enabled=True
    )
    test_db.add(config)
    test_db.commit()
    
    smart_append = SmartAppendLogic(test_db)
    smart_append.update_pull_progress(config.id, '01234567', datetime(2024, 6, 1))
    
    # Reset progress
    smart_append.reset_station_progress(config.id, '01234567')
    
    # Should now use config start date (as if first pull)
    start_date = smart_append.get_pull_start_date(
        config_id=config.id,
        station_number='01234567',
        config_start_date=config.pull_start_date
    )
    
    assert start_date == datetime(2020, 1, 1)
