# Station Filter Improvements - Add Stations Page

## Date: January 26, 2025

## Summary
Enhanced the "Add Stations to Configuration" page with additional filtering capabilities to make it easier to find and select relevant stations.

## New Filters Added

### 1. ✅ Data Source / Agency Filter
**Purpose**: Filter stations by their data source/network
**Options**:
- All Agencies (default)
- USGS - United States Geological Survey
- NOAA_RFC - NOAA River Forecast Centers
- EC - Environment Canada

**Use Case**: Quickly filter to stations from a specific agency, especially useful when your configuration targets a specific data source.

### 2. ✅ River Forecast Center (RFC) Filter
**Purpose**: Filter NOAA RFC stations by their specific forecast center
**Options** (13 RFCs):
- NWRFC - Northwest RFC (covers Columbia River Basin)
- CNRFC - California-Nevada RFC
- CBRFC - Colorado Basin RFC
- MBRFC - Missouri Basin RFC
- NCRFC - North Central RFC
- NERFC - Northeast RFC
- MARFC - Middle Atlantic RFC
- OHRFC - Ohio RFC
- LMRFC - Lower Mississippi RFC
- ABRFC - Arkansas-Red Basin RFC
- WGRFC - West Gulf RFC
- SERFC - Southeast RFC
- APRFC - Alaska RFC

**Use Case**: Essential for targeting specific forecast regions. For example, to get Columbia River forecasts, select NWRFC.

**Note**: This filter only applies to stations with agency=NOAA_RFC. USGS and EC stations won't have RFC codes.

### 3. ✅ Existing Filters (Improved)
- **State/Province**: Renamed from "State" to clarify it includes Canadian provinces
- **HUC Code**: Enhanced placeholder to show you can enter partial HUCs (e.g., "17" for Columbia River Basin)
- **Search**: Search by station ID or name

## UI Enhancements

### Station Results Display
Each station now shows:
- **Station Number** (bold)
- **Agency Badge** (blue) - Shows USGS, NOAA_RFC, or EC
- **RFC Badge** (green) - Shows RFC code for NOAA stations (e.g., NWRFC)
- **Status Badges**: "Already Added" or "Selected"
- **Metadata**: State and HUC code

### Configuration Context Alert
Added an informational alert at the top that shows:
- The configuration's data source
- Helpful tips based on the data source type
- Example: For NOAA_RFC configs, suggests using the RFC filter

## Filter Combinations

### Example Use Cases

#### 1. Columbia River Basin Forecasts (NOAA RFC)
```
✓ Data Source: NOAA_RFC
✓ RFC: NWRFC
✓ HUC: 17
```
Result: All NOAA forecast stations in the Columbia River Basin (HUC 17) managed by Northwest RFC.

#### 2. California USGS Observations
```
✓ Data Source: USGS
✓ State: CA
```
Result: All USGS observation stations in California.

#### 3. Environment Canada Stations
```
✓ Data Source: EC
✓ State: BC (or other Canadian province)
```
Result: All Environment Canada stations in British Columbia.

#### 4. Specific RFC Across Multiple States
```
✓ Data Source: NOAA_RFC
✓ RFC: CNRFC
```
Result: All California-Nevada RFC stations (covers CA, NV, parts of OR and UT).

#### 5. By HUC Watershed
```
✓ HUC: 1701 (or any partial HUC)
```
Result: All stations in that hydrologic unit, regardless of agency.

## Technical Implementation

### Backend (Already Supported)
The `station_search_ajax` view in `apps/streamflow/views.py` already supports:
- `agency` parameter → filters by MasterStation.agency
- `rfc` parameter → filters by MasterStation.rfc_code
- `state` parameter → filters by MasterStation.state_code
- `huc` parameter → filters by MasterStation.huc_code (startswith)
- `q` parameter → searches station_number and station_name

### Frontend Updates
**File**: `apps/streamflow/templates/streamflow/add_stations.html`

1. Added two new filter dropdowns (agency and RFC)
2. Updated JavaScript `loadStations()` to include agency and rfc in query params
3. Updated station display to show agency and RFC badges
4. Updated clear filters to reset all filters including agency and RFC

### Database Fields Used
- `MasterStation.agency` - USGS, NOAA_RFC, or EC
- `MasterStation.rfc_code` - RFC identifier for NOAA stations
- `MasterStation.state_code` - State/province code
- `MasterStation.huc_code` - Hydrologic Unit Code
- `MasterStation.station_number` - Unique identifier
- `MasterStation.station_name` - Human-readable name

## Data Availability Notes

### Observations vs Forecasts
**Current Status**: Cannot directly filter by observation vs forecast capability yet.

**Reason**: The `MasterStation` model doesn't currently track which data types are available for each station. This information is inferred from:
- **USGS stations** → typically have observations (discharge, stage)
- **NOAA RFC stations** → typically have forecasts
- **EC stations** → typically have observations

**Future Enhancement**: Could add a `data_types_available` JSONField to MasterStation to explicitly track available data types per station.

### Station Counts (as of import)
- **USGS**: ~10,999 stations (observations)
- **NOAA RFC**: ~996 stations (forecasts)
  - NWRFC: 374 stations
  - CNRFC: 339 stations
  - CBRFC: 209 stations
  - MBRFC: 67 stations
  - Others: 7 stations
- **Environment Canada**: (to be imported)

## User Guidance

### Best Practices

1. **Start Broad, Then Narrow**: Begin with one or two filters, review results, then add more filters to refine.

2. **Match Configuration Source**: When adding stations to a configuration, consider filtering by the same data source as your configuration for consistency.

3. **Use HUC for Watershed Focus**: If you're interested in a specific watershed (like Columbia River = HUC 17), use the HUC filter to get all stations in that region regardless of agency.

4. **RFC for Regional Forecasts**: If you need forecast data for a specific region, use the RFC filter to see which forecast stations are available.

5. **State for Geographic Boundaries**: Use state filter when working within state/provincial boundaries or for regulatory reporting.

### Performance Tips

- The search loads 100 stations at a time
- Use "Load More" button to see additional results
- More specific filters = faster results
- "Select All Visible" button selects current page only (not all matching stations)

## Testing

To test the new filters:

1. Navigate to a configuration detail page
2. Click "Add Stations" button
3. Try different filter combinations:
   - Select "NOAA_RFC" in Data Source → should show ~996 NOAA stations
   - Select "NWRFC" in RFC filter → should show ~374 NWRFC stations
   - Add state filter → further refines results
   - Clear filters → resets all

## Related Files
- Frontend: `apps/streamflow/templates/streamflow/add_stations.html`
- Backend: `apps/streamflow/views.py` (station_search_ajax, add_stations_to_config)
- Models: `apps/streamflow/models.py` (MasterStation)
- Tests: `tests/test_frontend_ui.py`
