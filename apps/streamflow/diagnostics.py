"""System diagnostics and health check utilities."""

import os
import shutil
import logging
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Any

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django.core.management import call_command
from django.core.management.base import CommandError
from io import StringIO

logger = logging.getLogger(__name__)


class SystemDiagnostics:
    """Comprehensive system health checks."""
    
    @staticmethod
    def check_database() -> Dict[str, Any]:
        """Check PostgreSQL connection and performance."""
        try:
            from django.db import connections
            import time
            
            # Test connection
            start = time.time()
            with connection.cursor() as cursor:
                cursor.execute("SELECT version();")
                version = cursor.fetchone()[0]
                
                # Get database size
                cursor.execute("""
                    SELECT pg_database_size(current_database()) / (1024*1024*1024.0) as size_gb;
                """)
                db_size = cursor.fetchone()[0]
                
                # Check table count
                cursor.execute("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = 'public';
                """)
                table_count = cursor.fetchone()[0]
            
            latency = round((time.time() - start) * 1000, 2)
            
            # Parse version
            version_short = version.split()[1] if 'PostgreSQL' in version else version
            
            return {
                'status': 'healthy',
                'connected': True,
                'version': version_short,
                'latency_ms': latency,
                'size_gb': round(db_size, 2),
                'table_count': table_count,
                'message': f'Connected to PostgreSQL {version_short}',
                'details': version
            }
        except Exception as e:
            logger.error(f"Database check failed: {e}")
            return {
                'status': 'error',
                'connected': False,
                'message': f'Connection failed: {str(e)}',
                'error': str(e)
            }
    
    @staticmethod
    def check_redis() -> Dict[str, Any]:
        """Check Redis server status."""
        try:
            import redis
            from urllib.parse import urlparse
            
            broker_url = getattr(settings, 'CELERY_BROKER_URL', None)
            if not broker_url or 'redis' not in broker_url:
                return {
                    'status': 'warning',
                    'connected': False,
                    'message': 'Redis not configured'
                }
            
            # Parse Redis URL
            parsed = urlparse(broker_url)
            redis_client = redis.Redis(
                host=parsed.hostname or 'localhost',
                port=parsed.port or 6379,
                decode_responses=True
            )
            
            # Test connection
            info = redis_client.info()
            
            return {
                'status': 'healthy',
                'connected': True,
                'version': info.get('redis_version', 'Unknown'),
                'memory_used_mb': round(info.get('used_memory', 0) / (1024*1024), 2),
                'uptime_seconds': info.get('uptime_in_seconds', 0),
                'connected_clients': info.get('connected_clients', 0),
                'message': f"Redis {info.get('redis_version', 'Unknown')} running"
            }
        except ImportError:
            return {
                'status': 'warning',
                'connected': False,
                'message': 'Redis library not installed'
            }
        except Exception as e:
            logger.error(f"Redis check failed: {e}")
            return {
                'status': 'error',
                'connected': False,
                'message': f'Connection failed: {str(e)}',
                'error': str(e)
            }
    
    @staticmethod
    def check_celery_worker() -> Dict[str, Any]:
        """Check if Celery worker is running."""
        try:
            from celery import current_app
            
            # First check if Redis broker is reachable
            broker_url = current_app.conf.broker_url
            broker_status = "Unknown"
            broker_details = ""
            
            try:
                import redis
                # Parse redis URL
                if broker_url.startswith('redis://'):
                    r = redis.from_url(broker_url)
                    r.ping()
                    broker_status = "Connected"
                    broker_details = f"Broker: {broker_url}"
            except Exception as broker_err:
                broker_status = "Failed"
                broker_details = f"Broker connection failed: {str(broker_err)}"
            
            # Try to inspect active workers
            inspect = current_app.control.inspect(timeout=2.0)
            stats = inspect.stats()
            
            if not stats:
                error_details = [
                    "No Celery workers found",
                    f"Broker Status: {broker_status}",
                    broker_details,
                    "",
                    "To start a worker, run:",
                    "  celery -A config worker -l info",
                    "",
                    "For background execution:",
                    "  celery -A config worker -l info --detach"
                ]
                
                return {
                    'status': 'error',
                    'running': False,
                    'worker_count': 0,
                    'broker_status': broker_status,
                    'message': 'No Celery workers found',
                    'error': '\n'.join(error_details),
                    'troubleshooting': error_details
                }
            
            worker_count = len(stats)
            worker_names = list(stats.keys())
            
            # Get active tasks
            active = inspect.active()
            active_task_count = sum(len(tasks) for tasks in active.values()) if active else 0
            
            # Get registered tasks
            registered = inspect.registered()
            registered_count = len(list(registered.values())[0]) if registered else 0
            
            return {
                'status': 'healthy',
                'running': True,
                'worker_count': worker_count,
                'worker_names': worker_names,
                'active_tasks': active_task_count,
                'registered_tasks': registered_count,
                'broker_status': broker_status,
                'message': f'{worker_count} worker(s) running, {active_task_count} active tasks'
            }
        except Exception as e:
            logger.error(f"Celery worker check failed: {e}")
            
            error_details = [
                f"Error: {str(e)}",
                f"Error Type: {type(e).__name__}",
                "",
                "Common causes:",
                "  1. Celery worker not started",
                "  2. Redis server not running",
                "  3. Incorrect broker URL configuration",
                "",
                "Start worker with:",
                "  celery -A config worker -l info",
                "",
                "Check Redis:",
                "  redis-cli ping"
            ]
            
            return {
                'status': 'error',
                'running': False,
                'worker_count': 0,
                'message': f'Unable to connect to Celery workers',
                'error': '\n'.join(error_details),
                'troubleshooting': error_details
            }
    
    @staticmethod
    def check_celery_beat() -> Dict[str, Any]:
        """Check Celery Beat scheduler status."""
        try:
            # Check if beat process is running
            result = subprocess.run(
                ['pgrep', '-f', 'celery.*beat'],
                capture_output=True,
                text=True
            )
            
            is_running = result.returncode == 0
            pid = result.stdout.strip() if is_running else None
            
            if is_running:
                # Try to get scheduled tasks info
                from celery import current_app
                from django_celery_beat.models import PeriodicTask
                
                enabled_tasks = PeriodicTask.objects.filter(enabled=True).count()
                total_tasks = PeriodicTask.objects.count()
                
                return {
                    'status': 'healthy',
                    'running': True,
                    'pid': pid,
                    'enabled_tasks': enabled_tasks,
                    'total_tasks': total_tasks,
                    'message': f'Celery Beat running ({enabled_tasks}/{total_tasks} tasks enabled)'
                }
            else:
                troubleshooting = [
                    "Celery Beat scheduler is not running",
                    "",
                    "This is only needed for scheduled/periodic tasks.",
                    "Manual data pulls will still work without Beat.",
                    "",
                    "To start Celery Beat:",
                    "  celery -A config beat -l info",
                    "",
                    "For background execution:",
                    "  celery -A config beat -l info --detach"
                ]
                
                return {
                    'status': 'warning',
                    'running': False,
                    'message': 'Celery Beat not running (only needed for scheduled tasks)',
                    'troubleshooting': troubleshooting
                }
        except ImportError:
            return {
                'status': 'warning',
                'running': False,
                'message': 'django-celery-beat not installed (optional)',
                'troubleshooting': [
                    "django-celery-beat is not installed",
                    "This is optional and only needed for database-backed periodic tasks",
                    "",
                    "To install:",
                    "  pip install django-celery-beat"
                ]
            }
        except Exception as e:
            logger.error(f"Celery beat check failed: {e}")
            return {
                'status': 'warning',
                'running': False,
                'message': f'Unable to check Celery Beat: {str(e)}',
                'error': str(e)
            }
    
    @staticmethod
    def check_gee_api() -> Dict[str, Any]:
        """Test Google Earth Engine connectivity."""
        try:
            from src.acquisition.gee_client import GEEClient
            
            client = GEEClient()
            
            # Simple test - try to access a collection
            import ee
            try:
                # Try to get info about a known collection
                collection = ee.ImageCollection('NOAA/NWS/RTMA')
                info = collection.limit(1).first().getInfo()
                
                return {
                    'status': 'healthy',
                    'authenticated': True,
                    'message': 'Google Earth Engine API connected',
                    'test_result': 'Successfully accessed RTMA collection'
                }
            except Exception as test_error:
                return {
                    'status': 'warning',
                    'authenticated': True,
                    'message': f'Authenticated but test query failed: {str(test_error)}'
                }
                
        except Exception as e:
            logger.error(f"GEE API check failed: {e}")
            return {
                'status': 'error',
                'authenticated': False,
                'message': f'Authentication failed: {str(e)}',
                'error': str(e)
            }
    
    @staticmethod
    def check_data_providers() -> Dict[str, List[Dict[str, Any]]]:
        """Test connectivity to data provider APIs."""
        import requests
        import time
        
        providers = [
            {
                'name': 'USGS NWIS',
                'url': 'https://waterservices.usgs.gov/nwis/iv/',
                'params': {'format': 'json', 'sites': '01646500', 'parameterCd': '00060', 'period': 'P1D'},
                'timeout': 10,
                'description': 'USGS stream gauge data'
            },
            {
                'name': 'NOAA Weather API',
                'url': 'https://api.weather.gov/gridpoints/SEW/124,67',
                'params': {},
                'timeout': 10,
                'description': 'NOAA RFC forecast data'
            },
            {
                'name': 'Environment Canada',
                'url': 'https://geo.weather.gc.ca/geomet',
                'params': {'service': 'WMS', 'version': '1.3.0', 'request': 'GetCapabilities'},
                'timeout': 15,
                'description': 'Environment Canada stream gauges'
            },
            {
                'name': 'NOAA NOMADS',
                'url': 'https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/',
                'params': {},
                'timeout': 10,
                'description': 'RTMA real-time mesoscale analysis'
            },
            {
                'name': 'NASA EarthData',
                'url': 'https://urs.earthdata.nasa.gov/api/users/test',
                'params': {},
                'timeout': 10,
                'description': 'SMAP, MODIS, GPM data access'
            }
        ]
        
        results = []
        for provider in providers:
            try:
                start = time.time()
                response = requests.get(
                    provider['url'],
                    params=provider['params'],
                    timeout=provider['timeout'],
                    allow_redirects=True
                )
                latency = round((time.time() - start) * 1000, 2)
                
                # For EarthData, getting redirected is normal
                is_ok = response.status_code in [200, 301, 302, 401, 403]
                
                results.append({
                    'name': provider['name'],
                    'status': 'healthy' if is_ok else 'warning',
                    'online': is_ok,
                    'status_code': response.status_code,
                    'latency_ms': latency,
                    'description': provider['description'],
                    'message': f'✓ {latency}ms' if is_ok else f'Status {response.status_code}'
                })
            except requests.Timeout:
                results.append({
                    'name': provider['name'],
                    'status': 'error',
                    'online': False,
                    'description': provider['description'],
                    'message': '✗ Request timeout'
                })
            except Exception as e:
                results.append({
                    'name': provider['name'],
                    'status': 'error',
                    'online': False,
                    'description': provider['description'],
                    'message': f'✗ {str(e)[:50]}'
                })
        
        return {'apis': results}
    
    @staticmethod
    def check_storage() -> Dict[str, Any]:
        """Check disk space and file permissions."""
        storage_checks = {}
        
        # Check raster data directory
        raster_root = getattr(settings, 'RASTER_ROOT', None)
        if raster_root:
            try:
                raster_path = Path(raster_root)
                if raster_path.exists():
                    # Get disk usage
                    usage = shutil.disk_usage(raster_path)
                    
                    # Count files
                    file_count = sum(1 for _ in raster_path.rglob('*.tif'))
                    
                    # Check permissions
                    readable = os.access(raster_path, os.R_OK)
                    writable = os.access(raster_path, os.W_OK)
                    
                    percent_used = (usage.used / usage.total) * 100
                    
                    storage_checks['raster_data'] = {
                        'status': 'healthy' if percent_used < 90 else 'warning',
                        'exists': True,
                        'path': str(raster_path),
                        'used_gb': round(usage.used / (1024**3), 2),
                        'free_gb': round(usage.free / (1024**3), 2),
                        'total_gb': round(usage.total / (1024**3), 2),
                        'percent_used': round(percent_used, 1),
                        'file_count': file_count,
                        'readable': readable,
                        'writable': writable,
                        'message': f'{file_count} raster files, {round(usage.free / (1024**3), 1)} GB free'
                    }
                else:
                    storage_checks['raster_data'] = {
                        'status': 'warning',
                        'exists': False,
                        'message': 'Raster data directory not found'
                    }
            except Exception as e:
                storage_checks['raster_data'] = {
                    'status': 'error',
                    'message': f'Error checking raster storage: {str(e)}'
                }
        else:
            storage_checks['raster_data'] = {
                'status': 'warning',
                'message': 'RASTER_ROOT not configured'
            }
        
        # Check static files
        static_root = getattr(settings, 'STATIC_ROOT', None)
        if static_root:
            try:
                static_path = Path(static_root)
                if static_path.exists():
                    usage = shutil.disk_usage(static_path)
                    dir_size = sum(f.stat().st_size for f in static_path.rglob('*') if f.is_file())
                    
                    storage_checks['static_files'] = {
                        'status': 'healthy',
                        'exists': True,
                        'size_mb': round(dir_size / (1024**2), 2),
                        'message': f'{round(dir_size / (1024**2), 1)} MB used'
                    }
                else:
                    storage_checks['static_files'] = {
                        'status': 'warning',
                        'exists': False,
                        'message': 'Static files not collected'
                    }
            except Exception as e:
                storage_checks['static_files'] = {
                    'status': 'warning',
                    'message': f'Unable to check static files: {str(e)}'
                }
        
        return storage_checks
    
    @staticmethod
    def check_application() -> Dict[str, Any]:
        """Check Django application status."""
        import django
        from django.core.management import call_command
        
        # Check for unapplied migrations
        try:
            out = StringIO()
            call_command('showmigrations', '--plan', stdout=out)
            output = out.getvalue()
            unapplied = output.count('[ ]')
            
            migrations_status = 'healthy' if unapplied == 0 else 'warning'
            migrations_message = 'All migrations applied' if unapplied == 0 else f'{unapplied} unapplied migrations'
        except Exception as e:
            migrations_status = 'error'
            migrations_message = f'Unable to check migrations: {str(e)}'
            unapplied = None
        
        # Get model counts
        try:
            from apps.streamflow.models import (
                Station, DischargeObservation, ForecastRun,
                PullConfiguration, RasterLayer, RasterPullConfiguration
            )
            
            model_counts = {
                'stations': Station.objects.count(),
                'observations': DischargeObservation.objects.count(),
                'forecasts': ForecastRun.objects.count(),
                'ts_configs': PullConfiguration.objects.filter(is_enabled=True).count(),
                'raster_layers': RasterLayer.objects.count(),
                'raster_configs': RasterPullConfiguration.objects.filter(is_active=True).count(),
            }
        except Exception as e:
            model_counts = {'error': str(e)}
        
        return {
            'django_version': django.get_version(),
            'debug_mode': settings.DEBUG,
            'migrations': {
                'status': migrations_status,
                'message': migrations_message,
                'unapplied': unapplied
            },
            'model_counts': model_counts,
            'installed_apps': len(settings.INSTALLED_APPS),
            'middleware': len(settings.MIDDLEWARE)
        }
    
    @staticmethod
    def check_recent_activity() -> Dict[str, Any]:
        """Get recent pull logs and activity."""
        from apps.streamflow.models import DataPullLog, RasterPullLog
        
        cutoff = timezone.now() - timedelta(hours=24)
        
        # Timeseries activity
        ts_logs = DataPullLog.objects.filter(start_time__gte=cutoff)
        ts_recent = DataPullLog.objects.order_by('-start_time').first()
        
        # Gridded activity
        raster_logs = RasterPullLog.objects.filter(started_at__gte=cutoff)
        raster_recent = RasterPullLog.objects.order_by('-started_at').first()
        
        return {
            'timeseries': {
                'total_24h': ts_logs.count(),
                'success_24h': ts_logs.filter(status='success').count(),
                'failed_24h': ts_logs.filter(status='failed').count(),
                'last_pull': {
                    'time': ts_recent.start_time if ts_recent else None,
                    'status': ts_recent.status if ts_recent else None,
                    'config': ts_recent.configuration.name if ts_recent and ts_recent.configuration else None
                } if ts_recent else None
            },
            'gridded': {
                'total_24h': raster_logs.count(),
                'success_24h': raster_logs.filter(status='success').count(),
                'failed_24h': raster_logs.filter(status='failed').count(),
                'last_pull': {
                    'time': raster_recent.started_at if raster_recent else None,
                    'status': raster_recent.status if raster_recent else None,
                    'config': raster_recent.configuration.name if raster_recent and raster_recent.configuration else None,
                    'layers_successful': raster_recent.layers_successful if raster_recent else 0,
                    'layers_failed': raster_recent.layers_failed if raster_recent else 0
                } if raster_recent else None
            }
        }
    
    @staticmethod
    def get_overall_status(checks: Dict[str, Any]) -> str:
        """Determine overall system status."""
        # Check critical components
        critical_errors = []
        warnings = []
        
        if checks.get('database', {}).get('status') == 'error':
            critical_errors.append('Database connection failed')
        
        if checks.get('celery_worker', {}).get('status') == 'error':
            warnings.append('Celery worker not running')
        
        if checks.get('redis', {}).get('status') == 'error':
            warnings.append('Redis connection failed')
        
        # Check storage
        storage = checks.get('storage', {})
        for key, value in storage.items():
            if value.get('status') == 'error':
                critical_errors.append(f'{key} error')
            elif value.get('status') == 'warning':
                warnings.append(f'{key} warning')
        
        if critical_errors:
            return 'error'
        elif warnings:
            return 'warning'
        else:
            return 'healthy'
