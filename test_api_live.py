#!/usr/bin/env python
"""
Test script to verify API endpoints with actual HTTP requests.
Run with: python test_api_live.py

This script assumes the Django dev server is running on localhost:8000
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000/api/v1"

def print_test(name):
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print('='*60)

def test_endpoint(method, endpoint, params=None, expected_keys=None):
    """Test an API endpoint and validate response."""
    url = f"{BASE_URL}{endpoint}"
    
    try:
        if method == 'GET':
            response = requests.get(url, params=params, timeout=10)
        else:
            return False, f"Unsupported method: {method}"
        
        print(f"URL: {url}")
        if params:
            print(f"Params: {params}")
        print(f"Status: {response.status_code}")
        
        if response.status_code != 200:
            return False, f"Non-200 status: {response.status_code}"
        
        data = response.json()
        
        # Check for pagination
        if 'results' in data:
            count = len(data['results'])
            total = data.get('count', 'N/A')
            print(f"Results: {count} records (Total: {total})")
            
            if count > 0:
                print(f"First record keys: {list(data['results'][0].keys())}")
                if expected_keys:
                    missing = [k for k in expected_keys if k not in data['results'][0]]
                    if missing:
                        return False, f"Missing keys: {missing}"
        else:
            print(f"Response keys: {list(data.keys())}")
            if expected_keys:
                missing = [k for k in expected_keys if k not in data]
                if missing:
                    return False, f"Missing keys: {missing}"
        
        return True, "✓ PASS"
        
    except requests.exceptions.RequestException as e:
        return False, f"Request failed: {e}"
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def main():
    print("\n" + "="*60)
    print("STREAMFLOW DATAOPS API TEST SUITE")
    print("="*60)
    
    results = []
    
    # Test 1: List Stations
    print_test("List Stations")
    success, msg = test_endpoint(
        'GET', '/stations/',
        expected_keys=['station_number', 'name', 'agency']
    )
    results.append(('List Stations', success, msg))
    print(msg)
    
    # Test 2: Get Single Station
    print_test("Get Single Station")
    success, msg = test_endpoint(
        'GET', '/stations/06611000/',
        expected_keys=['station_number', 'name', 'latitude', 'longitude']
    )
    results.append(('Get Single Station', success, msg))
    print(msg)
    
    # Test 3: List Observations
    print_test("List Observations")
    success, msg = test_endpoint(
        'GET', '/observations/discharge/',
        expected_keys=['station_number', 'discharge', 'observed_at', 'unit']
    )
    results.append(('List Observations', success, msg))
    print(msg)
    
    # Test 4: Filter Observations by Station
    print_test("Filter Observations by Station")
    success, msg = test_endpoint(
        'GET', '/observations/discharge/',
        params={'station_number': '06611000'},
        expected_keys=['station_number', 'discharge']
    )
    results.append(('Filter Observations', success, msg))
    print(msg)
    
    # Test 5: Observation Statistics
    print_test("Observation Statistics")
    success, msg = test_endpoint(
        'GET', '/observations/discharge/statistics/',
        expected_keys=['count', 'min_value', 'max_value']
    )
    results.append(('Observation Statistics', success, msg))
    print(msg)
    
    # Test 6: List Forecasts
    print_test("List Forecasts")
    success, msg = test_endpoint(
        'GET', '/forecasts/',
        expected_keys=['station_number', 'source', 'run_date', 'forecast_point_count']
    )
    results.append(('List Forecasts', success, msg))
    print(msg)
    
    # Test 7: Forecast Statistics
    print_test("Forecast Statistics")
    success, msg = test_endpoint(
        'GET', '/forecasts/statistics/',
        expected_keys=['count', 'total_forecast_points']
    )
    results.append(('Forecast Statistics', success, msg))
    print(msg)
    
    # Test 8: Latest Forecast
    print_test("Latest Forecast")
    success, msg = test_endpoint(
        'GET', '/forecasts/latest/',
        expected_keys=['station_number', 'run_date', 'data']
    )
    results.append(('Latest Forecast', success, msg))
    print(msg)
    
    # Test 9: Forecast by Station
    print_test("Forecasts by Station")
    success, msg = test_endpoint(
        'GET', '/forecasts/by-station/06611000/',
        expected_keys=['station_number', 'source']
    )
    results.append(('Forecasts by Station', success, msg))
    print(msg)
    
    # Test 10: List Configurations
    print_test("List Configurations")
    success, msg = test_endpoint(
        'GET', '/configurations/',
        expected_keys=['name', 'data_source', 'is_enabled']
    )
    results.append(('List Configurations', success, msg))
    print(msg)
    
    # Test 11: List Logs
    print_test("List Logs")
    success, msg = test_endpoint(
        'GET', '/logs/',
        expected_keys=['status', 'records_processed']
    )
    results.append(('List Logs', success, msg))
    print(msg)
    
    # Test 12: API Documentation
    print_test("API Documentation (Swagger)")
    try:
        response = requests.get(f"{BASE_URL}/docs/", timeout=10)
        if response.status_code == 200:
            results.append(('Swagger UI', True, '✓ PASS'))
            print('✓ PASS')
        else:
            results.append(('Swagger UI', False, f'Status: {response.status_code}'))
            print(f'Status: {response.status_code}')
    except Exception as e:
        results.append(('Swagger UI', False, str(e)))
        print(f'Error: {e}')
    
    # Print Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, success, _ in results if success)
    failed = len(results) - passed
    
    for name, success, msg in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status:8} | {name:30} | {msg if not success else ''}")
    
    print(f"\nTotal: {len(results)} | Passed: {passed} | Failed: {failed}")
    
    if failed == 0:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n⚠️  {failed} test(s) failed")
    
    return failed == 0


if __name__ == '__main__':
    print("\nNOTE: This script requires the Django dev server to be running.")
    print("Start it with: python manage.py runserver")
    print("\nPress Ctrl+C to cancel, or Enter to continue...")
    try:
        input()
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        exit(0)
    
    success = main()
    exit(0 if success else 1)
