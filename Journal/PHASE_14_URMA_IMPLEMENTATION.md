# Phase 14: URMA Implementation - COMPLETE ✅

**Date:** January 29, 2026  
**Duration:** ~45 minutes  
**Status:** ✅ COMPLETE

---

## Overview

Added URMA (UnRestricted Mesoscale Analysis) gridded data support to the system, bringing operational raster sources to **3/7 (43%)**. URMA provides hourly 2.5km meteorological analysis using only unrestricted data sources, complementing the existing RTMA implementation.

---

## Implementation Summary

### Data Source Details

**URMA (NOAA NCEP):**
- **URL:** https://nomads.ncep.noaa.gov/pub/data/nccf/com/urma/prod/
- **Format:** GRIB2 (identical to RTMA)
- **Resolution:** 2.5km (same as RTMA)
- **Update Frequency:** Hourly
- **Coverage:** CONUS (main), plus Alaska, Hawaii, Puerto Rico variants
- **Retention:** 2-3 days (typical NOMADS)
- **File Pattern:** `urma2p5.YYYYMMDD/urma2p5.tHHz.2dvaranl_ndfd.grb2_wexp`
- **File Size:** 82MB (main analysis files)

### Variables Implemented

| Variable | Description | Units | GRIB Short Name |
|----------|-------------|-------|-----------------|
| tmp2m | 2-meter Temperature | K | TMP |
| dpt2m | 2-meter Dewpoint Temperature | K | DPT |
| ugrd10m | 10-meter U Wind Component | m/s | UGRD |
| vgrd10m | 10-meter V Wind Component | m/s | VGRD |
| pres | Surface Pressure | Pa | PRES |

---

## Files Modified

### 1. src/acquisition/nomads_client.py
**Lines Added:** ~140

**Changes:**
- Added URMA constants (URMA_PATH, URMA_RESOLUTION)
- Implemented `get_urma_data()` method (~60 lines)
- Implemented `_build_urma_url()` method (~20 lines)
- Implemented `check_urma_availability()` method (~40 lines)
- Reused existing `_extract_rtma_to_geotiff()` for GRIB2 processing (formats identical)

**Key Code:**
```python
def get_urma_data(
    self,
    variable: str,
    timestamp: datetime,
    bbox: List[float],
    output_path: Path,
    timeout: int = 300
) -> Dict:
    """Fetch URMA data and convert to GeoTIFF."""
    # Reuses RTMA extraction since formats are identical
    metadata = self._extract_rtma_to_geotiff(
        grib_path=grib_path,
        variable=variable,
        bbox=bbox,
        output_path=output_path
    )
    metadata['source'] = 'URMA'
    return metadata
```

### 2. src/acquisition/raster_tasks.py
**Lines Added:** ~30

**Changes:**
- Added URMA detection to `_fetch_nomads_layer()` function
- Added variable mapping (identical to RTMA)
- Pattern matching: 'urma' in collection_id or dataset name

**Key Code:**
```python
elif 'urma' in dataset.collection_id.lower() or 'urma' in dataset.name.lower():
    var_map = {
        'tmp2m': 'temperature',
        'dpt2m': 'temperature',
        'ugrd10m': 'wind_u',
        'vgrd10m': 'wind_v',
        'pres': 'pressure'
    }
    nomads_var = var_map.get(variable.name, variable.gee_band_name)
    metadata = client.get_urma_data(...)
```

### 3. apps/streamflow/management/commands/init_raster_datasets.py
**Lines Added:** ~40

**Changes:**
- Added NOAA_URMA dataset configuration with 5 variables
- Added URMA_Hourly_Western_US pull configuration

**Dataset Configuration:**
```python
{
    'name': 'NOAA_URMA',
    'data_source': 'nomads',
    'collection_id': 'urma2p5',
    'description': 'NOAA UnRestricted Mesoscale Analysis - 2.5km CONUS analysis (hourly)',
    'resolution_m': 2500,
    'temporal_resolution': 'hourly',
    'update_frequency': 'hourly',
    'file_format': 'GRIB2',
    'is_active': True,
    'variables': [...]
}
```

---

## Testing Results

### Database Initialization
```bash
python manage.py init_raster_datasets
```

**Output:**
```
Dataset: NOAA_URMA
  ✓ Created dataset
    ✓ Variable: tmp2m
    ✓ Variable: dpt2m
    ✓ Variable: ugrd10m
    ✓ Variable: vgrd10m
    ✓ Variable: pres

⚙️  Creating Pull Configurations...
  ✓ URMA hourly configuration
```

### Data Pull Test
```bash
python manage.py test_raster_sources --dataset NOAA_URMA
```

**Results:**
- **Attempted:** 15 pulls
- **Successful:** 10 layers created (66% success rate)
- **Failed:** 0
- **Skipped:** 5 (data not yet available for future hours)
- **Variables Tested:** All 5 (tmp2m, dpt2m, ugrd10m, vgrd10m, pres)
- **Test Period:** 2 hours (2026-01-29 13:00-15:00)

**File Output:**
- **Location:** `data/rasters/urma2p5/`
- **Structure:** `{variable}/{extent}/{year}/{month}/{filename}.tif`
- **Total Size:** 984KB (10 GeoTIFF files)
- **Format:** GeoTIFF with spatial subsetting to Test_PNW_Small extent

### Sample Files Created
```
data/rasters/urma2p5/tmp2m/Test_PNW_Small/2026/01/urma2p5_tmp2m_Test_PNW_Small_20260129_1400Z.tif
data/rasters/urma2p5/dpt2m/Test_PNW_Small/2026/01/urma2p5_dpt2m_Test_PNW_Small_20260129_1300Z.tif
data/rasters/urma2p5/pres/Test_PNW_Small/2026/01/urma2p5_pres_Test_PNW_Small_20260129_1300Z.tif
data/rasters/urma2p5/ugrd10m/Test_PNW_Small/2026/01/urma2p5_ugrd10m_Test_PNW_Small_20260129_1400Z.tif
data/rasters/urma2p5/vgrd10m/Test_PNW_Small/2026/01/urma2p5_vgrd10m_Test_PNW_Small_20260129_1400Z.tif
```

---

## System Status Update

### Raster Data Sources Progress

**Operational (3/7 - 43%):**
- ✅ NOAA RTMA - Real-Time Mesoscale Analysis (2.5km, hourly)
- ✅ NCEP Stage IV QPE - Quantitative Precipitation Estimate (4km, hourly)
- ✅ **NOAA URMA - UnRestricted Mesoscale Analysis (2.5km, hourly)** ← NEW

**Blocked (2/7 - 29%):**
- ❌ MODIS Terra LST - HDF4/pyhdf installation issue
- ❌ MODIS Aqua LST - HDF4/pyhdf installation issue

**Debugging (1/7 - 14%):**
- 🟡 NASA SMAP L4 - Data discovery needs investigation

**Not Implemented (1/7 - 14%):**
- ⚪ NASA GPM IMERG - Not started

### Pull Configurations Active

| Configuration | Dataset | Variables | Extents | Frequency | Status |
|--------------|---------|-----------|---------|-----------|--------|
| RTMA_Hourly_Western_US | NOAA_RTMA | 5 | Western_US | 1 hour | ✅ Active |
| StageIV_Hourly_Western_US | NCEP_StageIV_QPE | 2 | Western_US | 1 hour | ✅ Active |
| **URMA_Hourly_Western_US** | **NOAA_URMA** | **5** | **Western_US** | **1 hour** | **✅ Active** |

---

## Implementation Notes

### Key Decisions

1. **Code Reuse:** Leveraged existing RTMA infrastructure since URMA uses identical GRIB2 format and file structure
2. **Variable Mapping:** Used same mapping as RTMA (both provide identical meteorological variables)
3. **URL Pattern:** Confirmed URMA uses same naming convention as RTMA (`{product}.tHHz.2dvaranl_ndfd.grb2_wexp`)
4. **Detection Logic:** Added 'urma' pattern matching in raster_tasks.py before Stage IV check

### URMA vs RTMA

Both products are nearly identical:

| Aspect | RTMA | URMA |
|--------|------|------|
| Resolution | 2.5km | 2.5km |
| Format | GRIB2 | GRIB2 |
| Update Frequency | Hourly | Hourly |
| Variables | 5+ (tmp, dpt, wind, pres) | 5+ (same) |
| Coverage | CONUS | CONUS (+AK, HI, PR variants) |
| Data Sources | All available (incl. proprietary) | Unrestricted only |
| URL Pattern | rtma2p5.YYYYMMDD/rtma2p5.tHHz... | urma2p5.YYYYMMDD/urma2p5.tHHz... |

**Key Difference:** URMA uses only non-proprietary data sources, making it freely shareable without restrictions.

### URMA Variants Discovered

While implementing, discovered multiple URMA products on NOMADS:
- `urma2p5` - CONUS 2.5km (implemented)
- `akurma` - Alaska
- `hiurma` - Hawaii
- `prurma` - Puerto Rico
- `pcpurma` - Precipitation-focused URMA

Future enhancement: Could add regional variants if needed.

---

## Technical Details

### GRIB2 Processing Pipeline

1. **Download:** Fetch 82MB GRIB2 file from NOMADS
2. **Extract:** Use pygrib to read specific variable bands
3. **Subset:** Crop to extent bounding box
4. **Reproject:** Convert to standard projection (if needed)
5. **Export:** Write as compressed GeoTIFF
6. **Cleanup:** Remove temporary GRIB2 file

### Error Handling

- **404 Errors:** Expected for recent hours (data not yet available)
- **Retry Logic:** 3 attempts with exponential backoff
- **Timeout:** 300 seconds per download
- **Validation:** Checks data exists before processing

---

## Next Steps

### Immediate
- ✅ Test URMA with real pulls (COMPLETE)
- ✅ Verify file creation (COMPLETE)
- ⏳ Document in journal (IN PROGRESS)
- ⏳ Commit and push changes

### Future Enhancements
- Add regional URMA variants (Alaska, Hawaii, Puerto Rico) if needed
- Add precipitation-focused URMA (pcpurma) for higher-resolution precip
- Implement automated quality checks on URMA vs RTMA comparisons
- Add URMA to monitoring dashboard

---

## Lessons Learned

1. **Infrastructure Reuse:** When data sources use identical formats, implementation is trivial (added URMA in <1 hour)
2. **NOMADS Consistency:** NOAA NOMADS products follow consistent patterns, making new additions predictable
3. **Pattern Detection:** Simple string matching ('urma' in name) is effective for routing data to correct handlers

---

## References

- **NOMADS URMA:** https://nomads.ncep.noaa.gov/pub/data/nccf/com/urma/prod/
- **URMA Documentation:** https://www.nco.ncep.noaa.gov/pmb/products/rtma/
- **GRIB2 Standard:** https://www.nco.ncep.noaa.gov/pmb/docs/grib2/

---

**Phase 14 Status:** ✅ COMPLETE  
**Operational Sources:** 3/7 (43%)  
**Next Phase:** Phase 15 - USGS Historical Data Population
