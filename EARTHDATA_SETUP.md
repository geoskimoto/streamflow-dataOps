# NASA EarthData Setup Guide

## Overview

This guide walks you through setting up authentication for NASA EarthData to access satellite and raster datasets.

---

## Step 1: Create EarthData Account

1. Visit: https://urs.earthdata.nasa.gov/users/new
2. Fill out registration form
3. Verify your email address
4. Log in to confirm account is active

**Note**: Account creation is instant and free. No payment information required.

---

## Step 2: Approve Applications

Some datasets require application approval:

1. Log in to: https://urs.earthdata.nasa.gov/
2. Go to "Applications" → "Authorized Apps"
3. Approve these applications:
   - **NASA GESDISC DATA ARCHIVE** (for GPM precipitation)
   - **NSIDC_DATAPOOL_OPS** (for SMAP soil moisture)
   - **LP DAAC Data Pool** (for MODIS temperature)

**Note**: Approvals are instant for most users.

---

## Step 3: Configure Authentication

Choose one of these two methods:

### Method A: .netrc File (Recommended)

Create or edit `~/.netrc` file:

```bash
# Create .netrc file
cat > ~/.netrc << 'EOF'
machine urs.earthdata.nasa.gov
    login your_username
    password your_password
EOF

# Set proper permissions (REQUIRED)
chmod 600 ~/.netrc
```

**Important**: Replace `your_username` and `your_password` with your actual credentials.

### Method B: Environment Variables

Add to your `.env` file or shell profile:

```bash
export EARTHDATA_USERNAME=your_username
export EARTHDATA_PASSWORD=your_password
```

For Django development, add to `.env`:
```
EARTHDATA_USERNAME=your_username
EARTHDATA_PASSWORD=your_password
```

---

## Step 4: Test Authentication

Run the test script:

```bash
python test_earthdata_auth.py
```

Expected output:
```
╔==========================================================╗
║          NASA EarthData Client Test Suite               ║
╚==========================================================╝

============================================================
TEST 1: Authentication
============================================================
✅ Successfully authenticated with NASA EarthData
   Auth method: .netrc

============================================================
TEST 2: SMAP Granule Search
============================================================
Searching for SMAP data:
  Collection: SPL4SMGP_008
  Date range: 2026-01-26 to 2026-01-27
  Bounding box: [-124.7, 41.5, -108.0, 49.0]
✅ Found 5 SMAP granules

   Granule 1:
     Size: 156.3 MB
     Producer: 2026-01-27T12:00:00.000Z
...
```

---

## Step 5: Verify Collections Access

Test access to each dataset:

### SMAP Soil Moisture
```python
from src.acquisition.earthdata_client import EarthDataClient
from datetime import datetime, timedelta

client = EarthDataClient()

# Check SMAP availability
bbox = [-124.7, 41.5, -108.0, 49.0]  # HUC17
end_date = datetime.now() - timedelta(days=2)
start_date = end_date - timedelta(days=1)

availability = client.check_data_availability(
    collection_id='SPL4SMGP_008',
    bbox=bbox,
    start_date=start_date,
    end_date=end_date
)

print(availability)
# {'available': True, 'count': 8, 'message': 'Found 8 granules'}
```

### GPM Precipitation
```python
# Note: GPM IMERG Final has ~3.5 month latency
end_date = datetime.now() - timedelta(days=120)
start_date = end_date - timedelta(days=1)

availability = client.check_data_availability(
    collection_id='GPM_3IMERGDF_07',
    bbox=bbox,
    start_date=start_date,
    end_date=end_date
)

print(availability)
# {'available': True, 'count': 1, 'message': 'Found 1 granules'}
```

---

## Troubleshooting

### Authentication Failed

**Error**: `EarthDataAuthenticationError: Authentication failed`

**Solutions**:
1. Verify username/password are correct
2. Check `.netrc` file permissions: `chmod 600 ~/.netrc`
3. Try environment variables instead
4. Confirm EarthData account is active

### No Granules Found

**Error**: `Found 0 granules`

**Solutions**:
1. Check date range - some datasets have latency:
   - SMAP: ~1-2 days
   - GPM IMERG Final: ~3.5 months
   - MODIS: ~1-2 days
2. Verify bounding box covers data extent
3. Confirm collection ID is correct

### Permission Denied

**Error**: `401 Unauthorized` or `403 Forbidden`

**Solutions**:
1. Go to https://urs.earthdata.nasa.gov/
2. Navigate to "Applications" → "Authorized Apps"
3. Approve required applications (GESDISC, NSIDC, LP DAAC)
4. Wait 5-10 minutes for permissions to propagate

### Download Slow or Fails

**Solutions**:
1. Use wired connection (faster than WiFi)
2. Download during off-peak hours
3. Check NASA EarthData status: https://status.earthdata.nasa.gov/
4. Increase timeout in client (default 300s)

---

## Available Datasets

### SMAP Level-4 Soil Moisture (SPL4SMGP_008)
- **Resolution**: 9 km
- **Temporal**: 3-hourly
- **Latency**: 1-2 days
- **Coverage**: Global (85°N to 85°S)
- **Variables**: Surface (0-5cm), root zone (0-100cm) soil moisture
- **Size**: ~150 MB per file (HDF5)
- **DAAC**: NSIDC

### GPM IMERG Final Daily (GPM_3IMERGDF_07)
- **Resolution**: 0.1° (~10 km)
- **Temporal**: Daily
- **Latency**: 3.5 months
- **Coverage**: 60°N to 60°S
- **Variables**: Precipitation rate (mm/day)
- **Size**: ~40 MB per file (NetCDF4/HDF5)
- **DAAC**: GES DISC

### MODIS Land Surface Temperature (MOD11A1_061, MYD11A1_061)
- **Resolution**: 1 km
- **Temporal**: Daily (day + night)
- **Latency**: 1-2 days
- **Coverage**: Global
- **Variables**: LST day/night, QC, emissivity
- **Size**: ~20 MB per tile (HDF4)
- **DAAC**: LP DAAC
- **Note**: Data in sinusoidal tiles, requires mosaicking

---

## Integration with Django

Add to `config/settings.py`:

```python
# NASA EarthData Configuration
EARTHDATA_USERNAME = os.getenv('EARTHDATA_USERNAME', '')
EARTHDATA_PASSWORD = os.getenv('EARTHDATA_PASSWORD', '')

# Data source collections
EARTHDATA_COLLECTIONS = {
    'SMAP_SPL4': 'SPL4SMGP_008',
    'GPM_IMERG': 'GPM_3IMERGDF_07',
    'MODIS_LST_TERRA': 'MOD11A1_061',
    'MODIS_LST_AQUA': 'MYD11A1_061',
}
```

---

## Best Practices

1. **Cache Downloads**: SMAP files are 150+ MB - implement local caching
2. **Use .netrc**: More secure than environment variables
3. **Check Latency**: Always subtract latency days from current date
4. **Handle Errors**: Network issues are common, implement retry logic
5. **Respect Limits**: Don't hammer the API - use reasonable search limits
6. **Clean Up**: Delete downloaded HDF5/NetCDF after converting to GeoTIFF

---

## Additional Resources

- **EarthData Search**: https://search.earthdata.nasa.gov/
- **CMR API Docs**: https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html
- **earthaccess Library**: https://earthaccess.readthedocs.io/
- **NSIDC (SMAP)**: https://nsidc.org/data/smap
- **GES DISC (GPM)**: https://disc.gsfc.nasa.gov/datasets/GPM_3IMERGDF_07
- **LP DAAC (MODIS)**: https://lpdaac.usgs.gov/products/mod11a1v061/

---

## Support

For issues with:
- **This implementation**: Open GitHub issue or check `MIGRATION_PLAN_EARTHDATA_NOMADS.md`
- **EarthData authentication**: Contact support@earthdata.nasa.gov
- **Dataset access**: Contact specific DAAC support (links above)
