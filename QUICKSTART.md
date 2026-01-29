# Quick Start Guide: Production Raster System

## 🚀 Getting Started (3 minutes)

### 1. Prerequisites Check
```bash
redis-cli ping         # Should return "PONG"
pg_isready            # Should return "accepting connections"
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Initialize System
```bash
# Set up all datasets and configurations
python manage.py init_raster_datasets

# Or preview first
python manage.py init_raster_datasets --dry-run
```

### 4. Start Services
```bash
# Automated (recommended)
./scripts/start_production.sh

# Or manual in 4 terminals:
python manage.py runserver              # Terminal 1
celery -A config worker -l info         # Terminal 2
celery -A config beat -l info           # Terminal 3
celery -A config flower --port=5555     # Terminal 4
```

---

## 📊 Access Points

| Service | URL | Purpose |
|---------|-----|---------|
| **Django Admin** | http://localhost:8000/admin/ | Manage datasets |
| **REST API** | http://localhost:8000/api/v1/ | API endpoints |
| **API Docs** | http://localhost:8000/api/v1/schema/swagger-ui/ | Interactive docs |
| **Flower** | http://localhost:5555/ | Task monitoring |

---

## 🕐 Automatic Schedules

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

See [PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md) for complete guide including:
- Detailed troubleshooting
- Service management
- Performance tuning
- Alert configuration
- Backup procedures

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
