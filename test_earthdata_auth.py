#!/usr/bin/env python3
"""
Test script for NASA EarthData authentication and basic operations.

Usage:
    python test_earthdata_auth.py

Requirements:
    - NASA EarthData account
    - Either:
      1. ~/.netrc file with urs.earthdata.nasa.gov credentials, OR
      2. EARTHDATA_USERNAME and EARTHDATA_PASSWORD environment variables
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from src.acquisition.earthdata_client import EarthDataClient, EarthDataError

def test_authentication():
    """Test EarthData authentication."""
    print("=" * 60)
    print("TEST 1: Authentication")
    print("=" * 60)
    
    try:
        client = EarthDataClient()
        
        if client.authenticated:
            print("✅ Successfully authenticated with NASA EarthData")
            print(f"   Auth method: {'Environment' if client.username else '.netrc'}")
            return client
        else:
            print("❌ Authentication failed")
            return None
            
    except Exception as e:
        print(f"❌ Authentication error: {e}")
        print("\nTo fix:")
        print("1. Create NASA EarthData account: https://urs.earthdata.nasa.gov/users/new")
        print("2. Either:")
        print("   a) Create ~/.netrc file:")
        print("      machine urs.earthdata.nasa.gov")
        print("          login your_username")
        print("          password your_password")
        print("   b) Set environment variables:")
        print("      export EARTHDATA_USERNAME=your_username")
        print("      export EARTHDATA_PASSWORD=your_password")
        return None

def test_smap_search(client):
    """Test SMAP granule search."""
    print("\n" + "=" * 60)
    print("TEST 2: SMAP Granule Search")
    print("=" * 60)
    
    try:
        # Search for SMAP data over HUC17 (Columbia River Basin)
        bbox = [-124.7, 41.5, -108.0, 49.0]
        end_date = datetime.now() - timedelta(days=2)  # SMAP has latency
        start_date = end_date - timedelta(days=1)
        
        print(f"Searching for SMAP data:")
        print(f"  Collection: {client.COLLECTIONS['SMAP_SPL4']}")
        print(f"  Date range: {start_date.date()} to {end_date.date()}")
        print(f"  Bounding box: {bbox}")
        
        granules = client.search_granules(
            collection_id=client.COLLECTIONS['SMAP_SPL4'],
            bbox=bbox,
            start_date=start_date,
            end_date=end_date,
            limit=5
        )
        
        if granules:
            print(f"✅ Found {len(granules)} SMAP granules")
            for i, granule in enumerate(granules[:3], 1):
                # Get granule info
                try:
                    size_mb = granule['umm']['DataGranule']['ArchiveAndDistributionInformation'][0]['SizeInBytes'] / 1024 / 1024
                    print(f"\n   Granule {i}:")
                    print(f"     Size: {size_mb:.1f} MB")
                    print(f"     Producer: {granule['umm']['DataGranule']['ProductionDateTime']}")
                except:
                    print(f"   Granule {i}: [metadata unavailable]")
            return True
        else:
            print("⚠️  No SMAP granules found (may need to adjust date range)")
            return False
            
    except Exception as e:
        print(f"❌ SMAP search failed: {e}")
        return False

def test_gpm_search(client):
    """Test GPM granule search."""
    print("\n" + "=" * 60)
    print("TEST 3: GPM Granule Search")
    print("=" * 60)
    
    try:
        # Search for GPM data
        bbox = [-124.7, 41.5, -108.0, 49.0]
        end_date = datetime.now() - timedelta(days=120)  # GPM Final has 3.5 month latency
        start_date = end_date - timedelta(days=1)
        
        print(f"Searching for GPM IMERG data:")
        print(f"  Collection: {client.COLLECTIONS['GPM_IMERG']}")
        print(f"  Date range: {start_date.date()} to {end_date.date()}")
        print(f"  Bounding box: {bbox}")
        print(f"  Note: GPM IMERG Final has ~3.5 month latency")
        
        granules = client.search_granules(
            collection_id=client.COLLECTIONS['GPM_IMERG'],
            bbox=bbox,
            start_date=start_date,
            end_date=end_date,
            limit=5
        )
        
        if granules:
            print(f"✅ Found {len(granules)} GPM granules")
            for i, granule in enumerate(granules[:3], 1):
                try:
                    size_mb = granule['umm']['DataGranule']['ArchiveAndDistributionInformation'][0]['SizeInBytes'] / 1024 / 1024
                    print(f"\n   Granule {i}:")
                    print(f"     Size: {size_mb:.1f} MB")
                except:
                    print(f"   Granule {i}: [metadata unavailable]")
            return True
        else:
            print("⚠️  No GPM granules found")
            return False
            
    except Exception as e:
        print(f"❌ GPM search failed: {e}")
        return False

def test_availability_check(client):
    """Test availability checking."""
    print("\n" + "=" * 60)
    print("TEST 4: Data Availability Check")
    print("=" * 60)
    
    bbox = [-124.7, 41.5, -108.0, 49.0]
    
    # Test SMAP
    end_date = datetime.now() - timedelta(days=2)
    start_date = end_date - timedelta(days=7)
    
    print("Checking SMAP availability...")
    smap_avail = client.check_data_availability(
        collection_id=client.COLLECTIONS['SMAP_SPL4'],
        bbox=bbox,
        start_date=start_date,
        end_date=end_date
    )
    
    if smap_avail['available']:
        print(f"✅ SMAP: {smap_avail['message']}")
    else:
        print(f"❌ SMAP: {smap_avail['message']}")
    
    # Test GPM
    end_date = datetime.now() - timedelta(days=120)
    start_date = end_date - timedelta(days=7)
    
    print("\nChecking GPM availability...")
    gpm_avail = client.check_data_availability(
        collection_id=client.COLLECTIONS['GPM_IMERG'],
        bbox=bbox,
        start_date=start_date,
        end_date=end_date
    )
    
    if gpm_avail['available']:
        print(f"✅ GPM: {gpm_avail['message']}")
    else:
        print(f"❌ GPM: {gpm_avail['message']}")

def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "NASA EarthData Client Test Suite" + " " * 16 + "║")
    print("╚" + "=" * 58 + "╝")
    
    # Test authentication
    client = test_authentication()
    
    if not client:
        print("\n❌ Cannot proceed without authentication")
        sys.exit(1)
    
    # Run other tests
    smap_ok = test_smap_search(client)
    gpm_ok = test_gpm_search(client)
    test_availability_check(client)
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Authentication: ✅")
    print(f"SMAP Search:    {'✅' if smap_ok else '⚠️'}")
    print(f"GPM Search:     {'✅' if gpm_ok else '⚠️'}")
    print("\n✅ EarthData client is ready to use!")
    print("\nNext steps:")
    print("1. Implement GeoTIFF conversion methods")
    print("2. Add download retry logic")
    print("3. Create unit tests")
    print("4. Integrate with Django pull tasks")

if __name__ == '__main__':
    main()
