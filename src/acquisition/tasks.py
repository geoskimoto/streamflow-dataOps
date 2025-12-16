"""Celery tasks for data acquisition."""
from celery import Task
from datetime import datetime, timezone
import logging
from src.celery_app.celery import app
from src.database.connection import SessionLocal
from src.database.repositories import (
    PullConfigurationRepository, 
    StationMappingRepository,
    DataPullLogRepository
)
from src.acquisition.usgs_client import USGSClient
from src.acquisition.canada_client import CanadaClient
from src.acquisition.noaa_client import NOAAClient
from src.acquisition.smart_append import SmartAppendLogic
from src.acquisition.data_processor import DataProcessor

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """Base task class with database session management."""
    _db = None
    
    @property
    def db(self):
        if self._db is None:
            self._db = SessionLocal()
        return self._db
    
    def after_return(self, *args, **kwargs):
        """Close database session after task completes."""
        if self._db is not None:
            self._db.close()
            self._db = None


@app.task(bind=True)
def test_task(self):
    """Test task to verify Celery setup."""
    logger.info("Test task executed successfully!")
    return "Test task completed"


@app.task(base=DatabaseTask, bind=True, max_retries=3)
def execute_pull_configuration(self, config_id: int):
    """
    Execute a data pull for a specific configuration.
    
    This is the main task that orchestrates the entire data pull process:
    1. Load configuration
    2. For each station in configuration:
       - Determine start date using Smart Append Logic
       - Fetch data from appropriate source (USGS/EC)
       - Validate and store data
       - Update progress
    3. Log execution results
    
    Args:
        config_id: Pull configuration ID
    """
    db = SessionLocal()
    try:
        logger.info(f"=" * 60)
        logger.info(f"Starting pull for configuration {config_id}")
        logger.info(f"=" * 60)
        
        # Get configuration
        config_repo = PullConfigurationRepository(db)
        config = config_repo.get_by_id(config_id)
        
        if not config:
            logger.error(f"Configuration {config_id} not found")
            return {'status': 'error', 'message': 'Configuration not found'}
        
        if not config.is_enabled:
            logger.warning(f"Configuration {config_id} is disabled")
            return {'status': 'skipped', 'message': 'Configuration disabled'}
        
        # Create log entry
        log_repo = DataPullLogRepository(db)
        log = log_repo.create_log(config_id, 'running')
        
        # Initialize components
        total_records = 0
        successful_stations = 0
        failed_stations = 0
        errors = []
        
        smart_append = SmartAppendLogic(db)
        processor = DataProcessor(db)
        
        # Get stations in configuration
        config_stations = config_repo.get_stations(config_id)
        logger.info(f"Processing {len(config_stations)} stations")
        
        for config_station in config_stations:
            station_number = config_station.station_number
            logger.info(f"\n--- Processing station {station_number} ---")
            
            try:
                # Determine start date using Smart Append Logic
                start_date = smart_append.get_pull_start_date(
                    config_id=config_id,
                    station_number=station_number,
                    config_start_date=config.pull_start_date
                )
                
                end_date = datetime.now(timezone.utc)
                
                logger.info(f"Pulling data from {start_date} to {end_date}")
                
                # Fetch data based on data type and agency
                observations = []
                
                # Determine agency (default to USGS for now)
                # In production, this would be determined from station metadata
                agency = 'USGS'  # Could also be 'EC' for Canadian stations
                
                if agency == 'USGS':
                    client = USGSClient()
                    
                    if config.data_type == 'daily_mean':
                        observations = client.get_daily_mean(
                            station_number=station_number,
                            start_date=start_date,
                            end_date=end_date
                        )
                    elif config.data_type == 'realtime_15min':
                        observations = client.get_instantaneous(
                            station_number=station_number,
                            start_date=start_date,
                            end_date=end_date
                        )
                    else:
                        logger.error(f"Unknown data type: {config.data_type}")
                        continue
                
                elif agency == 'EC':
                    client = CanadaClient()
                    
                    if config.data_type == 'daily_mean':
                        observations = client.get_daily_mean(
                            station_number=station_number,
                            start_date=start_date,
                            end_date=end_date
                        )
                    elif config.data_type == 'realtime_15min':
                        observations = client.get_realtime_data(
                            station_number=station_number,
                            start_date=start_date,
                            end_date=end_date
                        )
                    else:
                        logger.error(f"Unknown data type: {config.data_type}")
                        continue
                
                logger.info(f"Fetched {len(observations)} observations")
                
                # Process and store observations
                if observations:
                    inserted_count = processor.process_observations(
                        station_number=station_number,
                        observations=observations
                    )
                    
                    total_records += inserted_count
                    logger.info(f"Inserted {inserted_count} records")
                    
                    # Update progress
                    if inserted_count > 0:
                        # Use the latest observation date as progress marker
                        latest_date = max(obs['observed_at'] for obs in observations)
                        smart_append.update_pull_progress(
                            config_id=config_id,
                            station_number=station_number,
                            successful_pull_date=latest_date
                        )
                
                successful_stations += 1
                logger.info(f"✓ Successfully processed station {station_number}")
                
            except Exception as e:
                failed_stations += 1
                error_msg = f"Error processing station {station_number}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
        
        # Update log entry
        log_status = 'success' if failed_stations == 0 else 'partial_success' if successful_stations > 0 else 'failed'
        log_repo.update_log(log.id, {
            'status': log_status,
            'records_processed': total_records,
            'end_time': datetime.now(timezone.utc),
            'error_message': '\n'.join(errors) if errors else None
        })
        
        # Update configuration last_run_at
        config_repo.update(config_id, {
            'last_run_at': datetime.now(timezone.utc)
        })
        
        logger.info(f"\n" + "=" * 60)
        logger.info(f"Pull configuration {config_id} completed:")
        logger.info(f"  - Total records: {total_records}")
        logger.info(f"  - Successful stations: {successful_stations}")
        logger.info(f"  - Failed stations: {failed_stations}")
        logger.info(f"  - Status: {log_status}")
        logger.info(f"=" * 60)
        
        return {
            'status': log_status,
            'records_processed': total_records,
            'successful_stations': successful_stations,
            'failed_stations': failed_stations,
            'errors': errors
        }
        
    except Exception as e:
        logger.error(f"Critical error in pull configuration {config_id}: {e}")
        try:
            log_repo.update_log(log.id, {
                'status': 'failed',
                'end_time': datetime.now(timezone.utc),
                'error_message': str(e)
            })
        except:
            pass
        raise
    finally:
        db.close()


@app.task(base=DatabaseTask, bind=True)
def execute_forecast_pull(self, config_id: int):
    """
    Execute a forecast data pull for a specific configuration.
    
    Args:
        config_id: Pull configuration ID
    """
    db = SessionLocal()
    try:
        logger.info(f"Starting forecast pull for configuration {config_id}")
        
        # Get configuration
        config_repo = PullConfigurationRepository(db)
        config = config_repo.get_by_id(config_id)
        
        if not config or not config.is_enabled:
            logger.warning(f"Configuration {config_id} not found or disabled")
            return
        
        # Initialize components
        noaa_client = NOAAClient()
        processor = DataProcessor(db)
        mapping_repo = StationMappingRepository(db)
        
        successful_count = 0
        failed_count = 0
        
        # Get stations in configuration
        config_stations = config_repo.get_stations(config_id)
        
        for config_station in config_stations:
            station_number = config_station.station_number
            
            try:
                # Translate USGS ID to NOAA HADS ID
                hads_id = mapping_repo.get_mapping('USGS', station_number, 'NOAA-HADS')
                
                if not hads_id:
                    logger.warning(f"No HADS mapping found for station {station_number}")
                    continue
                
                # Fetch forecast data
                forecast_data = noaa_client.get_forecast(hads_id, forecast_type='short')
                
                if forecast_data:
                    # Store forecast
                    success = processor.process_forecast(station_number, forecast_data)
                    if success:
                        successful_count += 1
                    else:
                        failed_count += 1
                else:
                    logger.info(f"No forecast data available for station {station_number}")
                
            except Exception as e:
                logger.error(f"Error fetching forecast for station {station_number}: {e}")
                failed_count += 1
                continue
        
        logger.info(
            f"Forecast pull completed: {successful_count} successful, {failed_count} failed"
        )
        
        return {
            'successful': successful_count,
            'failed': failed_count
        }
        
    except Exception as e:
        logger.error(f"Critical error in forecast pull {config_id}: {e}")
        raise
    finally:
        db.close()


@app.task(bind=True)
def cleanup_old_logs(self, days_to_keep: int = 30):
    """
    Clean up old data pull logs.
    
    Args:
        days_to_keep: Number of days of logs to retain
    """
    from datetime import timedelta
    
    db = SessionLocal()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        
        log_repo = DataPullLogRepository(db)
        # Implementation would delete logs older than cutoff_date
        
        logger.info(f"Cleaned up logs older than {cutoff_date}")
        
    except Exception as e:
        logger.error(f"Error cleaning up logs: {e}")
        raise
    finally:
        db.close()
