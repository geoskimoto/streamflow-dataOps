# Dashboard Integration Guide

**StreamFlow DataOps API Integration**  
**Version:** 1.0  
**Date:** January 17, 2026  
**Status:** Ready for Integration

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Adapter Pattern Implementation](#adapter-pattern)
6. [Migration Steps](#migration-steps)
7. [Testing](#testing)
8. [Rollback Procedures](#rollback-procedures)
9. [Troubleshooting](#troubleshooting)
10. [FAQ](#faq)

---

## Overview

This guide provides step-by-step instructions for integrating the StreamFlow DataOps API into the existing USGS Streamflow Dashboard. The integration uses an **adapter pattern** to allow seamless switching between local SQLite database and the remote DataOps API.

### Benefits of Integration

- **Centralized Data Management**: Single source of truth for streamflow data
- **Automatic Data Updates**: Celery-powered background data collection
- **Multi-Source Support**: USGS, Environment Canada, NOAA integration
- **Improved Performance**: Optimized queries, caching, and pagination
- **Better Maintainability**: Separation of data collection from visualization
- **Scalability**: Handle 10,000+ stations with minimal latency

###Current Architecture

```
Dashboard (Standalone)
├── SQLite Database
├── Data Collection Scripts
├── Visualization Components
└── Flask/Streamlit UI
```

### Target Architecture

```
Dashboard (Client)              DataOps API (Server)
├── DataOps Client Library  →  ├── Django REST API
├── Adapter Layer           →  ├── Celery Workers
├── Visualization (unchanged)   ├── Redis Cache
└── Flask/Streamlit UI          ├── PostgreSQL/SQLite
                                └── Multi-Source Data Collection
```

---

## Prerequisites

### Dashboard Environment

- Python 3.8+ (3.13 recommended)
- Access to dashboard codebase: `~/Proj/streamflow-dashboard/usgs-streamflow-dashboard`
- Existing dashboard should be functional

### DataOps API

- **API URL**: `http://localhost:8000` (development) or `https://api.dataops.example.com` (production)
- **API Documentation**: `http://localhost:8000/api/docs/` (Swagger UI)
- **API Status**: Phase 4 Complete (24 endpoints operational)

### Required Packages

```bash
pip install requests python-dotenv pandas
```

---

## Installation

### Step 1: Install DataOps Client Library

From the dashboard project directory:

```bash
cd ~/Proj/streamflow-dashboard/usgs-streamflow-dashboard

# Option A: Install from source
pip install -e ~/Proj/streamflow-dataOps/streamflow-dataOps/dataops_client

# Option B: Copy client into dashboard
cp -r ~/Proj/streamflow-dataOps/streamflow-dataOps/dataops_client ./dataops_client
pip install -e ./dataops_client
```

### Step 2: Verify Installation

```bash
python -c "from dataops_client import DataOpsClient; print('✓ Client installed')"
```

---

## Configuration

### Step 1: Environment Variables

Create `.env` file in dashboard root:

```ini
# DataOps API Configuration
DATAOPS_API_URL=http://localhost:8000
DATAOPS_API_TOKEN=your-jwt-token-here  # Optional for read-only
DATAOPS_VERIFY_SSL=true
DATAOPS_CACHE_ENABLED=true
DATAOPS_CACHE_TTL=300  # 5 minutes

# Feature Flag
USE_DATAOPS_API=false  # Start with false, switch to true after testing
```

### Step 2: Load Environment

Add to dashboard's main application file:

```python
# app.py or main.py
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Check feature flag
USE_DATAOPS_API = os.getenv('USE_DATAOPS_API', 'false').lower() == 'true'
print(f"DataOps API Mode: {'ENABLED' if USE_DATAOPS_API else 'DISABLED (using local DB)'}")
```

---

## Adapter Pattern Implementation

### Step 1: Create Adapter Module

Create `dashboard/data_adapter.py`:

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
```

### Step 2: Update Dashboard Code

Replace direct database calls with adapter:

**Before (local database):**
```python
# Old code
from local_database import get_stations, get_discharge_data

stations = get_stations(state='CO')
data = get_discharge_data('09070500', '2026-01-01', '2026-01-17')
```

**After (with adapter):**
```python
# New code
from data_adapter import DataAdapter

adapter = DataAdapter()  # Auto-detects mode from environment
stations = adapter.get_stations(state='CO')
data = adapter.get_station_data('09070500', '2026-01-01', '2026-01-17')
```

---

## Migration Steps

### Phase 1: Preparation (1-2 days)

1. **Backup Current System**
   ```bash
   # Backup database
   cp dashboard_database.db dashboard_database.db.backup
   
   # Backup code
   git add -A
   git commit -m "Pre-migration checkpoint"
   git tag pre-dataops-migration
   ```

2. **Install Client Library**
   - Follow [Installation](#installation) steps
   - Verify installation with test script

3. **Create Adapter**
   - Create `data_adapter.py` from template above
   - Ensure local database code is compatible

### Phase 2: Testing (2-3 days)

1. **Unit Tests**
   ```python
   # test_adapter.py
   from data_adapter import DataAdapter
   
   def test_adapter_local_mode():
       os.environ['USE_DATAOPS_API'] = 'false'
       adapter = DataAdapter()
       stations = adapter.get_stations(limit=10)
       assert len(stations) > 0
   
   def test_adapter_api_mode():
       os.environ['USE_DATAOPS_API'] = 'true'
       adapter = DataAdapter()
       stations = adapter.get_stations(limit=10)
       assert len(stations) > 0
   ```

2. **Integration Tests**
   - Test each dashboard feature with adapter
   - Verify data consistency between modes
   - Check performance (API vs local)

3. **Side-by-Side Comparison**
   ```python
   # Compare outputs
   os.environ['USE_DATAOPS_API'] = 'false'
   adapter_local = DataAdapter()
   local_data = adapter_local.get_station_data('09070500', '2026-01-01', '2026-01-17')
   
   os.environ['USE_DATAOPS_API'] = 'true'
   adapter_api = DataAdapter()
   api_data = adapter_api.get_station_data('09070500', '2026-01-01', '2026-01-17')
   
   # Compare
   assert len(local_data) == len(api_data)
   ```

### Phase 3: Gradual Rollout (3-5 days)

1. **Development Testing**
   - Set `USE_DATAOPS_API=false` (local mode)
   - Test all dashboard features
   - Verify nothing broke

2. **API Mode Testing**
   - Set `USE_DATAOPS_API=true`
   - Test with DataOps API
   - Monitor performance and errors

3. **User Acceptance**
   - Run dashboard with both modes
   - Get feedback from users
   - Document any issues

### Phase 4: Production Deployment

1. **Pre-Deployment Checklist**
   - [ ] All tests passing
   - [ ] Performance acceptable
   - [ ] Rollback plan documented
   - [ ] Users notified
   - [ ] Monitoring configured

2. **Deployment**
   ```bash
   # Update environment
   echo "USE_DATAOPS_API=true" >> .env
   echo "DATAOPS_API_URL=https://api.dataops.example.com" >> .env
   
   # Restart dashboard
   ./restart_dashboard.sh
   ```

3. **Post-Deployment**
   - Monitor error logs
   - Check API response times
   - Verify data accuracy
   - Gather user feedback

---

## Testing

### Test Script

Create `test_integration.py`:

```python
"""Test DataOps API Integration"""

import os
from data_adapter import DataAdapter
from datetime import datetime, timedelta

def test_basic_functionality():
    """Test basic adapter functionality."""
    print("Testing DataOps Integration...")
    print("=" * 60)
    
    adapter = DataAdapter()
    
    # Test 1: Get stations
    print("\n1. Testing get_stations()...")
    stations = adapter.get_stations(state='CO', limit=5)
    print(f"   ✓ Retrieved {len(stations)} Colorado stations")
    
    if len(stations) > 0:
        station_num = stations.iloc[0]['station_number']
        print(f"   Example: {station_num}")
        
        # Test 2: Get station info
        print(f"\n2. Testing get_station_info('{station_num}')...")
        info = adapter.get_station_info(station_num)
        print(f"   ✓ Name: {info['name']}")
        print(f"   ✓ Location: ({info['latitude']}, {info['longitude']})")
        
        # Test 3: Get discharge data
        print(f"\n3. Testing get_station_data('{station_num}')...")
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        data = adapter.get_station_data(
            station_num,
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d')
        )
        print(f"   ✓ Retrieved {len(data)} observations")
        
        if len(data) > 0:
            print(f"   ✓ Date range: {data['date'].min()} to {data['date'].max()}")
            print(f"   ✓ Discharge range: {data['discharge'].min():.2f} - {data['discharge'].max():.2f} cfs")
        
        # Test 4: Get statistics
        print(f"\n4. Testing get_station_statistics('{station_num}')...")
        stats = adapter.get_station_statistics(
            station_num,
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d')
        )
        print(f"   ✓ Count: {stats.get('count', 0)}")
        print(f"   ✓ Mean: {stats.get('mean', 0):.2f} cfs")
        print(f"   ✓ Range: {stats.get('min', 0):.2f} - {stats.get('max', 0):.2f} cfs")
    
    print("\n" + "=" * 60)
    print("✓ All tests passed!")

if __name__ == '__main__':
    test_basic_functionality()
```

Run test:
```bash
python test_integration.py
```

---

## Rollback Procedures

### If Issues Occur

1. **Immediate Rollback**
   ```bash
   # Disable API mode
   echo "USE_DATAOPS_API=false" >> .env
   
   # Restart dashboard
   ./restart_dashboard.sh
   ```

2. **Full Rollback**
   ```bash
   # Restore from backup
   cp dashboard_database.db.backup dashboard_database.db
   
   # Revert code
   git checkout pre-dataops-migration
   
   # Remove client
   pip uninstall dataops-client
   ```

3. **Restore Data**
   - If local database corrupted, restore from backup
   - Re-run data collection scripts if needed

---

## Troubleshooting

### Common Issues

#### Issue 1: Connection Refused

**Symptom:**
```
ConnectionError: Connection refused to http://localhost:8000
```

**Solution:**
- Verify DataOps API is running: `curl http://localhost:8000/api/v1/health/`
- Check `DATAOPS_API_URL` in `.env`
- Verify network connectivity

#### Issue 2: Authentication Failed

**Symptom:**
```
AuthenticationError: Authentication failed. Check your API token.
```

**Solution:**
- Verify `DATAOPS_API_TOKEN` is set correctly
- Check token expiration
- For read-only access, token may not be required

#### Issue 3: Missing Data

**Symptom:**
```
NotFoundError: Station not found
```

**Solution:**
- Verify station exists in DataOps: `curl http://localhost:8000/api/v1/stations/09070500/`
- Check station was imported correctly
- Verify station is active

#### Issue 4: Slow Performance

**Symptom:**
Dashboard loads slowly with API mode enabled.

**Solution:**
- Enable caching: `DATAOPS_CACHE_ENABLED=true`
- Increase cache TTL: `DATAOPS_CACHE_TTL=600`
- Check API server performance
- Optimize queries (reduce date ranges, limit results)

#### Issue 5: Data Mismatch

**Symptom:**
Different results between local DB and API.

**Solution:**
- Check data freshness in both systems
- Verify data types match (daily_mean vs realtime_15min)
- Check for timezone issues
- Compare raw data manually

---

## FAQ

### Q1: Can I use both local and API modes simultaneously?

No, the adapter uses a single mode at a time based on the `USE_DATAOPS_API` flag. However, you can instantiate two adapters with different configurations for comparison.

### Q2: What happens if the API is down?

The client includes retry logic (3 attempts with exponential backoff). If all retries fail, an exception is raised. You should handle this in your dashboard code and potentially fallback to local mode.

### Q3: How often is data updated in the API?

Data update frequency depends on the PullConfiguration schedule. Typical schedules:
- Real-time data: Every 1-6 hours
- Daily mean data: Once per day
- Check configuration status via API: `/api/v1/configurations/`

### Q4: Can I still add/edit stations locally?

In API mode, station management should be done through the DataOps web interface or API. Local changes won't be reflected in the centralized system.

### Q5: What's the performance difference?

- **Local DB**: Faster for single queries (<1ms)
- **API**: Slightly slower (5-50ms) but with benefits:
  - Centralized data management
  - Automatic updates
  - Multi-source integration
  - Better for multi-user scenarios

### Q6: How do I contribute back data quality flags?

Use the API's update endpoints or the Django admin interface to flag data quality issues. This helps improve data for all users.

### Q7: Can I cache data locally in API mode?

Yes! The client includes built-in caching (5-minute default). You can also implement your own caching layer in the adapter.

---

## Contact & Support

- **Documentation**: [DataOps README](../dataops_client/README.md)
- **API Docs**: http://localhost:8000/api/docs/
- **Issues**: Create GitHub issue in streamflow-dataOps repository
- **Questions**: Contact development team

---

## Appendix: Complete Example

### Example Dashboard Integration

```python
# dashboard_app.py
from flask import Flask, render_template, request
from data_adapter import DataAdapter
from datetime import datetime, timedelta

app = Flask(__name__)
adapter = DataAdapter()

@app.route('/')
def index():
    """Main dashboard page."""
    # Get list of stations
    states = ['CO', 'CA', 'OR', 'WA']
    stations = adapter.get_stations(limit=100)
    
    return render_template('index.html', stations=stations)

@app.route('/station/<station_number>')
def station_detail(station_number):
    """Station detail page with discharge graph."""
    # Get station info
    station = adapter.get_station_info(station_number)
    
    # Get discharge data (last 30 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    data = adapter.get_station_data(
        station_number,
        start_date.strftime('%Y-%m-%d'),
        end_date.strftime('%Y-%m-%d'),
        data_type='daily_mean'
    )
    
    # Get statistics
    stats = adapter.get_station_statistics(
        station_number,
        start_date.strftime('%Y-%m-%d'),
        end_date.strftime('%Y-%m-%d')
    )
    
    return render_template(
        'station_detail.html',
        station=station,
        data=data.to_dict('records'),
        stats=stats
    )

@app.route('/compare')
def compare_stations():
    """Compare multiple stations."""
    station_numbers = request.args.getlist('stations')
    
    if not station_numbers:
        return "No stations selected", 400
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)
    
    # Batch query
    data = adapter.batch_query_stations(
        station_numbers,
        start_date.strftime('%Y-%m-%d'),
        end_date.strftime('%Y-%m-%d')
    )
    
    return render_template('compare.html', data=data)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
```

---

**End of Integration Guide**

For additional examples and API documentation, see:
- [DataOps Client README](../dataops_client/README.md)
- [API Documentation](http://localhost:8000/api/docs/)
- [Phase 4 Implementation Plan](../Journal/IMPLEMENTATION_PLAN.md)
