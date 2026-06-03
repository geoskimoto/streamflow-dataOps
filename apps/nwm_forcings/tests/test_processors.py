"""Tests for NWM variable extraction and daily aggregation."""
import math
import numpy as np
import pytest


def test_vapor_pressure_from_specific_humidity():
    from apps.nwm_forcings.processors import vapor_pressure_pa

    result = vapor_pressure_pa(q=0.01, psfc=101325.0)
    assert 1500 < result < 1700


def test_vapor_pressure_zero_humidity():
    from apps.nwm_forcings.processors import vapor_pressure_pa

    result = vapor_pressure_pa(q=0.0, psfc=101325.0)
    assert result == pytest.approx(0.0, abs=1.0)


def test_daylight_seconds_equinox_midlat():
    from apps.nwm_forcings.processors import daylight_seconds

    result = daylight_seconds(lat_deg=45.0, doy=80)
    assert 43000 < result < 44000


def test_daylight_seconds_summer_solstice():
    from apps.nwm_forcings.processors import daylight_seconds

    result = daylight_seconds(lat_deg=47.0, doy=172)
    assert result > 54000


def test_daylight_seconds_winter_solstice():
    from apps.nwm_forcings.processors import daylight_seconds

    result = daylight_seconds(lat_deg=47.0, doy=355)
    assert result < 32400


def test_extract_basin_value_mean():
    from apps.nwm_forcings.processors import extract_basin_value

    data = np.zeros((10, 10), dtype=np.float32)
    data[2:5, 3:6] = 5.0
    y_idx = np.array([2, 3, 4, 2, 3, 4], dtype=np.int32)
    x_idx = np.array([3, 3, 3, 4, 4, 4], dtype=np.int32)
    result = extract_basin_value(data, y_idx, x_idx)
    assert result == pytest.approx(5.0)


def test_extract_basin_value_empty_indices():
    from apps.nwm_forcings.processors import extract_basin_value

    data = np.ones((10, 10), dtype=np.float32)
    result = extract_basin_value(data, np.array([], dtype=np.int32), np.array([], dtype=np.int32))
    assert np.isnan(result)


def test_aggregate_hourly_records_to_daily():
    from apps.nwm_forcings.processors import aggregate_hourly_to_daily

    records = []
    for h in range(24):
        records.append({
            "rainrate_mm_s": 0.001,
            "t2d_k": 280.0 + h * 0.5,
            "swdown_w_m2": max(0.0, 500.0 * math.sin(math.pi * h / 12)),
            "vp_pa": 800.0,
        })

    result = aggregate_hourly_to_daily(records, centroid_lat=47.0, target_date_doy=172)

    assert result["prcp_mm_day"] == pytest.approx(86.4, rel=1e-3)
    assert result["tmin_c"] == pytest.approx(6.85, abs=0.1)
    assert result["tmax_c"] == pytest.approx(18.35, abs=0.1)
    assert result["srad_w_m2"] > 0
    assert result["vp_pa"] == pytest.approx(800.0)
    assert result["dayl_s"] > 54000
