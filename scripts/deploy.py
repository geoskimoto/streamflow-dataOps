#!/usr/bin/env python
"""
Production deployment script for StreamFlow DataOps.

Comprehensive deployment including:
- Environment validation
- System dependency checks
- Database migrations
- Static file collection
- Station data population
- PullConfiguration setup

Usage:
    python scripts/deploy.py [OPTIONS]
    
Options:
    --dry-run              Show what would be done without making changes
    --skip-deps            Skip system dependency checks
    --skip-stations        Skip station data population
    --skip-migrations      Skip database migrations
    --skip-static          Skip static file collection
    --skip-configs         Skip PullConfiguration setup
"""

import os
import sys
import django
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Setup Django
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.streamflow.models import (
    PullConfiguration, 
    PullConfigurationStation,
    Station,
    MasterStation
)
from django.db.models import Q
from django.core.management import call_command
from django.conf import settings


# ============================================================================
# VALIDATION & CHECKS
# ============================================================================

def check_environment_file():
    """Verify .env file exists with required variables."""
    print("\n🔍 Checking Environment Configuration...")
    print("-" * 70)
    
    env_file = Path(settings.BASE_DIR) / '.env'
    
    if not env_file.exists():
        print("  ⚠️  WARNING: .env file not found")
        print("  → Copy .env.example to .env and configure it")
        return False
    
    # Check for required variables
    required_vars = [
        'DATABASE_URL',
        'REDIS_URL',
    ]
    
    optional_vars = [
        'EARTHDATA_USERNAME',
        'EARTHDATA_PASSWORD',
        'SECRET_KEY',
        'DEBUG',
    ]
    
    missing_required = []
    missing_optional = []
    
    with open(env_file, 'r') as f:
        content = f.read()
        for var in required_vars:
            if var not in content or f'{var}=' not in content:
                missing_required.append(var)
        for var in optional_vars:
            if var not in content or f'{var}=' not in content:
                missing_optional.append(var)
    
    if missing_required:
        print(f"  ✗ Missing required variables: {', '.join(missing_required)}")
        return False
    
    print("  ✓ .env file exists with required variables")
    
    if missing_optional:
        print(f"  ⚠️  Optional variables not set: {', '.join(missing_optional)}")
    
    return True


def check_system_dependencies():
    """Check if required system dependencies are installed."""
    print("\n🔍 Checking System Dependencies...")
    print("-" * 70)
    
    dependencies = {
        'python': {'cmd': ['python', '--version'], 'required': True},
        'postgresql': {'cmd': ['psql', '--version'], 'required': True},
        'redis': {'cmd': ['redis-cli', '--version'], 'required': True},
        'gdal': {'cmd': ['gdalinfo', '--version'], 'required': True},
    }
    
    all_good = True
    
    for name, info in dependencies.items():
        try:
            result = subprocess.run(
                info['cmd'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                version = result.stdout.strip().split('\n')[0]
                print(f"  ✓ {name}: {version}")
            else:
                raise subprocess.CalledProcessError(result.returncode, info['cmd'])
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            if info['required']:
                print(f"  ✗ {name}: NOT FOUND (required)")
                all_good = False
            else:
                print(f"  ⚠️  {name}: NOT FOUND (optional)")
    
    # Check Python packages
    try:
        from osgeo import gdal
        print(f"  ✓ Python GDAL bindings: {gdal.__version__}")
    except ImportError:
        print("  ✗ Python GDAL bindings: NOT INSTALLED")
        all_good = False
    
    try:
        import psycopg2
        print(f"  ✓ psycopg2: {psycopg2.__version__}")
    except ImportError:
        print("  ✗ psycopg2: NOT INSTALLED")
        all_good = False
    
    try:
        import redis
        # Test Redis connection
        r = redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))
        r.ping()
        print(f"  ✓ Redis connection: OK")
    except Exception as e:
        print(f"  ⚠️  Redis connection: FAILED ({e})")
        print("  → Make sure Redis is running: sudo systemctl start redis")
    
    return all_good


def check_database_connection():
    """Verify database connection works."""
    print("\n🔍 Checking Database Connection...")
    print("-" * 70)
    
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT version();")
            version = cursor.fetchone()[0]
            print(f"  ✓ Database connected: {version.split(',')[0]}")
            
            # Check for PostGIS
            cursor.execute("SELECT PostGIS_Version();")
            postgis_version = cursor.fetchone()[0]
            print(f"  ✓ PostGIS extension: {postgis_version}")
            
        return True
    except Exception as e:
        print(f"  ✗ Database connection failed: {e}")
        print("  → Check DATABASE_URL in .env file")
        print("  → Ensure PostgreSQL is running")
        print("  → Run: createdb streamflow_db")
        return False


# ============================================================================
# DEPLOYMENT STEPS
# ============================================================================

def run_migrations(dry_run=False):
    """Run database migrations."""
    print("\n📦 Running Database Migrations...")
    print("-" * 70)
    
    if dry_run:
        print("  → Would run: python manage.py migrate")
        return True
    
    try:
        call_command('migrate', verbosity=1, interactive=False)
        print("  ✓ Migrations completed successfully")
        return True
    except Exception as e:
        print(f"  ✗ Migration failed: {e}")
        return False


def collect_static_files(dry_run=False):
    """Collect static files."""
    print("\n📁 Collecting Static Files...")
    print("-" * 70)
    
    if dry_run:
        print("  → Would run: python manage.py collectstatic --noinput")
        return True
    
    try:
        call_command('collectstatic', verbosity=1, interactive=False)
        print("  ✓ Static files collected successfully")
        return True
    except Exception as e:
        print(f"  ✗ Static collection failed: {e}")
        return False


def populate_station_data(dry_run=False):
    """Populate master stations and station mappings."""
    print("\n🗺️  Populating Station Data...")
    print("-" * 70)
    
    # Check if stations already exist
    station_count = Station.objects.count()
    master_count = MasterStation.objects.count()
    
    print(f"  Current data: {station_count} stations, {master_count} master stations")
    
    if dry_run:
        if master_count == 0:
            print("  → Would run: python manage.py load_master_stations")
        else:
            print("  → Master stations already loaded")
            
        if station_count == 0:
            print("  → Would run: python manage.py sync_stations")
        else:
            print("  → Stations already loaded")
            
        print("  → Would run: python manage.py populate_station_mappings")
        return True
    
    try:
        # Load master stations if needed
        if master_count == 0:
            print("  → Loading master stations...")
            call_command('load_master_stations', verbosity=1)
            new_master_count = MasterStation.objects.count()
            print(f"  ✓ Loaded {new_master_count} master stations")
        else:
            print(f"  ✓ Master stations already loaded ({master_count} records)")
        
        # Sync stations if needed
        if station_count == 0:
            print("  → Syncing active stations...")
            call_command('sync_stations', verbosity=1)
            new_station_count = Station.objects.count()
            print(f"  ✓ Synced {new_station_count} active stations")
        else:
            print(f"  ✓ Stations already synced ({station_count} records)")
        
        # Populate station mappings
        print("  → Populating station mappings...")
        call_command('populate_station_mappings', verbosity=1)
        print("  ✓ Station mappings populated")
        
        return True
    except Exception as e:
        print(f"  ✗ Station population failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# PULLCONFIGURATION SETUP (Original Functions)
# ============================================================================


def get_nwrfc_stations():
    """Get all active NWRFC stations."""
    # Get all NWRFC station identifiers from MasterStation
    nwrfc_master = MasterStation.objects.filter(rfc_code='NWRFC')
    
    nwrfc_lids = set()
    for master in nwrfc_master:
        if master.noaa_lid:
            nwrfc_lids.add(master.noaa_lid)
        if master.station_number:
            nwrfc_lids.add(master.station_number)
    
    # Find corresponding active stations
    stations = Station.objects.filter(
        Q(station_number__in=nwrfc_lids),
        agency='NOAA_RFC',
        is_active=True
    )
    
    return list(stations)


def create_nwrfc_short_forecast_config(dry_run=False):
    """Create NWRFC 18-hour forecast collection configuration."""
    
    config_name = "NWRFC Short-Range Forecast Collection"
    
    # Check if already exists
    if PullConfiguration.objects.filter(name=config_name).exists():
        print(f"  ✓ '{config_name}' already exists, skipping...")
        return None
    
    if dry_run:
        stations = get_nwrfc_stations()
        print(f"  → Would create '{config_name}' with {len(stations)} stations")
        return None
    
    # Create configuration
    config = PullConfiguration.objects.create(
        name=config_name,
        description="Collects 18-hour short-range forecasts from Northwest RFC stations daily at 8:30 AM PST",
        data_source="NOAA_RFC",
        data_type="forecast",
        forecast_type="short",  # 18-hour forecast
        data_strategy="append",  # Preserve historical runs
        pull_start_date=datetime.now(timezone.utc),
        is_enabled=True,
        schedule_type="daily",
        schedule_value="30 16 * * *"  # 8:30 AM PST = 16:30 UTC
    )
    
    # Get NWRFC stations and create associations
    stations = get_nwrfc_stations()
    station_links = [
        PullConfigurationStation(
            configuration=config,
            station_number=station.station_number
        )
        for station in stations
    ]
    
    PullConfigurationStation.objects.bulk_create(station_links)
    
    print(f"  ✓ Created '{config_name}' with {len(station_links)} stations")
    return config


def create_nwrfc_medium_forecast_config(dry_run=False):
    """Create NWRFC 10-day forecast collection configuration."""
    
    config_name = "NWRFC Medium-Range Forecast Collection"
    
    # Check if already exists
    if PullConfiguration.objects.filter(name=config_name).exists():
        print(f"  ✓ '{config_name}' already exists, skipping...")
        return None
    
    if dry_run:
        stations = get_nwrfc_stations()
        print(f"  → Would create '{config_name}' with {len(stations)} stations")
        return None
    
    # Create configuration
    config = PullConfiguration.objects.create(
        name=config_name,
        description="Collects 10-day medium-range forecasts from Northwest RFC stations daily at 8:30 AM PST for ML training",
        data_source="NOAA_RFC",
        data_type="forecast",
        forecast_type="medium",  # 10-day forecast
        data_strategy="append",  # Preserve historical runs
        pull_start_date=datetime.now(timezone.utc),
        is_enabled=True,
        schedule_type="daily",
        schedule_value="30 16 * * *"  # 8:30 AM PST = 16:30 UTC
    )
    
    # Get NWRFC stations and create associations
    stations = get_nwrfc_stations()
    station_links = [
        PullConfigurationStation(
            configuration=config,
            station_number=station.station_number
        )
        for station in stations
    ]
    
    PullConfigurationStation.objects.bulk_create(station_links)
    
    print(f"  ✓ Created '{config_name}' with {len(station_links)} stations")
    return config


def get_pnw_usgs_stations():
    """Get all active USGS stations in Pacific Northwest (HUC 17)."""
    stations = Station.objects.filter(
        huc_code__startswith='17',
        agency='USGS',
        is_active=True
    )
    return list(stations)


def get_western_us_usgs_stations():
    """Get all active USGS stations in Western US (HUC 14-18)."""
    stations = Station.objects.filter(
        huc_code__regex=r'^1[4-8]',
        agency='USGS',
        is_active=True
    )
    return list(stations)


def create_pnw_daily_mean_config(dry_run=False):
    """Create Pacific Northwest daily mean observed data configuration."""
    
    config_name = "PNW USGS Daily Mean Discharge"
    
    # Check if already exists
    if PullConfiguration.objects.filter(name=config_name).exists():
        print(f"  ✓ '{config_name}' already exists, skipping...")
        return None
    
    if dry_run:
        stations = get_pnw_usgs_stations()
        print(f"  → Would create '{config_name}' with {len(stations)} stations")
        return None
    
    # Create configuration
    config = PullConfiguration.objects.create(
        name=config_name,
        description="Collects historical and ongoing daily mean discharge from all PNW USGS stations (HUC 17) - scheduled daily at 9 AM PST",
        data_source="USGS",
        data_type="observed",
        data_strategy="replace",  # Historical data doesn't change, replace is more efficient
        pull_start_date=datetime.now(timezone.utc),
        is_enabled=True,
        schedule_type="daily",
        schedule_value="0 17 * * *"  # 9:00 AM PST = 17:00 UTC
    )
    
    # Get PNW USGS stations and create associations
    stations = get_pnw_usgs_stations()
    station_links = [
        PullConfigurationStation(
            configuration=config,
            station_number=station.station_number
        )
        for station in stations
    ]
    
    PullConfigurationStation.objects.bulk_create(station_links)
    
    print(f"  ✓ Created '{config_name}' with {len(station_links)} stations")
    return config


def create_pnw_realtime_config(dry_run=False):
    """Create Pacific Northwest real-time USGS 7-day rolling window configuration."""
    
    config_name = "PNW USGS Real-time 7-Day Window"
    
    # Check if already exists
    if PullConfiguration.objects.filter(name=config_name).exists():
        print(f"  ✓ '{config_name}' already exists, skipping...")
        return None
    
    if dry_run:
        stations = get_pnw_usgs_stations()
        print(f"  → Would create '{config_name}' with {len(stations)} stations")
        return None
    
    # Create configuration
    config = PullConfiguration.objects.create(
        name=config_name,
        description="Collects real-time 15-minute discharge data with 7-day rolling window from all PNW USGS stations - runs every 4 hours",
        data_source="USGS",
        data_type="realtime",
        data_strategy="overwrite",  # Overwrite to manage storage with rolling window
        pull_start_date=datetime.now(timezone.utc),
        is_enabled=True,
        schedule_type="custom",
        schedule_value="0 */4 * * *"  # Every 4 hours
    )
    
    # Get PNW USGS stations and create associations
    stations = get_pnw_usgs_stations()
    station_links = [
        PullConfigurationStation(
            configuration=config,
            station_number=station.station_number
        )
        for station in stations
    ]
    
    PullConfigurationStation.objects.bulk_create(station_links)
    
    print(f"  ✓ Created '{config_name}' with {len(station_links)} stations")
    return config


def create_pnw_historical_backfill_config(dry_run=False):
    """Create one-time historical backfill configuration for PNW USGS stations (HUC 17 only)."""
    
    config_name = "HUC 17 USGS Historical Backfill (One-Time)"
    
    # Check if already exists
    if PullConfiguration.objects.filter(name=config_name).exists():
        print(f"  ✓ '{config_name}' already exists, skipping...")
        return None
    
    if dry_run:
        stations = get_pnw_usgs_stations()
        print(f"  → Would create '{config_name}' with {len(stations)} stations")
        return None
    
    # Create configuration for historical backfill - HUC 17 only
    config = PullConfiguration.objects.create(
        name=config_name,
        description="ONE-TIME: Backfills complete historical record for HUC 17 (Pacific Northwest) USGS stations. Pulls from earliest available data to present. Disable after completion.",
        data_source="USGS",
        data_type="observed",
        data_strategy="replace",  # Replace strategy handles duplicates gracefully
        pull_start_date=datetime(1900, 1, 1, tzinfo=timezone.utc),  # Pull from earliest available
        is_enabled=True,  # Enabled by default - disable manually after backfill completes
        schedule_type="manual",  # Manual execution only
        schedule_value=""  # No automatic schedule
    )
    
    # Get HUC 17 stations only
    stations = get_pnw_usgs_stations()
    station_links = [
        PullConfigurationStation(
            configuration=config,
            station_number=station.station_number
        )
        for station in stations
    ]
    
    PullConfigurationStation.objects.bulk_create(station_links)
    
    print(f"  ✓ Created '{config_name}' with {len(station_links)} stations")
    print(f"  ℹ️  HUC 17 (Pacific Northwest): OR, WA, ID portions")
    return config


def create_western_us_historical_backfill_config(dry_run=False):
    """Create one-time historical backfill configuration for Western US USGS stations (HUC 14-18)."""
    
    config_name = "HUC 14-18 USGS Historical Backfill (One-Time)"
    
    # Check if already exists
    if PullConfiguration.objects.filter(name=config_name).exists():
        print(f"  ✓ '{config_name}' already exists, skipping...")
        return None
    
    if dry_run:
        stations = get_western_us_usgs_stations()
        print(f"  → Would create '{config_name}' with {len(stations)} stations")
        return None
    
    # Create configuration for historical backfill - All Western US
    config = PullConfiguration.objects.create(
        name=config_name,
        description="ONE-TIME: Backfills complete historical record for HUC 14-18 (Western US) USGS stations. Includes Upper/Lower Colorado (14-15), Great Basin (16), Pacific Northwest (17), California (18). Pulls from earliest available data to present. Disable after completion.",
        data_source="USGS",
        data_type="observed",
        data_strategy="replace",  # Replace strategy handles duplicates gracefully
        pull_start_date=datetime(1900, 1, 1, tzinfo=timezone.utc),  # Pull from earliest available
        is_enabled=False,  # Disabled by default - enable manually when ready for larger backfill
        schedule_type="manual",  # Manual execution only
        schedule_value=""  # No automatic schedule
    )
    
    # Get all Western US stations (HUC 14-18)
    stations = get_western_us_usgs_stations()
    station_links = [
        PullConfigurationStation(
            configuration=config,
            station_number=station.station_number
        )
        for station in stations
    ]
    
    PullConfigurationStation.objects.bulk_create(station_links)
    
    print(f"  ✓ Created '{config_name}' with {len(station_links)} stations")
    print(f"  ℹ️  Coverage: HUC 14 (Upper CO), 15 (Lower CO), 16 (Great Basin), 17 (PNW), 18 (CA)")
    print(f"  ℹ️  Disabled by default - enable when ready for comprehensive Western US backfill")
    return config


def create_grid_configs(dry_run=False):
    """Create grid/raster data configurations."""
    print("  ⊘ Grid configurations (TODO: not implemented yet)")
    return None


def setup_pull_configurations(dry_run=False):
    """Create all PullConfigurations."""
    print("\n⚙️  Setting Up Data Collection Configurations...")
    print("-" * 70)
    
    try:
        create_nwrfc_short_forecast_config(dry_run=dry_run)
        create_nwrfc_medium_forecast_config(dry_run=dry_run)
        create_pnw_daily_mean_config(dry_run=dry_run)
        create_pnw_realtime_config(dry_run=dry_run)
        create_pnw_historical_backfill_config(dry_run=dry_run)
        create_western_us_historical_backfill_config(dry_run=dry_run)
        create_grid_configs(dry_run=dry_run)
        return True
    except Exception as e:
        print(f"\n✗ Error creating configurations: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# MAIN DEPLOYMENT ORCHESTRATION
# ============================================================================

def main(dry_run=False, skip_deps=False, skip_stations=False, 
         skip_migrations=False, skip_static=False, skip_configs=False):
    """Main deployment orchestration."""
    
    print("=" * 70)
    print("🚀 StreamFlow DataOps - Full Deployment")
    print("=" * 70)
    
    if dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***\n")
    
    failed_steps = []
    
    # Step 1: Environment validation
    if not check_environment_file():
        failed_steps.append("Environment file")
        print("\n⚠️  WARNING: Continuing with warnings...")
    
    # Step 2: System dependencies (can be skipped for speed)
    if not skip_deps:
        if not check_system_dependencies():
            print("\n⚠️  WARNING: Some dependencies missing. Continuing anyway...")
    else:
        print("\n⏭️  Skipping system dependency checks")
    
    # Step 3: Database connection
    if not check_database_connection():
        failed_steps.append("Database connection")
        print("\n❌ Cannot proceed without database connection")
        return 1
    
    # Step 4: Run migrations
    if not skip_migrations:
        if not run_migrations(dry_run=dry_run):
            failed_steps.append("Migrations")
    else:
        print("\n⏭️  Skipping migrations")
    
    # Step 5: Collect static files
    if not skip_static:
        if not collect_static_files(dry_run=dry_run):
            failed_steps.append("Static files")
    else:
        print("\n⏭️  Skipping static file collection")
    
    # Step 6: Populate station data
    if not skip_stations:
        if not populate_station_data(dry_run=dry_run):
            failed_steps.append("Station data")
    else:
        print("\n⏭️  Skipping station data population")
    
    # Step 7: Setup PullConfigurations
    if not skip_configs:
        if not setup_pull_configurations(dry_run=dry_run):
            failed_steps.append("PullConfigurations")
    else:
        print("\n⏭️  Skipping PullConfiguration setup")
    
    # Summary
    print("\n" + "=" * 70)
    if dry_run:
        print("✅ Dry Run Complete - No changes made")
    elif failed_steps:
        print("⚠️  Deployment Completed with Warnings")
        print(f"   Failed steps: {', '.join(failed_steps)}")
        print("\n   Review errors above and fix issues before production use")
    else:
        print("✅ Deployment Complete - All Systems Ready!")
        print("\n   Next steps:")
        print("   1. Create superuser: python manage.py createsuperuser")
        print("   2. Start Celery worker: celery -A config worker -l info")
        print("   3. Start Celery beat: celery -A config beat -l info")
        print("   4. Start server: python manage.py runserver 0.0.0.0:8000")
    print("=" * 70)
    
    return 1 if failed_steps else 0


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Deploy StreamFlow DataOps with full setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/deploy.py                    # Full deployment
  python scripts/deploy.py --dry-run          # Preview changes
  python scripts/deploy.py --skip-deps        # Skip slow dependency checks
  python scripts/deploy.py --skip-stations    # Skip station data (if already loaded)
        """
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        '--skip-deps',
        action='store_true',
        help="Skip system dependency checks (faster)"
    )
    parser.add_argument(
        '--skip-stations',
        action='store_true',
        help="Skip station data population"
    )
    parser.add_argument(
        '--skip-migrations',
        action='store_true',
        help="Skip database migrations"
    )
    parser.add_argument(
        '--skip-static',
        action='store_true',
        help="Skip static file collection"
    )
    parser.add_argument(
        '--skip-configs',
        action='store_true',
        help="Skip PullConfiguration setup"
    )
    
    args = parser.parse_args()
    exit_code = main(
        dry_run=args.dry_run,
        skip_deps=args.skip_deps,
        skip_stations=args.skip_stations,
        skip_migrations=args.skip_migrations,
        skip_static=args.skip_static,
        skip_configs=args.skip_configs
    )
    sys.exit(exit_code)
