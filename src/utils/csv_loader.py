"""Utility for loading master station list from CSV."""
import pandas as pd
from typing import List, Dict, Any
from pathlib import Path


def load_master_stations_from_csv(csv_path: str) -> List[Dict[str, Any]]:
    """
    Load master station list from CSV file.
    
    Expected CSV columns:
    - station_number (or site_no)
    - station_name (or station_nm)
    - latitude (or dec_lat_va)
    - longitude (or dec_long_va)
    - state_code (or state_cd)
    - huc_code (or huc_cd)
    - altitude_ft (or alt_va)
    - drainage_area_sqmi (or drain_area_va)
    - agency (optional, defaults to 'USGS')
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        List of dictionaries with station data
    """
    csv_file = Path(csv_path)
    
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    # Read CSV
    df = pd.read_csv(csv_path, dtype=str)
    
    # Map USGS column names to our schema
    column_mapping = {
        'site_no': 'station_number',
        'station_nm': 'station_name',
        'dec_lat_va': 'latitude',
        'dec_long_va': 'longitude',
        'state_cd': 'state_code',
        'huc_cd': 'huc_code',
        'alt_va': 'altitude_ft',
        'drain_area_va': 'drainage_area_sqmi'
    }
    
    # Rename columns if they match USGS format
    df = df.rename(columns=column_mapping)
    
    # Convert to list of dicts
    stations = []
    for _, row in df.iterrows():
        station_data = {
            'station_number': str(row.get('station_number', '')).strip(),
            'station_name': str(row.get('station_name', '')).strip(),
            'latitude': _convert_to_float(row.get('latitude')),
            'longitude': _convert_to_float(row.get('longitude')),
            'state_code': str(row.get('state_code', '')).strip() or None,
            'huc_code': str(row.get('huc_code', '')).strip() or None,
            'altitude_ft': _convert_to_float(row.get('altitude_ft')),
            'drainage_area_sqmi': _convert_to_float(row.get('drainage_area_sqmi')),
            'agency': str(row.get('agency', 'USGS')).strip()
        }
        
        # Only add if station_number is valid
        if station_data['station_number']:
            stations.append(station_data)
    
    return stations


def load_station_mappings_from_csv(csv_path: str) -> List[Dict[str, Any]]:
    """
    Load station ID mappings from CSV file.
    
    Expected CSV columns:
    - source_agency
    - source_id
    - target_agency
    - target_id
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        List of dictionaries with mapping data
    """
    csv_file = Path(csv_path)
    
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    df = pd.read_csv(csv_path, dtype=str)
    
    mappings = []
    for _, row in df.iterrows():
        mapping_data = {
            'source_agency': str(row.get('source_agency', '')).strip(),
            'source_id': str(row.get('source_id', '')).strip(),
            'target_agency': str(row.get('target_agency', '')).strip(),
            'target_id': str(row.get('target_id', '')).strip()
        }
        
        # Only add if all required fields are present
        if all(mapping_data.values()):
            mappings.append(mapping_data)
    
    return mappings


def _convert_to_float(value: Any) -> float:
    """Convert value to float, handling empty/invalid values."""
    if pd.isna(value) or value == '' or value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def example_usage():
    """Example of how to use the CSV loader."""
    from src.database.connection import SessionLocal
    from src.database.repositories import MasterStationRepository
    
    # Load stations from CSV
    stations = load_master_stations_from_csv('data/usgs_stations.csv')
    
    # Insert into database
    db = SessionLocal()
    try:
        repo = MasterStationRepository(db)
        count = repo.bulk_upsert(stations)
        print(f"Loaded {count} stations into master_stations table")
    finally:
        db.close()


if __name__ == "__main__":
    example_usage()
