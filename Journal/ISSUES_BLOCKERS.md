# Issues and Blockers Log

**Project:** StreamFlow DataOps Implementation  
**Purpose:** Track problems, blockers, and their resolutions

---

## Issue Template

```
## [#ID] Issue Title
**Date Reported:** YYYY-MM-DD
**Status:** Open / In Progress / Resolved / Closed
**Severity:** Critical / High / Medium / Low
**Phase:** Phase number
**Reporter:** Name/System
**Description:** Clear description of the issue
**Impact:** What is affected
**Workaround:** Temporary solution (if any)
**Resolution:** How it was resolved
**Date Resolved:** YYYY-MM-DD
```

---

## Active Issues

### [#007] MODIS HDF4 Processing - Rasterio Compatibility Issue
**Date Reported:** January 29, 2026  
**Status:** 🔴 Open - Blocked  
**Severity:** High  
**Phase:** Phase 11 - Raster Acquisition  
**Reporter:** System Testing  
**Description:** Rasterio Python library cannot open HDF4_EOS subdatasets for MODIS data processing. While command-line `gdalinfo` successfully opens and reads the HDF4 files, rasterio.open() fails with "No such file or directory" error when attempting to open HDF4_EOS subdataset paths.

**Technical Details:**
- Files successfully download from NASA EarthData (3-5 MB HDF4 files)
- Command-line GDAL works: `gdalinfo 'HDF4_EOS:EOS_GRID:"path":MODIS_Grid_Daily_1km_LST:LST_Day_1km'` ✅
- Python rasterio fails: `rasterio.open('HDF4_EOS:EOS_GRID:"path":MODIS_Grid_Daily_1km_LST:LST_Day_1km')` ❌
- Error message: "No such file or directory"
- GDAL HDF4 drivers confirmed available: `gdalinfo --formats | grep HDF4` shows HDF4/HDF4Image support

**Impact:** 
- MODIS LST (Terra & Aqua) datasets non-functional (2/5 raster data sources)
- Land surface temperature data unavailable
- 40% of planned raster data sources blocked

**Workaround:** None currently implemented

**Proposed Solutions:**
1. **Install Python GDAL bindings** (`python-gdal` or `gdal` package) and rewrite processor to use GDAL directly
2. **Upgrade rasterio** to newer version with better HDF4 support
3. **Alternative preprocessing** - Convert HDF4 to GeoTIFF using command-line GDAL before processing with rasterio

**Dependencies:** Python environment (miniconda3), GDAL library (system has HDF4 support)

**Priority:** High - blocking 40% of raster data functionality

---

## Recently Resolved Issues (January 20, 2026)

### [#005] DischargeObservation Filterset Configuration Error
**Date Reported:** January 17, 2026  
**Status:** ✅ Resolved  
**Severity:** Medium  
**Phase:** Phase 5  
**Description:** DischargeObservation ViewSet had filterset_fields containing non-model fields (`station_number`, `data_type`, `is_provisional`, `data_source`) that are properties on the serializer, not database fields. This caused TypeError: "'Meta.fields' must not contain non-model field names".  
**Impact:** 7 API tests failing for DischargeObservation endpoints  
**Resolution:** 
- Updated `apps/api/views/observation.py` filterset_fields to only include actual model fields: `['station', 'quality_code', 'type', 'unit']`
- Updated serializer to add `station_number` as computed field via `source='station.station_number'`
- Updated all query methods to use correct field names (`observed_at` not `timestamp`, `discharge` not `value`)
- All 5 DischargeObservation tests now passing  
**Date Resolved:** January 20, 2026

### [#006] DataPullLogViewSet Not Registered
**Date Reported:** January 17, 2026  
**Status:** ✅ Resolved  
**Severity:** Medium  
**Phase:** Phase 5  
**Description:** DataPullLogViewSet was planned but never created or registered in the API router, causing 4 tests to fail with "Reverse for 'datapulllog-list' not found".  
**Impact:** 4 API tests skipped, missing endpoint in API  
**Resolution:**
- Created `apps/api/views/log.py` with DataPullLogViewSet (ReadOnlyModelViewSet)
- Created `apps/api/serializers/log.py` with DataPullLogSerializer and DataPullLogListSerializer
- Registered in `apps/api/urls.py`: `router.register(r'logs', DataPullLogViewSet, basename='log')`
- Updated test URLs from `api:datapulllog-list` to `api:log-list`
- Added to `__init__.py` exports
- All 4 DataPullLog tests now passing  
**Date Resolved:** January 20, 2026

### [#007] Pagination Limit Parameter Not Respected
**Date Reported:** January 17, 2026  
**Status:** ✅ Resolved  
**Severity:** Low  
**Phase:** Phase 5  
**Description:** API pagination was not respecting the `limit` query parameter. DRF's default PageNumberPagination only uses `page` parameter, not `limit`.  
**Impact:** 1 test failing, API consumers cannot control page size via `limit` parameter  
**Resolution:**
- Created `apps/api/pagination.py` with StandardResultsSetPagination class
- Added `page_size_query_param = 'limit'` to allow clients to set page size
- Set `max_page_size = 1000` to prevent abuse
- Updated `config/settings.py` REST_FRAMEWORK to use custom pagination class
- Added pagination_class to viewsets
- Pagination test now passing  
**Date Resolved:** January 20, 2026

---

## Previously Resolved Issues

### [#002] psycopg2-binary Installation Failed
**Date Reported:** January 16, 2026  
**Status:** ✅ Resolved (Workaround)  
**Severity:** Low  
**Phase:** Phase 0  
**Description:** Attempted to install psycopg2-binary==2.9.9 from requirements.txt. Installation failed with error: "pg_config executable not found". This is because PostgreSQL development libraries are not installed on the system.  
**Impact:** Cannot use PostgreSQL database immediately. Limited to SQLite for development.  
**Workaround:** Use SQLite for all development phases. Documented in Decision [D015].  
**Resolution:** Decided to use SQLite for development, PostgreSQL for production only. If PostgreSQL needed for development, install postgresql-devel package or use Docker.  
**Date Resolved:** January 16, 2026

### [#003] Static Files Directory Missing
**Date Reported:** January 16, 2026  
**Status:** 📝 Open (Low Priority)  
**Severity:** Low  
**Phase:** Phase 0  
**Description:** Django `manage.py check` reports warning: "The directory '/home/mrguy/Proj/streamflow-dataOps/streamflow-dataOps/static' in the STATICFILES_DIRS setting does not exist."  
**Impact:** Warning only, doesn't affect functionality. Django staticfiles won't work until created.  
**Workaround:** None needed for Phase 0.  
**Resolution:** Will create `static/` directory in Phase 1 when working on UI.  
**Target Date:** Phase 1

### [#004] Existing Tests Use SQLAlchemy (Not Django ORM)
**Date Reported:** January 16, 2026  
**Status:** 📝 Open (Medium Priority)  
**Severity:** Medium  
**Phase:** Phase 0  
**Description:** The project has 5 test files (test_data_processor.py, test_models.py, test_repositories.py, test_smart_append.py, test_usgs_client.py) but they were written for the original SQLAlchemy implementation, not Django ORM. Tests cannot run in current state.  
**Impact:** Cannot run automated tests until updated. Test coverage is 0%.  
**Workaround:** Manual testing for now.  
**Resolution:** Update tests to use Django ORM and pytest-django in Phase 1-2.  
**Estimated Effort:** 1-2 days  
**Target Phase:** Phase 1 (during UI development)

---

## Resolved Issues

### [#001] Example Placeholder Issue
**Status:** 📝 Template (Removed)  
This was just a template example.

---

## Blockers

### Critical Blockers (Stopping Work)

None.

---

### High Priority Blockers (Impacting Schedule)

None.

---

### Medium Priority Blockers (May Impact Schedule)

None.

---

## Technical Debt

### Identified Technical Debt

#### [TD001] Update Acquisition Layer to Use Django ORM
**Date Identified:** January 16, 2026  
**Status:** 📋 Planned  
**Description:** Component 2 (acquisition layer) was originally built with SQLAlchemy. Needs conversion to Django ORM.  
**Impact:** Code inconsistency, harder maintenance  
**Priority:** High  
**Target Phase:** Phase 3  
**Estimated Effort:** 1-2 days

#### [TD002] Incomplete Templates in Component 3
**Date Identified:** January 16, 2026  
**Status:** 📋 Planned  
**Description:** Some templates in `apps/streamflow/templates/` are stubs or incomplete.  
**Impact:** Non-functional UI pages  
**Priority:** High  
**Target Phase:** Phase 1  
**Estimated Effort:** 3-4 days

---

## Risks and Concerns

### [R001] Performance with 1,500+ Stations
**Category:** Performance  
**Probability:** Medium  
**Impact:** High  
**Description:** Data collection and API queries may be slow with full station list.  
**Mitigation:**
- Early performance testing
- Query optimization
- Caching strategy
- Chunking and pagination
**Status:** 🟡 Monitoring

### [R002] USGS API Rate Limiting
**Category:** External Dependency  
**Probability:** High  
**Impact:** Medium  
**Description:** USGS may rate limit or block requests if we exceed limits.  
**Mitigation:**
- Respect rate limits (current: 0.5s delay)
- Implement exponential backoff
- Monitor 429 responses
- Consider caching
**Status:** 🟡 Monitoring

### [R003] Data Consistency During Migration
**Category:** Data Integrity  
**Probability:** Medium  
**Impact:** High  
**Description:** Risk of data loss or corruption when migrating from dashboard database.  
**Mitigation:**
- Comprehensive validation scripts
- Backup before migration
- Dry-run testing
- Parallel operation period
**Status:** 🟡 Monitoring

---

## Questions and Unknowns

### [Q001] PostgreSQL or SQLite for Development?
**Status:** ❓ Open  
**Context:** Plan says PostgreSQL for production, SQLite for dev. Do we need both?  
**Impact:** Development environment setup complexity  
**Decision Needed By:** Phase 0  
**Options:**
1. Support both (requires compatibility testing)
2. PostgreSQL only (requires Docker/local install)
3. SQLite only (may miss PostgreSQL-specific issues)

### [Q002] How to Handle Dashboard During Transition?
**Status:** ❓ Open  
**Context:** Dashboard currently collects its own data. When to switch to API?  
**Impact:** Production availability  
**Decision Needed By:** Phase 4  
**Options:**
1. Hard cutover (risky)
2. Parallel operation with manual sync (complex)
3. Feature flag to toggle between sources (preferred)

---

## Lessons Learned

### [L001] Branch Management
**Date:** January 16, 2026  
**Context:** Had separate `master` and `main` branches with divergent content.  
**Lesson:** Establish single primary branch early; avoid parallel development on multiple branches.  
**Action Taken:** Merged master → main, deleted master branch.

---

## Communication Log

### Internal Notes

**January 16, 2026:**
- Project kickoff
- Completed project analysis
- Created implementation plan
- Set up Journal system

---

## Dependencies Tracking

### External Dependencies

| Dependency | Current Version | Required Version | Status | Notes |
|-----------|----------------|------------------|--------|-------|
| Django | 4.2.7 | 4.2+ | ✅ OK | Installed |
| Celery | 5.3.4 | 5.3+ | ✅ OK | Installed |
| Redis | 5.0.1 | 5.0+ | ✅ OK | Installed |
| PostgreSQL | - | 12+ | ⚠️ TBD | Need to verify |
| DRF | - | 3.14+ | ❌ NOT INSTALLED | Phase 2 |

### Internal Dependencies (Between Phases)

- Phase 1 → Phase 2: UI informs API design
- Phase 2 → Phase 3: API must exist before integration
- Phase 3 → Phase 4: Backend must be stable before dashboard integration
- Phases 1-4 → Phase 5: All features complete before comprehensive testing

---

## Issue Statistics

**Total Issues:** 0  
**Open:** 0  
**In Progress:** 0  
**Resolved:** 0  
**Closed:** 0

**By Severity:**
- Critical: 0
- High: 0
- Medium: 0
- Low: 0

**By Phase:**
- Phase 0: 0
- Phase 1: 0
- Phase 2: 0
- Phase 3: 0
- Phase 4: 0
- Phase 5: 0

---

**Last Updated:** January 16, 2026, 1:30 PM
