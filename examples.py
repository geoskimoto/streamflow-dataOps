"""Example usage of the database layer."""
from datetime import datetime
from src.database.connection import SessionLocal
from src.database.repositories import (
    StationRepository,
    DischargeObservationRepository,
    PullConfigurationRepository,
    PullStationProgressRepository
)


def example_basic_usage():
    """Example: Create a station and add observations."""
    print("\n=== Example 1: Basic Usage ===")
    
    db = SessionLocal()
    try:
        # Create a station
        station_repo = StationRepository(db)
        station = station_repo.create({
            'station_number': '14211720',
            'name': 'WILLAMETTE RIVER AT PORTLAND, OR',
            'agency': 'USGS',
            'latitude': 45.5230,
            'longitude': -122.6670,
            'state': 'OR',
            'huc_code': '17090012',
            'basin': 'Willamette River',
            'is_active': True
        })
        print(f"✓ Created station: {station.name} (ID: {station.id})")
        
        # Add some observations
        obs_repo = DischargeObservationRepository(db)
        observations = [
            {
                'station_id': station.id,
                'observed_at': datetime(2024, 1, 1, 12, 0),
                'discharge': 15000.0,
                'unit': 'cfs',
                'type': 'realtime_15min',
                'quality_code': 'P'
            },
            {
                'station_id': station.id,
                'observed_at': datetime(2024, 1, 1, 12, 15),
                'discharge': 15050.0,
                'unit': 'cfs',
                'type': 'realtime_15min',
                'quality_code': 'P'
            }
        ]
        
        count = obs_repo.bulk_create(observations)
        print(f"✓ Added {count} observations")
        
        # Get latest observation
        latest = obs_repo.get_latest_observation(station.id, 'realtime_15min')
        print(f"✓ Latest observation: {latest.discharge} {latest.unit} at {latest.observed_at}")
        
    finally:
        db.close()


def example_pull_configuration():
    """Example: Create a pull configuration with Smart Append Logic."""
    print("\n=== Example 2: Pull Configuration with Smart Append Logic ===")
    
    db = SessionLocal()
    try:
        # Create a pull configuration
        config_repo = PullConfigurationRepository(db)
        config = config_repo.create({
            'name': 'Oregon Daily Discharge',
            'description': 'Daily mean discharge for Oregon stations',
            'data_type': 'daily_mean',
            'data_strategy': 'append',
            'pull_start_date': datetime(2020, 1, 1),
            'schedule_type': 'daily',
            'schedule_value': '0 6 * * *',  # 6 AM daily
            'is_enabled': True
        })
        print(f"✓ Created configuration: {config.name} (ID: {config.id})")
        
        # Add stations to the configuration
        stations = [
            {
                'station_number': '14211720',
                'station_name': 'WILLAMETTE RIVER AT PORTLAND, OR',
                'state': 'OR',
                'huc_code': '17090012'
            },
            {
                'station_number': '14128910',
                'station_name': 'COLUMBIA RIVER AT THE DALLES, OR',
                'state': 'OR',
                'huc_code': '17070105'
            }
        ]
        
        count = config_repo.add_stations(config.id, stations)
        print(f"✓ Added {count} stations to configuration")
        
        # Simulate Smart Append Logic
        progress_repo = PullStationProgressRepository(db)
        
        # First pull for station 1
        progress1 = progress_repo.update_progress(
            config_id=config.id,
            station_number='14211720',
            last_pull_date=datetime(2024, 1, 1)
        )
        print(f"✓ Updated progress for station 14211720: last pull {progress1.last_successful_pull_date}")
        
        # Second pull - would start from last_successful_pull_date
        progress1 = progress_repo.update_progress(
            config_id=config.id,
            station_number='14211720',
            last_pull_date=datetime(2024, 6, 1)
        )
        print(f"✓ Updated progress for station 14211720: last pull {progress1.last_successful_pull_date}")
        
        # Get all progress records
        all_progress = progress_repo.get_all_for_config(config.id)
        print(f"✓ Total progress records: {len(all_progress)}")
        
    finally:
        db.close()


def example_search():
    """Example: Search for stations."""
    print("\n=== Example 3: Search Stations ===")
    
    db = SessionLocal()
    try:
        station_repo = StationRepository(db)
        
        # Search by name
        results = station_repo.search(query='WILLAMETTE')
        print(f"✓ Found {len(results)} stations matching 'WILLAMETTE'")
        
        # Search by state
        results = station_repo.search(state='OR')
        print(f"✓ Found {len(results)} stations in Oregon")
        
        # Search by HUC
        results = station_repo.search(huc_code='1709')
        print(f"✓ Found {len(results)} stations in HUC 1709*")
        
    finally:
        db.close()


if __name__ == "__main__":
    print("Component 1 Database Layer - Examples")
    print("=" * 50)
    
    # Note: This will create a SQLite database in memory or as configured
    # Make sure you have initialized the database first:
    # python src/database/init_db.py
    
    example_basic_usage()
    example_pull_configuration()
    example_search()
    
    print("\n" + "=" * 50)
    print("✓ All examples completed successfully!")
