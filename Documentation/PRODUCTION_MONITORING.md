# Production Scheduling & Monitoring Guide

Complete guide for running, monitoring, and maintaining the automated raster data acquisition system.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Service Management](#service-management)
3. [Monitoring with Flower](#monitoring-with-flower)
4. [Health Checks & Alerts](#health-checks--alerts)
5. [Data Retention](#data-retention)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites

- PostgreSQL running
- Redis running
- Python environment activated
- NASA EarthData credentials configured (`.netrc` or environment variables)

### Automated Setup

```bash
# Initialize datasets and start all services
./scripts/start_production.sh
```

This script will:
- ✅ Check Redis and PostgreSQL
- ✅ Initialize raster datasets if needed
- ✅ Run database migrations
- ✅ Start Django, Celery worker, Celery beat, and Flower in tmux

### Manual Setup

```bash
# 1. Initialize datasets (first time only)
python manage.py init_raster_datasets

# 2. Run migrations
python manage.py migrate

# 3. Start services in separate terminals:

# Terminal 1: Django
python manage.py runserver 0.0.0.0:8000

# Terminal 2: Celery Worker
celery -A config worker -l info --concurrency=4

# Terminal 3: Celery Beat (Scheduler)
celery -A config beat -l info

# Terminal 4: Flower (Monitoring)
celery -A config flower --port=5555
```

---

## Service Management

### Production Schedules

All schedules defined in `config/celery.py`:

| Task | Schedule | Data Source | Description |
|------|----------|-------------|-------------|
| **fetch-rtma-hourly** | Every hour at :05 | NOMADS | NOAA RTMA temperature, wind |
| **fetch-smap-daily** | Daily at 3:00 AM UTC | EarthData | NASA SMAP soil moisture |
| **fetch-modis-terra-daily** | Daily at 4:00 AM UTC | EarthData | MODIS Terra LST |
| **fetch-modis-aqua-daily** | Daily at 4:30 AM UTC | EarthData | MODIS Aqua LST |
| **fetch-gpm-daily** | Daily at 5:00 AM UTC | EarthData | GPM precipitation |
| **cleanup-rtma-weekly** | Sunday at 2:00 AM UTC | - | Delete RTMA >7 days old |
| **cleanup-earthdata-monthly** | 1st of month at 3:00 AM UTC | - | Delete EarthData >30 days old |
| **monitor-pull-health** | Every 6 hours | - | Check system health |
| **cleanup-pull-logs** | Sunday at 1:00 AM UTC | - | Delete logs >90 days old |

### Managing Celery Services

```bash
# Check worker status
celery -A config inspect active

# Check scheduled tasks
celery -A config inspect scheduled

# View registered tasks
celery -A config inspect registered

# Purge all tasks
celery -A config purge

# Stop workers gracefully
celery -A config control shutdown

# Restart workers
pkill -f "celery worker" && celery -A config worker -l info --detach
```

### Tmux Session Management

```bash
# Attach to running session
tmux attach -t streamflow

# List windows (inside tmux)
Ctrl+B then W

# Switch between windows
Ctrl+B then [0-3]  # Window number

# Detach from session
Ctrl+B then D

# Kill session
tmux kill-session -t streamflow
```

---

## Monitoring with Flower

### Access Flower Dashboard

Open browser to: **http://localhost:5555/**

### Key Features

#### 1. **Tasks Tab**
- View all executed tasks
- Filter by state (success, failure, running)
- Inspect task arguments and results
- View execution time and timestamps

#### 2. **Workers Tab**
- Monitor worker processes
- Check CPU and memory usage
- View active tasks per worker
- Restart individual workers

#### 3. **Monitor Tab**
- Real-time task execution graphs
- Success/failure rates
- Task throughput (tasks/minute)
- Queue lengths

#### 4. **Broker Tab**
- Redis connection status
- Queue statistics
- Message counts

### Task States in Flower

| State | Description |
|-------|-------------|
| 🟢 **SUCCESS** | Task completed successfully |
| 🔴 **FAILURE** | Task failed (check error logs) |
| 🟡 **PENDING** | Task queued, waiting for worker |
| 🔵 **RUNNING** | Task currently executing |
| ⚪ **RETRY** | Task retrying after failure |

---

## Health Checks & Alerts

### Manual Health Check

```bash
# Generate comprehensive health report
python manage.py shell << EOF
from src.acquisition.monitoring_tasks import generate_health_report
import json
report = generate_health_report()
print(json.dumps(report, indent=2))
EOF
```

### Automated Health Monitoring

The `monitor-pull-health` task runs every 6 hours and checks:

- ✅ Last successful pull for each dataset
- ✅ Consecutive failure counts
- ✅ Disk space usage
- ✅ Stale data (>48 hours since pull)

### Email Alerts Configuration

Add to `.env` file:

```bash
# Email alerting
ALERT_EMAIL_ENABLED=true
ALERT_EMAIL_RECIPIENTS=admin@example.com,ops@example.com
ALERT_EMAIL_FROM=noreply@streamflow-dataops.org

# SMTP settings (Django)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
```

### Alert Thresholds

Configure in `config/settings.py`:

```python
# Alert after 3 consecutive failures
RASTER_PULL_FAILURE_THRESHOLD = 3

# Alert if no successful pull in 48 hours
RASTER_PULL_MAX_AGE_HOURS = 48
```

### Testing Alerts

```bash
# Manually trigger health check
python manage.py shell -c "
from src.acquisition.monitoring_tasks import monitor_pull_health
result = monitor_pull_health()
print(result)
"
```

---

## Data Retention

### Current Policies

| Data Source | Retention Period | Cleanup Schedule |
|-------------|------------------|------------------|
| **NOAA RTMA** | 7 days | Weekly (Sunday 2 AM) |
| **NASA EarthData** | 30 days | Monthly (1st at 3 AM) |
| **Pull Logs** | 90 days | Weekly (Sunday 1 AM) |

### Manual Cleanup

```bash
# Clean up RTMA data older than 7 days
python manage.py shell -c "
from src.acquisition.monitoring_tasks import cleanup_old_layers
result = cleanup_old_layers(dataset_name='NOAA_RTMA', retention_days=7, dry_run=False)
print(f'Deleted {result[\"deleted_layers\"]} layers, freed {result[\"freed_bytes\"]/(1024**3):.2f} GB')
"

# Dry run to see what would be deleted
python manage.py shell -c "
from src.acquisition.monitoring_tasks import cleanup_old_layers
result = cleanup_old_layers(data_source='earthdata', retention_days=30, dry_run=True)
print(f'Would delete {result[\"total_layers\"]} layers')
"
```

### Disk Space Monitoring

```bash
# Check current usage
df -h /path/to/data/rasters

# Check number of raster files
python manage.py shell -c "
from apps.streamflow.models import RasterLayer
from pathlib import Path
from django.conf import settings

total_size = 0
count = 0
for layer in RasterLayer.objects.all():
    path = Path(layer.file_path)
    if path.exists():
        total_size += path.stat().st_size
        count += 1

print(f'Total layers: {count}')
print(f'Total size: {total_size/(1024**3):.2f} GB')
"
```

---

## Troubleshooting

### No Data Being Pulled

1. **Check Celery Beat is running:**
   ```bash
   ps aux | grep "celery beat"
   ```

2. **Check scheduled tasks:**
   ```bash
   celery -A config inspect scheduled
   ```

3. **Check for errors in logs:**
   ```bash
   tail -f logs/celery-worker.log
   ```

4. **Manually trigger a pull:**
   ```bash
   python manage.py shell -c "
   from apps.streamflow.models import RasterPullConfiguration
   from src.acquisition.raster_tasks import pull_raster_data
   config = RasterPullConfiguration.objects.first()
   pull_raster_data(config.id)
   "
   ```

### Tasks Stuck in PENDING

- **Cause:** Worker not running or Redis connection lost
- **Fix:**
  ```bash
  # Check Redis
  redis-cli ping
  
  # Restart worker
  pkill -f "celery worker"
  celery -A config worker -l info
  ```

### High Failure Rate

1. **Check NASA EarthData credentials:**
   ```bash
   python manage.py test_earthdata_integration
   ```

2. **Check NOAA NOMADS availability:**
   ```bash
   python manage.py test_nomads_rtma
   ```

3. **Review failed pull logs:**
   ```python
   # In Django shell
   from apps.streamflow.models import RasterPullLog
   failed = RasterPullLog.objects.filter(status='failed').order_by('-started_at')[:10]
   for log in failed:
       print(f"{log.started_at}: {log.configuration.name}")
       print(f"  Error: {log.error_message}\n")
   ```

### Disk Space Full

```bash
# Emergency cleanup - delete all data older than X days
python manage.py shell -c "
from src.acquisition.monitoring_tasks import cleanup_old_layers

# Delete old RTMA (>3 days)
cleanup_old_layers(dataset_name='NOAA_RTMA', retention_days=3, dry_run=False)

# Delete old NASA data (>14 days)
cleanup_old_layers(data_source='earthdata', retention_days=14, dry_run=False)
"
```

### Memory Issues

```bash
# Reduce worker concurrency
celery -A config worker -l info --concurrency=2

# Or limit memory per worker
celery -A config worker -l info --max-memory-per-child=500000  # 500MB
```

### Database Connection Errors

```bash
# Check PostgreSQL
pg_isready

# Check connections
python manage.py shell -c "
from django.db import connection
cursor = connection.cursor()
cursor.execute('SELECT version();')
print(cursor.fetchone())
"

# Reset connections
python manage.py migrate --fake-initial
```

---

## Performance Monitoring

### Key Metrics to Track

1. **Pull Success Rate**
   - Target: >95% success rate
   - Alert if <90% over 24 hours

2. **Pull Duration**
   - RTMA: <5 minutes
   - SMAP/MODIS: <15 minutes
   - GPM: <10 minutes

3. **Data Freshness**
   - RTMA: <2 hours old
   - Daily products: <36 hours old

4. **Disk Usage**
   - Target: <80% capacity
   - Alert at >90%

### Performance Commands

```bash
# Average pull duration by dataset
python manage.py shell -c "
from apps.streamflow.models import RasterPullLog
from django.db.models import Avg, Count
from datetime import timedelta

stats = RasterPullLog.objects.filter(
    status='completed',
    duration__isnull=False
).values('configuration__dataset__name').annotate(
    avg_duration=Avg('duration'),
    count=Count('id')
)

for stat in stats:
    avg_mins = stat['avg_duration'].total_seconds() / 60 if stat['avg_duration'] else 0
    print(f\"{stat['configuration__dataset__name']}: {avg_mins:.1f} min avg ({stat['count']} pulls)\")
"
```

---

## Production Checklist

### Daily Checks
- [ ] Check Flower dashboard for errors
- [ ] Verify all scheduled tasks ran
- [ ] Review disk space usage

### Weekly Checks
- [ ] Review pull success rates
- [ ] Check for stale datasets
- [ ] Verify cleanup tasks executed

### Monthly Checks
- [ ] Review alert thresholds
- [ ] Analyze performance trends
- [ ] Update retention policies if needed
- [ ] Test backup/restore procedures

---

## Additional Resources

- **Django Admin:** http://localhost:8000/admin/
- **API Documentation:** http://localhost:8000/api/v1/docs/
- **Flower Dashboard:** http://localhost:5555/
- **Celery Documentation:** https://docs.celeryq.dev/
- **Flower Documentation:** https://flower.readthedocs.io/

---

## Support

For issues or questions:
1. Check logs in `logs/celery-worker.log`
2. Review Flower dashboard for task failures
3. Run health check command
4. Check GitHub issues: [streamflow-dataOps](https://github.com/geoskimoto/streamflow-dataOps)
