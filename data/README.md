# Sample USGS to NOAA-HADS Station ID Mappings

This file contains example mappings between USGS station IDs and NOAA HADS (Hydrometeorological Automated Data System) IDs.

To load these mappings:
```bash
python manage.py load_station_mappings --csv-file data/sample_station_mappings.csv
```

## Finding Mappings

1. **USGS Water Data**: https://waterdata.usgs.gov/nwis
2. **NOAA HADS**: https://hads.ncep.noaa.gov/
3. **Cross-reference**: Look up station names and locations to match IDs

## Format

CSV file should have columns: `usgs_id,hads_id`

Example stations in the Potomac River Basin and Chesapeake Bay area are included in the sample CSV.
