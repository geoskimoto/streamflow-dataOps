# Django Management Commands Reference

Complete reference for all custom `manage.py` commands in the StreamFlow DataOps application.

---

## Table of Contents

### Timeseries Station Management
- [load_master_stations](#load_master_stations) - Import USGS stations
- [load_ec_stations](#load_ec_stations) - Import Environment Canada stations
- [import_noaa_rfc_stations](#import_noaa_rfc_stations) - Import NOAA RFC stations
- [add_huc17_stations](#add_huc17_stations) - Add Columbia River Basin stations
- [sync_stations](#sync_stations) - Create Station records from MasterStation
- [populate_station_mappings](#populate_station_mappings) - Create station lookup mappings
- [load_station_mappings](#load_station_mappings) - Load station mappings from CSV
- [populate_usgs_historical](#populate_usgs_historical) - Populate complete historical discharge data

### Gridded/Raster Data Management
- [init_raster_datasets](#init_raster_datasets) - Initialize all raster datasets
- [pull_raster_data](#pull_raster_data) - Manually pull raster data
- [backfill_rasters](#backfill_rasters) - Backfill historical raster data
- [setup_raster_datasets](#setup_raster_datasets) - Legacy setup command
- [setup_spatial_extents](#setup_spatial_extents) - Setup spatial extent definitions
- [create_raster_config](#create_raster_config) - Interactive config creation

### Testing & Diagnostics
- [test_gee_connection](#test_gee_connection) - Test Google Earth Engine connection
- [test_earthdata_integration](#test_earthdata_integration) - Test NASA EarthData authentication
- [test_nomads_rtma](#test_nomads_rtma) - Test NOAA NOMADS RTMA data access
- [test_modis_lst](#test_modis_lst) - Test MODIS land surface temperature data

---

## Timeseries Station Management

### load_master_stations

Load USGS stream gauge stations into the master station list.

**Usage:**
```bash
# By state
python manage.py load_master_stations --state WA
python manage.py load_master_stations --state OR

# By HUC code
python manage.py load_master_stations --huc 17
python manage.py load_master_stations --huc 02070010

# Clear existing first
python manage.py load_master_stations --state CA --clear

# Specify site type (default: ST for stream)
python manage.py load_master_stations --state ID --site-type ST
```

**Arguments:**
- `--state` - State code (e.g., WA, OR, CA, ID, MT)
- `--huc` - HUC code (2, 4, or 8-digit)
- `--site-type` - Site type code (default: ST for stream)
- `--clear` - Clear existing stations before loading

**What it does:**
- Fetches USGS stations using the dataretrieval package
- Filters for stream gauges with discharge (parameter 00060)
- Filters for sites with daily values available
- Creates or updates MasterStation records
- Records: station_number, name, lat/lon, state, HUC, altitude, drainage area

**Common use cases:**
```bash
# Western US states
python manage.py load_master_stations --state WA
python manage.py load_master_stations --state OR
python manage.py load_master_stations --state CA
python manage.py load_master_stations --state ID
python manage.py load_master_stations --state MT

# Pacific Northwest (Columbia River Basin)
python manage.py load_master_stations --huc 17
```

---

### load_ec_stations

Load Environment Canada stations (British Columbia).

**Usage:**
```bash
# Load BC stations (currently requires manual data)
python manage.py load_ec_stations --province BC

# Clear existing EC stations first
python manage.py load_ec_stations --province BC --clear
```

**Arguments:**
- `--province` - Province code (default: BC)
- `--clear` - Clear existing EC stations before loading

**What it does:**
- **Note:** Currently shows instructions for manual loading due to EC API changes
- Provides guidance for downloading station data from https://wateroffice.ec.gc.ca/
- Marks stations with agency='EC'

**Status:** Requires manual data download or CSV loading. See command output for instructions.

---

### import_noaa_rfc_stations

Import stations from NOAA River Forecast Centers (RFC).

**Usage:**
```bash
# By states
python manage.py import_noaa_rfc_stations --states WA OR CA ID MT

# By specific RFC
python manage.py import_noaa_rfc_stations --rfc NWRFC
python manage.py import_noaa_rfc_stations --rfc CNRFC
python manage.py import_noaa_rfc_stations --rfc CBRFC

# Include British Columbia stations from NWRFC
python manage.py import_noaa_rfc_stations --states WA OR --include-bc

# Only gauges with active forecasts (default behavior)
python manage.py import_noaa_rfc_stations --states WA OR --forecasts-only

# Preview without saving
python manage.py import_noaa_rfc_stations --states WA OR --dry-run

# Clear existing NOAA_RFC stations first
python manage.py import_noaa_rfc_stations --states WA OR --clear
```

**Arguments:**
- `--states` - Space-separated state codes (e.g., WA OR CA ID MT)
- `--rfc` - Specific RFC code (NWRFC, CNRFC, CBRFC, etc.)
- `--include-bc` - Include British Columbia stations from NWRFC
- `--forecasts-only` - Only import gauges with active forecasts (default: True)
- `--clear` - Clear existing NOAA_RFC stations before loading
- `--dry-run` - Preview what would be imported without saving

**What it does:**
- Fetches gauge data from NOAA Water Watch API
- Filters to requested states/RFCs
- Optionally filters for gauges with active forecasts
- Creates MasterStation records with agency='NOAA_RFC'
- Records: noaa_lid, station_name, lat/lon, state, RFC code

**RFC Codes:**
- NWRFC - Northwest River Forecast Center (WA, OR, ID, MT)
- CNRFC - California-Nevada RFC (CA, NV)
- CBRFC - Colorado Basin RFC (CO, UT, WY, NM, AZ)

---

### add_huc17_stations

Add Columbia River Basin (HUC 17) stations to a configuration.

**Usage:**
```bash
# By configuration ID
python manage.py add_huc17_stations --config-id 1

# By configuration name
python manage.py add_huc17_stations --config-name "Columbia"

# Limit number of stations
python manage.py add_huc17_stations --config-name "Columbia" --limit 50

# Dry run
python manage.py add_huc17_stations --config-id 1 --dry-run
```

**Arguments:**
- `--config-id` - ID of the configuration to add stations to
- `--config-name` - Name of configuration (searches for substring)
- `--limit` - Maximum number of stations to add
- `--dry-run` - Preview without making changes

**What it does:**
- Finds MasterStation records with huc_code starting with '17'
- Creates Station records if they don't exist
- Adds stations to the specified PullConfiguration
- Creates PullConfigurationStation links

---

### sync_stations

Create Station records from MasterStation data for configured pull configurations.

**Usage:**
```bash
# Sync all configurations
python manage.py sync_stations

# Sync specific configuration
python manage.py sync_stations --config "Western US"

# Dry run
python manage.py sync_stations --dry-run
```

**Arguments:**
- `--config` - Specific configuration name to process
- `--dry-run` - Show what would be created without creating

**What it does:**
- Iterates through PullConfigurationStation records
- For each master station, creates or updates corresponding Station record
- Copies data: station_number, name, lat/lon, state, HUC, altitude, drainage area
- Essential step after loading master stations

**Workflow:**
1. `load_master_stations` - Load from USGS
2. Configure stations through Django admin or API
3. `sync_stations` - Create Station records for data pulls

---

### populate_station_mappings

Create StationMapping records linking Station to MasterStation for RFC lookups.

**Usage:**
```bash
# Populate mappings
python manage.py populate_station_mappings

# Clear and repopulate
python manage.py populate_station_mappings --clear
```

**Arguments:**
- `--clear` - Clear existing mappings before populating

**What it does:**
- Creates bidirectional mappings between Station and MasterStation
- Uses USGS station numbers for direct matching
- Uses NOAA LID for RFC station lookups
- Enables cross-agency station identification

---

### load_station_mappings

Load station mappings from CSV file.

**Usage:**
```bash
python manage.py load_station_mappings --csv-file data/sample_station_mappings.csv
```

**Arguments:**
- `--csv-file` - Path to CSV file with station mappings

**CSV Format:**
```csv
usgs_station_number,noaa_lid,notes
12345678,ABCD1,Main stem gauge
```

---

### populate_usgs_historical

Populate complete historical discharge data for USGS stations by HUC, state, or station number.

**Purpose:** One-time population of historical daily mean discharge records. Use PullConfiguration for ongoing appends.

**Usage:**
```bash
# By HUC (e.g., Columbia River Basin)
python manage.py populate_usgs_historical --huc 17

# By state
python manage.py populate_usgs_historical --state WA --state OR

# Specific stations
python manage.py populate_usgs_historical --station 14211720 --station 14105700

# Test with dry run
python manage.py populate_usgs_historical --huc 17 --limit 5 --dry-run

# Custom date range (testing)
python manage.py populate_usgs_historical \
  --station 14211720 \
  --start-date 2026-01-20 \
  --end-date 2026-01-26

# Include inactive stations
python manage.py populate_usgs_historical --huc 17 --include-inactive

# Force re-population
python manage.py populate_usgs_historical --huc 17 --force
```

**Arguments:**
- `--huc` - HUC code(s) to process (repeatable)
- `--state` - State code(s) to process (repeatable)
- `--station` - Specific station number(s) (repeatable)
- `--include-inactive` - Include inactive stations (default: active only)
- `--dry-run` - Show what would be done without fetching data
- `--limit` - Limit number of stations (for testing)
- `--force` - Re-populate even if already complete
- `--start-date` - Override start date (YYYY-MM-DD)
- `--end-date` - Override end date (YYYY-MM-DD, default: today)
- `--batch-size` - Records per bulk insert (default: 1000)
- `--delay` - Seconds between stations (default: 1.0)

**What it does:**
1. Discovers stations matching criteria (from Station or MasterStation)
2. Checks if station already has complete historical data
3. Fetches daily mean discharge from USGS using dataretrieval library
4. Bulk inserts records with duplicate protection (ignore_conflicts)
5. Updates Station.historical_data_populated_at timestamp
6. Supports graceful shutdown (Ctrl+C) and resume capability

**Progress Tracking:**
- Sets `Station.historical_data_populated_at` when complete
- Sets `Station.historical_record_count` with number of records
- Automatically skips already-populated stations (use `--force` to override)

**Performance:**
- ~1-10 seconds per station (depends on record length)
- ~2-15 minutes for 100 stations
- ~1-8 hours for full HUC 17 (~2,890 stations)

**Resume Capability:**
If interrupted, simply re-run the same command - it will skip completed stations automatically.

**Example Workflow:**
```bash
# 1. Test first with dry run
python manage.py populate_usgs_historical --huc 17 --limit 5 --dry-run

# 2. Test with real data (short date range)
python manage.py populate_usgs_historical --huc 17 --limit 10 \
  --start-date 2026-01-20 --end-date 2026-01-26

# 3. Run full historical population
python manage.py populate_usgs_historical --huc 17

# 4. Set up ongoing appends with PullConfiguration
# (Create config via Django admin or web interface)
```

**See also:**
- [USGS Historical Population Guide](../USGS_HISTORICAL_POPULATION_GUIDE.md) - Complete usage guide
- [sync_stations](#sync_stations) - Sync stations from MasterStation first
- PullConfiguration - For ongoing daily appends after historical population

---

## Gridded/Raster Data Management

### init_raster_datasets

Initialize all raster datasets, variables, spatial extents, and pull configurations.

**Usage:**
```bash
# Initialize all datasets
python manage.py init_raster_datasets

# Preview without creating
python manage.py init_raster_datasets --dry-run

# Overwrite existing
python manage.py init_raster_datasets --overwrite
```

**Arguments:**
- `--dry-run` - Show what would be created without creating
- `--overwrite` - Overwrite existing datasets

**What it does:**
Creates database records for:
1. **Spatial Extents:**
   - Western US
   - Pacific Northwest
   - California
   - Columbia River Basin

2. **Datasets & Variables:**
   - **NOAA RTMA** (Hourly, 2.5km): Temperature, Pressure, Wind Speed/Direction, Humidity, Precipitation
   - **NASA SMAP L4** (Daily, 9km): Soil Moisture 0-5cm, 0-100cm, Root Zone
   - **MODIS Terra** (Daily, 1km): Day LST, Night LST, Day QC, Night QC
   - **MODIS Aqua** (Daily, 1km): Day LST, Night LST, Day QC, Night QC
   - **NASA GPM IMERG** (30-min, 11km): Precipitation, Probability, Error

3. **Pull Configurations:**
   - Example configurations for each dataset
   - Automatic scheduling via Celery Beat

**Required before:**
- Creating custom pull configurations
- Running scheduled data pulls
- Using the gridded data interface

---

### pull_raster_data

Manually trigger a raster data pull.

**Usage:**
```bash
# List available configurations
python manage.py pull_raster_data --list

# Pull by configuration name
python manage.py pull_raster_data --config "Western US RTMA"

# Pull by configuration ID
python manage.py pull_raster_data --config-id 1

# Specify date (default: today)
python manage.py pull_raster_data --config "Western US RTMA" --date 2026-01-15
```

**Arguments:**
- `--config` - Configuration name
- `--config-id` - Configuration ID
- `--date` - Date to pull (YYYY-MM-DD, default: today)
- `--list` - List available configurations

**What it does:**
- Triggers immediate data pull for specified configuration
- Downloads data from source (NOMADS, EarthData, or GEE)
- Creates RasterLayer records
- Saves GeoTIFF files to storage
- Records pull status in RasterPullLog

**Common use cases:**
```bash
# Pull today's RTMA temperature data
python manage.py pull_raster_data --config "RTMA Temperature"

# Backfill a specific date
python manage.py pull_raster_data --config "SMAP Soil Moisture" --date 2026-01-20
```

---

### backfill_rasters

Backfill historical raster data for a date range.

**Usage:**
```bash
# Backfill date range
python manage.py backfill_rasters \
    --config "Western US RTMA" \
    --start-date 2026-01-01 \
    --end-date 2026-01-15

# By configuration ID
python manage.py backfill_rasters \
    --config-id 1 \
    --start-date 2026-01-01 \
    --end-date 2026-01-15

# Dry run to preview
python manage.py backfill_rasters \
    --config "SMAP Soil Moisture" \
    --start-date 2026-01-01 \
    --end-date 2026-01-15 \
    --dry-run
```

**Arguments:**
- `--config` - Configuration name
- `--config-id` - Configuration ID
- `--start-date` - Start date (YYYY-MM-DD, required)
- `--end-date` - End date (YYYY-MM-DD, required)
- `--dry-run` - Preview dates without pulling data

**What it does:**
- Iterates through date range
- Pulls data for each date sequentially
- Useful for filling data gaps or initializing new configurations
- Creates RasterLayer records for each successful pull

**Performance notes:**
- Pulls are sequential (not parallel)
- Large date ranges may take considerable time
- RTMA: ~2-5 minutes per day
- MODIS/SMAP: ~5-15 minutes per day
- Consider using smaller ranges and monitoring progress

---

### setup_raster_datasets

**Status:** Legacy command, superseded by `init_raster_datasets`

Creates initial raster dataset structures. Use `init_raster_datasets` instead for complete setup.

---

### setup_spatial_extents

Setup spatial extent definitions for raster data pulls.

**Usage:**
```bash
python manage.py setup_spatial_extents
```

**What it does:**
- Creates predefined spatial extent records
- Extents: Western US, Pacific Northwest, California, Columbia River Basin
- Used by raster pull configurations to define data bounds

**Note:** Usually run as part of `init_raster_datasets`

---

### create_raster_config

Interactive command to create a raster pull configuration.

**Usage:**
```bash
python manage.py create_raster_config
```

**What it does:**
- Interactive prompts for configuration details
- Guides through dataset, variables, extent, and schedule selection
- Creates RasterPullConfiguration record
- Alternative to using Django admin or API

---

## Testing & Diagnostics

### test_gee_connection

Test Google Earth Engine authentication and connection.

**Usage:**
```bash
python manage.py test_gee_connection
```

**What it does:**
- Tests GEE authentication using service account
- Verifies service account JSON file exists
- Tests basic GEE API access
- Reports connection status

**Requirements:**
- Service account JSON file configured in settings
- `earthengine-api` package installed

---

### test_earthdata_integration

Test NASA EarthData authentication and data access.

**Usage:**
```bash
python manage.py test_earthdata_integration
```

**What it does:**
- Tests EarthData authentication using .netrc credentials
- Verifies access to SMAP, MODIS, and GPM data sources
- Attempts to list and download sample data
- Reports detailed status for each dataset

**Requirements:**
- EarthData credentials in ~/.netrc
- `requests` package installed
- See [EARTHDATA_SETUP.md](../EARTHDATA_SETUP.md) for credential setup

**Tested sources:**
- SMAP Level 4 Soil Moisture
- MODIS Terra LST (MOD11A1)
- MODIS Aqua LST (MYD11A1)
- GPM IMERG Precipitation

---

### test_nomads_rtma

Test NOAA NOMADS RTMA data access.

**Usage:**
```bash
python manage.py test_nomads_rtma
```

**What it does:**
- Tests connection to NOAA NOMADS server
- Verifies RTMA data availability
- Attempts to download sample RTMA file
- Reports access status

**Requirements:**
- Internet connection to nomads.ncep.noaa.gov
- `requests` package installed

**Tested parameters:**
- Temperature
- Pressure
- Wind speed/direction
- Humidity

---

### test_modis_lst

Test MODIS land surface temperature data access and processing.

**Usage:**
```bash
python manage.py test_modis_lst
```

**What it does:**
- Tests EarthData authentication for MODIS
- Verifies access to both Terra (MOD11A1) and Aqua (MYD11A1)
- Tests HDF4 file download and processing
- Reports processing capabilities

**Requirements:**
- EarthData credentials
- `pyhdf` or GDAL with HDF4 support (optional, for processing)

**Note:** HDF4 processing may require additional system libraries. See output for details.

---

## Common Workflows

### Initial System Setup

```bash
# 1. Initialize all raster datasets
python manage.py init_raster_datasets

# 2. Load timeseries stations (choose one or more)
python manage.py load_master_stations --state WA
python manage.py load_master_stations --state OR
python manage.py import_noaa_rfc_stations --rfc NWRFC

# 3. Verify station counts
python manage.py shell -c "from apps.streamflow.models import MasterStation; print(f'Total: {MasterStation.objects.count()}')"
```

### Test Data Sources

```bash
# Test all data sources
python manage.py test_nomads_rtma
python manage.py test_earthdata_integration
python manage.py test_gee_connection  # if using GEE

# Manual test pull
python manage.py pull_raster_data --list
python manage.py pull_raster_data --config "Western US RTMA"
```

### Station Data Workflow

```bash
# 1. Load master stations from USGS
python manage.py load_master_stations --state CA --state NV

# 2. Load RFC stations
python manage.py import_noaa_rfc_stations --states CA NV

# 3. Create pull configuration (through admin or API)
# 4. Sync stations to create Station records
python manage.py sync_stations

# 5. Create station mappings for cross-agency lookups
python manage.py populate_station_mappings
```

### Backfill Historical Data

```bash
# Backfill last 30 days of RTMA data
python manage.py backfill_rasters \
    --config "Western US RTMA" \
    --start-date 2026-01-01 \
    --end-date 2026-01-30

# Preview first
python manage.py backfill_rasters \
    --config "SMAP Soil Moisture" \
    --start-date 2026-01-01 \
    --end-date 2026-01-15 \
    --dry-run
```

---

## Troubleshooting

### Command not found
```bash
# Ensure you're in the project directory
cd /path/to/streamflow-dataOps

# Activate virtual environment if using one
source venv/bin/activate

# Verify manage.py exists
ls manage.py
```

### Import errors
```bash
# Install requirements
pip install -r requirements.txt

# Check Python path
python -c "import sys; print('\n'.join(sys.path))"
```

### Database errors
```bash
# Run migrations
python manage.py migrate

# Check database connection
python manage.py dbshell
```

### Authentication errors (EarthData)
```bash
# Verify .netrc exists
cat ~/.netrc | grep earthdata

# Test authentication
python manage.py test_earthdata_integration

# See setup guide
cat Documentation/EARTHDATA_SETUP.md
```

---

## Getting Help

For command-specific help:
```bash
python manage.py <command> --help
```

For general help:
```bash
python manage.py help
```

List all available commands:
```bash
python manage.py help
```

---

**Last Updated:** January 29, 2026
