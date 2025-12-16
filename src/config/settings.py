"""Configuration settings for the application."""
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./streamflow_dev.db')
