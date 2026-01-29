"""Celery tasks for automated raster data pulls."""

import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from celery import shared_task
from django.utils import timezone
from django.conf import settings

from apps.streamflow.models import (
    RasterPullConfiguration,
    RasterPullLog,
    RasterLayer,
    RasterVariable,
    RasterDataset,
    SpatialExtent
)
from src.acquisition.gee_client import GEEClient, GEEClientError
from src.acquisition.earthdata_client import EarthDataClient, EarthDataError
from src.acquisition.nomads_client import NomadsClient, NomadsError
from src.acquisition.nomads_stage4_client import Stage4QPEClient, Stage4Error
from src.acquisition.raster_processor import RasterProcessor, RasterProcessorError

logger = logging.getLogger(__name__)

# Import monitoring tasks
from src.acquisition.monitoring_tasks import (
    cleanup_old_layers,
    cleanup_old_pull_logs,
    monitor_pull_health,
    generate_health_report
)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def pull_raster_data(self, config_id: int, start_date: Optional[str] = None, 
                     end_date: Optional[str] = None, pull_log_id: Optional[int] = None) -> Dict:
    """
    Pull raster data for a configuration.
    
    Args:
        config_id: RasterPullConfiguration ID
        start_date: Optional start date (ISO format)
        end_date: Optional end date (ISO format)
        pull_log_id: Optional existing RasterPullLog ID (created by trigger view)
        
    Returns:
        Dictionary with pull statistics
    """
    try:
        config = RasterPullConfiguration.objects.get(id=config_id)
    except RasterPullConfiguration.DoesNotExist:
        logger.error(f"Configuration not found: {config_id}")
        return {'error': 'Configuration not found'}
    
    # Get task ID (may be None if running synchronously)
    task_id = self.request.id if self and hasattr(self, 'request') else None
    
    # Use existing pull log if provided, otherwise create new one
    if pull_log_id:
        try:
            pull_log = RasterPullLog.objects.get(id=pull_log_id)
            pull_log.status = 'running'
            pull_log.started_at = timezone.now()  # Update with actual start time
            if task_id:
                pull_log.celery_task_id = task_id
            pull_log.save()
        except RasterPullLog.DoesNotExist:
            logger.warning(f"Pull log {pull_log_id} not found, creating new one")
            pull_log = RasterPullLog.objects.create(
                configuration=config,
                status='running',
                started_at=timezone.now(),
                celery_task_id=task_id or ''
            )
    else:
        # Create new pull log
        pull_log = RasterPullLog.objects.create(
            configuration=config,
            status='running',
            started_at=timezone.now(),
            celery_task_id=task_id or ''
        )
    
    # Wrap entire task in try-catch to ensure log is always updated
    try:
        logger.info(f"Starting raster pull for config {config.name} (ID: {config_id})")
        
        # Initialize clients (will be created per data source)
        processor = RasterProcessor()
        
        # Determine date range
        if start_date and end_date:
            # Parse ISO format strings and make timezone-aware
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
            # Ensure timezone-aware
            if start_dt.tzinfo is None:
                start_dt = timezone.make_aware(start_dt)
            if end_dt.tzinfo is None:
                end_dt = timezone.make_aware(end_dt)
        else:
            # Use lookback days
            end_dt = timezone.now()
            start_dt = end_dt - timedelta(days=config.lookback_days)
        
        logger.info(f"Pull date range: {start_dt} to {end_dt}")
        
        # Get variables and extents
        variables = config.variables.all()
        extents = config.extents.all()
        
        if not variables.exists() or not extents.exists():
            raise ValueError("Configuration has no variables or extents")
        
        stats = {
            'attempted': 0,
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }
        
        # Pull data for each variable and extent
        for variable in variables:
            for extent in extents:
                try:
                    result = _pull_variable_extent(
                        processor,
                        config,
                        variable,
                        extent,
                        start_dt,
                        end_dt
                    )
                    stats['attempted'] += result['attempted']
                    stats['successful'] += result['successful']
                    stats['failed'] += result['failed']
                    stats['skipped'] += result['skipped']
                    
                except Exception as e:
                    error_msg = f"Error pulling {variable.name} for {extent.name}: {str(e)}"
                    logger.error(error_msg)
                    stats['errors'].append(error_msg)
                    stats['failed'] += 1
        
        # Update pull log
        pull_log.completed_at = timezone.now()
        pull_log.layers_attempted = stats['attempted']
        pull_log.layers_successful = stats['successful']
        pull_log.layers_failed = stats['failed']
        pull_log.layers_skipped = stats['skipped']
        
        if stats['successful'] > 0 and stats['failed'] == 0:
            pull_log.status = 'success'
        elif stats['successful'] > 0:
            pull_log.status = 'partial'
        else:
            pull_log.status = 'failed'
            
        if stats['errors']:
            pull_log.warnings = {'errors': stats['errors'][:100]}  # Limit error list
        
        pull_log.calculate_duration()
        pull_log.save()
        
        # Update configuration
        if stats['successful'] > 0:
            config.last_successful_pull = timezone.now()
        config.last_pull_attempt = timezone.now()
        config.save()
        
        logger.info(f"Pull complete: {stats['successful']}/{stats['attempted']} successful")
        return stats
        
    except Exception as e:
        logger.exception(f"Error in pull_raster_data: {e}")
        
        # Update pull log with full error details
        import traceback
        pull_log.completed_at = timezone.now()
        pull_log.status = 'failed'
        pull_log.error_message = str(e)
        pull_log.error_traceback = traceback.format_exc()
        pull_log.calculate_duration()
        pull_log.save()
        
        # Update config last attempt time
        config.last_pull_attempt = timezone.now()
        config.save()
        
        # Retry task if retries available
        if self and hasattr(self, 'request') and self.request.retries < self.max_retries:
            try:
                raise self.retry(exc=e)
            except Exception:
                pass  # MaxRetriesExceededError or retry failed
        
        logger.error(f"Task failed for config {config_id}, retries: {self.request.retries if self and hasattr(self, 'request') else 0}")
        return {'error': str(e), 'retries_exceeded': True}


def _pull_variable_extent(
    processor: RasterProcessor,
    config: RasterPullConfiguration,
    variable: RasterVariable,
    extent: SpatialExtent,
    start_dt: datetime,
    end_dt: datetime
) -> Dict:
    """
    Pull data for a specific variable and extent.
    
    Routes to appropriate client based on dataset data_source.
    
    Returns:
        Dictionary with pull statistics
    """
    stats = {'attempted': 0, 'successful': 0, 'failed': 0, 'skipped': 0}
    
    dataset = variable.dataset
    bbox = extent.bbox
    
    # Initialize appropriate client based on data source
    client = None
    if dataset.data_source == 'earthdata':
        try:
            client = EarthDataClient()
        except EarthDataError as e:
            logger.error(f"Failed to initialize EarthDataClient: {e}")
            return stats
    elif dataset.data_source == 'nomads':
        try:
            client = NomadsClient()
        except NomadsError as e:
            logger.error(f"Failed to initialize NomadsClient: {e}")
            return stats
    elif dataset.data_source == 'gee':
        try:
            client = GEEClient()
        except GEEClientError as e:
            logger.error(f"Failed to initialize GEEClient: {e}")
            return stats
    else:
        logger.error(f"Unsupported data source: {dataset.data_source}")
        return stats
    
    # Determine temporal resolution
    if dataset.temporal_resolution == 'hourly':
        # Pull hourly data
        current_dt = start_dt.replace(minute=0, second=0, microsecond=0)
        while current_dt <= end_dt:
            stats['attempted'] += 1
            
            try:
                success = _pull_single_layer(
                    client,
                    processor,
                    config,
                    variable,
                    extent,
                    current_dt,
                    bbox
                )
                if success:
                    stats['successful'] += 1
                else:
                    stats['skipped'] += 1
                    
            except Exception as e:
                logger.error(f"Error pulling {variable.name} at {current_dt}: {e}")
                stats['failed'] += 1
            
            current_dt += timedelta(hours=1)
            
    elif dataset.temporal_resolution == 'daily':
        # Pull daily data
        current_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        while current_dt <= end_dt:
            stats['attempted'] += 1
            
            try:
                success = _pull_single_layer(
                    client,
                    processor,
                    config,
                    variable,
                    extent,
                    current_dt,
                    bbox
                )
                if success:
                    stats['successful'] += 1
                else:
                    stats['skipped'] += 1
                    
            except Exception as e:
                logger.error(f"Error pulling {variable.name} at {current_dt}: {e}")
                stats['failed'] += 1
            
            current_dt += timedelta(days=1)
    
    return stats


def _pull_single_layer(
    client,  # Can be EarthDataClient or GEEClient
    processor: RasterProcessor,
    config: RasterPullConfiguration,
    variable: RasterVariable,
    extent: SpatialExtent,
    timestamp: datetime,
    bbox: List[float]
) -> bool:
    """
    Pull a single raster layer using appropriate client.
    
    Returns:
        True if pulled successfully, False if skipped
    """
    # Check if layer already exists
    existing = RasterLayer.objects.filter(
        variable=variable,
        extent=extent,
        timestamp=timestamp
    ).first()
    
    if existing and existing.is_valid:
        logger.debug(f"Layer already exists: {variable.name} at {timestamp}")
        return False  # Skipped
    
    # Fetch data based on client type
    dataset = variable.dataset
    file_path = _generate_file_path(variable, extent, timestamp)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Route to appropriate data fetching method
    if dataset.data_source == 'earthdata':
        success = _fetch_earthdata_layer(
            client,
            dataset,
            variable,
            timestamp,
            bbox,
            file_path,
            config
        )
    elif dataset.data_source == 'nomads':
        success = _fetch_nomads_layer(
            client,
            dataset,
            variable,
            timestamp,
            bbox,
            file_path,
            config
        )
    elif dataset.data_source == 'gee':
        success = _fetch_gee_layer(
            client,
            dataset,
            variable,
            timestamp,
            bbox,
            file_path,
            config
        )
    else:
        logger.error(f"Unsupported data source: {dataset.data_source}")
        return False
    
    if not success:
        return False
    
    # Process raster
    process_start = timezone.now()
    
    # Calculate statistics
    stats = processor.calculate_statistics(file_path)
    
    # Validate
    is_valid, errors = processor.validate_raster(
        file_path,
        expected_bbox=bbox,
        expected_crs='EPSG:4326',
        min_value=variable.min_valid_value,
        max_value=variable.max_valid_value
    )
    
    # Compress if configured
    if config.apply_compression:
        file_path = processor.compress_raster(
            file_path,
            compression='LZW'  # Default compression method
        )
    
    # Generate thumbnail if configured
    thumbnail_path = None
    if getattr(config, 'generate_thumbnails', False):
        thumbnail_path = processor.generate_thumbnail(file_path)
    
    process_time = (timezone.now() - process_start).total_seconds()
    
    # Create or update RasterLayer record
    if existing:
        layer = existing
    else:
        layer = RasterLayer()
    
    layer.variable = variable
    layer.extent = extent
    layer.timestamp = timestamp
    layer.date = timestamp.date()
    layer.file_path = str(file_path.relative_to(settings.RASTER_ROOT))
    layer.file_size_bytes = file_path.stat().st_size
    layer.format = 'GeoTIFF'
    layer.compression = 'lzw' if config.apply_compression else None
    layer.resolution_m = stats['resolution'][0]
    layer.width_pixels = stats['width']
    layer.height_pixels = stats['height']
    layer.crs = stats['crs']
    layer.min_value = stats['min_value']
    layer.max_value = stats['max_value']
    layer.mean_value = stats['mean_value']
    layer.std_dev = stats['std_dev']
    layer.no_data_value = stats['nodata']
    layer.is_valid = is_valid
    layer.validation_errors = errors if not is_valid else None
    layer.processing_time_seconds = process_time
    layer.thumbnail_path = str(thumbnail_path.relative_to(settings.RASTER_ROOT)) if thumbnail_path else None
    layer.save()
    
    logger.info(f"Successfully pulled layer: {variable.name} at {timestamp} ({layer.file_size_bytes} bytes)")
    return True


def _fetch_earthdata_layer(
    client: EarthDataClient,
    dataset,
    variable,
    timestamp: datetime,
    bbox: List[float],
    file_path: Path,
    config
) -> bool:
    """Fetch layer from NASA EarthData."""
    try:
        # Map variable names to EarthData variable names
        if 'SPL4SMGP' in dataset.collection_id or 'SMAP' in dataset.name:
            # SMAP L4 Soil Moisture
            # Map variable names to SMAP variable names expected by earthdata_client
            smap_var_map = {
                'sm_surface': 'soil_moisture_surface',
                'sm_rootzone': 'soil_moisture_rootzone',
                'sm_profile': 'soil_moisture_surface',  # Use surface as fallback
                'soil_moisture_surface': 'soil_moisture_surface',
                'soil_moisture_rootzone': 'soil_moisture_rootzone'
            }
            smap_var = smap_var_map.get(variable.name, variable.gee_band_name or 'soil_moisture_surface')
            
            metadata = client.get_smap_data(
                variable=smap_var,
                date=timestamp,
                bbox=bbox,
                output_path=file_path
            )
            
        elif 'GPM' in dataset.collection_id or 'IMERG' in dataset.collection_id or 'GPM' in dataset.name:
            metadata = client.get_gpm_data(
                date=timestamp,
                bbox=bbox,
                output_path=file_path
            )
            
        elif 'MOD11A1' in dataset.collection_id or 'MYD11A1' in dataset.collection_id:
            # MODIS Land Surface Temperature
            # Determine product from collection_id
            product = 'MOD11A1' if 'MOD11A1' in dataset.collection_id else 'MYD11A1'
            
            # Map variable names to MODIS variable names
            modis_var_map = {
                'lst_day': 'LST_Day_1km',
                'lst_night': 'LST_Night_1km',
                'land_surface_temperature_day': 'LST_Day_1km',
                'land_surface_temperature_night': 'LST_Night_1km'
            }
            modis_var = modis_var_map.get(variable.name, variable.gee_band_name or 'LST_Day_1km')
            
            metadata = client.get_modis_data(
                product=product,
                variable=modis_var,
                date=timestamp,
                bbox=bbox,
                output_path=file_path
            )
            
        else:
            logger.warning(f"Unknown EarthData dataset: {dataset.collection_id}")
            return False
        
        if metadata is None:
            logger.warning(f"No EarthData data available for {variable.name} at {timestamp}")
            return False
        
        logger.info(f"EarthData fetch complete: {metadata}")
        return True
        
    except EarthDataError as e:
        logger.error(f"EarthData fetch failed: {e}")
        return False


def _fetch_gee_layer(
    client: GEEClient,
    dataset,
    variable,
    timestamp: datetime,
    bbox: List[float],
    file_path: Path,
    config
) -> bool:
    """Fetch layer from Google Earth Engine (legacy)."""
    try:
        if 'RTMA' in dataset.collection_id:
            # Map variable name to RTMA variable
            rtma_var_map = {
                'temperature': 'temperature',
                'precipitation': 'precipitation',
                'wind_speed': 'wind_speed'
            }
            rtma_var = rtma_var_map.get(variable.name)
            if not rtma_var:
                logger.warning(f"Unknown RTMA variable: {variable.name}")
                return False
            
            image = client.get_rtma_image(
                variable=rtma_var,
                timestamp=timestamp,
                bbox=bbox,
                resolution=config.target_resolution_m or dataset.resolution_m
            )
            
        elif 'SMAP' in dataset.collection_id:
            # Map variable name to SMAP variable
            smap_var_map = {
                'soil_moisture_surface': 'soil_moisture_surface',
                'soil_moisture_rootzone': 'soil_moisture_rootzone'
            }
            smap_var = smap_var_map.get(variable.name)
            if not smap_var:
                logger.warning(f"Unknown SMAP variable: {variable.name}")
                return False
            
            image = client.get_smap_image(
                variable=smap_var,
                date=timestamp.date(),
                bbox=bbox,
                resolution=config.target_resolution_m or dataset.resolution_m
            )
        else:
            logger.warning(f"Unknown GEE dataset: {dataset.collection_id}")
            return False
        
        if image is None:
            logger.warning(f"No GEE data available for {variable.name} at {timestamp}")
            return False
        
        # Export to GeoTIFF
        metadata = client.export_to_geotiff(
            image=image,
            output_path=file_path,
            bbox=bbox,
            scale=config.target_resolution_m or dataset.resolution_m,
            crs='EPSG:4326'
        )
        
        logger.info(f"GEE fetch complete: {metadata}")
        return True
        
    except GEEClientError as e:
        logger.error(f"GEE fetch failed: {e}")
        return False


def _fetch_nomads_layer(
    client: NomadsClient,
    dataset,
    variable,
    timestamp: datetime,
    bbox: List[float],
    file_path: Path,
    config
) -> bool:
    """Fetch layer from NOAA NOMADS."""
    try:
        # Map variable names to NOMADS variable names
        if 'rtma' in dataset.collection_id.lower():
            var_map = {
                'temperature': 'temperature',
                'tmp2m': 'temperature',  # 2m temperature
                'dpt2m': 'temperature',  # dewpoint temperature (treated as temp for now)
                'precipitation': 'precipitation',
                'wind_speed': 'wind_speed',
                'wind_u': 'wind_u',
                'wind_v': 'wind_v',
                'ugrd10m': 'wind_u',  # U-component at 10m
                'vgrd10m': 'wind_v',  # V-component at 10m
                'pressure': 'pressure',
                'pres': 'pressure'  # surface pressure
            }
            nomads_var = var_map.get(variable.name, variable.gee_band_name)
            
            metadata = client.get_rtma_data(
                variable=nomads_var,
                timestamp=timestamp,
                bbox=bbox,
                output_path=file_path
            )
            
        elif 'pcpanl' in dataset.collection_id.lower() or 'stage4' in dataset.name.lower() or 'stage_iv' in dataset.name.lower():
            # NCEP Stage IV QPE
            stage4_client = Stage4QPEClient()
            
            # Determine accumulation period based on variable name
            if variable.name in ['precip_1hr', 'apcp_1hr', 'precipitation_1hr', 'precipitation_1-hour']:
                metadata = stage4_client.get_hourly_precip(
                    timestamp=timestamp,
                    bbox=bbox,
                    output_path=file_path
                )
            elif variable.name in ['precip_6hr', 'apcp_6hr', 'precipitation_6hr', 'precipitation_6-hour']:
                metadata = stage4_client.get_6hourly_precip(
                    timestamp=timestamp,
                    bbox=bbox,
                    output_path=file_path
                )
            else:
                logger.warning(f"Unknown Stage IV variable: {variable.name}")
                return False
            
        else:
            logger.warning(f"Unknown NOMADS dataset: {dataset.collection_id}")
            return False
        
        if metadata is None:
            logger.warning(f"No NOMADS data available for {variable.name} at {timestamp}")
            return False
        
        logger.info(f"NOMADS fetch complete: {metadata}")
        return True
        
    except (NomadsError, Stage4Error) as e:
        logger.error(f"NOMADS fetch failed: {e}")
        return False


def _generate_file_path(variable: RasterVariable, extent: SpatialExtent, timestamp: datetime) -> Path:
    """Generate file path for raster layer."""
    dataset = variable.dataset
    
    # Extract dataset name from collection ID (works for both GEE and EarthData)
    if '/' in dataset.collection_id:
        # GEE format: NOAA/NWS/RTMA
        dataset_name = dataset.collection_id.split('/')[-1]
    else:
        # EarthData format: SPL4SMGP_008
        dataset_name = dataset.collection_id
    
    # Format timestamp
    if dataset.temporal_resolution == 'hourly':
        time_str = timestamp.strftime('%Y%m%d_%H%MZ')
    else:
        time_str = timestamp.strftime('%Y%m%d')
    
    # Build path
    raster_root = Path(settings.RASTER_ROOT)
    file_path = raster_root / dataset_name / variable.name / extent.name / str(timestamp.year) / f"{timestamp.month:02d}" / f"{dataset_name}_{variable.name}_{extent.name}_{time_str}.tif"
    
    return file_path


@shared_task
def process_raster_file(layer_id: int) -> Dict:
    """
    Process an existing raster file (validation, statistics, compression).
    
    Args:
        layer_id: RasterLayer ID
        
    Returns:
        Dictionary with processing results
    """
    try:
        layer = RasterLayer.objects.get(id=layer_id)
    except RasterLayer.DoesNotExist:
        return {'error': 'Layer not found'}
    
    try:
        processor = RasterProcessor()
        file_path = Path(settings.RASTER_ROOT) / layer.file_path
        
        if not file_path.exists():
            return {'error': 'File not found'}
        
        # Calculate statistics
        stats = processor.calculate_statistics(file_path)
        
        # Validate
        is_valid, errors = processor.validate_raster(file_path)
        
        # Update layer
        layer.width_pixels = stats['width']
        layer.height_pixels = stats['height']
        layer.min_value = stats['min_value']
        layer.max_value = stats['max_value']
        layer.mean_value = stats['mean_value']
        layer.std_dev = stats['std_dev']
        layer.is_valid = is_valid
        layer.validation_errors = errors if not is_valid else None
        layer.save()
        
        logger.info(f"Processed raster layer {layer_id}")
        return {'success': True, 'is_valid': is_valid}
        
    except Exception as e:
        logger.exception(f"Error processing raster layer {layer_id}: {e}")
        return {'error': str(e)}


@shared_task
def cleanup_old_rasters(days: int = 365, dry_run: bool = False) -> Dict:
    """
    Clean up old raster files.
    
    Args:
        days: Delete rasters older than this many days
        dry_run: If True, don't actually delete
        
    Returns:
        Dictionary with cleanup statistics
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=days)
        
        old_layers = RasterLayer.objects.filter(timestamp__lt=cutoff_date)
        
        stats = {
            'count': old_layers.count(),
            'size_bytes': 0,
            'deleted': 0,
            'errors': []
        }
        
        for layer in old_layers:
            file_path = Path(settings.RASTER_ROOT) / layer.file_path
            
            if file_path.exists():
                stats['size_bytes'] += file_path.stat().st_size
                
                if not dry_run:
                    try:
                        file_path.unlink()
                        
                        # Delete thumbnail if exists
                        if layer.thumbnail_path:
                            thumb_path = Path(settings.RASTER_ROOT) / layer.thumbnail_path
                            if thumb_path.exists():
                                thumb_path.unlink()
                        
                        layer.delete()
                        stats['deleted'] += 1
                        
                    except Exception as e:
                        error_msg = f"Error deleting {file_path}: {str(e)}"
                        logger.error(error_msg)
                        stats['errors'].append(error_msg)
        
        mode = "DRY RUN" if dry_run else "DELETED"
        logger.info(f"Cleanup {mode}: {stats['deleted']}/{stats['count']} files ({stats['size_bytes']} bytes)")
        
        return stats
        
    except Exception as e:
        logger.exception(f"Error in cleanup_old_rasters: {e}")
        return {'error': str(e)}


@shared_task
def scheduled_raster_pulls(
    data_source: Optional[str] = None,
    dataset_name: Optional[str] = None
) -> Dict:
    """
    Run scheduled raster pulls for specific data source or dataset.
    
    Called by Celery Beat on different schedules for different data sources.
    
    Args:
        data_source: Filter by data source (earthdata, nomads, gee)
        dataset_name: Filter by specific dataset name
    
    Returns:
        Dictionary with execution statistics
    """
    try:
        # Build query for active configurations
        query = {'is_active': True}
        
        if dataset_name:
            # Get dataset by name
            try:
                dataset = RasterDataset.objects.get(name=dataset_name)
                query['dataset'] = dataset
                logger.info(f"Running scheduled pulls for dataset: {dataset_name}")
            except RasterDataset.DoesNotExist:
                logger.error(f"Dataset not found: {dataset_name}")
                return {'error': f'Dataset not found: {dataset_name}'}
        
        elif data_source:
            # Get all datasets for this data source
            datasets = RasterDataset.objects.filter(
                data_source=data_source,
                is_active=True
            )
            if not datasets.exists():
                logger.warning(f"No active datasets found for data source: {data_source}")
                return {'configs_total': 0, 'configs_run': 0}
            
            query['dataset__in'] = datasets
            logger.info(f"Running scheduled pulls for data source: {data_source} ({datasets.count()} datasets)")
        
        # Get matching configurations
        configs = RasterPullConfiguration.objects.filter(**query)
        
        stats = {
            'data_source': data_source,
            'dataset_name': dataset_name,
            'configs_total': configs.count(),
            'configs_queued': 0,
            'configs_skipped': 0,
            'configs_failed': 0,
        }
        
        for config in configs:
            try:
                # Queue pull task
                pull_raster_data.delay(config.id)
                stats['configs_queued'] += 1
                logger.info(f"Queued pull task for {config.name} (Dataset: {config.dataset.name})")
                
            except Exception as e:
                logger.error(f"Error queueing pull for {config.name}: {e}")
                stats['configs_failed'] += 1
        
        logger.info(
            f"Scheduled pulls complete: {stats['configs_queued']} queued, "
            f"{stats['configs_skipped']} skipped, {stats['configs_failed']} failed"
        )
        return stats
        
    except Exception as e:
        logger.exception(f"Error in scheduled_raster_pulls: {e}")
        return {'error': str(e)}

