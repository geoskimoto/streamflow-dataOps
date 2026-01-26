# Quick Start: Environment Canada Integration

## Run These Commands to Complete the Integration

### 1. Import British Columbia Stations
```bash
cd /home/mrguy/Proj/streamflow-dataOps/streamflow-dataOps
python manage.py import_bc_stations
```

**What it does:** Fetches all BC hydrometric stations from Environment Canada API and adds them to the MasterStation table.

**Expected output:**
```
======================================================================
Importing BC stations from Environment Canada
======================================================================
Fetching stations from API (limit=5000)...
✓ Fetched 1234 stations from API

Importing stations into MasterStation table...
  ... 100 stations created
  ... 200 stations created
  ...

======================================================================
Import Summary
======================================================================
✓ Created: 1234 new stations
✓ Updated: 0 existing stations

MasterStation table now contains:
  • 1234 BC stations (EC)
  • 1234 total EC stations
  • 13229 total stations (all agencies)
```

---

### 2. Populate StationMapping Table
```bash
python manage.py populate_station_mappings
```

**What it does:** Links Station records to MasterStation records, enabling the RFC filter.

**Expected output:**
```
======================================================================
Populating StationMapping Table
======================================================================

Processing 309 Station records...
  ... 50 mappings created
  ... 100 mappings created
  ...

======================================================================
StationMapping Summary
======================================================================
✓ Created: 309 new mappings
  Already existed: 0 mappings

StationMapping table now contains:
  • 309 total mappings
  • 309 unique Station records mapped
  • 309 unique MasterStation records mapped

RFC code distribution in mapped stations:
  • NCRFC: 45 stations
  • MARFC: 38 stations
  • NERFC: 156 stations
  • None: 70 stations

✓ Successfully populated StationMapping table!
  The RFC filter should now work correctly.
```

---

### 3. Start Development Server and Test
```bash
python manage.py runserver
```

Then visit: http://localhost:8000/stations/

**Test checklist:**
- [ ] Check "Show only stations in active configurations" box
- [ ] Verify station count drops to ~200
- [ ] Uncheck box and verify count returns to 309
- [ ] Select an RFC from dropdown
- [ ] Verify filtered stations appear
- [ ] Select a Configuration from dropdown
- [ ] Verify filtered stations appear
- [ ] Try combining filters

---

## Optional: Import Only Active BC Stations

If you only want stations with real-time data:
```bash
python manage.py import_bc_stations --active-only
```

This will import only stations with `REAL_TIME=1`.

---

## Optional: Test EC Data Retrieval

```bash
python test_ec_client.py
```

This will test:
- Station metadata retrieval
- Daily mean data retrieval
- Unit conversion (cms to cfs)
- BC station listing

---

## Troubleshooting

### If import_bc_stations is slow:
- Normal for first run (~1-2 minutes for ~1200 stations)
- API rate limiting may occur
- Use `--limit 100` to test with smaller batch

### If RFC filter is empty after populate_station_mappings:
1. Restart Django server
2. Check that StationMapping has records: 
   ```bash
   python manage.py dbshell
   SELECT COUNT(*) FROM station_mapping;
   ```

### If "configured only" checkbox doesn't filter:
- Make sure you have PullConfigurationStation records
- Check browser console for JavaScript errors
- Try hard refresh (Ctrl+Shift+R)

---

## Expected Results

### Before Running Commands:
- MasterStation: 11,995 records (USGS + NOAA only)
- StationMapping: 0 records (empty)
- Station: 309 records
- RFC filter: Not functional
- EC stations: Not available

### After Running Commands:
- MasterStation: ~13,200 records (USGS + NOAA + BC EC)
- StationMapping: 309 records
- Station: 309 records (unchanged)
- RFC filter: Fully functional
- EC stations: Available in /stations/all and can be synced

---

## Next Steps After Testing

1. **Add EC stations to configurations:**
   - Go to /stations/all
   - Filter by Agency: Environment Canada
   - Click "Sync Master" to add desired BC stations to Station table
   - Add them to pull configurations

2. **Test data acquisition:**
   - Create a PullConfiguration with `data_source='EC'`
   - Add BC stations to the configuration
   - Run data pull manually or via Celery
   - Verify discharge observations in cms and cfs

3. **Monitor performance:**
   - Check API response times
   - Verify unit conversions are correct
   - Test with different date ranges
