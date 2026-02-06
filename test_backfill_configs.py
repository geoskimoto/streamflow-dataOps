#!/usr/bin/env python
"""
Test script for historical backfill configurations.

Tests the HUC 17 and HUC 14-18 backfill configs without relying on Celery.
Runs a small test pull to verify everything is working.
"""

import os
import sys
import django
from datetime import datetime, timedelta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.streamflow.models import PullConfiguration, Station, DischargeObservation
from src.acquisition.usgs_client import USGSClient
from django.utils import timezone


def check_celery_status():
    """Check if Celery is running (optional info)."""
    print("\n" + "="*80)
    print("CELERY STATUS CHECK")
    print("="*80)
    
    import subprocess
    try:
        result = subprocess.run(['pgrep', '-f', 'celery'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ Celery processes found:")
            for pid in result.stdout.strip().split('\n'):
                print(f"  - PID: {pid}")
        else:
            print("⚠ No Celery processes found (this is OK for manual testing)")
    except Exception as e:
        print(f"⚠ Could not check Celery status: {e}")


def check_configurations():
    """Check if both backfill configurations exist."""
    print("\n" + "="*80)
    print("CONFIGURATION CHECK")
    print("="*80)
    
    configs = PullConfiguration.objects.filter(
        name__icontains='historical'
    ).order_by('name')
    
    if not configs.exists():
        print("❌ No historical backfill configurations found!")
        print("   Run: python scripts/deploy.py")
        return None
    
    print(f"✓ Found {configs.count()} historical backfill configuration(s):\n")
    
    for config in configs:
        print(f"Configuration: {config.name}")
        print(f"  - ID: {config.id}")
        print(f"  - Enabled: {'✓ YES' if config.is_enabled else '✗ NO'}")
        print(f"  - Data Source: {config.data_source}")
        print(f"  - Data Type: {config.data_type}")
        print(f"  - Strategy: {config.data_strategy}")
        print(f"  - Schedule Type: {config.schedule_type}")
        
        # Count stations
        try:
            # Try different ways to get stations
            if hasattr(config, 'get_station_numbers'):
                station_numbers = config.get_station_numbers()
            elif hasattr(config, 'configuration_stations'):
                station_numbers = list(config.configuration_stations.values_list('station_number', flat=True))
            elif hasattr(config, 'stations'):
                station_numbers = list(config.stations.values_list('station_number', flat=True))
            else:
                station_numbers = []
            
            print(f"  - Stations: {len(station_numbers)}")
            
            if len(station_numbers) > 0:
                print(f"    Sample stations: {', '.join(station_numbers[:5])}")
            else:
                print(f"    ⚠ WARNING: No stations configured!")
        except Exception as e:
            print(f"    ⚠ Could not count stations: {e}")
        print()
    
    return configs


def test_station_count():
    """Verify station counts match expectations."""
    print("\n" + "="*80)
    print("STATION COUNT VERIFICATION")
    print("="*80)
    
    huc17_count = Station.objects.filter(
        agency='USGS',
        huc_code__startswith='17',
        is_active=True
    ).count()
    
    huc14_18_count = Station.objects.filter(
        agency='USGS',
        huc_code__regex=r'^1[4-8]',
        is_active=True
    ).count()
    
    print(f"HUC 17 Active Stations: {huc17_count:,}")
    print(f"HUC 14-18 Active Stations: {huc14_18_count:,}")
    
    if huc17_count == 0:
        print("\n⚠ WARNING: No HUC 17 stations found!")
        print("   These should have been created by deploy.py")
    
    return huc17_count, huc14_18_count


def test_usgs_client():
    """Test USGS client with a known good station."""
    print("\n" + "="*80)
    print("USGS CLIENT TEST")
    print("="*80)
    
    # Pick a known reliable station
    test_station = '14211720'  # Johnson Creek at Milwaukie, OR
    
    print(f"Testing with station: {test_station} (Johnson Creek, OR)")
    print("Fetching last 3 days of data...")
    
    try:
        client = USGSClient()
        end_date = datetime.now()
        start_date = end_date - timedelta(days=3)
        
        data = client.get_daily_mean(test_station, start_date, end_date)
        
        if data and len(data) > 0:
            print(f"✓ SUCCESS: Retrieved {len(data)} records")
            print(f"\nSample data:")
            for record in data[:3]:
                print(f"  {record['datetime']}: {record['value']} cfs")
        else:
            print("⚠ No data returned (station may be inactive)")
            
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_small_backfill(config_name='HUC 17', num_stations=3):
    """Test backfill with a small number of stations."""
    print("\n" + "="*80)
    print(f"SMALL BACKFILL TEST ({num_stations} stations)")
    print("="*80)
    
    try:
        config = PullConfiguration.objects.get(name__icontains=config_name)
    except PullConfiguration.DoesNotExist:
        print(f"❌ Configuration not found: {config_name}")
        return False
    
    print(f"Configuration: {config.name}")
    print(f"Testing with {num_stations} random stations...")
    
    try:
        # Try different ways to get stations
        if hasattr(config, 'get_station_numbers'):
            station_numbers = config.get_station_numbers()
        elif hasattr(config, 'configuration_stations'):
            station_numbers = list(config.configuration_stations.values_list('station_number', flat=True))
        elif hasattr(config, 'stations'):
            station_numbers = list(config.stations.values_list('station_number', flat=True))
        else:
            station_numbers = []
    except Exception as e:
        print(f"❌ Could not get stations: {e}")
        return False
    
    if len(station_numbers) == 0:
        print("❌ No stations in configuration!")
        return False
    
    # Get first N stations
    test_stations = station_numbers[:num_stations]
    print(f"Test stations: {', '.join(test_stations)}\n")
    
    client = USGSClient()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)  # Just 7 days for testing
    
    total_records = 0
    successful = 0
    
    for station_number in test_stations:
        print(f"Station {station_number}:", end=" ")
        
        try:
            # Try to get station object
            station = Station.objects.filter(station_number=station_number).first()
            if not station:
                print("❌ Not found in database")
                continue
            
            # Fetch data
            data = client.get_daily_mean(station_number, start_date, end_date)
            
            if data and len(data) > 0:
                print(f"✓ {len(data)} records retrieved")
                total_records += len(data)
                successful += 1
                
                # Show sample
                if len(data) > 0:
                    latest = data[0]
                    print(f"  Latest: {latest['datetime']} = {latest['value']} cfs")
            else:
                print("⚠ No data available")
                
        except Exception as e:
            print(f"❌ Error: {e}")
    
    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"  Successful: {successful}/{len(test_stations)}")
    print(f"  Total records: {total_records}")
    print(f"{'='*80}")
    
    return successful > 0


def check_existing_observations():
    """Check how many observations are already in the database."""
    print("\n" + "="*80)
    print("EXISTING DATA CHECK")
    print("="*80)
    
    total_obs = DischargeObservation.objects.count()
    print(f"Total observations in database: {total_obs:,}")
    
    if total_obs > 0:
        # Get date range
        oldest = DischargeObservation.objects.order_by('observed_at').first()
        newest = DischargeObservation.objects.order_by('-observed_at').first()
        
        print(f"Date range: {oldest.observed_at.date()} to {newest.observed_at.date()}")
        
        # Count by HUC
        huc17_obs = DischargeObservation.objects.filter(
            station__huc_code__startswith='17'
        ).count()
        print(f"HUC 17 observations: {huc17_obs:,}")


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("HISTORICAL BACKFILL CONFIGURATION TEST")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # 1. Check Celery (informational only)
    check_celery_status()
    
    # 2. Check configurations exist
    configs = check_configurations()
    if not configs:
        print("\n❌ FAILED: No configurations found")
        return
    
    # 3. Verify station counts
    huc17_count, huc14_18_count = test_station_count()
    
    # 4. Check existing data
    check_existing_observations()
    
    # 5. Test USGS client
    usgs_ok = test_usgs_client()
    if not usgs_ok:
        print("\n❌ USGS client test failed - cannot proceed")
        return
    
    # 6. Test small backfill
    print("\n" + "="*80)
    print("READY TO TEST")
    print("="*80)
    print("\nWould you like to test a small backfill?")
    print("This will fetch 7 days of data for 3 stations (safe test)")
    
    response = input("\nRun test? (y/n): ").strip().lower()
    
    if response == 'y':
        test_small_backfill('HUC 17', num_stations=3)
    else:
        print("\nSkipping backfill test")
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)
    print("\nTo run full backfill:")
    print("  1. Ensure Celery worker is running:")
    print("     celery -A config worker -l info")
    print("  2. Ensure Celery beat is running (if using scheduled pulls):")
    print("     celery -A config beat -l info")
    print("  3. Trigger manually via Django shell:")
    print("     python manage.py shell")
    print("     >>> from src.acquisition.tasks import pull_usgs_data")
    print("     >>> config = PullConfiguration.objects.get(name__contains='HUC 17')")
    print("     >>> result = pull_usgs_data.delay(config.id)")
    print("     >>> print(f'Task ID: {result.id}')")
    print()


if __name__ == '__main__':
    main()
