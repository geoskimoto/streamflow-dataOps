#!/usr/bin/env python
"""
Sync additional HUC regions (15, 16, 18) to Station table.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.streamflow.models import Station, MasterStation

def sync_huc_regions(huc_codes):
    """Sync stations from MasterStation to Station for specified HUC codes."""
    
    print("\n" + "="*80)
    print("SYNCING HUC REGIONS TO STATION TABLE")
    print("="*80)
    
    total_created = 0
    total_already_exist = 0
    
    for huc in huc_codes:
        print(f"\n🔄 Processing HUC {huc}...")
        
        # Get master stations for this HUC
        master_stations = MasterStation.objects.filter(
            agency='USGS',
            huc_code__startswith=huc
        )
        
        count = master_stations.count()
        print(f"   Found {count:,} stations in MasterStation table")
        
        created = 0
        already_exist = 0
        
        for master in master_stations:
            # Check if station already exists
            if Station.objects.filter(station_number=master.station_number).exists():
                already_exist += 1
                continue
            
            # Create station from master
            Station.objects.create(
                station_number=master.station_number,
                name=master.station_name,
                agency=master.agency,
                latitude=master.latitude,
                longitude=master.longitude,
                state=master.state_code,
                huc_code=master.huc_code,
                is_active=True
            )
            created += 1
        
        print(f"   ✓ Created: {created:,} new stations")
        if already_exist > 0:
            print(f"   ⏭ Skipped: {already_exist:,} (already exist)")
        
        total_created += created
        total_already_exist += already_exist
    
    print("\n" + "="*80)
    print("SYNC COMPLETE")
    print("="*80)
    print(f"Total new stations created: {total_created:,}")
    print(f"Total already existing: {total_already_exist:,}")
    
    # Verify final counts
    print("\n" + "="*80)
    print("VERIFICATION")
    print("="*80)
    
    for huc in huc_codes:
        active_count = Station.objects.filter(
            agency='USGS',
            huc_code__startswith=huc,
            is_active=True
        ).count()
        master_count = MasterStation.objects.filter(
            agency='USGS',
            huc_code__startswith=huc
        ).count()
        print(f"HUC {huc}: {active_count:,} active / {master_count:,} master {'✓' if active_count == master_count else '⚠'}")
    
    # Check total HUC 14-18
    total_active = Station.objects.filter(
        agency='USGS',
        huc_code__regex=r'^1[4-8]',
        is_active=True
    ).count()
    
    total_master = MasterStation.objects.filter(
        agency='USGS',
        huc_code__regex=r'^1[4-8]'
    ).count()
    
    print(f"\nTotal HUC 14-18:")
    print(f"  Active: {total_active:,}")
    print(f"  Master: {total_master:,}")
    print(f"  Status: {'✓ COMPLETE' if total_active == total_master else '⚠ MISMATCH'}")
    
    return total_created


if __name__ == '__main__':
    # Sync HUC 15, 16, 18 (HUC 17 is already synced)
    huc_regions = ['15', '16', '18']
    
    print(f"\nThis will sync {len(huc_regions)} HUC regions: {', '.join(huc_regions)}")
    response = input("Continue? (y/n): ").strip().lower()
    
    if response == 'y':
        created = sync_huc_regions(huc_regions)
        
        if created > 0:
            print("\n✓ Stations synced successfully!")
            print("\nNow the HUC 14-18 config should have all 5,394 stations.")
            print("Run: python check_backfill_status.py")
    else:
        print("Canceled")
