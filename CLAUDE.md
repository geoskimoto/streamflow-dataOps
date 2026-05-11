# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

StreamFlow DataOps is a Django 4.2 platform for managing streamflow observations and forecasts from USGS, NOAA River Forecast Centers, and Environment Canada. It includes automated data acquisition via Celery, a REST API (DRF + drf-spectacular), a Bootstrap 5 web dashboard, PostGIS spatial data, and satellite raster ingestion (NOAA RTMA, NASA SMAP/MODIS/GPM).

Production domain: `streamflowops.3rdplaces.io` — deployed as a systemd service behind nginx on a Hostinger VPS.

---

## Commands

```bash
# Activate virtualenv (always required)
source venv/bin/activate

# Run development server
python manage.py runserver 0.0.0.0:8000

# Run all tests
python manage.py test

# Run a single test file
pytest tests/test_api_forecasts.py

# Run a single test class or method
python manage.py test tests.test_models.StationModelTest
python manage.py test tests.test_models.StationModelTest.test_str

# Check for model changes requiring migrations
python manage.py makemigrations --check

# Apply migrations
python manage.py migrate

# Start Celery worker
celery -A config worker --loglevel=info

# Start Celery Beat scheduler
celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler

# Collect static files
python manage.py collectstatic --noinput

# Seed raster dataset metadata (required after fresh deploy or migrations that wipe raster tables)
# Safe to re-run — uses get_or_create, skips existing records
# If /gridded-configurations/new/ shows "No datasets with variables found", run this
python manage.py init_raster_datasets
```

---

## Architecture

### App Layout

```
apps/
  streamflow/   # Core models, web views, management commands, templates
  api/          # DRF viewsets, serializers, URL registration
  analytics/    # DailyFlowPercentile model + scheduled computation tracking
  monitoring/   # Placeholder health monitoring app

src/
  acquisition/  # Data clients, Celery tasks, raster processing (NOT a Django app)
  analytics/    # Percentile computation logic and Celery tasks
```

The `src/` tree is not a Django app — it's imported directly by Celery tasks and management commands. Task autodiscovery in `config/celery.py` explicitly includes `src.acquisition` and `src.acquisition.raster_tasks`.

### Core Data Models (`apps/streamflow/models.py`)

- **Station** — 309 active monitoring stations (USGS, EC, NOAA_RFC)
- **DischargeObservation** — Time-series discharge with `type` (`realtime_15min` | `daily_mean`) and `quality_code`; unique on `(station, observed_at, type)`
- **ForecastRun** — Forecast payload in a `data` JSONField (`[{date, value}]`); `forecast_type` is `short` | `medium` | `long`; unique on `(station, source, run_date, forecast_type)`
- **PullConfiguration** + **PullConfigurationStation** — Scheduled acquisition jobs linked to stations
- **PullStationProgress** — Tracks last successful pull per station for smart-append (incremental pulls)
- **MasterStation** / **StationMapping** — 14,319 reference stations; cross-network ID resolution (USGS ↔ HADS ↔ EC)
- **RasterDataset / RasterVariable / RasterLayer / SpatialExtent** — Gridded raster metadata (PostGIS geometry on SpatialExtent)
- **DailyFlowPercentile** — Precomputed daily percentile bands per station/DOY

### Forecast Types

`ForecastRun.forecast_type` has three values:

| Value | Label | Horizon |
|-------|-------|---------|
| `short` | Short-range | 3–7 days (18 hr raw NOAA) |
| `medium` | Medium-range | up to 10 days |
| `long` | Long-range | up to 30 days |

The NOAA API client (`src/acquisition/noaa_client.py`) passes `forecast_type` directly as the `forecast` query param to `https://api.water.noaa.gov/nwps/v1/gauges/{hads_id}/stageflow`. The parquet importer infers type by horizon: ≤7 days → `short`, ≤10 days → `medium`, >10 days → `long`.

**NOAA station IDs are HADS IDs, not USGS IDs.** Translation happens via `StationMapping` before any NOAA API call.

### Data Acquisition Flow

1. `PullConfiguration` defines what (source, data type, stations) and when (schedule)
2. Celery Beat dispatcher (`src.acquisition.tasks.scheduled_streamflow_pulls`) runs every 5 min and triggers due configs
3. Each config calls the appropriate client: `USGSClient`, `NOAAClient`, or `CanadaClient`
4. `DataProcessor` (`src/acquisition/data_processor.py`) handles upsert logic
5. `PullStationProgress` records the watermark to enable smart-append on next run
6. `DataPullLog` records success/failure

### API (`apps/api/`)

Base path: `/api/v1/` — Full OpenAPI docs at `/api/v1/docs/`

Key non-obvious endpoints:
- `GET /api/v1/master-stations/lookup/?id={id}` — Cross-network station ID resolution
- `POST /api/v1/configurations/{id}/trigger/` — Manual pull trigger
- `POST /api/v1/raster-layers/extract_points/` — Extract raster values at lat/lon coordinates

### Raster Pipeline

Clients in `src/acquisition/`: `NomadsClient` (RTMA GRIB2), `EarthDataClient` (SMAP/MODIS/GPM HDF5/NetCDF4). Output processed by `RasterProcessor` into GeoTIFFs stored under `data/rasters/{dataset}/{variable}/{extent}/{year}/{month}/`. `RasterLayer` model tracks metadata and file paths.

### Settings & Environment

Settings live in `config/settings.py` (single file, no split dev/prod). Key env vars:

```
DATABASE_URL            # postgresql://user:pass@host:5432/db
CELERY_BROKER_URL       # redis://localhost:6379/0
EARTHDATA_USERNAME/PASSWORD  # NASA EarthData
DJANGO_SECRET_KEY
RASTER_ROOT             # Absolute path for raster file storage
ALERT_EMAIL_ENABLED / ALERT_EMAIL_RECIPIENTS
FLOWER_BASIC_AUTH
```

`DEBUG=False` is hardcoded; set it via env if needed locally.

### Celery Beat Schedule Summary

| Task | Schedule |
|------|----------|
| Streamflow pull dispatcher | Every 5 min |
| NOAA RTMA raster | Hourly at :05 |
| NASA SMAP | Daily 03:00 UTC |
| MODIS Terra/Aqua | Daily 04:00/04:30 UTC |
| GPM precipitation | Daily 05:00 UTC |
| Daily flow percentiles | 06:00, 12:00, 18:00 UTC |
| RTMA cleanup (>7 days) | Sunday 02:00 UTC |
| EarthData cleanup (>30 days) | 1st of month 03:00 UTC |

### Deployment

- Systemd service on Hostinger VPS; restart: `sudo systemctl restart <service>`
- nginx proxies HTTPS, serves static files via `location ^~ /static/`
- `SECURE_PROXY_SSL_HEADER` set; nginx handles SSL termination
- Static files collected to `staticfiles/`
- WSGI entry: `config.wsgi.application`

### Testing Notes

Tests use both `pytest` and Django's `manage.py test`. Test files live in `tests/` (40+ modules). Integration tests and Selenium E2E tests exist — these require a live DB and browser respectively; skip with `-k "not selenium"` when running unit tests only.
