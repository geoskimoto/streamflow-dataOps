# Quick Start: Running Raster Data Tests

## Prerequisites

1. **Database Setup**
```bash
# Grant test database permissions (one-time setup)
sudo -u postgres psql -c "ALTER USER streamflow_user CREATEDB;"
sudo -u postgres psql -c "ALTER USER streamflow_user SUPERUSER;"
```

2. **Dependencies**
```bash
pip install selenium==4.40.0
```

3. **GEE Credentials** (for integration tests)
Create `.env` file with:
```env
GEE_SERVICE_ACCOUNT_KEY=./rtmaandsma-fe989e72b62e.json
GEE_PROJECT_ID=rtmaandsmap
GEE_SERVICE_ACCOUNT_EMAIL=gee-access@rtmaandsma.iam.gserviceaccount.com
```

---

## Run Tests

### Quick: Run All API Tests (18 tests)
```bash
python manage.py test tests.test_raster_frontend.RasterAPIEndpointsTest \
    tests.test_raster_frontend.RasterAPIResponseFormatTest \
    tests.test_raster_frontend.RasterErrorHandlingTest --verbosity=2
```

**Expected Result:** All 18 tests pass in ~0.2 seconds ✅

---

### Full: Run GEE Integration Tests (23 tests)
```bash
# Requires valid GEE credentials
python manage.py test tests.test_gee_integration --verbosity=2
```

**Expected Result:** All 23 tests pass (may take 2-5 minutes due to API calls)

**Tests:**
- GEE authentication verification (4 tests)
- Data availability checks (2 tests)
- RTMA data pulls (5 tests)
- SMAP data pulls (3 tests)
- GeoTIFF export (2 tests)
- Raster processing (3 tests)
- Database operations (3 tests)
- End-to-end workflow (1 test)

---

### Optional: Run Selenium UI Tests
```bash
# Install chromedriver first
sudo apt install chromium-chromedriver  # Ubuntu/Debian
# OR
brew install chromedriver               # macOS

# Run tests
python manage.py test tests.test_raster_frontend.RasterFrontendSeleniumTest --verbosity=2
```

---

### Run Everything
```bash
python manage.py test tests.test_raster_frontend tests.test_gee_integration --verbosity=2
```

---

## Test Results Summary

| Test Suite | Tests | Status | Duration |
|------------|-------|--------|----------|
| API Endpoints | 9 | ✅ Passing | ~0.1s |
| Response Format | 5 | ✅ Passing | ~0.05s |
| Error Handling | 4 | ✅ Passing | ~0.02s |
| **API Total** | **18** | **✅ All Pass** | **~0.17s** |
| GEE Integration | 23 | ⏳ Ready | ~2-5 min |
| Selenium UI | 3 | ⚠️ Optional | ~5-10s |
| **Grand Total** | **44** | **18/44 Passing** | - |

---

## Common Issues

### Issue: "Permission denied to create database"
**Fix:**
```bash
sudo -u postgres psql -c "ALTER USER streamflow_user CREATEDB;"
```

### Issue: "Permission denied to create extension postgis"
**Fix:**
```bash
sudo -u postgres psql -c "ALTER USER streamflow_user SUPERUSER;"
```

### Issue: "No module named 'selenium'"
**Fix:**
```bash
pip install selenium
```

### Issue: "Selenium driver not available"
**This is normal** - Selenium tests are optional and will be skipped if chromedriver is not installed.

### Issue: GEE Authentication Failed
**Check:**
1. Service account key file exists: `ls -la rtmaandsma-fe989e72b62e.json`
2. `.env` has correct GEE_* variables
3. Service account has GEE project permissions

---

## Test Output Examples

### ✅ Successful Run
```
Found 18 test(s).
Creating test database for alias 'default' ('test_streamflow_db')...
System check identified no issues (0 silenced).

test_raster_coverage_endpoint ... ok
test_raster_datasets_list ... ok
test_raster_layer_detail ... ok
... (15 more tests)

----------------------------------------------------------------------
Ran 18 tests in 0.170s

OK
```

### ❌ Failed Test Example
```
FAIL: test_raster_datasets_list
----------------------------------------------------------------------
AttributeError: 'RasterDataset' object has no attribute 'rastervariable_set'
```
*This was fixed - related_name issues in serializers*

---

## Next Steps

After all tests pass:

1. **Commit test results** to Journal
2. **Run actual data pull** with management commands
3. **Verify data files** created in `data/rasters/`
4. **Test API in browser** at `/api/v1/docs/`
5. **Configure Celery** for automated pulls

---

## Resources

- Full test report: `Documentation/TEST_SUITE_REPORT.md`
- Test files:
  - `tests/test_raster_frontend.py` (API tests)
  - `tests/test_gee_integration.py` (GEE tests)
- API Documentation: http://localhost:8000/api/v1/docs/
- Django Test Guide: https://docs.djangoproject.com/en/4.2/topics/testing/

---

**Last Updated:** January 27, 2026  
**Status:** API tests passing (18/18), GEE tests ready to run
