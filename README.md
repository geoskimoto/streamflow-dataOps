# StreamFlow DataOps - Django Application

**A comprehensive water resource data management system for streamflow observations and forecasts.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 4.2.7](https://img.shields.io/badge/django-4.2.7-green.svg)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 📋 Overview

StreamFlow DataOps is a Django-based platform for managing streamflow data from multiple sources including USGS, NOAA/NWS River Forecast Centers, and Canadian Hydrometric Services. The system provides automated data acquisition, storage, and access through both a web interface and REST API.

**NEW:** Now includes gridded satellite raster data from Google Earth Engine for temperature, precipitation, wind, and soil moisture!

### Key Features

- 🌊 **Multi-Source Data Integration** - USGS, NOAA RFC, Environment Canada
- 🛰️ **Satellite Raster Data** - RTMA meteorology & SMAP soil moisture via Google Earth Engine
- 📊 **Real-time & Historical Data** - Support for both observation types
- 🔮 **Forecast Management** - Store and visualize forecast runs with time-series data
- 🗺️ **309 Active Stations** - Western US focus with extensible coverage
- 📍 **Spatial Data** - PostGIS-enabled database for geographic analysis
- 🔄 **Automated Scheduling** - Celery-based background data pulls
- 📡 **REST API** - Full API with OpenAPI/Swagger documentation
- 🎨 **Web Dashboard** - Bootstrap 5 interface with interactive visualizations
- 📈 **Plotly Integration** - Interactive forecast charts

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 16+ with PostGIS extension
- Redis (for Celery background tasks)
- Google Earth Engine account (for raster data)
- GDAL development libraries (for raster processing)

### Installation

```bash
# Clone repository
git clone <repository-url>
cd streamflow-dataOps

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install system dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install postgresql-16 postgresql-16-postgis-3 gdal-bin libgdal-dev

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env with your database credentials and GEE settings

# Setup PostgreSQL with PostGIS
sudo -u postgres createdb streamflow_db
sudo -u postgres psql streamflow_db -c "CREATE EXTENSION postgis;"
sudo -u postgres psql streamflow_db -c "CREATE EXTENSION postgis_topology;"

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Collect static files
python manage.py collectstatic --noinput

# Setup raster data (optional, for satellite data features)
python manage.py setup_raster_datasets
python manage.py setup_spatial_extents
python manage.py test_gee_connection

# Populate station mappings (enables RFC filter)
python manage.py populate_station_mappings

# Optional: Import BC stations from Environment Canada
python manage.py import_bc_stations

# Start development server
python manage.py runserver
```

Visit http://localhost:8000 to access the dashboard!

---

## 📚 Documentation

Full documentation is available in the [Documentation/](Documentation/) directory:

- **[INDEX.md](Documentation/INDEX.md)** - Documentation index and quick reference
- **[STATUS.md](Documentation/STATUS.md)** - Current project status
- **[API_TEST_RESULTS.md](Documentation/API_TEST_RESULTS.md)** - API testing results
- **[DEPLOYMENT.md](Documentation/DEPLOYMENT.md)** - Production deployment guide
- **[DJANGO_QUICKSTART.md](Documentation/DJANGO_QUICKSTART.md)** - Development guide

### API Documentation

- **Swagger UI:** http://localhost:8000/api/v1/docs/
- **ReDoc:** http://localhost:8000/api/v1/redoc/
- **OpenAPI Schema:** http://localhost:8000/api/v1/schema/

---

## 🏗️ Architecture

### Tech Stack

- **Backend:** Django 4.2.7, Django REST Framework
- **Database:** PostgreSQL 16+ with PostGIS 3.4+
- **Spatial:** GeoDjango, PostGIS for spatial queries
- **Raster Processing:** GDAL 3.8+, rasterio 1.5+
- **Google Earth Engine:** earthengine-api 1.7+
- **Task Queue:** Celery with Redis broker
- **API Docs:** DRF Spectacular (OpenAPI 3.0)
- **Frontend:** Bootstrap 5, Plotly.js, Vanilla JavaScript
- **Data Sources:** USGS NWIS, NOAA/NWS RFC, Environment Canada, Google Earth Engine

### Project Structure

```
streamflow-dataOps/
├── apps/
│   ├── api/                    # REST API endpoints
│   ├── streamflow/             # Core streamflow models and views
│   └── monitoring/             # System monitoring
├── src/
│   ├── acquisition/            # Data acquisition clients
│   │   ├── gee_client.py      # Google Earth Engine client
│   │   ├── raster_processor.py # Raster processing utilities
│   │   └── raster_tasks.py    # Celery tasks for raster pulls
│   └── utils/                  # Shared utilities
├── config/                     # Django settings
├── tests/                      # Test suite
├── Journal/                    # Development journal
├── Documentation/              # All documentation
├── data/
│   └── rasters/                # Raster data storage
│       ├── RTMA/               # NOAA RTMA meteorology
│       └── SMAP_SPL4/          # NASA SMAP soil moisture
└── static/                     # Static assets
```

---

## 🛰️ Raster/Satellite Data

StreamFlow DataOps integrates gridded satellite data from Google Earth Engine for comprehensive spatial analysis. The system supports automated pulls, processing, and API access to meteorological and soil moisture rasters.

### Supported Datasets

#### RTMA (Real-Time Mesoscale Analysis)
- **Source:** NOAA/NWS
- **Collection:** `NOAA/NWS/RTMA`
- **Resolution:** 2.5 km (2,500m)
- **Frequency:** Hourly
- **Variables:**
  - Temperature (2m air temp, Kelvin)
  - Precipitation (accumulated, kg/m²)
  - Wind Speed (10m wind, m/s)

#### SMAP SPL4 (Soil Moisture Active Passive Level 4)
- **Source:** NASA
- **Collection:** `NASA/SMAP/SPL4SMGP/008`
- **Resolution:** 9 km (9,000m)
- **Frequency:** Daily (3-hour snapshots)
- **Variables:**
  - Surface Soil Moisture (0-5cm, m³/m³)
  - Root Zone Soil Moisture (0-100cm, m³/m³)

### Spatial Coverage

- **Primary:** HUC 17 (Columbia River Basin): [-124.7, 41.5, -108.0, 49.0]
- **Extended:** Western US (CA, OR, WA, ID, MT, WY, CO, UT, NV, AZ, NM): [-125.0, 31.0, -102.0, 49.0]

### Google Earth Engine Setup

1. **Create GEE Account:** https://earthengine.google.com/
2. **Authenticate locally:**
   ```bash
   earthengine authenticate
   ```
3. **Or configure service account (production):**
   ```env
   # .env file
   GEE_SERVICE_ACCOUNT_KEY=./rtmaandsma-fe989e72b62e.json
   GEE_PROJECT_ID=rtmaandsmap
   GEE_SERVICE_ACCOUNT_EMAIL= gee-access@rtmaandsma.iam.gserviceaccount.com
   ```

```
1. Enable the Earth Engine API
Before creating a service account, Google Cloud needs to know your project is allowed to use Earth Engine.

Go to the Google Cloud Console.

Ensure RTMAandSMAP is selected in the top project dropdown.

Search for "Earth Engine API" in the top search bar and click Enable.

2. Create the Service Account
This will provide you with your GEE_SERVICE_ACCOUNT_EMAIL.

Navigate to IAM & Admin > Service Accounts.

Click + Create Service Account.

Give it a name (e.g., gee-access-link). The console will automatically generate an email address like gee-access-link@rtmaandsmap.iam.gserviceaccount.com. Copy this email.

Click Create and Continue.

Grant Access: Under "Role," search for and select Earth Engine Resource Viewer (or Earth Engine Admin if you need to write/delete assets).

Click Done.

3. Generate the JSON Key
This provides the GEE_SERVICE_ACCOUNT_KEY file.

In the Service Accounts list, click on the email address you just created.

Go to the Keys tab.

Click Add Key > Create new key.

Select JSON and click Create.

A .json file will download to your computer. Move this to your project folder (but don't commit it to GitHub!). The full path to this file is your GEE_SERVICE_ACCOUNT_KEY.

4. Register the Service Account with GEE
This is the step most people miss. Even with a key, Earth Engine won't let the account in unless it's registered on their specific allowlist.

Go to the Earth Engine Register Page.

Follow the prompts to register a "Non-commercial" or "Commercial" project.

When asked, ensure you register the Service Account Email you created in Step 2.
```

### Raster Management Commands

```bash
# Setup datasets and spatial extents
python manage.py setup_raster_datasets    # Initialize RTMA & SMAP metadata
python manage.py setup_spatial_extents    # Create HUC17 & Western US extents

# Test GEE connection
python manage.py test_gee_connection --dataset RTMA --days-back 7

# Create pull configuration
python manage.py create_raster_config \
  --name "HUC17 Daily RTMA" \
  --dataset RTMA \
  --variables temperature precipitation wind_speed \
  --extents HUC_17 \
  --frequency 8 \
  --enabled

# Manual data pull
python manage.py pull_raster_data --config "HUC17 Daily RTMA"
python manage.py pull_raster_data --config-id 1 --async  # Asynchronous via Celery

# Backfill historical data
python manage.py backfill_rasters \
  --config "HUC17 Daily RTMA" \
  --start-date 2025-01-01 \
  --end-date 2025-12-31 \
  --async

# List configurations
python manage.py pull_raster_data --list
```

### Raster Database Models

- **RasterDataset** - GEE dataset metadata (RTMA, SMAP)
- **RasterVariable** - Variable definitions (temperature, soil moisture, etc.)
- **SpatialExtent** - Geographic boundaries with PostGIS geometry
- **RasterLayer** - Individual raster file metadata with statistics
- **RasterPullConfiguration** - Automated pull settings (schedule, variables, extents)
- **RasterPullLog** - Execution history and monitoring

### Automated Pulls

Raster data pulls are scheduled via Celery Beat:
- **Every 8 hours:** Active configurations run automatically
- **Weekly cleanup:** Old rasters removed (configurable retention)

```bash
# Start Celery workers
celery -A config worker -l info

# Start Celery beat scheduler
celery -A config beat -l info
```

### Storage

Rasters are stored as compressed GeoTIFF files with organized directory structure:

```
data/rasters/
  RTMA/
    temperature/
      HUC_17/
        2026/
          01/
            RTMA_temperature_HUC17_20260127_12Z.tif
    precipitation/
      ...
  SMAP_SPL4/
    soil_moisture_surface/
      ...
```

- **Format:** GeoTIFF with LZW compression
- **Metadata:** PostgreSQL database with PostGIS
- **Thumbnails:** PNG previews for quick visualization
- **Compression:** ~65-70% file size reduction

---

## 🔌 REST API Endpoints

### Raster Data Endpoints (NEW!)

#### Datasets & Variables
- `GET /api/v1/raster-datasets/` - List available datasets (RTMA, SMAP)
- `GET /api/v1/raster-datasets/{id}/variables/` - Variables for dataset
- `GET /api/v1/raster-datasets/{id}/coverage/` - Temporal coverage
- `GET /api/v1/raster-variables/` - List all variables
- `GET /api/v1/raster-variables/?dataset=RTMA` - Filter by dataset

#### Spatial Extents
- `GET /api/v1/spatial-extents/` - List available extents (HUC_17, Western_US)

#### Raster Layers
- `GET /api/v1/raster-layers/` - List raster layers (with filtering)
- `GET /api/v1/raster-layers/?variable=temperature&start_date=2026-01-01&end_date=2026-01-31`
- `GET /api/v1/raster-layers/{id}/` - Layer details
- `GET /api/v1/raster-layers/{id}/download/` - Download GeoTIFF file
- `GET /api/v1/raster-layers/{id}/thumbnail/` - Get PNG thumbnail
- `POST /api/v1/raster-layers/extract_points/` - Extract values at coordinates
- `GET /api/v1/raster-layers/coverage/` - Temporal coverage summary
- `GET /api/v1/raster-layers/statistics/` - Aggregated statistics

#### Pull Configurations & Logs
- `GET /api/v1/raster-configurations/` - List pull configurations
- `GET /api/v1/raster-configurations/{id}/logs/` - Execution logs
- `GET /api/v1/raster-logs/` - All pull logs

**Example: Extract Temperature at Points**
```bash
curl -X POST http://localhost:8000/api/v1/raster-layers/extract_points/ \
  -H "Content-Type: application/json" \
  -d '{
    "layer_id": 1,
    "coordinates": [
      [-122.5, 45.5],
      [-118.0, 46.0]
    ]
  }'
```

### Streamflow Endpoints

#### Stations
- `GET /api/v1/stations/` - List all stations (309 records)
- `GET /api/v1/stations/{station_number}/` - Station details

### Observations
- `GET /api/v1/observations/discharge/` - List observations (683 records)
- `GET /api/v1/observations/discharge/statistics/` - Aggregate statistics

### Forecasts
- `GET /api/v1/forecasts/` - List forecast runs (450 records)
- `GET /api/v1/forecasts/{id}/` - Forecast with full data array
- `GET /api/v1/forecasts/statistics/` - Forecast statistics
- `GET /api/v1/forecasts/by-station/{station_number}/` - Station forecasts
- `GET /api/v1/forecasts/latest/` - Most recent forecast

### Configurations & Logs
- `GET /api/v1/configurations/` - Data pull configurations
- `GET /api/v1/logs/` - Execution logs

All endpoints support filtering, pagination, and ordering. See API documentation for details.

---

## 🧪 Testing

```bash
# Run all tests
python manage.py test

# Run API tests
python manage.py test apps.api.test_api_complete

# Run live API tests (requires running server)
python test_api_live.py

# Run specific test
python manage.py test apps.streamflow.tests.test_models
```

**Test Coverage:** 36/36 tests passing ✅

---

## 🛠️ Management Commands

### Data Setup & Maintenance

```bash
# Populate StationMapping table (required for RFC filter)
python manage.py populate_station_mappings

# Import Environment Canada stations (British Columbia)
python manage.py import_bc_stations

# Import only active real-time BC stations
python manage.py import_bc_stations --active-only (11,000+ stations)
- **NOAA:** `NOAAClient` - River forecast center forecasts (1,000+ stations)
- **Canada:** `CanadaClient` - Environment Canada hydrometric data (2,300+ BC stations)
  - Uses MSC GeoMet API
  - Metric units (cms) with automatic CFS conversion
  - Real-time (15-min) and daily mean data
python manage.py populate_station_mappings --clear
```

### Station Data Management

```bash
# Sync master stations to working stations
python manage.py sync_stations

# Import stations from CSV
python manage.py import_stations data/stations.csv

# Export stations to CSV
python manage.py export_stations output.csv
```

---

## 🗄️ Database Models

### Streamflow Models

- **Station** - Monitoring station metadata (309 records)
- **DischargeObservation** - Time-series discharge data (683 records)
- **ForecastRun** - Forecast data with JSON arrays (450 records)
- **PullConfiguration** - Data acquisition settings (4 configurations)
- **DataPullLog** - Execution history and monitoring
- **MasterStation** - 14,319 reference stations from all sources
- **StationMapping** - Links working Stations to MasterStations (309 mappings)

### Raster Data Models (NEW!)

- **RasterDataset** - GEE dataset metadata (RTMA, SMAP)
- **RasterVariable** - Variable definitions (temperature, soil moisture, etc.)
- **SpatialExtent** - Geographic boundaries with PostGIS geometry
- **RasterLayer** - Individual raster file metadata with statistics
- **RasterPullConfiguration** - Automated pull settings
- **RasterPullLog** - Pull execution history

### Data Sources

- **USGS:** `USGSClient` - Real-time and daily mean discharge (11,000+ stations)
- **NOAA:** `NOAAClient` - River forecast center forecasts (1,000+ stations)
- **Canada:** `CanadaClient` - Environment Canada hydrometric data (2,300+ BC stations)
  - Uses MSC GeoMet API
  - Metric units (cms) with automatic CFS conversion
  - Real-time (15-min) and daily mean data
- **Google Earth Engine:** `GEEClient` - Satellite raster data (RTMA, SMAP)
  - NOAA RTMA meteorological analysis
  - NASA SMAP soil moisture

---

## ⚙️ Configuration

Key environment variables in `.env`:

```env
# Database (PostgreSQL required for raster data)
DATABASE_URL=postgresql://user:pass@localhost:5432/streamflow_db

# Django
SECRET_KEY=your-secret-key-here
DEBUG=True

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0

# Google Earth Engine (for raster data)
GEE_SERVICE_ACCOUNT_KEY=/path/to/service-account-key.json
GEE_PROJECT_ID=your-gee-project-id
GEE_SERVICE_ACCOUNT_EMAIL=your-account@project.iam.gserviceaccount.com

# Data Sources (streamflow)
USGS_API_BASE_URL=https://waterservices.usgs.gov/nwis/iv/
NOAA_API_BASE_URL=https://api.weather.gov/

# Raster Storage
RASTER_ROOT=/absolute/path/to/data/rasters
RASTER_DEFAULT_COMPRESSION=LZW
RASTER_MAX_FILE_SIZE_MB=500
```

---

## 📈 Current Status

### Master Stations:** 14,319 reference stations (USGS: 11,000 | EC: 2,324 | NOAA: 996)
- **Station Mappings:** 309 Station-to-MasterStation links (RFC filter enabled)
- **Production Data (as of January 26, 2026)

- **Stations:** 309 active monitoring locations
- **Observations:** 683 discharge records
- **Forecasts:** 450 forecast runs with complete data
- **Pull Configurations:** 4 active automated pulls
- **API Status:**  (January 2026)

- ✅ Environment Canada integration (MSC GeoMet API)
- ✅ StationMapping system for RFC filter
- ✅ "Configured stations only" filter toggle
- ✅ 2,324 BC stations available for sync
### Recent Updates

- ✅ Complete REST API with forecast endpoints
- ✅ Interactive forecast visualization
- ✅ Comprehensive test suite (36 tests)
- ✅ API documentation (Swagger/ReDoc)
- ✅ Production-ready deployment

See [Documentation/STATUS.md](Documentation/STATUS.md) for detailed status.

---

## 🚀 Deployment

### Production Deployment

See [Documentation/DEPLOYMENT.md](Documentation/DEPLOYMENT.md) for complete deployment instructions.

Quick deployment checklist:
- ✅ PostgreSQL database configured
- ✅ Redis server running
- ✅ Environment variables set
- ✅ Static files collected
- ✅ Migrations applied
- ✅ Celery workers started
- ✅ Gunicorn/uWSGI configured
- ✅ Nginx reverse proxy setup

---

## 🤝 Contributing

1. Check [Journal/PROGRESS_TRACKER.md](Journal/PROGRESS_TRACKER.md) for current work
2. Review [Documentation/STATUS.md](Documentation/STATUS.md)
3. Create feature branch from `main`
4. Write tests for new features
5. Update documentation
6. Submit pull request

### Development Workflow

```bash
# Create feature branch
git checkout -b feature/your-feature

# Make changes and test
python manage.py test

# Update documentation
# Update Journal/ if significant changes

# Commit and push
git add .
git commit -m "Description of changes"
git push origin feature/your-feature
```

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🔗 Links

- **API Documentation:** http://localhost:8000/api/v1/docs/
- **Admin Interface:** http://localhost:8000/admin/
- **Project Journal:** [Journal/README.md](Journal/README.md)
- **Documentation Index:** [Documentation/INDEX.md](Documentation/INDEX.md)

---

## 📧 Support

For questions, issues, or contributions, please:
1. Check existing documentation
2. Review [Journal/](Journal/) for development context
3. Open an issue with detailed description

---

**Built with Django & Django REST Framework** | **Water Resource Data Management** | **Multi-Source Integration**
