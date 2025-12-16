# Component 1: Relational Database Design and Persistence Layer

## Overview
Design and implement a robust database schema with SQLAlchemy ORM to store streamflow discharge data, station metadata, forecasts, and data pull configurations. The system must be portable across SQLite (development) and PostgreSQL (production).

---

## Implementation Plan

### Phase 1: Project Setup and Environment Configuration

#### 1.1 Initialize Python Project Structure
```
streamflow_dataops/
├── src/
│   ├── __init__.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── connection.py
│   │   ├── repositories.py
│   │   └── init_db.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   └── utils/
│       ├── __init__.py
│       └── csv_loader.py
├── data/
│   └── hads_id_mappings.csv
├── migrations/
├── tests/
│   ├── __init__.py
│   └── test_models.py
├── requirements.txt
├── .env.example
└── README.md
```

#### 1.2 Install Dependencies
Create `requirements.txt`:
```
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
alembic==1.12.1
python-dotenv==1.0.0
pandas==2.1.3
```

#### 1.3 Environment Configuration
Create `.env.example`:
```
DATABASE_URL=sqlite:///./streamflow_dev.db
# DATABASE_URL=postgresql://user:password@localhost:5432/streamflow_db
```

Create `src/config/settings.py`:
```python
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./streamflow_dev.db')
```

---

### Phase 2: Database Connection Layer

#### 2.1 Create Database Connection Module (`src/database/connection.py`)
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from src.config.settings import DATABASE_URL

# Create engine with appropriate settings
engine = create_engine(
    DATABASE_URL,
    echo=True,  # Set to False in production
    pool_pre_ping=True,  # Verify connections before using
    pool_size=10,  # Adjust based on load
    max_overflow=20
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for declarative models
Base = declarative_base()

# Dependency for FastAPI/Flask routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

---

### Phase 3: SQLAlchemy Models Definition

#### 3.1 Create Models Module (`src/database/models.py`)

**Key Considerations:**
- Use appropriate SQLAlchemy types that map correctly to PostgreSQL and SQLite
- Define relationships between tables
- Add indexes for frequently queried fields
- Include validation constraints

```python
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, 
    Numeric, ForeignKey, UniqueConstraint, Index, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.database.connection import Base

class Station(Base):
    """Stores station metadata"""
    __tablename__ = "stations"
    
    id = Column(Integer, primary_key=True, index=True)
    station_number = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(Text, nullable=False)
    agency = Column(String(50), nullable=False)  # 'USGS', 'EC'
    
    # Geographic Information
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    timezone = Column(String(50), default='UTC')
    
    # Hydrological Attributes
    huc_code = Column(String(20), index=True)
    basin = Column(String(100))
    state = Column(String(50), index=True)
    catchment_area = Column(Numeric)  # sq km
    
    # Record Statistics
    years_of_record = Column(Numeric)
    record_start_date = Column(DateTime(timezone=True))
    record_end_date = Column(DateTime(timezone=True))
    
    # Status
    is_active = Column(Boolean, default=True)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    discharge_observations = relationship("DischargeObservation", back_populates="station")
    forecast_runs = relationship("ForecastRun", back_populates="station")


class DischargeObservation(Base):
    """Stores time series discharge observations"""
    __tablename__ = "discharge_observations"
    
    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    observed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    discharge = Column(Numeric, nullable=False)
    unit = Column(String(10), nullable=False)  # 'cfs', 'cms'
    type = Column(String(20), nullable=False)  # 'realtime_15min', 'daily_mean'
    quality_code = Column(String(10))  # 'P' (Provisional), 'A' (Approved)
    
    # Relationships
    station = relationship("Station", back_populates="discharge_observations")
    
    # Unique constraint to prevent duplicates
    __table_args__ = (
        UniqueConstraint('station_id', 'observed_at', 'type', name='unique_observation_idx'),
        Index('idx_station_observed_type', 'station_id', 'observed_at', 'type'),
    )


class ForecastRun(Base):
    """Stores forecast data"""
    __tablename__ = "forecast_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False, index=True)
    source = Column(String(50), nullable=False)  # 'NOAA_RFC'
    run_date = Column(DateTime(timezone=True), nullable=False, index=True)
    data = Column(JSON, nullable=False)  # Array of { date: string, value: number }
    rmse = Column(Numeric)  # Accuracy metric
    
    # Relationships
    station = relationship("Station", back_populates="forecast_runs")
    
    __table_args__ = (
        Index('idx_station_run_date', 'station_id', 'run_date'),
    )


class PullConfiguration(Base):
    """Stores data pull job configurations"""
    __tablename__ = "pull_configurations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    data_type = Column(String(20), nullable=False)  # 'realtime_15min', 'daily_mean'
    data_strategy = Column(String(20), nullable=False)  # 'append', 'overwrite'
    pull_start_date = Column(DateTime(timezone=True), nullable=False)
    is_enabled = Column(Boolean, default=True)
    
    # Schedule (cron-like)
    schedule_type = Column(String(20), nullable=False)  # 'hourly', 'daily', 'weekly'
    schedule_value = Column(String(50))  # e.g., '0 */6 * * *' for cron
    
    last_run_at = Column(DateTime(timezone=True))
    next_run_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    configuration_stations = relationship("PullConfigurationStation", back_populates="configuration")
    logs = relationship("DataPullLog", back_populates="configuration")
    progress_records = relationship("PullStationProgress", back_populates="configuration")


class PullConfigurationStation(Base):
    """Junction table linking configurations to stations"""
    __tablename__ = "pull_configuration_stations"
    
    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey("pull_configurations.id"), nullable=False, index=True)
    station_number = Column(String(50), nullable=False)
    station_name = Column(Text)
    huc_code = Column(String(20))
    state = Column(String(50))
    
    # Relationships
    configuration = relationship("PullConfiguration", back_populates="configuration_stations")


class DataPullLog(Base):
    """Tracks data pull job execution history"""
    __tablename__ = "data_pull_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey("pull_configurations.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False)  # 'success', 'failed', 'running'
    records_processed = Column(Integer)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True))
    error_message = Column(Text)
    
    # Relationships
    configuration = relationship("PullConfiguration", back_populates="logs")
    
    __table_args__ = (
        Index('idx_config_start_time', 'config_id', 'start_time'),
    )


class PullStationProgress(Base):
    """Tracks the progress of each station within a configuration (Smart Append Logic)"""
    __tablename__ = "pull_station_progress"
    
    id = Column(Integer, primary_key=True, index=True)
    config_id = Column(Integer, ForeignKey("pull_configurations.id"), nullable=False, index=True)
    station_number = Column(String(50), nullable=False)
    
    # CRUCIAL FIELD FOR SMART LOGIC
    last_successful_pull_date = Column(DateTime(timezone=True))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    configuration = relationship("PullConfiguration", back_populates="progress_records")
    
    __table_args__ = (
        UniqueConstraint('config_id', 'station_number', name='unique_progress_idx'),
    )


class MasterStation(Base):
    """Master station list (from CSV import)"""
    __tablename__ = "master_stations"
    
    id = Column(Integer, primary_key=True, index=True)
    station_number = Column(String(50), unique=True, nullable=False, index=True)
    station_name = Column(Text, nullable=False)
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    state_code = Column(String(10), index=True)
    huc_code = Column(String(20), index=True)
    altitude_ft = Column(Numeric)
    drainage_area_sqmi = Column(Numeric)
    agency = Column(String(20), default='USGS')


class StationMapping(Base):
    """Stores mappings between different network IDs"""
    __tablename__ = "station_mappings"
    
    id = Column(Integer, primary_key=True, index=True)
    source_agency = Column(String(50), nullable=False)  # e.g., 'USGS'
    source_id = Column(String(50), nullable=False, index=True)
    target_agency = Column(String(50), nullable=False)  # e.g., 'NOAA-HADS'
    target_id = Column(String(50), nullable=False)
    
    __table_args__ = (
        UniqueConstraint('source_agency', 'source_id', 'target_agency', name='unique_mapping_idx'),
        Index('idx_source_lookup', 'source_agency', 'source_id'),
    )
```

---

### Phase 4: Database Initialization

#### 4.1 Create Database Initialization Script (`src/database/init_db.py`)
```python
from src.database.connection import engine, Base
from src.database.models import (
    Station, DischargeObservation, ForecastRun, 
    PullConfiguration, PullConfigurationStation,
    DataPullLog, PullStationProgress, MasterStation, StationMapping
)
from src.utils.csv_loader import load_station_mappings
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_database(load_initial_data=True):
    """
    Initialize database schema and optionally load initial data
    
    Args:
        load_initial_data: If True, loads CSV data into tables
    """
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")
    
    if load_initial_data:
        logger.info("Loading initial station mapping data...")
        load_station_mappings()
        logger.info("Initial data loaded successfully")

def drop_all_tables():
    """Drop all tables - USE WITH CAUTION"""
    logger.warning("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    logger.info("All tables dropped")

if __name__ == "__main__":
    init_database(load_initial_data=True)
```

---

### Phase 5: Repository Pattern Implementation

#### 5.1 Create Repository Classes (`src/database/repositories.py`)

```python
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime
from src.database.models import (
    Station, DischargeObservation, StationMapping, 
    PullStationProgress, MasterStation
)

class StationRepository:
    """Repository for Station operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_by_id(self, station_id: int) -> Optional[Station]:
        return self.db.query(Station).filter(Station.id == station_id).first()
    
    def get_by_station_number(self, station_number: str) -> Optional[Station]:
        return self.db.query(Station).filter(Station.station_number == station_number).first()
    
    def create(self, station_data: dict) -> Station:
        station = Station(**station_data)
        self.db.add(station)
        self.db.commit()
        self.db.refresh(station)
        return station
    
    def update(self, station_id: int, station_data: dict) -> Optional[Station]:
        station = self.get_by_id(station_id)
        if station:
            for key, value in station_data.items():
                setattr(station, key, value)
            self.db.commit()
            self.db.refresh(station)
        return station
    
    def get_active_stations(self) -> List[Station]:
        return self.db.query(Station).filter(Station.is_active == True).all()


class DischargeObservationRepository:
    """Repository for DischargeObservation operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def bulk_insert_ignore_duplicates(self, observations: List[dict]) -> int:
        """
        Insert observations, ignoring duplicates based on unique constraint
        Returns count of successfully inserted records
        """
        inserted_count = 0
        for obs_data in observations:
            try:
                obs = DischargeObservation(**obs_data)
                self.db.add(obs)
                self.db.commit()
                inserted_count += 1
            except Exception as e:
                # Duplicate or other error - rollback and continue
                self.db.rollback()
        return inserted_count
    
    def get_latest_observation_date(self, station_id: int, obs_type: str) -> Optional[datetime]:
        """Get the latest observation date for a station and type"""
        result = self.db.query(DischargeObservation.observed_at)\
            .filter(
                and_(
                    DischargeObservation.station_id == station_id,
                    DischargeObservation.type == obs_type
                )
            )\
            .order_by(DischargeObservation.observed_at.desc())\
            .first()
        return result[0] if result else None


class StationMappingRepository:
    """Repository for StationMapping operations - CRITICAL for ID translation"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_mapping(self, source_agency: str, source_id: str, target_agency: str) -> Optional[str]:
        """
        Get target ID for a given source ID
        
        Args:
            source_agency: Source agency (e.g., 'USGS')
            source_id: Source station ID
            target_agency: Target agency (e.g., 'NOAA-HADS')
            
        Returns:
            Target station ID or None if not found
        """
        mapping = self.db.query(StationMapping)\
            .filter(
                and_(
                    StationMapping.source_agency == source_agency,
                    StationMapping.source_id == source_id,
                    StationMapping.target_agency == target_agency
                )
            ).first()
        return mapping.target_id if mapping else None
    
    def bulk_insert_mappings(self, mappings: List[dict]) -> int:
        """Bulk insert station mappings"""
        inserted_count = 0
        for mapping_data in mappings:
            try:
                mapping = StationMapping(**mapping_data)
                self.db.add(mapping)
                self.db.commit()
                inserted_count += 1
            except Exception:
                self.db.rollback()
        return inserted_count


class PullProgressRepository:
    """Repository for PullStationProgress - CRITICAL for Smart Append Logic"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_last_pull_date(self, config_id: int, station_number: str) -> Optional[datetime]:
        """
        Get last successful pull date for a station in a configuration
        This is THE key method for Smart Append Logic
        """
        progress = self.db.query(PullStationProgress)\
            .filter(
                and_(
                    PullStationProgress.config_id == config_id,
                    PullStationProgress.station_number == station_number
                )
            ).first()
        return progress.last_successful_pull_date if progress else None
    
    def update_last_pull_date(self, config_id: int, station_number: str, pull_date: datetime):
        """Update last successful pull date for a station"""
        progress = self.db.query(PullStationProgress)\
            .filter(
                and_(
                    PullStationProgress.config_id == config_id,
                    PullStationProgress.station_number == station_number
                )
            ).first()
        
        if progress:
            progress.last_successful_pull_date = pull_date
            progress.updated_at = datetime.utcnow()
        else:
            progress = PullStationProgress(
                config_id=config_id,
                station_number=station_number,
                last_successful_pull_date=pull_date
            )
            self.db.add(progress)
        
        self.db.commit()


class MasterStationRepository:
    """Repository for MasterStation operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def search_stations(self, 
                        state_code: Optional[str] = None,
                        huc_code_prefix: Optional[str] = None,
                        search_term: Optional[str] = None,
                        limit: int = 100) -> List[MasterStation]:
        """
        Search master stations with filters
        
        Args:
            state_code: Filter by state code
            huc_code_prefix: Filter by HUC prefix (e.g., '02' for 2-digit HUC)
            search_term: Search in station name or number
            limit: Maximum results to return
        """
        query = self.db.query(MasterStation)
        
        if state_code:
            query = query.filter(MasterStation.state_code == state_code)
        
        if huc_code_prefix:
            query = query.filter(MasterStation.huc_code.like(f'{huc_code_prefix}%'))
        
        if search_term:
            query = query.filter(
                or_(
                    MasterStation.station_name.ilike(f'%{search_term}%'),
                    MasterStation.station_number.ilike(f'%{search_term}%')
                )
            )
        
        return query.limit(limit).all()
```

---

### Phase 6: CSV Data Loader Utility

#### 6.1 Create CSV Loader (`src/utils/csv_loader.py`)
```python
import pandas as pd
import logging
from pathlib import Path
from src.database.connection import SessionLocal
from src.database.repositories import StationMappingRepository

logger = logging.getLogger(__name__)

def load_station_mappings(csv_path: str = "data/hads_id_mappings.csv"):
    """
    Load station ID mappings from CSV file into database
    
    CSV Format:
    source_agency,source_id,target_agency,target_id
    USGS,01010000,NOAA-HADS,HADSID001
    """
    csv_file = Path(csv_path)
    if not csv_file.exists():
        logger.error(f"CSV file not found: {csv_path}")
        return
    
    db = SessionLocal()
    try:
        df = pd.read_csv(csv_path)
        mappings = df.to_dict('records')
        
        repo = StationMappingRepository(db)
        inserted = repo.bulk_insert_mappings(mappings)
        
        logger.info(f"Loaded {inserted} station mappings from {csv_path}")
    except Exception as e:
        logger.error(f"Error loading station mappings: {e}")
        db.rollback()
    finally:
        db.close()


def load_master_stations(csv_path: str = "data/usgs_master_stations.csv"):
    """
    Load master station list from CSV into database
    
    CSV Format should match MasterStation model fields
    """
    # Similar implementation to load_station_mappings
    pass
```

---

### Phase 7: Database Migrations with Alembic

#### 7.1 Initialize Alembic
```bash
alembic init migrations
```

#### 7.2 Configure Alembic (`migrations/env.py`)
Update the file to use your Base and connection:
```python
from src.database.connection import Base, engine
from src.database import models  # Import all models

target_metadata = Base.metadata

# In run_migrations_online():
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=target_metadata
    )
```

#### 7.3 Create Initial Migration
```bash
alembic revision --autogenerate -m "Initial schema"
alembic upgrade head
```

---

### Phase 8: Testing

#### 8.1 Create Unit Tests (`tests/test_models.py`)
```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.connection import Base
from src.database.models import Station, DischargeObservation, StationMapping
from src.database.repositories import StationRepository, StationMappingRepository

@pytest.fixture
def test_db():
    """Create in-memory SQLite database for testing"""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine)
    db = TestSessionLocal()
    yield db
    db.close()

def test_create_station(test_db):
    repo = StationRepository(test_db)
    station_data = {
        'station_number': '01010000',
        'name': 'Test Station',
        'agency': 'USGS',
        'latitude': 45.12345678,
        'longitude': -68.12345678
    }
    station = repo.create(station_data)
    assert station.id is not None
    assert station.station_number == '01010000'

def test_station_mapping(test_db):
    repo = StationMappingRepository(test_db)
    mappings = [
        {
            'source_agency': 'USGS',
            'source_id': '01010000',
            'target_agency': 'NOAA-HADS',
            'target_id': 'HADS001'
        }
    ]
    repo.bulk_insert_mappings(mappings)
    
    target_id = repo.get_mapping('USGS', '01010000', 'NOAA-HADS')
    assert target_id == 'HADS001'

# Add more tests...
```

---

## Implementation Checklist

- [ ] Phase 1: Project setup and dependencies
- [ ] Phase 2: Database connection layer
- [ ] Phase 3: Define all SQLAlchemy models
- [ ] Phase 4: Create database initialization script
- [ ] Phase 5: Implement repository pattern for data access
- [ ] Phase 6: Create CSV loader utilities
- [ ] Phase 7: Set up Alembic for migrations
- [ ] Phase 8: Write comprehensive unit tests
- [ ] Additional: Create helper scripts for common operations
- [ ] Additional: Document all models and relationships
- [ ] Additional: Performance optimization (indexes, query tuning)

---

## Key Design Decisions

1. **SQLAlchemy ORM**: Provides database portability and Python-idiomatic data access
2. **Repository Pattern**: Encapsulates data access logic, making code more maintainable and testable
3. **Alembic Migrations**: Version control for database schema changes
4. **Smart Append Logic**: Implemented via `PullStationProgress` table and repository methods
5. **Station Mapping**: Dedicated table and repository for ID translation between agencies
6. **Timezone Handling**: All datetime fields use timezone-aware types, stored in UTC

---

## Next Steps

After completing this component:
1. Integrate with Component 2 (Data Acquisition Services)
2. Use repositories in Celery worker tasks
3. Build Django admin interface (Component 3)
4. Consider adding database backup/restore utilities
5. Implement monitoring for database performance
