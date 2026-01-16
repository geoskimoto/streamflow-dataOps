"""Database initialization script."""

from src.database.connection import engine, Base
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


def init_db():
    """Create all database tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created successfully!")


def drop_db():
    """Drop all database tables (use with caution!)."""
    print("WARNING: Dropping all database tables...")
    Base.metadata.drop_all(bind=engine)
    print("✓ Database tables dropped!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--drop":
        response = input("Are you sure you want to drop all tables? (yes/no): ")
        if response.lower() == "yes":
            drop_db()
            init_db()
        else:
            print("Operation cancelled.")
    else:
        init_db()
