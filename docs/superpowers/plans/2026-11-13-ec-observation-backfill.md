# Environment Canada Observation Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the 2,047 Environment Canada stations whose daily-mean records were truncated by the same 5σ filter, by routing the existing backfill and audit tooling through the existing `CanadaClient`.

**Architecture:** The USGS backfill and audit commands already contain the hard-won run machinery — per-gage fault isolation, connection reset, pacing on every path, crash-safe `.done.txt` resume sidecar, `try/finally` report writing, dry-run. Rather than duplicate ~300 lines per agency (which the project's DRY rule forbids and which this codebase has already had to correct once), extract that machinery into a shared runner and make both commands thin agency-specific wrappers. Then add the EC commands.

**Tech Stack:** Python 3.12, Django 6.0.2, PostgreSQL, `CanadaClient` (MSC GeoMet API, `api.weather.gc.ca`), pytest + pytest-django.

## Background: what was measured

The 5σ outlier filter lived in `DataProcessor.validate_observations`, which **every** source passes through — not just USGS. EC was therefore exposed to the same truncation. Sampled 2026-11-13 against the live EC API, stations with >3,000 daily rows:

| Station | DB max (cms) | EC max (cms) | ratio | verdict |
|---|---|---|---|---|
| 08DB001 | 4,530 | 9,460 | 0.48 | truncated |
| 08LC003 | 310 | 552 | 0.56 | truncated |
| 08NE039 | 52.2 | 91.3 | 0.57 | truncated |
| 08MG005 | 880 | 1,370 | 0.64 | truncated |
| 08NE049 | 8,690 | 10,600 | 0.82 | truncated |
| 08LE031 | 1,610 | 1,610 | 1.00 | ok |
| 08LD001 | 391 | 396 | 0.99 | ok |
| 08NM050 | 77.9 | 77.9 | 1.00 | ok |

**5 of 8 truncated.** The three clean ones are consistent with the mechanism: the filter only bites when a batch is long enough for a real peak to exceed |z| > 5, so stations whose history arrived through ordinary incremental pulls were never affected.

Scale: **2,047 EC stations, 11,733,533 daily-mean rows**, which is **11.7M of the 37M `DailyFlowPercentile` rows (32%)**. The percentile recompute is blocked on this; doing it before the EC repair would rebuild a third of the table from truncated data.

## Global Constraints

- **The production tree IS the deployment.** Develop in the worktree `.claude/worktrees/usgs-observation-ingest-fix`, push, `git pull` in `/home/streamflow/streamflow-dataOps/streamflow-dataOps`, restart services.
- Run Python as `venv/bin/python`. `source venv/bin/activate` does not work here.
- **A Stage B USGS backfill is running against production during this work** (pid in `data/stage_b.pid`). Do NOT run any backfill or audit management command, and do not restart Celery services, while implementing. Tests only.
- **Never modify application code to make a failing test pass.** Report and stop.
- **Do NOT use `git stash`** — the stash stack is shared across worktrees.
- `observed_at` for daily means must be timezone-aware **midnight UTC**. All 11,733,533 existing EC rows are at exactly `00:00:00` UTC, and `CanadaClient.get_daily_mean` already emits that. Any deviation turns a corrective upsert into a duplicate insert.
- EC discharge is stored in **`cms`**, not `cfs`. `CanadaClient` already sets `unit="cms"`. Never convert or overwrite the unit.
- `station_number` has **zero collisions across agencies** (verified 2026-11-13), so resolving a station by `station_number` alone is unambiguous.
- The existing USGS command behaviour must not change. Its tests must keep passing unmodified.
- `DischargeObservation.quality_code` is `CharField(max_length=10)`.
- The refactor must preserve every property the USGS command's review rounds established: per-gage fault isolation with `connection.close()`, pacing on **every** path including failures and skips, `.done.txt` sidecar appended and flushed per successful gage, report written in a `try/finally`, `--dry-run` performing no database writes.

---

### Task 1: Extract the shared backfill runner

**Files:**
- Create: `apps/streamflow/management/backfill_runner.py`
- Modify: `apps/streamflow/management/commands/backfill_usgs_observations.py`
- Test: `tests/test_backfill_runner.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `run_backfill(*, command, gages, fetch, agency, options) -> list[dict]` in
  `apps.streamflow.management.backfill_runner`, where `fetch(station_number, start_date, end_date) -> list[dict]`
  is an agency-specific callable. Returns the per-gage report rows. Task 2 reuses it.

**This is a pure refactor: behaviour must not change.** The existing
`tests/test_backfill_usgs_observations.py` must pass **unmodified** afterwards — that
is the regression proof. Do not edit it.

- [ ] **Step 1: Record the behaviour you must preserve**

Read `apps/streamflow/management/commands/backfill_usgs_observations.py` in full and write down, in your report, every behaviour in `handle()`: option parsing, date validation order, station lookup, the per-gage `try` scope, `connection.close()` on failure, the `finally` pacing sleep, the `.done.txt` sidecar gating, the `try/finally` report write, the status vocabulary (`ok`, `no_data`, `not_in_db`, `failed: …`, `dry_run`), and the summary line.

Run the existing tests first and record the count:
`venv/bin/python -m pytest tests/test_backfill_usgs_observations.py -q`

- [ ] **Step 2: Write the failing test for the runner**

Create `tests/test_backfill_runner.py`:

```python
"""Tests for the shared, agency-agnostic backfill runner.

The runner owns everything the USGS command's review rounds established:
per-gage fault isolation with a connection reset, pacing on every path,
a crash-safe .done.txt sidecar, report-on-exception, and a no-write dry run.
Both the USGS and EC commands delegate to it.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.management.base import BaseCommand

from apps.streamflow.management.backfill_runner import run_backfill
from apps.streamflow.models import DischargeObservation, Station


@pytest.fixture
def stations(db):
    a = Station.objects.create(
        station_number="08LE031", name="EC One", agency="EC", is_active=True
    )
    b = Station.objects.create(
        station_number="08LD001", name="EC Two", agency="EC", is_active=True
    )
    return a, b


def _obs(day, value, unit="cms"):
    return {
        "observed_at": datetime(2020, 1, day, tzinfo=timezone.utc),
        "discharge": value,
        "unit": unit,
        "type": "daily_mean",
        "quality_code": "A",
    }


def _opts(**over):
    base = {
        "start": None, "end": None, "dry_run": False,
        "sleep": 0, "report": None, "skip_gages_file": None,
    }
    base.update(over)
    return base


def _run(gages, fetch, agency="EC", **over):
    return run_backfill(
        command=BaseCommand(), gages=gages, fetch=fetch,
        agency=agency, options=_opts(**over),
    )


def test_writes_observations_and_reports_ok(stations):
    rows = _run(["08LE031"], lambda s, a, b: [_obs(1, 173.0), _obs(2, 172.0)])

    assert rows[0]["status"] == "ok"
    assert rows[0]["fetched"] == 2
    assert DischargeObservation.objects.filter(
        station=stations[0], type="daily_mean"
    ).count() == 2


def test_dry_run_writes_nothing(stations):
    rows = _run(["08LE031"], lambda s, a, b: [_obs(1, 173.0)], dry_run=True)

    assert rows[0]["status"] == "dry_run"
    assert DischargeObservation.objects.count() == 0


def test_unknown_station_is_skipped_and_run_continues(stations):
    seen = []

    def fetch(s, a, b):
        seen.append(s)
        return [_obs(1, 173.0)]

    rows = _run(["99999999", "08LE031"], fetch)

    assert rows[0]["status"] == "not_in_db"
    assert rows[1]["status"] == "ok"
    assert seen == ["08LE031"]


def test_fetch_failure_isolated_to_one_gage(stations):
    def fetch(s, a, b):
        if s == "08LE031":
            raise RuntimeError("boom")
        return [_obs(1, 391.0)]

    rows = _run(["08LE031", "08LD001"], fetch)

    assert rows[0]["status"].startswith("failed")
    assert rows[1]["status"] == "ok"
    assert DischargeObservation.objects.filter(station=stations[1]).count() == 1


def test_database_failure_isolated_and_connection_reset(stations):
    from django.db.utils import OperationalError

    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("server closed the connection unexpectedly")
        return 1

    with patch("apps.streamflow.management.backfill_runner.connection.close") as close, \
         patch("src.acquisition.data_processor.DataProcessor.process_observations",
               side_effect=flaky):
        rows = _run(["08LE031", "08LD001"], lambda s, a, b: [_obs(1, 1.0)])

    assert rows[0]["status"].startswith("failed")
    assert rows[1]["status"] == "ok"
    assert close.called, "the connection must be reset so the next gage reconnects"


def test_empty_fetch_is_no_data_not_ok(stations):
    rows = _run(["08LE031"], lambda s, a, b: [])
    assert rows[0]["status"] == "no_data"


def test_sleep_fires_on_every_path_including_failures(stations):
    def fetch(s, a, b):
        if s == "08LE031":
            raise RuntimeError("boom")
        return [_obs(1, 1.0)]

    with patch("apps.streamflow.management.backfill_runner.time.sleep") as sleep:
        _run(["08LE031", "08LD001"], fetch, sleep=1.0)

    assert sleep.called, "pacing must not be skipped on the failure path"


def test_done_sidecar_lists_only_ok_gages(stations, tmp_path):
    report = tmp_path / "r.csv"

    def fetch(s, a, b):
        return [] if s == "08LE031" else [_obs(1, 1.0)]

    _run(["08LE031", "08LD001"], fetch, report=str(report))

    sidecar = tmp_path / "r.csv.done.txt"
    assert sidecar.read_text().split() == ["08LD001"]


def test_report_is_written_even_when_the_loop_raises(stations, tmp_path):
    report = tmp_path / "r.csv"

    with patch("apps.streamflow.management.backfill_runner.time.sleep",
               side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            _run(["08LE031", "08LD001"], lambda s, a, b: [_obs(1, 1.0)],
                 report=str(report), sleep=1.0)

    assert "08LE031" in report.read_text()


def test_skip_file_excludes_listed_gages(stations, tmp_path):
    skip = tmp_path / "done.txt"
    skip.write_text("08LE031\n")
    seen = []

    _run(["08LE031", "08LD001"],
         lambda s, a, b: (seen.append(s), [_obs(1, 1.0)])[1],
         skip_gages_file=str(skip))

    assert seen == ["08LD001"]


def test_agency_scopes_the_station_lookup(stations):
    # An EC station must not be found when the runner is scoped to USGS.
    rows = _run(["08LE031"], lambda s, a, b: [_obs(1, 1.0)], agency="USGS")
    assert rows[0]["status"] == "not_in_db"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_backfill_runner.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'apps.streamflow.management.backfill_runner'`

- [ ] **Step 4: Extract the runner**

Create `apps/streamflow/management/backfill_runner.py` by **moving** the body of
`Command.handle()`'s gage loop out of `backfill_usgs_observations.py`, unchanged in
behaviour, into:

```python
def run_backfill(*, command, gages, fetch, agency, options) -> list[dict]:
```

Rules for the extraction:
- `command` is used only for `command.stdout.write(...)` and `command.style`, so the
  commands keep their existing output.
- `fetch(station_number, start_date, end_date)` replaces the direct
  `client.get_daily_mean(...)` call. Everything else — statuses, sidecar, pacing,
  `connection.close()`, `try/finally` report, dry-run — moves verbatim.
- `agency` scopes the `Station.objects.filter(station_number=..., agency=agency)` lookup.
- `options` is the command's parsed options dict, read with `.get()`.
- Import `time` and `connection` **into this module**, because the tests patch
  `apps.streamflow.management.backfill_runner.time.sleep` and
  `...backfill_runner.connection.close`.
- Keep `_write_report`, `_max_discharge`, and the report field list with the runner.
- Leave `_parse_date` and the `start > end` / `--end` without `--start` validation in the
  command, since they run before the loop.

Then reduce `backfill_usgs_observations.py`'s `handle()` to: parse and validate dates,
resolve gages, build the fetch callable, and delegate:

```python
        client = USGSWaterDataClient()

        def fetch(station_number, start_date, end_date):
            return client.get_daily_mean(station_number, start_date, end_date)

        run_backfill(
            command=self, gages=gages, fetch=fetch,
            agency="USGS", options=options,
        )
```

- [ ] **Step 5: Run both suites**

Run: `venv/bin/python -m pytest tests/test_backfill_runner.py tests/test_backfill_usgs_observations.py tests/test_gage_lists.py -v`
Expected: the runner's 11 tests pass AND every existing USGS backfill test passes **unmodified**. If any USGS test needed editing, the refactor changed behaviour — stop and report rather than editing the test.

- [ ] **Step 6: Commit**

```bash
git add apps/streamflow/management/backfill_runner.py \
        apps/streamflow/management/commands/backfill_usgs_observations.py \
        tests/test_backfill_runner.py
git commit -m "refactor: extract the agency-agnostic backfill runner"
```

---

### Task 2: EC backfill command

**Files:**
- Modify: `apps/streamflow/management/gage_lists.py`
- Create: `apps/streamflow/management/commands/backfill_ec_observations.py`
- Test: `tests/test_backfill_ec_observations.py`
- Test: `tests/test_gage_lists.py` (add cases; do not alter existing ones)

**Interfaces:**
- Consumes: `run_backfill` (Task 1), `CanadaClient.get_daily_mean`.
- Produces: `python manage.py backfill_ec_observations` with `--stations`,
  `--station-list-csv`, `--all-ec`, `--start`, `--end`, `--dry-run`, `--sleep`,
  `--report`, `--skip-gages-file`. Also `resolve_gages` gains agency support.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_gage_lists.py` (append; leave existing tests untouched):

```python
def test_all_stations_respects_agency(db):
    Station.objects.create(station_number="13317000", name="U", agency="USGS")
    Station.objects.create(station_number="08LE031", name="E", agency="EC")

    assert resolve_gages({"all_usgs": True}) == ["13317000"]
    assert resolve_gages({"all_ec": True}) == ["08LE031"]
```

Create `tests/test_backfill_ec_observations.py`:

```python
"""Tests for the Environment Canada observation backfill command.

EC went through the same 5-sigma filter as USGS — it lived in DataProcessor,
which every source uses. Sampled 2026-11-13, 5 of 8 EC stations with long
records held a maximum between 0.48 and 0.82 of the true EC maximum.
"""

from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.streamflow.models import DischargeObservation, Station

PATCH = (
    "apps.streamflow.management.commands.backfill_ec_observations."
    "CanadaClient.get_daily_mean"
)

# Shape verified against the live EC API on 2026-11-13: midnight UTC,
# unit 'cms', plus an extra discharge_cfs key the processor ignores.
EC_ROWS = [
    {
        "observed_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "discharge": 173.0,
        "discharge_cfs": 6109.4431,
        "unit": "cms",
        "type": "daily_mean",
        "quality_code": "A",
    },
    {
        "observed_at": datetime(2020, 1, 2, tzinfo=timezone.utc),
        "discharge": 172.0,
        "discharge_cfs": 6074.1284,
        "unit": "cms",
        "type": "daily_mean",
        "quality_code": "A",
    },
]


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="08LE031", name="Test EC", agency="EC", is_active=True
    )


def test_writes_ec_rows_in_cms(station):
    with patch(PATCH, return_value=EC_ROWS):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--sleep", "0", stdout=StringIO())

    rows = DischargeObservation.objects.filter(station=station, type="daily_mean")
    assert rows.count() == 2
    assert {r.unit for r in rows} == {"cms"}, "EC must stay in cms, never converted"
    assert rows.get(observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc)).discharge \
        == Decimal("173.0000")


def test_observed_at_stays_midnight_utc(station):
    # All 11,733,533 existing EC rows are at 00:00:00 UTC; any other
    # time-of-day would duplicate rather than update.
    with patch(PATCH, return_value=EC_ROWS):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--sleep", "0", stdout=StringIO())

    for r in DischargeObservation.objects.filter(station=station):
        assert r.observed_at.utctimetuple()[3:6] == (0, 0, 0)


def test_truncated_peak_is_restored(station):
    DischargeObservation.objects.create(
        station=station, observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        discharge=Decimal("100.0000"), unit="cms", type="daily_mean",
        quality_code="A",
    )
    with patch(PATCH, return_value=EC_ROWS):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--sleep", "0", stdout=StringIO())

    rows = DischargeObservation.objects.filter(station=station)
    assert rows.count() == 2, "existing row must update in place, not duplicate"
    assert rows.get(observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc)).discharge \
        == Decimal("173.0000")


def test_dry_run_writes_nothing(station):
    with patch(PATCH, return_value=EC_ROWS):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--sleep", "0", "--dry-run", stdout=StringIO())

    assert DischargeObservation.objects.count() == 0


def test_a_usgs_station_is_not_processed(db):
    Station.objects.create(station_number="12200500", name="U", agency="USGS")
    out = StringIO()
    with patch(PATCH, return_value=EC_ROWS) as fetch:
        call_command("backfill_ec_observations", "--stations", "12200500",
                     "--sleep", "0", stdout=out)

    assert not fetch.called, "the EC command must not touch USGS stations"
    assert "12200500" in out.getvalue()


def test_requires_a_station_selection(db):
    with pytest.raises(CommandError):
        call_command("backfill_ec_observations", stdout=StringIO())


def test_end_without_start_is_rejected(station):
    with pytest.raises(CommandError):
        call_command("backfill_ec_observations", "--stations", "08LE031",
                     "--end", "2020-01-05", stdout=StringIO())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_backfill_ec_observations.py tests/test_gage_lists.py -v`
Expected: the EC module fails to load the command (`Unknown command` / import error) and `test_all_stations_respects_agency` fails on the unsupported `all_ec` key.

- [ ] **Step 3: Generalise `resolve_gages`**

In `apps/streamflow/management/gage_lists.py`, keep `all_usgs` working exactly as now and add an `all_ec` option, both delegating to one agency-scoped query. Keep the `CommandError` message naming whichever selectors the caller supports. Do not change `load_skip_file`.

- [ ] **Step 4: Write the EC command**

Create `apps/streamflow/management/commands/backfill_ec_observations.py`, mirroring
the USGS command but with `CanadaClient` and `agency="EC"`:

```python
"""Re-fetch and upsert Environment Canada daily-mean discharge.

EC passed through the same DataProcessor 5-sigma filter as USGS, so its records
are truncated the same way: sampled 2026-11-13, 5 of 8 EC stations with long
records held a maximum between 0.48 and 0.82 of the true EC maximum.

EC discharge is stored in cms and must never be converted. Unlike the USGS API,
the MSC GeoMet endpoint needs no key and has no hourly request budget, but keep
the default pacing so it is not hammered.

    nohup venv/bin/python manage.py backfill_ec_observations --all-ec \\
        --report data/backfill_stage_c.csv \\
        > data/backfill_stage_c.log 2>&1 &
"""
```

Its `handle()` must: parse and validate `--start`/`--end` with the same rules as the
USGS command (including rejecting `--end` without `--start`), resolve stations, build
a `fetch` callable wrapping `CanadaClient().get_daily_mean`, and delegate to
`run_backfill(..., agency="EC", ...)`.

`CanadaClient.get_daily_mean(station_number, start_date, end_date=None)` requires a
non-`None` `start_date`. When `--start` is not given, pass
`datetime(1850, 1, 1, tzinfo=timezone.utc)` so the whole record is fetched, and say so
in the `--start` help text.

- [ ] **Step 5: Run the tests**

Run: `venv/bin/python -m pytest tests/test_backfill_ec_observations.py tests/test_gage_lists.py tests/test_backfill_runner.py tests/test_backfill_usgs_observations.py -v`
Expected: all pass, with the USGS tests still unmodified.

- [ ] **Step 6: Commit**

```bash
git add apps/streamflow/management/gage_lists.py \
        apps/streamflow/management/commands/backfill_ec_observations.py \
        tests/test_backfill_ec_observations.py tests/test_gage_lists.py
git commit -m "feat: add Environment Canada observation backfill command"
```

---

### Task 3: Make the audit agency-aware

**Files:**
- Modify: `apps/streamflow/management/commands/audit_usgs_observations.py`
- Create: `apps/streamflow/management/commands/audit_ec_observations.py`
- Test: `tests/test_audit_ec_observations.py`

**Interfaces:**
- Consumes: `CanadaClient.get_daily_mean`, `resolve_gages`.
- Produces: `python manage.py audit_ec_observations` with `--stations`,
  `--station-list-csv`, `--all-ec`, `--report`, `--sleep`, reporting the same
  `n_missing_in_db_span` / `n_missing_after_db_last` / `n_value_diff` figures.

Without this there is no way to verify the EC repair the way Stage A and B were
verified. If the comparison logic in the USGS audit can be shared the same way the
backfill runner was, share it; if the split would be more tangled than the duplication,
say so in your report and duplicate only the comparison core — but do not leave two
divergent copies of the status vocabulary and report writing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audit_ec_observations.py` mirroring
`tests/test_audit_usgs_observations.py`, with EC stations, `unit="cms"`, and the
`CanadaClient` patch target. It must cover at minimum: a clean station reports
`missing=0 diff=0` and does not raise; a station missing an in-span day reports it in
`n_missing_in_db_span` and raises `CommandError`; a value difference beyond the
`max(0.5, 0.5%)` tolerance is counted; a `cfs` row on an EC station is excluded from
the comparison by the unit filter.

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_audit_ec_observations.py -v`
Expected: `Unknown command: 'audit_ec_observations'`.

- [ ] **Step 3: Implement**

Build the EC audit so it reuses the USGS audit's comparison and reporting rather than
re-deriving them. Preserve every property the USGS audit's review established: the
tolerance is `max(0.5, 0.5% of the source value)` applied against the **source** value;
the comparison is bounded below by the station's first stored date and **not** bounded
above; `n_missing` is exactly `n_missing_in_db_span + n_missing_after_db_last`; the five
statuses `ok`/`failed`/`no_db_data`/`no_api_data`/`not_in_db` each get a distinct
per-station stdout line; `n_db_rows` is reported alongside `n_db` so duplicate rows per
date are visible; success styling requires rows, all-`ok`, and zero discrepancies; and a
not-all-clear run raises `CommandError` **after** the report is written in the `finally`.

The unit filter must be `cms` for EC, not `cfs`.

- [ ] **Step 4: Run the tests**

Run: `venv/bin/python -m pytest tests/test_audit_ec_observations.py tests/test_audit_usgs_observations.py -v`
Expected: all pass, USGS audit tests unmodified.

- [ ] **Step 5: Commit**

```bash
git add apps/streamflow/management/commands/audit_ec_observations.py \
        apps/streamflow/management/commands/audit_usgs_observations.py \
        tests/test_audit_ec_observations.py
git commit -m "feat: add Environment Canada observation audit command"
```

---

## Self-Review

**Coverage.** The EC truncation finding is addressed by Task 2 (repair) and Task 3
(verification). Task 1 exists so neither duplicates the USGS run machinery, which the
project's DRY rule forbids and which this codebase already had to correct once in the
gage-list helper.

**Deliberately out of scope**, to be surfaced to the user:
- Running the EC backfill itself — that happens after Stage B finishes, with the user's
  go-ahead, and is not part of this plan's tasks.
- The `DailyFlowPercentile` recompute, which waits until USGS Stage B and the EC repair
  are both verified so it is paid for once.
- Migrating `realtime_15min` off the legacy NWIS endpoint.
- NOAA_RFC stations: they hold forecasts, not daily-mean observations, so the 5σ filter
  did not truncate an observation record for them.

**Risk notes.**
- The highest risk is the Task 1 refactor silently changing USGS behaviour. The
  mitigation is that `tests/test_backfill_usgs_observations.py` must pass **unmodified**;
  any need to edit it is a signal to stop, not to edit.
- Second is the midnight-UTC invariant. `CanadaClient` already satisfies it and
  `test_observed_at_stays_midnight_utc` pins it.
- Third is unit handling: EC is `cms`. A conversion to `cfs` anywhere would corrupt
  11.7M rows. `test_writes_ec_rows_in_cms` pins it.
