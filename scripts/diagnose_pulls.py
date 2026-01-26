#!/usr/bin/env python
"""
Test and diagnose data pull issues.
This script will:
1. Check configuration stations vs Station table
2. Test data pulls for sample stations
3. Identify missing Station records
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.streamflow.models import (
    PullConfiguration, 
    PullConfigurationStation,
    MasterStation,
    Station,
    DischargeObservation,
    ForecastRun
)
from src.acquisition.usgs_client import USGSClient
from src.acquisition.noaa_client import NOAAClient
from datetime import datetime, timezone, timedelta

def check_configuration_coverage():
    """Check if all configured stations exist in Station table."""
    print("=" * 80)
    print("CONFIGURATION COVERAGE CHECK")
    print("=" * 80)
    
    configs = PullConfiguration.objects.all()
    
    for config in configs:
        config_stations = config.configuration_stations.all()
        missing_stations = []
        
        for config_station in config_stations:
            if not Station.objects.filter(station_number=config_station.station_number).exists():
                missing_stations.append(config_station.station_number)
        
        print(f"\n{config.name}:")
        print(f"  Total stations: {config_stations.count()}")
        print(f"  Missing from Station table: {len(missing_stations)}")
        
        if missing_stations and len(missing_stations) <= 5:
            print(f"  Missing: {', '.join(missing_stations)}")
        elif missing_stations:
            print(f"  Missing (first 5): {', '.join(missing_stations[:5])}...")

def create_missing_stations(config_name=None, dry_run=True):
    """Create Station records for all configured stations that are missing."""
    print("\n" + "=" * 80)
    print(f"CREATE MISSING STATIONS {'(DRY RUN)' if dry_run else '(LIVE)'}")
    print("=" * 80)
    
    if config_name:
        configs = PullConfiguration.objects.filter(name=config_name)
    else:
        configs = PullConfiguration.objects.all()
    
    total_created = 0
    
    for config in configs:
        print(f"\n{config.name}:")
        config_stations = config.configuration_stations.all()
        created_count = 0
        
        for config_station in config_stations:
            if not Station.objects.filter(station_number=config_station.station_number).exists():
                # Get info from MasterStation if available
                master = MasterStation.objects.filter(station_number=config_station.station_number).first()
                
                if master:
                    # Create from MasterStation
                    if not dry_run:
                        Station.objects.create(
                            station_number=config_station.station_number,
                            name=master.station_name,
                            agency=master.agency,
                            latitude=master.latitude,
                            longitude=master.longitude,
                            state=master.state_code or '',
                            huc_code=master.huc_code or '',
                            is_active=True
                        )
                    created_count += 1
                else:
                    # Create minimal record from config_station
                    if not dry_run:
                        Station.objects.create(
                            station_number=config_station.station_number,
                            name=config_station.station_name or f"Station {config_station.station_number}",
                            agency=config.data_source,
                            is_active=True
                        )
                    created_count += 1
        
        if created_count > 0:
            print(f"  Would create {created_count} stations" if dry_run else f"  Created {created_count} stations")
        total_created += created_count
    
    print(f"\nTotal: {total_created} stations {'would be created' if dry_run else 'created'}")
    return total_created

def test_usgs_station(station_number="09085000"):
    """Test USGS data pull for a specific station."""
    print("\n" + "=" * 80)
    print(f"TEST USGS STATION: {station_number}")
    print("=" * 80)
    
    client = USGSClient()
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=7)
    
    print(f"Fetching data from {start_date.date()} to {end_date.date()}")
    
    try:
        data = client.get_daily_mean(station_number, start_date, end_date)
        print(f"✓ Got {len(data)} observations")
        if data:
            print(f"Sample: {data[0]}")
        return data
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return []

def test_noaa_rfc_station(station_number="AGNO3"):
    """Test NOAA RFC forecast for a specific station."""
    print("\n" + "=" * 80)
    print(f"TEST NOAA RFC STATION: {station_number}")
    print("=" * 80)
    
    client = NOAAClient()
    
    print(f"Fetching RFC forecast...")
    
    try:
        data = client.get_rfc_forecast(station_number)
        if data and 'forecast_data' in data:
            print(f"✓ Got forecast with {len(data['forecast_data'])} points")
            print(f"Run date: {data['run_date']}")
            if data['forecast_data']:
                print(f"Sample: {data['forecast_data'][0]}")
        else:
            print(f"✗ No data returned")
        return data
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

def show_summary():
    """Show database summary."""
    print("\n" + "=" * 80)
    print("DATABASE SUMMARY")
    print("=" * 80)
    
    print(f"\nStations:")
    print(f"  MasterStation (available): {MasterStation.objects.count()}")
    print(f"  Station (operational): {Station.objects.count()}")
    for agency, name in Station.AGENCY_CHOICES:
        count = Station.objects.filter(agency=agency).count()
        print(f"    {name}: {count}")
    
    print(f"\nData:")
    print(f"  DischargeObservation: {DischargeObservation.objects.count()}")
    print(f"  ForecastRun: {ForecastRun.objects.count()}")
    
    print(f"\nConfigurations:")
    for config in PullConfiguration.objects.all():
        print(f"  {config.name}: {config.configuration_stations.count()} stations, {config.data_source}, {config.data_type}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Diagnose and fix data pull issues')
    parser.add_argument('--check', action='store_true', help='Check configuration coverage')
    parser.add_argument('--fix', action='store_true', help='Create missing Station records (dry-run by default)')
    parser.add_argument('--fix-live', action='store_true', help='Create missing Station records (LIVE - actually create)')
    parser.add_argument('--config', type=str, help='Specific configuration name to fix')
    parser.add_argument('--test-usgs', type=str, help='Test USGS station (e.g., 09085000)')
    parser.add_argument('--test-noaa', type=str, help='Test NOAA RFC station (e.g., AGNO3)')
    parser.add_argument('--summary', action='store_true', help='Show database summary')
    
    args = parser.parse_args()
    
    if args.summary or not any([args.check, args.fix, args.fix_live, args.test_usgs, args.test_noaa]):
        show_summary()
    
    if args.check:
        check_configuration_coverage()
    
    if args.fix or args.fix_live:
        create_missing_stations(args.config, dry_run=not args.fix_live)
    
    if args.test_usgs:
        test_usgs_station(args.test_usgs)
    
    if args.test_noaa:
        test_noaa_rfc_station(args.test_noaa)
    
    print("\n" + "=" * 80)
    print("Done!")
    print("=" * 80)
