"""Additional Celery tasks for monitoring, alerting, and cleanup."""

import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.db.models import Count, Q

from celery import shared_task

from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    RasterLayer,
    RasterPullLog,
    RasterPullConfiguration
)

logger = logging.getLogger(__name__)


@shared_task
def cleanup_old_layers(
    dataset_name: Optional[str] = None,
    data_source: Optional[str] = None,
    retention_days: int = 30,
    dry_run: bool = False
) -> Dict:
    """
    Clean up old raster layers based on retention policy.
    
    Args:
        dataset_name: Specific dataset name to clean (optional)
        data_source: Data source filter (earthdata, nomads, gee)
        retention_days: Number of days to retain
        dry_run: If True, only report what would be deleted
        
    Returns:
        Dictionary with cleanup statistics
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=retention_days)
        
        # Build query
        query = Q(timestamp__lt=cutoff_date)
        
        if dataset_name:
            query &= Q(variable__dataset__name=dataset_name)
        
        if data_source:
            query &= Q(variable__dataset__data_source=data_source)
        
        # Get layers to delete
        layers = RasterLayer.objects.filter(query)
        
        stats = {
            'total_layers': layers.count(),
            'deleted_layers': 0,
            'freed_bytes': 0,
            'errors': [],
            'dry_run': dry_run
        }
        
        if dry_run:
            logger.info(f"[DRY RUN] Would delete {stats['total_layers']} layers older than {retention_days} days")
            return stats
        
        # Delete layers and files
        for layer in layers:
            try:
                file_path = Path(layer.file_path)
                
                # Get file size before deletion
                if file_path.exists():
                    stats['freed_bytes'] += file_path.stat().st_size
                    file_path.unlink()
                
                # Delete thumbnail if exists
                if layer.thumbnail_path:
                    thumb_path = Path(layer.thumbnail_path)
                    if thumb_path.exists():
                        thumb_path.unlink()
                
                # Delete database record
                layer.delete()
                stats['deleted_layers'] += 1
                
            except Exception as e:
                error_msg = f"Error deleting layer {layer.id}: {str(e)}"
                logger.error(error_msg)
                stats['errors'].append(error_msg)
        
        freed_mb = stats['freed_bytes'] / (1024 * 1024)
        logger.info(
            f"Cleanup complete: Deleted {stats['deleted_layers']}/{stats['total_layers']} layers, "
            f"freed {freed_mb:.2f} MB"
        )
        
        return stats
        
    except Exception as e:
        logger.exception(f"Error in cleanup_old_layers: {e}")
        return {'error': str(e), 'dry_run': dry_run}


@shared_task
def cleanup_old_pull_logs(retention_days: int = 90) -> Dict:
    """
    Clean up old pull logs.
    
    Args:
        retention_days: Number of days to retain logs
        
    Returns:
        Dictionary with cleanup statistics
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=retention_days)
        
        # Keep failed logs longer for debugging
        old_logs = RasterPullLog.objects.filter(
            started_at__lt=cutoff_date,
            status='completed'
        )
        
        count = old_logs.count()
        old_logs.delete()
        
        logger.info(f"Cleaned up {count} pull logs older than {retention_days} days")
        
        return {
            'deleted_count': count,
            'retention_days': retention_days
        }
        
    except Exception as e:
        logger.exception(f"Error in cleanup_old_pull_logs: {e}")
        return {'error': str(e)}


@shared_task
def monitor_pull_health() -> Dict:
    """
    Monitor health of raster data pulls and send alerts if needed.
    
    Checks:
    - Datasets with no recent successful pulls
    - Configurations with consecutive failures
    - Disk space usage
    
    Returns:
        Dictionary with health status
    """
    try:
        alerts = []
        health_status = {
            'healthy': True,
            'alerts': [],
            'stats': {}
        }
        
        # Check each active dataset
        active_datasets = RasterDataset.objects.filter(is_active=True)
        
        for dataset in active_datasets:
            # Check last successful pull
            last_pull = RasterPullLog.objects.filter(
                configuration__dataset=dataset,
                status='completed'
            ).order_by('-completed_at').first()
            
            if last_pull:
                hours_since = (timezone.now() - last_pull.completed_at).total_seconds() / 3600
                max_age = settings.RASTER_PULL_MAX_AGE_HOURS
                
                if hours_since > max_age:
                    alert = {
                        'type': 'stale_data',
                        'dataset': dataset.name,
                        'hours_since_pull': round(hours_since, 1),
                        'message': f"No successful pull for {dataset.name} in {hours_since:.1f} hours"
                    }
                    alerts.append(alert)
                    health_status['healthy'] = False
            else:
                alert = {
                    'type': 'no_data',
                    'dataset': dataset.name,
                    'message': f"No successful pulls found for {dataset.name}"
                }
                alerts.append(alert)
                health_status['healthy'] = False
        
        # Check for consecutive failures
        recent_failures = RasterPullLog.objects.filter(
            status='failed',
            started_at__gte=timezone.now() - timedelta(days=1)
        ).values('configuration__dataset__name').annotate(
            failure_count=Count('id')
        ).filter(failure_count__gte=settings.RASTER_PULL_FAILURE_THRESHOLD)
        
        for failure in recent_failures:
            alert = {
                'type': 'consecutive_failures',
                'dataset': failure['configuration__dataset__name'],
                'failure_count': failure['failure_count'],
                'message': f"{failure['failure_count']} consecutive failures for {failure['configuration__dataset__name']}"
            }
            alerts.append(alert)
            health_status['healthy'] = False
        
        # Check disk space
        raster_root = Path(settings.RASTER_ROOT)
        if raster_root.exists():
            stat = os.statvfs(raster_root)
            free_bytes = stat.f_bavail * stat.f_frsize
            total_bytes = stat.f_blocks * stat.f_frsize
            free_percent = (free_bytes / total_bytes) * 100
            
            health_status['stats']['disk_free_percent'] = round(free_percent, 2)
            health_status['stats']['disk_free_gb'] = round(free_bytes / (1024**3), 2)
            
            if free_percent < 10:
                alert = {
                    'type': 'disk_space',
                    'free_percent': round(free_percent, 2),
                    'message': f"Low disk space: {free_percent:.1f}% free"
                }
                alerts.append(alert)
                health_status['healthy'] = False
        
        health_status['alerts'] = alerts
        
        # Send email alerts if configured
        if alerts and settings.ALERT_EMAIL_ENABLED:
            send_health_alert_email(alerts)
        
        if not health_status['healthy']:
            logger.warning(f"Health check failed with {len(alerts)} alerts")
        else:
            logger.info("Health check passed: All systems healthy")
        
        return health_status
        
    except Exception as e:
        logger.exception(f"Error in monitor_pull_health: {e}")
        return {
            'healthy': False,
            'error': str(e)
        }


def send_health_alert_email(alerts: List[Dict]) -> None:
    """
    Send email alerts for health check issues.
    
    Args:
        alerts: List of alert dictionaries
    """
    try:
        if not settings.ALERT_EMAIL_RECIPIENTS:
            logger.warning("No alert email recipients configured")
            return
        
        subject = f"🚨 Streamflow DataOps: {len(alerts)} Health Alerts"
        
        message_lines = [
            "Raster Data Pull Health Check Alerts",
            "=" * 60,
            f"\nGenerated: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"\nTotal Alerts: {len(alerts)}\n",
        ]
        
        for i, alert in enumerate(alerts, 1):
            message_lines.append(f"\n{i}. {alert['type'].upper()}")
            message_lines.append(f"   {alert['message']}")
            
            if 'dataset' in alert:
                message_lines.append(f"   Dataset: {alert['dataset']}")
            
            if 'hours_since_pull' in alert:
                message_lines.append(f"   Hours since last pull: {alert['hours_since_pull']}")
            
            if 'failure_count' in alert:
                message_lines.append(f"   Consecutive failures: {alert['failure_count']}")
        
        message_lines.extend([
            "\n" + "=" * 60,
            "\nPlease investigate these issues in the Django admin:",
            f"{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost'}/admin/",
            "\nOr check Flower monitoring:",
            f"{settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost'}:5555/",
        ])
        
        message = "\n".join(message_lines)
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.ALERT_EMAIL_FROM,
            recipient_list=[r.strip() for r in settings.ALERT_EMAIL_RECIPIENTS if r.strip()],
            fail_silently=False,
        )
        
        logger.info(f"Sent alert email to {len(settings.ALERT_EMAIL_RECIPIENTS)} recipients")
        
    except Exception as e:
        logger.exception(f"Error sending alert email: {e}")


@shared_task
def generate_health_report() -> Dict:
    """
    Generate comprehensive health report for all raster data sources.
    
    Returns:
        Dictionary with detailed statistics
    """
    try:
        report = {
            'generated_at': timezone.now().isoformat(),
            'datasets': {},
            'overall_stats': {},
        }
        
        # Overall statistics
        report['overall_stats'] = {
            'total_datasets': RasterDataset.objects.count(),
            'active_datasets': RasterDataset.objects.filter(is_active=True).count(),
            'total_variables': RasterVariable.objects.count(),
            'total_layers': RasterLayer.objects.count(),
            'total_pulls': RasterPullLog.objects.count(),
            'recent_pulls_24h': RasterPullLog.objects.filter(
                started_at__gte=timezone.now() - timedelta(days=1)
            ).count(),
        }
        
        # Per-dataset statistics
        for dataset in RasterDataset.objects.all():
            dataset_stats = {
                'name': dataset.name,
                'data_source': dataset.data_source,
                'is_active': dataset.is_active,
                'variables': dataset.variables.count(),
                'total_layers': RasterLayer.objects.filter(variable__dataset=dataset).count(),
                'recent_layers_7d': RasterLayer.objects.filter(
                    variable__dataset=dataset,
                    timestamp__gte=timezone.now() - timedelta(days=7)
                ).count(),
            }
            
            # Last successful pull
            last_pull = RasterPullLog.objects.filter(
                configuration__dataset=dataset,
                status='completed'
            ).order_by('-completed_at').first()
            
            if last_pull:
                dataset_stats['last_successful_pull'] = last_pull.completed_at.isoformat()
                dataset_stats['hours_since_pull'] = round(
                    (timezone.now() - last_pull.completed_at).total_seconds() / 3600,
                    2
                )
            else:
                dataset_stats['last_successful_pull'] = None
                dataset_stats['hours_since_pull'] = None
            
            # Recent pull success rate
            recent_pulls = RasterPullLog.objects.filter(
                configuration__dataset=dataset,
                started_at__gte=timezone.now() - timedelta(days=7)
            )
            
            if recent_pulls.exists():
                success_count = recent_pulls.filter(status='completed').count()
                total_count = recent_pulls.count()
                dataset_stats['success_rate_7d'] = round((success_count / total_count) * 100, 2)
            else:
                dataset_stats['success_rate_7d'] = None
            
            report['datasets'][dataset.name] = dataset_stats
        
        logger.info("Generated comprehensive health report")
        return report
        
    except Exception as e:
        logger.exception(f"Error generating health report: {e}")
        return {'error': str(e)}
