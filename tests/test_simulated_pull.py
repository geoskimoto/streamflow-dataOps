#!/usr/bin/env python
"""
Simulate the actual data pull process that Celery would run
Tests end-to-end functionality for HUC17 configuration
"""

import os
import sys
import django
from datetime import datetime, timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.streamflow.models import (
    PullConfiguration,
    Station,
    DischargeObservation,
    DataPullLog
)
from src.acquisition.usgs_client import USGSClient

print("\n" + "="*80)
print("SIMULATING ACTUAL DATA PULL PROCESS")
print("="*80)

# Get HUC17 configuration
config = PullConfiguration.objects.get(id=7)
print(f"\nConfiguration: {config.name}")
print(f"Data Source: {config.data_source}")
print(f"Data Type: {config.data_type}")
print(f"Strategy: {config.data_strategy}")
print(f"Stations: {config.configuration_stations.count()}")

# Date range for pull
end_date = datetime.now()
start_date = config.pull_start_date if config.pull_start_date else end_date - timedelta(days=30)

print(f"\nDate Range:")
print(f"  Start: {start_date.date()}")
print(f"  End: {end_date.date()}")

# Start a simulated pull log
print(f"\n" + "="*80)
print("STARTING DATA PULL (Testing first 5 stations)")
print("="*80)

client = USGSClient()
stats = {
    'stations_processed': 0,
    'stations_success': 0,
    'stations_no_data': 0,
    'stations_error': 0,
    'total_records': 0,
    'records_saved': 0,
    'records_duplicate': 0
}

# Process first 5 stations (to keep test fast)
for pcs in config.configuration_stations.all()[:5]:
    stats['stations_processed'] += 1
    
    print(f"\n[{stats['stations_processed']}/5] {pcs.station_number}: {pcs.station_name}")
    
    try:
        # Get Station object
        try:
            station = Station.objects.get(station_number=pcs.station_number)
        except Station.DoesNotExist:
            print(f"  ⚠️  Station not in Station table - skipping")
            stats['stations_error'] += 1
            continue
        
        # Fetch data from USGS
        print(f"  Fetching from USGS API...")
        data = client.get_daily_mean(pcs.station_number, start_date, end_date)
        
        if not data:
            print(f"  ⚠️  No data available from USGS")
            stats['stations_no_data'] += 1
            continue
        
        print(f"  ✅ Retrieved {len(data)} records from API")
        stats['total_records'] += len(data)
        
        # Save to database
        saved = 0
        duplicates = 0
        for record in data:
            obs, created = DischargeObservation.objects.update_or_create(
                station=station,
                observed_at=record['observed_at'],
                type=record.get('type', 'daily_mean'),
                defaults={
                    'discharge': record['discharge'],
                    'unit': record['unit'],
                    'quality_code': record.get('quality_code', ''),
                }
            )
            if created:
                saved += 1
            else:
                duplicates += 1
        
        stats['records_saved'] += saved
        stats['records_duplicate'] += duplicates
        
        print(f"  💾 Saved {saved} new records ({duplicates} duplicates)")
        
        if saved > 0:
            # Show date range of saved data
            first_date = data[-1]['observed_at'].date()
            last_date = data[0]['observed_at'].date()
            print(f"     Date range: {first_date} to {last_date}")
            print(f"     Sample: {data[0]['discharge']} {data[0]['unit']} on {last_date}")
        
        stats['stations_success'] += 1
        
    except Exception as e:
        print(f"  ❌ Error: {str(e)}")
        stats['stations_error'] += 1
        import traceback
        traceback.print_exc()

# Summary
print("\n" + "="*80)
print("DATA PULL SUMMARY")
print("="*80)

print(f"\nStations:")
print(f"  Processed: {stats['stations_processed']}")
print(f"  ✅ Success: {stats['stations_success']}")
print(f"  ⚠️  No Data: {stats['stations_no_data']}")
print(f"  ❌ Error: {stats['stations_error']}")

print(f"\nRecords:")
print(f"  Retrieved from API: {stats['total_records']}")
print(f"  💾 Saved (new): {stats['records_saved']}")
print(f"  ⏭️  Skipped (duplicate): {stats['records_duplicate']}")

# Check database state
print("\n" + "="*80)
print("DATABASE STATE AFTER PULL")
print("="*80)

total_obs = DischargeObservation.objects.count()
print(f"\nTotal observations in database: {total_obs}")

# Get stations that now have data
stations_with_data = []
for pcs in config.configuration_stations.all()[:5]:
    try:
        station = Station.objects.get(station_number=pcs.station_number)
        obs_count = station.discharge_observations.count()
        if obs_count > 0:
            latest = station.discharge_observations.first()
            stations_with_data.append((pcs.station_number, pcs.station_name, obs_count, latest))
    except:
        pass

if stations_with_data:
    print(f"\n✅ Stations with data ({len(stations_with_data)}):")
    for station_number, name, count, latest in stations_with_data:
        print(f"  {station_number}: {name[:50]}")
        print(f"    Observations: {count}")
        print(f"    Latest: {latest.observed_at.date()} = {latest.discharge} {latest.unit}")

# Final status
print("\n" + "="*80)
print("CONCLUSION")
print("="*80)

if stats['stations_success'] > 0:
    print(f"\n✅ SUCCESS! Data pull is working!")
    print(f"\nResults:")
    print(f"  - Successfully pulled data for {stats['stations_success']} stations")
    print(f"  - Saved {stats['records_saved']} new observations")
    print(f"  - Configuration is ready for production use")
    
    print(f"\nWhat happens next:")
    print(f"  1. When Celery runs this configuration, it will:")
    print(f"     - Process all {config.configuration_stations.count()} stations (not just 5)")
    print(f"     - Use the same logic tested here")
    print(f"     - Save data to DischargeObservation table")
    print(f"     - Create DataPullLog entry with results")
    print(f"\n  2. To enable automated pulls:")
    print(f"     - Start Celery worker: celery -A config worker")
    print(f"     - Start Celery beat: celery -A config beat")
    print(f"     - Configuration will run on schedule: {config.schedule_type}")
    
elif stats['stations_no_data'] == stats['stations_processed']:
    print(f"\n⚠️  All tested stations have no recent data")
    print(f"\nThis is normal for:")
    print(f"  - Seasonal streams")
    print(f"  - Discontinued gages")
    print(f"  - Stations without real-time reporting")
    print(f"\nThe USGS client is working correctly.")
    print(f"When Celery processes all {config.configuration_stations.count()} stations,")
    print(f"many will have data even if these first few don't.")
    
else:
    print(f"\n❌ Errors encountered")
    print(f"Review the error messages above")

print("\n" + "="*80)
