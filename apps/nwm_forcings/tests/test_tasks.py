"""Integration tests for the NWM daily ingestion task."""
import shutil
import numpy as np
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch


def make_24_hourly_files(tmp_path: Path, nc_file: Path) -> list[Path]:
    """Return 24 distinct copies of nc_file named nwm_t00z.nc … nwm_t23z.nc.

    Deduplication in ingest_day works by resolved path, so each copy must
    be a separate file on disk.
    """
    hourly_dir = tmp_path / "hourly"
    hourly_dir.mkdir(exist_ok=True)
    files = []
    for h in range(24):
        dest = hourly_dir / f"nwm_t{h:02d}z.nc"
        shutil.copy(str(nc_file), str(dest))
        files.append(dest)
    return files


def make_synthetic_nc(tmp_path: Path, ny=50, nx=60) -> Path:
    """Write a minimal NWM-like NetCDF file with the expected variables."""
    import netCDF4 as nc4

    out = tmp_path / "synthetic_nwm.nc"
    ds = nc4.Dataset(out, "w")
    ds.createDimension("Time", 1)
    ds.createDimension("south_north", ny)
    ds.createDimension("west_east", nx)

    def _make_var(name, fill=1.0):
        v = ds.createVariable(name, "f4", ("Time", "south_north", "west_east"))
        v[:] = fill
        return v

    _make_var("RAINRATE", 0.001)
    _make_var("T2D", 283.15)
    _make_var("Q2D", 0.005)
    _make_var("SWDOWN", 200.0)
    _make_var("PSFC", 95000.0)

    lats = np.linspace(44.0, 50.0, ny).reshape(1, ny, 1) * np.ones((1, ny, nx))
    lons = np.linspace(-125.0, -110.0, nx).reshape(1, 1, nx) * np.ones((1, ny, nx))
    xlat = ds.createVariable("XLAT_M", "f4", ("Time", "south_north", "west_east"))
    xlon = ds.createVariable("XLONG_M", "f4", ("Time", "south_north", "west_east"))
    xlat[:] = lats
    xlon[:] = lons
    ds.close()
    return out


@pytest.mark.django_db
def test_ingest_day_writes_basin_forcing(tmp_path, db):
    """Single-station ingestion with mock files writes BasinForcing row."""
    from apps.nwm_forcings.tasks import ingest_day
    from apps.streamflow.models import BasinForcing, Station
    from apps.nwm_forcings.weights import save_weights

    nc_file = make_synthetic_nc(tmp_path)
    y_idx = np.array([10, 11, 12], dtype=np.int32)
    x_idx = np.array([20, 21, 22], dtype=np.int32)
    weights_dir = tmp_path / "weights"
    weights_dir.mkdir()
    usgs_id = "14306500"
    save_weights(weights_dir / f"{usgs_id}.npz", y_idx, x_idx, 47.0, -117.0)

    station, _ = Station.objects.get_or_create(
        station_number=usgs_id,
        defaults={"agency": "USGS", "name": "Test Station"},
    )

    hourly_files = make_24_hourly_files(tmp_path, nc_file)
    ingest_date = date(2026, 1, 15)
    with patch("apps.nwm_forcings.tasks.settings") as mock_settings, \
         patch("apps.nwm_forcings.tasks.EA_LSTM_USGS_IDS", [usgs_id]):
        mock_settings.NWM_WEIGHTS_DIR = str(weights_dir)
        ingest_day(ingest_date=ingest_date, hourly_files=hourly_files)

    forcing = BasinForcing.objects.filter(
        station=station, date=ingest_date, source="nwm"
    ).first()
    assert forcing is not None
    assert forcing.prcp_mm_day == pytest.approx(0.001 * 86400, rel=1e-3)
    assert forcing.tmax_c == pytest.approx(283.15 - 273.15, abs=0.01)
    assert forcing.tmin_c == pytest.approx(283.15 - 273.15, abs=0.01)
    assert forcing.srad_w_m2 == pytest.approx(200.0, abs=0.1)
    assert forcing.dayl_s > 0


@pytest.mark.django_db
def test_ingest_day_upserts_on_rerun(tmp_path, db):
    """Re-ingesting the same date updates rather than duplicating rows."""
    from apps.nwm_forcings.tasks import ingest_day
    from apps.streamflow.models import BasinForcing, Station
    from apps.nwm_forcings.weights import save_weights

    nc_file = make_synthetic_nc(tmp_path)
    weights_dir = tmp_path / "weights"
    weights_dir.mkdir()
    usgs_id = "14306500"
    save_weights(
        weights_dir / f"{usgs_id}.npz",
        np.array([10], dtype=np.int32),
        np.array([20], dtype=np.int32),
        47.0, -117.0,
    )
    station, _ = Station.objects.get_or_create(
        station_number=usgs_id,
        defaults={"agency": "USGS", "name": "Test Station"},
    )

    hourly_files = make_24_hourly_files(tmp_path, nc_file)
    ingest_date = date(2026, 1, 15)
    with patch("apps.nwm_forcings.tasks.settings") as ms, \
         patch("apps.nwm_forcings.tasks.EA_LSTM_USGS_IDS", [usgs_id]):
        ms.NWM_WEIGHTS_DIR = str(weights_dir)
        ingest_day(ingest_date=ingest_date, hourly_files=hourly_files)
        ingest_day(ingest_date=ingest_date, hourly_files=hourly_files)

    assert BasinForcing.objects.filter(
        station=station, date=ingest_date, source="nwm"
    ).count() == 1


@pytest.mark.django_db
def test_ingest_nwm_forcings_daily_writes_log(tmp_path, db):
    """ingest_nwm_forcings_daily writes NWMIngestionLog row."""
    from apps.nwm_forcings.tasks import ingest_nwm_forcings_daily
    from apps.nwm_forcings.models import NWMIngestionLog
    from apps.streamflow.models import Station
    from apps.nwm_forcings.weights import save_weights
    from datetime import date, timedelta

    nc_file = make_synthetic_nc(tmp_path)
    weights_dir = tmp_path / "weights"
    weights_dir.mkdir()
    usgs_id = "14306500"
    save_weights(
        weights_dir / f"{usgs_id}.npz",
        np.array([10, 11], dtype=np.int32),
        np.array([20, 21], dtype=np.int32),
        47.0, -117.0,
    )
    Station.objects.get_or_create(
        station_number=usgs_id,
        defaults={"agency": "USGS", "name": "Test"},
    )

    yesterday = date.today() - timedelta(days=1)

    import shutil as _shutil

    def _fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        _shutil.copy(str(nc_file), str(dest))
        return dest

    with patch("apps.nwm_forcings.tasks.settings") as ms, \
         patch("apps.nwm_forcings.tasks.download_file", side_effect=_fake_download), \
         patch("apps.nwm_forcings.tasks.build_nomads_url", return_value="http://x"), \
         patch("apps.nwm_forcings.tasks.EA_LSTM_USGS_IDS", [usgs_id]):
        ms.NWM_WEIGHTS_DIR = str(weights_dir)
        ms.NWM_NOMADS_BASE = "https://nomads.ncep.noaa.gov"
        ms.NWM_TEMP_DIR = str(tmp_path / "temp")
        result = ingest_nwm_forcings_daily()

    assert result["status"] == "success"
    assert result["stations_updated"] == 1
    log = NWMIngestionLog.objects.get(ingest_date=yesterday)
    assert log.stations_updated == 1
