# Phase 15: USGS Historical Data Population System - IMPLEMENTATION PLAN

**Date:** January 29, 2026  
**Priority:** HIGH  
**Estimated Duration:** 4-6 hours

---

## Overview

Create a robust system to populate complete historical discharge records for USGS stations within a specified HUC (Hydrologic Unit Code) or state. The system must handle long-running operations, resume from failures, and check for existing data before fetching. Primary focus on HUC 17 (Columbia River Basin), but designed to work with any HUC or state.

---

## Business Requirements

### User Goals
1. **Bulk Data Population**: Get complete historical records for all USGS stations in a HUC or state
2. **Resume Capability**: If population fails partway, it should resume from where it stopped
3. **Idempotency**: Don't re-fetch data that already exists
4. **Progress Visibility**: Clear feedback on progress (station X of Y, records fetched, errors)
5. **Flexible Selection**: Support HUC-based OR state-based selection

### Primary Use Case
- **HUC 17 (Columbia River Basin)**: ~100-200 USGS stations
- **Complete Records**: Fetch all available historical data (potentially decades)
- **One-Time Operation**: This is for initial population, not ongoing appends (that's handled by PullConfiguration)

### Data Volume Expectations
- **Stations**: 100-200 per HUC (varies)
- **Records per Station**: 10,000-50,000+ (30+ years of daily data)
- **Total Records**: 1M-10M+ observations
- **Estimated Time**: 2-8 hours depending on station count and USGS API throttling

---

## Technical Requirements

### Data Source
- **Provider**: USGS NWIS (via dataretrieval library)
- **Parameter**: 00060 (Discharge)
- **Data Type**: Daily mean values (`get_daily_mean()`)
- **API**: `dataretrieval.nwis.get_dv()`

### Database Strategy
- **Check First**: Query `DischargeObservation` for existing data by station
- **Smart Populate**: Only fetch if:
  - Station has no records, OR
  - Station has partial records (check min/max date vs USGS record period)
- **Bulk Insert**: Use Django's `bulk_create()` with `ignore_conflicts=True` for efficiency
- **Transaction Safety**: Wrap inserts in transactions to handle failures

### Progress Tracking
Leverage existing `PullStationProgress` model:
```python
class PullStationProgress(models.Model):
    configuration = ForeignKey(PullConfiguration)
    station_number = CharField
    last_successful_pull_date = DateTimeField
    consecutive_failures = IntegerField
    is_active = BooleanField
```

**Enhancement Needed:**
- Add `historical_population_complete` boolean field
- Add `historical_population_started_at` datetime field
- Add `historical_population_completed_at` datetime field
- Add `total_historical_records` integer field

### Error Handling
- **Station Failures**: Log and continue to next station (don't abort entire operation)
- **API Rate Limiting**: Implement exponential backoff (already in USGSClient)
- **Database Errors**: Rollback transaction for that station, log error, continue
- **Resumability**: Track progress per station, so can restart without re-fetching completed stations

---

## Implementation Components

### Component 1: Management Command - `populate_usgs_historical`

**Purpose**: Main entry point for historical data population

**Usage Examples:**
```bash
# Populate HUC 17 (Columbia River Basin)
python manage.py populate_usgs_historical --huc 17

# Populate specific state
python manage.py populate_usgs_historical --state WA

# Multiple HUCs
python manage.py populate_usgs_historical --huc 17 --huc 16

# Dry run (check what would be fetched)
python manage.py populate_usgs_historical --huc 17 --dry-run

# Limit stations (for testing)
python manage.py populate_usgs_historical --huc 17 --limit 10

# Resume failed population
python manage.py populate_usgs_historical --huc 17 --resume

# Force repopulate even if complete
python manage.py populate_usgs_historical --huc 17 --force
```

**Command Options:**
- `--huc` (repeatable): HUC code(s) to process
- `--state` (repeatable): State code(s) to process (e.g., WA, OR, ID)
- `--station` (repeatable): Specific station numbers (overrides huc/state)
- `--dry-run`: Show what would be done without fetching
- `--limit`: Limit number of stations (for testing)
- `--resume`: Only process stations that haven't completed
- `--force`: Re-fetch even if already complete
- `--start-date`: Override start date (default: use station record_start_date)
- `--end-date`: Override end date (default: today)
- `--batch-size`: Number of records per bulk insert (default: 1000)
- `--delay`: Seconds between stations (default: 1)

**Output:**
```
====================================================================
USGS HISTORICAL DATA POPULATION
====================================================================
Mode: HUC 17 (Columbia River Basin)
Date Range: Complete historical records (station-specific)
Batch Size: 1000 records
Delay: 1 second between stations

Discovering stations...
  Found 127 USGS stations in HUC 17
  Already complete: 0
  Partially complete: 0
  Not started: 127

Stations to process: 127

====================================================================
STATION 1/127: 14211720 - Johnson Creek at Milwaukie, OR
====================================================================
  Record Period: 1941-01-01 to 2026-01-29 (85 years)
  Existing Records: 0
  Fetching data... ⏳

  ✓ Fetched 31,025 records
  ✓ Inserted 31,025 new records
  ⏱ Time: 4.2 seconds

====================================================================
STATION 2/127: 14128910 - Hood River at Tucker Bridge, OR
====================================================================
  Record Period: 1913-10-01 to 2026-01-29 (112 years)
  Existing Records: 15,230
  Checking for gaps...
  
  ✓ Records complete, skipping
  ⏱ Time: 0.3 seconds

====================================================================
[... progress for all stations ...]
====================================================================

====================================================================
POPULATION COMPLETE
====================================================================
  Total Stations: 127
  Successful: 125 (98%)
  Skipped (already complete): 18
  Failed: 2
  
  Total Records Fetched: 3,847,923
  Total Records Inserted: 3,721,048
  Total Time: 3h 24m 18s
  Average: 96 seconds per station

Failed Stations:
  - 14325000: API timeout after 3 retries
  - 14189500: No data returned (station inactive)

✓ Historical population complete!

Next steps:
  1. Set up PullConfiguration for ongoing appends
  2. Review failed stations and retry manually if needed
```

### Component 2: Historical Population Service

**File**: `src/acquisition/historical_population.py`

**Class**: `HistoricalPopulationService`

**Methods:**
```python
class HistoricalPopulationService:
    """Service for populating historical USGS data."""
    
    def __init__(self, batch_size=1000, delay=1):
        self.usgs_client = USGSClient()
        self.batch_size = batch_size
        self.delay = delay
    
    def populate_station(
        self,
        station_number: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Populate historical data for a single station.
        
        Returns:
            {
                'station_number': str,
                'status': 'success' | 'skipped' | 'failed',
                'records_fetched': int,
                'records_inserted': int,
                'existing_records': int,
                'duration_seconds': float,
                'error': str (if failed)
            }
        """
        
    def check_station_status(self, station_number: str) -> Dict:
        """
        Check existing data coverage for a station.
        
        Returns:
            {
                'station_number': str,
                'has_data': bool,
                'record_count': int,
                'min_date': datetime,
                'max_date': datetime,
                'expected_start': datetime,  # from Station.record_start_date
                'expected_end': datetime,  # from Station.record_end_date
                'is_complete': bool,  # True if covers expected range
                'gaps': List[Tuple[datetime, datetime]]  # date ranges with no data
            }
        """
    
    def discover_stations(
        self,
        huc_codes: Optional[List[str]] = None,
        state_codes: Optional[List[str]] = None,
        station_numbers: Optional[List[str]] = None
    ) -> List[Station]:
        """
        Discover stations matching criteria.
        
        Returns list of Station objects ordered by station_number.
        """
    
    def populate_bulk(
        self,
        stations: List[Station],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        resume: bool = False,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Populate historical data for multiple stations.
        
        Returns:
            {
                'total_stations': int,
                'successful': int,
                'skipped': int,
                'failed': int,
                'total_records_fetched': int,
                'total_records_inserted': int,
                'duration_seconds': float,
                'failed_stations': List[Dict],  # details of failures
                'results': List[Dict]  # per-station results
            }
        """
```

### Component 3: Database Migration

**File**: `apps/streamflow/migrations/000X_add_historical_population_tracking.py`

**Changes:**
```python
# Add fields to PullStationProgress
operations = [
    migrations.AddField(
        model_name='pullstationprogress',
        name='historical_population_complete',
        field=models.BooleanField(default=False),
    ),
    migrations.AddField(
        model_name='pullstationprogress',
        name='historical_population_started_at',
        field=models.DateTimeField(null=True, blank=True),
    ),
    migrations.AddField(
        model_name='pullstationprogress',
        name='historical_population_completed_at',
        field=models.DateTimeField(null=True, blank=True),
    ),
    migrations.AddField(
        model_name='pullstationprogress',
        name='total_historical_records',
        field=models.IntegerField(default=0),
    ),
]
```

**Or**: Create new model `HistoricalPopulationProgress` (cleaner separation):
```python
class HistoricalPopulationProgress(models.Model):
    station_number = models.CharField(max_length=50, unique=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('not_started', 'Not Started'),
            ('in_progress', 'In Progress'),
            ('complete', 'Complete'),
            ('failed', 'Failed'),
            ('partial', 'Partial')
        ],
        default='not_started'
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    records_fetched = models.IntegerField(default=0)
    records_inserted = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    attempts = models.IntegerField(default=0)
```

---

## Implementation Steps

### Phase 15.1: Database Schema (30 min)
1. Create migration for `HistoricalPopulationProgress` model
2. Run migration
3. Update admin.py to register model
4. Test model creation

### Phase 15.2: Service Layer (2 hours)
1. Create `src/acquisition/historical_population.py`
2. Implement `HistoricalPopulationService` class
3. Implement `check_station_status()` method
4. Implement `populate_station()` method with:
   - Status check
   - USGS data fetch
   - Bulk insert with conflict handling
   - Progress tracking
   - Error handling
5. Implement `discover_stations()` method
6. Implement `populate_bulk()` method
7. Add comprehensive logging

### Phase 15.3: Management Command (1.5 hours)
1. Create `apps/streamflow/management/commands/populate_usgs_historical.py`
2. Implement argument parsing
3. Implement dry-run mode
4. Implement progress display
5. Implement resume logic
6. Add signal handling (Ctrl+C graceful shutdown)
7. Create summary report

### Phase 15.4: Testing (1.5 hours)
1. **Unit Tests**: Test service methods with mock data
2. **Integration Test**: Test with 5-10 real stations
3. **Dry Run Test**: Verify dry-run doesn't write data
4. **Resume Test**: Test resume capability
5. **Error Handling**: Test API failures, database errors
6. **Large Scale Test**: Test with 50+ stations

### Phase 15.5: Documentation (30 min)
1. Create usage guide
2. Add to QUICKSTART.md
3. Update README.md
4. Document in Journal/PHASE_15_COMPLETE.md

---

## Questions for User

### 1. Station Selection
**Q**: Should we filter stations to only those that are currently active (is_active=True)?  
**Options**:
- A) Only populate active stations (most common use case)
- B) Populate all stations in HUC/state (preserves historical data)
- C) Make it configurable with `--include-inactive` flag

**My Recommendation**: Option C - default to active only, but allow --include-inactive flag

---

### 2. Data Type Priority
**Q**: Should we focus only on daily mean data, or also support instantaneous (15-min) data?  
**Context**: 
- Daily mean: ~30,000 records per 30 years
- Instantaneous: ~1,000,000 records per 30 years (35,040 per year)
**Options**:
- A) Daily mean only (manageable, most useful for long-term analysis)
- B) Support both with flag (e.g., `--data-type daily_mean|instantaneous`)
- C) Daily mean first, instantaneous as future enhancement

**My Recommendation**: Option A for initial implementation - daily mean only. Instantaneous can be Phase 15.5.

---

### 3. Progress Model Strategy
**Q**: Should we extend `PullStationProgress` or create new `HistoricalPopulationProgress` model?  
**Options**:
- A) Extend PullStationProgress (requires linking to a dummy PullConfiguration)
- B) Create HistoricalPopulationProgress (cleaner, but adds complexity)
- C) Don't track in database, use file-based checkpointing

**My Recommendation**: Option B - cleaner separation of concerns, easier to query

---

### 4. MasterStation vs Station
**Q**: Should we work with `MasterStation` (all USGS stations) or `Station` (working set)?  
**Context**:
- `MasterStation`: Contains all USGS stations from `load_master_stations` command
- `Station`: Working set of stations (subset of MasterStation)
**Options**:
- A) Work with Station only (requires running sync_stations first)
- B) Work with MasterStation, auto-create Station records if needed
- C) Flexible - check Station first, fallback to MasterStation

**My Recommendation**: Option B - auto-create Station records during population for convenience

---

### 5. Date Range Defaults
**Q**: What should be the default date range if station metadata is incomplete?  
**Context**: Some stations may not have record_start_date/record_end_date populated
**Options**:
- A) Fail and require manual date specification
- B) Use safe default (e.g., 1900-01-01 to today)
- C) Query USGS API for station info first to get actual dates

**My Recommendation**: Option C - query station info from USGS if dates missing

---

### 6. Concurrent Processing
**Q**: Should we support multi-threaded/async processing for faster population?  
**Context**: 
- Sequential: Safe, simple, ~100 stations * 3 seconds = 5 minutes + data fetch time
- Concurrent: Faster, but more complex, risk of overwhelming USGS API
**Options**:
- A) Sequential only (simple, safe)
- B) Add optional `--workers N` flag for concurrent processing
- C) Sequential for Phase 15, concurrent as future enhancement

**My Recommendation**: Option C - start sequential, add concurrency in Phase 15.5 if needed

---

### 7. Existing Data Strategy
**Q**: When we find existing data, how should we handle gaps?  
**Context**: Station might have records for 2000-2010 and 2020-2026, missing 2010-2020
**Options**:
- A) Skip station entirely if any data exists (safest)
- B) Detect gaps and fill them (complex but complete)
- C) Compare date range, only fetch if expected range not covered

**My Recommendation**: Option B - detect and fill gaps for truly complete records

---

### 8. Batch Size
**Q**: What batch size for bulk inserts?  
**Context**: Trade-off between memory usage and database round-trips
**Options**:
- A) Small (100-500): Less memory, more DB calls
- B) Medium (1000-2000): Balanced
- C) Large (5000+): Fewer DB calls, more memory

**My Recommendation**: Option B - 1000 records per batch (configurable via --batch-size)

---

## Success Criteria

### Functional Requirements Met
- ✅ Can populate all USGS stations in HUC 17
- ✅ Can populate all USGS stations in a state
- ✅ Doesn't re-fetch existing data
- ✅ Resumes from failure point
- ✅ Provides clear progress feedback
- ✅ Handles API errors gracefully
- ✅ Creates Station records if they don't exist

### Performance Requirements
- ✅ Processes 100 stations in < 4 hours
- ✅ Uses bulk inserts for efficiency
- ✅ Doesn't exceed USGS API rate limits

### Reliability Requirements
- ✅ Graceful Ctrl+C handling
- ✅ Transaction safety (no partial station records)
- ✅ Comprehensive error logging
- ✅ Resume capability tested

---

## Estimated Timeline

| Phase | Task | Duration | Dependencies |
|-------|------|----------|--------------|
| 15.1 | Database schema | 30 min | None |
| 15.2 | Service layer | 2 hours | 15.1 |
| 15.3 | Management command | 1.5 hours | 15.2 |
| 15.4 | Testing | 1.5 hours | 15.3 |
| 15.5 | Documentation | 30 min | 15.4 |
| **TOTAL** | **End-to-end** | **6 hours** | |

**Add buffer**: 1-2 hours for debugging and refinements  
**Total estimate**: 7-8 hours

---

## Files to Create

1. `apps/streamflow/migrations/000X_add_historical_population_tracking.py` - Database schema
2. `src/acquisition/historical_population.py` - Service layer (~400 lines)
3. `apps/streamflow/management/commands/populate_usgs_historical.py` - CLI (~300 lines)
4. `tests/test_historical_population.py` - Test suite (~200 lines)
5. `Journal/PHASE_15_HISTORICAL_POPULATION.md` - Documentation

**Total new code**: ~900 lines + tests

---

## Risk Assessment

### Low Risk
- ✅ Using proven USGS client (already working)
- ✅ Database models well-established
- ✅ Bulk insert patterns proven in raster system

### Medium Risk
- ⚠️ API rate limiting (mitigated by delays and retries)
- ⚠️ Long-running operations (mitigated by progress tracking and resume)
- ⚠️ Database performance with millions of records (mitigated by bulk inserts and indexes)

### Mitigations
- Start with small test (10 stations)
- Monitor USGS API response times
- Use database indexes on (station, observed_at, type)
- Implement exponential backoff for API errors

---

## Future Enhancements (Phase 15.5+)

1. **Concurrent Processing**: Add `--workers` flag for parallel processing
2. **Instantaneous Data**: Support 15-min data with `--data-type instantaneous`
3. **Web UI**: Create Django admin action for population
4. **Smart Gap Detection**: Identify and report suspicious gaps in data
5. **Data Quality Checks**: Validate discharge values (no negatives, check outliers)
6. **Export/Import**: Export populated data for backup
7. **Regional Variants**: Support Environment Canada historical data

---

**Status**: ⏳ AWAITING USER APPROVAL  
**Next Action**: Answer questions above, then proceed with implementation
