# StreamFlow DataOps - Deployment Quick Start Guide

Complete guide for deploying StreamFlow DataOps from scratch to production.

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [System Requirements](#system-requirements)
3. [Quick Deploy (Recommended)](#quick-deploy-recommended)
4. [Manual Deployment](#manual-deployment)
5. [Post-Deployment](#post-deployment)
6. [Production Configuration](#production-configuration)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Python | 3.11+ | Application runtime |
| PostgreSQL | 16+ | Database with spatial support |
| PostGIS | 3.3+ | Spatial database extension |
| Redis | 6.0+ | Celery message broker |
| GDAL | 3.4+ | Geospatial data processing |

### Optional Software

| Software | Purpose |
|----------|---------|
| Google Earth Engine account | Raster data (RTMA, SMAP) |
| NASA Earthdata account | Satellite data authentication |
| Nginx/Apache | Production web server |
| Supervisor/systemd | Process management |

---

## System Requirements

### Minimum Specifications
- **CPU**: 2 cores
- **RAM**: 4 GB
- **Storage**: 20 GB SSD
- **OS**: Ubuntu 22.04+ or similar Linux distribution

### Recommended Specifications
- **CPU**: 4+ cores
- **RAM**: 8+ GB
- **Storage**: 100+ GB SSD
- **OS**: Ubuntu 22.04 LTS

---

## Quick Deploy (Recommended)

The automated deployment script (`scripts/deploy.py`) handles all setup steps.

### Step 1: System Dependencies

```bash
# Update package lists
sudo apt-get update

# Install PostgreSQL with PostGIS
sudo apt-get install -y postgresql-16 postgresql-16-postgis-3

# Install Redis
sudo apt-get install -y redis-server

# Install GDAL libraries
sudo apt-get install -y gdal-bin libgdal-dev python3-gdal

# Install Python development headers
sudo apt-get install -y python3-dev python3-pip python3-venv

# Start services
sudo systemctl start postgresql redis-server
sudo systemctl enable postgresql redis-server
```

### Step 2: Clone & Setup

```bash
# Clone repository
git clone <repository-url>
cd streamflow-dataOps

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit configuration
nano .env
```

**Required .env variables:**
```bash
DATABASE_URL=postgresql://streamflow_user:PASSWORD@localhost:5432/streamflow_db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-here  # Generate with django command
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,yourdomain.com
```

**Generate SECRET_KEY:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Step 4: Setup Database

```bash
# Create database user
sudo -u postgres psql -c "CREATE USER streamflow_user WITH PASSWORD 'YOUR_PASSWORD';"

# Create database
sudo -u postgres psql -c "CREATE DATABASE streamflow_db OWNER streamflow_user;"

# Enable PostGIS extensions
sudo -u postgres psql streamflow_db -c "CREATE EXTENSION postgis;"
sudo -u postgres psql streamflow_db -c "CREATE EXTENSION postgis_topology;"

# Grant privileges
sudo -u postgres psql -c "ALTER USER streamflow_user CREATEDB;"
```

### Step 5: Run Automated Deployment

```bash
# Preview deployment (dry run)
python scripts/deploy.py --dry-run

# Full automated deployment
python scripts/deploy.py

# Or skip dependency checks (faster)
python scripts/deploy.py --skip-deps
```

**What deploy.py does:**
1. ✅ Validates environment configuration
2. ✅ Checks system dependencies (PostgreSQL, Redis, GDAL, Python packages)
3. ✅ Verifies database connection and PostGIS
4. ✅ Runs database migrations
5. ✅ Collects static files
6. ✅ Populates master stations (~11,000 stations)
7. ✅ Syncs active stations (~6,500 stations)
8. ✅ Creates station mappings for RFC filtering
9. ✅ Sets up PullConfigurations for automated data collection:
   - **NWRFC Short-Range Forecasts** - Daily at 8:30 AM PST (18-hour forecasts)
   - **NWRFC Medium-Range Forecasts** - Daily at 8:30 AM PST (10-day forecasts)
   - **PNW USGS Daily Mean Discharge** - Daily at 9:00 AM PST (ongoing updates)
   - **PNW USGS Real-time 7-Day Window** - Every 4 hours (15-minute data)
   - **HUC 17 Historical Backfill** - Manual, one-time (Pacific Northwest: ~2,890 stations)
   - **HUC 14-18 Historical Backfill** - Manual, one-time (Western US: ~5,394 stations, disabled by default)

**Deployment options:**
```bash
--dry-run          # Preview without making changes
--skip-deps        # Skip dependency checks (faster)
--skip-stations    # Skip station data population
--skip-migrations  # Skip database migrations
--skip-static      # Skip static file collection
--skip-configs     # Skip PullConfiguration setup
```

### Step 6: Create Admin User

```bash
python manage.py createsuperuser
# Enter username, email, and password when prompted
```

### Step 7: Start Services

**Development:**
```bash
# Terminal 1: Django server
python manage.py runserver 0.0.0.0:8000

# Terminal 2: Celery worker
celery -A config worker -l info

# Terminal 3: Celery beat scheduler
celery -A config beat -l info
```

**Production:** See [Production Configuration](#production-configuration)

### Step 8: Verify Installation

Visit these URLs:
- Dashboard: http://localhost:8000/streamflow/
- Admin: http://localhost:8000/admin/
- API Docs: http://localhost:8000/api/v1/docs/

---

## Manual Deployment

If you prefer manual control:

### 1. Install System Dependencies
```bash
sudo apt-get update
sudo apt-get install -y \
    postgresql-16 postgresql-16-postgis-3 \
    redis-server \
    gdal-bin libgdal-dev python3-gdal \
    python3-dev python3-pip python3-venv \
    nginx  # Optional for production
```

### 2. Setup Python Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Database
```bash
# Create user and database
sudo -u postgres psql <<EOF
CREATE USER streamflow_user WITH PASSWORD 'secure_password';
CREATE DATABASE streamflow_db OWNER streamflow_user;
\c streamflow_db
CREATE EXTENSION postgis;
CREATE EXTENSION postgis_topology;
GRANT ALL PRIVILEGES ON DATABASE streamflow_db TO streamflow_user;
EOF
```

### 4. Configure Environment
```bash
cp .env.example .env
# Edit .env with your settings
```

### 5. Run Migrations
```bash
python manage.py migrate
```

### 6. Collect Static Files
```bash
python manage.py collectstatic --noinput
```

### 7. Load Station Data
```bash
# Load master station list
python manage.py load_master_stations

# Sync active stations
python manage.py sync_stations

# Create RFC mappings
python manage.py populate_station_mappings

# Optional: Import BC stations
python manage.py import_bc_stations
```

### 8. Setup Pull Configurations

Log in to Django admin at http://localhost:8000/admin/ and create PullConfiguration objects, or use the `deploy.py` script for automated setup.

---

## Post-Deployment

### Optional: Setup Raster Data

If using Google Earth Engine for satellite raster data:

```bash
# Setup GEE datasets
python manage.py setup_raster_datasets

# Setup spatial extents
python manage.py setup_spatial_extents

# Test GEE connection
python manage.py test_gee_connection
```

**Required GEE environment variables:**
```bash
EARTHDATA_USERNAME=your-earthdata-username
EARTHDATA_PASSWORD=your-earthdata-password
GEE_PROJECT=your-gee-project-id
```

### Test Data Pulls

```bash
# Test USGS pull
python manage.py test_usgs_pull --station 12345678

# Test NOAA RFC pull
python manage.py test_noaa_pull --station PTRO3

# Test Environment Canada pull
python manage.py test_canada_pull --station 08AB001
```

### Run Historical Backfill (One-Time)

The deployment script creates **two** one-time historical backfill configurations:

#### 1. HUC 17 Historical Backfill (Pacific Northwest)
- **Stations**: ~2,890 USGS stations
- **Coverage**: Oregon, Washington, Idaho portions
- **Status**: Enabled by default
- **Use case**: Regional PNW focus

#### 2. HUC 14-18 Historical Backfill (Western US)
- **Stations**: ~5,394 USGS stations total
- **Coverage**: 
  - HUC 14: Upper Colorado River Basin
  - HUC 15: Lower Colorado River Basin  
  - HUC 16: Great Basin
  - HUC 17: Pacific Northwest
  - HUC 18: California
- **Status**: Disabled by default (enable when ready)
- **Use case**: Comprehensive Western US coverage

**Important Notes:**
- These are **one-time operations** that can take several hours to days
- Pull data from earliest available (~1900s for some stations) to present
- Estimated data volume per configuration:
  - **HUC 17**: ~30-50 million observations (5-15 GB)
  - **HUC 14-18**: ~80-150 million observations (15-40 GB)
- The `replace` strategy prevents duplicates on subsequent runs

**To run HUC 17 backfill:**

1. **Find the configuration:**
```bash
python manage.py shell
>>> from apps.streamflow.models import PullConfiguration
>>> config = PullConfiguration.objects.get(name__contains="HUC 17")
>>> print(f"ID: {config.id}, Enabled: {config.is_enabled}")
>>> exit()
```

2. **Run the backfill task:**
```bash
# Via Celery task (recommended)
python manage.py shell
>>> from src.acquisition.tasks import pull_usgs_data
>>> config_id = <ID>  # Replace with actual ID from step 1
>>> result = pull_usgs_data.delay(config_id)
>>> print(f"Task ID: {result.id}")
>>> exit()
```

3. **Monitor progress:**
```bash
# Watch Celery logs
tail -f logs/celery-worker.log

# Or check database
python manage.py shell
>>> from apps.streamflow.models import DischargeObservation, DataPullLog
>>> print(f"Total observations: {DischargeObservation.objects.count():,}")
>>> 
>>> # Check recent pull logs
>>> from apps.streamflow.models import DataPullLog
>>> logs = DataPullLog.objects.filter(configuration__name__contains="HUC 17").order_by('-start_time')[:5]
>>> for log in logs:
...     print(f"{log.start_time}: {log.status} - {log.records_processed:,} records")
```

4. **Disable after completion:**
```bash
python manage.py shell
>>> config = PullConfiguration.objects.get(name__contains="HUC 17")
>>> config.is_enabled = False
>>> config.save()
>>> print("HUC 17 backfill disabled")
>>> exit()
```

**To run HUC 14-18 backfill (larger operation):**

This configuration is **disabled by default**. Only enable after HUC 17 completes successfully.

1. **Enable the configuration:**
```bash
python manage.py shell
>>> config = PullConfiguration.objects.get(name__contains="HUC 14-18")
>>> config.is_enabled = True
>>> config.save()
>>> print(f"ID: {config.id} - Enabled")
>>> exit()
```

2. **Run and monitor** (same process as HUC 17 above)

3. **Disable after completion** (same process as HUC 17 above)

**Performance Tips:**
- Start with **HUC 17** to test the process
- Run during off-peak hours
- Monitor database disk space:
  ```bash
  df -h | grep postgres
  # Ensure 50-100GB available for HUC 14-18
  ```
- If issues occur, the `replace` strategy allows safe re-runs
- Consider running HUC regions individually if needed (create separate configs)

---

## Production Configuration

### Gunicorn Setup

Create `/etc/systemd/system/streamflow.service`:

```ini
[Unit]
Description=StreamFlow DataOps Gunicorn
After=network.target

[Service]
User=streamflow
Group=www-data
WorkingDirectory=/home/streamflow/streamflow-app
Environment="PATH=/home/streamflow/streamflow-app/venv/bin"
ExecStart=/home/streamflow/streamflow-app/venv/bin/gunicorn \
    --workers 4 \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    --access-logfile /var/log/streamflow/access.log \
    --error-logfile /var/log/streamflow/error.log \
    config.wsgi:application

[Install]
WantedBy=multi-user.target
```

### Celery Worker Service

Create `/etc/systemd/system/streamflow-celery.service`:

```ini
[Unit]
Description=StreamFlow Celery Worker
After=network.target redis.target

[Service]
Type=forking
User=streamflow
Group=www-data
WorkingDirectory=/home/streamflow/streamflow-app
Environment="PATH=/home/streamflow/streamflow-app/venv/bin"
ExecStart=/home/streamflow/streamflow-app/venv/bin/celery -A config worker \
    --loglevel=info \
    --logfile=/var/log/streamflow/celery-worker.log \
    --pidfile=/var/run/streamflow/celery-worker.pid

[Install]
WantedBy=multi-user.target
```

### Celery Beat Service

Create `/etc/systemd/system/streamflow-celery-beat.service`:

```ini
[Unit]
Description=StreamFlow Celery Beat
After=network.target redis.target

[Service]
Type=simple
User=streamflow
Group=www-data
WorkingDirectory=/home/streamflow/streamflow-app
Environment="PATH=/home/streamflow/streamflow-app/venv/bin"
ExecStart=/home/streamflow/streamflow-app/venv/bin/celery -A config beat \
    --loglevel=info \
    --logfile=/var/log/streamflow/celery-beat.log \
    --pidfile=/var/run/streamflow/celery-beat.pid

[Install]
WantedBy=multi-user.target
```

### Nginx Configuration

Create `/etc/nginx/sites-available/streamflow`:

```nginx
upstream streamflow_app {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    client_max_body_size 100M;

    location /static/ {
        alias /home/streamflow/streamflow-app/staticfiles/;
        expires 30d;
    }

    location / {
        proxy_pass http://streamflow_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Enable Services

```bash
# Create log directory
sudo mkdir -p /var/log/streamflow
sudo chown streamflow:www-data /var/log/streamflow

# Create PID directory
sudo mkdir -p /var/run/streamflow
sudo chown streamflow:www-data /var/run/streamflow

# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable streamflow streamflow-celery streamflow-celery-beat
sudo systemctl start streamflow streamflow-celery streamflow-celery-beat

# Enable and restart nginx
sudo ln -s /etc/nginx/sites-available/streamflow /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### SSL with Let's Encrypt

```bash
# Install certbot
sudo apt-get install -y certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Auto-renewal is configured automatically
```

---

## Troubleshooting

### Database Connection Errors

```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Test connection
psql -h localhost -U streamflow_user -d streamflow_db

# Check PostGIS
psql streamflow_db -c "SELECT PostGIS_Version();"
```

### Redis Connection Errors

```bash
# Check Redis status
sudo systemctl status redis-server

# Test connection
redis-cli ping
# Should return: PONG

# Check if Redis is listening
sudo netstat -tlnp | grep 6379
```

### GDAL Import Errors

```bash
# Check GDAL installation
gdalinfo --version

# Reinstall Python GDAL matching system version
pip uninstall gdal
pip install gdal==$(gdal-config --version)

# Test import
python -c "from osgeo import gdal; print(gdal.__version__)"
```

### Celery Not Running

```bash
# Check Celery worker
celery -A config inspect active

# Check Redis connection from Python
python -c "import redis; r=redis.from_url('redis://localhost:6379/0'); print(r.ping())"

# View Celery logs
tail -f /var/log/streamflow/celery-worker.log
```

### Static Files Not Loading

```bash
# Recollect static files
python manage.py collectstatic --noinput --clear

# Check permissions
sudo chown -R streamflow:www-data staticfiles/
sudo chmod -R 755 staticfiles/

# Verify Nginx configuration
sudo nginx -t
sudo systemctl restart nginx
```

### Database Migrations Failing

```bash
# Check migration status
python manage.py showmigrations

# Fake migrations if needed (careful!)
python manage.py migrate --fake-initial

# Or start fresh (WARNING: destroys data)
python manage.py migrate apps.streamflow zero
python manage.py migrate
```

### GEE Authentication Errors

```bash
# Check credentials file exists
ls rtmaandsma-*.json

# Test GEE connection
python manage.py test_gee_connection

# Verify Earthdata credentials
curl -u "$EARTHDATA_USERNAME:$EARTHDATA_PASSWORD" https://urs.earthdata.nasa.gov/api/users/find_or_create_token
```

---

## Monitoring

### Check Service Status

```bash
# All services
sudo systemctl status streamflow streamflow-celery streamflow-celery-beat nginx

# Check logs
sudo journalctl -u streamflow -f
sudo tail -f /var/log/streamflow/*.log
```

### Database Health

```bash
# Connect to database
psql -h localhost -U streamflow_user -d streamflow_db

# Check table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

# Check station count
SELECT COUNT(*) FROM stations WHERE is_active=true;

# Check observation count
SELECT COUNT(*) FROM discharge_observations;
```

### Celery Monitoring

```bash
# Install Flower (optional web monitor)
pip install flower

# Run Flower
celery -A config flower --port=5555

# Access at http://localhost:5555
```

---

## Backup & Restore

### Database Backup

```bash
# Full backup
pg_dump -h localhost -U streamflow_user streamflow_db > backup_$(date +%Y%m%d).sql

# Compressed backup
pg_dump -h localhost -U streamflow_user streamflow_db | gzip > backup_$(date +%Y%m%d).sql.gz

# Backup to directory format (parallel)
pg_dump -h localhost -U streamflow_user -Fd streamflow_db -j 4 -f backup_$(date +%Y%m%d)
```

### Database Restore

```bash
# From SQL file
psql -h localhost -U streamflow_user streamflow_db < backup_20260204.sql

# From compressed file
gunzip < backup_20260204.sql.gz | psql -h localhost -U streamflow_user streamflow_db

# From directory format
pg_restore -h localhost -U streamflow_user -d streamflow_db -j 4 backup_20260204/
```

---

## Updates & Maintenance

### Application Updates

```bash
# Pull latest code
cd /home/streamflow/streamflow-app
git pull origin main

# Activate virtual environment
source venv/bin/activate

# Update dependencies
pip install -r requirements.txt --upgrade

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Restart services
sudo systemctl restart streamflow streamflow-celery streamflow-celery-beat
```

### Regular Maintenance

**Daily:**
- Monitor Celery task success rates
- Check disk space usage
- Review error logs

**Weekly:**
- Review and archive old logs
- Check database performance
- Update station lists if needed

**Monthly:**
- Security patches and updates
- Database vacuum and analyze
- Review and optimize queries

---

## Additional Resources

- **Main README**: [../README.md](../README.md)
- **API Documentation**: http://localhost:8000/api/v1/docs/
- **Environment Canada Guide**: [QUICK_START_EC.md](QUICK_START_EC.md)
- **Earthdata Setup**: [EARTHDATA_SETUP.md](EARTHDATA_SETUP.md)
- **Production Monitoring**: [PRODUCTION_MONITORING.md](PRODUCTION_MONITORING.md)
- **Known Issues**: [0. Issues](0.%20Issues)

---

## Support

For issues or questions:
1. Check [Troubleshooting](#troubleshooting) section
2. Review [0. Issues](0.%20Issues) for known problems
3. Check deployment script output: `python scripts/deploy.py --dry-run`
4. Create an issue in the repository

---

**Last Updated**: February 2026  
**Version**: 1.0.0
