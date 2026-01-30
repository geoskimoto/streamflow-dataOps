# Raster Data Source Test Results
## Date: January 29, 2026

## Summary of Issues Found

### 1. **NOAA RTMA (NOMADS)** - ✅ **WORKING** (with database fix)
**Status**: Successfully downloads and processes GRIB2 files

**Issues Found & Fixed**:
- Database schema issue: `thumbnail_path` had NOT NULL constraint
- **Fix Applied**: Added `null=True` to model field, created migration

**Test Results**:
- ✅ Successfully downloaded 2 hours of RTMA data
- ✅ Converted GRIB2 to GeoTIFF
- ✅ Extracted variables: dpt2m (dewpoint temperature)
- ✅ Files created: ~86 KB per layer

**Data Retention**: NOMADS only keeps last 2-3 days
**Recommended Configuration**: `lookback_days=1` (maximum 2 days)

---

### 2. **NASA MODIS (Aqua & Terra)** - ❌ **FAILED** - HDF4 Processing Issue
**Status**: Downloads files but cannot process them

**Error Message**:
```
Failed to open MODIS tile: HDF4_EOS:EOS_GRID:"...MOD11A1.A2026023.h09v04.061.2026024091410.hdf":MODIS_Grid_Daily_1km_LST:LST_Day_1km: No such file or directory
Failed to mosaic MODIS tiles: No valid MODIS tiles to mosaic
```

**Root Cause**: 
- Files download successfully from NASA EarthData
- GDAL cannot open HDF4 files (driver issue or file corruption)
- Files may be incomplete/corrupt or GDAL lacks HDF4 support

**Investigation Needed**:
1. Verify GDAL HDF4 drivers: `gdalinfo --formats | grep HDF4`
2. Check downloaded file integrity
3. Test manual file opening: `gdalinfo <path-to-hdf>`
4. May need to install HDF4 libraries

---

### 3. **NASA GPM IMERG** - ❌ **FAILED** - No Data Found
**Status**: No data available for requested dates

**Error Message**:
```
No GPM data found for 2026-01-23
No EarthData data available for precipitation at 2026-01-23
```

**Root Cause**: Data for Jan 23-24, 2026 not available (3-5 day processing lag)

**Solution**: Use dates 5-7 days in the past

---

### 4. **NASA SMAP L4** - ❌ **NOT IMPLEMENTED**
**Status**: EarthData client doesn't have SMAP handler

**Error Message**:
```
Unknown EarthData dataset: SPL4SMGP_008
```

**Root Cause**: `earthdata_client.py` missing SMAP implementation

**Implementation Needed**:
```python
# In earthdata_client.py _fetch_earthdata_layer()
if 'SPL4SMGP' in dataset.collection_id or 'SMAP' in dataset.name:
    metadata = client.get_smap_data(
        variable=earthdata_var,
        date=timestamp,
        bbox=bbox,
        output_path=file_path
    )
```

---

### 5. **Database Schema Issue** - ✅ **FIXED**
**Issue**: `thumbnail_path` column had NOT NULL constraint

**Error**:
```
null value in column "thumbnail_path" of relation "raster_layers" violates not-null constraint
```

**Fix Applied**:
- Changed model field: `thumbnail_path = models.CharField(..., null=True, blank=True)`
- Created migration: `0008_alter_rasterlayer_thumbnail_path.py`
- Applied successfully

---

## Test Results Summary

| Dataset | Status | Download | Process | Notes |
|---------|--------|----------|---------|-------|
| **NOAA RTMA** | ✅ PASS | ✅ | ✅ | Working after DB fix |
| **MODIS Aqua** | ❌ FAIL | ✅ | ❌ | HDF4 processing error |
| **MODIS Terra** | ❌ FAIL | ✅ | ❌ | HDF4 processing error |
| **GPM IMERG** | ⚠️ SKIP | ⚠️ | - | No data for test dates |
| **SMAP L4** | ❌ FAIL | - | - | Not implemented |

---

## Data Retention Policies by Source

| Data Source | Provider | Retention Period | Recommended Lookback | Update Frequency |
|------------|----------|------------------|---------------------|------------------|
| **RTMA** | NOAA NOMADS | 2-3 days | 0-1 days | Hourly |
| **SMAP** | NASA EarthData | Indefinite | 3-7 days (processing lag) | Daily |
| **MODIS** | NASA EarthData | Indefinite | 3-7 days (processing lag) | Daily |
| **GPM IMERG** | NASA EarthData | Indefinite | 3-7 days (processing lag) | Daily |

---

## Priority Fixes Needed

1. **CRITICAL**: Implement SMAP handler in earthdata_client.py
2. **HIGH**: Debug MODIS HDF4 processing (check GDAL drivers)
3. **MEDIUM**: Verify GPM with appropriate dates
4. **MEDIUM**: Add better date range validation (check data availability windows)

---

## Recommended Configuration Updates

### For Automated Scheduled Pulls:

**RTMA (Hourly)**:
```python
RasterPullConfiguration(
    dataset=NOAA_RTMA,
    lookback_days=0,  # Current day only
    # Pull runs hourly, gets latest available
)
```

**NASA Products (Daily)**:
```python
RasterPullConfiguration(
    dataset=NASA_SMAP_L4,  # or MODIS, GPM
    lookback_days=5,  # 5 days back to allow for processing lag
)
```

---

## Next Steps

1. **Install/verify HDF4 support**:
   ```bash
   gdalinfo --formats | grep HDF4
   # If missing, may need: apt-get install libhdf4-dev
   ```

2. **Implement SMAP in earthdata_client.py**:
   - Add SMAP collection handling
   - Map variable names correctly
   - Test with historical dates (5+ days back)

3. **Re-run comprehensive test**:
   ```bash
   python manage.py test_raster_sources --cleanup
   ```

4. **Verify all data sources working before production deployment**
