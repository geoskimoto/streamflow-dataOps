#!/usr/bin/env python
"""Test script for raster processor."""

import os
import sys
import django
from pathlib import Path

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from src.acquisition.raster_processor import RasterProcessor

def main():
    """Test raster processor functionality."""
    print("=" * 80)
    print("Testing Raster Processor")
    print("=" * 80)
    
    processor = RasterProcessor()
    print(f"\n✓ RasterProcessor initialized")
    print(f"  - Raster root: {processor.raster_root}")
    print(f"  - Compression: {processor.compression}")
    print(f"  - Thumbnail size: {processor.thumbnail_size}")
    print(f"  - Max file size: {processor.max_file_size_mb} MB")
    
    # Check if we have any test rasters
    raster_dir = Path(processor.raster_root)
    if not raster_dir.exists():
        print(f"\n⚠ Raster directory does not exist: {raster_dir}")
        print("  Processor is ready but no test files available yet.")
        print("  Run Phase 2 (GEE client) to download test rasters first.")
        return
    
    # Find test rasters
    test_files = list(raster_dir.rglob('*.tif'))
    if not test_files:
        print(f"\n⚠ No GeoTIFF files found in {raster_dir}")
        print("  Processor is ready but no test files available yet.")
        print("  Run Phase 2 (GEE client) to download test rasters first.")
        return
    
    print(f"\n✓ Found {len(test_files)} test raster(s)")
    
    # Test with first raster
    test_file = test_files[0]
    print(f"\nTesting with: {test_file.name}")
    print(f"  Path: {test_file}")
    
    # Test statistics calculation
    print("\n1. Testing statistics calculation...")
    try:
        stats = processor.calculate_statistics(test_file)
        print("  ✓ Statistics calculated:")
        print(f"    - Dimensions: {stats['width']}x{stats['height']}")
        print(f"    - CRS: {stats['crs']}")
        print(f"    - Resolution: {stats['resolution']}")
        print(f"    - Bounds: {stats['bounds']}")
        print(f"    - Min value: {stats['min_value']}")
        print(f"    - Max value: {stats['max_value']}")
        print(f"    - Mean value: {stats['mean_value']}")
        print(f"    - Std dev: {stats['std_dev']}")
        print(f"    - Valid pixels: {stats['count_valid']}/{stats['count_total']} ({stats['percent_valid']:.1f}%)")
    except Exception as e:
        print(f"  ✗ Error: {e}")
    
    # Test validation
    print("\n2. Testing raster validation...")
    try:
        is_valid, errors = processor.validate_raster(test_file)
        if is_valid:
            print("  ✓ Raster is valid")
        else:
            print(f"  ✗ Validation failed:")
            for error in errors:
                print(f"    - {error}")
    except Exception as e:
        print(f"  ✗ Error: {e}")
    
    # Test checksum
    print("\n3. Testing checksum calculation...")
    try:
        checksum = processor.calculate_checksum(test_file)
        print(f"  ✓ Checksum: {checksum}")
    except Exception as e:
        print(f"  ✗ Error: {e}")
    
    # Test thumbnail generation
    print("\n4. Testing thumbnail generation...")
    try:
        thumb_path = test_file.with_suffix('.thumb.png')
        result_path = processor.generate_thumbnail(test_file, thumb_path)
        if result_path.exists():
            size = result_path.stat().st_size
            print(f"  ✓ Thumbnail generated: {result_path.name} ({size} bytes)")
        else:
            print(f"  ✗ Thumbnail not created")
    except Exception as e:
        print(f"  ✗ Error: {e}")
    
    # Test point extraction
    print("\n5. Testing point value extraction...")
    try:
        # Extract values at center and corners
        bounds = stats['bounds']
        center_lon = (bounds[0] + bounds[2]) / 2
        center_lat = (bounds[1] + bounds[3]) / 2
        
        coords = [
            (center_lon, center_lat),  # Center
            (bounds[0], bounds[1]),     # Lower left
            (bounds[2], bounds[3]),     # Upper right
        ]
        
        values = processor.extract_point_values(test_file, coords)
        print(f"  ✓ Extracted {len(values)} point values:")
        for i, (coord, value) in enumerate(zip(coords, values)):
            label = ['center', 'lower-left', 'upper-right'][i]
            print(f"    - {label} ({coord[0]:.2f}, {coord[1]:.2f}): {value}")
    except Exception as e:
        print(f"  ✗ Error: {e}")
    
    print("\n" + "=" * 80)
    print("Raster Processor tests complete!")
    print("=" * 80)

if __name__ == '__main__':
    main()
