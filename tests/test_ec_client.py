"""Test script for Environment Canada client using MSC GeoMet API."""

import sys
from datetime import datetime, timedelta
from src.acquisition.canada_client import CanadaClient

def test_canada_client():
    """Test the CanadaClient with Fraser River at Hope (08MF005)."""
    
    print("="*70)
    print("Testing Environment Canada Client (MSC GeoMet API)")
    print("="*70)
    
    client = CanadaClient()
    
    # Test station: 08MF005 - Fraser River at Hope, BC
    test_station = "08MF005"
    
    # Test 1: Get station info
    print(f"\n1. Testing get_station_info for {test_station}...")
    try:
        info = client.get_station_info(test_station)
        if info:
            print(f"✓ Station info retrieved:")
            print(f"  • Name: {info['name']}")
            print(f"  • Location: {info['latitude']}, {info['longitude']}")
            print(f"  • Province: {info['state']}")
            print(f"  • Drainage Area: {info['drainage_area']} km²")
            print(f"  • Status: {info['status']}")
            print(f"  • Real-time: {'Yes' if info['real_time'] else 'No'}")
        else:
            print("✗ No station info found")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    # Test 2: Get realtime data (last 2 days)
    print(f"\n2. Testing get_realtime_data for {test_station} (last 2 days)...")
    try:
        end_date = datetime(2025, 12, 27)  # Known good date from API test
        start_date = end_date - timedelta(days=2)
        
        realtime_data = client.get_realtime_data(test_station, start_date, end_date)
        
        if realtime_data:
            print(f"✓ Retrieved {len(realtime_data)} realtime observations")
            print(f"\n  First observation:")
            first = realtime_data[0]
            print(f"    • Time: {first['observed_at']}")
            print(f"    • Discharge: {first['discharge']:.2f} {first['unit']}")
            print(f"    • Discharge (CFS): {first['discharge_cfs']:.2f} cfs")
            print(f"    • Type: {first['type']}")
            print(f"    • Quality: {first['quality_code']}")
            
            print(f"\n  Last observation:")
            last = realtime_data[-1]
            print(f"    • Time: {last['observed_at']}")
            print(f"    • Discharge: {last['discharge']:.2f} {last['unit']}")
            print(f"    • Discharge (CFS): {last['discharge_cfs']:.2f} cfs")
        else:
            print("✗ No realtime data found")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 3: Get daily mean data (January 1965)
    print(f"\n3. Testing get_daily_mean for {test_station} (January 1965)...")
    try:
        start_date = datetime(1965, 1, 10)
        end_date = datetime(1965, 1, 20)
        
        daily_data = client.get_daily_mean(test_station, start_date, end_date)
        
        if daily_data:
            print(f"✓ Retrieved {len(daily_data)} daily mean observations")
            print(f"\n  First observation:")
            first = daily_data[0]
            print(f"    • Date: {first['observed_at'].date()}")
            print(f"    • Discharge: {first['discharge']:.2f} {first['unit']}")
            print(f"    • Discharge (CFS): {first['discharge_cfs']:.2f} cfs")
            print(f"    • Type: {first['type']}")
            
            # Calculate conversion factor
            cms_value = first['discharge']
            cfs_value = first['discharge_cfs']
            conversion = cfs_value / cms_value if cms_value > 0 else 0
            print(f"\n  Conversion factor: 1 cms = {conversion:.4f} cfs")
            print(f"  Expected: 1 cms = 35.3147 cfs")
        else:
            print("✗ No daily mean data found")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 4: Get BC stations
    print(f"\n4. Testing get_stations_by_province for BC (limit=10)...")
    try:
        bc_stations = client.get_stations_by_province("BC", limit=10)
        
        if bc_stations:
            print(f"✓ Retrieved {len(bc_stations)} BC stations")
            print(f"\n  Sample stations:")
            for i, station in enumerate(bc_stations[:5], 1):
                print(f"    {i}. {station['station_number']} - {station['name']}")
                print(f"       Status: {station['status']}, Real-time: {'Yes' if station['real_time'] else 'No'}")
        else:
            print("✗ No BC stations found")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*70)
    print("Testing complete!")
    print("="*70 + "\n")


if __name__ == "__main__":
    test_canada_client()
