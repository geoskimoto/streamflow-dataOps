# PullConfiguration Tests

This test suite verifies the PullConfiguration system for scheduled data collection.

## Test Organization

### Data Collection Tests (✅ All Pass)

These tests verify that data can be successfully collected from external APIs and stored in the database:

**USGSDailyMeanDataCollectionTests**
- `test_usgs_daily_mean_collection`: Verifies USGS daily mean API calls work correctly
- `test_daily_mean_observation_storage`: Verifies daily mean data can be stored in DischargeObservation table

**USGSRealtimeDataCollectionTests**
- `test_usgs_realtime_collection`: Verifies USGS real-time 15-minute API calls work correctly
- `test_realtime_observation_storage`: Verifies real-time data can be stored in DischargeObservation table

**NOAARFCForecastCollectionTests**
- `test_noaa_short_forecast_collection`: Verifies NOAA short-range (18hr) forecast API calls
- `test_noaa_medium_forecast_collection`: Verifies NOAA medium-range (10-day) forecast API calls
- `test_forecast_run_storage`: Verifies forecast data can be stored in ForecastRun table
- `test_append_strategy_preserves_historical_runs`: Verifies append strategy preserves historical forecast runs

### Deployment Verification Tests (⚠️ Production Only)

These tests verify that configurations exist in the database. They will FAIL in test database and PASS in production:

**PullConfigurationDeploymentTests**
- `test_nwrfc_short_forecast_config_exists`: Verifies NWRFC short-range config deployed
- `test_nwrfc_medium_forecast_config_exists`: Verifies NWRFC medium-range config deployed
- `test_pnw_daily_mean_config_exists`: Verifies PNW daily mean config deployed
- `test_pnw_realtime_config_exists`: Verifies PNW real-time config deployed
- `test_all_configs_have_valid_stations`: Verifies all station references are valid
- `test_no_duplicate_stations_within_config`: Verifies no duplicate station assignments

**ConfigurationIntegrationTests**
- `test_all_configs_have_unique_names`: Verifies unique configuration names
- `test_schedule_values_are_valid_cron`: Verifies cron expressions are valid
- `test_data_strategies_match_data_types`: Verifies strategies match data types (forecast→append, realtime→overwrite)
- `test_nwrfc_stations_are_noaa_agency`: Verifies NWRFC stations have NOAA_RFC agency
- `test_pnw_stations_are_usgs_agency`: Verifies PNW stations have USGS agency

## Running Tests

### Run Data Collection Tests (Use These for CI/CD)
```bash
python manage.py test tests.test_pull_configurations.USGSDailyMeanDataCollectionTests \
                       tests.test_pull_configurations.USGSRealtimeDataCollectionTests \
                       tests.test_pull_configurations.NOAARFCForecastCollectionTests \
                       -v 2 --keepdb
```

### Verify Production Deployment
```bash
# This will fail in test database - only use for production verification
python manage.py shell -c "
from apps.streamflow.models import PullConfiguration
configs = PullConfiguration.objects.all()
print(f'Deployed Configurations: {configs.count()}')
for config in configs:
    station_count = config.configuration_stations.count()
    print(f'  ✓ {config.name}: {station_count} stations')
"
```

## Deployed Configurations

### NWRFC Forecasts (78 stations)
1. **NWRFC Short-Range Forecast Collection**
   - Source: NOAA_RFC
   - Type: forecast (short - 18 hours)
   - Strategy: append (preserves historical runs)
   - Schedule: Daily at 8:30 AM PST (16:30 UTC)

2. **NWRFC Medium-Range Forecast Collection**
   - Source: NOAA_RFC
   - Type: forecast (medium - 10 days)
   - Strategy: append (preserves historical runs)
   - Schedule: Daily at 8:30 AM PST (16:30 UTC)

### PNW USGS Observations (2,890 stations)
3. **PNW USGS Daily Mean Discharge**
   - Source: USGS
   - Type: observed (daily mean)
   - Strategy: replace (historical data doesn't change)
   - Schedule: Daily at 9:00 AM PST (17:00 UTC)

4. **PNW USGS Real-time 7-Day Window**
   - Source: USGS
   - Type: realtime (15-minute instantaneous)
   - Strategy: overwrite (rolling 7-day window for storage management)
   - Schedule: Every 4 hours

## Test Results

### Latest Run (2026-02-03)

**Data Collection Tests**: ✅ 8/8 PASS
- All USGS daily mean tests pass
- All USGS real-time tests pass
- All NOAA RFC forecast tests pass

**Integration Tests**: ✅ 3/5 PASS (2 expected failures in test DB)
- Cron validation: ✅ PASS
- Data strategy validation: ✅ PASS
- Unique names: ✅ PASS
- NWRFC agency check: ⚠️ Expected failure (no configs in test DB)
- PNW agency check: ⚠️ Expected failure (no configs in test DB)

## Notes

- The deployment tests expect configs to exist in the database, so they will fail in the test database
- For CI/CD pipelines, only run the data collection tests
- Use `scripts/deploy.py` to recreate all production configurations
- The append strategy for forecasts is critical for ML training on forecast error patterns
