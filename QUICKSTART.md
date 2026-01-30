# StreamFlow DataOps Quick Start Guide

Complete guide to getting started with both **Timeseries Station Data** and **Gridded Raster Data** systems.

---

## 🚀 Getting Started (5 minutes)

### 1. Prerequisites Check
```bash
redis-cli ping         # Should return "PONG"
pg_isready            # Should return "accepting connections"
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Initialize Both Systems

#### A. Gridded/Raster Data System
```bash
# Set up all raster datasets and configurations
python manage.py init_raster_datasets

# Or preview first
python manage.py init_raster_datasets --dry-run
```

#### B. Timeseries Station System
```bash
# Load USGS stations (choose your region)
python manage.py load_master_stations --state WA
python manage.py load_master_stations --state OR
python manage.py load_master_stations --state CA

# Or load by watershed (HUC)
python manage.py load_master_stations --huc 17  # Columbia River Basin

# Load NOAA RFC stations
python manage.py import_noaa_rfc_stations --rfc NWRFC

# Or by states
python manage.py import_noaa_rfc_stations --states WA OR ID MT
```

### 4. Start Services
```bash
# Automated (recommended)
./scripts/start_production.sh

# Or manual in 4 terminals:
python manage.py runserver              # Terminal 1
celery -A config worker -l info         # Terminal 2
celery -A config beat -l info           # Terminal 3
celery -A config flower --port=5555 --broker=redis://localhost:6379/0     # Terminal 4
```

---

## 📊 Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| **Django Admin** | http://localhost:8000/admin/ | Manage datasets & stations |
| **Timeseries Configs** | http://localhost:8000/timeseries-configurations/ | Configure station data pulls |
| **Gridded Configs** | http://localhost:8000/gridded-configurations/ | Configure raster data pulls |
| **REST API** | http://localhost:8000/api/v1/ | API endpoints |
| **API Docs (Swagger)** | http://localhost:8000/api/v1/docs/ | Interactive API docs |
| **API Docs (ReDoc)** | http://localhost:8000/api/v1/redoc/ | Alternative API docs |
| **Flower** | http://localhost:5555/ | Task monitoring |

---

## 📍 Timeseries Station Data

### Initial Setup

1. **Load stations from USGS:**
   ```bash
   # By state (most common)
   python manage.py load_master_stations --state WA
   python manage.py load_master_stations --state OR
   python manage.py load_master_stations --state CA
   
   # By watershed
   python manage.py load_master_stations --huc 17  # Columbia River
   ```

2. **Load stations from NOAA River Forecast Centers:**
   ```bash
   # By RFC
   python manage.py import_noaa_rfc_stations --rfc NWRFC  # Northwest
   python manage.py import_noaa_rfc_stations --rfc CNRFC  # California-Nevada
   
   # By states
   python manage.py import_noaa_rfc_stations --states WA OR ID MT
   ```

3. **Verify stations loaded:**
   ```bash
   python manage.py shell -c "from apps.streamflow.models import MasterStation; print(f'Total stations: {MasterStation.objects.count()}')"
   ```

### Creating Pull Configurations

**Via Web Interface:**
1. Go to http://localhost:8000/timeseries-configurations/
2. Click "Create New Configuration"
3. Name your configuration (e.g., "Columbia River Stations")
4. Search and select stations
5. Set pull schedule (hourly, daily, etc.)
6. Save configuration

**Via Django Admin:**
1. Go to http://localhost:8000/admin/streamflow/pullconfiguration/
2. Add new pull configuration
3. Add stations to configuration

### Data Pull Operations

```bash
# Sync stations (create Station records from MasterStation)
python manage.py sync_stations

# Check configured stations
python manage.py shell -c "
from apps.streamflow.models import PullConfiguration
for config in PullConfiguration.objects.all():
    count = config.stations.count()
    print(f'{config.name}: {count} stations')
"
```

### Available Station Sources

| Source | Agency Code | Command | Coverage |
|--------|------------|---------|----------|
| **USGS** | USGS | `load_master_stations` | All US states, territories |
| **NOAA RFC** | NOAA_RFC | `import_noaa_rfc_stations` | US + some BC stations |
| **Environment Canada** | EC | `load_ec_stations` | British Columbia, Canada |

---

## 🌐 Gridded Raster Data

### Available Datasets

All datasets initialized by `init_raster_datasets`:

| Dataset | Temporal Resolution | Spatial Resolution | Variables |
|---------|-------------------|-------------------|-----------|
| **NOAA RTMA** | Hourly | 2.5 km | Temperature, Pressure, Wind, Humidity, Precip |
| **NASA SMAP L4** | Daily | 9 km | Soil Moisture (0-5cm, 0-100cm, Root Zone) |
| **MODIS Terra** | Daily | 1 km | Land Surface Temperature (Day/Night) |
| **MODIS Aqua** | Daily | 1 km | Land Surface Temperature (Day/Night) |
| **NASA GPM IMERG** | 30 minutes | 11 km | Precipitation, Probability, Error |

### Creating Pull Configurations

**Via Web Interface:**
1. Go to http://localhost:8000/gridded-configurations/
2. Click "Create New Configuration"
3. Name your configuration (e.g., "Western US Hourly Temperature")
4. Select variables (all must be from same dataset)
5. Choose spatial extent
6. Set pull schedule
7. Save configuration

**Via Management Command:**
```bash
python manage.py create_raster_config
```

### Manual Data Operations

```bash
# List available configurations
python manage.py pull_raster_data --list

# Manual pull for today
python manage.py pull_raster_data --config "Western US RTMA"

# Pull specific date
python manage.py pull_raster_data --config "SMAP Soil Moisture" --date 2026-01-15

# Backfill date range
python manage.py backfill_rasters \
    --config "Western US RTMA" \
    --start-date 2026-01-01 \
    --end-date 2026-01-15
```

---

## 🕐 Automatic Schedules

### Gridded Data (Raster)

| Task | Schedule | What it Does |
|------|----------|--------------|
| RTMA Temperature | Every hour | Real-time weather analysis |
| SMAP Soil Moisture | Daily 3 AM | Global soil moisture |
| MODIS Terra LST | Daily 4 AM | Land surface temperature |
| MODIS Aqua LST | Daily 4:30 AM | Land surface temperature |
| GPM Precipitation | Daily 5 AM | Global precipitation |
| Cleanup RTMA | Sunday 2 AM | Delete data >7 days |
| Cleanup NASA | 1st of month 3 AM | Delete data >30 days |
| Health Check | Every 6 hours | Monitor system status |

### Timeseries Data (Stations)

| Task | Schedule | What it Does |
|------|----------|--------------|
| Station Data Pulls | Per config | Pull discharge/stage data from USGS/RFC |
| Station Sync | Hourly | Update station metadata |

*Note: Timeseries pull schedules are configured per PullConfiguration*

---

## 🔍 Quick Commands

### Check System Health
```bash
# View dashboard
open http://localhost:5555/

# CLI health report
python manage.py shell -c "
from src.acquisition.monitoring_tasks import generate_health_report
import json; print(json.dumps(generate_health_report(), indent=2))
"
```

### Manual Data Pull
```bash
# Pull RTMA data
python manage.py shell -c "
from src.acquisition.raster_tasks import scheduled_raster_pulls
scheduled_raster_pulls(dataset_name='NOAA_RTMA')
"

# Pull all EarthData sources
python manage.py shell -c "
from src.acquisition.raster_tasks import scheduled_raster_pulls
scheduled_raster_pulls(data_source='earthdata')
"
```

### View Recent Tasks
```bash
# Show active tasks
celery -A config inspect active

# Show scheduled tasks
celery -A config inspect scheduled

# Show task stats
celery -A config inspect stats
```

### Check Logs
```bash
# Failed pulls
python manage.py shell -c "
from apps.streamflow.models import RasterPullLog
for log in RasterPullLog.objects.filter(status='failed')[:5]:
    print(f'{log.started_at}: {log.configuration.name} - {log.error_message}')
"

# Recent successful pulls
python manage.py shell -c "
from apps.streamflow.models import RasterPullLog
for log in RasterPullLog.objects.filter(status='completed').order_by('-completed_at')[:5]:
    print(f'{log.completed_at}: {log.configuration.name} - {log.layers_created} layers')
"
```

---

## 🗑️ Data Management

### Check Disk Usage
```bash
# Total storage used
python manage.py shell -c "
from apps.streamflow.models import RasterLayer
from pathlib import Path
total = sum(Path(l.file_path).stat().st_size for l in RasterLayer.objects.all() if Path(l.file_path).exists())
print(f'Total: {total/(1024**3):.2f} GB')
"
```

### Manual Cleanup
```bash
# Clean old RTMA (>7 days)
python manage.py shell -c "
from src.acquisition.monitoring_tasks import cleanup_old_layers
cleanup_old_layers(dataset_name='NOAA_RTMA', retention_days=7)
"

# Preview cleanup (dry run)
python manage.py shell -c "
from src.acquisition.monitoring_tasks import cleanup_old_layers
result = cleanup_old_layers(data_source='earthdata', retention_days=30, dry_run=True)
print(f'Would delete {result[\"total_layers\"]} layers')
"
```

---

## 🚨 Troubleshooting

### Problem: No data being pulled
```bash
# Check if beat is running
ps aux | grep "celery beat"

# Check scheduled tasks
celery -A config inspect scheduled

# Manually trigger
python manage.py shell -c "
from src.acquisition.raster_tasks import scheduled_raster_pulls
scheduled_raster_pulls(dataset_name='NOAA_RTMA')
"
```

### Problem: Tasks stuck in PENDING
```bash
# Check worker is running
ps aux | grep "celery worker"

# Restart worker
pkill -f "celery worker" && celery -A config worker -l info
```

### Problem: NASA EarthData not working
```bash
# Test authentication
python manage.py test_earthdata_integration

# Check credentials
cat ~/.netrc | grep earthdata
```

### Problem: High failure rate
```bash
# Check recent failures
python manage.py shell -c "
from apps.streamflow.models import RasterPullLog
from django.db.models import Count
failures = RasterPullLog.objects.filter(status='failed').values(
    'configuration__dataset__name'
).annotate(count=Count('id')).order_by('-count')[:5]
for f in failures:
    print(f\"{f['configuration__dataset__name']}: {f['count']} failures\")
"
```

---

## 📧 Email Alerts Setup

Add to `.env`:
```bash
ALERT_EMAIL_ENABLED=true
ALERT_EMAIL_RECIPIENTS=admin@example.com,ops@example.com
ALERT_EMAIL_FROM=noreply@streamflow-dataops.org

EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
```

Test alerts:
```bash
python manage.py shell -c "
from src.acquisition.monitoring_tasks import monitor_pull_health
monitor_pull_health()
"
```

---

## 📈 Performance Monitoring

### Key Metrics
- **Success Rate:** >95% (check in Flower)
- **Pull Duration:** RTMA <5min, MODIS <15min
- **Data Freshness:** RTMA <2hr, Daily <36hr
- **Disk Usage:** <80% capacity

### View Metrics
```bash
# Average pull duration
python manage.py shell -c "
from apps.streamflow.models import RasterPullLog
from django.db.models import Avg
stats = RasterPullLog.objects.filter(status='completed').values(
    'configuration__dataset__name'
).annotate(avg_duration=Avg('duration'))
for s in stats:
    print(f\"{s['configuration__dataset__name']}: {s['avg_duration'].total_seconds()/60:.1f} min\")
"

# Success rate (last 7 days)
python manage.py shell -c "
from apps.streamflow.models import RasterPullLog
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Q

week_ago = timezone.now() - timedelta(days=7)
logs = RasterPullLog.objects.filter(started_at__gte=week_ago)
total = logs.count()
success = logs.filter(status='completed').count()
print(f'Success rate: {(success/total*100):.1f}% ({success}/{total})')
"
```

---

## 🛡️ Production Checklist

### Daily
- [ ] Check Flower dashboard (http://localhost:5555/)
- [ ] Verify recent pulls successful
- [ ] Review disk space

### Weekly
- [ ] Check success rates >95%
- [ ] Verify cleanup tasks ran
- [ ] Review any alerts sent

### Monthly
- [ ] Analyze performance trends
- [ ] Update retention policies if needed
- [ ] Test alert system

---

## 📚 Full Documentation

- **[Management Commands Reference](Documentation/Reference/MANAGEMENT_COMMANDS.md)** - Complete guide to all `manage.py` commands
- **[Production Monitoring](Documentation/PRODUCTION_MONITORING.md)** - Service management, performance tuning, alerts
- **[EarthData Setup](Documentation/EARTHDATA_SETUP.md)** - NASA EarthData authentication
- **[API Documentation](http://localhost:8000/api/v1/docs/)** - Interactive Swagger docs (when server running)

---

## 💡 Pro Tips

1. **Use tmux** for persistent sessions that survive disconnects
2. **Monitor Flower** regularly to catch issues early
3. **Set up email alerts** for hands-off monitoring
4. **Run dry-runs** before manual cleanup operations
5. **Check health reports** before investigating specific issues

---

**Need Help?** Check logs first, then Flower dashboard, then run health check command.

**Ready to Go?** Run `./scripts/start_production.sh` and access Flower at http://localhost:5555/
