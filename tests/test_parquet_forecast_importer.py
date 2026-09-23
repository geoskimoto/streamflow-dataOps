"""Tests for the streaming NWRFC parquet importer.

Covers the two defects that would have made a full import fail silently
(wrong ON CONFLICT key, swallowed exceptions) and the streaming behaviour
required by a 144M-row file.
"""

from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.streamflow.models import ForecastRun, Station
from src.acquisition.parquet_forecast_importer import (
    infer_forecast_type,
    iter_forecast_runs,
)


def _write_parquet(tmp_path, rows, row_group_size=None):
    """Write rows [(lid, issuance, sim_time, cfs), ...] to a parquet file."""
    df = pd.DataFrame(rows, columns=["lid", "issuance_time", "sim_time", "simulation (cfs)"])
    table = pa.Table.from_pandas(df, preserve_index=False)
    path = tmp_path / "forecasts.parquet"
    pq.write_table(table, path, row_group_size=row_group_size or len(df))
    return str(path)


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="CHDW1", name="Test", agency="NOAA_RFC", is_active=True
    )


# --- forecast_type inference ------------------------------------------------

@pytest.mark.parametrize(
    "horizon_hours,expected",
    [(24.0, "short"), (7 * 24, "short"), (7 * 24 + 0.1, "medium"),
     (10 * 24, "medium"), (10 * 24 + 0.1, "long")],
)
def test_infer_forecast_type_boundaries(horizon_hours, expected):
    assert infer_forecast_type(horizon_hours) == expected


# --- streaming --------------------------------------------------------------

def test_iter_forecast_runs_yields_one_run_per_issuance(tmp_path):
    iss = datetime(2010, 1, 1, 18, 7)
    rows = [
        ("CHDW1", iss, datetime(2010, 1, 2, 0, 0), 2380.0),
        ("CHDW1", iss, datetime(2010, 1, 2, 6, 0), 2370.0),
        ("CHDW1", datetime(2010, 1, 2, 22, 59), datetime(2010, 1, 3, 0, 0), 2380.0),
    ]
    runs = list(iter_forecast_runs(_write_parquet(tmp_path, rows)))
    assert len(runs) == 2


def test_iter_forecast_runs_handles_group_straddling_row_groups(tmp_path):
    """A single (lid, issuance_time) group may span two row groups.

    Emitting per row group without buffering would split this into two runs
    of one point each instead of one run of two points.
    """
    iss = datetime(2010, 1, 1, 18, 7)
    rows = [
        ("CHDW1", iss, datetime(2010, 1, 2, 0, 0), 2380.0),
        ("CHDW1", iss, datetime(2010, 1, 2, 6, 0), 2370.0),
    ]
    path = _write_parquet(tmp_path, rows, row_group_size=1)
    assert pq.ParquetFile(path).metadata.num_row_groups == 2

    runs = list(iter_forecast_runs(path))
    assert len(runs) == 1
    assert len(runs[0][2]) == 2


def test_iter_forecast_runs_sorts_points_and_formats_dates(tmp_path):
    iss = datetime(2010, 1, 1, 18, 7)
    rows = [
        ("CHDW1", iss, datetime(2010, 1, 2, 6, 0), 2370.0),
        ("CHDW1", iss, datetime(2010, 1, 2, 0, 0), 2380.0),
    ]
    _, _, points, _ = list(iter_forecast_runs(_write_parquet(tmp_path, rows)))[0]
    assert points == [
        {"date": "2010-01-02T00:00:00Z", "value": 2380.0},
        {"date": "2010-01-02T06:00:00Z", "value": 2370.0},
    ]


def test_iter_forecast_runs_returns_utc_aware_issuance(tmp_path):
    rows = [("CHDW1", datetime(2010, 1, 1, 18, 7), datetime(2010, 1, 2, 0, 0), 2380.0)]
    _, issuance, _, _ = list(iter_forecast_runs(_write_parquet(tmp_path, rows)))[0]
    assert issuance == datetime(2010, 1, 1, 18, 7, tzinfo=timezone.utc)


def test_single_point_run_is_emitted_not_dropped(tmp_path):
    """820 runs in the real archive have exactly one point."""
    rows = [("CHDW1", datetime(2010, 1, 1, 18, 7), datetime(2010, 1, 2, 0, 0), 2380.0)]
    runs = list(iter_forecast_runs(_write_parquet(tmp_path, rows)))
    assert len(runs) == 1
    assert len(runs[0][2]) == 1


def test_negative_horizon_run_is_emitted_not_dropped(tmp_path):
    """One run in the real archive ends before it was issued.

    It must survive to the import so the anomaly is logged, not silently lost.
    """
    rows = [("CHDW1", datetime(2010, 1, 10, 18, 7), datetime(2010, 1, 6, 0, 0), 2380.0)]
    runs = list(iter_forecast_runs(_write_parquet(tmp_path, rows)))
    assert len(runs) == 1
    assert runs[0][3] == "short"  # negative horizon falls through the <= 7d branch


def test_unsorted_file_raises_rather_than_splitting_runs(tmp_path):
    """The carry-forward buffering assumes issuance_time is non-decreasing.

    A file that violates it would silently split runs across row groups, so
    the iterator must refuse rather than emit wrong data.
    """
    rows = [
        ("CHDW1", datetime(2010, 1, 5, 0, 0), datetime(2010, 1, 6, 0, 0), 1.0),
        ("CHDW1", datetime(2010, 1, 1, 0, 0), datetime(2010, 1, 2, 0, 0), 2.0),
    ]
    path = _write_parquet(tmp_path, rows, row_group_size=1)
    with pytest.raises(ValueError, match="not sorted by issuance_time"):
        list(iter_forecast_runs(path))


# --- upsert key -------------------------------------------------------------

def test_bulk_create_upsert_uses_all_five_unique_fields(station, db):
    """The real index is (station, source, run_date, forecast_type, is_forecast).

    Omitting is_forecast raises 'no unique or exclusion constraint matching
    the ON CONFLICT specification'.
    """
    run_date = datetime(2010, 1, 1, 18, 7, tzinfo=timezone.utc)
    first = ForecastRun(
        station=station, source="NOAA_RFC", run_date=run_date,
        forecast_type="medium", is_forecast=True,
        data=[{"date": "2010-01-02T00:00:00Z", "value": 2380.0}],
    )
    ForecastRun.objects.bulk_create(
        [first], update_conflicts=True, update_fields=["data"],
        unique_fields=["station", "source", "run_date", "forecast_type", "is_forecast"],
    )

    second = ForecastRun(
        station=station, source="NOAA_RFC", run_date=run_date,
        forecast_type="medium", is_forecast=True,
        data=[{"date": "2010-01-02T00:00:00Z", "value": 9999.0}],
    )
    ForecastRun.objects.bulk_create(
        [second], update_conflicts=True, update_fields=["data"],
        unique_fields=["station", "source", "run_date", "forecast_type", "is_forecast"],
    )

    runs = ForecastRun.objects.filter(station=station)
    assert runs.count() == 1
    assert runs.first().data[0]["value"] == 9999.0


def test_flush_batch_raises_instead_of_returning_zero(station, db, monkeypatch):
    """A failed flush must not be reported as a successful no-op."""
    import io

    from django.core.management.color import no_style

    from src.acquisition.parquet_forecast_importer import ParquetForecastImporter

    importer = ParquetForecastImporter(io.StringIO(), io.StringIO(), no_style())

    def boom(*args, **kwargs):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(ForecastRun.objects, "bulk_create", boom)

    with pytest.raises(RuntimeError, match="database exploded"):
        importer._flush_batch([ForecastRun(station=station, source="NOAA_RFC",
                                           run_date=datetime(2010, 1, 1, tzinfo=timezone.utc),
                                           forecast_type="medium", is_forecast=True, data=[])],
                              dry_run=False)
