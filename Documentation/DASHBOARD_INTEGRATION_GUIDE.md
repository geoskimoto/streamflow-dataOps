# External Application Integration Guide

**StreamFlow DataOps API Integration**  
**Version:** 2.0  
**Date:** February 5, 2026  
**Status:** Production Ready

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Connection Methods](#connection-methods)
4. [API Endpoints](#api-endpoints)
5. [Authentication](#authentication)
6. [Python Client Library](#python-client-library)
7. [Direct HTTP/REST Integration](#direct-httprest-integration)
8. [Data Export Options](#data-export-options)
9. [Adapter Pattern for Existing Applications](#adapter-pattern)
10. [Performance & Caching](#performance--caching)
11. [Error Handling](#error-handling)
12. [Troubleshooting](#troubleshooting)
13. [Examples](#examples)

---

## Overview

This guide shows you how to connect **any external application** (dashboards, analysis tools, web apps, mobile apps, etc.) to the StreamFlow DataOps system. The system provides a REST API for accessing streamflow data from multiple sources (USGS, Environment Canada, NOAA) through a single unified interface.

### What This System Provides

- **Unified Data Access**: Query 5,394+ USGS stations across Western US (HUC 14-18) through one API
- **Multi-Source Integration**: USGS, Environment Canada, and NOAA data sources
- **Automated Updates**: Background Celery workers keep data current
- **Multiple Data Types**: Daily mean, real-time 15-minute, forecasts
- **Flexible Export**: JSON, CSV, or Python objects
- **No Authentication Required**: Read-only access is open by default (configurable)
- **RESTful Design**: Standard HTTP methods, consistent URL patterns

### System Architecture

```
Your Application                    DataOps System
┌──────────────────────┐           ┌────────────────────────┐
│  Web Dashboard       │           │  Django REST API       │
│  Mobile App          │  ──HTTP─→ │  - 24 Endpoints        │
│  Analysis Tool       │           │  - JSON/CSV Export     │
│  Desktop Software    │           │  - OpenAPI/Swagger     │
│  Python Script       │           │                        │
└──────────────────────┘           │  PostgreSQL Database   │
                                   │  - 2.5M+ Observations  │
     OR                            │  - 5,394 Stations      │
                                   │                        │
┌──────────────────────┐           │  Celery Workers        │
│  Python Application  │           │  - Auto Data Updates   │
│  + DataOps Client    │  ──API─→  │  - Multi-Source Pulls  │
│  (Recommended)       │           │  - Background Tasks    │
└──────────────────────┘           └────────────────────────┘
```

### Why Use This System?

- **No Data Management**: Let DataOps handle collection, validation, and storage
- **Multiple Sources**: USGS, Environment Canada, NOAA in one place
- **Always Current**: Automated updates keep data fresh
- **Production Ready**: 2.5M observations, battle-tested, optimized queries
- **Easy Integration**: RESTful API, Python client, or direct HTTP
- **Flexible Export**: JSON for apps, CSV for analysis, Python objects for scripts

---

## Quick Start

### 1. Check if API is Running

```bash
# Test the API
curl http://localhost:8000/api/v1/stations/?limit=1

# Or visit in browser
open http://localhost:8000/api/docs/
```

### 2. Choose Your Integration Method

**Option A: Python Client (Recommended)**
```bash
pip install -e /path/to/streamflow-dataOps/dataops_client
```

**Option B: Direct HTTP/REST**
- Use any HTTP library (requests, axios, fetch, etc.)
- No installation needed

### 3. Get Data in 3 Lines

**Python Client:**
```python
from dataops_client import DataOpsClient

client = DataOpsClient(base_url="http://localhost:8000")
stations = client.get_stations(state="CO", limit=10)
print(f"Found {stations.count} Colorado stations")
```

**Direct HTTP (cURL):**
```bash
curl "http://localhost:8000/api/v1/stations/?state=CO&limit=10"
```

**JavaScript/Web:**
```javascript
fetch('http://localhost:8000/api/v1/stations/?state=CO&limit=10')
  .then(res => res.json())
  .then(data => console.log(`Found ${data.count} stations`));
```

---

## Connection Methods

### Method 1: Python Client Library (Easiest)

**Best for:** Python applications, data science, automation scripts

**Pros:**
- Type hints and autocomplete
- Built-in error handling
- Automatic pagination
- Response caching
- Model objects (not raw JSON)

**Setup:**
```bash
# Install from local path
pip install -e /path/to/streamflow-dataOps/dataops_client

# Or add to requirements.txt
-e git+https://github.com/yourorg/streamflow-dataOps.git#egg=dataops-client&subdirectory=dataops_client
```

**Usage:**
```python
from dataops_client import DataOpsClient

client = DataOpsClient(base_url="http://localhost:8000")

# Get stations
stations = client.get_stations(state="CO", agency="USGS", limit=50)

# Get data for a station
data = client.get_station_data(
    station_number="09070500",
    start_date="2026-01-01",
    end_date="2026-02-05"
)

# Get statistics
stats = client.get_station_statistics(
    station_number="09070500",
    start_date="2026-01-01",
    end_date="2026-02-05"
)
```

### Method 2: Direct HTTP/REST

**Best for:** Non-Python apps, web frontends, mobile apps, any language

**Pros:**
- No dependencies
- Works with any HTTP library
- Language agnostic
- Simple and direct

**Base URL:**
```
http://localhost:8000/api/v1/
```

**Example Endpoints:**
```
GET /api/v1/stations/                    # List stations
GET /api/v1/stations/09070500/           # Get specific station
GET /api/v1/stations/09070500/data/      # Get discharge data
GET /api/v1/stations/09070500/statistics/ # Get statistics
GET /api/v1/observations/discharge/      # Query all observations
```

**JavaScript Example:**
```javascript
const API_BASE = 'http://localhost:8000/api/v1';

async function getStations(state) {
  const response = await fetch(`${API_BASE}/stations/?state=${state}`);
  return await response.json();
}

async function getStationData(stationNumber, startDate, endDate) {
  const url = `${API_BASE}/stations/${stationNumber}/data/?` +
    `start_date=${startDate}&end_date=${endDate}`;
  const response = await fetch(url);
  return await response.json();
}
```

**Python requests Example:**
```python
import requests

API_BASE = "http://localhost:8000/api/v1"

# Get Colorado stations
response = requests.get(f"{API_BASE}/stations/", params={
    "state": "CO",
    "limit": 50
})
stations = response.json()

# Get discharge data
response = requests.get(
    f"{API_BASE}/stations/09070500/data/",
    params={
        "start_date": "2026-01-01",
        "end_date": "2026-02-05",
        "data_type": "daily_mean"
    }
)
data = response.json()
```

### Method 3: Adapter Pattern (For Legacy Applications)

**Best for:** Existing applications migrating from local database

See [Adapter Pattern Section](#adapter-pattern) below for full details.

---

## API Endpoints

### Base URL
```
http://localhost:8000/api/v1/
```

### Interactive Documentation
```
http://localhost:8000/api/docs/       # Swagger UI (interactive)
http://localhost:8000/api/redoc/      # ReDoc (clean docs)
http://localhost:8000/api/schema/     # OpenAPI JSON schema
```

### Core Endpoints

#### Stations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/stations/` | GET | List all stations with filtering |
| `/stations/{station_number}/` | GET | Get specific station details |
| `/stations/{station_number}/data/` | GET | Get discharge observations |
| `/stations/{station_number}/statistics/` | GET | Get statistical summary |
| `/stations/batch/` | POST | Batch query multiple stations |

**Common Query Parameters:**
- `state` - Filter by state code (CO, CA, OR, WA, etc.)
- `agency` - Filter by agency (USGS, EC, NOAA)
- `is_active` - Filter by active status (true/false)
- `search` - Search in station number or name
- `huc_code` - Filter by Hydrologic Unit Code
- `limit` - Results per page (default 100, max 1000)
- `offset` - Pagination offset

#### Discharge Observations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/observations/discharge/` | GET | Query discharge observations |
| `/observations/discharge/export/` | GET | Export to CSV format |
| `/observations/discharge/aggregate/` | GET | Aggregate by time period |

**Query Parameters:**
- `station_number` - Filter by station
- `start_date` - Start date (YYYY-MM-DD)
- `end_date` - End date (YYYY-MM-DD)
- `data_type` - Type (daily_mean, realtime_15min, forecast_short, forecast_medium)
- `min_discharge` / `max_discharge` - Value filters
- `quality_code` - Filter by quality flag

#### Pull Configurations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/configurations/` | GET | List data pull configurations |
| `/configurations/{id}/` | GET | Get specific configuration |
| `/configurations/{id}/trigger/` | POST | Manually trigger data pull |

#### Data Pull Logs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/logs/` | GET | List data pull execution logs |
| `/logs/{id}/` | GET | Get specific log details |
| `/logs/recent/` | GET | Get recent pull activity |

---

## Authentication

### Current Configuration

**Read-Only Access: No Authentication Required**

The API is currently configured with `AllowAny` permission for all endpoints, meaning:
- ✅ You can query data without authentication
- ✅ No API token needed
- ✅ Simple HTTP requests work immediately

**Note:** Write operations (POST, PUT, DELETE) are restricted to Django admin users via session authentication.

### For Production (Optional)

If deploying to production, you may want to enable JWT token authentication:

1. **Install JWT package:**
```bash
pip install djangorestframework-simplejwt
```

2. **Update settings.py:**
```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}
```

3. **Get token:**
```bash
curl -X POST http://localhost:8000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"your_user","password":"your_pass"}'
```

4. **Use token:**
```bash
curl http://localhost:8000/api/v1/stations/ \
  -H "Authorization: Bearer YOUR_TOKEN_HERE"
```

---

## Python Client Library

### Installation

```bash
# From local repository
pip install -e /path/to/streamflow-dataOps/dataops_client

# From requirements.txt
echo "-e /path/to/streamflow-dataOps/dataops_client" >> requirements.txt
pip install -r requirements.txt
```

### Configuration

**Option 1: Direct initialization**
```python
from dataops_client import DataOpsClient

client = DataOpsClient(
    base_url="http://localhost:8000",
    api_token=None,  # Not needed for read-only
    timeout=60,
    verify_ssl=True,
    cache_enabled=True,
    cache_ttl=300  # 5 minutes
)
```

**Option 2: Environment variables**
```bash
# .env file
DATAOPS_API_URL=http://localhost:8000
DATAOPS_API_TOKEN=  # Leave empty for no auth
DATAOPS_CACHE_ENABLED=true
DATAOPS_CACHE_TTL=300
```

```python
from dotenv import load_dotenv
from dataops_client import DataOpsClient

load_dotenv()
client = DataOpsClient.from_env()
```

### Core Methods

#### Get Stations
```python
# List all active Colorado USGS stations
stations = client.get_stations(
    state="CO",
    agency="USGS",
    is_active=True,
    limit=100
)

print(f"Found {stations.count} stations")
for station in stations.results:
    print(f"{station.station_number}: {station.station_name}")
```

#### Get Single Station
```python
station = client.get_station("09070500")
print(f"Name: {station.station_name}")
print(f"Location: ({station.latitude}, {station.longitude})")
print(f"HUC: {station.huc_code}")
print(f"State: {station.state_code}")
```

#### Get Discharge Data
```python
from datetime import datetime, timedelta

# Get last 30 days
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

data = client.get_station_data(
    station_number="09070500",
    start_date=start_date,
    end_date=end_date,
    data_type="daily_mean"
)

print(f"Retrieved {len(data)} observations")
for obs in data[:5]:
    print(f"{obs.observed_at}: {obs.discharge_value} {obs.unit}")
```

#### Get Statistics
```python
stats = client.get_station_statistics(
    station_number="09070500",
    start_date="2026-01-01",
    end_date="2026-02-05"
)

print(f"Count: {stats['count']}")
print(f"Mean: {stats['mean']:.2f} cfs")
print(f"Range: {stats['min']:.2f} - {stats['max']:.2f} cfs")
print(f"Median: {stats['median']:.2f} cfs")
```

#### Export to CSV
```python
csv_data = client.get_station_data(
    station_number="09070500",
    start_date="2026-01-01",
    end_date="2026-02-05",
    format="csv"
)

# Save to file
with open("discharge_data.csv", "w") as f:
    f.write(csv_data)
```

#### Convert to Pandas
```python
import pandas as pd

data = client.get_station_data(
    station_number="09070500",
    start_date="2026-01-01",
    end_date="2026-02-05"
)

# Convert to DataFrame
df = pd.DataFrame([
    {
        'date': obs.observed_at,
        'discharge': obs.discharge_value,
        'unit': obs.unit,
        'quality': obs.quality_code
    }
    for obs in data
])

df['date'] = pd.to_datetime(df['date'])
df = df.set_index('date')
```

---

## Direct HTTP/REST Integration

### Python with requests

```python
import requests
from datetime import datetime, timedelta

API_BASE = "http://localhost:8000/api/v1"

import requests
from datetime import datetime, timedelta

API_BASE = "http://localhost:8000/api/v1"

def get_stations(state=None, agency=None, limit=100):
    """Get list of stations."""
    params = {"limit": limit}
    if state:
        params["state"] = state
    if agency:
        params["agency"] = agency
    
    response = requests.get(f"{API_BASE}/stations/", params=params)
    response.raise_for_status()
    return response.json()

def get_station_data(station_number, start_date, end_date, data_type="daily_mean"):
    """Get discharge observations for a station."""
    params = {
        "start_date": start_date.strftime("%Y-%m-%d") if isinstance(start_date, datetime) else start_date,
        "end_date": end_date.strftime("%Y-%m-%d") if isinstance(end_date, datetime) else end_date,
        "data_type": data_type
    }
    
    response = requests.get(
        f"{API_BASE}/stations/{station_number}/data/",
        params=params
    )
    response.raise_for_status()
    return response.json()

def get_station_statistics(station_number, start_date, end_date):
    """Get statistical summary for a station."""
    params = {
        "start_date": start_date.strftime("%Y-%m-%d") if isinstance(start_date, datetime) else start_date,
        "end_date": end_date.strftime("%Y-%m-%d") if isinstance(end_date, datetime) else end_date
    }
    
    response = requests.get(
        f"{API_BASE}/stations/{station_number}/statistics/",
        params=params
    )
    response.raise_for_status()
    return response.json()

# Example usage
if __name__ == "__main__":
    # Get Colorado stations
    result = get_stations(state="CO", limit=10)
    print(f"Found {result['count']} stations")
    
    for station in result['results']:
        print(f"  {station['station_number']}: {station['station_name']}")
    
    # Get discharge data
    end = datetime.now()
    start = end - timedelta(days=30)
    data = get_station_data("09070500", start, end)
    print(f"\nRetrieved {len(data)} observations")
```

### JavaScript/TypeScript

```javascript
const API_BASE = 'http://localhost:8000/api/v1';

// Get stations
async function getStations(params = {}) {
  const queryString = new URLSearchParams(params).toString();
  const response = await fetch(`${API_BASE}/stations/?${queryString}`);
  
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  
  return await response.json();
}

// Get station data
async function getStationData(stationNumber, startDate, endDate, dataType = 'daily_mean') {
  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate,
    data_type: dataType
  });
  
  const response = await fetch(
    `${API_BASE}/stations/${stationNumber}/data/?${params}`
  );
  
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  
  return await response.json();
}

// Get statistics
async function getStationStatistics(stationNumber, startDate, endDate) {
  const params = new URLSearchParams({
    start_date: startDate,
    end_date: endDate
  });
  
  const response = await fetch(
    `${API_BASE}/stations/${stationNumber}/statistics/?${params}`
  );
  
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  
  return await response.json();
}

// Example usage
(async () => {
  try {
    // Get Colorado stations
    const stations = await getStations({ state: 'CO', limit: 10 });
    console.log(`Found ${stations.count} stations`);
    
    // Get discharge data
    const data = await getStationData(
      '09070500',
      '2026-01-01',
      '2026-02-05'
    );
    console.log(`Retrieved ${data.length} observations`);
    
  } catch (error) {
    console.error('API Error:', error.message);
  }
})();
```

### R Language

```r
library(httr)
library(jsonlite)

API_BASE <- "http://localhost:8000/api/v1"

# Get stations
get_stations <- function(state = NULL, agency = NULL, limit = 100) {
  params <- list(limit = limit)
  if (!is.null(state)) params$state <- state
  if (!is.null(agency)) params$agency <- agency
  
  response <- GET(
    paste0(API_BASE, "/stations/"),
    query = params
  )
  
  stop_for_status(response)
  content(response, as = "parsed")
}

# Get station data
get_station_data <- function(station_number, start_date, end_date, data_type = "daily_mean") {
  response <- GET(
    paste0(API_BASE, "/stations/", station_number, "/data/"),
    query = list(
      start_date = start_date,
      end_date = end_date,
      data_type = data_type
    )
  )
  
  stop_for_status(response)
  content(response, as = "parsed")
}

# Example usage
stations <- get_stations(state = "CO", limit = 10)
cat(sprintf("Found %d stations\n", stations$count))

data <- get_station_data("09070500", "2026-01-01", "2026-02-05")
cat(sprintf("Retrieved %d observations\n", length(data)))
```

### cURL (Command Line)

```bash
# Get Colorado stations
curl "http://localhost:8000/api/v1/stations/?state=CO&limit=10" | jq .

# Get specific station
curl "http://localhost:8000/api/v1/stations/09070500/" | jq .

# Get discharge data
curl "http://localhost:8000/api/v1/stations/09070500/data/?start_date=2026-01-01&end_date=2026-02-05" | jq .

# Get statistics
curl "http://localhost:8000/api/v1/stations/09070500/statistics/?start_date=2026-01-01&end_date=2026-02-05" | jq .

# Export to CSV
curl "http://localhost:8000/api/v1/stations/09070500/data/?start_date=2026-01-01&end_date=2026-02-05&format=csv" > data.csv
```

---

## Data Export Options

### JSON (Default)

**Best for:** Web apps, APIs, programmatic access

```python
import requests

response = requests.get(
    "http://localhost:8000/api/v1/stations/09070500/data/",
    params={"start_date": "2026-01-01", "end_date": "2026-02-05"}
)
data = response.json()  # Returns list of dicts
```

**Response Structure:**
```json
[
  {
    "id": 123456,
    "station_number": "09070500",
    "observed_at": "2026-01-01T00:00:00Z",
    "discharge_value": 1234.5,
    "unit": "cfs",
    "data_type": "daily_mean",
    "quality_code": "A",
    "data_source": "USGS"
  },
  ...
]
```

### CSV Export

**Best for:** Excel, data analysis, spreadsheets

```bash
# Download CSV
curl "http://localhost:8000/api/v1/stations/09070500/data/?start_date=2026-01-01&end_date=2026-02-05&format=csv" > discharge.csv
```

```python
import requests

response = requests.get(
    "http://localhost:8000/api/v1/stations/09070500/data/",
    params={
        "start_date": "2026-01-01",
        "end_date": "2026-02-05",
        "format": "csv"
    }
)

# Save to file
with open("discharge_data.csv", "w") as f:
    f.write(response.text)

# Or load directly into pandas
import pandas as pd
from io import StringIO

df = pd.read_csv(StringIO(response.text))
```

### Pandas DataFrame

**Best for:** Python data analysis

```python
import pandas as pd
import requests

response = requests.get(
    "http://localhost:8000/api/v1/stations/09070500/data/",
    params={"start_date": "2026-01-01", "end_date": "2026-02-05"}
)
data = response.json()

# Convert to DataFrame
df = pd.DataFrame(data)
df['observed_at'] = pd.to_datetime(df['observed_at'])
df = df.set_index('observed_at')

# Now you can analyze
print(df.describe())
df.plot(y='discharge_value')
```

---

## Adapter Pattern

### For Existing Applications with Local Database

If you have an existing application using a local database and want to gradually migrate to the DataOps API, use an adapter pattern:

### Environment Configuration

**.env file:**
```ini
# Feature flag to switch between local DB and API
USE_DATAOPS_API=false  # Start with false, switch to true after testing

# API configuration (only used when USE_DATAOPS_API=true)
DATAOPS_API_URL=http://localhost:8000
DATAOPS_CACHE_ENABLED=true
DATAOPS_CACHE_TTL=300
```

### Adapter Implementation

```python
"""
Data Adapter for StreamFlow Dashboard

Provides unified interface to switch between local database and DataOps API.
"""

import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import pandas as pd


class DataAdapter:
    """
    Adapter to switch between local database and DataOps API.
    
    Usage:
        adapter = DataAdapter()
        stations = adapter.get_stations(state='CO')
        data = adapter.get_station_data('09070500', '2026-01-01', '2026-01-17')
    """
    
    def __init__(self):
        """Initialize adapter based on USE_DATAOPS_API flag."""
        self.use_api = os.getenv('USE_DATAOPS_API', 'false').lower() == 'true'
        
        if self.use_api:
            from dataops_client import DataOpsClient
            self.client = DataOpsClient(
                base_url=os.getenv('DATAOPS_API_URL', 'http://localhost:8000'),
                api_token=os.getenv('DATAOPS_API_TOKEN'),
                cache_enabled=os.getenv('DATAOPS_CACHE_ENABLED', 'true').lower() == 'true',
                cache_ttl=int(os.getenv('DATAOPS_CACHE_TTL', '300'))
            )
            print("✓ DataAdapter: Using DataOps API")
        else:
            # Import local database module
            from .local_database import LocalDatabase  # Your existing DB code
            self.db = LocalDatabase()
            print("✓ DataAdapter: Using local database")
    
    def get_stations(
        self,
        state: Optional[str] = None,
        agency: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """
        Get list of stations.
        
        Args:
            state: Filter by state code (e.g., 'CO', 'CA')
            agency: Filter by agency (USGS, EC, NOAA)
            is_active: Filter by active status
            search: Search in station number or name
            limit: Maximum results
        
        Returns:
            DataFrame with station metadata
        """
        if self.use_api:
            # Use DataOps API
            response = self.client.get_stations(
                state=state,
                agency=agency,
                is_active=is_active,
                search=search,
                limit=limit
            )
            
            # Convert to DataFrame
            stations = []
            for station in response.results:
                stations.append({
                    'station_number': station.station_number,
                    'name': station.name,
                    'agency': station.agency,
                    'latitude': float(station.latitude) if station.latitude else None,
                    'longitude': float(station.longitude) if station.longitude else None,
                    'state': station.state_code,
                    'huc_code': station.huc_code,
                    'is_active': station.is_active,
                })
            
            return pd.DataFrame(stations)
        else:
            # Use local database
            return self.db.query_stations(
                state=state,
                agency=agency,
                is_active=is_active,
                search=search,
                limit=limit
            )
    
    def get_station_data(
        self,
        station_number: str,
        start_date: str,
        end_date: str,
        data_type: str = 'daily_mean'
    ) -> pd.DataFrame:
        """
        Get discharge observations for a station.
        
        Args:
            station_number: Station identifier (e.g., '09070500')
            start_date: Start date ('YYYY-MM-DD')
            end_date: End date ('YYYY-MM-DD')
            data_type: Type of data (daily_mean, realtime_15min)
        
        Returns:
            DataFrame with discharge observations
        """
        if self.use_api:
            # Use DataOps API
            observations = self.client.get_station_data(
                station_number=station_number,
                start_date=start_date,
                end_date=end_date,
                data_type=data_type
            )
            
            # Convert to DataFrame
            data = []
            for obs in observations:
                data.append({
                    'date': obs.observed_at,
                    'station_number': obs.station_number,
                    'discharge': obs.discharge_value,
                    'unit': obs.unit,
                    'quality': obs.quality_code,
                    'type': obs.data_type
                })
            
            df = pd.DataFrame(data)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
            return df
        else:
            # Use local database
            return self.db.query_discharge_data(
                station_number=station_number,
                start_date=start_date,
                end_date=end_date,
                data_type=data_type
            )
    
    def get_station_info(self, station_number: str) -> Dict[str, Any]:
        """
        Get detailed information for a single station.
        
        Args:
            station_number: Station identifier
        
        Returns:
            Dictionary with station details
        """
        if self.use_api:
            station = self.client.get_station(station_number)
            return {
                'station_number': station.station_number,
                'name': station.name,
                'agency': station.agency,
                'latitude': float(station.latitude) if station.latitude else None,
                'longitude': float(station.longitude) if station.longitude else None,
                'state': station.state_code,
                'huc_code': station.huc_code,
                'basin_name': station.basin_name,
                'is_active': station.is_active,
                'last_observation_date': station.last_observation_date,
            }
        else:
            return self.db.get_station_by_number(station_number)
    
    def get_station_statistics(
        self,
        station_number: str,
        start_date: str,
        end_date: str
    ) -> Dict[str, float]:
        """
        Get statistical summary for a station.
        
        Args:
            station_number: Station identifier
            start_date: Start date
            end_date: End date
        
        Returns:
            Dictionary with min, max, mean, percentiles
        """
        if self.use_api:
            return self.client.get_station_statistics(
                station_number=station_number,
                start_date=start_date,
                end_date=end_date
            )
        else:
            # Calculate from local data
            df = self.db.query_discharge_data(
                station_number, start_date, end_date
            )
            
            if df.empty:
                return {}
            
            return {
                'count': len(df),
                'min': float(df['discharge'].min()),
                'max': float(df['discharge'].max()),
                'mean': float(df['discharge'].mean()),
                'median': float(df['discharge'].median()),
                'std': float(df['discharge'].std()),
            }
    
    def batch_query_stations(
        self,
        station_numbers: List[str],
        start_date: str,
        end_date: str
    ) -> Dict[str, pd.DataFrame]:
        """
        Query data for multiple stations.
        
        Args:
            station_numbers: List of station identifiers
            start_date: Start date
            end_date: End date
        
        Returns:
            Dictionary mapping station_number to DataFrame
        """
        if self.use_api:
            try:
                # Try batch endpoint if available
                result = self.client.batch_query_data(
                    station_numbers=station_numbers,
                    start_date=start_date,
                    end_date=end_date
                )
                
                # Convert to DataFrames
                return {
                    station_num: pd.DataFrame([
                        {
                            'date': obs.observed_at,
                            'discharge': obs.discharge_value,
                            'unit': obs.unit,
                            'quality': obs.quality_code
                        }
                        for obs in observations
                    ])
                    for station_num, observations in result.items()
                }
            except Exception:
                # Fallback: query individually
                result = {}
                for station_num in station_numbers:
                    result[station_num] = self.get_station_data(
                        station_num, start_date, end_date
                    )
                return result
        else:
            # Query from local database
            result = {}
            for station_num in station_numbers:
                result[station_num] = self.db.query_discharge_data(
                    station_num, start_date, end_date
                )
            return result
    
    def clear_cache(self):
        """Clear any cached data."""
        if self.use_api and hasattr(self.client, 'clear_cache'):
            self.client.clear_cache()
### Adapter Implementation

**Create `data_adapter.py`:**

```python
"""
Data Adapter for switching between local database and DataOps API.

Usage:
    adapter = DataAdapter()
    stations = adapter.get_stations(state='CO')
    data = adapter.get_station_data('09070500', '2026-01-01', '2026-02-05')
"""

import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import pandas as pd


class DataAdapter:
    """Unified interface for local DB or DataOps API."""
    
    def __init__(self):
        """Initialize adapter based on USE_DATAOPS_API environment variable."""
        self.use_api = os.getenv('USE_DATAOPS_API', 'false').lower() == 'true'
        
        if self.use_api:
            from dataops_client import DataOpsClient
            self.client = DataOpsClient(
                base_url=os.getenv('DATAOPS_API_URL', 'http://localhost:8000'),
                cache_enabled=os.getenv('DATAOPS_CACHE_ENABLED', 'true').lower() == 'true',
                cache_ttl=int(os.getenv('DATAOPS_CACHE_TTL', '300'))
            )
            print("✓ DataAdapter: Using DataOps API")
        else:
            # Import your existing local database module
            from .local_database import LocalDatabase
            self.db = LocalDatabase()
            print("✓ DataAdapter: Using local database")
    
    def get_stations(
        self,
        state: Optional[str] = None,
        agency: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """Get list of stations."""
        if self.use_api:
            response = self.client.get_stations(
                state=state,
                agency=agency,
                is_active=is_active,
                search=search,
                limit=limit
            )
            
            stations = [{
                'station_number': s.station_number,
                'name': s.station_name,
                'agency': s.agency,
                'latitude': float(s.latitude) if s.latitude else None,
                'longitude': float(s.longitude) if s.longitude else None,
                'state': s.state_code,
                'huc_code': s.huc_code,
                'is_active': s.is_active,
            } for s in response.results]
            
            return pd.DataFrame(stations)
        else:
            return self.db.query_stations(
                state=state,
                agency=agency,
                is_active=is_active,
                search=search,
                limit=limit
            )
    
    def get_station_data(
        self,
        station_number: str,
        start_date: str,
        end_date: str,
        data_type: str = 'daily_mean'
    ) -> pd.DataFrame:
        """Get discharge observations for a station."""
        if self.use_api:
            observations = self.client.get_station_data(
                station_number=station_number,
                start_date=start_date,
                end_date=end_date,
                data_type=data_type
            )
            
            data = [{
                'date': obs.observed_at,
                'station_number': obs.station_number,
                'discharge': obs.discharge_value,
                'unit': obs.unit,
                'quality': obs.quality_code,
                'type': obs.data_type
            } for obs in observations]
            
            df = pd.DataFrame(data)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
            return df
        else:
            return self.db.query_discharge_data(
                station_number=station_number,
                start_date=start_date,
                end_date=end_date,
                data_type=data_type
            )
```

### Migration Steps

**Phase 1: Preparation (Day 1)**
1. Install DataOps client library
2. Create adapter module
3. Test adapter in local mode (`USE_DATAOPS_API=false`)

**Phase 2: API Testing (Day 2-3)**  
1. Switch to API mode (`USE_DATAOPS_API=true`)
2. Test all features
3. Compare results with local data
4. Monitor performance

**Phase 3: Production (Day 4+)**
1. Deploy with API mode enabled
2. Monitor for issues
3. Retire local data collection scripts

**Quick Rollback:** Set `USE_DATAOPS_API=false` and restart

---

## Performance & Caching

### Response Times

Typical API response times:
- Station list (100 records): 10-50ms
- Station detail: 5-15ms  
- Discharge data (30 days): 50-200ms
- Discharge data (1 year): 200-500ms
- Statistics calculation: 100-300ms

### Client-Side Caching

The Python client includes built-in caching:

```python
client = DataOpsClient(
    base_url="http://localhost:8000",
    cache_enabled=True,
    cache_ttl=300  # Cache for 5 minutes
)

# First call - hits API
stations = client.get_stations(state="CO")  # ~50ms

# Second call within 5 minutes - returns cached
stations = client.get_stations(state="CO")  # <1ms
```

### Application-Level Caching

For web applications, implement your own caching:

```python
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=128)
def get_cached_stations(state: str, timestamp: int):
    """Cache stations for 5 minutes."""
    client = DataOpsClient(base_url="http://localhost:8000")
    return client.get_stations(state=state)

def get_stations_with_cache(state: str):
    # Generate cache key that changes every 5 minutes
    cache_key = int(datetime.now().timestamp() // 300)
    return get_cached_stations(state, cache_key)
```

### Optimization Tips

1. **Use pagination** - Don't fetch all 5,394 stations at once
2. **Limit date ranges** - Query smaller time windows
3. **Use statistics endpoint** - Faster than calculating client-side
4. **Enable caching** - Reduce redundant API calls
5. **Batch operations** - Use batch endpoints when available

---

## Error Handling

### Common HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process response |
| 404 | Not Found | Station doesn't exist or no data |
| 400 | Bad Request | Check query parameters |
| 500 | Server Error | Retry with backoff |
| 503 | Service Unavailable | API or database down |

### Python Error Handling

```python
from dataops_client import DataOpsClient, DataOpsError, NotFoundError
import time

client = DataOpsClient(base_url="http://localhost:8000")

try:
    stations = client.get_stations(state="CO")
except NotFoundError:
    print("No stations found for this query")
except DataOpsError as e:
    print(f"API Error: {e}")
    # Fallback to local data or retry
except Exception as e:
    print(f"Unexpected error: {e}")
```

### Retry Logic

```python
import requests
from time import sleep

def api_call_with_retry(url, params, max_retries=3):
    """Make API call with exponential backoff."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt  # 1s, 2s, 4s
            print(f"Retry {attempt + 1}/{max_retries} after {wait_time}s...")
            sleep(wait_time)
```

---

## Troubleshooting

### Issue: "Connection refused"

**Problem:** Can't connect to API

**Solutions:**
1. Check if API is running: `curl http://localhost:8000/api/v1/stations/?limit=1`
2. Verify `DATAOPS_API_URL` in your configuration
3. Check firewall/network settings
4. Start the API: `python manage.py runserver`

### Issue: "Station not found"

**Problem:** 404 error for station

**Solutions:**
1. Verify station exists: `curl http://localhost:8000/api/v1/stations/{station_number}/`
2. Check if station is active in database
3. Verify correct station number format

### Issue: "No data returned"

**Problem:** Empty result set

**Solutions:**
1. Check date range - data may not exist for those dates
2. Verify `data_type` parameter (daily_mean, realtime_15min, etc.)
3. Query `/api/v1/stations/{station_number}/` to see `last_observation_date`
4. Check if data exists: `curl "http://localhost:8000/api/v1/observations/discharge/?station_number={station_number}&limit=1"`

### Issue: Slow performance

**Problem:** API responses are slow

**Solutions:**
1. Enable caching in client
2. Reduce date ranges in queries
3. Use pagination (`limit` and `offset`)
4. Check API server load
5. Consider caching at application level

### Issue: Data discrepancy

**Problem:** Different results from API vs local DB

**Solutions:**
1. Check data freshness - when was each last updated?
2. Verify `data_type` matches (daily_mean vs realtime_15min)
3. Check timezone handling
4. Compare raw API response with database query

---

## Examples

### Example 1: Simple Dashboard

```python
"""Simple Flask dashboard using DataOps API."""

from flask import Flask, render_template, request
from dataops_client import DataOpsClient
from datetime import datetime, timedelta

app = Flask(__name__)
client = DataOpsClient(base_url="http://localhost:8000")

@app.route('/')
def index():
    """Station list page."""
    state = request.args.get('state', 'CO')
    stations = client.get_stations(state=state, limit=50)
    return render_template('index.html', 
                         stations=stations.results,
                         state=state)

@app.route('/station/<station_number>')
def station_detail(station_number):
    """Station detail with 30-day graph."""
    station = client.get_station(station_number)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    data = client.get_station_data(
        station_number,
        start_date,
        end_date
    )
    
    return render_template('station.html',
                         station=station,
                         data=data)

if __name__ == '__main__':
    app.run(debug=True)
```

### Example 2: Data Analysis Script

```python
"""Analyze discharge trends across multiple stations."""

from dataops_client import DataOpsClient
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt

client = DataOpsClient(base_url="http://localhost:8000")

# Get all Colorado USGS stations
stations = client.get_stations(state="CO", agency="USGS", limit=1000)
print(f"Analyzing {stations.count} Colorado stations...")

# Get last 30 days of data for each station
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

results = []
for station in stations.results[:10]:  # First 10 for demo
    print(f"Processing {station.station_number}...")
    
    stats = client.get_station_statistics(
        station.station_number,
        start_date,
        end_date
    )
    
    results.append({
        'station': station.station_number,
        'name': station.station_name,
        'mean_discharge': stats.get('mean', 0),
        'max_discharge': stats.get('max', 0)
    })

# Create DataFrame and analyze
df = pd.DataFrame(results)
df = df.sort_values('mean_discharge', ascending=False)

print("\nTop 5 by mean discharge:")
print(df.head())

# Plot
df.plot(x='station', y='mean_discharge', kind='bar', figsize=(12, 6))
plt.title('Mean Discharge by Station (Last 30 Days)')
plt.ylabel('Discharge (cfs)')
plt.tight_layout()
plt.savefig('discharge_analysis.png')
print("\n✓ Saved discharge_analysis.png")
```

### Example 3: Export to CSV

```python
"""Export station data to CSV files."""

from dataops_client import DataOpsClient
from datetime import datetime, timedelta
import os

client = DataOpsClient(base_url="http://localhost:8000")

# Define stations and time range
station_numbers = ["09070500", "09085000", "09095500"]
end_date = datetime.now()
start_date = end_date - timedelta(days=365)  # 1 year

# Create output directory
os.makedirs("data_exports", exist_ok=True)

# Export each station
for station_num in station_numbers:
    print(f"Exporting {station_num}...")
    
    csv_data = client.get_station_data(
        station_num,
        start_date,
        end_date,
        format="csv"
    )
    
    filename = f"data_exports/{station_num}_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}.csv"
    with open(filename, "w") as f:
        f.write(csv_data)
    
    print(f"  ✓ Saved {filename}")

print("\n✓ Export complete!")
```

### Example 4: React Frontend

```javascript
// React component for station search and display

import React, { useState, useEffect } from 'react';

const API_BASE = 'http://localhost:8000/api/v1';

function StationSearch() {
  const [state, setState] = useState('CO');
  const [stations, setStations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchStations();
  }, [state]);

  async function fetchStations() {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(
        `${API_BASE}/stations/?state=${state}&limit=50`
      );
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      
      const data = await response.json();
      setStations(data.results);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="station-search">
      <h2>Station Search</h2>
      
      <select value={state} onChange={(e) => setState(e.target.value)}>
        <option value="CO">Colorado</option>
        <option value="CA">California</option>
        <option value="OR">Oregon</option>
        <option value="WA">Washington</option>
      </select>

      {loading && <p>Loading...</p>}
      {error && <p className="error">Error: {error}</p>}

      <table>
        <thead>
          <tr>
            <th>Station Number</th>
            <th>Name</th>
            <th>Agency</th>
            <th>HUC</th>
          </tr>
        </thead>
        <tbody>
          {stations.map(station => (
            <tr key={station.station_number}>
              <td>{station.station_number}</td>
              <td>{station.station_name}</td>
              <td>{station.agency}</td>
              <td>{station.huc_code}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default StationSearch;
```

---

## Additional Resources

### Documentation Links

- **API Documentation**: [http://localhost:8000/api/docs/](http://localhost:8000/api/docs/) (Swagger UI)
- **Python Client README**: [../dataops_client/README.md](../dataops_client/README.md)
- **OpenAPI Schema**: [http://localhost:8000/api/schema/](http://localhost:8000/api/schema/)

### System Status

- **Active Stations**: 5,394 (HUC 14-18 Western US)
- **Total Observations**: 2.5M+ discharge records
- **Date Range**: 1897-present
- **Data Sources**: USGS, Environment Canada, NOAA
- **Update Frequency**: Configurable per data type

### Support

- **GitHub Issues**: Create issues for bugs or feature requests
- **Email**: Contact development team
- **Documentation**: Check README files in repository

---

## Quick Reference

### Endpoint Cheat Sheet

```bash
# Stations
GET  /api/v1/stations/                          # List stations
GET  /api/v1/stations/{station_number}/         # Get station
GET  /api/v1/stations/{station_number}/data/    # Get discharge data
GET  /api/v1/stations/{station_number}/statistics/  # Get statistics

# Observations
GET  /api/v1/observations/discharge/            # Query observations
GET  /api/v1/observations/discharge/export/     # Export to CSV

# Configurations
GET  /api/v1/configurations/                    # List configs
GET  /api/v1/configurations/{id}/               # Get config
POST /api/v1/configurations/{id}/trigger/       # Trigger pull

# Logs
GET  /api/v1/logs/                              # List logs
GET  /api/v1/logs/recent/                       # Recent activity
```

### Common Query Parameters

- `state` - Filter by state code (CO, CA, OR, etc.)
- `agency` - Filter by agency (USGS, EC, NOAA)
- `start_date` - Start date (YYYY-MM-DD)
- `end_date` - End date (YYYY-MM-DD)
- `data_type` - Data type (daily_mean, realtime_15min)
- `limit` - Results per page (default 100, max 1000)
- `offset` - Pagination offset
- `search` - Search term
- `format` - Response format (json, csv)

### Data Types

- `daily_mean` - Daily average discharge
- `realtime_15min` - 15-minute interval real-time data
- `forecast_short` - Short-term forecast
- `forecast_medium` - Medium-term forecast

---

**End of Integration Guide**

For more examples and detailed API documentation, visit:
- [Interactive API Docs](http://localhost:8000/api/docs/)
- [Python Client Documentation](../dataops_client/README.md)
- [System README](../README.md)


