# StreamFlow DataOps - Django Application

**A comprehensive water resource data management system for streamflow observations and forecasts.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 4.2.7](https://img.shields.io/badge/django-4.2.7-green.svg)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 📋 Overview

StreamFlow DataOps is a Django-based platform for managing streamflow data from multiple sources including USGS, NOAA/NWS River Forecast Centers, and Canadian Hydrometric Services. The system provides automated data acquisition, storage, and access through both a web interface and REST API.

### Key Features

- 🌊 **Multi-Source Data Integration** - USGS, NOAA RFC, Environment Canada
- 📊 **Real-time & Historical Data** - Support for both observation types
- 🔮 **Forecast Management** - Store and visualize forecast runs with time-series data
- 🗺️ **309 Active Stations** - Western US focus with extensible coverage
- 🔄 **Automated Scheduling** - Celery-based background data pulls
- 📡 **REST API** - Full API with OpenAPI/Swagger documentation
- 🎨 **Web Dashboard** - Bootstrap 5 interface with interactive visualizations
- 📈 **Plotly Integration** - Interactive forecast charts

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 12+ (or SQLite for development)
- Redis (for Celery background tasks)

### Installation

```bash
# Clone repository
git clone <repository-url>
cd streamflow-dataOps

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env with your database credentials

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Sync stations from configurations
python manage.py sync_stations

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
- **Database:** PostgreSQL (production), SQLite (development)
- **Task Queue:** Celery with Redis broker
- **API Docs:** DRF Spectacular (OpenAPI 3.0)
- **Frontend:** Bootstrap 5, Plotly.js, Vanilla JavaScript
- **Data Sources:** USGS NWIS, NOAA/NWS RFC, Environment Canada

### Project Structure

```
streamflow-dataOps/
├── apps/
│   ├── api/                    # REST API endpoints
│   ├── streamflow/             # Core streamflow models and views
│   └── monitoring/             # System monitoring
├── src/
│   ├── acquisition/            # Data acquisition clients
│   └── utils/                  # Shared utilities
├── config/                     # Django settings
├── tests/                      # Test suite
├── Journal/                    # Development journal
├── Documentation/              # All documentation
└── static/                     # Static assets
```

---

## 🔌 REST API Endpoints

### Stations
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

## 🗄️ Database Models

### Core Models

- **Station** - Monitoring station metadata (309 records)
- **DischargeObservation** - Time-series discharge data (683 records)
- **ForecastRun** - Forecast data with JSON arrays (450 records)
- **PullConfiguration** - Data acquisition settings (4 configurations)
- **DataPullLog** - Execution history and monitoring

### Data Sources

- **USGS:** `USGSClient` - Real-time and daily mean discharge
- **NOAA:** `NOAAClient` - River forecast center data
- **Canada:** `CanadaClient` - Hydrometric observations

---

## ⚙️ Configuration

Key environment variables in `.env`:

```env
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/streamflow_db

# Django
SECRET_KEY=your-secret-key-here
DEBUG=True

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0

# Data Sources
USGS_API_BASE_URL=https://waterservices.usgs.gov/nwis/iv/
NOAA_API_BASE_URL=https://api.weather.gov/
```

---

## 📈 Current Status

### Production Data (as of January 26, 2026)

- **Stations:** 309 active monitoring locations
- **Observations:** 683 discharge records
- **Forecasts:** 450 forecast runs with complete data
- **Pull Configurations:** 4 active automated pulls
- **API Status:** ✅ All endpoints tested and validated

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
