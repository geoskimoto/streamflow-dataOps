# Data Pull Fix Summary

## Issue
Data pulls were showing success status but not storing any observations in the database.

## Root Cause
**Missing Station Records**: The `Station` table only contained 157 records, while there were 308 stations configured across all `PullConfiguration` objects. When data was pulled, the `DataProcessor.process_observations()` method tried to fetch the Station record with `Station.objects.get(station_number=...)`, which raised a `DoesNotExist` exception for stations not in the table.

### Architectural Gap
- Adding stations to configurations creates `PullConfigurationStation` entries
- But it does NOT create corresponding `Station` entries
- The `Station` table is required for storing `DischargeObservation` and `ForecastRun` records
- NOAA RFC forecasts worked because `tasks.py` line 193 does `get_or_create` for Station
- USGS/EC observations failed because `data_processor.py` expects Station to pre-exist

## Solution
Created a `sync_stations` management command to backfill missing Station records from the MasterStation table.

### Command Features
```bash
# Dry run to see what would be created
python manage.py sync_stations --dry-run

# Create missing stations
python manage.py sync_stations

# Sync only specific configuration
python manage.py sync_stations --config "Active Stations Test"
```

The command:
1. Queries all `PullConfigurationStation` entries
2. Checks if corresponding `Station` record exists
3. Creates missing Station records from `MasterStation` data (with lat/lon, agency, etc.)
4. Falls back to minimal Station record if MasterStation entry not found

## Results

### Before Fix
- Station table: 157 records
- DischargeObservation: 60 records (old data from Jan 16)
- Data pulls showing success but `records_processed: 0`

### After Fix
- Executed: `python manage.py sync_stations`
- Created: **152 new Station records**
- Station table: **309 records** (complete coverage)
- Breakdown by configuration:
  - rfc test: 50 new stations (200 total)
  - Environment Canada Test: 2 new stations
  - Active Stations Test: 100 new stations
  - Test USGS Daily Mean: 0 new (all existed)
  - NOAA Forecast Test: 0 new (existed)

### Test Pull Results
Tested "Active Stations Test" configuration (100 USGS stations):
- **Result: SUCCESS**
- Records processed: **623 observations**
- DischargeObservation table: 60 → 683 records
- Successful stations: 100 (some returned no data for time period)
- Failed stations: 0

Latest DataPullLog entries show:
```
Active Stations Test:
  Status: success
  Records processed: 623
  Duration: ~97 seconds

rfc test:
  Status: success  
  Records processed: 4403
  Duration: ~5 minutes
```

## Recommendations

### 1. Auto-Create Stations When Adding to Config
Update the `add_stations_to_config` view to create Station records:
```python
def add_stations_to_config(request, config_id):
    # ... existing code ...
    
    for station in selected_stations:
        # Create PullConfigurationStation
        PullConfigurationStation.objects.create(...)
        
        # Also create Station if it doesn't exist
        Station.objects.get_or_create(
            station_number=station.station_number,
            defaults={
                'name': station.station_name,
                'agency': station.agency,
                'latitude': station.latitude,
                'longitude': station.longitude,
                # ... other fields
            }
        )
```

### 2. Run sync_stations Periodically
Add to deployment checklist or as a periodic Celery task:
```python
@celery_app.task
def sync_stations_task():
    """Periodic task to ensure Station table is in sync"""
    call_command('sync_stations')
```

### 3. Update Documentation
Document that:
- Station table must contain records for all configured stations
- Run `sync_stations` after importing new configurations or adding stations
- Station vs MasterStation architecture explained

### 4. Consider Data Processor Enhancement
Option to auto-create Station in `data_processor.py` if doesn't exist:
```python
try:
    station = Station.objects.get(station_number=station_number)
except Station.DoesNotExist:
    # Auto-create from MasterStation or minimal record
    master = MasterStation.objects.filter(station_number=station_number).first()
    if master:
        station = Station.objects.create(...)
    else:
        logger.warning(f"Station {station_number} not in MasterStation")
        return 0
```

## Files Modified/Created

### New Files
- `apps/streamflow/management/commands/sync_stations.py` - Management command to sync Station records

### Related Files
- `src/acquisition/data_processor.py` - Line 48: Expects Station.objects.get() to succeed
- `src/acquisition/tasks.py` - Line 193: Has get_or_create logic for NOAA RFC (but not USGS/EC)
- `apps/streamflow/models.py` - Station, MasterStation, PullConfigurationStation models

## Verification Steps

To verify data pulls are working:

```bash
# Check Station table coverage
python manage.py shell -c "
from apps.streamflow.models import Station, PullConfigurationStation
print(f'Stations in configs: {PullConfigurationStation.objects.values(\"station_number\").distinct().count()}')
print(f'Stations in table: {Station.objects.count()}')
"

# Trigger a test pull
python manage.py shell -c "
from apps.streamflow.models import PullConfiguration
from src.acquisition.tasks import execute_pull_configuration
config = PullConfiguration.objects.first()
result = execute_pull_configuration(config.id)
print(result)
"

# Check recent observations
python manage.py shell -c "
from apps.streamflow.models import DischargeObservation
from datetime import datetime, timezone, timedelta
recent = DischargeObservation.objects.filter(
    observed_at__gte=datetime.now(timezone.utc) - timedelta(days=1)
)
print(f'Recent observations: {recent.count()}')
"
```

## Date
January 26, 2026

## Status
✅ **RESOLVED** - Data pulls are now working correctly and storing observations.
