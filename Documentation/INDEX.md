# StreamFlow DataOps Documentation

**Last Updated:** January 29, 2026

This directory contains all project documentation, organized for easy reference.

---

## 🚀 Quick Start

- **[QUICKSTART.md](../QUICKSTART.md)** - Fast setup guide for both timeseries and raster systems
- **[README.md](../README.md)** - Project overview and introduction

---

## 📖 Core Documentation

### Setup & Configuration
- **[EARTHDATA_SETUP.md](EARTHDATA_SETUP.md)** - NASA EarthData authentication setup
- **[PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md)** - Service management, monitoring, troubleshooting
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Production deployment instructions
- **[DJANGO_QUICKSTART.md](DJANGO_QUICKSTART.md)** - Django development guide

### Reference Guides
- **[Reference/MANAGEMENT_COMMANDS.md](Reference/MANAGEMENT_COMMANDS.md)** - Complete guide to all `manage.py` commands
- **[DASHBOARD_INTEGRATION_GUIDE.md](DASHBOARD_INTEGRATION_GUIDE.md)** - Dashboard features and usage
- **[DJANGO_MIGRATION.md](DJANGO_MIGRATION.md)** - SQLAlchemy to Django migration guide

### Project Status
- **[STATUS.md](STATUS.md)** - Current project status and progress
- **[API_TEST_RESULTS.md](API_TEST_RESULTS.md)** - API testing results
- **[DATA_PULL_FIX_SUMMARY.md](DATA_PULL_FIX_SUMMARY.md)** - Data pull system fixes

---

## 🌐 Frontend Documentation

- **[Frontend/GRIDDED_DATA_FRONTEND.md](Frontend/GRIDDED_DATA_FRONTEND.md)** - Gridded/raster data UI guide
- **[Frontend/TESTING_GRIDDED_FRONTEND.md](Frontend/TESTING_GRIDDED_FRONTEND.md)** - Frontend testing procedures
- **[FRONTEND_SESSION_SUMMARY.md](FRONTEND_SESSION_SUMMARY.md)** - Frontend development session notes
- **[FRONTEND_TEST_RESULTS.md](FRONTEND_TEST_RESULTS.md)** - Frontend test results

---

## 🔄 Migration & Planning

- **[Migration-Plans/MIGRATION_PLAN_EARTHDATA_NOMADS.md](Migration-Plans/MIGRATION_PLAN_EARTHDATA_NOMADS.md)** - EarthData/NOMADS migration strategy

---

## 📓 Development Journal

The **[Journal/](../Journal/)** directory contains detailed development logs:

- **[PROGRESS_TRACKER.md](../Journal/PROGRESS_TRACKER.md)** - Overall progress tracking
- **[DECISION_LOG.md](../Journal/DECISION_LOG.md)** - Architectural and technical decisions
- **[IMPLEMENTATION_PLAN.md](../Journal/IMPLEMENTATION_PLAN.md)** - Feature implementation plans
- **[TESTING_LOG.md](../Journal/TESTING_LOG.md)** - Testing history and results
- **Session logs** - Detailed work session documentation

---

## 🗄️ Archived Documentation

The **[Archive/](Archive/)** directory contains outdated documentation:

### Component Design (Legacy)
- `component_1_database_design.md` - Original database design
- `component_2_data_acquisition.md` - Initial data acquisition design
- `component_3_django_interface.md` - Early Django interface planning
- `component_4_rest_api.md` - Initial REST API design
- `README_COMPONENT2.md` - Component 2 specific documentation

### Legacy Phases
- `PHASE_2_STATUS.md` - Phase 2 development status
- `PHASE_2_COMPLETE.md` - Phase 2 completion notes

These files are kept for historical reference but are no longer maintained.

---

## 🏗️ System Architecture

### Applications
- **apps/api/** - REST API endpoints, serializers, views
- **apps/streamflow/** - Core data models, management commands, web interface
- **apps/monitoring/** - System health monitoring
- **src/acquisition/** - Data acquisition clients (USGS, NOAA, Canada, NASA)
- **src/celery_app/** - Celery configuration and tasks

### API Documentation (Live)
- **Swagger UI:** http://localhost:8000/api/v1/docs/
- **ReDoc:** http://localhost:8000/api/v1/redoc/
- **OpenAPI Schema:** http://localhost:8000/api/v1/schema/

---

## 📊 System Components

### Timeseries Data
- **Data Sources:** USGS, NOAA RFC, Environment Canada
- **Management Commands:** load_master_stations, import_noaa_rfc_stations, sync_stations
- **Web Interface:** http://localhost:8000/timeseries-configurations/
- **API:** `/api/v1/stations/`, `/api/v1/observations/`, `/api/v1/forecasts/`

### Gridded/Raster Data
- **Data Sources:** NOAA RTMA, NASA SMAP, MODIS Terra/Aqua, GPM IMERG
- **Management Commands:** init_raster_datasets, pull_raster_data, backfill_rasters
- **Web Interface:** http://localhost:8000/gridded-configurations/
- **API:** `/api/v1/raster/datasets/`, `/api/v1/raster/configurations/`, `/api/v1/raster/layers/`

---

## 🔧 Quick Commands

### Development
```bash
# Start development server
python manage.py runserver

# Run tests
python manage.py test

# Run API tests
python test_api_live.py

# Create migration
python manage.py makemigrations

# Apply migrations
python manage.py migrate
```

### Data Operations
```bash
# Sync stations from configurations
python manage.py sync_stations

# Trigger data pull
python manage.py trigger_pull <config_id>

# Load sample stations
bash scripts/load_western_us_stations.sh
```

### API Testing
```bash
# Run comprehensive API tests
python manage.py test apps.api.test_api_complete

# Test specific endpoint
curl http://localhost:8000/api/v1/stations/
```

---

## 🤝 Contributing

1. Check [Journal/PROGRESS_TRACKER.md](../Journal/PROGRESS_TRACKER.md) for current work
2. Review [STATUS.md](STATUS.md) for project status
3. Update relevant documentation when making changes
4. Add session notes to Journal/ directory

---

## 📝 Documentation Standards

### When to Update Documentation
- ✅ After implementing major features
- ✅ When API endpoints change
- ✅ After significant bug fixes
- ✅ When deployment procedures change

### File Naming Conventions
- Use UPPERCASE for main docs (README.md, STATUS.md)
- Use descriptive names with underscores
- Keep file names concise but clear

### Archiving Process
Old documentation is moved to `Archive/` when:
- Feature has been replaced/rewritten
- Design docs are superseded by implementation
- Information is historical but not current

---

**Need Help?** Check the [Journal/README.md](../Journal/README.md) for development session notes and context.
