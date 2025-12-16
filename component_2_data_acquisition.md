# Component 2: Data Acquisition and Preparation Services

## Overview
Build reliable, scheduled data ingestion services using Celery worker tasks to acquire observed and forecasted streamflow data from multiple sources (USGS, Environment Canada, NOAA). Implement Smart Append Logic to efficiently manage continuous data updates.

---

## Implementation Plan

### Phase 1: Project Structure Setup

#### 1.1 Extend Project Structure
```
streamflow_dataops/
├── src/
│   ├── acquisition/
│   │   ├── __init__.py
│   │   ├── tasks.py              # Celery tasks
│   │   ├── usgs_client.py        # USGS data retrieval
│   │   ├── canada_client.py      # Environment Canada client
│   │   ├── noaa_client.py        # NOAA NWM client
│   │   ├── data_processor.py     # Data transformation/validation
│   │   └── smart_append.py       # Smart append logic implementation
│   ├── celery_app/
│   │   ├── __init__.py
│   │   ├── celery.py             # Celery app configuration
│   │   └── beat_schedule.py      # Celery Beat schedule
│   └── config/
│       └── celery_config.py
├── requirements.txt
└── README_acquisition.md
```

#### 1.2 Install Additional Dependencies
Update `requirements.txt`:
```
celery==5.3.4
redis==5.0.1
dataretrieval==1.0.7  # USGS library
requests==2.31.0
pytz==2023.3
pandas==2.1.3
numpy==1.26.2
python-dateutil==2.8.2
tenacity==8.2.3  # For retry logic
```

---

### Phase 2: Celery Configuration

#### 2.1 Create Celery App (`src/celery_app/celery.py`)
```python
from celery import Celery
from celery.schedules import crontab
from src.config.settings import REDIS_URL

app = Celery('streamflow_acquisition')

# Configure Celery
app.config_from_object('src.config.celery_config')

# Auto-discover tasks
app.autodiscover_tasks(['src.acquisition'])

# Configure result backend
app.conf.update(
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3000,  # 50 minutes soft limit
)
```

#### 2.2 Celery Configuration (`src/config/celery_config.py`)
```python
from celery.schedules import crontab

# Broker settings
broker_url = 'redis://localhost:6379/0'
result_backend = 'redis://localhost:6379/0'

# Task settings
task_serializer = 'json'
result_serializer = 'json'
accept_content = ['json']
timezone = 'UTC'
enable_utc = True

# Beat schedule (will be dynamically updated by Django interface)
beat_schedule = {
    # Example static schedule - real schedules created dynamically
    'test-every-hour': {
        'task': 'src.acquisition.tasks.test_task',
        'schedule': crontab(minute=0),  # Every hour
    },
}
```

#### 2.3 Update Settings (`src/config/settings.py`)
```python
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./streamflow_dev.db')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# API Configuration
USGS_BASE_URL = 'https://waterservices.usgs.gov/nwis'
EC_BASE_URL = 'https://wateroffice.ec.gc.ca/services'
NOAA_NWM_BASE_URL = 'https://api.water.noaa.gov'

# Retry settings
MAX_RETRIES = 3
RETRY_BACKOFF = 300  # 5 minutes
```

---

### Phase 3: USGS Data Client

#### 3.1 Create USGS Client (`src/acquisition/usgs_client.py`)
```python
import dataretrieval.nwis as nwis
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class USGSClient:
    """Client for retrieving USGS streamflow data"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60)
    )
    def get_daily_mean(self, 
                       station_number: str, 
                       start_date: datetime, 
                       end_date: Optional[datetime] = None) -> List[Dict]:
        """
        Retrieve daily mean discharge data from USGS
        
        Args:
            station_number: USGS station ID (e.g., '01010000')
            start_date: Start date for data retrieval
            end_date: End date (defaults to today if None)
        
        Returns:
            List of dictionaries with discharge observations
        """
        if end_date is None:
            end_date = datetime.utcnow()
        
        try:
            self.logger.info(f"Fetching USGS daily mean data for {station_number} from {start_date} to {end_date}")
            
            # Use dataRetrieval library
            df, metadata = nwis.get_dv(
                sites=station_number,
                parameterCd='00060',  # Discharge parameter code
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d')
            )
            
            if df.empty:
                self.logger.warning(f"No data returned for {station_number}")
                return []
            
            # Transform to our format
            observations = []
            for index, row in df.iterrows():
                # Get the discharge value column (usually ends with '_00060_00003')
                discharge_col = [col for col in df.columns if col.endswith('_00060_00003')][0]
                quality_col = [col for col in df.columns if col.endswith('_00060_00003_cd')]
                
                obs = {
                    'observed_at': index,
                    'discharge': float(row[discharge_col]) if pd.notna(row[discharge_col]) else None,
                    'unit': 'cfs',  # USGS default unit
                    'type': 'daily_mean',
                    'quality_code': row[quality_col[0]] if quality_col and pd.notna(row[quality_col[0]]) else None
                }
                
                if obs['discharge'] is not None:
                    observations.append(obs)
            
            self.logger.info(f"Retrieved {len(observations)} records for {station_number}")
            return observations
            
        except Exception as e:
            self.logger.error(f"Error fetching USGS data for {station_number}: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60)
    )
    def get_instantaneous(self,
                          station_number: str,
                          start_date: datetime,
                          end_date: Optional[datetime] = None) -> List[Dict]:
        """
        Retrieve instantaneous (real-time) discharge data from USGS
        
        Args:
            station_number: USGS station ID
            start_date: Start date for data retrieval
            end_date: End date (defaults to now if None)
        
        Returns:
            List of dictionaries with discharge observations
        """
        if end_date is None:
            end_date = datetime.utcnow()
        
        try:
            self.logger.info(f"Fetching USGS instantaneous data for {station_number}")
            
            df, metadata = nwis.get_iv(
                sites=station_number,
                parameterCd='00060',
                start=start_date.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d')
            )
            
            if df.empty:
                self.logger.warning(f"No instantaneous data for {station_number}")
                return []
            
            observations = []
            for index, row in df.iterrows():
                discharge_col = [col for col in df.columns if '_00060' in col and not col.endswith('_cd')][0]
                quality_col = [col for col in df.columns if col.endswith('_cd')]
                
                obs = {
                    'observed_at': index,
                    'discharge': float(row[discharge_col]) if pd.notna(row[discharge_col]) else None,
                    'unit': 'cfs',
                    'type': 'realtime_15min',
                    'quality_code': row[quality_col[0]] if quality_col and pd.notna(row[quality_col[0]]) else None
                }
                
                if obs['discharge'] is not None:
                    observations.append(obs)
            
            self.logger.info(f"Retrieved {len(observations)} instantaneous records")
            return observations
            
        except Exception as e:
            self.logger.error(f"Error fetching instantaneous USGS data: {e}")
            raise
```

---

### Phase 4: Environment Canada Client

#### 4.1 Create EC Client (`src/acquisition/canada_client.py`)
```python
import requests
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional
import logging
import pytz
from io import StringIO
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class CanadaClient:
    """Client for retrieving Environment Canada streamflow data"""
    
    def __init__(self):
        self.base_url = "https://wateroffice.ec.gc.ca/services/real_time_data/csv/inline"
        self.logger = logging.getLogger(__name__)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60)
    )
    def get_realtime_data(self,
                          station_number: str,
                          start_date: datetime,
                          end_date: Optional[datetime] = None) -> List[Dict]:
        """
        Retrieve real-time discharge data from Environment Canada
        
        Args:
            station_number: EC station ID
            start_date: Start date for data retrieval
            end_date: End date (defaults to now if None)
        
        Returns:
            List of dictionaries with discharge observations
        """
        if end_date is None:
            end_date = datetime.utcnow()
        
        try:
            # Build request URL
            params = {
                'stations[]': station_number,
                'parameters[]': '47',  # Discharge parameter code
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d')
            }
            
            self.logger.info(f"Fetching EC data for {station_number}")
            
            response = requests.get(self.base_url, params=params, timeout=60)
            response.raise_for_status()
            
            # Parse CSV response
            df = pd.read_csv(StringIO(response.text))
            
            if df.empty:
                self.logger.warning(f"No data returned for EC station {station_number}")
                return []
            
            # Transform to our format
            observations = []
            for _, row in df.iterrows():
                # Convert from LST to UTC
                # EC data is in Local Standard Time
                local_tz = pytz.timezone('America/Toronto')  # Adjust based on station location
                observed_at_local = pd.to_datetime(row['Date'])
                observed_at_utc = local_tz.localize(observed_at_local).astimezone(pytz.UTC)
                
                obs = {
                    'observed_at': observed_at_utc,
                    'discharge': float(row['Value']) if pd.notna(row['Value']) else None,
                    'unit': 'cms',  # EC uses cubic meters per second
                    'type': 'realtime_15min',
                    'quality_code': row.get('Quality', None)
                }
                
                if obs['discharge'] is not None:
                    observations.append(obs)
            
            self.logger.info(f"Retrieved {len(observations)} EC records")
            return observations
            
        except Exception as e:
            self.logger.error(f"Error fetching EC data for {station_number}: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60)
    )
    def get_daily_mean(self,
                       station_number: str,
                       start_date: datetime,
                       end_date: Optional[datetime] = None) -> List[Dict]:
        """
        Retrieve daily mean discharge data from Environment Canada
        Similar implementation to get_realtime_data with different parameter
        """
        # Implementation similar to get_realtime_data
        # Use parameter code for daily means
        pass
```

---

### Phase 5: NOAA National Water Model Client

#### 5.1 Create NOAA Client (`src/acquisition/noaa_client.py`)
```python
import requests
from datetime import datetime
from typing import List, Dict, Optional
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class NOAAClient:
    """Client for retrieving NOAA National Water Model forecast data"""
    
    def __init__(self):
        self.base_url = "https://api.water.noaa.gov/nwps/v1"
        self.logger = logging.getLogger(__name__)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60)
    )
    def get_forecast(self,
                     hads_id: str,
                     forecast_type: str = 'short') -> Optional[Dict]:
        """
        Retrieve forecast data from NOAA NWM
        
        Args:
            hads_id: NOAA HADS station ID (NOT USGS ID - must be translated first)
            forecast_type: 'short' (18hr), 'medium' (10day), or 'long' (30day)
        
        Returns:
            Dictionary with forecast data
        """
        try:
            endpoint = f"{self.base_url}/gauges/{hads_id}/stageflow"
            
            params = {
                'forecast': forecast_type
            }
            
            self.logger.info(f"Fetching NOAA forecast for HADS ID {hads_id}")
            
            response = requests.get(endpoint, params=params, timeout=60)
            response.raise_for_status()
            
            data = response.json()
            
            if not data:
                self.logger.warning(f"No forecast data for HADS ID {hads_id}")
                return None
            
            # Extract forecast time series
            forecast_data = []
            if 'forecast' in data and 'data' in data['forecast']:
                for point in data['forecast']['data']:
                    forecast_data.append({
                        'date': point['validTime'],
                        'value': point['flow']  # Discharge value
                    })
            
            result = {
                'source': 'NOAA_NWM',
                'run_date': datetime.utcnow(),
                'data': forecast_data,
                'rmse': data.get('forecast', {}).get('rmse', None)
            }
            
            self.logger.info(f"Retrieved forecast with {len(forecast_data)} points")
            return result
            
        except Exception as e:
            self.logger.error(f"Error fetching NOAA forecast for {hads_id}: {e}")
            raise
```

---

### Phase 6: Smart Append Logic Implementation

#### 6.1 Create Smart Append Module (`src/acquisition/smart_append.py`)
```python
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from src.database.repositories import PullProgressRepository, PullConfigurationRepository
import logging

logger = logging.getLogger(__name__)

class SmartAppendLogic:
    """
    Implements the Smart Append Logic for determining data pull start dates
    
    Logic:
    - First pull: Use pullConfiguration.pull_start_date
    - Subsequent pulls: Use pullStationProgress.last_successful_pull_date
    - This ensures complete initial download, then efficient incremental updates
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.progress_repo = PullProgressRepository(db)
    
    def get_pull_start_date(self, 
                            config_id: int, 
                            station_number: str,
                            config_start_date: datetime) -> datetime:
        """
        Determine the start date for data pull based on Smart Append Logic
        
        Args:
            config_id: Pull configuration ID
            station_number: Station identifier
            config_start_date: The pull_start_date from configuration
        
        Returns:
            Start date to use for data pull request
        """
        # Check if we have previous progress for this station
        last_pull_date = self.progress_repo.get_last_pull_date(config_id, station_number)
        
        if last_pull_date is None:
            # First pull - use configuration start date
            logger.info(f"First pull for station {station_number} - using config start date: {config_start_date}")
            return config_start_date
        else:
            # Subsequent pull - use last successful pull date
            logger.info(f"Subsequent pull for station {station_number} - using last pull date: {last_pull_date}")
            return last_pull_date
    
    def update_pull_progress(self,
                            config_id: int,
                            station_number: str,
                            successful_pull_date: datetime):
        """
        Update progress after successful data pull
        
        Args:
            config_id: Pull configuration ID
            station_number: Station identifier
            successful_pull_date: The latest date successfully pulled
        """
        self.progress_repo.update_last_pull_date(
            config_id=config_id,
            station_number=station_number,
            pull_date=successful_pull_date
        )
        logger.info(f"Updated progress for station {station_number} to {successful_pull_date}")
```

---

### Phase 7: Data Processor

#### 7.1 Create Data Processor (`src/acquisition/data_processor.py`)
```python
from typing import List, Dict
from datetime import datetime
import logging
from sqlalchemy.orm import Session
from src.database.repositories import StationRepository, DischargeObservationRepository

logger = logging.getLogger(__name__)

class DataProcessor:
    """Process and validate raw data before database insertion"""
    
    def __init__(self, db: Session):
        self.db = db
        self.station_repo = StationRepository(db)
        self.obs_repo = DischargeObservationRepository(db)
    
    def process_observations(self,
                            station_number: str,
                            observations: List[Dict]) -> int:
        """
        Process and store discharge observations
        
        Args:
            station_number: Station identifier
            observations: List of observation dictionaries
        
        Returns:
            Count of successfully inserted records
        """
        # Get station from database
        station = self.station_repo.get_by_station_number(station_number)
        if not station:
            logger.error(f"Station {station_number} not found in database")
            return 0
        
        # Add station_id to each observation
        for obs in observations:
            obs['station_id'] = station.id
            
            # Ensure observed_at is datetime
            if not isinstance(obs['observed_at'], datetime):
                obs['observed_at'] = datetime.fromisoformat(str(obs['observed_at']))
        
        # Bulk insert with duplicate handling
        inserted_count = self.obs_repo.bulk_insert_ignore_duplicates(observations)
        
        logger.info(f"Inserted {inserted_count} observations for station {station_number}")
        return inserted_count
    
    def validate_observations(self, observations: List[Dict]) -> List[Dict]:
        """
        Validate observation data quality
        
        Checks:
        - Non-negative discharge values
        - Reasonable ranges
        - Required fields present
        """
        valid_observations = []
        
        for obs in observations:
            # Check required fields
            if not all(k in obs for k in ['observed_at', 'discharge', 'unit', 'type']):
                logger.warning(f"Missing required fields in observation: {obs}")
                continue
            
            # Check discharge value
            if obs['discharge'] < 0:
                logger.warning(f"Negative discharge value: {obs}")
                continue
            
            # Add more validation as needed
            valid_observations.append(obs)
        
        return valid_observations
```

---

### Phase 8: Celery Tasks Implementation

#### 8.1 Create Task Module (`src/acquisition/tasks.py`)
```python
from celery import Task
from datetime import datetime
import logging
from src.celery_app.celery import app
from src.database.connection import SessionLocal
from src.database.repositories import (
    PullConfigurationRepository, 
    StationMappingRepository,
    DataPullLogRepository
)
from src.acquisition.usgs_client import USGSClient
from src.acquisition.canada_client import CanadaClient
from src.acquisition.noaa_client import NOAAClient
from src.acquisition.smart_append import SmartAppendLogic
from src.acquisition.data_processor import DataProcessor

logger = logging.getLogger(__name__)

class DatabaseTask(Task):
    """Base task with database session"""
    _db = None
    
    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db
    
    def after_return(self, *args, **kwargs):
        if self._db is not None:
            self._db.close()


@app.task(base=DatabaseTask, bind=True)
def execute_pull_configuration(self, config_id: int):
    """
    Execute a data pull for a specific configuration
    
    Args:
        config_id: Pull configuration ID
    """
    db = SessionLocal()
    try:
        logger.info(f"Starting pull for configuration {config_id}")
        
        # Get configuration
        config_repo = PullConfigurationRepository(db)
        config = config_repo.get_by_id(config_id)
        
        if not config or not config.is_enabled:
            logger.warning(f"Configuration {config_id} not found or disabled")
            return
        
        # Create log entry
        log_repo = DataPullLogRepository(db)
        log = log_repo.create_log(config_id, 'running', datetime.utcnow())
        
        # Process each station in configuration
        total_records = 0
        smart_append = SmartAppendLogic(db)
        processor = DataProcessor(db)
        
        for config_station in config.configuration_stations:
            try:
                station_number = config_station.station_number
                
                # Determine start date using Smart Append Logic
                start_date = smart_append.get_pull_start_date(
                    config_id=config_id,
                    station_number=station_number,
                    config_start_date=config.pull_start_date
                )
                
                # Fetch data based on data type
                observations = []
                
                if config.data_type == 'daily_mean':
                    # USGS daily mean
                    client = USGSClient()
                    observations = client.get_daily_mean(station_number, start_date)
                
                elif config.data_type == 'realtime_15min':
                    # USGS instantaneous
                    client = USGSClient()
                    observations = client.get_instantaneous(station_number, start_date)
                
                # Validate and process observations
                valid_obs = processor.validate_observations(observations)
                inserted = processor.process_observations(station_number, valid_obs)
                total_records += inserted
                
                # Update progress
                if observations:
                    latest_date = max(obs['observed_at'] for obs in observations)
                    smart_append.update_pull_progress(config_id, station_number, latest_date)
                
                logger.info(f"Processed {inserted} records for station {station_number}")
                
            except Exception as e:
                logger.error(f"Error processing station {station_number}: {e}")
                continue
        
        # Update log with success
        log_repo.update_log(log.id, 'success', datetime.utcnow(), total_records)
        logger.info(f"Completed pull for configuration {config_id} - {total_records} records")
        
    except Exception as e:
        logger.error(f"Error in execute_pull_configuration: {e}")
        if 'log' in locals():
            log_repo.update_log(log.id, 'failed', datetime.utcnow(), error_message=str(e))
        raise
    finally:
        db.close()


@app.task(base=DatabaseTask, bind=True)
def fetch_noaa_forecast(self, station_number: str, station_agency: str = 'USGS'):
    """
    Fetch NOAA forecast for a station
    
    Args:
        station_number: Station ID (USGS or EC)
        station_agency: Source agency (USGS or EC)
    """
    db = SessionLocal()
    try:
        # Translate station ID to NOAA HADS ID
        mapping_repo = StationMappingRepository(db)
        hads_id = mapping_repo.get_mapping(
            source_agency=station_agency,
            source_id=station_number,
            target_agency='NOAA-HADS'
        )
        
        if not hads_id:
            logger.warning(f"No HADS mapping found for {station_agency} {station_number}")
            return
        
        # Fetch forecast
        noaa_client = NOAAClient()
        forecast_data = noaa_client.get_forecast(hads_id)
        
        if forecast_data:
            # Store in database
            # Implementation here...
            logger.info(f"Stored forecast for station {station_number}")
        
    except Exception as e:
        logger.error(f"Error fetching NOAA forecast: {e}")
        raise
    finally:
        db.close()


@app.task
def test_task():
    """Test task for debugging"""
    logger.info("Test task executed successfully")
    return "Task completed"
```

---

### Phase 9: Testing and Deployment

#### 9.1 Create Test Script (`tests/test_acquisition.py`)
```python
import pytest
from datetime import datetime, timedelta
from src.acquisition.usgs_client import USGSClient
from src.acquisition.smart_append import SmartAppendLogic

def test_usgs_client():
    """Test USGS data retrieval"""
    client = USGSClient()
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)
    
    # Test with a known active station
    observations = client.get_daily_mean('01646500', start_date, end_date)
    
    assert len(observations) > 0
    assert all('discharge' in obs for obs in observations)

def test_smart_append_first_pull(test_db):
    """Test Smart Append Logic for first pull"""
    smart_append = SmartAppendLogic(test_db)
    config_start = datetime(2020, 1, 1)
    
    # First pull should return config start date
    start_date = smart_append.get_pull_start_date(1, '01010000', config_start)
    
    assert start_date == config_start

# Add more tests...
```

#### 9.2 Running Celery Workers

**Start Redis (if not running):**
```bash
redis-server
```

**Start Celery Worker:**
```bash
celery -A src.celery_app.celery worker --loglevel=info
```

**Start Celery Beat (scheduler):**
```bash
celery -A src.celery_app.celery beat --loglevel=info
```

**Monitor Tasks:**
```bash
celery -A src.celery_app.celery events
```

Or use Flower for web-based monitoring:
```bash
pip install flower
celery -A src.celery_app.celery flower
```

---

## Implementation Checklist

- [ ] Phase 1: Extend project structure
- [ ] Phase 2: Configure Celery and Redis
- [ ] Phase 3: Implement USGS client
- [ ] Phase 4: Implement Environment Canada client
- [ ] Phase 5: Implement NOAA client
- [ ] Phase 6: Implement Smart Append Logic
- [ ] Phase 7: Create data processor
- [ ] Phase 8: Create Celery tasks
- [ ] Phase 9: Write tests and deploy workers
- [ ] Additional: Error handling and retry logic
- [ ] Additional: Logging and monitoring setup
- [ ] Additional: Rate limiting for API calls
- [ ] Additional: Data quality validation

---

## Key Design Decisions

1. **Celery + Redis**: Reliable task queue for scheduled data pulls
2. **Smart Append Logic**: Efficient incremental data updates using progress tracking
3. **Retry Logic**: Tenacity library for automatic retries with exponential backoff
4. **Station ID Mapping**: Dedicated repository for translating between agency IDs
5. **Data Validation**: Pre-insertion validation to ensure data quality
6. **Timezone Handling**: All timestamps converted to UTC before storage
7. **Modular Clients**: Separate client classes for each data source

---

## API Rate Limiting Considerations

- **USGS**: Generally no hard limits, but be respectful (~1 request/second)
- **Environment Canada**: May have rate limits, implement delays if needed
- **NOAA**: Check API documentation for rate limits

Implement rate limiting in clients if necessary:
```python
from time import sleep
import functools

def rate_limit(calls_per_second=1):
    min_interval = 1.0 / calls_per_second
    def decorator(func):
        last_called = [0.0]
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            wait_time = min_interval - elapsed
            if wait_time > 0:
                sleep(wait_time)
            result = func(*args, **kwargs)
            last_called[0] = time.time()
            return result
        return wrapper
    return decorator
```

---

## Next Steps

After completing this component:
1. Integrate with Component 1 (Database Layer) - DONE via repositories
2. Build Django interface (Component 3) to manage configurations
3. Implement monitoring and alerting for failed tasks
4. Add data quality reporting
5. Consider caching strategies for frequently accessed data
