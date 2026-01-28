# Google Earth Engine Implementation Archive

**Date Archived**: January 28, 2026  
**Reason**: Migration to NASA EarthData + NOAA NOMADS public data sources  
**Branch**: feature/raster-data-gee (commits prior to migration)

---

## Why GEE Was Archived

The Google Earth Engine implementation was replaced with NASA EarthData and NOAA NOMADS for the following reasons:

1. **Cost Concerns**: GEE commercial usage requires payment; cannot sustain costs for production use
2. **Open Access**: NASA EarthData and NOAA NOMADS provide free, unrestricted access to all data
3. **Public Sources**: Better alignment with open science principles
4. **Simpler Architecture**: Direct file downloads vs. cloud processing exports
5. **Vendor Independence**: No lock-in to proprietary platform

---

## What Was Replaced

### Datasets Migrated

| GEE Dataset | Replacement | Notes |
|-------------|-------------|-------|
| NOAA/NWS/RTMA | NOAA NOMADS RTMA GRIB2 | Direct download, same source |
| NASA/SMAP/SPL4SMGP/008 | EarthData SPL4SMGP_008 | Same dataset, direct HDF5 access |
| N/A | EarthData GPM_3IMERGDF_07 | Better precipitation product |
| N/A | EarthData MOD11A1_061 | MODIS land surface temperature |

### Files Archived

1. **src/acquisition/gee_client.py** (426 lines)
   - `GEEClient` class
   - Methods: `get_rtma_image()`, `get_smap_image()`, `export_to_geotiff()`
   - Authentication via service account

2. **tests/test_gee_integration.py** (639 lines)
   - 6 test classes, 28 tests total
   - Coverage: authentication, data availability, RTMA pulls, SMAP pulls, GeoTIFF export

### Related Commits

- Initial GEE implementation: [commit hash from feature/raster-data-gee]
- Last working GEE version: 330faa0 (Jan 27, 2026)

---

## Rollback Instructions

If migration fails and GEE access needs to be restored:

### 1. Restore Files
```bash
# From archive directory
cp archive/gee_implementation_jan2026/gee_client.py src/acquisition/
cp archive/gee_implementation_jan2026/test_gee_integration.py tests/
```

### 2. Restore Dependencies
```bash
# Add back to requirements.txt
echo "earthengine-api==0.1.384" >> requirements.txt
echo "google-auth==2.27.0" >> requirements.txt
pip install -r requirements.txt
```

### 3. Restore Settings
```python
# config/settings.py
GEE_SERVICE_ACCOUNT_EMAIL = os.getenv('GEE_SERVICE_ACCOUNT_EMAIL', '')
GEE_SERVICE_ACCOUNT_KEY = os.getenv('GEE_SERVICE_ACCOUNT_KEY', '')

GEE_DATASETS = {
    'RTMA': 'NOAA/NWS/RTMA',
    'SMAP_SPL4': 'NASA/SMAP/SPL4SMGP/008',
}
```

### 4. Restore Service Account
- Obtain new GEE service account key from Google Cloud Console
- Place in `config/gee-service-account.json`
- Set environment variable: `GEE_SERVICE_ACCOUNT_KEY=/path/to/key.json`

### 5. Re-authenticate
```bash
earthengine authenticate --service-account
```

### 6. Run Tests
```bash
python manage.py test tests.test_gee_integration
```

---

## Key Differences: GEE vs. EarthData/NOMADS

### Authentication
- **GEE**: Service account JSON key, OAuth for personal use
- **EarthData**: Username/password in .netrc file
- **NOMADS**: No authentication required

### Data Access
- **GEE**: Query collections via Python API, cloud-side filtering
- **EarthData**: Query CMR API for granule URLs, download HDF5/NetCDF
- **NOMADS**: Direct HTTP/FTP download of GRIB2 files

### Processing
- **GEE**: Server-side processing, export tasks, async results
- **EarthData**: Client-side processing of downloaded files
- **NOMADS**: Client-side GRIB2 decoding and extraction

### Formats
- **GEE**: GeoTIFF export only
- **EarthData**: HDF5, NetCDF4 → convert to GeoTIFF
- **NOMADS**: GRIB2 → convert to GeoTIFF

### Performance
- **GEE**: Fast queries, slow exports (task queue)
- **EarthData**: Fast downloads, client processing
- **NOMADS**: Very fast (US-based servers)

---

## Lessons Learned

### What Worked Well with GEE
- Unified API for multiple datasets
- Server-side processing reduced client load
- Good documentation and community support
- Integrated authentication

### Challenges with GEE
- Service account setup complexity
- Export task delays (minutes to hours)
- Quota limits on compute and exports
- Cost barrier for production use
- Vendor lock-in concerns

### Advantages of New Approach
- No cost barriers
- Direct file control
- Standard formats (HDF5, GRIB2, NetCDF)
- Better for offline/archival workflows
- Transparent data provenance

---

## Reference Documentation

### GEE Resources
- Official Docs: https://developers.google.com/earth-engine
- Python API: https://developers.google.com/earth-engine/guides/python_install
- RTMA Collection: https://developers.google.com/earth-engine/datasets/catalog/NOAA_NWS_RTMA
- SMAP Collection: https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL4SMGP_008

### Migration Resources
- Migration Plan: `/MIGRATION_PLAN_EARTHDATA_NOMADS.md`
- New EarthData Client: `src/acquisition/earthdata_client.py` (to be created)
- New NOMADS Client: `src/acquisition/nomads_client.py` (to be created)

---

## Contact

For questions about this archive or GEE implementation details, refer to:
- Git history: `git log --all -- src/acquisition/gee_client.py`
- Journal entries: `Journal/SESSION_JAN_27_2026_RASTER.md`
- Phase 10 notes: `Journal/PROGRESS_TRACKER.md`

**Last Updated**: January 28, 2026
