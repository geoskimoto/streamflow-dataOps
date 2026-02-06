# StreamFlow DataOps Documentation

Welcome to the StreamFlow DataOps documentation. This system provides comprehensive water resource data management for streamflow observations, forecasts, and gridded satellite raster data.

## 📚 Documentation Structure

### Getting Started
- **[Quick Start Guide](DEPLOYMENT.md)** - Deploy the application from scratch
- **[QUICK_START_EC.md](QUICK_START_EC.md)** - Environment Canada integration guide
- **[EARTHDATA_SETUP.md](EARTHDATA_SETUP.md)** - NASA Earthdata authentication setup

### Core Documentation
- **[INDEX.md](INDEX.md)** - Complete documentation index
- **[PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md)** - System monitoring and maintenance
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Full deployment guide with deploy.py script

### Reference
- **[Reference/](Reference/)** - API specifications and data models
- **[Implementation-Plans/](Implementation-Plans/)** - Historical implementation plans
- **[Migration-Plans/](Migration-Plans/)** - Database migration strategies

### Frontend
- **[Frontend/](Frontend/)** - UI component documentation and guides

### Issues & Tracking
- **[0. Issues](0.%20Issues)** - Current issues and known bugs

### Archived Documentation
- **[Archive/](Archive/)** - Historical documentation and session notes

---

## 🚀 Quick Start

For a complete deployment from scratch, see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

### Prerequisites
- Python 3.11+
- PostgreSQL 16+ with PostGIS
- Redis
- GDAL libraries
- Google Earth Engine account (optional, for raster data)

### Basic Setup
```bash
# Clone and setup environment
git clone <repository-url>
cd streamflow-dataOps
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Deploy with automated script
python scripts/deploy.py

# Create admin user
python manage.py createsuperuser

# Start services
python manage.py runserver
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete deployment instructions.

---

## 🏗️ System Architecture

### Core Components

**Web Application**
- Django 4.2+ web framework
- Bootstrap 5 responsive UI
- Interactive Plotly visualizations
- PostgreSQL with PostGIS for spatial data

**REST API**
- OpenAPI/Swagger documentation
- 24+ endpoints for data access
- DRF (Django REST Framework)
- Available at `/api/v1/`

**Data Acquisition**
- Multi-source integration (USGS, NOAA RFC, Environment Canada)
- Celery-based task scheduling
- Google Earth Engine for satellite raster data
- Configurable pull schedules

**Database Models**
- **Station** - Monitoring station metadata
- **DischargeObservation** - Time-series streamflow data
- **ForecastRun** - Forecast data with time-series
- **PullConfiguration** - Data collection automation
- **RasterDataset** - Gridded satellite data (RTMA, SMAP)

### Data Flow
```
External Sources → Celery Tasks → Database → API/Web Interface
     ↓                  ↓              ↓            ↓
  USGS/NOAA        Scheduled       PostGIS    REST API
  Env Canada        Tasks        TimeSeries   Dashboard
  GEE/Earthdata   Background      Spatial     Visualizations
```

---

## 📊 System Capabilities

### Supported Data Types

**Streamflow Observations**
- Real-time 15-minute data
- Daily mean discharge
- Historical records dating back decades
- Quality codes (Provisional/Approved)

**Forecasts**
- Short-range (18-hour) forecasts
- Medium-range (10-day) forecasts
- Historical forecast runs for ML training
- Multi-point time-series data

**Raster/Gridded Data**
- RTMA: Temperature, precipitation, wind speed
- SMAP: Soil moisture (0-5cm, 5-100cm)
- NASA Earthdata integration
- Configurable spatial extents

### Data Sources

**USGS (United States Geological Survey)**
- ~6,500+ active stations
- Real-time and historical data
- HUC-based station organization

**NOAA/NWS River Forecast Centers**
- Northwest RFC (NWRFC)
- Short and medium-range forecasts
- Daily updates at 8:30 AM PST

**Environment Canada**
- British Columbia hydrometric stations
- ~2,500+ stations
- Standardized data format

**Google Earth Engine**
- RTMA meteorological grids
- SMAP soil moisture data
- 4km and 9km resolutions

---

## 🔌 API Access

### REST API Endpoints

Base URL: `http://localhost:8000/api/v1/`

**Stations**
- `GET /api/v1/stations/` - List all stations
- `GET /api/v1/stations/{station_number}/` - Station details

**Observations**
- `GET /api/v1/observations/discharge/` - Query discharge data
- `GET /api/v1/observations/discharge/statistics/` - Aggregate statistics

**Forecasts**
- `GET /api/v1/forecasts/` - List forecast runs
- `GET /api/v1/forecasts/latest/` - Latest forecasts
- `GET /api/v1/forecasts/by-station/{station_number}/` - Station forecasts

**Raster Data**
- `GET /api/v1/raster-datasets/` - Available datasets
- `GET /api/v1/raster-layers/` - Query gridded data
- `GET /api/v1/spatial-extents/` - Defined geographic areas

**Documentation**
- `GET /api/v1/docs/` - Interactive Swagger UI
- `GET /api/v1/redoc/` - ReDoc documentation
- `GET /api/v1/schema/` - OpenAPI schema

### Python Client Library

A Python client is available in `dataops_client/`:

```python
from dataops_client import StreamFlowClient

client = StreamFlowClient("http://localhost:8000")

# Get station data
stations = client.get_stations(state="WA")

# Get observations
observations = client.get_discharge_observations(
    station_number="12345678",
    start_date="2024-01-01",
    end_date="2024-01-31"
)

# Get forecasts
forecasts = client.get_forecasts(station_number="PTRO3")
```

---

## 🧪 Testing

The project includes comprehensive test coverage:

```bash
# Run all tests
python manage.py test

# Run specific test modules
python manage.py test apps.streamflow.tests
python manage.py test tests.test_api_observations
python manage.py test tests.test_api_forecasts

# Run with coverage
pytest --cov=apps --cov=src tests/
```

Test suites available:
- Model tests (stations, observations, forecasts)
- View tests (CRUD operations, dashboard)
- API tests (endpoints, filtering, error handling)
- Form tests (validation, data import)
- Integration tests (data pipeline)

---

## 📈 Monitoring & Maintenance

### System Health

Monitor system health via:
- Django admin interface: `/admin/`
- Dashboard: `/streamflow/` (requires login)
- Celery Flower (if installed): `celery -A config flower`
- Log files: `logs/` directory

### Regular Maintenance

**Daily**
- Monitor Celery task success rates
- Check for failed data pulls
- Review error logs

**Weekly**
- Database performance review
- Storage usage monitoring
- Update station lists if needed

**Monthly**
- Review and archive old data
- Update dependencies
- Security patches

See [PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md) for detailed monitoring guides.

---

## 🛠️ Management Commands

### Station Management
```bash
# Load master station list
python manage.py load_master_stations

# Sync active stations
python manage.py sync_stations

# Populate RFC mappings
python manage.py populate_station_mappings

# Import BC stations from Environment Canada
python manage.py import_bc_stations
```

### Data Collection
```bash
# Test data pulls
python manage.py test_usgs_pull --station 12345678
python manage.py test_noaa_pull --station PTRO3
python manage.py test_canada_pull --station 08AB001

# Manual data pulls
python manage.py pull_usgs_data --config-id 1
python manage.py pull_noaa_data --config-id 2
```

### Raster Data
```bash
# Setup raster datasets
python manage.py setup_raster_datasets

# Setup spatial extents
python manage.py setup_spatial_extents

# Test GEE connection
python manage.py test_gee_connection

# Pull raster data
python manage.py pull_raster_data --dataset rtma_temp
```

### Utilities
```bash
# Create superuser
python manage.py createsuperuser

# Database shell
python manage.py dbshell

# Django shell with models
python manage.py shell_plus
```

---

## 🐛 Troubleshooting

### Common Issues

**Database Connection Errors**
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Test connection
psql -h localhost -U postgres streamflow_db

# Verify PostGIS extension
psql streamflow_db -c "SELECT PostGIS_Version();"
```

**Celery Not Running**
```bash
# Check Redis connection
redis-cli ping

# Start Celery worker
celery -A config worker -l info

# Start Celery beat scheduler
celery -A config beat -l info
```

**GDAL Import Errors**
```bash
# Install GDAL system libraries
sudo apt-get install gdal-bin libgdal-dev

# Reinstall Python GDAL
pip uninstall gdal
pip install gdal==$(gdal-config --version)
```

**Google Earth Engine Authentication**
```bash
# Authenticate with service account
python manage.py test_gee_connection

# Check credentials file exists
ls rtmaandsma-*.json
```

See **[0. Issues](0.%20Issues)** for current known issues.

---

## 📄 License

This project is licensed under the MIT License. See [LICENSE](../LICENSE) for details.

---

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

---

## 📞 Support

For issues, questions, or contributions:
- Create an issue in the repository
- Check existing documentation
- Review [0. Issues](0.%20Issues) for known problems

---

## 📝 Changelog

See implementation plans in [Implementation-Plans/](Implementation-Plans/) for historical development notes.

Current version: 1.0.0 (Production Ready)
Last updated: February 2026

- **Component 4**: REST API (FastAPI endpoints)

## Notes

- Always use the repository pattern instead of direct ORM access
- The `get_db()` function in connection.py provides dependency injection for FastAPI
- Alembic migrations should be created for all schema changes
- The Smart Append Logic prevents duplicate data pulls and reduces API calls
- Station mappings enable cross-referencing data from multiple agencies

## License

[Add your license here]
