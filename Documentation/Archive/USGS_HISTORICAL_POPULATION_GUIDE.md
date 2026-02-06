# USGS Historical Data Population - Usage Guide

## Overview

The `populate_usgs_historical` command fetches complete historical discharge records for USGS stations. It's designed for one-time population of historical data, while PullConfiguration handles ongoing appends.

## Quick Start

```bash
# Populate all active stations in HUC 17 (Columbia River Basin)
python manage.py populate_usgs_historical --huc 17

# Populate stations in specific states
python manage.py populate_usgs_historical --state WA --state OR

# Populate specific stations
python manage.py populate_usgs_historical --station 14211720 --station 14105700

# Test first - dry run
python manage.py populate_usgs_historical --huc 17 --limit 5 --dry-run
```

## Command Options

### Selection Options
- `--huc CODE`: HUC code(s) to process (e.g., `--huc 17`). Repeatable.
- `--state CODE`: State code(s) (e.g., `--state WA`). Repeatable.
- `--station NUMBER`: Specific station number(s). Repeatable.
- `--include-inactive`: Include inactive stations (default: active only)

### Date Range Options
- `--start-date YYYY-MM-DD`: Override start date (default: station's record_start_date or 30 years ago)
- `--end-date YYYY-MM-DD`: Override end date (default: today)

### Behavior Options
- `--dry-run`: Show what would be done without fetching data
- `--limit N`: Process only first N stations (for testing)
- `--force`: Re-fetch even if station already populated
- `--batch-size N`: Records per bulk insert (default: 1000)
- `--delay SECONDS`: Wait between stations (default: 1.0)

## Examples

### Test with Small Subset
```bash
# Dry run first to see what would happen
python manage.py populate_usgs_historical --huc 17 --limit 5 --dry-run

# Test with short date range (7 days)
python manage.py populate_usgs_historical \
  --station 14211720 \
  --start-date 2026-01-20 \
  --end-date 2026-01-26
```

### Populate HUC 17 (Columbia River Basin)
```bash
# All active stations
python manage.py populate_usgs_historical --huc 17

# Include inactive stations
python manage.py populate_usgs_historical --huc 17 --include-inactive

# Custom date range
python manage.py populate_usgs_historical \
  --huc 17 \
  --start-date 2020-01-01 \
  --end-date 2025-12-31
```

### Populate by State
```bash
# Washington state
python manage.py populate_usgs_historical --state WA

# Multiple states
python manage.py populate_usgs_historical --state WA --state OR --state ID
```

### Force Re-population
```bash
# Re-fetch all data (useful if data was corrupted)
python manage.py populate_usgs_historical --huc 17 --force
```

## How It Works

### Station Discovery
1. Checks `Station` table first for matching stations
2. If none found, queries `MasterStation` table
3. Auto-creates `Station` records from `MasterStation` if needed
4. Filters by HUC, state, or specific station numbers
5. Excludes inactive stations by default (use `--include-inactive` to change)

### Data Population Logic
1. **Check if already populated**: Looks at `Station.historical_data_populated_at`
2. **Skip if complete**: If station has data and `--force` not used, checks completeness
3. **Fetch from USGS**: Uses `dataretrieval` library to get daily mean discharge
4. **Bulk insert**: Inserts records in batches (default 1000) with `ignore_conflicts=True`
5. **Update tracking**: Sets `historical_data_populated_at` and `historical_record_count`

### Gap Filling
- If station has existing data but isn't complete, fetches full date range
- `ignore_conflicts=True` prevents duplicate insertions
- Automatically fills gaps without re-fetching existing data

## Expected Performance

### Time Estimates
- **Per Station**: 1-10 seconds (depending on record length and USGS API)
- **100 Stations**: 2-15 minutes (with 1 second delay between stations)
- **Full HUC 17 (~2,890 stations)**: 1-8 hours

### Data Volume
- **Daily Mean**: ~365 records per year per station
- **30 Years**: ~11,000 records per station
- **HUC 17 Full**: 1-10 million records (many stations inactive/short records)

## Progress Tracking

### Database Fields
Each `Station` gets two tracking fields:
- `historical_data_populated_at`: Timestamp when last populated
- `historical_record_count`: Number of records fetched

### Resume Capability
If script crashes or is interrupted:
1. Stations with `historical_data_populated_at` set are skipped
2. Simply re-run the same command to resume
3. Use `--force` if you want to re-populate already completed stations

## Error Handling

### Common Failures
1. **No data returned**: Station inactive or no data for date range
2. **API timeout**: USGS API slow/unavailable (retries 3 times automatically)
3. **Invalid station**: Station doesn't exist in USGS system

### Graceful Shutdown
- Press `Ctrl+C` to interrupt
- Current station will finish, then script exits
- Progress is saved - simply re-run to resume

## Validation

### Check Data After Population
```python
python manage.py shell

from apps.streamflow.models import Station, DischargeObservation

# Check a specific station
station = Station.objects.get(station_number='14211720')
print(f"Populated: {station.historical_data_populated_at}")
print(f"Record count: {station.historical_record_count}")

# Check actual observations
obs = DischargeObservation.objects.filter(station=station)
print(f"DB records: {obs.count()}")
print(f"Date range: {obs.first().observed_at} to {obs.last().observed_at}")
```

### Check All Populated Stations
```python
from apps.streamflow.models import Station

populated = Station.objects.filter(
    historical_data_populated_at__isnull=False
).order_by('-historical_record_count')

print(f"Total populated stations: {populated.count()}")
for s in populated[:10]:
    print(f"{s.station_number}: {s.historical_record_count} records")
```

## Integration with PullConfiguration

### After Historical Population
1. Historical population gets complete records (one-time)
2. Create PullConfiguration for ongoing appends:
   ```python
   python manage.py shell
   
   from apps.streamflow.models import PullConfiguration, Station
   
   config = PullConfiguration.objects.create(
       name='HUC 17 Daily Updates',
       data_source='USGS',
       data_type='daily_mean',
       data_strategy='append',
       pull_start_date='2026-01-01',  # Start where historical ended
       is_enabled=True,
       schedule_type='daily'
   )
   
   # Add all HUC 17 stations
   stations = Station.objects.filter(huc_code__startswith='17', agency='USGS')
   for station in stations:
       config.configuration_stations.create(station_number=station.station_number)
   ```

3. PullConfiguration will use "Smart Append" to only fetch new data after the historical records

## Troubleshooting

### "No data returned from USGS"
- Station may be inactive for that date range
- Try checking USGS website: https://waterdata.usgs.gov/nwis/dv/?site_no={STATION_NUMBER}
- Many old/inactive stations in MasterStation won't have recent data

### Slow Performance
- Increase `--delay` if getting rate limited by USGS
- Decrease `--batch-size` if getting memory errors
- Use `--limit` to test with smaller subset first

### Memory Issues
- Reduce `--batch-size` (try 500 or 250)
- Process stations in chunks using `--limit` and specific station lists

## Best Practices

1. **Always test first**: Use `--dry-run` and `--limit 5` to validate
2. **Start with small date range**: Test with recent 30 days before full history
3. **Monitor first few stations**: Watch for errors/timeouts before running full job
4. **Run during off-peak**: Large populations best run overnight/weekend
5. **Check results**: Validate data quality on sample stations after completion

## Technical Details

### Data Type
- **Only daily mean** (`00060` parameter code)
- Instantaneous data not supported in this command
- Use PullConfiguration for 15-min realtime data

### Bulk Insert Strategy
- Uses Django's `bulk_create()` with `ignore_conflicts=True`
- Prevents duplicate records if same data fetched twice
- Unique constraint on `(station, observed_at, type)`

### USGS Client
- Uses `dataretrieval` library (official USGS Python package)
- Automatic retry with exponential backoff (3 attempts)
- Respects USGS API rate limits

## Files Created

- `apps/streamflow/migrations/0009_add_historical_tracking_to_station.py` - Database migration
- `src/acquisition/historical_population.py` - Service layer (~450 lines)
- `apps/streamflow/management/commands/populate_usgs_historical.py` - CLI (~250 lines)

## Next Steps

After running historical population:
1. **Verify data quality**: Check sample stations in Django admin
2. **Set up ongoing appends**: Create PullConfiguration for daily updates
3. **Enable Celery**: Configure automated pulls via Celery beat
4. **Monitor**: Check execution logs in Django admin

## Support

For issues or questions:
- Check execution logs in console output
- Review Django admin for Station and DischargeObservation records
- Use `--dry-run` to debug without writing data
- Check USGS website for station availability
