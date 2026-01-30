# Gridded Data Frontend Implementation

## Overview
Complete frontend UI implementation for raster/gridded data management in the Django web interface. This adds user-friendly pages for browsing, configuring, and managing Google Earth Engine (GEE) data pulls.

## Implementation Date
Created: 2024

## Features Implemented

### 1. Data Browsing
- **List View** (`/gridded-data/`)
  - Table with filters (dataset, variable, extent, date range)
  - Pagination (50 items per page)
  - Shows: timestamp, dataset, variable, extent, resolution, file size, statistics
  - Purple theme for visual distinction from timeseries data

- **Detail View** (`/gridded-data/<id>/`)
  - Layer metadata (dataset, variable, timestamp, extent, resolution, dimensions)
  - Statistics display (min, max, mean, std dev) with Kelvin→Fahrenheit conversion
  - Interactive Leaflet map showing spatial extent
  - Thumbnail display (if available)
  - API access information

### 2. Configuration Management
- **Configuration List** (`/gridded-configurations/`)
  - Table showing all raster pull configurations
  - Displays: name, dataset, variables, extents, schedule, last run, success rate
  - Success rate progress bars with color coding (green ≥80%, yellow ≥50%, red <50%)
  - Actions: view, edit, trigger manual pull

- **Create/Edit Form** (`/gridded-configurations/new/`, `/gridded-configurations/<id>/edit/`)
  - Basic Information: name, dataset, description
  - Data Selection: checkbox grids for variables and extents
  - Schedule Settings: enable/disable, frequency (hours), lookback period (days)
  - Processing Options: resampling method, compression, thumbnails, validation
  - Form validation requiring at least one variable and extent

- **Configuration Detail** (`/gridded-configurations/<id>/`)
  - Shows all configuration settings
  - Recent execution logs table (status, layers created, duration)
  - Trigger manual pull button
  - Edit and delete actions

- **Delete Confirmation** (`/gridded-configurations/<id>/delete/`)
  - Confirmation page with warning about data loss
  - Shows configuration name

### 3. Navigation Integration
- **Navbar Updates**
  - Added "Gridded Data" link (icon: fa-th)
  - Added "Gridded Configurations" link (icon: fa-layer-group)
  - Placed after "Logs" section
  - Active state highlighting

- **Dashboard Cards**
  - Purple-themed card showing total gridded data layers
  - Shows today's new layers count
  - Purple-themed card showing configuration count
  - Shows enabled configurations count
  - Links to list views

### 4. Template Filters
- **Temperature Conversion**
  - `kelvin_to_fahrenheit` - Converts K to °F: (K - 273.15) × 9/5 + 32
  - `kelvin_to_celsius` - Converts K to °C: K - 273.15
  - Auto-applies to temperature variables in statistics display
  
- **File Size Formatting**
  - `format_file_size` - Formats bytes to human-readable (e.g., "1.5 MB")

## Files Created

### Templates (6 files)
1. `apps/streamflow/templates/streamflow/gridded_data_list.html` (232 lines)
2. `apps/streamflow/templates/streamflow/gridded_data_detail.html` (258 lines)
3. `apps/streamflow/templates/streamflow/raster_config_list.html` (146 lines)
4. `apps/streamflow/templates/streamflow/raster_config_form.html` (237 lines)
5. `apps/streamflow/templates/streamflow/raster_config_detail.html` (169 lines)
6. `apps/streamflow/templates/streamflow/raster_config_confirm_delete.html` (51 lines)

### Template Tags (2 files)
1. `apps/streamflow/templatetags/__init__.py`
2. `apps/streamflow/templatetags/raster_filters.py` (95 lines)

## Files Modified

### Views
- `apps/streamflow/views.py`
  - Added 9 new view functions (lines ~1200-1432):
    - `gridded_data_list()` - List with filtering
    - `gridded_data_detail()` - Detail with map data
    - `raster_config_list()` - List with statistics
    - `raster_config_detail()` - Detail with logs
    - `raster_config_create()` - Create configuration
    - `raster_config_edit()` - Edit configuration
    - `raster_config_delete()` - Delete confirmation
    - `trigger_raster_pull()` - Manual pull trigger
  - Updated `dashboard()` view to include raster statistics

### Forms
- `apps/streamflow/forms.py`
  - Added `RasterPullConfigurationForm` class (lines ~280-302)
  - Fields: name, description, dataset, variables, extents, schedule settings, processing options
  - CheckboxSelectMultiple widgets for multi-select
  - Custom validation (at least one variable and extent required)

### URL Configuration
- `apps/streamflow/urls.py`
  - Added 8 new URL patterns (lines ~48-55):
    - Gridded data list and detail
    - Configuration CRUD operations
    - Manual pull trigger

### Navigation
- `templates/base.html`
  - Added two navbar links for gridded data and configurations

### Dashboard
- `apps/streamflow/templates/streamflow/dashboard.html`
  - Added two purple-themed cards for gridded data metrics

## Design Decisions

### Color Scheme
- **Purple (#6f42c1)** used throughout for visual distinction from blue (timeseries)
- Applied to: cards, badges, buttons, links, borders, icons

### Map Implementation
- **Leaflet 1.9.4** chosen for simplicity (vs complex GEE visualization)
- Shows extent as purple rectangle on OpenStreetMap base layer
- Auto-fits bounds to extent
- Marker with popup showing layer info

### Form Design
- Checkbox grids for multi-select (variables, extents)
- CSS Grid layout: `repeat(auto-fill, minmax(200px, 1fr))`
- Grouped into logical sections (4 cards)
- Help text for each field

### Terminology
- "Gridded Data" used throughout (not "Raster" or "GEE Data")
- Consistent with user preference

### Access Control
- All pages public (no login required)
- Matches existing timeseries pattern
- No download buttons (API-only data delivery)

## API Integration

### Data Access
- Detail page shows API endpoints:
  - Layer metadata: `/api/v1/raster-layers/<id>/`
  - Data array: `/api/v1/raster-layers/<id>/data/`
  - Thumbnail: `/api/v1/raster-layers/<id>/thumbnail/`

### Manual Pulls
- Trigger button calls `trigger_raster_pull()` view
- View uses Celery: `execute_raster_pull_task.delay(config.id)`
- Redirects to config detail with success message

## Technical Notes

### Model Queries
- Uses `select_related()` for efficient foreign key joins
- Annotates configurations with stats: `total_runs`, `successful_runs`, `last_run`
- Filters in list view: dataset, variable, extent, date range
- Success rate calculated: `(successful_runs / total_runs) * 100`

### Template Structure
- All extend `base.html`
- Use Bootstrap 5 classes
- Font Awesome icons throughout
- Consistent `.raster-card`, `.btn-raster`, `.raster-badge` classes

### Form Validation
- Django ModelForm with custom `clean()` method
- Validates at least one variable selected
- Validates at least one extent selected
- Shows validation errors above form

## Testing Checklist

- [ ] List view loads and displays layers
- [ ] Filters work (dataset, variable, extent, dates)
- [ ] Pagination works with filter preservation
- [ ] Detail view shows layer info and map
- [ ] Map displays extent correctly
- [ ] Temperature conversion shows for Kelvin units
- [ ] Configuration list shows all configs
- [ ] Create form validates and saves
- [ ] Edit form loads existing data and updates
- [ ] Manual pull trigger works (Celery task)
- [ ] Delete confirmation works
- [ ] Navbar links navigate correctly
- [ ] Dashboard cards show correct counts
- [ ] No console errors
- [ ] Responsive layout works on mobile

## Next Steps

1. **Test with Real Data**
   - Create a raster configuration
   - Trigger a pull
   - Verify layers appear in list
   - Check map visualization

2. **Potential Enhancements**
   - Add download buttons (if needed)
   - Add raster comparison tool
   - Add time series animation
   - Add advanced filtering
   - Add export to CSV/JSON
   - Add bulk operations

3. **Documentation**
   - Update user guide with gridded data section
   - Add screenshots
   - Document API endpoints

## Dependencies

- Django 4.2.7
- Bootstrap 5
- Font Awesome 6.4.0
- Leaflet 1.9.4
- Existing raster models (RasterLayer, RasterPullConfiguration, etc.)
- Celery for async task execution
- PostGIS for spatial queries

## Code Quality

- No linting errors
- Follows existing Django patterns
- Consistent naming conventions
- Comments where needed
- DRY principles (reusable classes)
- Responsive design
- Accessible (aria labels, semantic HTML)
