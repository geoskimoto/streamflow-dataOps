# Running Issues & Blockers

**Last Updated:** January 28, 2026  
**Status:** Active tracking

---

## 🔴 Critical Issues

### None currently

---

## 🟡 Known Issues (Non-Blocking)

### Issue #1: Rasterio HDF4 Subdataset Access

**Status:** Known Issue - Workaround Available  
**Severity:** Medium  
**Component:** MODIS LST Data Processing  
**Discovered:** January 28, 2026  
**Affects:** MODIS Terra/Aqua LST data ingestion

#### Problem Description

The `rasterio` Python library fails to open HDF4 EOS subdatasets from MODIS products, despite the files being valid and accessible via GDAL command-line tools.

#### Error Message
```
rasterio.errors.RasterioIOError: HDF4_EOS:EOS_GRID:"/path/to/file.hdf":MODIS_Grid_Daily_1km_LST:LST_Day_1km: No such file or directory
```

#### Diagnostic Details

**Environment:**
- OS: Linux (Ubuntu-based)
- Python: 3.13.11
- rasterio: 1.3.9
- GDAL: 3.8.3
- HDF4 driver: Available and functional in GDAL

**What Works:**
- ✅ NASA EarthData authentication successful
- ✅ MODIS granule search returns correct results (4 tiles for Pacific NW)
- ✅ File downloads complete successfully (~5MB per tile, 20MB total)
- ✅ Files are valid HDF4 format (verified with `file` command)
- ✅ GDAL CLI tools can read files perfectly:
  ```bash
  gdalinfo 'HDF4_EOS:EOS_GRID:"/tmp/modis_test/temp/MOD11A1.A2025364.h09v04.061.2026001001054.hdf":MODIS_Grid_Daily_1km_LST:LST_Day_1km'
  # Returns full metadata, coordinate system, etc.
  ```
- ✅ `gdalwarp` can extract and reproject subdatasets

**What Fails:**
- ❌ `rasterio.open()` on HDF4 EOS subdatasets
- ❌ Python-based HDF4 subdataset mosaicking

**Test Commands:**
```bash
# Successful search and download
python manage.py test_modis_lst --days-ago 30 --product MOD11A1 --output-dir /tmp/modis_test

# Files exist after test:
ls -lh /tmp/modis_test/temp/
# -rw-rw-r-- 1 mrguy mrguy 5.0M Jan 28 20:32 MOD11A1.A2025364.h09v04.061.2026001001054.hdf
# -rw-rw-r-- 1 mrguy mrguy 5.2M Jan 28 20:32 MOD11A1.A2025364.h10v04.061.2026001001232.hdf
# ... (4 files total)

# GDAL CLI works:
gdalinfo /tmp/modis_test/temp/MOD11A1.A2025364.h09v04.061.2026001001054.hdf
# Shows 12 subdatasets successfully

# But Python fails:
python -c "import rasterio; rasterio.open('HDF4_EOS:EOS_GRID:\"/tmp/modis_test/temp/MOD11A1.A2025364.h09v04.061.2026001001054.hdf\":MODIS_Grid_Daily_1km_LST:LST_Day_1km')"
# RasterioIOError: No such file or directory
```

#### Root Cause Analysis

This appears to be a known limitation/bug in rasterio's handling of HDF4 EOS subdataset connection strings. Possible causes:

1. **Quote Escaping:** Rasterio may not properly escape quotes in the subdataset string when passing to GDAL
2. **Driver Initialization:** Python bindings may initialize the HDF4 driver differently than CLI tools
3. **Connection String Format:** Rasterio may expect a different format for EOS subdatasets
4. **Rasterio Version Bug:** Version 1.3.9 may have a regression (would need to test with other versions)

#### Affected Functionality

- `src/acquisition/earthdata_processor.py::mosaic_modis_tiles()` - Lines 355-400
- `src/acquisition/earthdata_client.py::get_modis_data()` - Lines 420-490
- MODIS LST data ingestion in production schedules

#### Recommended Solutions

**Option 1: Use GDAL Python bindings (Recommended)**
```python
from osgeo import gdal

# Instead of rasterio.open()
ds = gdal.Open(subdataset_string)
if ds is None:
    raise error

# Read array
band = ds.GetRasterBand(1)
data = band.ReadAsArray()
```

**Option 2: Subprocess to gdalwarp (Most Reliable)**
```python
import subprocess

# Use CLI tool that's proven to work
subprocess.run([
    'gdalwarp',
    '-of', 'GTiff',
    '-t_srs', 'EPSG:4326',
    '-te', str(bbox[0]), str(bbox[1]), str(bbox[2]), str(bbox[3]),
    subdataset_string,
    output_path
], check=True)
```

**Option 3: Pre-extract subdatasets**
```python
# Extract to temporary GeoTIFF first, then use rasterio
import subprocess
temp_tif = tempfile.mktemp(suffix='.tif')
subprocess.run(['gdal_translate', subdataset_string, temp_tif], check=True)
with rasterio.open(temp_tif) as src:
    data = src.read(1)
```

**Option 4: Update to newer rasterio/GDAL**
- Test with rasterio >= 1.4.0 (may have fixes)
- Ensure GDAL >= 3.9.0 (latest HDF4 driver improvements)

#### Workaround Priority

**Immediate:** Option 2 (subprocess) - Zero risk, proven to work  
**Long-term:** Option 1 (GDAL bindings) - More Pythonic, still reliable  
**Testing:** Option 4 (version update) - May resolve without code changes

#### Implementation Notes

If implementing Option 2:
1. Add subprocess calls in `earthdata_processor.py::mosaic_modis_tiles()`
2. Use gdalwarp with mosaic mode (-te for bbox clipping)
3. Keep rasterio for post-processing (metadata extraction, thumbnail generation)
4. Add proper error handling and logging

**Estimated Fix Time:** 2-4 hours  
**Testing Time:** 1 hour  
**Risk:** Low (CLI tools proven stable)

#### Related Files
- `src/acquisition/earthdata_processor.py` (mosaic_modis_tiles function)
- `src/acquisition/earthdata_client.py` (get_modis_data function)
- `apps/streamflow/management/commands/test_modis_lst.py` (test command)

#### Testing Commands
```bash
# Test MODIS search and download
python manage.py test_modis_lst --days-ago 30 --product MOD11A1 --output-dir /tmp/modis_test

# Verify GDAL CLI access
gdalinfo /tmp/modis_test/temp/*.hdf | grep -A5 SUBDATASET_1

# Test fix (after implementation)
python manage.py test_modis_lst --days-ago 30 --product MOD11A1 --output-dir /tmp/modis_test_fixed
ls -lh /tmp/modis_test_fixed/*.tif  # Should show processed GeoTIFF
```

---

## 🟢 Resolved Issues

### Issue: MODIS Collection ID Format

**Status:** ✅ Resolved  
**Date:** January 28, 2026  

**Problem:** NASA CMR API was returning no results with collection ID format `MOD11A1_061`

**Solution:** Changed to short name format `MOD11A1` (version implicit). CMR API prefers short names without version suffix for MODIS products.

**Files Changed:**
- `src/acquisition/earthdata_client.py` (COLLECTIONS dict)
- `apps/streamflow/management/commands/init_raster_datasets.py` (dataset definitions)

### Issue: SpatialExtent Initialization Error

**Status:** ✅ Resolved  
**Date:** January 28, 2026  

**Problem:** `init_raster_datasets` command failed with error: `FieldError: Invalid field name(s) for model SpatialExtent: 'bbox'`

**Solution:** Updated to use proper model fields (`min_lon`, `min_lat`, `max_lon`, `max_lat`) instead of non-existent `bbox` field. The `bbox` property is computed, not a database field.

**Files Changed:**
- `apps/streamflow/management/commands/init_raster_datasets.py`

### Issue: Frontend Test ALLOWED_HOSTS

**Status:** ✅ Resolved  
**Date:** January 28, 2026  

**Problem:** Frontend tests failing with "Invalid HTTP_HOST header: 'testserver'"

**Solution:** Added `'testserver'` to `ALLOWED_HOSTS` in settings.py. Also updated serializer field names from `gee_collection_id` to `collection_id`.

**Files Changed:**
- `config/settings.py`
- `apps/api/serializers/raster_serializers.py`

---

## 📋 Open Tasks (Not Issues)

### Data Retention Testing
- Verify automated cleanup tasks run correctly
- Monitor disk space usage over 30 days
- Validate retention policies (RTMA: 7d, EarthData: 30d)

### Production Monitoring Setup
- Configure email alerts (ALERT_EMAIL_ENABLED)
- Set up monitoring thresholds
- Test Flower dashboard in production
- Create alerting runbook

### Performance Optimization
- Profile SMAP/GPM download times
- Optimize RTMA hourly processing
- Add parallel downloads for MODIS tiles
- Implement caching for repeated queries

### Documentation
- Add MODIS troubleshooting guide (after HDF4 fix)
- Create operator training materials
- Document emergency procedures
- Update API examples with MODIS

---

## 🔍 Investigation Needed

### MODIS Data Latency
**Status:** Observed, documenting  
**Description:** MODIS data shows 2-7 day processing lag at NASA. Need to establish baseline expectations and alert thresholds.

**Questions:**
- What's the typical latency for MOD11A1/MYD11A1?
- Should we alert if data >5 days old?
- Is Terra or Aqua typically faster?

**Action:** Monitor for 2 weeks, establish SLA baselines

---

## 📝 Notes for Future Sessions

1. **MODIS HDF4 Issue:** Choose solution approach (subprocess vs GDAL bindings) and implement
2. **Production Readiness:** All 5 data sources except MODIS fully operational
3. **Testing Status:** 72 tests passing (12/14 integration tests passing)
4. **Monitoring:** Flower, health checks, and alerting all configured
5. **Deployment:** Automated startup script ready (`./scripts/start_production.sh`)

---

**File Purpose:** This document tracks all known issues, blockers, and technical debt for the raster data acquisition system. Update this file when new issues are discovered or existing issues are resolved.
