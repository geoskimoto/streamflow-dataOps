#!/usr/bin/env python
"""
Manually trigger HUC 17 historical backfill.

This script will start the backfill task and show you the progress.
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.streamflow.models import PullConfiguration, DischargeObservation
from src.acquisition.tasks import pull_usgs_data
from celery.result import AsyncResult
import time


def main():
    print("\n" + "="*80)
    print("HUC 17 HISTORICAL BACKFILL TRIGGER")
    print("="*80)
    
    # Find the HUC 17 config
    try:
        config = PullConfiguration.objects.get(name__icontains='HUC 17', name__icontains='One-Time')
        print(f"\nConfiguration found:")
        print(f"  Name: {config.name}")
        print(f"  ID: {config.id}")
        print(f"  Enabled: {config.is_enabled}")
        
        # Get station count
        station_count = config.configuration_stations.count()
        print(f"  Stations: {station_count:,}")
        
    except PullConfiguration.DoesNotExist:
        print("❌ HUC 17 Historical Backfill configuration not found!")
        print("   Run: python scripts/deploy.py")
        return
    
    if not config.is_enabled:
        print("\n⚠ WARNING: Configuration is DISABLED")
        print("   Would you like to enable it? (y/n): ", end="")
        response = input().strip().lower()
        if response == 'y':
            config.is_enabled = True
            config.save()
            print("✓ Configuration enabled")
        else:
            print("Exiting without triggering")
            return
    
    # Check current observation count
    current_count = DischargeObservation.objects.count()
    print(f"\n Current observations in database: {current_count:,}")
    
    # Warning about data volume
    print("\n" + "="*80)
    print("⚠ IMPORTANT: This will pull historical data for 2,890 stations")
    print("   Estimated time: 1-8 hours")
    print("   Estimated data: 30-50 million observations (5-15 GB)")
    print("="*80)
    
    print("\nAre you sure you want to start the historical backfill? (yes/no): ", end="")
    response = input().strip().lower()
    
    if response != 'yes':
        print("Canceled")
        return
    
    # Trigger the task
    print("\n🚀 Starting backfill task...")
    result = pull_usgs_data.delay(config.id)
    
    print(f"✓ Task started!")
    print(f"  Task ID: {result.id}")
    print(f"  Configuration: {config.name}")
    print(f"  Stations: {station_count:,}")
    
    print("\n" + "="*80)
    print("MONITORING (Press Ctrl+C to stop monitoring, task will continue)")
    print("="*80)
    
    # Monitor progress
    try:
        last_count = current_count
        while True:
            time.sleep(10)  # Check every 10 seconds
            
            # Get current status
            task = AsyncResult(result.id)
            status = task.state
            
            # Count observations
            new_count = DischargeObservation.objects.count()
            new_records = new_count - last_count
            total_new = new_count - current_count
            
            print(f"[{time.strftime('%H:%M:%S')}] Status: {status} | "
                  f"New records: +{total_new:,} (+{new_records:,} since last check)")
            
            last_count = new_count
            
            if status in ['SUCCESS', 'FAILURE', 'REVOKED']:
                print(f"\n✓ Task completed with status: {status}")
                if status == 'SUCCESS':
                    print(f"  Total new records: {total_new:,}")
                break
                
    except KeyboardInterrupt:
        print("\n\n⏸ Monitoring stopped (task continues in background)")
        print(f"  Task ID: {result.id}")
        print("\nTo check status later:")
        print(f"  python -c \"from celery.result import AsyncResult; print(AsyncResult('{result.id}').state)\"")
    
    print("\n" + "="*80)
    print("To view Celery logs:")
    print("  tail -f logs/celery-worker.log")
    print("\nTo check database:")
    print("  python manage.py shell")
    print("  >>> from apps.streamflow.models import DischargeObservation")
    print("  >>> print(f'Total: {DischargeObservation.objects.count():,}')")
    print("="*80)


if __name__ == '__main__':
    main()
