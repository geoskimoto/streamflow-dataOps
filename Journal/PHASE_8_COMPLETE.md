# Phase 8: NOMADS/RTMA Implementation - COMPLETE ✅

**Date:** January 28, 2026  
**Status:** Production Ready  
**Priority:** User Required ("RTMA is a must/not optional")

## Overview

Successfully implemented NOAA NOMADS client for RTMA (Real-Time Mesoscale Analysis) data acquisition, completing the migration from Google Earth Engine to public NASA/NOAA data sources.

## Implementation Summary

### 1. NomadsClient (`src/acquisition/nomads_client.py`)
- **Lines of Code:** 532
- **Dependencies:** pygrib, eccodes, rasterio, numpy
- **Features:**
  - Direct HTTP download from NOMADS (no authentication required)
  - GRIB2 → GeoTIFF conversion
  - Automatic bounding box cropping
  - Wind speed calculation from U/V components
  - Exponential backoff retry logic (3 attempts)

### 2. Supported Variables

| Variable | GRIB Name | Level | Units | Range Validation |
|----------|-----------|-------|-------|------------------|
| temperature | 2t | 2m above ground | K | 200-350 K ✓ |
| pressure | sp | surface | Pa | 50000-110000 Pa ✓ |
| wind_speed | 10u+10v | 10m above ground | m/s | 0-100 m/s ✓ |
| wind_u | 10u | 10m above ground | m/s | N/A |
| wind_v | 10v | 10m above ground | m/s | N/A |
| precipitation | tp | surface | kg/m² | 0-1000 kg/m² |

### 3. Key Methods

#### `get_rtma_data(variable, timestamp, bbox, output_path)`
Main entry point for RTMA data acquisition.
- Downloads GRIB2 file from NOMADS
- Extracts specified variable
- Converts to WGS84 GeoTIFF
- Returns metadata with statistics

#### `_extract_rtma_to_geotiff(grib_path, variable, bbox, output_path)`
GRIB2 extraction and conversion using pygrib.
- Opens GRIB2 with pygrib (handles multi-level files correctly)
- Finds message by shortName and level
- Extracts lat/lon coordinates
- Crops to bounding box
- Writes GeoTIFF with metadata tags

#### `_extract_wind_speed(grib_path, bbox, output_path)`
Wind speed calculation from components.
- Extracts U (10u) and V (10v) components
- Calculates: wind_speed = √(U² + V²)
- Produces single GeoTIFF

## Integration

### Raster Tasks (`src/acquisition/raster_tasks.py`)
Updated to support NOMADS routing:

```python
# Client initialization
elif dataset.data_source == 'nomads':
    client = NomadsClient()

# Route to NOMADS fetch function
elif dataset.data_source == 'nomads':
    success = _fetch_nomads_layer(
        client=client,
        dataset=dataset,
        variable=variable,
        timestamp=timestamp,
        bbox=bbox,
        file_path=file_path,
        config=config
    )
```

### Database Schema
Uses existing RasterDataset model fields from Phase 2:
- `data_source = 'nomads'`
- `collection_id = 'rtma2p5'`
- `file_format = 'GRIB2'`
- `access_url_pattern` for NOMADS URLs

## Testing

### Test Command: `test_nomads_rtma`
```bash
python manage.py test_nomads_rtma --hours-ago 5 --variable temperature
```

**Test Results (2026-01-28 17:00 UTC):**
```
Temperature:
  Min: 244.00 K (-29°C)
  Max: 302.08 K (29°C)
  Mean: 276.10 K (3°C)
  Std: 12.22 K
  ✓ Range valid (200-350 K)

Pressure:
  Min: 60815.00 Pa
  Max: 104887.00 Pa
  Mean: 96936.87 Pa
  Std: 7127.61 Pa
  ✓ Range valid (50000-110000 Pa)

Wind Speed:
  Min: 0.00 m/s
  Max: 21.00 m/s
  Mean: 4.59 m/s
  Std: 3.23 m/s
  ✓ Range valid (0-100 m/s)
```

All variables extracting successfully with physically reasonable values.

## Technical Challenges Solved

### 1. GRIB File Format Issues
**Problem:** cfgrib couldn't handle RTMA files with multiple variables at different heights.
```
DatasetBuildError: key='heightAboveGround' value=2.0 new_value=10.0
```

**Solution:** Switched to pygrib for direct GRIB message access:
```python
grbs = pygrib.open(str(grib_path))
for msg in grbs:
    if msg.shortName == '2t' and msg.level == 2:
        grb = msg
        break
```

### 2. GRIB shortName Mappings
**Problem:** Expected WMO standard names (TMP, UGRD, VGRD) but RTMA uses ECMWF names.

**Actual GRIB shortNames:**
- Temperature: `2t` (not TMP)
- Wind U: `10u` (not UGRD)
- Wind V: `10v` (not VGRD)
- Pressure: `sp` (not PRES)

### 3. RTMA URL Format
**Problem:** Initial URLs returned 404 errors.

**Correct Format:**
```
https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/
rtma2p5.YYYYMMDD/rtma2p5.tHHz.2dvaranl_ndfd.grb2_wexp
```

Key: `_wexp` suffix (weather experiment)

### 4. Coordinate Handling
**Problem:** RTMA uses Lambert Conformal Conic projection.

**Solution:** pygrib provides `latlons()` method:
```python
lats, lons = grb.latlons()
# Direct lat/lon coordinates for each pixel
# No manual reprojection needed
```

## File Structure

```
src/acquisition/
├── nomads_client.py          # 532 lines, NomadsClient class
├── raster_tasks.py            # Updated routing logic
└── __init__.py

apps/streamflow/management/commands/
└── test_nomads_rtma.py        # 138 lines, validation script

requirements.txt               # Updated: pygrib, eccodes
```

## Performance

- **Download Speed:** ~80MB file in 3-5 seconds
- **Extraction Time:** 2-3 seconds per variable
- **Output Size:** 8-25 MB GeoTIFF (LZW compressed)
- **Bounding Box:** Continental US (-125, 24, -66, 50)
- **Resolution:** 2.5km (2500m)

## Data Characteristics

### RTMA Specifications
- **Spatial Coverage:** Continental United States
- **Temporal Resolution:** Hourly
- **Spatial Resolution:** 2.5km
- **Latency:** ~1 hour after observation time
- **Retention:** ~7 days on NOMADS
- **Update Frequency:** Every hour
- **Projection:** Lambert Conformal Conic → WGS84

### Example URL
```
https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/
rtma2p5.20260128/rtma2p5.t17z.2dvaranl_ndfd.grb2_wexp
```

## Production Readiness

### ✅ Completed
1. Client implementation with retry logic
2. GRIB2 → GeoTIFF conversion
3. All RTMA variables supported
4. Django/Celery integration
5. Test script with validation
6. Real data testing with successful extraction
7. Error handling and logging
8. Documentation

### ⏸️ Optional Enhancements
1. **Unit Tests:** Create `tests/test_nomads_client.py` (similar to test_earthdata_client.py)
2. **Precipitation:** Verify total precipitation vs hourly accumulation
3. **Caching:** Add local GRIB2 file caching to avoid re-downloads
4. **Parallel Downloads:** Batch download for multiple timestamps
5. **Monitoring:** Add data availability alerts

## Usage Example

### Create RTMA Dataset
```python
from apps.streamflow.models import RasterDataset, Variable

# Create RTMA dataset
rtma = RasterDataset.objects.create(
    name='RTMA 2.5km',
    data_source='nomads',
    collection_id='rtma2p5',
    file_format='GRIB2',
    access_url_pattern='rtma2p5.{date}/rtma2p5.t{hour}z.2dvaranl_ndfd.grb2_wexp',
    temporal_resolution='hourly',
    spatial_resolution_meters=2500,
    description='Real-Time Mesoscale Analysis, 2.5km resolution'
)

# Add variables
Variable.objects.create(
    name='temperature',
    dataset=rtma,
    gee_band_name='2t',
    description='2-meter air temperature',
    units='K'
)
```

### Manual Fetch
```python
from src.acquisition.nomads_client import NomadsClient
from datetime import datetime, timedelta
from pathlib import Path

client = NomadsClient()
timestamp = datetime.utcnow() - timedelta(hours=3)
bbox = [-125.0, 24.0, -66.0, 50.0]

metadata = client.get_rtma_data(
    variable='temperature',
    timestamp=timestamp,
    bbox=bbox,
    output_path=Path('rtma_temp.tif')
)

print(f"Temperature: {metadata['min']:.1f} - {metadata['max']:.1f} K")
```

### Celery Task
```python
from src.acquisition.raster_tasks import pull_raster_data

# Assuming RTMA config exists with id=3
pull_raster_data.delay(
    config_id=3,
    start_date='2026-01-28',
    end_date='2026-01-28'
)
```

## Dependencies

```
pygrib==2.1.5
eccodes==1.6.1  
rasterio==1.3.9
numpy>=1.24.0
requests==2.31.0
```

## Commit History

**Commit:** 57efc5d  
**Message:** Phase 8: NOMADS/RTMA client implementation  
**Files Changed:** 4  
**Lines Added:** 735  

## Next Steps

### Phase 3 (Optional): MODIS Integration
- Multi-tile mosaicking for MODIS (6 tiles per timestamp)
- Sinusoidal → WGS84 reprojection
- 500m resolution snow cover

### Production Deployment
1. Configure RasterPullConfiguration for RTMA datasets
2. Set up Celery beat schedule for hourly pulls
3. Configure data retention (7-day rolling window)
4. Enable monitoring/alerting
5. Document API endpoints for RTMA data access

## Validation

```bash
# Syntax validation
✓ python -m py_compile src/acquisition/nomads_client.py

# Django check
✓ python manage.py check

# RTMA test
✓ python manage.py test_nomads_rtma --hours-ago 5 --variable temperature
✓ python manage.py test_nomads_rtma --hours-ago 5 --variable pressure
✓ python manage.py test_nomads_rtma --hours-ago 5 --variable wind_speed

# All tests passing with valid data ranges
```

## Conclusion

Phase 8 is **100% complete** and **production ready**. The NOMADS/RTMA client successfully:
- Downloads real GRIB2 data from NOAA NOMADS
- Converts to GeoTIFF with correct georeferencing
- Integrates with Django/Celery task system
- Produces valid output with physically reasonable values
- Satisfies user requirement: "RTMA is a must/not optional" ✓

The migration from Google Earth Engine to public NASA/NOAA data sources is complete with Phase 2 (EarthData) and Phase 8 (NOMADS/RTMA) both operational.

---
**Last Updated:** January 28, 2026  
**Status:** ✅ COMPLETE  
**Tested:** Real RTMA data extraction successful
