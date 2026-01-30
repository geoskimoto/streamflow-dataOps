"""
Comprehensive test for all raster data sources.

Creates test configurations for each dataset with all available variables,
then triggers pulls to verify each data source works correctly.
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from datetime import datetime, timedelta
from django.utils import timezone
from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    RasterPullConfiguration,
    RasterPullLog,
    RasterLayer,
    SpatialExtent
)
from src.acquisition.raster_tasks import pull_raster_data


def create_test_extent():
    """Create or get a small test extent (Pacific Northwest)."""
    extent, created = SpatialExtent.objects.get_or_create(
        name="Test_PNW_Small",
        defaults={
            'description': 'Small test extent for automated testing',
            'min_lon': -125.0,
            'max_lon': -120.0,
            'min_lat': 45.0,
            'max_lat': 48.0
        }
    )
    return extent


def clean_test_configs():
    """Remove any existing test configurations."""
    RasterPullConfiguration.objects.filter(name__startswith='TEST_').delete()
    print("✓ Cleaned up existing test configurations")


def create_test_config(dataset, extent, date_offset_days=5):
    """
    Create a test configuration for a dataset.
    
    Args:
        dataset: RasterDataset instance
        extent: SpatialExtent instance
        date_offset_days: How many days back to pull (to avoid data availability issues)
    
    Returns:
        RasterPullConfiguration instance
    """
    # Get all variables for this dataset
    variables = RasterVariable.objects.filter(dataset=dataset)
    
    if not variables.exists():
        print(f"  ⚠️  No variables found for {dataset.name}")
        return None
    
    # Create configuration
    config = RasterPullConfiguration.objects.create(
        name=f"TEST_{dataset.name}",
        dataset=dataset,
        description=f"Automated test configuration for {dataset.name}",
        enabled=False,  # Don't enable for automated scheduling
        lookback_days=date_offset_days,
        apply_compression=True,
        generate_thumbnails=False,  # Skip thumbnails for faster testing
        target_resolution_m=None  # Use native resolution
    )
    
    # Add all variables
    config.variables.set(variables)
    
    # Add test extent
    config.extents.add(extent)
    
    print(f"  ✓ Created config with {variables.count()} variables")
    return config


def test_dataset(dataset, extent):
    """
    Test a single dataset by creating a config and pulling data.
    
    Args:
        dataset: RasterDataset instance
        extent: SpatialExtent instance
    
    Returns:
        dict: Test results
    """
    print(f"\n{'='*60}")
    print(f"Testing: {dataset.name}")
    print(f"  Source: {dataset.data_source}")
    print(f"  Collection: {dataset.collection_id}")
    print(f"  Resolution: {dataset.temporal_resolution}")
    print(f"{'='*60}")
    
    # Determine appropriate date range based on data source and resolution
    end_date = timezone.now() - timedelta(days=3)  # 3 days ago to avoid data availability issues
    
    if dataset.temporal_resolution == 'hourly':
        # For hourly data (RTMA), pull just 3 hours
        start_date = end_date - timedelta(hours=3)
    elif dataset.temporal_resolution == 'daily':
        # For daily data, pull 2 days
        start_date = end_date - timedelta(days=2)
    else:
        # Default to 1 day
        start_date = end_date - timedelta(days=1)
    
    print(f"\nDate range: {start_date} to {end_date}")
    
    # Create test configuration
    config = create_test_config(dataset, extent)
    if not config:
        return {
            'dataset': dataset.name,
            'status': 'skipped',
            'reason': 'No variables configured'
        }
    
    # Run pull synchronously (not via Celery)
    print(f"\nExecuting pull (synchronous)...")
    try:
        result = pull_raster_data(
            config.id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat()
        )
        
        print(f"\nResults:")
        print(f"  Attempted: {result.get('attempted', 0)}")
        print(f"  Successful: {result.get('successful', 0)}")
        print(f"  Failed: {result.get('failed', 0)}")
        print(f"  Skipped: {result.get('skipped', 0)}")
        
        if result.get('errors'):
            print(f"  Errors:")
            for error in result.get('errors', [])[:5]:  # Show first 5 errors
                print(f"    - {error}")
        
        # Check for created layers
        variables = config.variables.all()
        total_layers = 0
        for var in variables:
            layers = RasterLayer.objects.filter(
                variable=var,
                timestamp__gte=start_date,
                timestamp__lte=end_date
            )
            layer_count = layers.count()
            total_layers += layer_count
            if layer_count > 0:
                print(f"  {var.name}: {layer_count} layers created")
        
        # Determine overall status
        if result.get('successful', 0) > 0:
            status = 'success'
        elif result.get('attempted', 0) == result.get('skipped', 0) and result.get('skipped', 0) > 0:
            status = 'all_skipped'
        elif 'error' in result:
            status = 'error'
        else:
            status = 'failed'
        
        return {
            'dataset': dataset.name,
            'status': status,
            'attempted': result.get('attempted', 0),
            'successful': result.get('successful', 0),
            'failed': result.get('failed', 0),
            'skipped': result.get('skipped', 0),
            'layers_created': total_layers,
            'errors': result.get('errors', [])[:5]
        }
        
    except Exception as e:
        print(f"\n❌ Exception during pull: {e}")
        import traceback
        traceback.print_exc()
        return {
            'dataset': dataset.name,
            'status': 'exception',
            'error': str(e)
        }


def print_summary(results):
    """Print a summary of all test results."""
    print(f"\n\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}\n")
    
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = sum(1 for r in results if r['status'] in ['failed', 'error', 'exception'])
    skipped_count = sum(1 for r in results if r['status'] in ['skipped', 'all_skipped'])
    
    print(f"Total datasets tested: {len(results)}")
    print(f"  ✓ Successful: {success_count}")
    print(f"  ⚠️  All skipped: {skipped_count}")
    print(f"  ❌ Failed: {failed_count}")
    print()
    
    for result in results:
        status_icon = {
            'success': '✓',
            'failed': '❌',
            'error': '❌',
            'exception': '❌',
            'skipped': '⊘',
            'all_skipped': '⚠️'
        }.get(result['status'], '?')
        
        print(f"{status_icon} {result['dataset']:30} Status: {result['status']}")
        
        if result['status'] == 'success':
            print(f"    Layers created: {result.get('layers_created', 0)}")
            print(f"    Success rate: {result.get('successful', 0)}/{result.get('attempted', 0)}")
        
        elif result['status'] == 'all_skipped':
            print(f"    All {result.get('skipped', 0)} attempts were skipped (data likely already exists or not available)")
        
        elif result['status'] == 'exception':
            print(f"    Error: {result.get('error', 'Unknown')}")
        
        if result.get('errors'):
            print(f"    Errors: {len(result['errors'])} (showing first 3)")
            for error in result['errors'][:3]:
                print(f"      - {error}")
        
        print()


def run_all_tests():
    """Run tests for all raster datasets."""
    print("="*60)
    print("RASTER DATA SOURCE COMPREHENSIVE TEST")
    print("="*60)
    print("\nThis test will:")
    print("  1. Create test configurations for each dataset")
    print("  2. Pull historical data (to avoid availability issues)")
    print("  3. Verify data can be downloaded and processed")
    print("  4. Report success/failure for each source")
    print()
    
    # Create test extent
    extent = create_test_extent()
    print(f"✓ Using test extent: {extent.name}")
    
    # Clean up old test configs
    clean_test_configs()
    
    # Get all datasets
    datasets = RasterDataset.objects.all().order_by('name')
    print(f"✓ Found {datasets.count()} datasets to test\n")
    
    if datasets.count() == 0:
        print("❌ No datasets found! Run initialization first.")
        return
    
    # Test each dataset
    results = []
    for dataset in datasets:
        result = test_dataset(dataset, extent)
        results.append(result)
    
    # Print summary
    print_summary(results)
    
    # Clean up test configurations (optional)
    print("\nCleaning up test configurations...")
    clean_test_configs()
    print("✓ Done")
    
    return results


if __name__ == '__main__':
    print("\nStarting comprehensive raster source tests...\n")
    results = run_all_tests()
    
    # Exit with appropriate code
    failed_count = sum(1 for r in results if r['status'] in ['failed', 'error', 'exception'])
    sys.exit(0 if failed_count == 0 else 1)
