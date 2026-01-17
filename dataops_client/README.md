# DataOps API Client

A Python client library for consuming the StreamFlow DataOps REST API. Provides easy access to station metadata, discharge observations, and data pull configuration management.

## Installation

```bash
# From within your project directory
pip install -e /path/to/streamflow-dataOps/dataops_client

# Or add to requirements.txt
-e /path/to/streamflow-dataOps/dataops_client
```

## Quick Start

```python
from dataops_client import DataOpsClient

# Initialize client
client = DataOpsClient(
    base_url="http://localhost:8000",
    api_token="your-jwt-token-here"  # Optional for read-only endpoints
)

# Get list of Colorado stations
stations = client.get_stations(state="CO", limit=10)
print(f"Found {stations.count} stations")

for station in stations.results:
    print(f"- {station.station_number}: {station.station_name}")

# Get discharge data for a specific station
from datetime import datetime, timedelta

end_date = datetime.now()
start_date = end_date - timedelta(days=30)

data = client.get_station_data(
    station_number="09070500",
    start_date=start_date,
    end_date=end_date,
    data_type="daily_mean"
)

print(f"Retrieved {len(data)} observations")
for obs in data[:5]:  # First 5 records
    print(f"  {obs.observed_at}: {obs.discharge_value} {obs.unit}")
```

## Configuration

### Environment Variables

The client can be configured using environment variables:

```bash
export DATAOPS_API_URL="https://api.dataops.example.com"
export DATAOPS_API_TOKEN="your-jwt-token"
export DATAOPS_API_TIMEOUT="60"
export DATAOPS_VERIFY_SSL="true"
export DATAOPS_CACHE_ENABLED="true"
export DATAOPS_CACHE_TTL="300"
```

Then initialize the client using defaults:

```python
from dataops_client.config import ClientConfig
from dataops_client import DataOpsClient

config = ClientConfig.from_env()
client = DataOpsClient(**config.to_dict())
```

### Configuration File

Create a `.env` file in your project root:

```ini
DATAOPS_API_URL=http://localhost:8000
DATAOPS_API_TOKEN=your-token-here
DATAOPS_CACHE_ENABLED=true
DATAOPS_CACHE_TTL=300
```

Load it using `python-dotenv`:

```python
from dotenv import load_dotenv
from dataops_client import DataOpsClient

load_dotenv()
client = DataOpsClient.from_env()
```

## Features

### ✅ Station Operations

#### List Stations
```python
# Get all active stations
stations = client.get_stations(is_active=True)

# Filter by state and agency
stations = client.get_stations(state="CO", agency="USGS", limit=50)

# Search by station number or name
stations = client.get_stations(search="Eagle River")

# Get specific page
stations = client.get_stations(limit=100, offset=200)
```

#### Get Single Station
```python
station = client.get_station("09070500")
print(f"Station: {station.station_name}")
print(f"Location: {station.latitude}, {station.longitude}")
print(f"HUC: {station.huc_code}")
```

#### Get Station Data
```python
# Get 30 days of daily mean discharge
data = client.get_station_data(
    station_number="09070500",
    start_date="2026-01-01",
    end_date="2026-01-31",
    data_type="daily_mean"
)

# Get real-time 15-minute data
data = client.get_station_data(
    station_number="09085000",
    start_date=datetime.now() - timedelta(days=7),
    end_date=datetime.now(),
    data_type="realtime_15min"
)

# Export to CSV format
csv_data = client.get_station_data(
    station_number="09070500",
    start_date="2026-01-01",
    end_date="2026-01-17",
    format="csv"
)
```

#### Get Station Statistics
```python
stats = client.get_station_statistics(
    station_number="09070500",
    start_date="2025-01-01",
    end_date="2025-12-31",
    aggregation="monthly"
)

print(f"Min: {stats['min']} cfs")
print(f"Max: {stats['max']} cfs")
print(f"Mean: {stats['mean']} cfs")
print(f"P50 (median): {stats['p50']} cfs")
```

### ✅ Configuration Management

#### List Configurations
```python
# Get all enabled configurations
configs = client.get_configurations(is_enabled=True)

for config in configs.results:
    print(f"{config.name}: {config.station_count} stations")

# Filter by data source
usgs_configs = client.get_configurations(data_source="USGS")
```

#### Get Configuration Details
```python
config = client.get_configuration(config_id=3)
print(f"Configuration: {config['name']}")
print(f"Stations: {len(config['stations'])}")
print(f"Last run: {config['last_run_at']}")
```

#### Execute Configuration
```python
# Trigger immediate data pull
result = client.execute_configuration(config_id=3)
print(f"Task ID: {result['task_id']}")
print(f"Status: {result['status']}")
```

### ✅ Execution Logs

```python
# Get recent logs
logs = client.get_logs(limit=20)

# Filter by configuration and status
logs = client.get_logs(
    configuration_id=3,
    status="success",
    limit=50
)

for log in logs.results:
    print(f"{log['start_time']}: {log['status']} - {log['records_processed']} records")
```

### ✅ Batch Operations

#### Query Multiple Stations
```python
stations = ["09070500", "09085000", "09041090"]

data = client.batch_query_data(
    station_numbers=stations,
    start_date="2026-01-01",
    end_date="2026-01-17",
    data_type="daily_mean"
)

for station_num, observations in data.items():
    print(f"{station_num}: {len(observations)} observations")
```

## Advanced Features

### Caching

The client includes automatic response caching to reduce API load:

```python
# Cache is enabled by default (5 minute TTL)
client = DataOpsClient(
    base_url="http://localhost:8000",
    cache_enabled=True,
    cache_ttl=300  # 5 minutes
)

# First request hits API
stations = client.get_stations(state="CO")

# Second request within 5 minutes uses cache
stations = client.get_stations(state="CO")  # From cache

# Clear cache manually
client.clear_cache()

# Disable cache for specific request
data = client.get_station_data(
    "09070500",
    start_date="2026-01-01",
    end_date="2026-01-17",
    use_cache=False  # Always fetch fresh data
)
```

### Retry Logic

The client automatically retries failed requests with exponential backoff:

```python
# Default: 3 retries with 2x backoff (2s, 4s, 8s)
client = DataOpsClient(base_url="http://localhost:8000")

# Custom retry configuration
from dataops_client.client import retry_on_failure

@retry_on_failure(max_retries=5, backoff_factor=3)
def my_api_call():
    return client.get_stations()
```

### Error Handling

```python
from dataops_client.exceptions import (
    NotFoundError,
    ValidationError,
    RateLimitError,
    AuthenticationError,
)

try:
    station = client.get_station("INVALID123")
except NotFoundError:
    print("Station not found")
except ValidationError as e:
    print(f"Invalid request: {e}")
except RateLimitError:
    print("Rate limit exceeded, try again later")
except AuthenticationError:
    print("Authentication failed")
```

### Pagination

```python
# Get first page
page1 = client.get_stations(limit=100, offset=0)
print(f"Total stations: {page1.count}")
print(f"Page 1: {len(page1.results)} stations")

# Get next page
page2 = client.get_stations(limit=100, offset=100)

# Iterate through all pages
offset = 0
limit = 100
all_stations = []

while True:
    page = client.get_stations(limit=limit, offset=offset)
    all_stations.extend(page.results)
    
    if not page.next:
        break
    
    offset += limit

print(f"Retrieved {len(all_stations)} total stations")
```

## Integration Examples

### Dashboard Integration

```python
# dashboard/dataops_adapter.py
import os
from dataops_client import DataOpsClient

# Feature flag to switch between local SQLite and DataOps API
USE_DATAOPS_API = os.getenv('USE_DATAOPS_API', 'false').lower() == 'true'

class DataAdapter:
    """Adapter to switch between local database and DataOps API."""
    
    def __init__(self):
        if USE_DATAOPS_API:
            self.client = DataOpsClient(
                base_url=os.getenv('DATAOPS_API_URL'),
                api_token=os.getenv('DATAOPS_API_TOKEN')
            )
            self.use_api = True
        else:
            from .local_db import LocalDatabase
            self.db = LocalDatabase()
            self.use_api = False
    
    def get_station_data(self, station_number, start_date, end_date):
        """Get discharge data - from API or local DB."""
        if self.use_api:
            return self.client.get_station_data(
                station_number, start_date, end_date
            )
        else:
            return self.db.query_data(station_number, start_date, end_date)
    
    def get_stations(self, **filters):
        """Get list of stations."""
        if self.use_api:
            return self.client.get_stations(**filters)
        else:
            return self.db.query_stations(**filters)

# Usage in dashboard
adapter = DataAdapter()
data = adapter.get_station_data("09070500", "2026-01-01", "2026-01-17")
```

### Data Analysis Example

```python
import pandas as pd
from dataops_client import DataOpsClient

client = DataOpsClient(base_url="http://localhost:8000")

# Get data for analysis
observations = client.get_station_data(
    station_number="09070500",
    start_date="2025-01-01",
    end_date="2025-12-31",
    data_type="daily_mean"
)

# Convert to pandas DataFrame
df = pd.DataFrame([
    {
        'date': obs.observed_at,
        'discharge': obs.discharge_value,
        'quality': obs.quality_code
    }
    for obs in observations
])

# Analysis
print(f"Records: {len(df)}")
print(f"Mean discharge: {df['discharge'].mean():.2f} cfs")
print(f"Max discharge: {df['discharge'].max():.2f} cfs")
print(f"Missing data: {df['discharge'].isna().sum()} days")

# Seasonal analysis
df['month'] = df['date'].dt.month
monthly = df.groupby('month')['discharge'].agg(['mean', 'min', 'max'])
print(monthly)
```

## Troubleshooting

### Connection Issues

```python
# Check API health
health = client.health_check()
print(health)

# Test with explicit timeout
client = DataOpsClient(
    base_url="http://localhost:8000",
    timeout=120  # Increase timeout for slow connections
)
```

### SSL Certificate Errors

```python
# Disable SSL verification (not recommended for production)
client = DataOpsClient(
    base_url="https://api.dataops.example.com",
    verify_ssl=False
)
```

### Rate Limiting

```python
import time

# Add delays between requests
stations = ["09070500", "09085000", "09041090"]

data = {}
for station_num in stations:
    data[station_num] = client.get_station_data(
        station_num, "2026-01-01", "2026-01-17"
    )
    time.sleep(0.5)  # 500ms delay between requests
```

## API Reference

See the [API Documentation](http://localhost:8000/api/docs/) for complete endpoint details.

## License

MIT License - see LICENSE file for details.
