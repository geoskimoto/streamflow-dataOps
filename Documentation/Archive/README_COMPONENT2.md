# Component 2: Data Acquisition and Preparation Services

This component implements automated data acquisition from multiple sources (USGS, Environment Canada, NOAA) using Celery worker tasks with Smart Append Logic for efficient incremental updates.

## Features

✅ **Multi-Source Data Acquisition**
- USGS data via `dataretrieval` library (daily mean & instantaneous)
- Environment Canada real-time and aggregated data
- NOAA National Water Model forecast data

✅ **Smart Append Logic**
- Incremental data pulls using `PullStationProgress` tracking
- First pull: Uses `pullConfiguration.pull_start_date`
- Subsequent pulls: Uses `last_successful_pull_date`
- Avoids duplicate data and reduces API calls

✅ **Celery Task Queue**
- Asynchronous task processing with Redis broker
- Configurable schedules (hourly, daily, weekly)
- Retry logic with exponential backoff
- Task monitoring and logging

✅ **Data Validation & Quality Control**
- Negative discharge filtering
- Reasonable range checking
- Missing field detection
- Data quality summary generation

✅ **Error Handling**
- Automatic retries for transient failures
- Detailed error logging
- Per-station failure isolation
- Comprehensive execution logs

## Project Structure

```
src/
├── acquisition/
│   ├── __init__.py
│   ├── tasks.py              # Celery tasks (main orchestration)
│   ├── usgs_client.py        # USGS data retrieval
│   ├── canada_client.py      # Environment Canada client
│   ├── noaa_client.py        # NOAA NWM forecast client
│   ├── data_processor.py     # Data validation and storage
│   └── smart_append.py       # Smart Append Logic implementation
├── celery_app/
│   ├── __init__.py
│   └── celery.py             # Celery app configuration
└── config/
    └── settings.py           # Updated with Redis & API config

tests/
├── test_usgs_client.py       # USGS client tests
├── test_smart_append.py      # Smart Append Logic tests (6 tests)
└── test_data_processor.py    # Data processor tests (9 tests)
```

## Installation

### 1. Install Redis

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install redis-server
sudo systemctl start redis
sudo systemctl enable redis
```

**macOS:**
```bash
brew install redis
brew services start redis
```

**Verify Redis:**
```bash
redis-cli ping
# Should return: PONG
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

New dependencies added:
- `celery==5.3.4` - Task queue
- `redis==5.0.1` - Message broker
- `dataretrieval==1.0.7` - USGS data library
- `requests==2.31.0` - HTTP client
- `pytz==2023.3` - Timezone handling
- `tenacity==8.2.3` - Retry logic

### 3. Configure Environment

Update `.env` file:
```bash
# Database
DATABASE_URL=sqlite:///./streamflow_dev.db

# Redis (for Celery)
REDIS_URL=redis://localhost:6379/0
```

## Usage

### Starting Celery Workers

**Start Celery worker:**
```bash
celery -A src.celery_app.celery worker --loglevel=info
```

**Start Celery Beat (scheduler):**
```bash
celery -A src.celery_app.celery beat --loglevel=info
```

**Start both together (development):**
```bash
celery -A src.celery_app.celery worker --beat --loglevel=info
```

### Executing Data Pulls

**Manual execution:**
```python
from src.acquisition.tasks import execute_pull_configuration

# Execute a pull configuration
result = execute_pull_configuration.delay(config_id=1)

# Check result
print(result.get())
```

**Scheduled execution:**
- Schedules are defined in `PullConfiguration` table
- Celery Beat automatically triggers tasks based on schedule
- In Component 3 (Django interface), users can create/manage schedules

### Using Individual Clients

**USGS Client:**
```python
from src.acquisition.usgs_client import USGSClient
from datetime import datetime

client = USGSClient()

# Get daily mean data
observations = client.get_daily_mean(
    station_number='14211720',
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 1, 31)
)

# Get instantaneous data
observations = client.get_instantaneous(
    station_number='14211720',
    start_date=datetime(2024, 12, 1),
    end_date=datetime(2024, 12, 1, 6, 0)
)

# Get station info
info = client.get_station_info('14211720')
```

**Environment Canada Client:**
```python
from src.acquisition.canada_client import CanadaClient

client = CanadaClient()

# Get real-time data
observations = client.get_realtime_data(
    station_number='01AP004',
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 1, 7)
)

# Get daily mean (calculated from real-time)
observations = client.get_daily_mean(
    station_number='01AP004',
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 1, 7)
)
```

**NOAA Client:**
```python
from src.acquisition.noaa_client import NOAAClient

client = NOAAClient()

# Get forecast (requires HADS ID, not USGS ID)
forecast = client.get_forecast(
    hads_id='PORO3',  # Must translate from USGS ID first
    forecast_type='short'  # 'short', 'medium', or 'long'
)
```

### Smart Append Logic

```python
from src.database.connection import SessionLocal
from src.acquisition.smart_append import SmartAppendLogic
from datetime import datetime

db = SessionLocal()
smart_append = SmartAppendLogic(db)

# Get start date for pull (uses last_successful_pull_date or config start date)
start_date = smart_append.get_pull_start_date(
    config_id=1,
    station_number='14211720',
    config_start_date=datetime(2020, 1, 1)
)

# After successful pull, update progress
smart_append.update_pull_progress(
    config_id=1,
    station_number='14211720',
    successful_pull_date=datetime(2024, 12, 15)
)

# Get all progress for a configuration
all_progress = smart_append.get_all_progress(config_id=1)

# Reset progress to force re-pull all data
smart_append.reset_station_progress(config_id=1, station_number='14211720')
```

### Data Processor

```python
from src.database.connection import SessionLocal
from src.acquisition.data_processor import DataProcessor

db = SessionLocal()
processor = DataProcessor(db)

# Process observations (validates and stores)
count = processor.process_observations(
    station_number='14211720',
    observations=observations_list
)

# Get data quality summary
summary = processor.get_data_quality_summary(observations_list)
print(f"Valid: {summary['valid_records']}/{summary['total_records']}")
print(f"Mean discharge: {summary['mean_discharge']} cfs")
```

## Task Execution Flow

1. **Celery Beat** triggers `execute_pull_configuration` based on schedule
2. **Task loads** pull configuration from database
3. **For each station** in configuration:
   - Smart Append Logic determines start date
   - Appropriate client (USGS/EC/NOAA) fetches data
   - Data Processor validates data
   - Observations stored in database
   - Progress updated for next pull
4. **Execution logged** with status and record counts

## Testing

```bash
# Run all acquisition tests
pytest tests/test_smart_append.py tests/test_data_processor.py -v

# Run with coverage
pytest tests/test_smart_append.py tests/test_data_processor.py --cov=src/acquisition

# Run integration tests (requires API access)
pytest tests/test_usgs_client.py -m integration -v
```

**Test Coverage:**
- Smart Append Logic: 6 tests
- Data Processor: 9 tests
- USGS Client: 5 tests (including integration tests)

## Monitoring & Debugging

**Monitor Celery tasks:**
```bash
# Using Flower (web-based monitoring)
pip install flower
celery -A src.celery_app.celery flower

# Access at http://localhost:5555
```

**Check Redis:**
```bash
redis-cli
> KEYS *
> GET celery-task-meta-<task-id>
```

**View task logs:**
```python
from src.database.repositories import DataPullLogRepository
from src.database.connection import SessionLocal

db = SessionLocal()
log_repo = DataPullLogRepository(db)

# Get recent logs for a configuration
logs = log_repo.get_recent_logs(config_id=1, limit=10)
for log in logs:
    print(f"{log.start_time}: {log.status} - {log.records_processed} records")
```

## Configuration Examples

**Create a daily pull configuration:**
```python
from src.database.repositories import PullConfigurationRepository
from src.database.connection import SessionLocal
from datetime import datetime

db = SessionLocal()
config_repo = PullConfigurationRepository(db)

config = config_repo.create({
    'name': 'Oregon Daily Discharge',
    'description': 'Daily mean discharge for Oregon stations',
    'data_type': 'daily_mean',
    'data_strategy': 'append',
    'pull_start_date': datetime(2020, 1, 1),
    'schedule_type': 'daily',
    'schedule_value': '0 6 * * *',  # 6 AM daily (cron format)
    'is_enabled': True
})

# Add stations
stations = [
    {'station_number': '14211720', 'station_name': 'WILLAMETTE RIVER AT PORTLAND, OR'},
    {'station_number': '14128910', 'station_name': 'COLUMBIA RIVER AT THE DALLES, OR'}
]
config_repo.add_stations(config.id, stations)
```

## API Rate Limits & Best Practices

**USGS:**
- No strict rate limits for reasonable use
- Recommend batch requests when possible
- Use daily values instead of instantaneous when appropriate

**Environment Canada:**
- CSV endpoint typically allows reasonable request rates
- Add delays between requests if pulling many stations

**NOAA:**
- Be respectful of API limits
- Cache forecast data appropriately
- Forecasts updated periodically, no need for constant polling

## Troubleshooting

**Redis connection refused:**
```bash
# Check if Redis is running
sudo systemctl status redis

# Start Redis
sudo systemctl start redis
```

**Celery tasks not executing:**
```bash
# Check Celery worker is running
ps aux | grep celery

# Restart worker
pkill -f celery
celery -A src.celery_app.celery worker --loglevel=info
```

**USGS data not returning:**
- Check station number is valid
- Verify date range has data
- Check internet connectivity
- USGS site may be down (check https://waterservices.usgs.gov/)

**Data validation failures:**
- Check DataPullLog table for error messages
- Review validation rules in data_processor.py
- Adjust validation thresholds if needed

## Next Steps

After completing Component 2, proceed with:
- **Component 3**: Django Web Interface (UI for configuration management)
- **Component 4**: REST API (FastAPI endpoints for data access)

Component 3 will provide a web UI to:
- Create and manage pull configurations
- Select stations interactively
- View execution logs and progress
- Enable/disable scheduled pulls
- Monitor data quality

## Performance Notes

- **Bulk operations**: Data is inserted in bulk for efficiency
- **Duplicate detection**: Unique constraints prevent duplicate observations
- **Progress tracking**: Minimizes redundant API calls
- **Parallel processing**: Can run multiple configurations concurrently
- **Error isolation**: Failure in one station doesn't affect others

## License

[Add your license here]
