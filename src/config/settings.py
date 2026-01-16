"""Configuration settings for the application."""

import os
from dotenv import load_dotenv

load_dotenv()

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./streamflow_dev.db")

# Redis / Celery
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# API Configuration
USGS_BASE_URL = "https://waterservices.usgs.gov/nwis"
EC_BASE_URL = "https://wateroffice.ec.gc.ca/services"
NOAA_NWM_BASE_URL = "https://api.water.noaa.gov/nwps/v1"

# Retry settings
MAX_RETRIES = 3
RETRY_BACKOFF = 300  # 5 minutes in seconds
