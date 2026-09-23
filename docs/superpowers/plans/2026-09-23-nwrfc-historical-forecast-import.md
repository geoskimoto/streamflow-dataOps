# NWRFC Historical Forecast Archive Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load the complete NWRFC historical forecast archive (3,596,831 runs, WY2006–2026) into `forecast_runs`, after correcting the `run_date` key semantics that currently prevent the archive from superseding live-pull rows.

**Architecture:** Three independent code changes followed by one data operation. First fix `NOAAClient.get_rfc_forecast()` so live pulls key on the NWPS `issuedTime` field rather than falling back to `datetime.now()`. Then make the live pull path upsert on the full unique tuple with an explicit `forecast_type`. Then rewrite `ParquetForecastImporter` to stream row groups instead of loading a 144M-row DataFrame, with a corrected `ON CONFLICT` key that no longer fails silently. Finally back up, delete the superseded window, and load the archive.

**Tech Stack:** Python 3.12, Django 6.0, PostgreSQL (production) / SQLite (tests), pyarrow 23.0, pandas 2.1, pytest with `--reuse-db`.

## Global Constraints

- Source file: `/home/geoskimoto/projects/resid-cast/all_nwrfc_forecasts_WY2006_2026.parquet` — read-only, never modified.
- Parquet schema: `lid` (large_string), `issuance_time` (timestamp[us]), `sim_time` (timestamp[us]), `simulation (cfs)` (double).
- Archive coverage window: `2005-10-01 00:13:00+00` through `2026-09-22 16:24:00+00`.
- The real unique constraint is `unique_forecast_run (station_id, source, run_date, forecast_type, is_forecast)`. Any `bulk_create(update_conflicts=True)` must pass **all five** fields as `unique_fields`.
- `forecast_type` inference rule (unchanged): horizon ≤ 7 days → `short`, ≤ 10 days → `medium`, > 10 days → `long`.
- New `Station` records are created with `is_active=False`.
- LIDs `COQO3`, `SKMW1`, `WDHN2` are **excluded from the delete** — 708 runs preserved.
- Timestamps in the parquet are tz-naive and must be treated as UTC.
- **This working tree is production.** Code tasks (1–3) are done in a git worktree. Task 4 (the data operation) runs in this tree only after 1–3 are merged.
- Per the recorded baseline, ~311 tests already fail on clean `main`. Prove no regressions by diffing failure sets, not by expecting green.
- Run the venv python by absolute path: `venv/bin/python`. `source venv/bin/activate` does not put `python` on PATH in this environment.
- Reference spec: `docs/superpowers/specs/2026-09-23-nwrfc-historical-forecast-import-design.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/acquisition/noaa_client.py` | NWPS API client; derive `run_date` from `issuedTime` | Modify (lines 296–306) |
| `src/acquisition/tasks.py` | Live pull; upsert `ForecastRun` on full unique tuple | Modify (lines 181–187) |
| `src/acquisition/parquet_forecast_importer.py` | Streaming archive importer | Rewrite `run()` / `_flush_batch()`; keep station-resolution helpers |
| `tests/test_noaa_client_run_date.py` | Issuance-time parsing behaviour | Create |
| `tests/test_parquet_forecast_importer.py` | Upsert key, streaming group assembly, type inference | Create |
| `scripts/swap_nwrfc_archive.py` | Backup + scoped delete, reversible | Create |

Station-resolution helpers in `parquet_forecast_importer.py` (`_fetch_gauge_metadata`, `_create_station_from_metadata`, `_create_station_from_master`) are kept as-is apart from the `is_active` change. Only the ingest path is rewritten.

---

## Task 1: Derive `run_date` from the NWPS `issuedTime` field

Root cause of 68,057 mis-keyed rows. `get_rfc_forecast()` reads `forecast.get("issueTime")`; the API field is `issuedTime`, so the lookup always returns `None` and falls through to `datetime.now(timezone.utc)`. A bare `except:` hides malformed values the same way.

**Files:**
- Modify: `src/acquisition/noaa_client.py:296-306`
- Test: `tests/test_noaa_client_run_date.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `NOAAClient.get_rfc_forecast(lid: str) -> dict | None`. The returned dict keeps its existing keys `run_date` (tz-aware `datetime`, UTC), `forecast_data` (`list[dict]`), `rmse` (`float | None`). **New behaviour:** returns `None` when no issuance time can be determined. Task 2 depends on `run_date` being a true issuance time.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_noaa_client_run_date.py`:

```python
"""Tests for issuance-time derivation in NOAAClient.get_rfc_forecast.

The NWPS stageflow endpoint returns the issuance timestamp under the key
"issuedTime". Reading "issueTime" (no 'd') silently yields None, which is how
68,057 forecast_runs rows ended up keyed on fetch time instead of issuance
time. These tests pin the field name and forbid the now() fallback.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.acquisition.noaa_client import NOAAClient


def _payload(forecast_overrides=None):
    """Minimal stageflow payload shaped like the real API response."""
    forecast = {
        "issuedTime": "2026-09-22T15:26:00Z",
        "pedts": "QRIFF",
        "wfo": "PQR",
        "timeZone": "PST8PDT",
        "secondaryUnits": "kcfs",
        "data": [
            {"validTime": "2026-09-22T18:00:00Z", "primary": 3.31, "secondary": 1.34},
            {"validTime": "2026-09-23T00:00:00Z", "primary": 3.29, "secondary": 1.32},
        ],
    }
    if forecast_overrides is not None:
        forecast.update(forecast_overrides)
    return {"forecast": forecast}


@pytest.fixture
def client():
    return NOAAClient()


def _mock_get(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return patch("src.acquisition.noaa_client.requests.get", return_value=resp)


def test_run_date_reads_issuedTime(client):
    """run_date comes from 'issuedTime' — the actual NWPS field name."""
    with _mock_get(_payload()):
        result = client.get_rfc_forecast("WTLO3")
    assert result is not None
    assert result["run_date"] == datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)


def test_run_date_is_not_fetch_time(client):
    """Regression guard: run_date must never be a now() stand-in.

    The defect produced microsecond-precision timestamps; a real issuance
    time is minute-precision.
    """
    with _mock_get(_payload()):
        result = client.get_rfc_forecast("WTLO3")
    assert result["run_date"].second == 0
    assert result["run_date"].microsecond == 0


def test_falls_back_to_legacy_issueTime_key(client):
    """Tolerate the legacy spelling if some endpoint still emits it."""
    payload = _payload({"issuedTime": None, "issueTime": "2026-09-22T15:26:00Z"})
    with _mock_get(payload):
        result = client.get_rfc_forecast("WTLO3")
    assert result["run_date"] == datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)


def test_returns_none_when_issuance_time_missing(client):
    """No issuance time -> skip the run rather than invent a key."""
    payload = _payload({"issuedTime": None})
    with _mock_get(payload):
        result = client.get_rfc_forecast("WTLO3")
    assert result is None


def test_returns_none_when_issuance_time_malformed(client):
    """Unparseable issuance time -> skip, do not substitute now()."""
    payload = _payload({"issuedTime": "not-a-timestamp"})
    with _mock_get(payload):
        result = client.get_rfc_forecast("WTLO3")
    assert result is None


def test_malformed_issuance_time_is_logged(client, caplog):
    """The old bare `except:` hid this for months. It must be visible."""
    payload = _payload({"issuedTime": "not-a-timestamp"})
    with _mock_get(payload):
        with caplog.at_level("WARNING"):
            client.get_rfc_forecast("WTLO3")
    assert "not-a-timestamp" in caplog.text


def test_forecast_data_still_converts_kcfs_to_cfs(client):
    """Guard the surrounding behaviour we are not changing."""
    with _mock_get(_payload()):
        result = client.get_rfc_forecast("WTLO3")
    assert result["forecast_data"][0]["value"] == 1340.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_noaa_client_run_date.py -v`

Expected: `test_run_date_reads_issuedTime`, `test_run_date_is_not_fetch_time`, `test_returns_none_when_issuance_time_missing`, `test_returns_none_when_issuance_time_malformed` and `test_malformed_issuance_time_is_logged` FAIL. The current code returns a `now()`-derived `run_date` instead of the parsed or `None` value.

- [ ] **Step 3: Implement the fix**

Replace `src/acquisition/noaa_client.py` lines 296–306 (the block starting `# Get the issue time (run_date)`) with:

```python
            # Get the issue time (run_date).
            # NWPS spells this "issuedTime"; "issueTime" is accepted as a
            # legacy fallback. Never substitute now() — a fetch-time key
            # cannot be reconciled with the NWRFC archive.
            issue_time = forecast.get("issuedTime") or forecast.get("issueTime")
            if not issue_time:
                self.logger.warning(
                    f"No issuance time in forecast for {lid}; skipping run"
                )
                return None
            try:
                run_date = datetime.fromisoformat(issue_time.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                self.logger.warning(
                    f"Unparseable issuance time {issue_time!r} for {lid}; skipping run"
                )
                return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_noaa_client_run_date.py -v`

Expected: 7 passed.

- [ ] **Step 5: Confirm against the live API**

Run:

```bash
venv/bin/python -c "
from src.acquisition.noaa_client import NOAAClient
r = NOAAClient().get_rfc_forecast('WTLO3')
print(r['run_date'], len(r['forecast_data']))
"
```

Expected: a minute-precision UTC timestamp (e.g. `2026-09-22 15:26:00+00:00`) and a non-zero point count. If it prints a microsecond-precision time, the fix did not take.

- [ ] **Step 6: Commit**

```bash
git add src/acquisition/noaa_client.py tests/test_noaa_client_run_date.py
git commit -m "fix: read NWPS issuedTime so forecast run_date is issuance time

get_rfc_forecast() read forecast['issueTime'] but the NWPS field is
'issuedTime', so the lookup always returned None and fell through to
datetime.now(). That keyed 68,057 forecast_runs rows on fetch time instead of
issuance time, making them irreconcilable with the NWRFC archive.

Reads issuedTime with issueTime as a legacy fallback, and skips the run with a
warning when no issuance time can be parsed rather than inventing a key. The
bare except: that hid this is now a narrow except (ValueError, AttributeError)."
```

---

## Task 2: Upsert live forecast runs on the full unique tuple

The live pull calls `ForecastRun.objects.create()` with no `forecast_type`, so every live row is labelled `short` regardless of horizon — inconsistent with the archive, which labels the same 10-day forecasts `medium`. With Task 1 making `run_date` stable, a re-pull of the same issuance must update rather than duplicate.

The storing logic is currently inline inside a long branch of `_pull_station_data`, which cannot be tested without mocking the whole pull. Extract it into a module-level helper so the behaviour is directly exercisable.

**Files:**
- Modify: `src/acquisition/tasks.py:181-187`
- Test: `tests/test_noaa_rfc_pull_upsert.py`

**Interfaces:**
- Consumes: `NOAAClient.get_rfc_forecast()` from Task 1, returning `run_date` as a true issuance time; `_infer_forecast_type(horizon_hours: float) -> str` from `src.acquisition.parquet_forecast_importer` (Task 3 keeps this function at that path with that signature).
- Produces: `store_rfc_forecast(station, forecast_data: dict) -> tuple[ForecastRun, bool]` in `src.acquisition.tasks`, where `forecast_data` has keys `run_date`, `forecast_data`, `rmse`. Returns `(run, created)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_noaa_rfc_pull_upsert.py`:

```python
"""Tests for storing live NOAA_RFC forecast pulls.

Two behaviours are pinned: re-pulling the same issuance updates in place
rather than inserting a duplicate, and forecast_type reflects the actual
horizon instead of always defaulting to 'short'.
"""

from datetime import datetime, timezone

import pytest

from apps.streamflow.models import ForecastRun, Station
from src.acquisition.parquet_forecast_importer import _infer_forecast_type
from src.acquisition.tasks import store_rfc_forecast


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="WTLO3", name="Test Gauge", agency="NOAA_RFC", is_active=True
    )


def _payload(run_date, points, rmse=None):
    return {"run_date": run_date, "forecast_data": points, "rmse": rmse}


def test_repeat_issuance_updates_instead_of_duplicating(station):
    """The old create() inserted a second row for the same issuance."""
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    store_rfc_forecast(station, _payload(
        run_date, [{"date": "2026-09-22T18:00:00Z", "value": 1340.0}]))
    run, created = store_rfc_forecast(station, _payload(
        run_date, [{"date": "2026-09-22T18:00:00Z", "value": 1350.0}]))

    assert created is False
    runs = ForecastRun.objects.filter(station=station, source="NOAA_RFC")
    assert runs.count() == 1
    assert runs.first().data[0]["value"] == 1350.0


def test_ten_day_forecast_is_not_labelled_short(station):
    """The live path hardcoded 'short' by falling back to the model default."""
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    run, _ = store_rfc_forecast(station, _payload(run_date, [
        {"date": "2026-09-22T18:00:00Z", "value": 1340.0},
        {"date": "2026-10-02T18:00:00Z", "value": 1200.0},
    ]))
    assert run.forecast_type == "medium"


def test_short_horizon_is_labelled_short(station):
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    run, _ = store_rfc_forecast(station, _payload(run_date, [
        {"date": "2026-09-22T18:00:00Z", "value": 1340.0},
        {"date": "2026-09-25T18:00:00Z", "value": 1200.0},
    ]))
    assert run.forecast_type == "short"


def test_differing_horizons_do_not_collide(station):
    """Same issuance, different horizon -> distinct rows, per the unique key."""
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    store_rfc_forecast(station, _payload(run_date, [
        {"date": "2026-09-25T18:00:00Z", "value": 1.0}]))
    store_rfc_forecast(station, _payload(run_date, [
        {"date": "2026-10-02T18:00:00Z", "value": 2.0}]))
    assert ForecastRun.objects.filter(station=station).count() == 2


def test_rmse_is_persisted(station):
    run_date = datetime(2026, 9, 22, 15, 26, tzinfo=timezone.utc)
    run, _ = store_rfc_forecast(station, _payload(
        run_date, [{"date": "2026-09-23T18:00:00Z", "value": 1.0}], rmse=0.25))
    assert float(run.rmse) == 0.25


@pytest.mark.parametrize(
    "horizon_hours,expected",
    [
        (24.0, "short"),
        (7 * 24, "short"),        # boundary: exactly 7 days is short
        (7 * 24 + 0.1, "medium"),
        (10 * 24, "medium"),      # boundary: exactly 10 days is medium
        (10 * 24 + 0.1, "long"),
        (30 * 24, "long"),
    ],
)
def test_forecast_type_follows_horizon(horizon_hours, expected):
    assert _infer_forecast_type(horizon_hours) == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_noaa_rfc_pull_upsert.py -v`

Expected: collection fails with `ImportError: cannot import name 'store_rfc_forecast' from 'src.acquisition.tasks'`. The helper does not exist yet.

- [ ] **Step 3: Extract the helper and implement the upsert**

Add this module-level function to `src/acquisition/tasks.py`, near the other helpers:

```python
def store_rfc_forecast(station, forecast_data):
    """
    Upsert one NOAA_RFC forecast run.

    Keyed on the full unique tuple so re-pulling an issuance updates in place.
    forecast_type is derived from the actual horizon; the previous code let it
    fall back to the model default of 'short', labelling 10-day forecasts the
    same as 3-day ones.
    """
    from apps.streamflow.models import ForecastRun
    from src.acquisition.parquet_forecast_importer import _infer_forecast_type

    points = forecast_data['forecast_data']
    last_valid = datetime.fromisoformat(points[-1]['date'].replace('Z', '+00:00'))
    horizon_hours = (last_valid - forecast_data['run_date']).total_seconds() / 3600

    return ForecastRun.objects.update_or_create(
        station=station,
        source='NOAA_RFC',
        run_date=forecast_data['run_date'],
        forecast_type=_infer_forecast_type(horizon_hours),
        is_forecast=True,
        defaults={
            'data': points,
            'rmse': forecast_data.get('rmse'),
        },
    )
```

Then replace `src/acquisition/tasks.py` lines 181–187 (the `ForecastRun.objects.create(...)` call) with:

```python
                    store_rfc_forecast(station_obj, forecast_data)
```

Confirm `datetime` is imported at the top of `tasks.py`; add `from datetime import datetime` if it is not.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_noaa_rfc_pull_upsert.py -v`

Expected: 11 passed (5 tests + 6 parametrised cases).

- [ ] **Step 5: Commit**

```bash
git add src/acquisition/tasks.py tests/test_noaa_rfc_pull_upsert.py
git commit -m "fix: upsert NOAA_RFC pulls on full unique tuple with real forecast_type

The live pull used ForecastRun.objects.create() with no forecast_type, so every
live row was labelled 'short' by the model default regardless of horizon — the
same 10-day forecasts the NWRFC archive labels 'medium'. Re-pulling an issuance
also inserted a duplicate rather than updating.

Now infers forecast_type from the actual horizon and upserts on
(station, source, run_date, forecast_type, is_forecast)."
```

---

## Task 3: Stream the parquet and correct the upsert key

Two defects plus a scale problem. `_flush_batch` passes four `unique_fields` against a five-column index, so `ON CONFLICT` fails — and the bare `except Exception` returns `(0, 0)`, making total failure look like a clean no-op. Separately the importer loads all 144,269,656 rows via `pd.read_parquet()` and iterates with `.iterrows()`, which does not fit in the available 9 GB.

**Files:**
- Modify: `src/acquisition/parquet_forecast_importer.py`
- Test: `tests/test_parquet_forecast_importer.py`

**Interfaces:**
- Consumes: `_infer_forecast_type(horizon_hours: float) -> str` — keep this module-level function, unchanged in name and signature (Task 2 imports it).
- Produces:
  - `ParquetForecastImporter.run(parquet_path: str, dry_run: bool = False, filter_lids: list[str] | None = None, batch_size: int = 500) -> dict` returning keys `created`, `updated`, `failed`, `anomalies`.
  - `iter_forecast_runs(parquet_path: str) -> Iterator[tuple[str, datetime, list[dict], str]]` yielding `(lid, issuance_time_utc, data_points, forecast_type)`, where `data_points` is `[{"date": "%Y-%m-%dT%H:%M:%SZ", "value": float}, ...]` sorted by `sim_time`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_parquet_forecast_importer.py`:

```python
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
    _infer_forecast_type,
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
    assert _infer_forecast_type(horizon_hours) == expected


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_parquet_forecast_importer.py -v`

Expected: collection fails with `ImportError: cannot import name 'iter_forecast_runs'`. `test_flush_batch_raises_instead_of_returning_zero` also fails once importable, because `_flush_batch` currently swallows the exception and returns `(0, 0)`.

- [ ] **Step 3: Add the streaming iterator**

Add to `src/acquisition/parquet_forecast_importer.py`, after `_infer_forecast_type`:

```python
import pyarrow.parquet as pq


def iter_forecast_runs(parquet_path: str):
    """
    Stream (lid, issuance_time, data_points, forecast_type) tuples.

    Reads one row group at a time so a 144M-row file never lands in memory.
    A single (lid, issuance_time) group can straddle a row-group boundary,
    so the last issuance_time seen is held back until a later row group
    proves it complete. The file is ordered by issuance_time, which is what
    makes that single-key carry sufficient — verified across all 1,487 row
    groups of the WY2006-2026 archive, and re-checked here per row group so
    a future unsorted file fails loudly instead of silently splitting runs.
    """
    pf = pq.ParquetFile(parquet_path)
    carry = {}  # (lid, issuance_time) -> list[(sim_time, value)]
    prev_max_iss = None

    for rg in range(pf.metadata.num_row_groups):
        table = pf.read_row_groups([rg])
        lids = table.column("lid").to_pylist()
        issuances = table.column("issuance_time").to_pylist()
        sim_times = table.column("sim_time").to_pylist()
        values = table.column("simulation (cfs)").to_pylist()

        if prev_max_iss is not None and min(issuances) < prev_max_iss:
            raise ValueError(
                f"{parquet_path} is not sorted by issuance_time at row group "
                f"{rg} (min {min(issuances)} < previous max {prev_max_iss}); "
                "the streaming buffer would split runs"
            )

        buckets = dict(carry)
        carry = {}
        for lid, iss, st, val in zip(lids, issuances, sim_times, values):
            buckets.setdefault((lid, iss), []).append((st, val))

        # Hold back every group at the highest issuance_time in this row
        # group — those may continue into the next one.
        max_iss = max(issuances)
        prev_max_iss = max_iss
        for key in list(buckets):
            if key[1] == max_iss:
                carry[key] = buckets.pop(key)

        for key, points in buckets.items():
            yield _build_run(key, points)

    for key, points in carry.items():
        yield _build_run(key, points)


def _build_run(key, points):
    """Turn a buffered group into (lid, issuance_utc, data_points, forecast_type)."""
    lid, issuance = key
    points.sort(key=lambda p: p[0])
    horizon_hours = (points[-1][0] - issuance).total_seconds() / 3600
    data = [
        {"date": st.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": float(val)}
        for st, val in points
    ]
    if issuance.tzinfo is None:
        issuance = issuance.replace(tzinfo=timezone.utc)
    return lid, issuance, data, _infer_forecast_type(horizon_hours)
```

- [ ] **Step 4: Fix the upsert key and remove the silent failure**

Replace the body of `_flush_batch` with:

```python
    def _flush_batch(self, batch, dry_run):
        """
        Upsert a batch of ForecastRun objects. Parquet is source of truth.

        Exceptions propagate. A swallowed failure here previously reported
        "upserted: 0, failed: 0", making a total failure indistinguishable
        from a successful no-op.
        """
        if dry_run:
            return 0, 0

        with transaction.atomic():
            results = ForecastRun.objects.bulk_create(
                batch,
                update_conflicts=True,
                update_fields=["data"],
                unique_fields=[
                    "station", "source", "run_date", "forecast_type", "is_forecast"
                ],
            )
        return len(results), 0
```

- [ ] **Step 5: Rewrite `run()` to consume the iterator**

Replace the body of `run()` between the station-resolution block and the final summary. Resolve stations by making one pass for the LID list using the parquet metadata rather than a DataFrame:

```python
        self._log(f"Scanning LIDs in {parquet_path}…")
        pf = pq.ParquetFile(parquet_path)
        lids = set()
        for rg in range(pf.metadata.num_row_groups):
            lids.update(pf.read_row_groups([rg], columns=["lid"]).column("lid").to_pylist())
        lids = sorted(lids)
        if filter_lids:
            lids = [l for l in lids if l in set(filter_lids)]
        self._log(f"Found {len(lids)} unique LID(s)")

        station_map, skipped_lids = self._resolve_stations(lids, dry_run)
        skipped = set(skipped_lids)
        wanted = set(filter_lids) if filter_lids else None

        totals = {"created": 0, "updated": 0, "failed": 0, "anomalies": 0}
        batch = []
        for idx, (lid, issuance, data, ftype) in enumerate(
            iter_forecast_runs(parquet_path), 1
        ):
            if wanted is not None and lid not in wanted:
                continue
            if lid in skipped:
                totals["failed"] += 1
                continue

            last = datetime.strptime(data[-1]["date"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if last < issuance:
                totals["anomalies"] += 1
                self._warn(
                    f"  Negative horizon for {lid} @ {issuance.isoformat()} "
                    f"(last point {data[-1]['date']}) — importing as-is"
                )
            elif len(data) == 1:
                totals["anomalies"] += 1

            if dry_run:
                totals["created"] += 1
            else:
                batch.append(ForecastRun(
                    station=station_map[lid], source="NOAA_RFC", run_date=issuance,
                    forecast_type=ftype, is_forecast=True, data=data,
                ))
                if len(batch) >= batch_size:
                    c, u = self._flush_batch(batch, dry_run)
                    totals["created"] += c
                    totals["updated"] += u
                    batch = []

            if idx % 100000 == 0:
                self._log(f"  {idx:,} runs processed…")

        if batch and not dry_run:
            c, u = self._flush_batch(batch, dry_run)
            totals["created"] += c
            totals["updated"] += u
```

Add `from datetime import datetime, timezone` to the module imports, replacing the existing `from datetime import timezone`. Update the closing summary to report `anomalies` alongside the other counts.

- [ ] **Step 6: Create new stations as inactive**

In `_create_station_from_metadata` and `_create_station_from_master`, change `"is_active": True` to `"is_active": False` in both `defaults` dicts. Add a comment on each:

```python
            # New archive-only gauges are created inactive so they do not join
            # pull configurations or active-station counts. NWRFC configs must
            # keep skip_inactive_stations off, or they would filter these out.
            "is_active": False,
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_parquet_forecast_importer.py -v`

Expected: 14 passed (9 tests + 5 parametrised cases).

- [ ] **Step 8: Verify the streaming path against the real file**

Run:

```bash
venv/bin/python -c "
import itertools
from src.acquisition.parquet_forecast_importer import iter_forecast_runs
p='/home/geoskimoto/projects/resid-cast/all_nwrfc_forecasts_WY2006_2026.parquet'
for lid, iss, data, ft in itertools.islice(iter_forecast_runs(p), 3):
    print(lid, iss, ft, len(data), data[0], data[-1])
"
```

Expected: three runs printed, the first being `HODO3 2005-10-01 00:13:00+00:00 medium 38 ...`. Memory stays flat — this reads a couple of row groups, not the file.

- [ ] **Step 9: Commit**

```bash
git add src/acquisition/parquet_forecast_importer.py tests/test_parquet_forecast_importer.py
git commit -m "fix: stream parquet import and correct the ON CONFLICT key

_flush_batch passed four unique_fields against the five-column
unique_forecast_run index, so ON CONFLICT raised ProgrammingError — and the
bare except returned (0, 0), printing 'upserted: 0, failed: 0' so a total
failure was indistinguishable from a no-op. Exceptions now propagate and
is_forecast is part of the key.

Replaces the read-everything-then-iterrows ingest with row-group streaming
that buffers groups straddling a row-group boundary, so the 144M-row archive
imports within available memory. New stations are created is_active=False."
```

---

## Task 4: Back up, delete the superseded window, and import

Data operation. Runs in the production tree only after Tasks 1–3 are merged and their tests pass.

**Files:**
- Create: `scripts/swap_nwrfc_archive.py`

**Interfaces:**
- Consumes: the corrected `ParquetForecastImporter` from Task 3.
- Produces: no importable API; a CLI with `--backup`, `--delete`, and `--verify` phases.

- [ ] **Step 1: Write the backup-and-delete script**

Create `scripts/swap_nwrfc_archive.py`:

```python
"""
Back up and delete the NOAA_RFC rows superseded by the NWRFC archive.

Phases are separate commands so the backup is always taken before anything is
destroyed, and so --verify can be re-run afterwards.

  venv/bin/python scripts/swap_nwrfc_archive.py --backup
  venv/bin/python scripts/swap_nwrfc_archive.py --delete
  venv/bin/python scripts/swap_nwrfc_archive.py --verify
"""
import argparse
import gzip
import json
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.streamflow.models import ForecastRun  # noqa: E402

WINDOW_START = "2005-10-01 00:13:00+00"
WINDOW_END = "2026-09-22 16:24:00+00"
# Present in forecast_runs but absent from the archive; the NWPS API serves
# only the current forecast, so these 708 runs cannot be re-fetched.
EXCLUDED_LIDS = ["COQO3", "SKMW1", "WDHN2"]
BACKUP_PATH = "data/backups/nwrfc_superseded_runs.jsonl.gz"


def target_queryset():
    return (
        ForecastRun.objects.filter(
            source="NOAA_RFC",
            run_date__gte=WINDOW_START,
            run_date__lte=WINDOW_END,
        )
        .exclude(station__station_number__in=EXCLUDED_LIDS)
    )


def backup():
    os.makedirs(os.path.dirname(BACKUP_PATH), exist_ok=True)
    qs = target_queryset().select_related("station")
    n = 0
    with gzip.open(BACKUP_PATH, "wt") as fh:
        for r in qs.iterator(chunk_size=2000):
            fh.write(json.dumps({
                "station_number": r.station.station_number,
                "source": r.source,
                "run_date": r.run_date.isoformat(),
                "forecast_type": r.forecast_type,
                "is_forecast": r.is_forecast,
                "rmse": str(r.rmse) if r.rmse is not None else None,
                "data": r.data,
            }) + "\n")
            n += 1
    print(f"backed up {n:,} rows -> {BACKUP_PATH}")
    return n


def delete():
    if not os.path.exists(BACKUP_PATH):
        sys.exit(f"refusing to delete: no backup at {BACKUP_PATH}. Run --backup first.")
    n, _ = target_queryset().delete()
    print(f"deleted {n:,} rows")


def verify():
    from django.db.models import Count
    print("by source:", list(
        ForecastRun.objects.values("source").annotate(n=Count("id")).order_by()
    ))
    print("remaining in window:", target_queryset().count())
    print("preserved pre-window:", ForecastRun.objects.filter(
        source="NOAA_RFC", run_date__lt=WINDOW_START).count())
    print("preserved orphan-station:", ForecastRun.objects.filter(
        source="NOAA_RFC", station__station_number__in=EXCLUDED_LIDS).count())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.backup:
        backup()
    if a.delete:
        delete()
    if a.verify:
        verify()
    if not (a.backup or a.delete or a.verify):
        ap.error("pick at least one of --backup / --delete / --verify")
```

- [ ] **Step 2: Confirm the delete scope before running it**

Run: `PYTHONPATH=$PWD venv/bin/python scripts/swap_nwrfc_archive.py --verify`

Expected, **before** any delete:
- `remaining in window: 88123`
- `preserved pre-window: 411`
- `preserved orphan-station: 708`

**If `remaining in window` is not 88,123, stop.** The window bounds or exclusions are wrong and the delete would remove the wrong rows.

- [ ] **Step 3: Pause Celery Beat**

```bash
sudo systemctl stop celery-beat
systemctl is-active celery-beat
```

Expected: `inactive`. This prevents the enabled NWRFC config (#2, 369 stations) from writing mid-swap.

- [ ] **Step 4: Back up**

Run: `PYTHONPATH=$PWD venv/bin/python scripts/swap_nwrfc_archive.py --backup`

Expected: `backed up 88,123 rows -> data/backups/nwrfc_superseded_runs.jsonl.gz`. Confirm the file is non-empty with `ls -lh data/backups/`.

- [ ] **Step 5: Delete**

Run: `PYTHONPATH=$PWD venv/bin/python scripts/swap_nwrfc_archive.py --delete --verify`

Expected: `deleted 88,123 rows`, then `remaining in window: 0`, `preserved pre-window: 411`, `preserved orphan-station: 708`.

- [ ] **Step 6: Dry-run the import**

Run:

```bash
PYTHONPATH=$PWD venv/bin/python manage.py import_parquet_forecasts \
  /home/geoskimoto/projects/resid-cast/all_nwrfc_forecasts_WY2006_2026.parquet --dry-run
```

Expected: reports 3,596,831 runs across 441 LIDs and writes nothing.

- [ ] **Step 7: Import one station end-to-end**

Run:

```bash
PYTHONPATH=$PWD venv/bin/python manage.py import_parquet_forecasts \
  /home/geoskimoto/projects/resid-cast/all_nwrfc_forecasts_WY2006_2026.parquet \
  --station CHDW1
```

Then confirm a known run round-tripped intact:

```bash
PYTHONPATH=$PWD venv/bin/python -c "
import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup()
from apps.streamflow.models import ForecastRun
r = ForecastRun.objects.get(station__station_number='CHDW1', source='NOAA_RFC',
                            run_date='2010-01-01 18:07:00+00')
print(r.forecast_type, len(r.data), r.data[0], r.data[-1])
"
```

Expected: `medium 39 {'date': '2010-01-02T00:00:00Z', 'value': 2380.0} {'date': '2010-01-11T12:00:00Z', 'value': 2380.0}` — the values measured from the parquet during reconnaissance.

- [ ] **Step 8: Run the full import**

```bash
nohup env PYTHONPATH=$PWD venv/bin/python manage.py import_parquet_forecasts \
  /home/geoskimoto/projects/resid-cast/all_nwrfc_forecasts_WY2006_2026.parquet \
  > data/backups/nwrfc_import.log 2>&1 &
```

Monitor with `tail -f data/backups/nwrfc_import.log` and watch disk with `df -h /home`. Expected growth is ~6–7 GB against 36 GB free. **If free space drops below 10 GB, stop the import** — the backup is on the same volume.

- [ ] **Step 9: Verify the load**

```bash
PYTHONPATH=$PWD venv/bin/python -c "
import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute(\"\"\"
      SELECT count(*) total,
             count(*) FILTER (WHERE run_date < '2005-10-01 00:13:00+00') pre_window,
             count(*) FILTER (WHERE date_part('microseconds', run_date)::int %% 1000000 <> 0) microsec
      FROM forecast_runs WHERE source='NOAA_RFC'\"\"\")
    print('total / pre_window / microsecond-keyed:', c.fetchone())
    c.execute(\"SELECT pg_size_pretty(pg_database_size(current_database()))\")
    print('db size:', c.fetchone())
"
```

Expected: total ≈ 3,596,831 + 411 + 708 = **3,597,950**, `pre_window` = 411, and `microsec` = 708 (only the three preserved orphan stations). Any shortfall in the total must be explained against the importer's reported `failed` and `anomalies` counts, not rounded past.

- [ ] **Step 10: Restart Celery Beat and confirm a clean pull cycle**

```bash
sudo systemctl start celery-beat
systemctl is-active celery-beat
```

Wait for one dispatch cycle (the dispatcher runs every 5 minutes), then confirm new rows key on issuance time, not fetch time:

```bash
PYTHONPATH=$PWD venv/bin/python -c "
import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup()
from apps.streamflow.models import ForecastRun
for r in ForecastRun.objects.filter(source='NOAA_RFC').order_by('-run_date')[:5]:
    print(r.station.station_number, r.run_date, r.forecast_type)
"
```

Expected: minute-precision `run_date`s with zero microseconds, and `forecast_type` reflecting the real horizon rather than a uniform `short`.

- [ ] **Step 11: Commit**

```bash
git add scripts/swap_nwrfc_archive.py
git commit -m "feat: add NWRFC archive swap script for backup, scoped delete, and verify

Backs up the 88,123 NOAA_RFC rows superseded by the WY2006-2026 archive before
deleting them, refusing to delete without a backup present. Excludes COQO3,
SKMW1 and WDHN2 (708 runs), which NWRFC does not carry in the archive and the
NWPS API cannot re-serve, and preserves the 411 rows predating the archive."
```

---

## Rollback

If the import must be undone:

1. `sudo systemctl stop celery-beat`
2. Delete the imported window: the same `target_queryset()` in `scripts/swap_nwrfc_archive.py` selects exactly the imported rows.
3. Restore from `data/backups/nwrfc_superseded_runs.jsonl.gz` — each line carries `station_number`, `run_date`, `forecast_type`, `is_forecast`, `rmse` and `data`, sufficient to reconstruct every deleted row.
4. Revert Tasks 1–3 if the `run_date` change is implicated: `git revert <commit>`.
5. `sudo systemctl start celery-beat`

The 411 pre-window rows and 708 orphan-station rows are never deleted, so they need no restore path.
