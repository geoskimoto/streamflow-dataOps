# Phase 16: NOAA RFC Historical Forecast Population - IMPLEMENTATION PLAN

**Date:** January 29, 2026  
**Priority:** HIGH  
**Status:** 🟡 FRAMEWORK COMPLETE - Scraper Implementation Needed

---

## ✅ Phase 16.1: Database Schema Fix - COMPLETE

**Completed:** January 29, 2026

**Changes Made:**
1. ✅ Added `forecast_type` field to ForecastRun model (short/medium/long)
2. ✅ Added unique constraint on (station, source, run_date, forecast_type)
3. ✅ Added composite index on (station, run_date, forecast_type)
4. ✅ Created and applied migration 0010_add_forecast_type_to_forecast_run.py

**Schema Now Supports:**
- Multiple forecast types per station/run_date (short vs medium)
- Duplicate prevention via unique constraint
- Efficient queries by forecast type

---

## ✅ Phase 16.2: Population Framework - COMPLETE

**Completed:** January 29, 2026

**Files Created:**
1. `src/acquisition/rfc_forecast_population.py` (~600 lines)
   - RFCForecastPopulationService class
   - Station discovery by RFC/HUC/LID
   - NWRFC scraping framework (URLs, parsing structure)
   - Bulk population with respectful delays

2. `apps/streamflow/management/commands/populate_rfc_forecasts.py` (~350 lines)
   - Complete CLI with 11 arguments
   - Dry-run support
   - Graceful shutdown (Ctrl+C)
   - Progress tracking and summary

**Command Usage:**
```bash
# Populate short-range forecasts for all NWRFC stations
python manage.py populate_rfc_forecasts --rfc NWRFC --forecast-type short

# Test with specific stations
python manage.py populate_rfc_forecasts --station ABOM8 --forecast-type short --dry-run

# Populate medium-range for HUC 17
python manage.py populate_rfc_forecasts --huc 17 --forecast-type medium --limit 10
```

**Status:** Framework is complete and tested. Station discovery, argument parsing, database operations all working.

---

## 🔴 Phase 16.3: RFC Website Scraping - NOT COMPLETE

**Status:** Needs Implementation

**Current State:**
The scraping framework attempts to fetch from 3 potential NWRFC URLs:
- `https://www.nwrfc.noaa.gov/river/station/flowplot/flowplot.cgi?lid={LID}`
- `https://www.nwrfc.noaa.gov/data/rfc_fcst/{LID}.csv`
- `https://www.nwrfc.noaa.gov/river/station/{LID}/forecasts`

**Test Result:** All URLs return 404 or unparseable content.

**Root Cause:** RFC websites don't provide straightforward public access to historical forecast archives. Each RFC has different website structures, and many don't expose historical forecasts at all.

**Next Steps Required:**

1. **Manual RFC Website Research** (4-6 hours per RFC)
   - Visit actual NWRFC website: https://www.nwrfc.noaa.gov/
   - Find where historical forecasts are located (if available)
   - Document actual URL patterns and data formats
   - Determine how far back historical data goes
   - Check robots.txt and terms of service

2. **Implement Actual Scraping Logic** (6-10 hours)
   - Build parsers for actual NWRFC HTML/CSV/JSON format
   - Extract issue dates and forecast points correctly
   - Handle pagination if data is split across pages
   - Test with multiple stations to ensure robustness

3. **Expand to Other RFCs** (3-5 hours per RFC)
   - Repeat research for CNRFC, CBRFC, etc.
   - Build RFC-specific scraper methods
   - Document each RFC's data availability

**Alternative Approach:** 
Instead of scraping historical data (which may not exist), focus on **collecting forecasts going forward** via PullConfiguration. This gives you high-quality forecast archive without legal/technical scraping issues.

---

## 📊 Current Capabilities

**What Works Now:**
- ✅ Database schema supports multiple forecast types
- ✅ Command discovers RFC stations by RFC/HUC/LID
- ✅ Respects existing data (skip or --force)
- ✅ Dry-run mode for safe testing
- ✅ Graceful shutdown and error handling
- ✅ Bulk processing with delays

**What Doesn't Work:**
- ❌ Actual scraping of historical forecasts (URLs don't exist as guessed)
- ❌ Parsing of RFC website content (need real data format)

---

## 🎯 Recommendation

**Option A: Research & Implement NWRFC Scraping** (10-15 hours)
- Manually research actual NWRFC website structure
- Implement real scraping logic
- Test with production data
- Document findings

**Option B: Focus on Forward Collection** (Already working) ⭐ **RECOMMENDED**
- PullConfiguration already fetches current forecasts
- Database stores them with issue times  
- After 3-6 months, you'll have robust training dataset
- No legal concerns, no fragile scrapers
- Use existing infrastructure

**My Recommendation:** Go with **Option B** unless you urgently need historical data. The framework is ready if you want to implement scraping later, but forward collection is more sustainable.

---

## Overview

Create a system to populate historical NOAA River Forecast Center (RFC) forecast runs for model training and error analysis. Unlike observed discharge data, forecasts are issued multiple times per day/week, creating a rich dataset for analyzing forecast skill over time.

### Business Goal
Train machine learning models to predict forecast error by analyzing:
- Forecast vs observed discharge differences
- Forecast performance by lead time (1-day, 3-day, 7-day ahead)
- Seasonal patterns in forecast accuracy
- Station-specific forecast biases

---

## Critical Research: NOAA RFC Forecast Data Availability

### ⚠️ **MAJOR CONSTRAINT DISCOVERED**

The NOAA Water API (`https://api.water.noaa.gov/nwps/v1`) provides **ONLY THE CURRENT/LATEST FORECAST**, not historical forecasts.

**API Limitations:**
```python
# This endpoint returns ONLY the most recent forecast:
GET /gauges/{lid}/stageflow?forecast=short

Response:
{
    "forecast": {
        "issueTime": "2026-01-29T12:00:00Z",  # Latest issue only
        "data": [...]  # Current forecast points
    }
}
```

**No historical forecast API exists in NOAA Water API v1.**

### Historical Forecast Data Sources

After researching NOAA RFC operations, there are **3 possible approaches**:

#### Option 1: Scrape RFC Websites Directly 🔥 (Most Feasible)
Each RFC maintains public web pages with historical forecasts.

**Example - Northwest RFC (NWRFC):**
```
https://www.nwrfc.noaa.gov/river/station/flowplot/flowplot.cgi?lid=AAMC1
https://www.nwrfc.noaa.gov/data/rfc_fcst/{LID}.csv
```

**Characteristics:**
- ✅ Publicly accessible
- ✅ Historical data often available (varies by RFC, typically 30-90 days)
- ❌ Format varies by RFC (12 RFCs, each different)
- ❌ No standardized API
- ❌ Scraping may violate terms of service
- ❌ Fragile (HTML changes break scrapers)

**Example RFCs:**
- NWRFC (Northwest) - https://www.nwrfc.noaa.gov/
- CNRFC (California-Nevada) - https://www.cnrfc.noaa.gov/
- CBRFC (Colorado Basin) - https://www.cbrfc.noaa.gov/
- MARFC (Mid-Atlantic) - https://www.marfc.noaa.gov/
- ...12 total RFCs

#### Option 2: NOAA National Water Model (NWM) Retrospective 📊 (Research Grade)
NOAA provides retrospective NWM forecasts for research.

**Source:** https://registry.opendata.aws/nwm-archive/

**Characteristics:**
- ✅ Comprehensive historical forecasts
- ✅ Standardized format (NetCDF)
- ✅ AWS S3 public dataset
- ❌ Extremely large (petabytes)
- ❌ Different from RFC operational forecasts
- ❌ Requires significant processing/storage
- ❌ Complex to extract station-specific data

**Not practical for operational system.**

#### Option 3: Store Forecasts Going Forward ⭐ (RECOMMENDED)
Start capturing forecasts now for future analysis.

**Approach:**
- Configure PullConfiguration to fetch forecasts daily/hourly
- Store each forecast run with its issue timestamp
- Build historical dataset over time (3-6 months minimum for training)

**Characteristics:**
- ✅ Clean, standardized data
- ✅ Uses existing infrastructure
- ✅ Sustainable long-term
- ❌ No immediate historical data
- ❌ Requires waiting to accumulate dataset

---

## Recommended Implementation Strategy

### Phase 16A: Enhanced Forecast Collection (IMMEDIATE)
Improve current forecast storage to build historical dataset going forward.

### Phase 16B: RFC Website Scraping (OPTIONAL - if historical data urgently needed)
Build RFC-specific scrapers for recent historical forecasts.

### Phase 16C: Analysis Tools (FUTURE)
Tools to analyze forecast error once sufficient data accumulated.

---

## Phase 16A: Enhanced Forecast Collection (Recommended First Step)

### Goals
1. Store forecasts with proper issue timestamps (run_date)
2. Store multiple forecasts per day per station
3. Enable querying forecasts by issue date and lead time
4. Prevent duplicate forecast storage

### Database Schema Changes

#### Problem with Current Schema
```python
class ForecastRun(models.Model):
    station = ForeignKey(Station)
    source = CharField  # 'NOAA_RFC'
    run_date = DateTimeField  # Issue timestamp
    data = JSONField  # [{'date': '2026-02-01', 'value': 15000}, ...]
    rmse = DecimalField
```

**Issues:**
- No unique constraint on (station, run_date) → can store duplicates
- No efficient way to query by forecast lead time
- `data` JSON makes analysis difficult

#### Proposed Enhanced Schema

**Option A: Keep Existing Model, Add Constraints**
```python
class ForecastRun(models.Model):
    # ... existing fields ...
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['station', 'source', 'run_date'],
                name='unique_forecast_run'
            )
        ]
```

**Option B: Add ForecastPoint Model for Better Analysis** (RECOMMENDED)
```python
class ForecastRun(models.Model):
    """Metadata about a forecast issuance."""
    station = ForeignKey(Station)
    source = CharField  # 'NOAA_RFC'
    issue_time = DateTimeField  # When forecast was issued (renamed from run_date)
    forecast_type = CharField  # 'short', 'medium', 'long'
    rmse = DecimalField(null=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['station', 'source', 'issue_time', 'forecast_type'],
                name='unique_forecast_run'
            )
        ]

class ForecastPoint(models.Model):
    """Individual forecast data point."""
    forecast_run = ForeignKey(ForecastRun, related_name='points')
    valid_time = DateTimeField  # When forecast is valid for
    discharge = DecimalField  # Predicted discharge value
    unit = CharField(default='cfs')
    lead_time_hours = IntegerField  # Calculated: (valid_time - issue_time) in hours
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['forecast_run', 'valid_time'],
                name='unique_forecast_point'
            )
        ]
        indexes = [
            models.Index(fields=['valid_time', 'lead_time_hours']),
        ]
```

**Benefits of Option B:**
- ✅ Easy to query forecasts by lead time
- ✅ Enables SQL analysis of forecast error
- ✅ Can join with DischargeObservation on valid_time
- ✅ Efficient storage (no JSON parsing)
- ✅ Better for model training queries

### Management Command: `populate_rfc_forecasts`

**Purpose:** Fetch and store current forecasts for all RFC stations (run daily/hourly to build historical dataset).

**Usage:**
```bash
# Fetch forecasts for all NWRFC stations
python manage.py populate_rfc_forecasts --rfc NWRFC

# Specific stations
python manage.py populate_rfc_forecasts --station AAMC1 --station AGNO3

# All stations in HUC 17
python manage.py populate_rfc_forecasts --huc 17

# Dry run
python manage.py populate_rfc_forecasts --rfc NWRFC --dry-run

# Forecast type
python manage.py populate_rfc_forecasts --rfc NWRFC --forecast-type short
```

**Arguments:**
- `--rfc` - RFC code (NWRFC, CNRFC, etc.)
- `--huc` - HUC code (filters stations)
- `--station` - Specific NOAA LID(s)
- `--forecast-type` - short/medium/long (default: short)
- `--dry-run` - Show what would be fetched
- `--limit` - Limit stations (testing)

**Logic:**
1. Discover stations (from Station or MasterStation with agency='NOAA_RFC')
2. For each station:
   - Fetch current forecast via NOAAClient.get_rfc_forecast()
   - Check if forecast already exists (by issue_time)
   - If new, create ForecastRun and ForecastPoint records
   - If duplicate, skip
3. Report statistics

**Expected Performance:**
- ~2-5 seconds per station
- 100 stations = 3-8 minutes
- Should be run **hourly or every 6 hours** to capture forecast updates

### Service Layer: `ForecastPopulationService`

**File:** `src/acquisition/forecast_population.py`

**Methods:**
```python
class ForecastPopulationService:
    def __init__(self):
        self.noaa_client = NOAAClient()
    
    def populate_station_forecast(
        self,
        station: Station,
        forecast_type: str = 'short',
        force: bool = False
    ) -> Dict:
        """
        Fetch and store current forecast for a station.
        
        Returns:
            {
                'station_number': str,
                'status': 'success' | 'duplicate' | 'no_forecast' | 'failed',
                'issue_time': datetime,
                'forecast_points': int,
                'error': str (if failed)
            }
        """
    
    def discover_rfc_stations(
        self,
        rfc_code: Optional[str] = None,
        huc_codes: Optional[List[str]] = None,
        station_numbers: Optional[List[str]] = None
    ) -> List[Station]:
        """Discover NOAA_RFC stations matching criteria."""
    
    def populate_bulk(
        self,
        stations: List[Station],
        forecast_type: str = 'short'
    ) -> Dict:
        """Populate forecasts for multiple stations."""
```

---

## Phase 16B: RFC Website Scraping (Optional - Historical Data)

### ⚠️ WARNING: Proceed with Caution

**Legal/Ethical Considerations:**
- Check each RFC's Terms of Service
- Respect robots.txt
- Add delays between requests (2-5 seconds)
- Identify your scraper in User-Agent
- Consider contacting RFC directly for bulk data access

### Implementation Approach

Each RFC has different website structure. Would need **RFC-specific scrapers**.

**Example: Northwest RFC (NWRFC) Scraper**

**Forecast Archive URL:**
```
https://www.nwrfc.noaa.gov/river/station/flowplot/flowplot.cgi?lid=AAMC1&pe=HG&v=1.0
```

**Data Format:** Often CSV or HTML tables

**Scraper Structure:**
```python
class NWRFCScraper:
    """Scraper for Northwest RFC historical forecasts."""
    
    def __init__(self):
        self.base_url = "https://www.nwrfc.noaa.gov"
    
    def get_historical_forecasts(
        self,
        lid: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """
        Scrape historical forecasts for a station.
        
        Returns list of forecast runs with their data.
        """
        # Parse HTML/CSV from RFC website
        # Extract issue times and forecast values
        # Return structured data
```

**Challenges:**
- 12 different RFCs = 12 different scrapers
- Fragile (breaks when website changes)
- May have gaps in historical data
- Time-consuming to develop and maintain

**Recommendation:** Only implement if absolutely need historical data AND have confirmed with RFC staff that scraping is acceptable.

---

## Phase 16C: Forecast Analysis Tools (Future)

Once sufficient forecasts accumulated (3-6 months), create analysis tools.

### Analysis Queries

**1. Forecast Error by Lead Time:**
```sql
SELECT 
    fp.lead_time_hours,
    AVG(fp.discharge - do.discharge) as mean_error,
    STDDEV(fp.discharge - do.discharge) as error_stddev,
    COUNT(*) as n_forecasts
FROM forecast_point fp
JOIN discharge_observation do 
    ON fp.valid_time = do.observed_at 
    AND fp.forecast_run.station = do.station
WHERE do.type = 'daily_mean'
GROUP BY fp.lead_time_hours
ORDER BY fp.lead_time_hours;
```

**2. Station-Specific Bias:**
```sql
SELECT 
    s.station_number,
    s.name,
    AVG(fp.discharge - do.discharge) as mean_bias,
    COUNT(*) as n_comparisons
FROM forecast_point fp
JOIN forecast_run fr ON fp.forecast_run_id = fr.id
JOIN station s ON fr.station_id = s.id
JOIN discharge_observation do 
    ON fp.valid_time = do.observed_at 
    AND fr.station_id = do.station_id
GROUP BY s.id
ORDER BY ABS(mean_bias) DESC;
```

### Django Management Command: `analyze_forecast_skill`

```bash
# Analyze forecast error for all stations
python manage.py analyze_forecast_skill

# Specific station
python manage.py analyze_forecast_skill --station AAMC1

# By RFC
python manage.py analyze_forecast_skill --rfc NWRFC

# Export to CSV for model training
python manage.py analyze_forecast_skill --output forecast_errors.csv
```

---

## Implementation Timeline

### Phase 16A: Enhanced Forecast Collection (6-8 hours)

| Task | Duration | Priority |
|------|----------|----------|
| **Database Schema** | 2 hours | HIGH |
| - Add ForecastPoint model | 1 hour | |
| - Create migration | 30 min | |
| - Add unique constraints | 30 min | |
| **Service Layer** | 2 hours | HIGH |
| - Create forecast_population.py | 1.5 hours | |
| - Implement duplicate detection | 30 min | |
| **Management Command** | 2 hours | HIGH |
| - Create populate_rfc_forecasts.py | 1.5 hours | |
| - Argument parsing & validation | 30 min | |
| **Testing** | 2 hours | HIGH |
| - Test with NWRFC stations | 1 hour | |
| - Verify duplicate prevention | 1 hour | |

**Total: 8 hours**

### Phase 16B: RFC Scraping (Optional, 20-40 hours)

| Task | Duration | Priority |
|------|----------|----------|
| Scraper for NWRFC | 4-6 hours | MEDIUM |
| Scraper for CNRFC | 4-6 hours | MEDIUM |
| Scraper for additional RFCs | 3-4 hours each | LOW |
| Testing & validation | 4-8 hours | MEDIUM |

**Total: 20-40 hours (only if historical data critical)**

### Phase 16C: Analysis Tools (4-6 hours - FUTURE)

| Task | Duration | Priority |
|------|----------|----------|
| Forecast skill analysis command | 2-3 hours | LOW |
| Export utilities for ML | 1-2 hours | LOW |
| Visualization tools | 1-2 hours | LOW |

**Total: 4-6 hours (implement after data accumulated)**

---

## Questions for You

### 1. Historical Data Urgency
**Q:** Do you need historical forecasts immediately, or can you start collecting today and build the dataset over time?

**Options:**
- **A)** Need historical data ASAP → Implement RFC scraping (Phase 16B) [20-40 hours]
- **B)** Can wait 3-6 months → Just implement enhanced collection (Phase 16A) [8 hours] ⭐ **RECOMMENDED**
- **C)** Want both → Enhanced collection now, scraping later if needed

### 2. Forecast Collection Frequency
**Q:** How often should forecasts be collected?

**Options:**
- **A)** Every hour (comprehensive, many duplicates)
- **B)** Every 6 hours (good balance) ⭐ **RECOMMENDED**
- **C)** Daily (minimal, may miss forecast updates)

RFCs typically issue forecasts:
- **Short-range (18hr):** Multiple times daily
- **Medium-range (10day):** 1-2 times daily
- **Long-range (30day):** Weekly

### 3. Database Schema Choice
**Q:** Should we keep simple JSONField or split into ForecastPoint model?

**Options:**
- **A)** Keep current simple schema (JSONField for data)
  - Pros: Less code, backward compatible
  - Cons: Harder to query, slower analysis
- **B)** Add ForecastPoint model (normalized schema) ⭐ **RECOMMENDED**
  - Pros: Efficient queries, better for ML training
  - Cons: More complex, migration needed

### 4. Scope of RFCs
**Q:** Which RFCs should we support?

**Options:**
- **A)** NWRFC only (your primary region)
- **B)** NWRFC + CNRFC (Pacific coast)
- **C)** All 12 RFCs (nationwide)

For Phase 16A (enhanced collection), this doesn't matter - works for all RFCs via API.  
For Phase 16B (scraping), each RFC requires custom scraper.

### 5. Forecast Types
**Q:** Which forecast horizons to collect?

**Options:**
- **A)** Short-range only (18hr) - most frequent, most accurate
- **B)** Short + Medium (18hr + 10day) ⭐ **RECOMMENDED**
- **C)** All three (short + medium + long)

Storage implications:
- Short: ~30-50 points per forecast
- Medium: ~240 points per forecast  
- Long: ~720 points per forecast

---

## My Recommendations

### Recommended Path: Phase 16A Only (Enhanced Collection)

**Rationale:**
1. **No historical API exists** - Can't easily get past forecasts
2. **Scraping is risky** - Legal concerns, fragile, time-consuming
3. **Future data is valuable** - 6 months of high-quality forecasts better than spotty historical scrapes
4. **Existing infrastructure** - Can use PullConfiguration/Celery for automation
5. **Sustainable** - Will have continuous forecast archive going forward

**What This Gives You:**
- Start collecting forecasts TODAY
- After 30 days: Analyze 1-day ahead forecast skill
- After 90 days: Analyze 3-day ahead forecast skill
- After 180 days: Train initial ML models
- After 1 year: Robust forecast error dataset

**Implementation Steps:**
1. Add ForecastPoint model (better for analysis)
2. Add unique constraints to prevent duplicates
3. Create populate_rfc_forecasts command
4. Configure Celery to run every 6 hours
5. Let it collect data for 3-6 months
6. Then implement Phase 16C analysis tools

**Timeline:** 8 hours implementation + 3-6 months data collection

### If You Need Historical Data Urgently

Then we'd need to:
1. Identify which RFCs are critical (NWRFC? CNRFC?)
2. Research their specific website structures
3. Build custom scrapers for each
4. Accept that data quality may be inconsistent
5. Budget 4-6 hours per RFC for scraper development

**Timeline:** 8 hours (Phase 16A) + 20-40 hours (Phase 16B)

---

## What Would You Like To Do?

Please answer the questions above, and I'll proceed with implementation based on your preferences!

---

**Files to Create (Phase 16A):**
1. `apps/streamflow/migrations/000X_add_forecast_point_model.py` - Database migration
2. `src/acquisition/forecast_population.py` - Service layer (~300 lines)
3. `apps/streamflow/management/commands/populate_rfc_forecasts.py` - CLI (~250 lines)
4. `Documentation/RFC_FORECAST_COLLECTION_GUIDE.md` - Usage guide

**Total new code:** ~550 lines + documentation + tests
