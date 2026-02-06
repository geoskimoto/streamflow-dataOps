# Historical Backfill Configuration Session - February 4, 2026

## Session Summary

Completed configuration of two separate historical backfill pull configurations for USGS stations, with verified station counts and comprehensive deployment documentation.

---

## 1. Station Count Verification

### Database Query Results

**Active Stations:**
```
HUC 17 only: 2,890 active stations
HUC 14-18 total: 2,890 active stations  
HUC 14-16 (non-17): 0 active stations
```

**Master Stations:**
```
HUC 14 (Upper Colorado): 0 master stations
HUC 15 (Lower Colorado): 50 master stations
HUC 16 (Great Basin): 145 master stations
HUC 17 (Pacific Northwest): 2,890 master stations
HUC 18 (California): 2,309 master stations
Total HUC 14-18: 5,394 master stations
```

### Key Findings

- Initial assumption of 6,500 stations in HUC 17 was incorrect
- Actual HUC 17 count: **2,890 stations**
- Total Western US (HUC 14-18): **5,394 stations**
- Only HUC 17 currently has active stations synced
- Other HUC regions (14-16, 18) exist in MasterStation but not yet synced to active Station table

---

## 2. Two-Configuration Approach

### Configuration 1: HUC 17 Historical Backfill

**Purpose:** Regional Pacific Northwest focus

**Details:**
- **Name:** "PNW USGS Historical Backfill (One-Time)"
- **Stations:** ~2,890 USGS stations
- **Coverage:** Oregon, Washington, Idaho portions of HUC 17
- **Status:** Enabled by default
- **Execution:** Manual, one-time
- **Strategy:** `replace` (prevents duplicates on re-runs)
- **Date Range:** Earliest available (varies by station, some ~1900s) to present
- **Estimated Data Volume:** 30-50 million observations (5-15 GB)

**Station Retrieval Function:**
```python
def get_pnw_usgs_stations():
    """Get all active USGS stations in HUC 17 (Pacific Northwest)."""
    from apps.streamflow.models import Station
    
    stations = Station.objects.filter(
        agency='USGS',
        huc_code__startswith='17',
        is_active=True
    ).values_list('station_number', flat=True)
    
    return list(stations)
```

### Configuration 2: HUC 14-18 Historical Backfill

**Purpose:** Comprehensive Western US coverage

**Details:**
- **Name:** "Western US USGS Historical Backfill (HUC 14-18)"
- **Stations:** ~5,394 USGS stations (when all synced)
- **Coverage:** 
  - HUC 14: Upper Colorado River Basin
  - HUC 15: Lower Colorado River Basin
  - HUC 16: Great Basin
  - HUC 17: Pacific Northwest
  - HUC 18: California
- **Status:** Disabled by default (user must enable when ready)
- **Execution:** Manual, one-time
- **Strategy:** `replace` (prevents duplicates on re-runs)
- **Date Range:** Earliest available to present
- **Estimated Data Volume:** 80-150 million observations (15-40 GB)

**Station Retrieval Function:**
```python
def get_western_us_usgs_stations():
    """Get all active USGS stations in HUC 14-18 (Western US)."""
    from apps.streamflow.models import Station
    
    stations = Station.objects.filter(
        agency='USGS',
        huc_code__regex=r'^1[4-8]',  # HUC 14, 15, 16, 17, 18
        is_active=True
    ).values_list('station_number', flat=True)
    
    return list(stations)
```

---

## 3. Implementation Details

### Files Modified

**scripts/deploy.py:**
- Added `get_pnw_usgs_stations()` function
- Added `get_western_us_usgs_stations()` function
- Created `create_pnw_historical_backfill_config()` function
- Created `create_western_us_historical_backfill_config()` function
- Updated `setup_pull_configurations()` to create both configs

**Key Configuration Parameters:**
```python
PullConfiguration.objects.create(
    name='PNW USGS Historical Backfill (One-Time)',
    data_source='USGS',
    data_type='daily_mean',
    data_strategy='replace',  # Prevents duplicates
    pull_start_date='1900-01-01',
    is_enabled=True,  # HUC 17 enabled by default
    schedule_type='manual',
    description='One-time historical backfill for all PNW USGS stations in HUC 17.'
)

PullConfiguration.objects.create(
    name='Western US USGS Historical Backfill (HUC 14-18)',
    data_source='USGS',
    data_type='daily_mean',
    data_strategy='replace',
    pull_start_date='1900-01-01',
    is_enabled=False,  # HUC 14-18 disabled by default
    schedule_type='manual',
    description='One-time historical backfill for all Western US USGS stations.'
)
```

---

## 4. Deployment Guide Updates

### Documentation/DEPLOYMENT_GUIDE.md

Updated comprehensive deployment guide with:

**Added Sections:**
- Detailed instructions for running HUC 17 backfill
- Detailed instructions for running HUC 14-18 backfill
- Performance tips and monitoring guidance
- Data volume estimates
- Database disk space requirements

**Backfill Instructions Include:**
1. Finding configuration ID
2. Running via Celery task
3. Monitoring progress (logs and database)
4. Disabling after completion

**Example Usage:**
```bash
# Find configuration
python manage.py shell
>>> from apps.streamflow.models import PullConfiguration
>>> config = PullConfiguration.objects.get(name__contains="HUC 17")
>>> print(f"ID: {config.id}, Enabled: {config.is_enabled}")

# Run backfill
>>> from src.acquisition.tasks import pull_usgs_data
>>> result = pull_usgs_data.delay(config.id)
>>> print(f"Task ID: {result.id}")

# Monitor progress
>>> from apps.streamflow.models import DischargeObservation
>>> print(f"Total observations: {DischargeObservation.objects.count():,}")

# Disable after completion
>>> config.is_enabled = False
>>> config.save()
```

---

## 5. Additional Work This Session

### API Testing

**Created comprehensive test suites:**
- **test_api_filtering.py** (349 lines, 19 tests) - Pagination, date filtering, ordering, multi-field filtering, search
- **test_api_errors.py** (473 lines, 24 tests) - Error handling, validation, boundary conditions, response structure

**Test Results:** 43/43 tests passing (100%)

### CSV Export Feature

**Decision:** Disabled CSV export functionality
- Feature referenced non-existent `obs.data_source` field
- User indicated CSV export not needed
- Commented out `export_csv()` action in [observation.py](apps/api/views/observation.py#L61-L101)

### Station URL Pattern

**Clarification:** Station API uses `station_number` as lookup field (not `pk`)
- This is intentional good design
- Provides human-readable, stable identifiers
- Independent of database IDs
- Example: `/api/v1/stations/USGS-12345678/`

### Documentation Reorganization

**Archived 21 outdated files to Documentation/Archive:**
- API_TEST_RESULTS.md
- DASHBOARD_INTEGRATION_GUIDE.md
- DATA_PULL_FIX_SUMMARY.md
- DEPLOYMENT.md
- DJANGO_MIGRATION.md
- DJANGO_QUICKSTART.md
- EC_INTEGRATION_SUMMARY.md
- FRONTEND_SESSION_SUMMARY.md
- FRONTEND_TEST_RESULTS.md
- RASTER_PULL_FIXES_JAN29.md
- SESSION_JAN_29_CONFIG_TESTING.md
- STATUS.md
- TEST_QUICK_START.md
- TEST_SUITE_REPORT.md
- USGS_DATA_PULL_DIAGNOSIS.md
- USGS_HISTORICAL_POPULATION_GUIDE.md

**Created new comprehensive guide:**
- Documentation/DEPLOYMENT_GUIDE.md (820 lines)

---

## 6. Commit Summary

**Commit:** `8eaec3e` - "Add historical backfill configurations and comprehensive API tests"

**Files Changed:** 27 files
- **Insertions:** +3,958 lines
- **Deletions:** -314 lines

**Key Changes:**
1. Created two historical backfill configurations in deploy.py
2. Verified actual station counts via database queries
3. Updated DEPLOYMENT_GUIDE.md with accurate counts and instructions
4. Created comprehensive API test suites (43 tests, all passing)
5. Archived 21 outdated documentation files
6. Disabled CSV export feature (not needed)
7. Fixed all test URL patterns to use station_number lookup

**Pushed to:** `origin/feature/raster-data-gee`

---

## 7. System Status

### Current Database State

**Stations:**
- Active stations: 2,890 (all HUC 17)
- Master stations: 5,394 (HUC 14-18)

**Pull Configurations (Total: 6):**
1. NWRFC Short-Range Forecasts - Daily at 8:30 AM PST (18-hour forecasts)
2. NWRFC Medium-Range Forecasts - Daily at 8:30 AM PST (10-day forecasts)
3. PNW USGS Daily Mean Discharge - Daily at 9:00 AM PST (ongoing updates)
4. PNW USGS Real-time 7-Day Window - Every 4 hours (15-minute data)
5. **HUC 17 Historical Backfill** - Manual, one-time (~2,890 stations, **ENABLED**)
6. **HUC 14-18 Historical Backfill** - Manual, one-time (~5,394 stations, **DISABLED**)

### Test Status

**API Tests:** 43/43 passing (100%)
- Pagination tests: 5/5 passing
- Date filtering tests: 4/4 passing
- Ordering tests: 3/3 passing
- Multi-field filtering: 4/4 passing
- Search tests: 3/3 passing
- Error handling: 8/8 passing
- Empty results: 3/3 passing
- Boundary conditions: 4/4 passing
- Content type: 1/1 passing
- Method restrictions: 3/3 passing
- Response structure: 3/3 passing
- Validation: 2/2 passing

---

## 8. Next Steps

### Immediate

1. **Test deploy.py with new configurations:**
   ```bash
   python scripts/deploy.py --dry-run
   ```

2. **Decide on backfill strategy:**
   - Option A: Run HUC 17 backfill only (2,890 stations)
   - Option B: Sync additional HUC regions first, then run HUC 14-18 backfill
   - Option C: Run both sequentially

3. **Monitor initial backfill:**
   - Watch Celery logs
   - Track database growth
   - Verify data quality

### Short Term

4. **Sync additional HUC regions** (if desired):
   ```bash
   python manage.py sync_stations --huc 14 --huc 15 --huc 16 --huc 18
   ```

5. **Enable HUC 14-18 backfill** (after HUC 17 completes):
   ```bash
   python manage.py shell
   >>> config = PullConfiguration.objects.get(name__contains="HUC 14-18")
   >>> config.is_enabled = True
   >>> config.save()
   ```

6. **Run existing API tests:**
   ```bash
   python manage.py test tests.test_api_observations
   python manage.py test tests.test_api_forecasts
   python manage.py test tests.test_api_raster
   ```

---

## 9. Performance Expectations

### HUC 17 Historical Backfill

**Time Estimates:**
- **Per Station:** 1-10 seconds (depending on record length and USGS API)
- **2,890 Stations:** 1-8 hours (with 1 second delay between stations)

**Data Volume:**
- **Daily Mean Records:** ~365 records per year per station
- **30 Years:** ~11,000 records per station
- **Total:** 30-50 million observations (5-15 GB)

### HUC 14-18 Historical Backfill

**Time Estimates:**
- **5,394 Stations:** 2-15 hours

**Data Volume:**
- **Total:** 80-150 million observations (15-40 GB)

### Database Disk Space

**Recommendations:**
- Ensure 50-100 GB available for HUC 14-18
- Monitor disk space during backfill
- Consider running during off-peak hours

---

## 10. Technical Notes

### Why Two Configurations?

1. **Risk Management:** Test with smaller HUC 17 first
2. **Resource Control:** Separate enable/disable control
3. **Monitoring:** Easier to track progress separately
4. **Flexibility:** Can run regions independently if needed

### Replace Strategy Benefits

- Prevents duplicate observations on re-runs
- Safe to run multiple times
- Handles gaps automatically
- Uses `ignore_conflicts=True` in bulk_create

### Station Sync Consideration

- Currently only HUC 17 stations are synced to active Station table
- To run HUC 14-18 backfill with all 5,394 stations, first sync additional regions:
  ```bash
  python manage.py sync_stations --huc 14 --huc 15 --huc 16 --huc 18
  ```

---

## 11. Resources

**Files:**
- [scripts/deploy.py](../scripts/deploy.py) - Deployment automation
- [Documentation/DEPLOYMENT_GUIDE.md](../Documentation/DEPLOYMENT_GUIDE.md) - Complete deployment guide
- [TEST_RESULTS.md](../TEST_RESULTS.md) - API test summary

**Documentation:**
- [README.md](../README.md) - Main project documentation
- [Documentation/README.md](../Documentation/README.md) - Documentation index

**API:**
- Swagger UI: http://localhost:8000/api/v1/docs/
- ReDoc: http://localhost:8000/api/v1/redoc/

---

**Session Completed:** February 4, 2026  
**Duration:** ~2 hours  
**Status:** ✅ Ready for backfill execution
