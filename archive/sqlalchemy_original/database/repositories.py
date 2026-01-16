"""Repository pattern for database operations."""

from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from src.database.models import (
    Station,
    DischargeObservation,
    ForecastRun,
    PullConfiguration,
    PullConfigurationStation,
    DataPullLog,
    PullStationProgress,
    MasterStation,
    StationMapping,
)


class StationRepository:
    """Repository for Station model."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, station_id: int) -> Optional[Station]:
        return self.db.query(Station).filter(Station.id == station_id).first()

    def get_by_station_number(self, station_number: str) -> Optional[Station]:
        return (
            self.db.query(Station)
            .filter(Station.station_number == station_number)
            .first()
        )

    def get_all(self, skip: int = 0, limit: int = 100) -> List[Station]:
        return self.db.query(Station).offset(skip).limit(limit).all()

    def create(self, station_data: Dict[str, Any]) -> Station:
        station = Station(**station_data)
        self.db.add(station)
        self.db.commit()
        self.db.refresh(station)
        return station

    def update(
        self, station_id: int, station_data: Dict[str, Any]
    ) -> Optional[Station]:
        station = self.get_by_id(station_id)
        if station:
            for key, value in station_data.items():
                setattr(station, key, value)
            self.db.commit()
            self.db.refresh(station)
        return station

    def delete(self, station_id: int) -> bool:
        station = self.get_by_id(station_id)
        if station:
            self.db.delete(station)
            self.db.commit()
            return True
        return False

    def search(
        self,
        query: Optional[str] = None,
        state: Optional[str] = None,
        huc_code: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> List[Station]:
        q = self.db.query(Station)

        if query:
            q = q.filter(
                or_(
                    Station.station_number.ilike(f"%{query}%"),
                    Station.name.ilike(f"%{query}%"),
                )
            )

        if state:
            q = q.filter(Station.state == state)

        if huc_code:
            q = q.filter(Station.huc_code.startswith(huc_code))

        if is_active is not None:
            q = q.filter(Station.is_active == is_active)

        return q.all()


class DischargeObservationRepository:
    """Repository for DischargeObservation model."""

    def __init__(self, db: Session):
        self.db = db

    def bulk_create(self, observations: List[Dict[str, Any]]) -> int:
        """Bulk insert observations, ignoring duplicates."""
        count = 0
        for obs_data in observations:
            # Check if exists
            existing = (
                self.db.query(DischargeObservation)
                .filter(
                    and_(
                        DischargeObservation.station_id == obs_data["station_id"],
                        DischargeObservation.observed_at == obs_data["observed_at"],
                        DischargeObservation.type == obs_data["type"],
                    )
                )
                .first()
            )

            if not existing:
                obs = DischargeObservation(**obs_data)
                self.db.add(obs)
                count += 1

        self.db.commit()
        return count

    def get_by_station(
        self,
        station_id: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        data_type: Optional[str] = None,
    ) -> List[DischargeObservation]:
        q = self.db.query(DischargeObservation).filter(
            DischargeObservation.station_id == station_id
        )

        if start_date:
            q = q.filter(DischargeObservation.observed_at >= start_date)

        if end_date:
            q = q.filter(DischargeObservation.observed_at <= end_date)

        if data_type:
            q = q.filter(DischargeObservation.type == data_type)

        return q.order_by(DischargeObservation.observed_at).all()

    def get_latest_observation(
        self, station_id: int, data_type: str
    ) -> Optional[DischargeObservation]:
        """Get the most recent observation for a station."""
        return (
            self.db.query(DischargeObservation)
            .filter(
                and_(
                    DischargeObservation.station_id == station_id,
                    DischargeObservation.type == data_type,
                )
            )
            .order_by(DischargeObservation.observed_at.desc())
            .first()
        )


class PullConfigurationRepository:
    """Repository for PullConfiguration model."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, config_id: int) -> Optional[PullConfiguration]:
        return (
            self.db.query(PullConfiguration)
            .filter(PullConfiguration.id == config_id)
            .first()
        )

    def get_all(self, enabled_only: bool = False) -> List[PullConfiguration]:
        q = self.db.query(PullConfiguration)
        if enabled_only:
            q = q.filter(PullConfiguration.is_enabled == True)
        return q.all()

    def create(self, config_data: Dict[str, Any]) -> PullConfiguration:
        config = PullConfiguration(**config_data)
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update(
        self, config_id: int, config_data: Dict[str, Any]
    ) -> Optional[PullConfiguration]:
        config = self.get_by_id(config_id)
        if config:
            for key, value in config_data.items():
                setattr(config, key, value)
            self.db.commit()
            self.db.refresh(config)
        return config

    def add_stations(self, config_id: int, stations: List[Dict[str, Any]]) -> int:
        """Add stations to a configuration."""
        count = 0
        for station_data in stations:
            station_data["config_id"] = config_id
            config_station = PullConfigurationStation(**station_data)
            self.db.add(config_station)
            count += 1

        self.db.commit()
        return count

    def get_stations(self, config_id: int) -> List[PullConfigurationStation]:
        return (
            self.db.query(PullConfigurationStation)
            .filter(PullConfigurationStation.config_id == config_id)
            .all()
        )


class PullStationProgressRepository:
    """Repository for PullStationProgress model (Smart Append Logic)."""

    def __init__(self, db: Session):
        self.db = db

    def get_progress(
        self, config_id: int, station_number: str
    ) -> Optional[PullStationProgress]:
        return (
            self.db.query(PullStationProgress)
            .filter(
                and_(
                    PullStationProgress.config_id == config_id,
                    PullStationProgress.station_number == station_number,
                )
            )
            .first()
        )

    def update_progress(
        self, config_id: int, station_number: str, last_pull_date: datetime
    ) -> PullStationProgress:
        """Update or create progress record."""
        from datetime import timezone

        progress = self.get_progress(config_id, station_number)

        if progress:
            progress.last_successful_pull_date = last_pull_date
            progress.updated_at = datetime.now(timezone.utc)
        else:
            progress = PullStationProgress(
                config_id=config_id,
                station_number=station_number,
                last_successful_pull_date=last_pull_date,
            )
            self.db.add(progress)

        self.db.commit()
        self.db.refresh(progress)
        return progress

    def get_all_for_config(self, config_id: int) -> List[PullStationProgress]:
        return (
            self.db.query(PullStationProgress)
            .filter(PullStationProgress.config_id == config_id)
            .all()
        )


class DataPullLogRepository:
    """Repository for DataPullLog model."""

    def __init__(self, db: Session):
        self.db = db

    def create_log(self, config_id: int, status: str = "running") -> DataPullLog:
        from datetime import timezone

        log = DataPullLog(
            config_id=config_id, status=status, start_time=datetime.now(timezone.utc)
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def update_log(
        self, log_id: int, log_data: Dict[str, Any]
    ) -> Optional[DataPullLog]:
        log = self.db.query(DataPullLog).filter(DataPullLog.id == log_id).first()
        if log:
            for key, value in log_data.items():
                setattr(log, key, value)
            self.db.commit()
            self.db.refresh(log)
        return log

    def get_recent_logs(self, config_id: int, limit: int = 10) -> List[DataPullLog]:
        return (
            self.db.query(DataPullLog)
            .filter(DataPullLog.config_id == config_id)
            .order_by(DataPullLog.start_time.desc())
            .limit(limit)
            .all()
        )


class MasterStationRepository:
    """Repository for MasterStation model."""

    def __init__(self, db: Session):
        self.db = db

    def bulk_upsert(self, stations: List[Dict[str, Any]]) -> int:
        """Bulk insert/update master stations from CSV."""
        count = 0
        for station_data in stations:
            existing = (
                self.db.query(MasterStation)
                .filter(MasterStation.station_number == station_data["station_number"])
                .first()
            )

            if existing:
                for key, value in station_data.items():
                    setattr(existing, key, value)
            else:
                station = MasterStation(**station_data)
                self.db.add(station)
            count += 1

        self.db.commit()
        return count

    def search(
        self,
        query: Optional[str] = None,
        state_code: Optional[str] = None,
        huc_code: Optional[str] = None,
    ) -> List[MasterStation]:
        q = self.db.query(MasterStation)

        if query:
            q = q.filter(
                or_(
                    MasterStation.station_number.ilike(f"%{query}%"),
                    MasterStation.station_name.ilike(f"%{query}%"),
                )
            )

        if state_code:
            q = q.filter(MasterStation.state_code == state_code)

        if huc_code:
            q = q.filter(MasterStation.huc_code.startswith(huc_code))

        return q.all()


class StationMappingRepository:
    """Repository for StationMapping model."""

    def __init__(self, db: Session):
        self.db = db

    def get_mapping(
        self, source_agency: str, source_id: str, target_agency: str
    ) -> Optional[str]:
        """Get target ID for a source ID."""
        mapping = (
            self.db.query(StationMapping)
            .filter(
                and_(
                    StationMapping.source_agency == source_agency,
                    StationMapping.source_id == source_id,
                    StationMapping.target_agency == target_agency,
                )
            )
            .first()
        )

        return mapping.target_id if mapping else None

    def create_mapping(self, mapping_data: Dict[str, Any]) -> StationMapping:
        mapping = StationMapping(**mapping_data)
        self.db.add(mapping)
        self.db.commit()
        self.db.refresh(mapping)
        return mapping

    def bulk_create(self, mappings: List[Dict[str, Any]]) -> int:
        """Bulk insert mappings, ignoring duplicates."""
        count = 0
        for mapping_data in mappings:
            existing = (
                self.db.query(StationMapping)
                .filter(
                    and_(
                        StationMapping.source_agency == mapping_data["source_agency"],
                        StationMapping.source_id == mapping_data["source_id"],
                        StationMapping.target_agency == mapping_data["target_agency"],
                    )
                )
                .first()
            )

            if not existing:
                mapping = StationMapping(**mapping_data)
                self.db.add(mapping)
                count += 1

        self.db.commit()
        return count
