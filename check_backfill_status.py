#!/usr/bin/env python
"""Quick status check for backfill configurations."""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.streamflow.models import PullConfiguration, DischargeObservation, DataPullLog

print("\n" + "="*80)
print("BACKFILL CONFIGURATION STATUS")
print("="*80)

# Check configurations
configs = PullConfiguration.objects.filter(
    name__icontains='historical'
).order_by('name')

for config in configs:
    print(f"\n📋 {config.name}")
    print(f"   ID: {config.id}")
    print(f"   Status: {'✓ ENABLED' if config.is_enabled else '✗ DISABLED'}")
    print(f"   Schedule: {config.schedule_type}")
    print(f"   Strategy: {config.data_strategy}")
    
    try:
        station_count = config.configuration_stations.count()
        print(f"   Stations: {station_count:,}")
    except:
        print(f"   Stations: Unable to count")
    
    # Check recent logs
    recent_logs = DataPullLog.objects.filter(
        configuration=config
    ).order_by('-start_time')[:3]
    
    if recent_logs:
        print(f"   Recent runs:")
        for log in recent_logs:
            status_icon = "✓" if log.status == 'success' else "✗" if log.status == 'error' else "⏳"
            print(f"      {status_icon} {log.start_time.strftime('%Y-%m-%d %H:%M')} - "
                  f"{log.status} ({log.records_processed or 0:,} records)")

# Check database
print("\n" + "="*80)
print("DATABASE STATUS")
print("="*80)

total = DischargeObservation.objects.count()
print(f"Total observations: {total:,}")

if total > 0:
    oldest = DischargeObservation.objects.order_by('observed_at').first()
    newest = DischargeObservation.objects.order_by('-observed_at').first()
    print(f"Date range: {oldest.observed_at.date()} to {newest.observed_at.date()}")

# Check Celery
print("\n" + "="*80)
print("CELERY STATUS")
print("="*80)

import subprocess
try:
    result = subprocess.run(['pgrep', '-f', 'celery worker'], capture_output=True, text=True)
    worker_running = result.returncode == 0
    
    result = subprocess.run(['pgrep', '-f', 'celery beat'], capture_output=True, text=True)
    beat_running = result.returncode == 0
    
    print(f"Worker: {'✓ RUNNING' if worker_running else '✗ NOT RUNNING'}")
    print(f"Beat: {'✓ RUNNING' if beat_running else '✗ NOT RUNNING'}")
    
    if not worker_running:
        print("\n⚠ Start Celery worker:")
        print("   celery -A config worker -l info")
    
    if not beat_running:
        print("\n⚠ Start Celery beat:")
        print("   celery -A config beat -l info")
        
except Exception as e:
    print(f"Could not check Celery: {e}")

print("\n" + "="*80)
print("\nTo trigger HUC 17 backfill:")
print("  python trigger_huc17_backfill.py")
print()
