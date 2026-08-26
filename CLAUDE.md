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

## Gridded Data Configuration — Enforced Rule

**All gridded dataset sources must be visible and configurable through the GUI at `/gridded-configurations/`.** This is a hard requirement — no hidden or code-only configurations.

Specifically:

- Any new `RasterDataset` and its `RasterVariable` entries **must** be registered in `python manage.py init_raster_datasets` (the management command in `apps/streamflow/management/commands/init_raster_datasets.py`). This is what populates the dataset/variable dropdowns in the GUI creation form. A dataset that is not registered here will not appear in the GUI.
- `RasterPullConfiguration` records (the scheduled pull jobs) must be created and managed through the GUI at `/gridded-configurations/new/` — never hardcoded in scripts, management commands, or migrations.
- When adding a new gridded source (e.g., NWM, a new NOAA product, a new NASA dataset), the workflow is always: (1) add to `init_raster_datasets`, (2) run the command, (3) create the configuration through the GUI.
- The GUI must remain the single source of truth for which datasets are actively being pulled and on what schedule.

---

## Architecture

### App Layout

```
apps/
  streamflow/     # Core models, web views, management commands, templates
  api/            # DRF viewsets, serializers, URL registration
  analytics/      # DailyFlowPercentile model + scheduled computation tracking
  monitoring/     # Placeholder health monitoring app
  nwm_forcings/   # NWM Analysis Assim hourly → daily basin forcing ingestion

src/
  acquisition/  # Data clients, Celery tasks, raster processing (NOT a Django app)
  analytics/    # Percentile computation logic and Celery tasks
```

The `src/` tree is not a Django app — it's imported directly by Celery tasks and management commands. Task autodiscovery in `config/celery.py` explicitly includes `src.acquisition` and `src.acquisition.raster_tasks`.

### Core Data Models (`apps/streamflow/models.py`)

- **Station** — 309 active monitoring stations (USGS, EC, NOAA_RFC)
- **DischargeObservation** — Time-series discharge with `type` (`realtime_15min` | `daily_mean`) and `quality_code`; unique on `(station, observed_at, type)`
- **ForecastRun** — Forecast payload in a `data` JSONField (`[{date, value}]`); `forecast_type` is `short` | `medium` | `long`; unique on `(station, source, run_date, forecast_type)`
- **PullConfiguration** + **PullConfigurationStation** — Scheduled acquisition jobs linked to stations; `skip_inactive_stations` (default off) limits a pull to `is_active` stations
- **PullStationProgress** — Tracks last successful pull per station for smart-append (incremental pulls)
- **MasterStation** / **StationMapping** — 14,319 reference stations; cross-network ID resolution (USGS ↔ HADS ↔ EC)
- **RasterDataset / RasterVariable / RasterLayer / SpatialExtent** — Gridded raster metadata (PostGIS geometry on SpatialExtent); `RasterDataset.DATA_SOURCE_CHOICES` includes `nwm_s3`
- **DailyFlowPercentile** — Precomputed daily percentile bands per station/DOY
- **BasinForcing** — Daily basin-averaged meteorological forcings for EA-LSTM inference; fields: `station` (FK→Station), `date`, `prcp_mm_day`, `tmax_c`, `tmin_c`, `srad_w_m2`, `vp_pa`, `dayl_s`, `source` (`nwm` | `daymet`); unique on `(station, date, source)`; table: `basin_forcings`

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
6. `DataPullLog` records success/partial/failure

#### Per-source request pacing

`SOURCE_PACING` in `src/acquisition/tasks.py` sets concurrency and inter-request
delay per data source. Upstreams throttle differently and not all of them say so:

| Source | Workers | Delay | Why |
|--------|---------|-------|-----|
| `nwrfc_web` | 1 | 1.5s | Returns 429 on any parallelism |
| `USGS` | 3 | 1.0s | Degrades silently under bursts — empty bodies (`Expecting value: line 1 column 1`) and truncated gzip, not 429s |
| everything else | 8 | 0 | Historical default |

When adding a source that starts failing intermittently at scale, add a
`SOURCE_PACING` entry rather than lowering the global `STATION_WORKERS`.

#### Run status is proportional, not all-or-nothing

`DataPullLog.status` is `running` | `success` | `partial` | `failed`.
`classify_pull_status()` returns `partial` when failures stay within
`PARTIAL_FAILURE_THRESHOLD` (5%) of stations attempted. Large configs routinely
lose a few stations to transient upstream errors that self-heal next run;
marking those runs `failed` buried the genuinely broken ones.

Use `DataPullLog.HEALTHY_STATUSES` for success-rate math rather than hardcoding
`'success'` — partial runs delivered their data and count as healthy.

#### Skipping discontinued stations

`PullConfiguration.skip_inactive_stations` (default `False`, GUI-toggleable on
the configuration form) restricts a pull to stations whose `Station.is_active`
is true.

**It is opt-in for a reason:** `is_active` is not maintained uniformly. All 366
`NOAA_RFC` stations are flagged inactive while actively producing forecasts, so
enabling this on a NWRFC config would silently empty the pull. It is safe for
USGS and EC, where the flag tracks reality. A run whose stations all filter out
is logged `failed`, never `success`.

### API (`apps/api/`)

Base path: `/api/v1/` — Full OpenAPI docs at `/api/v1/docs/`

Key non-obvious endpoints:
- `GET /api/v1/master-stations/lookup/?id={id}` — Cross-network station ID resolution
- `POST /api/v1/configurations/{id}/trigger/` — Manual pull trigger
- `POST /api/v1/raster-layers/extract_points/` — Extract raster values at lat/lon coordinates
- `GET /api/v1/forcings/{usgs_id}/?days=N` — Basin-averaged daily forcings for EA-LSTM inference; unauthenticated (public met data); returns `source='nwm'` rows, falling back to `source='daymet'` when none exist; ordered oldest-first; 400 on invalid `days`

### BasinForcing / EA-LSTM Integration

The `BasinForcing` model stores daily basin-averaged meteorological forcings used by the resid-cast EA-LSTM precipitation-runoff model. Two sources:

- `source='daymet'` — Historical CAMELS Daymet forcings (1980–2014); backfilled via `backfill_basin_forcings.py` for 37 CAMELS-overlap PNW stations; ~12,784 rows/station (473,008 total)
- `source='nwm'` — NWM Analysis Assim daily forcings; populated by the `apps/nwm_forcings/` Celery task (see below) and by `backfill_nwm_forcings` for historical dates

The forcings endpoint (`GET /api/v1/forcings/{usgs_id}/`) is consumed by `precip-runoff-cast/forecast_service/jobs/runner.py`, which calls it to build the dynamic input sequence for EA-LSTM inference. The view returns `nwm` rows first, falling back to `daymet` so inference works from historical data until NWM data is flowing.

### apps/nwm_forcings — NWM Analysis Assim Ingestion

Downloads hourly NWM Analysis Assim NetCDF forcing files, spatially aggregates them to 37 EA-LSTM CAMELS-overlap basin polygons using pre-computed weight indices, derives daily meteorological variables, and upserts `BasinForcing` rows with `source='nwm'`.

**Key modules:**

| File | Purpose |
|------|---------|
| `constants.py` | `EA_LSTM_USGS_IDS` — 37 CAMELS-overlap USGS station IDs |
| `models.py` | `NWMIngestionLog` — per-day ingest audit log |
| `grid.py` | `load_grid_from_file()` — reads XLAT_M/XLONG_M from NWM NetCDF |
| `weights.py` | `find_cells_in_polygon()`, `save_weights()`, `load_weights()` — basin polygon → grid cell indices (.npz) |
| `nwm_client.py` | `download_file()` with tenacity retry; `NWMTransientError` for 5xx (retried); `NWMDownloadError` for 4xx (not retried) |
| `processors.py` | `extract_hourly_basin_record()`, `aggregate_hourly_to_daily()` — variable extraction and unit conversion |
| `tasks.py` | `ingest_day()`, `ingest_nwm_forcings_daily()` Celery task |

**Management commands:**

```bash
# One-time setup: compute basin weight indices (downloads sample NWM file + queries NLDI API)
python manage.py compute_nwm_weights
python manage.py compute_nwm_weights --sample-file /path/to/existing.nc  # skip download
python manage.py compute_nwm_weights --usgs-id 14306500  # single station

# Historical backfill from AWS S3 (available from ~2018-10-01)
python manage.py backfill_nwm_forcings --start 2018-10-01 --end 2025-06-01
python manage.py backfill_nwm_forcings --start 2024-01-01 --end 2024-12-31 --dry-run
python manage.py backfill_nwm_forcings --start 2024-01-01 --end 2024-12-31 --no-skip-existing
```

**Variable derivations:**

| Variable | Formula |
|----------|---------|
| `prcp_mm_day` | `mean(RAINRATE mm/s) × 86400` — mean over actual downloaded hours only |
| `tmax_c` / `tmin_c` | `max/min(T2D K) − 273.15` |
| `srad_w_m2` | `mean(SWDOWN W/m²)` — mean over actual downloaded hours only |
| `vp_pa` | `(Q2D × PSFC) / (0.622 + 0.378 × Q2D)` |
| `dayl_s` | Astronomical solar declination formula from basin centroid latitude |

**Important conventions:**
- Weight files live in `data/nwm_weights/{usgs_id}.npz` (configurable via `NWM_WEIGHTS_DIR`)
- Partial days: fill missing hours with nearest available file for temp min/max; mean-based variables (`prcp_mm_day`, `srad_w_m2`) use only the actually-downloaded hours to avoid bias
- Skips station if `< 20` unique valid hours, no weight file, or station not in DB
- `stations_updated == 0` is logged as `status='failed'` — never silently reports success on empty output
- Tests require PostGIS on the test DB: `CREATE EXTENSION postgis;` as superuser once

**To backfill a new station** (must have a CAMELS Daymet file):
```bash
# Add USGS ID to resid_cast_stations.json with ealstm_available: true, then:
python backfill_basin_forcings.py   # idempotent, skips existing rows
```

### Raster Pipeline

Clients in `src/acquisition/`: `NomadsClient` (RTMA GRIB2), `EarthDataClient` (SMAP/MODIS/GPM HDF5/NetCDF4). Output processed by `RasterProcessor` into GeoTIFFs stored under `data/rasters/{dataset}/{variable}/{extent}/{year}/{month}/`. `RasterLayer` model tracks metadata and file paths.

### Settings & Environment

Settings live in `config/settings.py` (single file, no split dev/prod). Key env vars:

```
DATABASE_URL                 # postgresql://user:pass@host:5432/db
CELERY_BROKER_URL            # redis://localhost:6379/0
EARTHDATA_USERNAME/PASSWORD  # NASA EarthData
DJANGO_SECRET_KEY
RASTER_ROOT                  # Absolute path for raster file storage
ALERT_EMAIL_ENABLED / ALERT_EMAIL_RECIPIENTS
FLOWER_BASIC_AUTH
NWM_WEIGHTS_DIR              # Path to basin weight .npz files (default: data/nwm_weights/)
NWM_TEMP_DIR                 # Scratch dir for hourly NetCDF downloads (default: data/nwm_temp/)
NWM_NOMADS_BASE              # NOMADS base URL (default: https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod)
NWM_S3_BASE                  # AWS S3 base URL for historical data (default: https://noaa-nwm-pds.s3.amazonaws.com)
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
| NWM Analysis Assim ingest | Daily 07:00 UTC |
| RTMA cleanup (>7 days) | Sunday 02:00 UTC |
| EarthData cleanup (>30 days) | 1st of month 03:00 UTC |

### Deployment

**⚠️ This working tree IS production.** There is no separate deployed copy — `gunicorn.service`, `celery-worker.service`, `celery-beat.service`, and `flower.service` all run directly from `/home/streamflow/streamflow-dataOps/streamflow-dataOps` using the `venv/` in this directory (verified 2026-07-30 via systemd unit files, running-process CWDs, and nginx config). Uncommitted edits here go live: immediately for management commands and newly picked-up Celery tasks, on next service restart for the web app. Develop in a separate clone or worktree, push, then `git pull` here and restart.

`/home/streamflow/htdocs/streamflowops.3rdplaces.io/` is **not** the app — it's only the Let's Encrypt ACME challenge webroot (CloudPanel site root, reverse-proxy type). Its `.well-known/` is empty between cert renewals; do not delete it or SSL renewal breaks. See the README inside it.

- Systemd services on Hostinger VPS; restart: `sudo systemctl restart gunicorn celery-worker celery-beat`
- nginx proxies HTTPS to gunicorn on `127.0.0.1:8000`; serves `/static/` via alias to `staticfiles/` in this tree; `/flower/` proxies to `127.0.0.1:5555`
- `SECURE_PROXY_SSL_HEADER` set; nginx handles SSL termination (cert at `/etc/nginx/ssl-certificates/streamflowops.3rdplaces.io.crt`, auto-renewed by CloudPanel)
- Static files collected to `staticfiles/`
- WSGI entry: `config.wsgi.application`

### Testing Notes

Tests use both `pytest` and Django's `manage.py test`. Test files live in `tests/` (40+ modules). Integration tests and Selenium E2E tests exist — these require a live DB and browser respectively; skip with `-k "not selenium"` when running unit tests only.
