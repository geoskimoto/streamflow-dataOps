#!/usr/bin/env python
"""
Test actual USGS data pull for HUC17 configuration
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
    PullConfigurationStation,
    DischargeObservation
)
from src.acquisition.usgs_client import USGSClient

print("\n" + "="*80)
print("USGS DATA PULL TEST FOR HUC17 CONFIGURATION")
print("="*80)

# Get HUC17 configuration
config = PullConfiguration.objects.filter(name__icontains='HUC 17').first()
if not config:
    print("❌ No HUC17 configuration found!")
    sys.exit(1)

print(f"\nConfiguration: {config.name}")
print(f"Stations configured: {config.configuration_stations.count()}")

if config.configuration_stations.count() == 0:
    print("❌ No stations in configuration! Run: python manage.py add_huc17_stations")
    sys.exit(1)

# Test with first 3 stations
print("\n" + "="*80)
print("Testing data pull for first 3 stations")
print("="*80)

client = USGSClient()
end_date = datetime.now()
start_date = end_date - timedelta(days=7)

print(f"Date range: {start_date.date()} to {end_date.date()}")

test_stations = config.configuration_stations.all()[:3]
results = {
    'success': 0,
    'no_data': 0,
    'error': 0,
    'total_records': 0
}

for pcs in test_stations:
    print(f"\n{pcs.station_number}: {pcs.station_name}")
    print(f"  HUC: {pcs.huc_code}, State: {pcs.state}")
    
    try:
        # Get Station object
        try:
            station = Station.objects.get(station_number=pcs.station_number)
        except Station.DoesNotExist:
            print(f"  ❌ Station not in Station table")
            results['error'] += 1
            continue
        
        # Pull data
        data = client.get_daily_mean(pcs.station_number, start_date, end_date)
        
        if not data:
            print(f"  ⚠️  No data available")
            results['no_data'] += 1
            continue
        
        print(f"  ✅ Retrieved {len(data)} records")
        results['success'] += 1
        results['total_records'] += len(data)
        
        # Save to database
        saved = 0
        duplicates = 0
        for record in data:
            try:
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
            except Exception as e:
                print(f"     Error saving record: {e}")
        
        print(f"     Saved: {saved} new, {duplicates} duplicates")
        
        # Show sample
        print(f"     Sample: {data[0]['observed_at'].date()} = {data[0]['discharge']} {data[0]['unit']}")
        
    except Exception as e:
        print(f"  ❌ Error: {str(e)}")
        results['error'] += 1
        import traceback
        traceback.print_exc()

# Summary
print("\n" + "="*80)
print("TEST RESULTS")
print("="*80)
print(f"\nStations tested: 3")
print(f"  ✅ Success: {results['success']}")
print(f"  ⚠️  No data: {results['no_data']}")
print(f"  ❌ Errors: {results['error']}")
print(f"\nTotal records retrieved: {results['total_records']}")

# Check database
print("\n" + "="*80)
print("DATABASE CHECK")
print("="*80)

total_obs = DischargeObservation.objects.count()
print(f"\nTotal observations in database: {total_obs}")

# Check recent observations
recent = DischargeObservation.objects.order_by('-observed_at')[:5]
print(f"\nMost recent observations:")
for obs in recent:
    print(f"  {obs.station.station_number}: {obs.observed_at} = {obs.discharge} {obs.unit}")

# Check observations for HUC17 stations
huc17_station_numbers = [pcs.station_number for pcs in config.configuration_stations.all()]
huc17_observations = DischargeObservation.objects.filter(
    station__station_number__in=huc17_station_numbers
).count()
print(f"\nObservations for HUC17 stations: {huc17_observations}")

print("\n" + "="*80)
print("CONCLUSION")
print("="*80)

if results['success'] > 0:
    print("\n✅ USGS DATA PULL IS WORKING!")
    print(f"Successfully pulled data for {results['success']} stations")
    print(f"The configuration is ready for automated pulls")
    print("\nTo trigger the full configuration:")
    print("  - Wait for the scheduled time (check config.schedule_value)")
    print("  - Or manually trigger via Django admin")
    print("  - Or ensure Celery worker and beat are running")
else:
    print("\n⚠️  NO DATA PULLED")
    if results['no_data'] == 3:
        print("All tested stations have no recent data")
        print("This could be normal - try different stations or date range")
    elif results['error'] == 3:
        print("All tested stations had errors - investigate above")

print("\n" + "="*80)
