# NCEP Stage IV QPE Implementation Plan

**Date Created:** January 29, 2026  
**Status:** Planning  
**Priority:** Medium  
**Estimated Effort:** 8-12 hours

---

## Overview

Implement NCEP Stage IV Quantitative Precipitation Estimate (QPE) as a new raster data source in the StreamFlow DataOps platform. Stage IV provides quality-controlled, mosaicked precipitation data across the continental United States at 4km resolution.

### Data Source Information
- **Provider:** NOAA/NWS/NCEP  
- **Product:** Stage IV QPE (CONUS mosaic)  
- **Resolution:** 4km (~ 0.04°), Hourly & 6-hourly accumulations  
- **Domain:** Continental United States (CONUS)  
- **Format:** GRIB2  
- **Access URL:** https://water.noaa.gov/resources/downloads/precip/stageIV/  
- **Latency:** ~6 hours (operational real-time)  
- **Retention:** Rolling 2-3 day window on primary server  

### Use Cases
- Real-time precipitation monitoring
- QPE validation for hydrologic models
- Flood forecasting and analysis
- Water resource management
- Historical precipitation analysis

---

## Phase 1: Backend Data Acquisition (4-5 hours)

### 1.1 Create NOMADS Client Extension
**File:** `src/acquisition/nomads_stage4_client.py` (NEW)

**Class:** `Stage4QPEClient`
- Extends or parallels existing NOMADS client functionality
- Handles Stage IV specific URL patterns and file naming conventions
- Implements GRIB2 parsing for precipitation variables

**Key Methods:**
```python
class Stage4QPEClient:
    """Client for NCEP Stage IV QPE data acquisition."""
    
    BASE_URL = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/pcpanl/prod/"
    
    def __init__(self):
        """Initialize Stage IV client."""
        pass
    
    def get_available_dates(self, days_back: int = 2) -> List[datetime]:
        """Query available dates on NOMADS server."""
        # Parse directory listing to find available pcpanl.YYYYMMDD folders
        pass
    
    def get_hourly_precip(
        self,
        timestamp: datetime,
        bbox: List[float],
        output_path: Path
    ) -> Optional[Dict]:
        """
        Fetch hourly QPE accumulation.
        
        File pattern: st4_conus.YYYYMMDDHH.01h.grb2
        Variable: Total precipitation (kg/m^2 or mm)
        """
        pass
    
    def get_6hourly_precip(
        self,
        timestamp: datetime,
        bbox: List[float],
        output_path: Path
    ) -> Optional[Dict]:
        """
        Fetch 6-hourly QPE accumulation.
        
        File pattern: st4_conus.YYYYMMDDHH.06h.grb2
        """
        pass
    
    def _download_grib2(self, url: str, output_path: Path) -> Path:
        """Download GRIB2 file from NOMADS."""
        pass
    
    def _process_grib2_to_geotiff(
        self,
        grib_path: Path,
        bbox: List[float],
        output_path: Path
    ) -> Dict:
        """
        Extract precipitation band and convert to GeoTIFF.
        
        Steps:
        1. Open GRIB2 with rasterio/GDAL
        2. Read precipitation variable (band 1 typically)
        3. Subset to bounding box
        4. Convert units if needed (kg/m^2 to mm)
        5. Write GeoTIFF with proper metadata
        """
        pass
```

**Dependencies:**
- `rasterio` (GRIB2 support via GDAL)
- `requests` (HTTP downloads)
- Existing NOMADS infrastructure

**Testing:**
- Unit tests for date parsing
- Integration test for real file download
- GRIB2 to GeoTIFF conversion validation

---

### 1.2 Integrate into Raster Tasks
**File:** `src/acquisition/raster_tasks.py` (MODIFY)

**Changes:**
```python
def _fetch_nomads_layer(...):
    """Fetch layer from NOAA NOMADS."""
    try:
        if 'rtma2p5' in dataset.collection_id:
            # Existing RTMA logic
            ...
        elif 'pcpanl' in dataset.collection_id or 'stage4' in dataset.name.lower():
            # NEW: Stage IV logic
            from src.acquisition.nomads_stage4_client import Stage4QPEClient
            
            client = Stage4QPEClient()
            
            # Determine accumulation period (hourly vs 6-hourly)
            if variable.name in ['precip_1hr', 'apcp_1hr']:
                metadata = client.get_hourly_precip(
                    timestamp=timestamp,
                    bbox=bbox,
                    output_path=file_path
                )
            elif variable.name in ['precip_6hr', 'apcp_6hr']:
                metadata = client.get_6hourly_precip(
                    timestamp=timestamp,
                    bbox=bbox,
                    output_path=file_path
                )
            else:
                logger.warning(f"Unknown Stage IV variable: {variable.name}")
                return False
        else:
            # Unknown NOMADS product
            ...
```

---

### 1.3 Database Configuration
**File:** `apps/streamflow/management/commands/init_raster_datasets.py` (MODIFY)

**Add Stage IV Dataset:**
```python
# NCEP Stage IV QPE
stage4, created = RasterDataset.objects.get_or_create(
    name='NCEP_StageIV_QPE',
    defaults={
        'description': 'NCEP Stage IV Quantitative Precipitation Estimate - quality-controlled CONUS mosaic',
        'data_source': 'nomads',
        'collection_id': 'pcpanl/prod',  # NOMADS path segment
        'temporal_resolution': 'hourly',
        'spatial_resolution_m': 4000,  # 4km
        'coverage_area': 'CONUS',
        'variables_available': ['Total Precipitation'],
        'projection': 'EPSG:4326',
        'file_format': 'GRIB2',
        'access_url_pattern': 'https://nomads.ncep.noaa.gov/pub/data/nccf/com/pcpanl/prod/pcpanl.{YYYYMMDD}/st4_conus.{YYYYMMDDHH}.{period}.grb2',
        'update_frequency_hours': 1,
        'retention_days': 2,
    }
)

# Variables
precip_1hr, _ = RasterVariable.objects.get_or_create(
    dataset=stage4,
    name='precip_1hr',
    defaults={
        'description': '1-hour accumulated precipitation',
        'units': 'mm',
        'standard_name': 'precipitation_amount',
        'gee_band_name': 'apcp',  # Accumulated precipitation
    }
)

precip_6hr, _ = RasterVariable.objects.get_or_create(
    dataset=stage4,
    name='precip_6hr',
    defaults={
        'description': '6-hour accumulated precipitation',
        'units': 'mm',
        'standard_name': 'precipitation_amount',
        'gee_band_name': 'apcp',
    }
)
```

**Run Migration:**
```bash
python manage.py init_raster_datasets
```

---

## Phase 2: Frontend Configuration Interface (2-3 hours)

### 2.1 Update Configuration Form
**File:** `apps/streamflow/templates/streamflow/raster_config_form.html` (MODIFY)

**Changes:**
- Add Stage IV to dataset dropdown
- Show appropriate temporal resolution options (hourly/6-hourly)
- Update help text for NOMADS retention window

### 2.2 Variable Selection
**File:** `apps/streamflow/forms.py` (VERIFY/UPDATE)

**Ensure:**
- Variable checkboxes populate correctly for Stage IV
- Accumulation period labels are clear (1-hour vs 6-hour)
- Form validation handles Stage IV specific requirements

### 2.3 Configuration Detail View
**File:** `apps/streamflow/templates/streamflow/configuration_detail.html` (UPDATE)

**Add:**
- Display for accumulation period
- Link to NOMADS data source documentation
- Retention window warning (2 days only)

---

## Phase 3: REST API Integration (1-2 hours)

### 3.1 Serializer Updates
**File:** `apps/api/serializers/raster_serializers.py` (VERIFY)

**Ensure:**
- Stage IV datasets serialize correctly
- Variable metadata includes accumulation period
- API responses include data retention info

### 3.2 API Endpoints (existing)
**Files:** `apps/api/views/raster_views.py`, `apps/api/urls.py`

**Verify Existing Endpoints Work:**
- `GET /api/v1/raster/datasets/` - Lists Stage IV
- `GET /api/v1/raster/datasets/{id}/variables/` - Shows precip variables
- `POST /api/v1/raster/configurations/` - Can create Stage IV config
- `POST /api/v1/raster/configurations/{id}/trigger/` - Triggers pulls

**No new endpoints needed** - existing infrastructure supports new dataset type

### 3.3 API Documentation
**File:** `apps/api/views/raster_views.py` (UPDATE docstrings)

**Add Stage IV Examples:**
```python
"""
...
Example Stage IV configuration:
    {
        "name": "Stage IV CONUS 1-hour",
        "dataset": <stage4_id>,
        "extent": <conus_extent_id>,
        "variables": [<precip_1hr_id>],
        "lookback_days": 1,
        "schedule": "0 * * * *"  # Hourly
    }
"""
```

---

## Phase 4: Celery Scheduling & Monitoring (1 hour)

### 4.1 Beat Schedule
**File:** `config/celery.py` (ADD)

**New Schedule:**
```python
# NCEP Stage IV QPE - Hourly pulls
'stage4-qpe-hourly': {
    'task': 'src.acquisition.raster_tasks.scheduled_raster_pulls',
    'schedule': crontab(minute=15),  # :15 past each hour
    'kwargs': {
        'dataset_filter': 'NCEP_StageIV_QPE',
        'temporal_resolution': 'hourly'
    },
},
```

**Rationale:** 
- Stage IV has ~6 hour latency
- Hourly schedule ensures recent data captured
- :15 offset avoids RTMA conflicts

### 4.2 Monitoring Dashboard
**File:** `apps/streamflow/templates/streamflow/system_diagnostics.html` (UPDATE)

**Add Stage IV Section:**
- Recent pull status
- Files downloaded/processed
- Storage usage for precip data
- Alert if >24 hours without successful pull

---

## Phase 5: Testing & Validation (2-3 hours)

### 5.1 Unit Tests
**File:** `tests/test_stage4_client.py` (NEW)

**Test Cases:**
```python
def test_date_parsing():
    """Verify available date parsing from NOMADS directory."""
    pass

def test_url_construction():
    """Validate file URL patterns for hourly/6-hourly."""
    pass

def test_grib2_download():
    """Test actual file download (integration test)."""
    pass

def test_grib2_to_geotiff():
    """Verify GRIB2 conversion and metadata."""
    pass

def test_bbox_subsetting():
    """Ensure spatial subsetting works correctly."""
    pass
```

### 5.2 Integration Tests
**File:** `tests/test_stage4_integration.py` (NEW)

**Scenarios:**
```python
def test_create_stage4_configuration():
    """Create Stage IV config via API."""
    pass

def test_manual_trigger():
    """Manually trigger Stage IV pull."""
    pass

def test_scheduled_pull():
    """Verify Celery task execution."""
    pass

def test_data_retrieval():
    """Query pulled data via API."""
    pass
```

### 5.3 Real Data Validation
**Manual Testing:**
1. Create configuration for Pacific Northwest extent
2. Trigger pull for last 24 hours
3. Verify GeoTIFF files created
4. Validate precipitation values (sanity check)
5. Check database records (RasterLayer, PullLog)
6. Test API retrieval of layers

**Success Criteria:**
- Files downloaded without errors
- GeoTIFF files readable in QGIS/ArcGIS
- Precipitation values reasonable (0-200mm typical)
- Database records complete with metadata
- API returns correct layer information

---

## Phase 6: Documentation (1 hour)

### 6.1 User Documentation
**File:** `Documentation/Data-Sources/STAGE_IV_QPE.md` (NEW)

**Contents:**
- Data source overview
- Available variables and accumulation periods
- Spatial/temporal coverage
- Configuration examples
- Retention policy (2 days)
- Known limitations
- Troubleshooting guide

### 6.2 API Documentation
**Update:** OpenAPI schema automatically generated

**Manual Updates:**
- Add Stage IV example to API docs
- Document precip variable units (mm)
- Note CONUS-only coverage

### 6.3 Internal Documentation
**File:** `Documentation/Reference/STAGE_IV_TECHNICAL.md` (NEW)

**Technical Details:**
- GRIB2 band mapping
- Unit conversions
- NOMADS URL patterns
- Error handling strategies
- Performance benchmarks

---

## Implementation Checklist

### Backend (Phase 1)
- [ ] Create `nomads_stage4_client.py`
- [ ] Implement `Stage4QPEClient` class
- [ ] Add GRIB2 download method
- [ ] Add GRIB2 to GeoTIFF conversion
- [ ] Integrate into `raster_tasks.py`
- [ ] Update `init_raster_datasets.py`
- [ ] Run database initialization
- [ ] Unit tests for client methods
- [ ] Integration test with real data

### Frontend (Phase 2)
- [ ] Update configuration form template
- [ ] Verify variable selection works
- [ ] Update configuration detail view
- [ ] Test form submission
- [ ] Test manual trigger button

### API (Phase 3)
- [ ] Verify serializers handle Stage IV
- [ ] Test all existing endpoints
- [ ] Update API docstrings
- [ ] Regenerate OpenAPI schema
- [ ] Test API with Postman/curl

### Scheduling (Phase 4)
- [ ] Add Celery beat schedule
- [ ] Update monitoring dashboard
- [ ] Restart Celery workers
- [ ] Verify scheduled execution

### Testing (Phase 5)
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Run test suite (all passing)
- [ ] Manual testing with real data
- [ ] Validate output files
- [ ] Performance testing

### Documentation (Phase 6)
- [ ] User documentation
- [ ] API examples
- [ ] Technical reference
- [ ] Update main README
- [ ] Update STATUS.md

---

## Dependencies & Prerequisites

### System Requirements
- Existing NOMADS infrastructure (RTMA client)
- GDAL with GRIB2 support (already installed)
- Rasterio with GRIB driver (verify: `rio env --formats | grep GRIB`)
- Sufficient storage (~500MB per day for CONUS hourly)

### Configuration
- No authentication required (public NOMADS access)
- Network access to nomads.ncep.noaa.gov
- File system permissions for `/data/rasters/pcpanl/`

### Known Dependencies
- **GRIB2 Support:** Verify GDAL has GRIB driver
- **Storage:** ~20MB per hourly file × 24 hours × 2 days retention = ~1GB
- **Bandwidth:** ~20MB download per hour = ~480MB/day

---

## Risk Assessment

### Technical Risks

**1. GRIB2 Format Complexity**
- **Risk:** GRIB2 band indexing may vary
- **Mitigation:** Inspect sample files, add band validation
- **Severity:** Medium

**2. NOMADS Availability**
- **Risk:** Server downtime or file unavailability
- **Mitigation:** Implement retry logic, monitor with alerts
- **Severity:** Medium

**3. Storage Growth**
- **Risk:** 1GB/2-day retention adds up over time
- **Mitigation:** Cleanup task already implemented, monitor usage
- **Severity:** Low

**4. Unit Conversion**
- **Risk:** GRIB2 units may vary (kg/m^2 vs mm)
- **Mitigation:** Validate against known precipitation events
- **Severity:** Medium

### Operational Risks

**1. Data Latency**
- **Risk:** 6-hour lag may not meet real-time needs
- **Mitigation:** Document limitation clearly
- **Severity:** Low (expected)

**2. CONUS-Only Coverage**
- **Risk:** Users may expect global or regional coverage
- **Mitigation:** Clear documentation, UI warnings for non-CONUS extents
- **Severity:** Low

---

## Success Metrics

### Functional
- [ ] Stage IV dataset appears in configuration UI
- [ ] Manual pull completes successfully
- [ ] Scheduled pulls execute hourly
- [ ] GeoTIFF files created with correct metadata
- [ ] API returns Stage IV layers
- [ ] All tests passing (unit + integration)

### Performance
- [ ] Download time: <30 seconds per file
- [ ] Conversion time: <10 seconds per file
- [ ] End-to-end pull: <60 seconds
- [ ] Storage: <1GB for 2-day retention

### Quality
- [ ] Precipitation values validated against NWS reports
- [ ] No data corruption or missing files
- [ ] Proper handling of missing data (gaps in NOMADS)
- [ ] Error logs clear and actionable

---

## Timeline Estimate

| Phase | Task | Estimated Hours |
|-------|------|----------------|
| 1 | Backend Client | 3-4 hours |
| 1 | Task Integration | 1 hour |
| 1 | Database Config | 0.5 hours |
| 2 | Frontend Forms | 1.5 hours |
| 2 | Templates | 0.5 hours |
| 3 | API Verification | 0.5 hours |
| 3 | Documentation | 0.5 hours |
| 4 | Celery Schedule | 0.5 hours |
| 4 | Monitoring | 0.5 hours |
| 5 | Unit Tests | 1 hour |
| 5 | Integration Tests | 1 hour |
| 5 | Manual Validation | 1 hour |
| 6 | Documentation | 1 hour |

**Total Estimated Time:** 12-13 hours

**Suggested Schedule:**
- **Day 1 (4 hours):** Backend client development + testing
- **Day 2 (4 hours):** Integration + frontend + API
- **Day 3 (4 hours):** Testing + validation + documentation

---

## Post-Implementation

### Monitoring
- Add Stage IV to system diagnostics dashboard
- Configure alerts for failed pulls (>6 hours without success)
- Monitor storage usage weekly

### Maintenance
- Review NOMADS retention policy quarterly
- Update URL patterns if NOMADS structure changes
- Validate against NWS precipitation reports monthly

### Enhancements (Future)
1. **Archive Access:** Implement NCDC archive retrieval for historical data
2. **Forecast Integration:** Add Stage II (radar-only) for nowcasting
3. **Bias Correction:** Integrate gauge-adjusted Stage IV product
4. **Regional Products:** Add RFC-specific Stage III products

---

## References

- **NOMADS Stage IV:** https://nomads.ncep.noaa.gov/pub/data/nccf/com/pcpanl/prod/
- **Stage IV Documentation:** https://water.noaa.gov/resources/downloads/precip/stageIV/
- **GRIB2 Specification:** https://www.nco.ncep.noaa.gov/pmb/docs/grib2/
- **Existing RTMA Implementation:** `src/acquisition/nomads_client.py`

---

**Created by:** StreamFlow DataOps Team  
**Last Updated:** January 29, 2026  
**Status:** Ready for Implementation
