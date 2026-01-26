# StreamFlow DataOps Documentation

**Last Updated:** January 26, 2026

This directory contains all project documentation. Files are organized for easy reference.

---

## 📚 Current Documentation

### Getting Started
- **[README.md](README.md)** - Project overview, installation, and quick start guide
- **[DJANGO_QUICKSTART.md](DJANGO_QUICKSTART.md)** - Quick Django setup and development guide

### Deployment & Operations
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Production deployment instructions
- **[STATUS.md](STATUS.md)** - Current project status and progress tracker

### Feature Documentation
- **[DASHBOARD_INTEGRATION_GUIDE.md](DASHBOARD_INTEGRATION_GUIDE.md)** - Dashboard features and usage
- **[DJANGO_MIGRATION.md](DJANGO_MIGRATION.md)** - SQLAlchemy to Django migration guide
- **[API_TEST_RESULTS.md](API_TEST_RESULTS.md)** - Comprehensive API testing results
- **[DATA_PULL_FIX_SUMMARY.md](DATA_PULL_FIX_SUMMARY.md)** - Data pull system fixes and validation

### Development Journal
See the **[Journal/](../Journal/)** directory for detailed development logs, decision records, and session notes.

---

## 🗄️ Archived Documentation

The **[Archive/](Archive/)** directory contains outdated documentation from earlier project phases:

- `component_1_database_design.md` - Original database design (superseded by Django models)
- `component_2_data_acquisition.md` - Initial data acquisition design
- `component_3_django_interface.md` - Early Django interface planning
- `component_4_rest_api.md` - Initial REST API design (superseded by DRF implementation)
- `README_COMPONENT2.md` - Component 2 specific documentation

These files are kept for historical reference but are no longer actively maintained.

---

## 🏗️ Project Structure Reference

### API Documentation
- **Swagger UI:** http://localhost:8000/api/v1/docs/
- **ReDoc:** http://localhost:8000/api/v1/redoc/
- **OpenAPI Schema:** http://localhost:8000/api/v1/schema/

### Key Directories
- `/apps/` - Django applications (api, streamflow, monitoring)
- `/src/` - Core acquisition logic (USGS, NOAA, Canada clients)
- `/tests/` - Test suite
- `/config/` - Django settings and configuration
- `/Journal/` - Development journal and decision logs
- `/data/` - Sample data files

---

## 📊 Current System Status

### Database
- **Stations:** 309 active stations
- **Observations:** 683 discharge records
- **Forecasts:** 450 forecast runs
- **Configurations:** 4 active pull configurations

### API Endpoints
- ✅ Stations API (list, detail, statistics)
- ✅ Observations API (list, filter, export, statistics)
- ✅ Forecasts API (list, detail, statistics, by-station, latest)
- ✅ Configurations API (list, detail, manage)
- ✅ Logs API (list, detail, monitoring)

### Web Interface
- ✅ Dashboard with observations and forecasts
- ✅ Station management
- ✅ Configuration management
- ✅ Data pull execution and monitoring
- ✅ Interactive forecast visualization (Plotly)

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
