# Gridded Data Frontend - Testing Guide

## Quick Start

### 1. Start the Development Server
```bash
cd /home/mrguy/Proj/streamflow-dataOps/streamflow-dataOps
python manage.py runserver
```

### 2. Access Pages

**Dashboard:**
- URL: http://localhost:8000/
- Look for purple "Gridded Data" cards at bottom

**Gridded Data List:**
- URL: http://localhost:8000/gridded-data/
- Navbar: Click "Gridded Data"
- Test filters: dataset, variable, extent, date range
- Test pagination if >50 layers exist

**Gridded Data Detail:**
- URL: http://localhost:8000/gridded-data/<layer_id>/
- Click "View" button on any layer in list
- Verify map displays extent correctly
- Check temperature conversion shows for Kelvin units

**Configuration List:**
- URL: http://localhost:8000/gridded-configurations/
- Navbar: Click "Gridded Configurations"
- Test "New Configuration" button
- Test "Trigger Pull" button (requires Celery running)

**Create Configuration:**
- URL: http://localhost:8000/gridded-configurations/new/
- Test form validation (require 1+ variables, 1+ extents)
- Select RTMA or SMAP dataset
- Choose variables and extents
- Set schedule settings
- Submit and verify redirect

**Edit Configuration:**
- URL: http://localhost:8000/gridded-configurations/<config_id>/edit/
- Verify form loads with existing data
- Make changes and save
- Verify updates applied

**Configuration Detail:**
- URL: http://localhost:8000/gridded-configurations/<config_id>/
- View configuration settings
- View recent execution logs
- Test manual pull trigger

**Delete Configuration:**
- URL: http://localhost:8000/gridded-configurations/<config_id>/delete/
- Verify confirmation page
- Test cancel and delete buttons

## Automated Test Commands

### Check for Errors
```bash
python manage.py check
```

### Run Migrations (if needed)
```bash
python manage.py makemigrations
python manage.py migrate
```

### Create Test Configuration (CLI)
```bash
python manage.py create_raster_config \
    --name "Test RTMA Pull" \
    --dataset RTMA \
    --variables temperature precipitation \
    --extents HUC_17 \
    --frequency 6 \
    --lookback 7
```

### Trigger Manual Pull (CLI)
```bash
python manage.py pull_raster_data <config_id>
```

### Start Celery Worker (for manual pulls from UI)
```bash
celery -A config worker -l info
```

## Test Checklist

### Basic Functionality
- [ ] Dashboard shows gridded data cards
- [ ] Dashboard counts are correct
- [ ] Navbar links navigate to correct pages
- [ ] List view loads without errors
- [ ] Empty state shows when no data
- [ ] Filters work and update URL params
- [ ] Pagination preserves filter params
- [ ] Detail view loads with layer data
- [ ] Map displays and shows extent correctly
- [ ] Temperature conversion shows (if Kelvin)

### Configuration CRUD
- [ ] Create form loads
- [ ] Form validation works (1+ var, 1+ extent required)
- [ ] Create submits successfully
- [ ] List shows new configuration
- [ ] Edit form loads with existing data
- [ ] Edit submits and updates
- [ ] Detail view shows configuration
- [ ] Detail view shows execution logs
- [ ] Delete confirmation loads
- [ ] Delete works and redirects

### Manual Pull
- [ ] Trigger button shows on config list
- [ ] Trigger button shows on config detail
- [ ] Trigger creates Celery task (check worker logs)
- [ ] Success message shows with task ID
- [ ] Log entry created in database
- [ ] New layers appear after successful pull

### UI/UX
- [ ] Purple theme consistent throughout
- [ ] Icons display correctly (Font Awesome)
- [ ] Bootstrap styling consistent
- [ ] Responsive on mobile (shrink browser)
- [ ] No console errors (F12 → Console)
- [ ] Buttons and links have hover effects
- [ ] Form fields have help text
- [ ] Error messages display correctly

## Common Issues

### Issue: "No module named 'apps.streamflow.models'"
**Fix:** Check INSTALLED_APPS in settings.py includes 'apps.streamflow'

### Issue: Template not found
**Fix:** Run `python manage.py collectstatic` if using static server

### Issue: Import error for RasterLayer
**Fix:** Ensure raster models exist (run migrations)

### Issue: Celery task fails
**Fix:** 
1. Check Celery worker is running
2. Check Redis/RabbitMQ is running
3. Check GEE credentials configured
4. View worker logs for error details

### Issue: Map doesn't display
**Fix:**
1. Check browser console for JavaScript errors
2. Verify Leaflet CDN is accessible
3. Check bbox data exists in context

### Issue: Temperature conversion doesn't show
**Fix:**
1. Verify `{% load raster_filters %}` at top of template
2. Check variable.unit is 'K'
3. Check templatetags/__init__.py exists

## Database Queries for Testing

### Check layer count
```python
from apps.streamflow.models import RasterLayer
RasterLayer.objects.count()
```

### Check today's layers
```python
from django.utils import timezone
from apps.streamflow.models import RasterLayer
today = timezone.now().replace(hour=0, minute=0, second=0)
RasterLayer.objects.filter(created_at__gte=today).count()
```

### Check configurations
```python
from apps.streamflow.models import RasterPullConfiguration
RasterPullConfiguration.objects.all()
```

### Check recent logs
```python
from apps.streamflow.models import RasterPullLog
RasterPullLog.objects.order_by('-started_at')[:10]
```

### Create test layer (if no data exists)
```python
from apps.streamflow.models import RasterLayer, RasterVariable, RasterDataset, SpatialExtent
from django.contrib.gis.geos import Polygon
from django.utils import timezone
import os

# Get or create dataset
dataset, _ = RasterDataset.objects.get_or_create(
    name='RTMA',
    defaults={'description': 'Test dataset', 'is_active': True}
)

# Get or create variable
variable, _ = RasterVariable.objects.get_or_create(
    dataset=dataset,
    name='temperature',
    defaults={'unit': 'K', 'description': 'Air temperature'}
)

# Get or create extent
bbox = Polygon.from_bbox((-125, 32, -110, 42))
extent, _ = SpatialExtent.objects.get_or_create(
    name='HUC_17',
    defaults={'description': 'Test extent', 'bbox': bbox}
)

# Create test layer
layer = RasterLayer.objects.create(
    variable=variable,
    extent=extent,
    timestamp=timezone.now(),
    date=timezone.now().date(),
    file_path=os.path.join(settings.RASTER_DATA_DIR, 'test.tif'),
    resolution_m=2500.0,
    width=100,
    height=100,
    min_value=273.15,  # 0°C
    max_value=303.15,  # 30°C
    mean_value=288.15, # 15°C
    std_dev=5.0,
    is_valid=True
)

print(f"Created test layer: {layer.id}")
```

## Next Steps After Testing

1. **Performance Testing**
   - Load 1000+ layers and test list performance
   - Test filtering with large datasets
   - Check pagination speed

2. **Security Review**
   - Verify CSRF tokens on all forms
   - Check SQL injection prevention (Django ORM handles this)
   - Test permissions if auth added

3. **Documentation**
   - Add screenshots to README
   - Document API integration
   - Create user guide

4. **Monitoring**
   - Set up logging for pull failures
   - Add alerting for stale data
   - Monitor disk space (raster files)

5. **Enhancements**
   - Add data export (GeoTIFF download)
   - Add layer comparison tool
   - Add time series visualization
   - Add bulk operations
