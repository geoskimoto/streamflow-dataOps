# Component 1: Database Design and Persistence Layer

This is the implementation of Component 1 from the streamflow DataOps project. It provides a comprehensive database layer using SQLAlchemy ORM with support for PostgreSQL (production) and SQLite (development).

## Features

✅ **Database Models**
- Station metadata management
- Discharge observations with time-series support
- Forecast run data storage
- Pull configuration management
- Smart Append Logic via PullStationProgress
- Master station list management
- Cross-agency station ID mapping

✅ **Repository Pattern**
- Clean separation of concerns
- Reusable data access layer
- Bulk operations support
- Search and filter capabilities

✅ **Database Migrations**
- Alembic integration for schema versioning
- Auto-generate migrations from model changes
- Support for both SQLite and PostgreSQL

✅ **CSV Data Loading**
- Load master station lists from CSV files
- Import station ID mappings
- Bulk upsert operations

## Project Structure

```
streamflow_DataOps/
├── src/
│   ├── database/
│   │   ├── __init__.py
│   │   ├── connection.py      # SQLAlchemy engine and session
│   │   ├── models.py           # ORM models
│   │   ├── repositories.py     # Repository pattern
│   │   └── init_db.py          # Database initialization
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py         # Configuration
│   └── utils/
│       ├── __init__.py
│       └── csv_loader.py       # CSV import utilities
├── migrations/                  # Alembic migrations
│   └── versions/
├── tests/
│   ├── __init__.py
│   ├── test_models.py          # Model tests
│   └── test_repositories.py    # Repository tests
├── data/                        # CSV data files
├── .env.example                 # Environment template
├── .gitignore
├── alembic.ini                  # Alembic configuration
└── requirements.txt             # Python dependencies
```

## Installation

1. **Create a virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure environment:**
```bash
cp .env.example .env
# Edit .env and set your DATABASE_URL
```

For SQLite (development):
```
DATABASE_URL=sqlite:///./streamflow_dev.db
```

For PostgreSQL (production):
```
DATABASE_URL=postgresql://user:password@localhost:5432/streamflow_db
```

## Usage

### Initialize Database

```bash
# Create tables
python src/database/init_db.py

# Or use Alembic for migrations
alembic upgrade head
```

### Create Migration

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Add new column"

# Apply migration
alembic upgrade head
```

### Load Master Station Data

```python
from src.database.connection import SessionLocal
from src.database.repositories import MasterStationRepository
from src.utils.csv_loader import load_master_stations_from_csv

# Load from CSV
stations = load_master_stations_from_csv('data/usgs_stations.csv')

# Save to database
db = SessionLocal()
try:
    repo = MasterStationRepository(db)
    count = repo.bulk_upsert(stations)
    print(f"Loaded {count} stations")
finally:
    db.close()
```

### Working with Repositories

```python
from src.database.connection import SessionLocal
from src.database.repositories import StationRepository, DischargeObservationRepository
from datetime import datetime

db = SessionLocal()

# Create a station
station_repo = StationRepository(db)
station = station_repo.create({
    'station_number': '01234567',
    'name': 'Example Station',
    'agency': 'USGS',
    'latitude': 45.1234,
    'longitude': -122.5678,
    'state': 'OR',
    'huc_code': '17100101'
})

# Add observations
obs_repo = DischargeObservationRepository(db)
observations = [
    {
        'station_id': station.id,
        'observed_at': datetime(2024, 1, 1, 12, 0),
        'discharge': 1500.5,
        'unit': 'cfs',
        'type': 'realtime_15min'
    }
]
count = obs_repo.bulk_create(observations)
print(f"Added {count} observations")

# Search stations
results = station_repo.search(query='Example', state='OR')

db.close()
```

### Smart Append Logic

The `PullStationProgress` table tracks the last successful pull date for each station in a configuration, enabling incremental data pulls:

```python
from src.database.repositories import PullStationProgressRepository
from datetime import datetime

db = SessionLocal()
progress_repo = PullStationProgressRepository(db)

# Get last pull date for a station
progress = progress_repo.get_progress(config_id=1, station_number='01234567')
if progress:
    last_date = progress.last_successful_pull_date
    # Pull data from last_date to now
else:
    # First pull - use config.pull_start_date

# Update progress after successful pull
progress_repo.update_progress(
    config_id=1,
    station_number='01234567',
    last_pull_date=datetime.now()
)
```

## Database Schema

### Core Tables

**stations** - Station metadata
- station_number (unique)
- name, agency, latitude, longitude
- huc_code, basin, state
- catchment_area, years_of_record
- record_start_date, record_end_date

**discharge_observations** - Time series data
- station_id (FK)
- observed_at (timestamp)
- discharge, unit, type
- quality_code
- Unique constraint on (station_id, observed_at, type)

**forecast_runs** - Forecast data
- station_id (FK)
- source, run_date
- data (JSON array)
- rmse (accuracy metric)

### Configuration Tables

**pull_configurations** - Data pull job definitions
- name, description
- data_type, data_strategy
- pull_start_date
- schedule_type, schedule_value
- is_enabled

**pull_configuration_stations** - Stations in each config
- config_id (FK)
- station_number, station_name
- huc_code, state

**data_pull_logs** - Execution history
- config_id (FK)
- status, records_processed
- start_time, end_time
- error_message

**pull_station_progress** - Smart Append Logic
- config_id (FK)
- station_number
- last_successful_pull_date (crucial!)

### Reference Tables

**master_stations** - Master station list (from CSV)
- station_number, station_name
- latitude, longitude
- state_code, huc_code
- altitude_ft, drainage_area_sqmi

**station_mappings** - Cross-agency ID translation
- source_agency, source_id
- target_agency, target_id
- e.g., USGS ↔ NOAA-HADS

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/

# Run specific test file
pytest tests/test_models.py -v
```

## Next Steps

After completing Component 1, proceed with:
- **Component 2**: Data Acquisition Layer (Celery workers, API clients)
- **Component 3**: Django Web Interface (Configuration management UI)
- **Component 4**: REST API (FastAPI endpoints)

## Notes

- Always use the repository pattern instead of direct ORM access
- The `get_db()` function in connection.py provides dependency injection for FastAPI
- Alembic migrations should be created for all schema changes
- The Smart Append Logic prevents duplicate data pulls and reduces API calls
- Station mappings enable cross-referencing data from multiple agencies

## License

[Add your license here]
