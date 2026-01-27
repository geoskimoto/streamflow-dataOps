#!/usr/bin/env python
"""
Test USGS Data Pull System
Tests the entire data acquisition pipeline for USGS stations
"""

import os
import sys
import django
from datetime import datetime, timedelta

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.streamflow.models import (
    PullConfiguration, 
    Station, 
    MasterStation,
    PullConfigurationStation,
    DataPullLog,
    DischargeObservation
)
from src.acquisition.usgs_client import USGSClient
from src.acquisition.data_processor import DataProcessor

def test_1_list_configurations():
    """Test 1: List all pull configurations"""
    print("\n" + "="*80)
    print("TEST 1: List All Pull Configurations")
    print("="*80)
    
    configs = PullConfiguration.objects.all()
    print(f"\nFound {configs.count()} configurations:")
    
    for config in configs:
        station_count = config.configuration_stations.count()
        last_run = config.last_run_at.strftime('%Y-%m-%d %H:%M:%S') if config.last_run_at else 'Never'
        print(f"\nID: {config.id}")
        print(f"  Name: {config.name}")
        print(f"  Data Source: {config.data_source}")
        print(f"  Data Type: {config.data_type}")
        print(f"  Strategy: {config.data_strategy}")
        print(f"  Enabled: {config.is_enabled}")
        print(f"  Stations: {station_count}")
        print(f"  Last Run: {last_run}")
        print(f"  Schedule: {config.schedule_type} - {config.schedule_value}")
        
    return configs


def test_2_check_huc17_stations():
    """Test 2: Check stations in HUC17 (Columbia River Basin)"""
    print("\n" + "="*80)
    print("TEST 2: Check HUC17 Stations in Database")
    print("="*80)
    
    # Check MasterStation for HUC17
    huc17_master = MasterStation.objects.filter(huc_code__startswith='17')
    print(f"\nMasterStations with HUC17: {huc17_master.count()}")
    print(f"Sample stations:")
    for station in huc17_master[:5]:
        print(f"  {station.station_number} - {station.station_name} (HUC: {station.huc_code})")
    
    # Check working Stations for HUC17
    huc17_stations = Station.objects.filter(huc_code__startswith='17')
    print(f"\nWorking Stations with HUC17: {huc17_stations.count()}")
    
    # Check USGS stations specifically
    usgs_huc17 = Station.objects.filter(agency='USGS', huc_code__startswith='17')
    print(f"USGS Stations in HUC17: {usgs_huc17.count()}")
    
    return huc17_stations


def test_3_usgs_client_direct():
    """Test 3: Test USGS client directly with known good station"""
    print("\n" + "="*80)
    print("TEST 3: Direct USGS Client Test")
    print("="*80)
    
    # Use a known Columbia River station
    test_station = "14105700"  # Deschutes River at Moody, near Biggs, OR
    print(f"\nTesting with station: {test_station}")
    print("Location: Deschutes River at Moody, near Biggs, OR (HUC 17070306)")
    
    client = USGSClient()
    
    # Test recent data (last 7 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    print(f"\nFetching data from {start_date.date()} to {end_date.date()}...")
    
    try:
        data = client.get_daily_mean(test_station, start_date, end_date)
        
        if data:
            print(f"✅ SUCCESS: Retrieved {len(data)} records")
            print("\nSample records:")
            for record in data[:3]:
                print(f"  {record['observed_at']}: {record['discharge']} {record['unit']}")
            return True
        else:
            print(f"⚠️  WARNING: No data returned (station may not have recent data)")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_4_check_configuration_stations():
    """Test 4: Check stations in configurations"""
    print("\n" + "="*80)
    print("TEST 4: Check Configuration Stations")
    print("="*80)
    
    configs = PullConfiguration.objects.all()
    
    for config in configs:
        print(f"\n{config.name}:")
        config_stations = config.configuration_stations.all()[:5]
        
        if config_stations.count() == 0:
            print("  ⚠️  No stations configured!")
            continue
            
        print(f"  First 5 of {config.configuration_stations.count()} stations:")
        for pcs in config_stations:
            # Check if station exists in Station table
            try:
                station = Station.objects.get(station_number=pcs.station_number)
                status = "✅ In Station table"
            except Station.DoesNotExist:
                status = "❌ NOT in Station table"
                
            print(f"    {pcs.station_number}: {pcs.station_name} - {status}")


def test_5_check_recent_observations():
    """Test 5: Check for recent observations"""
    print("\n" + "="*80)
    print("TEST 5: Check Recent Observations")
    print("="*80)
    
    # Get recent observations
    recent_obs = DischargeObservation.objects.order_by('-observed_at')[:10]
    
    print(f"\nTotal observations in database: {DischargeObservation.objects.count()}")
    print(f"\nMost recent 10 observations:")
    
    for obs in recent_obs:
        print(f"  {obs.station_number}: {obs.observed_at} - {obs.discharge} {obs.unit}")
    
    # Check USGS observations specifically
    usgs_obs = DischargeObservation.objects.filter(station_number__startswith='1').count()
    print(f"\nUSGS observations (station numbers starting with '1'): {usgs_obs}")
    
    # Check observations from last 7 days
    recent_date = datetime.now() - timedelta(days=7)
    recent_count = DischargeObservation.objects.filter(observed_at__gte=recent_date).count()
    print(f"Observations from last 7 days: {recent_count}")


def test_6_check_pull_logs():
    """Test 6: Check data pull logs for errors"""
    print("\n" + "="*80)
    print("TEST 6: Check Data Pull Logs")
    print("="*80)
    
    logs = DataPullLog.objects.order_by('-start_time')[:10]
    
    print(f"\nTotal pull logs: {DataPullLog.objects.count()}")
    print(f"\nMost recent 10 pull attempts:")
    
    for log in logs:
        duration = ""
        if log.end_time:
            duration = f" ({(log.end_time - log.start_time).total_seconds():.1f}s)"
        
        icon = "✅" if log.status == "success" else "❌" if log.status == "failed" else "🔄"
        print(f"\n{icon} {log.configuration.name}")
        print(f"    Time: {log.start_time.strftime('%Y-%m-%d %H:%M:%S')}{duration}")
        print(f"    Status: {log.status}")
        print(f"    Records: {log.records_processed}")
        
        if log.error_message:
            print(f"    Error: {log.error_message[:200]}")


def test_7_manual_data_pull():
    """Test 7: Manually pull data for a test station"""
    print("\n" + "="*80)
    print("TEST 7: Manual Data Pull Test")
    print("="*80)
    
    # Find a USGS station to test with
    test_stations = Station.objects.filter(agency='USGS')[:1]
    
    if not test_stations:
        print("❌ No USGS stations found in Station table!")
        return False
    
    test_station = test_stations[0]
    print(f"\nTest station: {test_station.station_number} - {test_station.station_name}")
    
    client = USGSClient()
    processor = DataProcessor()
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=3)
    
    print(f"Pulling data from {start_date.date()} to {end_date.date()}...")
    
    try:
        # Pull data
        raw_data = client.get_daily_mean(test_station.station_number, start_date, end_date)
        
        if not raw_data:
            print(f"⚠️  No data available for this station")
            return False
        
        print(f"✅ Retrieved {len(raw_data)} raw records")
        
        # Process data
        print("\nProcessing and saving to database...")
        saved_count = 0
        
        for record in raw_data:
            obs, created = DischargeObservation.objects.update_or_create(
                station_number=test_station.station_number,
                observed_at=record['observed_at'],
                defaults={
                    'discharge': record['discharge'],
                    'unit': record['unit'],
                    'data_type': record.get('type', 'daily_mean'),
                    'quality_code': record.get('quality_code', ''),
                }
            )
            if created:
                saved_count += 1
        
        print(f"✅ Saved {saved_count} new observations ({len(raw_data) - saved_count} duplicates)")
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("USGS DATA PULL SYSTEM TEST SUITE")
    print("="*80)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    # Run tests
    test_1_list_configurations()
    test_2_check_huc17_stations()
    results['usgs_client'] = test_3_usgs_client_direct()
    test_4_check_configuration_stations()
    test_5_check_recent_observations()
    test_6_check_pull_logs()
    results['manual_pull'] = test_7_manual_data_pull()
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"\nUSGS Client Direct Test: {'✅ PASS' if results.get('usgs_client') else '❌ FAIL'}")
    print(f"Manual Data Pull Test: {'✅ PASS' if results.get('manual_pull') else '❌ FAIL'}")
    
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)
    
    if not results.get('usgs_client'):
        print("\n❌ USGS client is not working properly")
        print("   - Check internet connectivity")
        print("   - Verify dataretrieval package is installed: pip install dataretrieval")
        print("   - Check USGS NWIS service status: https://waterservices.usgs.gov/")
    
    if not results.get('manual_pull'):
        print("\n❌ Manual data pull failed")
        print("   - Verify database connections")
        print("   - Check for model/schema issues")
        print("   - Review error messages above")
    
    # Check if any configurations exist
    config_count = PullConfiguration.objects.count()
    if config_count == 0:
        print("\n⚠️  No pull configurations found")
        print("   - Create a configuration through Django admin or web interface")
        print("   - Add stations to the configuration")
        print("   - Ensure configuration is enabled")
    
    # Check if Celery/scheduler is running
    recent_logs = DataPullLog.objects.filter(start_time__gte=datetime.now() - timedelta(hours=24)).count()
    if recent_logs == 0:
        print("\n⚠️  No pull attempts in last 24 hours")
        print("   - Check if Celery worker is running: celery -A config worker")
        print("   - Check if Celery beat is running: celery -A config beat")
        print("   - Verify cron schedule in configuration")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    main()
