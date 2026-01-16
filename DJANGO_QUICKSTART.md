# Django Quick Start Guide

## Overview
This guide helps you get started with the Django-based streamflow DataOps system after the migration from SQLAlchemy.

## Initial Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file in the project root:

```env
# Database Configuration
DB_ENGINE=sqlite  # or 'postgresql'
DB_NAME=streamflow_db
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Celery Configuration
CELERY_BROKER_URL=redis://localhost:6379/0

# Django Secret Key (change for production!)
SECRET_KEY=your-secret-key-here
```

### 3. Run Migrations
```bash
python manage.py migrate
```

### 4. Create Superuser
```bash
python manage.py createsuperuser
```

### 5. Load Master Station Data (Optional)
```bash
python manage.py shell
>>> from apps.streamflow.models import MasterStation
>>> # Import your CSV data here
```

## Running the Application

### Development Server
```bash
python manage.py runserver
```

Access at: http://localhost:8000

### Django Admin
After creating a superuser, access the admin interface at:
http://localhost:8000/admin

**Available Admin Interfaces:**
- Stations
- Discharge Observations
- Forecast Runs
- Pull Configurations
- Pull Configuration Stations
- Data Pull Logs
- Pull Station Progress
- Master Stations
- Station Mappings

### Celery Worker (for background tasks)
```bash
celery -A config.celery worker --loglevel=info
```

### Celery Beat (for scheduled tasks)
```bash
celery -A config.celery beat --loglevel=info
```

### Combined Celery Worker + Beat
```bash
celery -A config.celery worker --beat --loglevel=info
```

## Django Shell

Access the Django shell for interactive Python:
```bash
python manage.py shell
```

Example usage:
```python
from apps.streamflow.models import Station, PullConfiguration
from django.utils import timezone

# Create a station
station = Station.objects.create(
    station_number="01646500",
    name="POTOMAC RIVER NEAR WASH, DC LITTLE FALLS PUMP STA",
    agency="USGS",
    latitude=38.94977778,
    longitude=-77.12888889,
    state="DC"
)

# Query stations
usgs_stations = Station.objects.filter(agency="USGS", is_active=True)

# Get discharge observations for a station
observations = station.discharge_observations.filter(
    observed_at__gte=timezone.now() - timezone.timedelta(days=7)
).order_by('-observed_at')[:10]
```

## Database Management

### Create New Migrations
After changing models:
```bash
python manage.py makemigrations
```

### Apply Migrations
```bash
python manage.py migrate
```

### Show Migrations
```bash
python manage.py showmigrations
```

### Rollback Migration
```bash
python manage.py migrate streamflow 0001  # Roll back to migration 0001
```

## Working with Models

### Import Models
```python
from apps.streamflow.models import (
    Station,
    DischargeObservation,
    ForecastRun,
    PullConfiguration,
    PullConfigurationStation,
    DataPullLog,
    PullStationProgress,
    MasterStation,
    StationMapping,
)
```

### Common Queries

#### Get all active USGS stations
```python
stations = Station.objects.filter(agency="USGS", is_active=True)
```

#### Get latest discharge observations
```python
from django.utils import timezone
from datetime import timedelta

recent_obs = DischargeObservation.objects.filter(
    observed_at__gte=timezone.now() - timedelta(days=1)
).select_related('station').order_by('-observed_at')
```

#### Get pull configurations with their stations
```python
configs = PullConfiguration.objects.prefetch_related(
    'configuration_stations'
).filter(is_enabled=True)

for config in configs:
    print(f"{config.name}: {config.configuration_stations.count()} stations")
```

#### Check Smart Append Logic progress
```python
progress = PullStationProgress.objects.filter(
    configuration_id=1
).select_related('configuration')

for prog in progress:
    print(f"{prog.station_number}: Last pull = {prog.last_successful_pull_date}")
```

## Working with Celery Tasks

### Define a Task
Create tasks in `apps/streamflow/tasks.py`:

```python
from celery import shared_task
from apps.streamflow.models import Station

@shared_task
def update_station_metadata(station_id):
    station = Station.objects.get(id=station_id)
    # Do something with station
    return f"Updated {station.station_number}"
```

### Call a Task
```python
from apps.streamflow.tasks import update_station_metadata

# Call asynchronously
result = update_station_metadata.delay(station_id=1)

# Call synchronously (for testing)
result = update_station_metadata(station_id=1)
```

### Schedule with Celery Beat
Use Django admin to create periodic tasks at:
http://localhost:8000/admin/django_celery_beat/

Or programmatically:
```python
from django_celery_beat.models import PeriodicTask, IntervalSchedule
import json

# Create interval schedule (every 6 hours)
schedule, created = IntervalSchedule.objects.get_or_create(
    every=6,
    period=IntervalSchedule.HOURS,
)

# Create periodic task
PeriodicTask.objects.create(
    interval=schedule,
    name='Pull USGS data every 6 hours',
    task='apps.streamflow.tasks.execute_pull_configuration',
    args=json.dumps([1]),  # config_id=1
)
```

## Next Development Steps

### 1. Update Acquisition Layer
Convert these files to use Django ORM:
- `src/acquisition/data_processor.py` - Use Django models instead of repositories
- `src/acquisition/smart_append.py` - Use Django QuerySet instead of SQLAlchemy
- `src/acquisition/tasks.py` - Import from `apps.streamflow.models`

### 2. Create Views
Create views in `apps/streamflow/views.py`:
- List pull configurations
- Create/edit pull configuration
- View execution logs
- Trigger manual pull

### 3. Create URLs
Add URLs to `apps/streamflow/urls.py` and include in `config/urls.py`

### 4. Create Templates
Create templates in `apps/streamflow/templates/streamflow/`:
- `base.html` - Base template with Bootstrap
- `configuration_list.html` - List all configs
- `configuration_form.html` - Create/edit form
- `configuration_detail.html` - View config details
- `log_list.html` - Execution logs

### 5. Update Tests
Convert tests to use Django's TestCase:
```python
from django.test import TestCase
from apps.streamflow.models import Station

class StationModelTest(TestCase):
    def setUp(self):
        self.station = Station.objects.create(
            station_number="01646500",
            name="Test Station",
            agency="USGS"
        )
    
    def test_station_creation(self):
        self.assertEqual(self.station.station_number, "01646500")
        self.assertTrue(self.station.is_active)
```

## Troubleshooting

### Import Errors
If you see `ModuleNotFoundError`, ensure:
1. You're in the project root directory
2. Virtual environment is activated (if using one)
3. All dependencies are installed: `pip install -r requirements.txt`

### Database Errors
- Check database configuration in `.env` file
- Run migrations: `python manage.py migrate`
- For PostgreSQL, ensure the database exists and credentials are correct

### Celery Connection Errors
- Ensure Redis is running: `redis-cli ping` should return `PONG`
- Check CELERY_BROKER_URL in settings

### Template Not Found
- Ensure templates are in `apps/streamflow/templates/streamflow/`
- Check TEMPLATES['DIRS'] in `config/settings.py`

## Resources

- [Django Documentation](https://docs.djangoproject.com/en/4.2/)
- [Django ORM Queries](https://docs.djangoproject.com/en/4.2/topics/db/queries/)
- [Celery Django Integration](https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html)
- [django-celery-beat](https://django-celery-beat.readthedocs.io/)
- [GeoDjango](https://docs.djangoproject.com/en/4.2/ref/contrib/gis/) - For future spatial data support

## Notes

- The original SQLAlchemy code is preserved in `archive/sqlalchemy_original/`
- Smart Append Logic is maintained through `PullStationProgress` model
- All 9 models have been migrated with full feature parity
- Django admin provides immediate UI for all models
