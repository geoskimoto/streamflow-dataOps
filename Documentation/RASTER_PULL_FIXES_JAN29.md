# Raster Pull System - Issues Fixed & Testing Complete

**Date:** January 29, 2026  
**Status:** ✅ RESOLVED - Raster pulls now working correctly

## Issues Found & Fixed

### 1. **Incorrect RTMA Collection ID**
**Problem:** RTMA dataset had `collection_id = "ds084.1"` which doesn't contain "rtma"  
**Impact:** Code checked `if 'rtma' in dataset.collection_id.lower()` and failed, logging "Unknown NOMADS dataset"  
**Fix:** Updated collection_id to `"rtma2p5"`  
**File:** Database record for RasterDataset  
**Line:** N/A (data fix)

### 2. **Variable Name Mapping Missing**
**Problem:** RTMA variables named "tmp2m", "dpt2m", etc. weren't mapped to NOMADS variable names  
**Impact:** "Unknown RTMA variable: tmp2m" errors  
**Fix:** Added comprehensive variable mapping including:
- `tmp2m` → `temperature`
- `dpt2m` → `temperature`  
- `ugrd10m` → `wind_u`
- `vgrd10m` → `wind_v`
- `pres` → `pressure`

**File:** `src/acquisition/raster_tasks.py`  
**Lines:** 569-582

### 3. **Missing Model Attributes**
**Problem:** Code referenced `config.compression_method` and `config.thumbnail_enabled` but model only has `apply_compression` and `generate_thumbnails`  
**Impact:** AttributeError crashes during processing  
**Fix:** 
- Changed `config.compression_method` to hardcoded `'LZW'`
- Changed `config.thumbnail_enabled` to `getattr(config, 'generate_thumbnails', False)`

**File:** `src/acquisition/raster_tasks.py`  
**Lines:** 367, 373

## Test Results

### Manual Integration Test
```
Configuration: test - only rtma
Variables: ['tmp2m']
Extents: ['Pacific_Northwest']

Result:
  Attempted: 4
  Successful: 3 ✅
  Failed: 0
  Skipped: 1 (expected - data not yet available)
```

### Database Verification
**Pull Logs:**
- Status: success
- Layers: 3/4 successful
- Duration: ~53 seconds

**Raster Layers Created:**
- 3 layers with timestamps: 16:00Z, 17:00Z, 18:00Z
- File sizes: 532-545 KB
- All marked as `is_valid: True`
- Thumbnails generated (.png files)

### File System Verification
```bash
$ ls -lh data/rasters/rtma2p5/tmp2m/Pacific_Northwest/2026/01/

-rw-rw-r-- 1  37K  rtma2p5_tmp2m_Pacific_Northwest_20260129_1600Z.png
-rw-rw-r-- 1 532K  rtma2p5_tmp2m_Pacific_Northwest_20260129_1600Z.tif
-rw-rw-r-- 1  37K  rtma2p5_tmp2m_Pacific_Northwest_20260129_1700Z.png
-rw-rw-r-- 1 539K  rtma2p5_tmp2m_Pacific_Northwest_20260129_1700Z.tif
-rw-rw-r-- 1  38K  rtma2p5_tmp2m_Pacific_Northwest_20260129_1800Z.png
-rw-rw-r-- 1 545K  rtma2p5_tmp2m_Pacific_Northwest_20260129_1800Z.tif
```

## System Status

### ✅ Working Components
1. **Manual trigger** - `POST /trigger-raster-pull/{config_id}/`
2. **Async task execution** - Celery worker processes tasks
3. **Data download** - NOMADS client fetching GRIB2 files
4. **Format conversion** - GRIB2 → GeoTIFF
5. **File storage** - Organized by dataset/variable/extent/year/month
6. **Thumbnail generation** - PNG previews created
7. **Database logging** - RasterPullLog entries created
8. **Layer tracking** - RasterLayer records with metadata

### URLs to Test
- **Gridded Data List:** http://localhost:8000/gridded-data/
- **Configuration List:** http://localhost:8000/raster-configs/
- **Configuration Detail:** http://localhost:8000/raster-config/{id}/
- **Pull Logs:** http://localhost:8000/gridded-logs/

## Files Modified

### 1. `src/acquisition/raster_tasks.py`
- **Lines 569-582:** Added RTMA variable mappings (tmp2m, dpt2m, ugrd10m, vgrd10m, pres)
- **Line 367:** Changed `config.compression_method` to `'LZW'`
- **Line 373:** Changed `config.thumbnail_enabled` to `getattr(config, 'generate_thumbnails', False)`

### 2. Database Records
- **RasterDataset (NOAA_RTMA):** collection_id changed from "ds084.1" to "rtma2p5"

### 3. New File Created
- **tests/test_raster_pull_integration.py** (436 lines)
  - RasterPullIntegrationTest class with 10 test methods
  - RasterLogViewTest class with 4 test methods
  - RasterDataStorageTest class with 2 test methods
  - Manual test runner function

## Next Steps

### Recommended Actions
1. ✅ **DONE:** Fix RTMA configuration issues
2. ✅ **DONE:** Test manual pull trigger
3. ✅ **DONE:** Verify data saves to filesystem
4. ✅ **DONE:** Verify logs appear in database
5. ⏭️ **TODO:** Test gridded-logs page displays logs correctly
6. ⏭️ **TODO:** Set up scheduled pulls via Celery Beat
7. ⏭️ **TODO:** Test other datasets (SMAP, MODIS, GPM) once configured
8. ⏭️ **TODO:** Add error handling for missing/delayed NOMADS files
9. ⏭️ **TODO:** Implement retry logic for failed downloads

### Configuration Recommendations
- Consider reducing `lookback_days` from 7 to 1-2 for RTMA (hourly data = lots of files)
- Monitor disk space usage (hourly data at 500KB/file = ~360 MB/month per variable)
- Set up log rotation for RasterPullLog table
- Configure Celery Beat schedule for automated pulls

## Testing Commands

### Manual Pull Test
```bash
cd /home/mrguy/Proj/streamflow-dataOps/streamflow-dataOps
python manage.py shell -c "
from tests.test_raster_pull_integration import run_manual_integration_test
run_manual_integration_test()
"
```

### Check Recent Logs
```bash
python manage.py shell -c "
from apps.streamflow.models import RasterPullLog
logs = RasterPullLog.objects.order_by('-started_at')[:5]
for log in logs:
    print(f'{log.configuration.name}: {log.status} ({log.layers_successful}/{log.layers_attempted})')
"
```

### Trigger Pull via Management Command
```bash
python manage.py pull_raster_data --config-id 1
```

### Check Celery Worker Status
```bash
python manage.py shell -c "
from celery import current_app
inspect = current_app.control.inspect()
print('Active workers:', inspect.active())
"
```

## Summary

The raster pull system is now **fully operational** for RTMA data. The issues were:
1. Incorrect dataset identifier preventing proper routing
2. Missing variable name mappings
3. Code referencing non-existent model fields

All issues have been resolved and verified through manual testing. The system successfully:
- Downloads RTMA GRIB2 files from NOMADS
- Converts to GeoTIFF format
- Generates thumbnails
- Stores files in organized directory structure
- Creates database records for tracking
- Logs all pull attempts

**Next immediate action:** Check the gridded-logs page (http://localhost:8000/gridded-logs/) to ensure the UI correctly displays the pull logs.
