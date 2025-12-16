"""Smart Append Logic implementation for incremental data pulls."""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from src.database.repositories import PullStationProgressRepository
import logging

logger = logging.getLogger(__name__)


class SmartAppendLogic:
    """
    Implements the Smart Append Logic for determining data pull start dates.
    
    Logic:
    - First pull for a station: Use pullConfiguration.pull_start_date
    - Subsequent pulls: Use pullStationProgress.last_successful_pull_date
    - This ensures complete initial download, then efficient incremental updates
    
    Benefits:
    - Avoids pulling duplicate data
    - Reduces API calls and processing time
    - Enables resumption after failures
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.progress_repo = PullStationProgressRepository(db)
        self.logger = logging.getLogger(__name__)
    
    def get_pull_start_date(self, 
                            config_id: int, 
                            station_number: str,
                            config_start_date: datetime) -> datetime:
        """
        Determine the start date for data pull based on Smart Append Logic.
        
        Args:
            config_id: Pull configuration ID
            station_number: Station identifier
            config_start_date: The pull_start_date from configuration
        
        Returns:
            Start date to use for data pull request
        """
        # Check if we have previous progress for this station
        progress = self.progress_repo.get_progress(config_id, station_number)
        
        if progress is None or progress.last_successful_pull_date is None:
            # First pull - use configuration start date
            self.logger.info(
                f"First pull for station {station_number} in config {config_id} "
                f"- using config start date: {config_start_date}"
            )
            return config_start_date
        else:
            # Subsequent pull - use last successful pull date
            last_date = progress.last_successful_pull_date
            self.logger.info(
                f"Subsequent pull for station {station_number} in config {config_id} "
                f"- using last pull date: {last_date}"
            )
            return last_date
    
    def update_pull_progress(self,
                            config_id: int,
                            station_number: str,
                            successful_pull_date: datetime) -> None:
        """
        Update progress after successful data pull.
        
        Args:
            config_id: Pull configuration ID
            station_number: Station identifier
            successful_pull_date: The latest date successfully pulled
        """
        self.progress_repo.update_progress(
            config_id=config_id,
            station_number=station_number,
            last_pull_date=successful_pull_date
        )
        self.logger.info(
            f"Updated progress for station {station_number} in config {config_id} "
            f"to {successful_pull_date}"
        )
    
    def get_all_progress(self, config_id: int) -> list:
        """
        Get all progress records for a configuration.
        
        Args:
            config_id: Pull configuration ID
        
        Returns:
            List of progress records
        """
        return self.progress_repo.get_all_for_config(config_id)
    
    def reset_station_progress(self, config_id: int, station_number: str) -> None:
        """
        Reset progress for a station (useful for re-pulling all data).
        
        Args:
            config_id: Pull configuration ID
            station_number: Station identifier
        """
        progress = self.progress_repo.get_progress(config_id, station_number)
        if progress:
            # Update to None to force full re-pull
            self.progress_repo.update_progress(
                config_id=config_id,
                station_number=station_number,
                last_pull_date=None
            )
            self.logger.info(
                f"Reset progress for station {station_number} in config {config_id}"
            )
