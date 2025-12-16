# Component 4: Future Database Web Service API

## Overview
Create a lightweight REST API using Flask or FastAPI to provide read-access to the streamflow database. This API will serve time series data (discharge observations) and forecast data to external applications, data visualization tools, and third-party integrations.

---

## Technical Stack Decision

### Option A: Flask (Recommended for this project)
**Pros:**
- Lightweight and flexible
- Easy integration with existing SQLAlchemy models
- Extensive ecosystem of extensions
- Better fit for simple API needs

**Cons:**
- Less built-in validation
- Manual API documentation

### Option B: FastAPI
**Pros:**
- Automatic OpenAPI documentation
- Built-in data validation with Pydantic
- High performance (async capable)
- Modern Python features (type hints)

**Cons:**
- Slightly steeper learning curve
- May be overkill for simple read-only API

**Decision: Use FastAPI** for automatic documentation, validation, and future scalability.

---

## Implementation Plan

### Phase 1: Project Setup

#### 1.1 Project Structure
```
streamflow_dataops/
├── src/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── dependencies.py      # Dependency injection
│   │   ├── schemas.py           # Pydantic schemas
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── stations.py      # Station endpoints
│   │   │   ├── observations.py  # Discharge observation endpoints
│   │   │   ├── forecasts.py     # Forecast endpoints
│   │   │   └── health.py        # Health check endpoint
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── station_service.py
│   │   │   ├── observation_service.py
│   │   │   └── forecast_service.py
│   │   └── middleware/
│   │       ├── __init__.py
│   │       ├── authentication.py
│   │       └── rate_limiting.py
├── tests/
│   └── api/
│       ├── test_stations.py
│       ├── test_observations.py
│       └── test_forecasts.py
└── requirements.txt
```

#### 1.2 Install Dependencies
Update `requirements.txt`:
```
# FastAPI and Server
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
pydantic-settings==2.1.0

# SQLAlchemy (already installed)
sqlalchemy==2.0.23

# Additional API Tools
python-jose[cryptography]==3.3.0  # JWT tokens
passlib[bcrypt]==1.7.4  # Password hashing
slowapi==0.1.9  # Rate limiting
python-multipart==0.0.6  # Form data support

# Development/Testing
pytest==7.4.3
httpx==0.25.1  # For testing async endpoints
pytest-asyncio==0.21.1
```

---

### Phase 2: FastAPI Application Setup

#### 2.1 Main Application (`src/api/main.py`)
```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import logging

from src.api.routers import stations, observations, forecasts, health
from src.config.settings import API_TITLE, API_VERSION, API_DESCRIPTION

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Create FastAPI app
app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately in production
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(stations.router, prefix="/api/v1/stations", tags=["Stations"])
app.include_router(observations.router, prefix="/api/v1/observations", tags=["Observations"])
app.include_router(forecasts.router, prefix="/api/v1/forecasts", tags=["Forecasts"])

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Streamflow DataOps API",
        "version": API_VERSION,
        "docs": "/docs"
    }

# Startup event
@app.on_event("startup")
async def startup_event():
    logging.info(f"Starting {API_TITLE} v{API_VERSION}")

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    logging.info("Shutting down API")
```

#### 2.2 Configuration (`src/config/settings.py` - Update)
```python
# Add to existing settings.py

# API Configuration
API_TITLE = "Streamflow DataOps API"
API_VERSION = "1.0.0"
API_DESCRIPTION = """
REST API for accessing streamflow discharge data and forecasts.

## Features
* Query discharge observations by station and date range
* Access forecast data
* Search and filter stations
* Export data in multiple formats (JSON, CSV)
"""

# Authentication (optional)
API_KEY_ENABLED = env.bool('API_KEY_ENABLED', default=False)
API_SECRET_KEY = env('API_SECRET_KEY', default='your-secret-key-change-in-production')
API_ALGORITHM = "HS256"
API_ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Rate Limiting
RATE_LIMIT_PER_MINUTE = env.int('RATE_LIMIT_PER_MINUTE', default=60)
```

---

### Phase 3: Pydantic Schemas

#### 3.1 Create Schemas (`src/api/schemas.py`)
```python
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List
from decimal import Decimal

# Station Schemas
class StationBase(BaseModel):
    station_number: str = Field(..., description="Unique station identifier")
    name: str = Field(..., description="Station name")
    agency: str = Field(..., description="Agency (USGS, EC)")
    latitude: Optional[Decimal] = Field(None, description="Latitude in decimal degrees")
    longitude: Optional[Decimal] = Field(None, description="Longitude in decimal degrees")

class StationDetail(StationBase):
    """Detailed station information"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    timezone: Optional[str] = None
    huc_code: Optional[str] = Field(None, description="Hydrologic Unit Code")
    basin: Optional[str] = None
    state: Optional[str] = None
    catchment_area: Optional[Decimal] = Field(None, description="Catchment area in sq km")
    years_of_record: Optional[Decimal] = None
    record_start_date: Optional[datetime] = None
    record_end_date: Optional[datetime] = None
    is_active: bool = True
    last_updated: Optional[datetime] = None

class StationList(BaseModel):
    """List of stations with pagination"""
    total: int
    page: int
    page_size: int
    stations: List[StationDetail]

# Discharge Observation Schemas
class DischargeObservationBase(BaseModel):
    observed_at: datetime = Field(..., description="Observation timestamp (UTC)")
    discharge: Decimal = Field(..., description="Discharge value")
    unit: str = Field(..., description="Unit of measurement (cfs, cms)")
    type: str = Field(..., description="Observation type (realtime_15min, daily_mean)")
    quality_code: Optional[str] = Field(None, description="Data quality code")

class DischargeObservation(DischargeObservationBase):
    """Single discharge observation"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    station_id: int

class ObservationSeries(BaseModel):
    """Time series of observations for a station"""
    station_number: str
    station_name: Optional[str] = None
    data_type: str
    unit: str
    start_date: datetime
    end_date: datetime
    count: int
    observations: List[DischargeObservationBase]

# Forecast Schemas
class ForecastDataPoint(BaseModel):
    """Single forecast data point"""
    date: str
    value: float

class ForecastBase(BaseModel):
    source: str = Field(..., description="Forecast source (NOAA_NWM)")
    run_date: datetime = Field(..., description="Forecast run date")
    data: List[ForecastDataPoint] = Field(..., description="Forecast time series")
    rmse: Optional[Decimal] = Field(None, description="Root Mean Square Error")

class Forecast(ForecastBase):
    """Forecast with metadata"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    station_id: int

class ForecastSeries(BaseModel):
    """Forecast series for a station"""
    station_number: str
    station_name: Optional[str] = None
    latest_run_date: datetime
    forecasts: List[Forecast]

# Query Parameters
class ObservationQuery(BaseModel):
    """Query parameters for observation endpoint"""
    station_number: str = Field(..., description="Station identifier")
    start_date: datetime = Field(..., description="Start date (ISO 8601)")
    end_date: Optional[datetime] = Field(None, description="End date (ISO 8601)")
    data_type: Optional[str] = Field("daily_mean", description="Data type filter")
    format: Optional[str] = Field("json", description="Response format (json, csv)")

# Error Response
class ErrorResponse(BaseModel):
    """Error response schema"""
    detail: str = Field(..., description="Error message")
    error_code: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

---

### Phase 4: Database Dependencies

#### 4.1 Dependencies (`src/api/dependencies.py`)
```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session
from src.database.connection import SessionLocal
from src.config.settings import API_KEY_ENABLED
import logging

logger = logging.getLogger(__name__)

# Database session dependency
def get_db():
    """
    Dependency to get database session
    Automatically closes session after request
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Optional API Key authentication
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(api_key_header)):
    """
    Verify API key if authentication is enabled
    """
    if not API_KEY_ENABLED:
        return None
    
    if api_key is None:
        raise HTTPException(
            status_code=401,
            detail="API key required"
        )
    
    # TODO: Validate API key against database
    # For now, just check if it exists
    if len(api_key) < 20:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    
    return api_key

# Common query validation
def validate_date_range(start_date, end_date):
    """Validate that date range is reasonable"""
    if end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must be before end_date"
        )
    
    # Limit to 2 years of data per request
    from datetime import timedelta
    max_range = timedelta(days=730)
    if end_date and (end_date - start_date) > max_range:
        raise HTTPException(
            status_code=400,
            detail="Date range cannot exceed 2 years"
        )
```

---

### Phase 5: Service Layer

#### 5.1 Station Service (`src/api/services/station_service.py`)
```python
from sqlalchemy.orm import Session
from typing import List, Optional
from src.database.repositories import StationRepository, MasterStationRepository
from src.database.models import Station, MasterStation

class StationService:
    """Business logic for station endpoints"""
    
    def __init__(self, db: Session):
        self.db = db
        self.station_repo = StationRepository(db)
        self.master_repo = MasterStationRepository(db)
    
    def get_station_by_number(self, station_number: str) -> Optional[Station]:
        """Get station by station number"""
        return self.station_repo.get_by_station_number(station_number)
    
    def search_stations(self,
                       state_code: Optional[str] = None,
                       huc_prefix: Optional[str] = None,
                       search_term: Optional[str] = None,
                       limit: int = 100,
                       offset: int = 0) -> tuple[List[MasterStation], int]:
        """
        Search stations with pagination
        Returns (stations, total_count)
        """
        stations = self.master_repo.search_stations(
            state_code=state_code,
            huc_code_prefix=huc_prefix,
            search_term=search_term,
            limit=limit + 1  # Get one extra to check if there are more
        )
        
        has_more = len(stations) > limit
        if has_more:
            stations = stations[:limit]
        
        # Get total count (simplified - in production, use COUNT query)
        total = len(stations)
        
        return stations, total
    
    def get_active_stations(self) -> List[Station]:
        """Get all active stations"""
        return self.station_repo.get_active_stations()
```

#### 5.2 Observation Service (`src/api/services/observation_service.py`)
```python
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
from src.database.repositories import DischargeObservationRepository
from src.database.models import DischargeObservation

class ObservationService:
    """Business logic for observation endpoints"""
    
    def __init__(self, db: Session):
        self.db = db
        self.obs_repo = DischargeObservationRepository(db)
    
    def get_observations(self,
                        station_id: int,
                        start_date: datetime,
                        end_date: Optional[datetime] = None,
                        data_type: Optional[str] = None,
                        limit: int = 10000) -> List[DischargeObservation]:
        """
        Get observations for a station within date range
        """
        if end_date is None:
            end_date = datetime.utcnow()
        
        # Query observations
        query = self.db.query(DischargeObservation)\
            .filter(
                DischargeObservation.station_id == station_id,
                DischargeObservation.observed_at >= start_date,
                DischargeObservation.observed_at <= end_date
            )
        
        if data_type:
            query = query.filter(DischargeObservation.type == data_type)
        
        observations = query\
            .order_by(DischargeObservation.observed_at)\
            .limit(limit)\
            .all()
        
        return observations
    
    def get_latest_observation(self, 
                               station_id: int,
                               data_type: Optional[str] = None) -> Optional[DischargeObservation]:
        """Get most recent observation for a station"""
        query = self.db.query(DischargeObservation)\
            .filter(DischargeObservation.station_id == station_id)
        
        if data_type:
            query = query.filter(DischargeObservation.type == data_type)
        
        return query\
            .order_by(DischargeObservation.observed_at.desc())\
            .first()
    
    def get_observation_statistics(self,
                                   station_id: int,
                                   start_date: datetime,
                                   end_date: datetime) -> dict:
        """Calculate statistics for observation period"""
        from sqlalchemy import func
        
        result = self.db.query(
            func.count(DischargeObservation.id).label('count'),
            func.avg(DischargeObservation.discharge).label('mean'),
            func.min(DischargeObservation.discharge).label('min'),
            func.max(DischargeObservation.discharge).label('max')
        ).filter(
            DischargeObservation.station_id == station_id,
            DischargeObservation.observed_at >= start_date,
            DischargeObservation.observed_at <= end_date
        ).first()
        
        return {
            'count': result.count,
            'mean': float(result.mean) if result.mean else None,
            'min': float(result.min) if result.min else None,
            'max': float(result.max) if result.max else None
        }
```

#### 5.3 Forecast Service (`src/api/services/forecast_service.py`)
```python
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional
from src.database.models import ForecastRun

class ForecastService:
    """Business logic for forecast endpoints"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_latest_forecast(self, station_id: int) -> Optional[ForecastRun]:
        """Get most recent forecast for a station"""
        return self.db.query(ForecastRun)\
            .filter(ForecastRun.station_id == station_id)\
            .order_by(ForecastRun.run_date.desc())\
            .first()
    
    def get_forecasts_by_date_range(self,
                                    station_id: int,
                                    start_date: datetime,
                                    end_date: datetime) -> List[ForecastRun]:
        """Get all forecasts for a station within date range"""
        return self.db.query(ForecastRun)\
            .filter(
                ForecastRun.station_id == station_id,
                ForecastRun.run_date >= start_date,
                ForecastRun.run_date <= end_date
            )\
            .order_by(ForecastRun.run_date.desc())\
            .all()
```

---

### Phase 6: API Endpoints

#### 6.1 Station Endpoints (`src/api/routers/stations.py`)
```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.dependencies import get_db, verify_api_key
from src.api.services.station_service import StationService
from src.api.schemas import StationDetail, StationList
from src.config.settings import RATE_LIMIT_PER_MINUTE

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

@router.get("/", response_model=StationList)
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def list_stations(
    state_code: Optional[str] = Query(None, description="Filter by state code"),
    huc_prefix: Optional[str] = Query(None, description="Filter by HUC prefix"),
    search: Optional[str] = Query(None, description="Search term"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    List and search stations with filters
    
    - **state_code**: Filter by state (e.g., 'MD', 'VA')
    - **huc_prefix**: Filter by HUC code prefix (e.g., '02' for Mid-Atlantic)
    - **search**: Search in station name or number
    - **page**: Page number for pagination
    - **page_size**: Number of results per page (max 100)
    """
    service = StationService(db)
    offset = (page - 1) * page_size
    
    stations, total = service.search_stations(
        state_code=state_code,
        huc_prefix=huc_prefix,
        search_term=search,
        limit=page_size,
        offset=offset
    )
    
    return StationList(
        total=total,
        page=page,
        page_size=page_size,
        stations=stations
    )

@router.get("/{station_number}", response_model=StationDetail)
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def get_station(
    station_number: str,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Get detailed information for a specific station
    
    - **station_number**: Station identifier (e.g., '01646500' for USGS)
    """
    service = StationService(db)
    station = service.get_station_by_number(station_number)
    
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_number} not found")
    
    return station

@router.get("/{station_number}/active", response_model=bool)
async def check_station_active(
    station_number: str,
    db: Session = Depends(get_db)
):
    """Check if a station is active"""
    service = StationService(db)
    station = service.get_station_by_number(station_number)
    
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    
    return station.is_active
```

---


#### 6.2 Observation Endpoints (`src/api/routers/observations.py`)
```python
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
import csv
import io

from src.api.dependencies import get_db, verify_api_key, validate_date_range
from src.api.services.observation_service import ObservationService
from src.api.services.station_service import StationService
from src.api.schemas import ObservationSeries, DischargeObservation
from slowapi import Limiter
from slowapi.util import get_remote_address
from src.config.settings import RATE_LIMIT_PER_MINUTE

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

@router.get("/{station_number}", response_model=ObservationSeries)
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def get_observations(
    station_number: str,
    start_date: datetime = Query(..., description="Start date (ISO 8601)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO 8601)"),
    data_type: Optional[str] = Query(None, description="Filter by data type"),
    format: str = Query("json", description="Response format: json or csv"),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Get discharge observations for a station
    
    - **station_number**: Station identifier
    - **start_date**: Start date in ISO 8601 format (e.g., '2023-01-01T00:00:00')
    - **end_date**: End date (defaults to current time)
    - **data_type**: Filter by type ('daily_mean', 'realtime_15min')
    - **format**: Response format ('json' or 'csv')
    
    Returns time series of discharge observations.
    """
    # Validate date range
    validate_date_range(start_date, end_date)
    
    # Get station
    station_service = StationService(db)
    station = station_service.get_station_by_number(station_number)
    
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_number} not found")
    
    # Get observations
    obs_service = ObservationService(db)
    observations = obs_service.get_observations(
        station_id=station.id,
        start_date=start_date,
        end_date=end_date,
        data_type=data_type
    )
    
    # Return CSV format if requested
    if format.lower() == 'csv':
        return generate_csv_response(station_number, observations)
    
    # Return JSON format
    return ObservationSeries(
        station_number=station_number,
        station_name=station.name,
        data_type=data_type or "all",
        unit=observations[0].unit if observations else "unknown",
        start_date=start_date,
        end_date=end_date or datetime.utcnow(),
        count=len(observations),
        observations=observations
    )

@router.get("/{station_number}/latest", response_model=DischargeObservation)
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def get_latest_observation(
    station_number: str,
    data_type: Optional[str] = Query(None, description="Filter by data type"),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Get the most recent observation for a station
    
    - **station_number**: Station identifier
    - **data_type**: Optional filter by data type
    """
    # Get station
    station_service = StationService(db)
    station = station_service.get_station_by_number(station_number)
    
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_number} not found")
    
    # Get latest observation
    obs_service = ObservationService(db)
    observation = obs_service.get_latest_observation(
        station_id=station.id,
        data_type=data_type
    )
    
    if not observation:
        raise HTTPException(
            status_code=404, 
            detail=f"No observations found for station {station_number}"
        )
    
    return observation

@router.get("/{station_number}/statistics")
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def get_observation_statistics(
    station_number: str,
    start_date: datetime = Query(..., description="Start date"),
    end_date: datetime = Query(..., description="End date"),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Get statistical summary of observations for a date range
    
    Returns count, mean, min, and max discharge values.
    """
    # Validate date range
    validate_date_range(start_date, end_date)
    
    # Get station
    station_service = StationService(db)
    station = station_service.get_station_by_number(station_number)
    
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_number} not found")
    
    # Get statistics
    obs_service = ObservationService(db)
    stats = obs_service.get_observation_statistics(
        station_id=station.id,
        start_date=start_date,
        end_date=end_date
    )
    
    return {
        "station_number": station_number,
        "start_date": start_date,
        "end_date": end_date,
        "statistics": stats
    }

def generate_csv_response(station_number: str, observations):
    """Generate CSV response for observations"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['station_number', 'observed_at', 'discharge', 'unit', 'type', 'quality_code'])
    
    # Write data
    for obs in observations:
        writer.writerow([
            station_number,
            obs.observed_at.isoformat(),
            str(obs.discharge),
            obs.unit,
            obs.type,
            obs.quality_code or ''
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=observations_{station_number}.csv"
        }
    )
```

#### 6.3 Forecast Endpoints (`src/api/routers/forecasts.py`)
```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from src.api.dependencies import get_db, verify_api_key
from src.api.services.forecast_service import ForecastService
from src.api.services.station_service import StationService
from src.api.schemas import Forecast, ForecastSeries
from slowapi import Limiter
from slowapi.util import get_remote_address
from src.config.settings import RATE_LIMIT_PER_MINUTE

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

@router.get("/{station_number}/latest", response_model=Forecast)
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def get_latest_forecast(
    station_number: str,
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Get the most recent forecast for a station
    
    - **station_number**: Station identifier
    
    Returns the latest forecast run with full time series data.
    """
    # Get station
    station_service = StationService(db)
    station = station_service.get_station_by_number(station_number)
    
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_number} not found")
    
    # Get latest forecast
    forecast_service = ForecastService(db)
    forecast = forecast_service.get_latest_forecast(station_id=station.id)
    
    if not forecast:
        raise HTTPException(
            status_code=404,
            detail=f"No forecasts available for station {station_number}"
        )
    
    return forecast

@router.get("/{station_number}", response_model=ForecastSeries)
@limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")
async def get_forecasts(
    station_number: str,
    start_date: datetime = Query(..., description="Start date for forecast runs"),
    end_date: datetime = Query(..., description="End date for forecast runs"),
    db: Session = Depends(get_db),
    api_key: str = Depends(verify_api_key)
):
    """
    Get all forecast runs for a station within a date range
    
    - **station_number**: Station identifier
    - **start_date**: Start date for forecast run dates
    - **end_date**: End date for forecast run dates
    
    Returns all forecast runs issued between the specified dates.
    """
    # Get station
    station_service = StationService(db)
    station = station_service.get_station_by_number(station_number)
    
    if not station:
        raise HTTPException(status_code=404, detail=f"Station {station_number} not found")
    
    # Get forecasts
    forecast_service = ForecastService(db)
    forecasts = forecast_service.get_forecasts_by_date_range(
        station_id=station.id,
        start_date=start_date,
        end_date=end_date
    )
    
    if not forecasts:
        raise HTTPException(
            status_code=404,
            detail=f"No forecasts found for station {station_number} in specified date range"
        )
    
    return ForecastSeries(
        station_number=station_number,
        station_name=station.name,
        latest_run_date=forecasts[0].run_date if forecasts else None,
        forecasts=forecasts
    )
```

#### 6.4 Health Check Endpoint (`src/api/routers/health.py`)
```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime

from src.api.dependencies import get_db

router = APIRouter()

@router.get("/")
async def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint
    
    Returns API status and database connectivity.
    """
    # Check database connection
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "database": db_status,
        "version": "1.0.0"
    }

@router.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """
    Readiness check for Kubernetes/container orchestration
    """
    try:
        db.execute(text("SELECT 1"))
        return {"ready": True}
    except Exception:
        return {"ready": False}, 503
```

---

### Phase 7: Testing

#### 7.1 Test Configuration (`tests/conftest.py`)
```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.api.dependencies import get_db
from src.database.connection import Base

# Test database URL (use in-memory SQLite)
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(scope="function")
def test_db():
    """Create test database"""
    engine = create_engine(SQLALCHEMY_TEST_DATABASE_URL)
    Base.metadata.create_all(bind=engine)
    
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    
    yield db
    
    db.close()
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(test_db):
    """Create test client with test database"""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client
    
    app.dependency_overrides.clear()
```

#### 7.2 Station Endpoint Tests (`tests/api/test_stations.py`)
```python
import pytest
from src.database.models import Station

def test_get_station(client, test_db):
    """Test getting a specific station"""
    # Create test station
    station = Station(
        station_number="01010000",
        name="Test Station",
        agency="USGS",
        latitude=45.0,
        longitude=-68.0,
        is_active=True
    )
    test_db.add(station)
    test_db.commit()
    
    # Test endpoint
    response = client.get("/api/v1/stations/01010000")
    assert response.status_code == 200
    
    data = response.json()
    assert data["station_number"] == "01010000"
    assert data["name"] == "Test Station"

def test_get_nonexistent_station(client):
    """Test getting a station that doesn't exist"""
    response = client.get("/api/v1/stations/99999999")
    assert response.status_code == 404

def test_list_stations(client, test_db):
    """Test listing stations"""
    # Create test stations
    for i in range(5):
        station = Station(
            station_number=f"0101000{i}",
            name=f"Test Station {i}",
            agency="USGS",
            is_active=True
        )
        test_db.add(station)
    test_db.commit()
    
    # Test endpoint
    response = client.get("/api/v1/stations/")
    assert response.status_code == 200
    
    data = response.json()
    assert data["total"] >= 5
    assert len(data["stations"]) <= data["page_size"]
```

#### 7.3 Observation Endpoint Tests (`tests/api/test_observations.py`)
```python
import pytest
from datetime import datetime, timedelta
from src.database.models import Station, DischargeObservation

def test_get_observations(client, test_db):
    """Test getting observations for a station"""
    # Create test station
    station = Station(
        station_number="01010000",
        name="Test Station",
        agency="USGS",
        is_active=True
    )
    test_db.add(station)
    test_db.commit()
    
    # Create test observations
    start_date = datetime(2023, 1, 1)
    for i in range(10):
        obs = DischargeObservation(
            station_id=station.id,
            observed_at=start_date + timedelta(days=i),
            discharge=100.0 + i,
            unit="cfs",
            type="daily_mean"
        )
        test_db.add(obs)
    test_db.commit()
    
    # Test endpoint
    response = client.get(
        "/api/v1/observations/01010000",
        params={
            "start_date": "2023-01-01T00:00:00",
            "end_date": "2023-01-10T00:00:00"
        }
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["station_number"] == "01010000"
    assert data["count"] == 10

def test_get_latest_observation(client, test_db):
    """Test getting latest observation"""
    # Create test station and observations
    station = Station(
        station_number="01010000",
        name="Test Station",
        agency="USGS",
        is_active=True
    )
    test_db.add(station)
    test_db.commit()
    
    obs = DischargeObservation(
        station_id=station.id,
        observed_at=datetime.utcnow(),
        discharge=150.5,
        unit="cfs",
        type="realtime_15min"
    )
    test_db.add(obs)
    test_db.commit()
    
    # Test endpoint
    response = client.get("/api/v1/observations/01010000/latest")
    assert response.status_code == 200
    
    data = response.json()
    assert data["discharge"] == "150.5"
```

---

### Phase 8: Documentation and Examples

#### 8.1 API Usage Examples (`docs/api_examples.md`)
```markdown
# API Usage Examples

## Authentication
If API key authentication is enabled, include the key in the header:
```bash
curl -H "X-API-Key: your-api-key-here" https://api.example.com/api/v1/stations/
```

## Get Station Information
```bash
# Get details for a specific station
curl https://api.example.com/api/v1/stations/01646500

# Search stations by state
curl "https://api.example.com/api/v1/stations/?state_code=MD"

# Search stations by HUC
curl "https://api.example.com/api/v1/stations/?huc_prefix=02"
```

## Get Discharge Observations
```bash
# Get daily mean observations for 2023
curl "https://api.example.com/api/v1/observations/01646500?\
start_date=2023-01-01T00:00:00&\
end_date=2023-12-31T23:59:59&\
data_type=daily_mean"

# Get latest observation
curl "https://api.example.com/api/v1/observations/01646500/latest"

# Export observations as CSV
curl "https://api.example.com/api/v1/observations/01646500?\
start_date=2023-01-01T00:00:00&\
format=csv" > observations.csv
```

## Get Forecasts
```bash
# Get latest forecast
curl "https://api.example.com/api/v1/forecasts/01646500/latest"

# Get all forecasts in date range
curl "https://api.example.com/api/v1/forecasts/01646500?\
start_date=2024-01-01T00:00:00&\
end_date=2024-01-31T23:59:59"
```

## Python Client Example
```python
import requests
from datetime import datetime, timedelta

API_BASE_URL = "https://api.example.com/api/v1"
API_KEY = "your-api-key"

headers = {"X-API-Key": API_KEY}

# Get station information
response = requests.get(
    f"{API_BASE_URL}/stations/01646500",
    headers=headers
)
station = response.json()
print(f"Station: {station['name']}")

# Get observations
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

response = requests.get(
    f"{API_BASE_URL}/observations/01646500",
    params={
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "data_type": "daily_mean"
    },
    headers=headers
)

observations = response.json()
print(f"Retrieved {observations['count']} observations")

# Process data
for obs in observations['observations']:
    print(f"{obs['observed_at']}: {obs['discharge']} {obs['unit']}")
```
```

---

### Phase 9: Deployment

#### 9.1 Docker Configuration (`Dockerfile.api`)
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Expose port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### 9.2 Docker Compose (`docker-compose.api.yml`)
```yaml
version: '3.8'

services:
  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/streamflow_db
      - API_KEY_ENABLED=true
      - RATE_LIMIT_PER_MINUTE=60
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=streamflow_db
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
```

#### 9.3 Systemd Service (`/etc/systemd/system/streamflow-api.service`)
```ini
[Unit]
Description=Streamflow DataOps API
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/streamflow_dataops
Environment="PATH=/opt/streamflow_dataops/venv/bin"
ExecStart=/opt/streamflow_dataops/venv/bin/uvicorn \
    src.api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

#### 9.4 Nginx Configuration
```nginx
server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Rate limiting
        limit_req zone=api_limit burst=20 nodelay;
    }
}

# Rate limit zone definition (add to http block)
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=60r/m;
```

---

## Implementation Checklist

- [ ] Phase 1: Project structure and dependencies
- [ ] Phase 2: FastAPI application setup
- [ ] Phase 3: Pydantic schemas
- [ ] Phase 4: Database dependencies
- [ ] Phase 5: Service layer implementation
- [ ] Phase 6: API endpoint implementation
  - [ ] Station endpoints
  - [ ] Observation endpoints
  - [ ] Forecast endpoints
  - [ ] Health check endpoints
- [ ] Phase 7: Testing
  - [ ] Unit tests
  - [ ] Integration tests
  - [ ] Load testing
- [ ] Phase 8: Documentation
  - [ ] API examples
  - [ ] Client libraries
- [ ] Phase 9: Deployment
  - [ ] Docker configuration
  - [ ] Production deployment
  - [ ] Monitoring setup

---

## Key Features

1. **RESTful API Design**: Clean, intuitive endpoints following REST principles
2. **Automatic Documentation**: OpenAPI/Swagger UI at `/docs`
3. **Data Export**: Support for JSON and CSV formats
4. **Rate Limiting**: Protection against abuse
5. **Authentication**: Optional API key authentication
6. **Error Handling**: Comprehensive error responses
7. **Performance**: Optimized queries and response times
8. **Scalability**: Horizontal scaling with multiple workers

---

## Performance Optimization

### 1. Database Query Optimization
- Use indexes on frequently queried fields
- Implement query result caching
- Use pagination for large result sets

### 2. API Caching
```python
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache

@router.get("/stations/{station_number}")
@cache(expire=3600)  # Cache for 1 hour
async def get_station(...):
    ...
```

### 3. Response Compression
```python
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)
```

---

## Security Best Practices

1. **HTTPS Only**: Always use HTTPS in production
2. **API Key Rotation**: Implement key rotation mechanism
3. **Input Validation**: Pydantic schemas validate all inputs
4. **SQL Injection**: SQLAlchemy ORM prevents SQL injection
5. **Rate Limiting**: Prevents DOS attacks
6. **CORS**: Configure appropriately for production
7. **Error Messages**: Don't expose sensitive information

---

## Monitoring and Observability

### 1. Logging
```python
import logging
from fastapi import Request

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"{request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Status: {response.status_code}")
    return response
```

### 2. Metrics (Prometheus)
```python
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)
```

### 3. Health Monitoring
- Use `/health` endpoint for liveness checks
- Use `/health/ready` for readiness checks
- Monitor response times and error rates

---

## Next Steps

1. **Add GraphQL Support**: Consider adding GraphQL endpoint
2. **WebSocket Streaming**: Real-time data streaming
3. **Batch Operations**: Support bulk data requests
4. **Data Versioning**: API versioning strategy
5. **Client SDKs**: Generate client libraries for Python, JavaScript, R
6. **Advanced Filtering**: More complex query capabilities
7. **Data Aggregation**: Pre-computed statistics and summaries

