# Migration Plan: Google Earth Engine → NASA EarthData + NOAA NOMADS

**Date:** January 28, 2026  
**Status:** DRAFT - Awaiting Review  
**Version:** 1.0

---

## Executive Summary

This plan outlines the migration from Google Earth Engine (GEE) to a hybrid approach using:
- **NASA EarthData** for soil moisture and global precipitation/temperature datasets
- **NOAA NOMADS** for real-time US weather analysis (RTMA)

### Key Benefits
- ✅ **Open Access**: No proprietary authentication or compute quotas
- ✅ **Public Sources**: All data freely available via HTTP/FTP
- ✅ **Simpler Architecture**: Direct file downloads, no cloud processing
- ✅ **Better for Streamflow**: Higher quality datasets for hydrological modeling
- ✅ **Future-Proof**: NASA/NOAA commitment to open science

---

## Research Findings: Dataset Collection IDs

### 1. NASA EarthData Collections

#### SMAP Soil Moisture (Primary Use Case)
- **Collection ID**: `SPL4SMGP_008`
- **Full Name**: SMAP Level-4 Global 3-hourly 9 km EASE-Grid Surface and Root Zone Soil Moisture
- **DAAC**: NSIDC (National Snow & Ice Data Center)
- **Resolution**: 9 km
- **Temporal**: 3-hourly
- **Variables**:
  - `sm_surface` - Surface soil moisture (0-5cm)
  - `sm_rootzone` - Root zone soil moisture (0-100cm)
- **Start Date**: March 31, 2015
- **Access**: Direct HDF5 download via HTTPS
- **API**: EarthData Search API, CMR (Common Metadata Repository)

#### GPM Precipitation (Replaces RTMA Precip + GEE)
- **Collection ID**: `GPM_3IMERGDF_07`
- **Full Name**: GPM IMERG Final Precipitation L3 1 day 0.1° x 0.1° V07
- **DAAC**: GES DISC (Goddard Earth Sciences Data and Information Services Center)
- **Resolution**: 0.1° (~10 km)
- **Temporal**: Daily (aggregated from 30-minute)
- **Variables**:
  - `precipitation` - Daily mean precipitation (mm/day)
  - `randomError` - Precipitation error estimate
  - `MWprecipitation` - Microwave-only precipitation
- **Start Date**: June 1, 2000
- **Coverage**: 60°N to 60°S (covers continental US)
- **Access**: HDF5/NetCDF via HTTPS
- **Latency**: 3.5 months (Final Run) - suitable for historical analysis

#### MODIS Land Surface Temperature (Replaces RTMA Temp)
- **Collection ID**: `MOD11A1_061` (Terra), `MYD11A1_061` (Aqua)
- **Full Name**: MODIS Land Surface Temperature/Emissivity Daily L3 Global 1km SIN Grid V061
- **DAAC**: LP DAAC (Land Processes Distributed Active Archive Center)
- **Resolution**: 1 km
- **Temporal**: Daily (day + night overpasses)
- **Variables**:
  - `LST_Day_1km` - Daytime land surface temperature (K)
  - `LST_Night_1km` - Nighttime land surface temperature (K)
  - `QC_Day` / `QC_Night` - Quality control flags
  - `Emis_31` / `Emis_32` - Emissivity bands
- **Start Date**: 2000-02-24 (Terra), 2002-07-04 (Aqua)
- **Access**: HDF4 via HTTPS
- **Platforms**: Terra (morning), Aqua (afternoon) - combined for better coverage

### 2. NOAA NOMADS (Alternative/Supplement for US)

#### RTMA 2.5 (Real-Time Mesoscale Analysis)
- **Collection**: RTMA CONUS 2.5km
- **URL Pattern**: `https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/rtma2p5.YYYYMMDD/`
- **Format**: GRIB2 (requires pygrib or cfgrib for reading)
- **Resolution**: 2.5 km (higher than MODIS/GPM)
- **Temporal**: Hourly
- **Variables**:
  - Temperature (2m, Kelvin)
  - Precipitation (accumulated, kg/m²)
  - Wind speed (10m, m/s)
  - Dew point, pressure, etc.
- **Coverage**: Continental US only
- **Access**: Direct HTTP download, no authentication
- **File Naming**: 
  - Analysis: `rtma2p5.tYYYYMMDDHH.2dvaranl_ndfd.grb2_wexp`
  - Precipitation: `rtma2p5.YYYYMMDDHH.pcp.184.grb2`
- **Retention**: ~2 days on NOMADS (use NCEI for archives)

---

## Architecture Comparison

### Current (GEE-Based)
```
Django App → GEEClient → Google Earth Engine API
                ↓
          Cloud Processing
                ↓
          Export to GeoTIFF
                ↓
          Local Storage
```

**Limitations**:
- Requires service account authentication
- Compute quotas and rate limits
- Export tasks can be slow
- Proprietary platform dependency

### Proposed (EarthData + NOMADS)
```
Django App → EarthDataClient → NASA CMR API
              ↓                      ↓
         Find URLs           Direct Download
              ↓                      ↓
       NOMadsClient          Process HDF5/GRIB2
              ↓                      ↓
    Direct FTP/HTTP          Convert to GeoTIFF
              ↓                      ↓
        Local Storage         Local Storage
```

**Benefits**:
- Simple HTTP authentication (username/password)
- No compute limits
- Direct file downloads
- Standard formats (HDF5, GRIB2)
- Multi-source flexibility

---

## Implementation Plan

### Phase 1: Research & Setup (1-2 days)

**1.1 Environment Setup**
- [ ] Create NASA EarthData account (https://urs.earthdata.nasa.gov/users/new)
- [ ] Configure `.netrc` file for authentication
- [ ] Install Python dependencies:
  ```bash
  pip install earthaccess h5py netCDF4 cfgrib pygrib rasterio
  ```
- [ ] Test authentication with sample downloads

**1.2 Archive GEE Code**
- [ ] Create `archive/gee_implementation_jan2026/` directory
- [ ] Move existing GEE code:
  - `src/acquisition/gee_client.py` → archive
  - `tests/test_gee_integration.py` → archive
  - `apps/streamflow/diagnostics.py` (GEE check method) → update
- [ ] Update `.gitignore` to exclude GEE service account keys
- [ ] Document GEE implementation in `archive/GEE_IMPLEMENTATION_NOTES.md`

### Phase 2: Data Client Development (3-4 days)

**2.1 Create EarthDataClient**
- [ ] File: `src/acquisition/earthdata_client.py`
- [ ] Class: `EarthDataClient`
- [ ] Methods:
  - `__init__(username, password)` - Initialize with credentials
  - `authenticate()` - Setup session with EarthData
  - `search_granules(collection_id, bbox, start_date, end_date)` - Find data files
  - `download_granule(url, output_path)` - Download HDF5/NetCDF
  - `get_smap_data(variable, date, bbox)` - Fetch SMAP soil moisture
  - `get_gpm_data(date, bbox)` - Fetch GPM precipitation
  - `get_modis_lst(date, bbox, platform='terra')` - Fetch MODIS temperature
  - `check_data_availability(collection_id, date_range)` - Availability check
- [ ] Use `earthaccess` library for CMR API interaction
- [ ] Implement session-based auth with retry logic
- [ ] Add progress tracking for large downloads

**2.2 Create NomadsClient**
- [ ] File: `src/acquisition/nomads_client.py`
- [ ] Class: `NomadsClient`
- [ ] Methods:
  - `get_rtma_temperature(timestamp, bbox)` - Fetch RTMA temp
  - `get_rtma_precipitation(timestamp, bbox)` - Fetch RTMA precip
  - `get_rtma_wind(timestamp, bbox)` - Fetch RTMA wind
  - `list_available_times(date)` - Check available hours
  - `download_grib(url, output_path)` - Download GRIB2 file
  - `extract_variable(grib_file, variable, bbox)` - Extract subset
- [ ] Use `pygrib` or `cfgrib` for GRIB2 reading
- [ ] Handle CONUS-specific grid projection
- [ ] Implement file caching (GRIB files are large)

**2.3 Update RasterProcessor**
- [ ] File: `src/acquisition/raster_processor.py`
- [ ] Add methods:
  - `process_hdf5(input_path, variable, bbox, output_path)` - Process HDF5 to GeoTIFF
  - `process_grib2(input_path, variable, bbox, output_path)` - Process GRIB2 to GeoTIFF
  - `resample(input_geotiff, target_resolution, method='bilinear')` - Resample to common grid
  - `calculate_statistics(geotiff_path)` - Extract min/max/mean/std
- [ ] Update existing methods to handle new formats
- [ ] Ensure consistent CRS (EPSG:4326) output

### Phase 3: Database Schema Updates (1 day)

**3.1 Migration: Update RasterDataset Model**
- [ ] Create migration: `0005_update_dataset_for_earthdata.py`
- [ ] Changes to `RasterDataset` model:
  ```python
  # Rename field
  gee_collection_id → collection_id  # Generic, not GEE-specific
  
  # Add new fields
  data_source = models.CharField(
      max_length=50, 
      choices=[('earthdata', 'NASA EarthData'), ('nomads', 'NOAA NOMADS')],
      default='earthdata'
  )
  daac = models.CharField(max_length=50, blank=True)  # e.g., 'NSIDC', 'GES_DISC'
  file_format = models.CharField(max_length=20)  # 'HDF5', 'NetCDF', 'GRIB2'
  access_url_pattern = models.CharField(max_length=500)  # URL template
  ```

**3.2 Data Migration: Update Existing Datasets**
- [ ] Update RTMA dataset:
  ```python
  RasterDataset.objects.filter(name='RTMA').update(
      data_source='nomads',
      collection_id='rtma2p5',  # Remove NOAA/NWS/ prefix
      file_format='GRIB2',
      access_url_pattern='https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/'
  )
  ```
- [ ] Update SMAP dataset:
  ```python
  RasterDataset.objects.filter(name='SMAP_SPL4').update(
      data_source='earthdata',
      collection_id='SPL4SMGP_008',
      daac='NSIDC_CPRD',
      file_format='HDF5',
      access_url_pattern='https://n5eil01u.ecs.nsidc.org/SMAP/'
  )
  ```

**3.3 Add New Datasets**
- [ ] Create GPM precipitation dataset:
  ```python
  RasterDataset.objects.create(
      name='GPM_IMERG',
      collection_id='GPM_3IMERGDF_07',
      data_source='earthdata',
      daac='GES_DISC',
      description='GPM IMERG Final Daily Precipitation',
      resolution_m=10000,
      temporal_resolution='daily',
      file_format='HDF5',
      is_active=True
  )
  ```
- [ ] Create MODIS LST datasets (Terra + Aqua)

**3.4 Update RasterVariable Model**
- [ ] Rename `gee_band_name` → `band_name` (generic)
- [ ] Add `extraction_method` field for format-specific parsing

### Phase 4: Task & View Updates (2 days)

**4.1 Update raster_tasks.py**
- [ ] File: `src/acquisition/raster_tasks.py`
- [ ] Replace `GEEClient` imports with `EarthDataClient` and `NomadsClient`
- [ ] Update `pull_raster_data()` task:
  - Route to appropriate client based on `dataset.data_source`
  - Handle different file formats (HDF5, GRIB2)
  - Update progress tracking
- [ ] Update `_pull_single_layer()` helper:
  - Branch on data source
  - Call appropriate client method
  - Update file naming conventions
- [ ] Add new helper: `_process_downloaded_file(file_path, format, variable, bbox)`

**4.2 Update Diagnostics**
- [ ] File: `apps/streamflow/diagnostics.py`
- [ ] Remove `check_gee_api()` method
- [ ] Add `check_earthdata_api()` method:
  - Test authentication
  - Query CMR for collection availability
  - Check download speed
- [ ] Add `check_nomads_access()` method:
  - Test HTTP access to NOMADS
  - Check latest RTMA availability
  - Measure latency
- [ ] Update `get_overall_status()` to use new checks

**4.3 Update Management Commands**
- [ ] `apps/streamflow/management/commands/setup_raster_datasets.py`
  - Update dataset creation with new fields
  - Add GPM and MODIS datasets
- [ ] `apps/streamflow/management/commands/test_gee_connection.py`
  - Rename to `test_data_sources.py`
  - Add tests for EarthData and NOMADS

### Phase 5: Testing (2-3 days)

**5.1 Unit Tests**
- [ ] Create `tests/test_earthdata_client.py`:
  - Test authentication
  - Test granule search
  - Test download (mock responses)
  - Test data parsing
- [ ] Create `tests/test_nomads_client.py`:
  - Test GRIB2 download
  - Test variable extraction
  - Test coordinate subsetting
- [ ] Update `tests/test_raster_processor.py`:
  - Add HDF5 processing tests
  - Add GRIB2 processing tests
  - Test format conversions

**5.2 Integration Tests**
- [ ] Create `tests/test_earthdata_integration.py`:
  - End-to-end SMAP data pull
  - End-to-end GPM data pull
  - End-to-end MODIS data pull
  - Verify GeoTIFF output
- [ ] Create `tests/test_nomads_integration.py`:
  - End-to-end RTMA temperature pull
  - End-to-end RTMA precipitation pull
  - Verify GeoTIFF output and statistics

**5.3 Manual Testing**
- [ ] Test full pull workflow:
  ```bash
  # Create config for each dataset
  python manage.py create_raster_config \
    --name "Test SMAP Pull" \
    --dataset SMAP_SPL4 \
    --variables soil_moisture_surface \
    --extents HUC_17 \
    --frequency 24
  
  # Run manual pull
  python manage.py pull_raster_data --config "Test SMAP Pull"
  
  # Verify in UI
  # Check logs, verify layers created, inspect GeoTIFF
  ```
- [ ] Test diagnostics page:
  - Verify EarthData authentication status
  - Verify NOMADS accessibility
  - Check for no GEE references

### Phase 6: Documentation & Deployment (1 day)

**6.1 Update Documentation**
- [ ] Update `README.md`:
  - Replace GEE setup with EarthData/NOMADS setup
  - Update dataset list with new collections
  - Add authentication instructions
- [ ] Update `DEPLOYMENT.md`:
  - Add EarthData account creation steps
  - Add `.netrc` configuration
  - Remove GEE service account instructions
- [ ] Create `EARTHDATA_SETUP.md`:
  - Detailed authentication guide
  - Dataset access examples
  - Troubleshooting common issues
- [ ] Update component documentation:
  - `component_4_rest_api.md` - Update dataset endpoints
  - `README_COMPONENT2.md` - Update data acquisition info

**6.2 Configuration Updates**
- [ ] `config/settings.py`:
  - Remove `GEE_DATASETS` dictionary
  - Add `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` (from env)
  - Add `NOMADS_BASE_URL` constant
  - Update `RASTER_DATA_DIR` structure if needed
- [ ] `.env.example`:
  - Add `EARTHDATA_USERNAME=your_username`
  - Add `EARTHDATA_PASSWORD=your_password`
  - Remove GEE service account variables
- [ ] Update `requirements.txt`:
  ```
  # Remove
  # earthengine-api==0.1.XXX
  # google-auth==2.XX.X
  
  # Add
  earthaccess==0.9.0
  h5py==3.10.0
  netCDF4==1.6.5
  cfgrib==0.9.10.4
  pygrib==2.1.5
  eccodes==1.6.1  # Required for pygrib
  ```

**6.3 Archive GEE Implementation**
- [ ] Create `archive/gee_implementation_jan2026/README.md`:
  - Explain why GEE was archived
  - Document what was replaced
  - Provide rollback instructions (if needed)
  - List commits related to GEE implementation
- [ ] Copy files to archive:
  ```bash
  mkdir -p archive/gee_implementation_jan2026
  cp src/acquisition/gee_client.py archive/gee_implementation_jan2026/
  cp tests/test_gee_integration.py archive/gee_implementation_jan2026/
  cp -r config/gee-service-account.json archive/gee_implementation_jan2026/ (if exists)
  ```
- [ ] Update `.gitignore`:
  ```
  # Remove GEE references, add archive exclusions
  archive/gee_implementation_jan2026/gee-service-account.json
  ```

### Phase 7: Gradual Rollout (1-2 days)

**7.1 Feature Flag**
- [ ] Add setting: `USE_EARTHDATA = True`
- [ ] Keep GEE client available but unused
- [ ] Allow easy rollback if issues found

**7.2 Parallel Testing**
- [ ] Run pulls with both systems
- [ ] Compare results (if GEE still has access)
- [ ] Monitor for errors/differences

**7.3 Final Cutover**
- [ ] Set `USE_EARTHDATA = True` permanently
- [ ] Remove GEE dependencies from requirements.txt
- [ ] Delete GEE service account from server
- [ ] Update monitoring/diagnostics

---

## Data Format Specifications

### SMAP HDF5 Structure
```python
# File: SMAP_L4_SM_gph_YYYYMMDDTHHMMSS_Vxxx_001.h5
# Groups: /Geophysical_Data/, /Metadata/
# Variables:
#   - sm_surface [lat, lon]  # m³/m³
#   - sm_rootzone [lat, lon]  # m³/m³
# Coordinates: lat, lon arrays
# CRS: EASE-Grid 2.0 (custom projection)
```

### GPM HDF5 Structure
```python
# File: 3B-DAY.MS.MRG.3IMERG.YYYYMMDD-S000000-E235959.V07.nc4
# Format: NetCDF4 (HDF5-based)
# Variables:
#   - precipitation [time, lat, lon]  # mm/day
#   - precipitation_cnt [time, lat, lon]  # count of valid samples
#   - randomError [time, lat, lon]  # mm/day
# Coordinates: lat (0.05 to 0.05 + 3600*0.1), lon (-180 to 180)
# CRS: WGS84 (EPSG:4326)
```

### MODIS HDF4 Structure
```python
# File: MOD11A1.A2026028.h09v04.061.YYYYDDDHHMMSS.hdf
# Format: HDF4-EOS
# SDS (Scientific Data Sets):
#   - LST_Day_1km [1200, 1200]  # Kelvin * 50 (scale factor)
#   - LST_Night_1km [1200, 1200]
#   - QC_Day [1200, 1200]  # Quality flags
# Projection: Sinusoidal (MODIS grid)
# Tiles: h09v04 format (requires mosaicking)
```

### RTMA GRIB2 Structure
```python
# File: rtma2p5.t12z.2dvaranl_ndfd.grb2_wexp
# Format: GRIB2
# Messages (bands):
#   - Temperature (2m) - K
#   - Dew Point (2m) - K
#   - Wind U/V (10m) - m/s
#   - Pressure - Pa
# Grid: Lambert Conformal (CONUS)
# Resolution: 2.5km
# Coordinates: Embedded in GRIB metadata
```

---

## Configuration Examples

### .netrc for EarthData Authentication
```bash
# File: ~/.netrc
# Permissions: chmod 600 ~/.netrc

machine urs.earthdata.nasa.gov
    login your_username
    password your_password
```

### Django Settings Update
```python
# config/settings.py

# NASA EarthData Configuration
EARTHDATA_USERNAME = os.getenv('EARTHDATA_USERNAME', '')
EARTHDATA_PASSWORD = os.getenv('EARTHDATA_PASSWORD', '')

# NOAA NOMADS Configuration
NOMADS_BASE_URL = 'https://nomads.ncep.noaa.gov/pub/data/nccf/com/'
NOMADS_RTMA_PATH = 'rtma/prod/'

# Data Source Collections
EARTHDATA_COLLECTIONS = {
    'SMAP_SPL4': 'SPL4SMGP_008',
    'GPM_IMERG': 'GPM_3IMERGDF_07',
    'MODIS_LST_TERRA': 'MOD11A1_061',
    'MODIS_LST_AQUA': 'MYD11A1_061',
}

NOMADS_PRODUCTS = {
    'RTMA_CONUS': 'rtma2p5',
    'URMA_CONUS': 'urma2p5',
}
```

---

## Risk Assessment & Mitigation

### Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| GRIB2 library issues (pygrib) | Medium | High | Use cfgrib as backup; pre-test on dev |
| HDF5 format complexities | Low | Medium | Use earthaccess library; extensive testing |
| NOMADS downtime/retention | Medium | Medium | Add retry logic; use NCEI archives |
| Download speed bottlenecks | Low | Medium | Implement parallel downloads; caching |
| Coordinate system mismatches | Medium | High | Standardize to EPSG:4326; validate outputs |
| MODIS tile mosaicking | Medium | Medium | Use pymodis or GDAL; pre-process tiles |

### Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Loss of GEE access during migration | Low | High | Keep GEE code in archive; feature flag |
| Data gaps between sources | Low | Medium | Overlap test period; document differences |
| Authentication failures | Medium | Low | Implement robust retry; alerting |
| Increased storage needs (GRIB2 large) | High | Low | Implement cleanup; compress old files |

---

## Success Criteria

### Technical
- [ ] All SMAP pulls working (soil moisture surface + rootzone)
- [ ] All GPM pulls working (daily precipitation)
- [ ] All MODIS pulls working (daytime temperature)
- [ ] All RTMA pulls working (temp, precip, wind)
- [ ] GeoTIFF outputs match quality of GEE outputs
- [ ] Statistics (min/max/mean) within expected ranges
- [ ] All unit tests passing (target: 95% coverage)
- [ ] All integration tests passing
- [ ] Diagnostics page shows healthy status for all sources

### Operational
- [ ] Pull duration comparable to or better than GEE
- [ ] No GEE dependencies in requirements.txt
- [ ] Documentation complete and reviewed
- [ ] Team trained on new data sources
- [ ] Monitoring/alerting configured

### Data Quality
- [ ] Visual inspection of GeoTIFFs (no artifacts)
- [ ] Time series continuity (no gaps)
- [ ] Coordinate accuracy (proper geolocation)
- [ ] Value ranges match expected climatology

---

## Timeline (Revised Per Decisions)

| Phase | Duration | Dependencies | Deliverables |
|-------|----------|--------------|--------------|
| 1. Research & Setup | 0.5 days | None | EarthData account, env configured, GEE archived |
| 2. EarthData Client Dev | 2-3 days | Phase 1 | EarthDataClient for SMAP/GPM/MODIS |
| 3. Database Updates | 0.5 days | Phase 2 | Migration files, updated models (EarthData only) |
| 4. Task/View Updates | 1-2 days | Phase 2, 3 | Updated pull logic for EarthData |
| 5. Testing (EarthData) | 2 days | Phase 2, 3, 4 | SMAP, GPM, MODIS tests passing |
| 6. Documentation | 0.5 days | Phase 5 | EarthData docs complete |
| 7. EarthData Rollout | 0.5 days | Phase 6 | EarthData in production |
| **SUBTOTAL** | **7-9 days** | | **EarthData complete, GEE archived** |
| 8. NOMADS Client Dev | 2 days | Phase 7 | NomadsClient for RTMA |
| 9. RTMA Integration | 1 day | Phase 8 | RTMA in pull system |
| 10. Testing (RTMA) | 1 day | Phase 9 | RTMA tests passing |
| 11. Final Docs & Deploy | 0.5 days | Phase 10 | Complete migration |
| **TOTAL** | **11-13 days** | | **Full migration complete** |

---

## Rollback Plan

If critical issues arise during migration:

1. **Immediate Rollback** (< 1 hour):
   - Revert to GEE branch: `git checkout feature/raster-data-gee`
   - Restart Django/Celery services
   - Re-enable GEE in diagnostics

2. **Data Recovery** (< 4 hours):
   - Any partial data pulled via EarthData can be deleted
   - Re-run pulls with GEE
   - No data loss risk (all downloads are additive)

3. **Migration Retry**:
   - Document issue in `ISSUES_BLOCKERS.md`
   - Fix root cause in separate branch
   - Re-test before retry
   - Gradual rollout with feature flag

---

## Post-Migration Tasks

### Week 1
- [ ] Monitor pull success rates
- [ ] Check storage usage trends
- [ ] Validate data quality samples
- [ ] User feedback collection

### Week 2-4
- [ ] Optimize download performance
- [ ] Add more datasets (e.g., VIIRS, Landsat)
- [ ] Implement advanced features (data fusion, gap filling)
- [ ] Performance tuning

### Month 2
- [ ] Add historical backfill for new datasets
- [ ] Expand spatial extents
- [ ] Add derived products (indices, anomalies)
- [ ] Consider adding near-real-time datasets

---

## Questions for Review ✅ ANSWERED

1. **Priority**: Should we implement EarthData + NOMADS simultaneously, or EarthData first?
   - **DECISION**: ✅ EarthData first (SMAP, GPM, MODIS), test thoroughly, THEN NOMADS (RTMA)
   - **Rationale**: Sequential implementation reduces risk, allows validation at each step

2. **RTMA Necessity**: Do we need real-time US data, or is daily MODIS + GPM sufficient?
   - **DECISION**: ✅ Daily MODIS + GPM is sufficient for now
   - **Note**: RTMA will be added last (Phase 8) but is REQUIRED for production use

3. **Storage**: GRIB2 files are large. Should we extract and discard, or keep originals?
   - **DECISION**: ✅ Extract to GeoTIFF, keep GRIB2 for 7 days, then delete (approved)

4. **Testing**: Should we keep GEE active for parallel comparison during migration?
   - **DECISION**: ✅ Archive GEE entirely - no parallel testing needed
   - **Rationale**: Cannot sustain GEE costs; rely on public sources only

5. **Datasets**: Which should be prioritized?
   - **DECISION**: ✅ SMAP (1st) → GPM (2nd) → MODIS (3rd) → RTMA (4th - REQUIRED)
   - **Implementation Order**: Build EarthData infrastructure with SMAP/GPM/MODIS, then add NOMADS/RTMA

---User (mrguy)  
**Approved by**: ✅ APPROVED - January 28, 2026  
**Date**: January 28, 2026

**Implementation Status**: 🚀 **IN PROGRESS - Phase 1 Started**

**Key Decisions**:
- Sequential implementation: EarthData (7-9 days) → NOMADS (4 days)
- No GEE parallel testing - archive immediately
- RTMA is REQUIRED but implemented last
- Daily temporal resolution sufficient
- GRIB2 retention: 7 days then purge
**Next Steps**: 
1. Review this plan
2. Answer questions above
3. Approve to proceed
4. Begin Phase 1 implementation

---

**Appendix A: Key Libraries**

```bash
# Core data access
earthaccess==0.9.0          # NASA EarthData unified access
requests==2.31.0            # HTTP downloads

# HDF5/NetCDF processing
h5py==3.10.0               # HDF5 reading
netCDF4==1.6.5             # NetCDF4 reading
xarray==2024.1.0           # Multi-dimensional arrays

# GRIB2 processing
cfgrib==0.9.10.4           # GRIB2 via ECMWF codes
pygrib==2.1.5              # GRIB2 (NOAA-compatible)
eccodes==1.6.1             # Required for pygrib

# Geospatial
rasterio==1.3.9            # GeoTIFF I/O
pyproj==3.6.1              # Coordinate transformations
GDAL==3.8.3                # Geospatial data abstraction

# Optional
pymodis==2.4.0             # MODIS-specific tools
pyhdf==0.11.3              # HDF4 support (for older MODIS)
```

**Appendix B: Sample Code**

See implementation files for detailed examples:
- `src/acquisition/earthdata_client.py` (to be created)
- `src/acquisition/nomads_client.py` (to be created)
- `tests/test_earthdata_client.py` (to be created)
