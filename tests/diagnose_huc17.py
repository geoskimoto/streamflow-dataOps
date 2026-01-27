#!/usr/bin/env python
"""
Quick diagnostic for HUC17 configuration issue
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
    MasterStation,
    PullConfigurationStation,
    DataPullLog
)
from src.acquisition.usgs_client import USGSClient

print("\n" + "="*80)
print("HUC17 CONFIGURATION DIAGNOSTIC")
print("="*80)

# 1. Find the HUC17 configuration
print("\n1. Finding HUC17 configuration...")
huc17_config = PullConfiguration.objects.filter(name__icontains='HUC 17').first()

if not huc17_config:
    print("❌ ERROR: No HUC17 configuration found!")
    sys.exit(1)

print(f"✅ Found: {huc17_config.name} (ID: {huc17_config.id})")
print(f"   Data Source: {huc17_config.data_source}")
print(f"   Enabled: {huc17_config.is_enabled}")
print(f"   Last Run: {huc17_config.last_run_at}")

# 2. Check stations in configuration
print("\n2. Checking stations in configuration...")
config_stations = huc17_config.configuration_stations.count()
print(f"   Stations in configuration: {config_stations}")

if config_stations == 0:
    print("\n❌ PROBLEM FOUND: Configuration has ZERO stations!")
    print("   This is why no data is being pulled.")
    print("\n   To fix this:")
    print("   1. Go to the configuration page in Django")
    print("   2. Add stations to the configuration")
    print("   3. Or use the web interface to add stations")
else:
    print(f"✅ Configuration has {config_stations} stations")
    # Show sample stations
    for pcs in huc17_config.configuration_stations.all()[:5]:
        print(f"   - {pcs.station_number}: {pcs.station_name}")

# 3. Check available HUC17 stations in database
print("\n3. Checking available HUC17 stations...")
huc17_master = MasterStation.objects.filter(
    huc_code__startswith='17',
    agency='USGS'
).count()
print(f"   USGS stations with HUC17 in MasterStation: {huc17_master}")

huc17_working = Station.objects.filter(
    huc_code__startswith='17',
    agency='USGS'
).count()
print(f"   USGS stations with HUC17 in Station (working): {huc17_working}")

if huc17_working > 0:
    print(f"\n   Sample HUC17 working stations:")
    for station in Station.objects.filter(huc_code__startswith='17', agency='USGS')[:10]:
        print(f"   - {station.station_number}: {station.station_name} (HUC: {station.huc_code})")

# 4. Test USGS client directly
print("\n4. Testing USGS client with Columbia River station...")
test_station = "14105700"  # Deschutes River
client = USGSClient()

end_date = datetime.now()
start_date = end_date - timedelta(days=3)

try:
    data = client.get_daily_mean(test_station, start_date, end_date)
    if data:
        print(f"✅ USGS client working: Retrieved {len(data)} records")
        print(f"   Sample: {data[0]['observed_at']} - {data[0]['discharge']} {data[0]['unit']}")
    else:
        print(f"⚠️  No data returned (but API working)")
except Exception as e:
    print(f"❌ USGS client error: {e}")

# 5. Check recent pull logs
print("\n5. Checking recent pull logs for this configuration...")
recent_logs = DataPullLog.objects.filter(
    configuration=huc17_config
).order_by('-start_time')[:5]

if recent_logs:
    print(f"   Found {recent_logs.count()} recent logs:")
    for log in recent_logs:
        icon = "✅" if log.status == "success" else "❌" if log.status == "failed" else "🔄"
        print(f"   {icon} {log.start_time.strftime('%Y-%m-%d %H:%M:%S')}: {log.status} - {log.records_processed} records")
        if log.error_message:
            print(f"      Error: {log.error_message[:100]}")
else:
    print("   No pull logs found for this configuration")

# Summary
print("\n" + "="*80)
print("DIAGNOSIS SUMMARY")
print("="*80)

if config_stations == 0:
    print("\n🔴 ROOT CAUSE: Configuration has NO stations assigned!")
    print("\nSOLUTION:")
    print("You need to add stations to your configuration. Here's how:")
    print("\n1. Via Web Interface:")
    print("   - Go to: http://localhost:8000/configurations/")
    print(f"   - Edit configuration: '{huc17_config.name}'")
    print("   - Click 'Add Stations' or 'Manage Stations'")
    print("   - Select HUC17 stations from the list")
    print("\n2. Via Django Shell:")
    print("   python manage.py shell")
    print("   >>> from apps.streamflow.models import PullConfiguration, Station, PullConfigurationStation")
    print(f"   >>> config = PullConfiguration.objects.get(id={huc17_config.id})")
    print("   >>> stations = Station.objects.filter(huc_code__startswith='17', agency='USGS')")
    print("   >>> for station in stations:")
    print("   ...     PullConfigurationStation.objects.create(")
    print("   ...         configuration=config,")
    print("   ...         station_number=station.station_number,")
    print("   ...         station_name=station.station_name,")
    print("   ...         huc_code=station.huc_code,")
    print("   ...         state=station.state")
    print("   ...     )")
    print(f"\n3. Available stations: {huc17_working} HUC17 stations ready to add")
else:
    print(f"\n✅ Configuration has {config_stations} stations")
    print("\nIf data still isn't pulling, check:")
    print("1. Is Celery worker running?")
    print("2. Is Celery beat scheduler running?")
    print("3. Check the schedule settings")
    print("4. Look at recent error logs")

print("\n" + "="*80)
