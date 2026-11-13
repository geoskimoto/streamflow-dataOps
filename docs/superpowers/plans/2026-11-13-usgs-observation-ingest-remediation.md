# USGS Observation Ingest Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the USGS daily-mean ingest from discarding flood peaks and from freezing provisional values, migrate daily-mean acquisition to the USGS Water Data OGC API, then backfill the 285 NWRFC-mapped gages so the missing peaks are actually restored.

**Architecture:** Four independent code fixes land first, each with its own tests: (1) the batch z-score filter in `DataProcessor.validate_observations` stops dropping records and only logs; (2) `process_observations` switches from `bulk_create(ignore_conflicts=True)` to a true upsert on the existing `unique_observation_idx` constraint; (3) `SmartAppendLogic` rewinds each incremental pull by a rolling window so late-published values are re-fetched; (4) a new `USGSWaterDataClient` replaces the retiring legacy NWIS WaterServices path for daily means. Only then do two new management commands run the staged backfill and verify it against the API.

**Tech Stack:** Python 3.12, Django 6.0.2, PostgreSQL/PostGIS, Celery, `requests` 2.31.0, `tenacity` 8.2.3, pytest + pytest-django.

## Background: what was measured

Audit report and data are in `streamflow-dataops-observation-issues/` at the repo root (`README.md`, `gage_gaps.csv`, `missing_days.csv`, `value_diffs.csv`). All four findings were reproduced against the live database on 2026-11-13:

- **46,701 missing gage-days** across 274 of 285 audited gages; 32,275 (69%) carry |z| > 5 against their gage's full record.
- At Skagit nr Mt Vernon (12200500) the entire November 2021 flood crest is absent: the DB holds 2021-11-12 (44,600 cfs) and 2021-11-14 (62,200), then jumps to 2021-11-20 (53,700). Missing: 11-13 (65,200), 11-15 (94,100), 11-16 (119,000), 11-17 (96,200), 11-18 (77,900), 11-19 (65,500). DB max 73,000 cfs vs true record max 142,000 cfs.
- **The two largest missing days (11-15, 11-16) are qualified `A,e`** — late-published *estimated* values. They are an issue-3 miss, not an issue-1 miss. **Removing the z-score filter alone does not recover them; the rolling window and the backfill do.**
- **49,523 gage-days hold stale values** differing from USGS, median 3.7%.
- Config 9 "USGS Daily Mean Pull" success/partial/failed by month: Jun 115/0/5, Jul 53/0/71, Aug 7/9/101, Sep 1/58/1, Oct 11/51/0, Nov 1-12 6/17/2. Errors are `Expecting value: line 1 column 1 (char 0)` and gzip decode failures from legacy WaterServices.

## Global Constraints

- **This working tree IS production.** `gunicorn.service`, `celery-worker.service`, `celery-beat.service` and `flower.service` all run from `/home/streamflow/streamflow-dataOps/streamflow-dataOps` using its `venv/`. Uncommitted edits to management commands and Celery tasks go live immediately. **Do all development in a separate git worktree**, push, then `git pull` here and `sudo systemctl restart gunicorn celery-worker celery-beat`.
- Run Python as `venv/bin/python` — `source venv/bin/activate && python` does not work in this environment.
- **Never modify application code to make a failing test pass.** If a test fails, report which test and why, then stop and ask.
- The test suite has ~311 pre-existing failures on clean `main`. Prove no regressions by **diffing failure sets**, not by expecting green.
- `tests/test_data_processor.py` and `tests/test_smart_append.py` currently fail to import (`ModuleNotFoundError: No module named 'sqlalchemy'`). They are dead legacy modules. **Do not resurrect them and do not install sqlalchemy.** Write new Django-based test modules instead.
- `observed_at` for daily means **must** be timezone-aware midnight UTC. All 25,311,950 existing USGS `daily_mean` rows are at exactly `00:00:00` UTC. Any other time-of-day creates duplicate rows instead of updating existing ones.
- `DischargeObservation.quality_code` is `CharField(max_length=10)`. Generated codes must be truncated to 10 characters.
- The unique constraint is `unique_observation_idx UNIQUE (station_id, observed_at, type)`. Any `bulk_create(update_conflicts=True)` must pass exactly `unique_fields=["station", "observed_at", "type"]`.
- USGS daily mean discharge is `parameter_code="00060"` **and** `statistic_id="00003"`. Always send both; this is what replaces the legacy `discharge_cols[0]` guess.
- Per project convention: **log data quality issues rather than silently dropping records.**
- Units for USGS are `"cfs"`. Do not change the `unit` value.
- Document units in names/comments; never reintroduce a batch z-score drop on streamflow.

---

### Task 1: Configuration for the Water Data API and the rolling window

**Files:**
- Modify: `config/settings.py`
- Modify: `.env` (add the three new keys, unquoted values, no secrets required)
- Test: `tests/test_usgs_waterdata_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `settings.USGS_WATERDATA_BASE` (str), `settings.USGS_API_KEY` (str, may be `""`), `settings.OBSERVATION_REFETCH_WINDOW_DAYS` (int). Tasks 2, 4 and 5 read these.

- [ ] **Step 1: Write the failing test**

Create `tests/test_usgs_waterdata_settings.py`:

```python
"""Pins the settings the USGS Water Data client and rolling re-fetch depend on."""

from django.conf import settings


def test_waterdata_base_default():
    assert settings.USGS_WATERDATA_BASE == (
        "https://api.waterdata.usgs.gov/ogcapi/v1"
    )


def test_api_key_is_a_string_never_none():
    # An absent key is legal — the API answers unauthenticated requests but
    # returns HTTP 429 under load — so the contract is only "always a str",
    # letting the client do `if self.api_key:`. This deliberately does NOT
    # assert a key is present, so the suite still passes without .env.
    assert isinstance(settings.USGS_API_KEY, str)


def test_refetch_window_is_180_days():
    assert settings.OBSERVATION_REFETCH_WINDOW_DAYS == 180
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_usgs_waterdata_settings.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'USGS_WATERDATA_BASE'`

- [ ] **Step 3: Add the settings**

In `config/settings.py`, next to the other acquisition env reads, add:

```python
# --- USGS Water Data OGC API ---------------------------------------------
# Replaces the retiring legacy NWIS WaterServices endpoint for daily means.
# An api.data.gov key is optional; without one the API returns HTTP 429 under
# load (honouring Retry-After). Set USGS_API_KEY to raise the rate limit.
USGS_WATERDATA_BASE = os.environ.get(
    "USGS_WATERDATA_BASE", "https://api.waterdata.usgs.gov/ogcapi/v1"
)
USGS_API_KEY = os.environ.get("USGS_API_KEY", "")

# Each incremental observation pull rewinds this many days before the station's
# last successful pull date and re-fetches, so that values USGS publishes or
# revises after the fact are picked up. USGS revises provisional daily values
# for months; 180 days covers that window.
OBSERVATION_REFETCH_WINDOW_DAYS = int(
    os.environ.get("OBSERVATION_REFETCH_WINDOW_DAYS", "180")
)
```

- [x] **Step 4: Add the keys to `.env` — ALREADY DONE on 2026-11-13**

`.env` already contains all three keys, including a **real, verified 40-character
api.data.gov key** (the same key resid-cast uses; confirmed authenticating with
`X-Ratelimit-Limit: 1000`). Do not overwrite it and do not print it.

```
USGS_WATERDATA_BASE=https://api.waterdata.usgs.gov/ogcapi/v1
USGS_API_KEY=<set, 40 chars — already present, leave alone>
OBSERVATION_REFETCH_WINDOW_DAYS=180
```

Verify rather than re-add:

```bash
grep -c '^USGS_API_KEY=' .env        # expect 1
git check-ignore -v .env .env.bak-20261113   # both must be ignored
```

A pre-change backup is at `.env.bak-20261113` (mode 0600). `.gitignore` was
widened to `.env.*` so no backup can carry the key into git.

- [ ] **Step 5: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_usgs_waterdata_settings.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add config/settings.py tests/test_usgs_waterdata_settings.py
git commit -m "feat: add USGS Water Data API and rolling re-fetch window settings"
```

Note: `.env` is almost certainly gitignored — do not force-add it. Record the three new keys in the CLAUDE.md env var list in Task 9.

---

### Task 2: Stop dropping high-z discharge values

**Files:**
- Modify: `src/acquisition/data_processor.py` (the second-pass outlier block, currently lines ~168–190)
- Test: `tests/test_data_processor_validation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DataProcessor.validate_observations(observations: List[Dict]) -> List[Dict]` now returns every observation that passes basic validation. Module constant `OUTLIER_LOG_Z_SCORE = 5.0`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_processor_validation.py`:

```python
"""Validation must keep real flood peaks.

Streamflow is heavy-tailed: the largest days of any long record sit far beyond
mean + 5 sigma and are real, approved USGS values. A batch z-score filter
removed them at 271 of 285 audited gages, including the whole November 2021
Skagit crest. These tests pin that high-z values survive while genuinely
invalid records are still rejected.

**Fixture sizing matters, and it is subtle.** With a batch of n values where
one is an outlier and the rest are equal, the largest attainable |z| using the
population standard deviation is exactly sqrt(n - 1). So a 26-value batch caps
at |z| = 5.0, which a strict `> 5` test never trips — a 26-value fixture
CANNOT distinguish the fixed code from the broken code. The fixtures below use
a 300-day baseflow record so the crest days reach |z| of 5.0 to 9.6, which is
what the real 31,453-day Skagit record looks like: its true mean + 5 sigma is
63,441 cfs, and this fixture's is ~65,410 cfs.
"""

from datetime import datetime, timedelta, timezone

from src.acquisition.data_processor import DataProcessor

START = datetime(2021, 1, 1, tzinfo=timezone.utc)

# The real USGS daily means for 12200500 that are missing from production.
SKAGIT_CREST = [65200.0, 94100.0, 119000.0, 96200.0, 77900.0, 65500.0]

# 300 days of plausible baseflow, 3,000-8,850 cfs.
BASEFLOW = [3000.0 + (i % 40) * 150 for i in range(300)]


def _obs(value, day_offset):
    return {
        "observed_at": START + timedelta(days=day_offset),
        "discharge": value,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A",
    }


def _batch(values):
    return [_obs(v, i) for i, v in enumerate(values)]


def _z_scores(values):
    mean = sum(values) / len(values)
    std_dev = (sum((x - mean) ** 2 for x in values) / len(values)) ** 0.5
    return [abs((v - mean) / std_dev) for v in values]


def test_fixture_is_actually_discriminating():
    # Guard the guard: if someone shrinks these fixtures, the peak tests below
    # would silently pass against the broken code too. This asserts the crest
    # really does exceed the old |z| > 5 cutoff.
    values = BASEFLOW + SKAGIT_CREST
    crest_z = _z_scores(values)[len(BASEFLOW):]

    assert max(crest_z) > 5.0
    assert sum(1 for z in crest_z if z > 5.0) >= 4, (
        f"expected several crest days above the old cutoff, got {crest_z}"
    )


def test_extreme_flood_peak_is_retained():
    # One 119,000 cfs crest against a long baseflow record: z is far above 5.
    values = BASEFLOW + [119000.0]

    valid = DataProcessor().validate_observations(_batch(values))

    assert len(valid) == len(values)
    assert 119000.0 in [float(o["discharge"]) for o in valid]


def test_skagit_november_2021_crest_survives_validation():
    # The exact days the 5-sigma filter removed from 12200500. The old code
    # dropped five of these six.
    values = BASEFLOW + SKAGIT_CREST

    valid = DataProcessor().validate_observations(_batch(values))

    kept = [float(o["discharge"]) for o in valid]
    assert len(valid) == len(values)
    for value in SKAGIT_CREST:
        assert value in kept, f"{value} cfs was dropped"


def test_high_z_value_is_logged_not_dropped(caplog):
    values = BASEFLOW + SKAGIT_CREST

    with caplog.at_level("INFO"):
        valid = DataProcessor().validate_observations(_batch(values))

    assert len(valid) == len(values)
    assert any("High-z discharge retained" in r.message for r in caplog.records)


def test_negative_discharge_still_rejected():
    valid = DataProcessor().validate_observations([_obs(-5.0, 0)])
    assert valid == []


def test_absurdly_high_discharge_still_rejected():
    valid = DataProcessor().validate_observations([_obs(2_000_000.0, 0)])
    assert valid == []


def test_none_discharge_still_rejected():
    valid = DataProcessor().validate_observations([_obs(None, 0)])
    assert valid == []


def test_missing_required_field_still_rejected():
    valid = DataProcessor().validate_observations([{"discharge": 100.0}])
    assert valid == []


def test_mixed_batch_keeps_peaks_and_rejects_invalid():
    # A realistic pull: valid baseflow, a real crest, and two bad records.
    observations = _batch(BASEFLOW + SKAGIT_CREST)
    observations.append(_obs(-1.0, 999))
    observations.append(_obs(5_000_000.0, 1000))

    valid = DataProcessor().validate_observations(observations)

    kept = [float(o["discharge"]) for o in valid]
    assert len(valid) == len(BASEFLOW) + len(SKAGIT_CREST)
    assert 119000.0 in kept
    assert -1.0 not in kept
    assert 5_000_000.0 not in kept
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_data_processor_validation.py -v`
Expected: 4 FAIL and 5 PASS (9 tests total). Failing: `test_extreme_flood_peak_is_retained`, `test_skagit_november_2021_crest_survives_validation`, `test_high_z_value_is_logged_not_dropped`, and `test_mixed_batch_keeps_peaks_and_rejects_invalid` — all because peaks are dropped and the counts come back short. Passing already: `test_fixture_is_actually_discriminating` (pure arithmetic on the fixture) and the four rejection tests.

If `test_fixture_is_actually_discriminating` fails, stop — the fixture has been altered and the peak tests would then pass against the broken code too, proving nothing.

- [ ] **Step 3: Replace the drop with a log**

In `src/acquisition/data_processor.py`, add near the top after the imports:

```python
# Discharge values beyond this many standard deviations of the batch mean are
# logged for review but never dropped. Streamflow is heavy-tailed, so real
# flood peaks exceed any fixed z-score. A previous version dropped them, which
# removed flood peaks at 271 of 285 audited gages — see
# docs/superpowers/plans/2026-11-13-usgs-observation-ingest-remediation.md
OUTLIER_LOG_Z_SCORE = 5.0
```

Then replace the whole second-pass block — everything from `# Second pass: statistical outlier detection` down to and including the `else: valid_observations = basic_valid` that closes the `if len(basic_valid) > 3:` — with:

```python
        # Second pass: flag statistical outliers for review. Never drop them.
        valid_observations = basic_valid

        if len(valid_observations) > 3:
            discharges = [float(obs["discharge"]) for obs in valid_observations]
            mean = sum(discharges) / len(discharges)
            variance = sum((x - mean) ** 2 for x in discharges) / len(discharges)
            std_dev = variance ** 0.5

            if std_dev > 0:
                for obs in valid_observations:
                    z_score = abs((float(obs["discharge"]) - mean) / std_dev)
                    if z_score > OUTLIER_LOG_Z_SCORE:
                        self.logger.info(
                            "High-z discharge retained: discharge=%s z_score=%.2f "
                            "observed_at=%s",
                            obs["discharge"],
                            z_score,
                            obs["observed_at"],
                        )
```

Leave the trailing `removed_count` logging and `return valid_observations` exactly as they are.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_data_processor_validation.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/acquisition/data_processor.py tests/test_data_processor_validation.py
git commit -m "fix: stop discarding flood peaks in observation validation, log high-z values instead"
```

---

### Task 3: Upsert observations instead of ignoring conflicts

**Files:**
- Modify: `src/acquisition/data_processor.py` (the `bulk_create` call, currently lines ~100–106)
- Test: `tests/test_data_processor_upsert.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DataProcessor.process_observations` now updates `discharge` and `quality_code` on conflict. Return value remains an `int` count of rows written (inserted + updated).

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_processor_upsert.py`:

```python
"""Re-pulling a day must overwrite its value, not silently keep the old one.

USGS publishes provisional daily values and revises them for months. With
ignore_conflicts the first provisional value was kept forever, leaving 49,523
gage-days stale against USGS.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from apps.streamflow.models import DischargeObservation, Station
from src.acquisition.data_processor import DataProcessor


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500",
        name="SKAGIT RIVER NEAR MOUNT VERNON, WA",
        agency="USGS",
        is_active=True,
    )


def _obs(value, quality_code):
    return {
        "observed_at": datetime(2021, 11, 16, tzinfo=timezone.utc),
        "discharge": value,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": quality_code,
    }


def test_revised_value_replaces_provisional(station):
    processor = DataProcessor()

    processor.process_observations(
        station_number=station.station_number, observations=[_obs(95000.0, "P")]
    )
    processor.process_observations(
        station_number=station.station_number, observations=[_obs(119000.0, "A, e")]
    )

    rows = DischargeObservation.objects.filter(
        station=station, type="daily_mean"
    )
    assert rows.count() == 1, "upsert must not create a duplicate row"
    row = rows.get()
    assert row.discharge == Decimal("119000.0000")
    assert row.quality_code == "A, e"


def test_repulling_identical_data_does_not_duplicate(station):
    processor = DataProcessor()
    for _ in range(3):
        processor.process_observations(
            station_number=station.station_number, observations=[_obs(119000.0, "A")]
        )

    assert DischargeObservation.objects.filter(station=station).count() == 1


def test_distinct_days_both_stored(station):
    processor = DataProcessor()
    observations = [
        {
            "observed_at": datetime(2021, 11, day, tzinfo=timezone.utc),
            "discharge": value,
            "unit": "cfs",
            "type": "daily_mean",
            "quality_code": "A",
        }
        for day, value in ((15, 94100.0), (16, 119000.0))
    ]

    processor.process_observations(
        station_number=station.station_number, observations=observations
    )

    assert DischargeObservation.objects.filter(station=station).count() == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_data_processor_upsert.py -v`
Expected: `test_revised_value_replaces_provisional` FAILS — `row.discharge` is still `95000.0000` because the conflict was ignored. The other two pass.

- [ ] **Step 3: Switch to an upsert**

In `src/acquisition/data_processor.py`, replace:

```python
        # Use bulk_create with ignore_conflicts to handle duplicates
        with transaction.atomic():
            created = DischargeObservation.objects.bulk_create(
                observation_objects,
                ignore_conflicts=True
            )
            inserted_count = len(created)
```

with:

```python
        # Upsert on unique_observation_idx (station, observed_at, type). USGS
        # revises provisional daily values for months, so a re-pulled day must
        # overwrite the stored value rather than be ignored.
        with transaction.atomic():
            written = DischargeObservation.objects.bulk_create(
                observation_objects,
                batch_size=5000,
                update_conflicts=True,
                update_fields=["discharge", "quality_code"],
                unique_fields=["station", "observed_at", "type"],
            )
            inserted_count = len(written)
```

Then change the log line immediately below it from `f"Inserted {inserted_count} of ..."` to:

```python
        self.logger.info(
            f"Wrote {inserted_count} of {len(observations)} observations "
            f"for station {station_number}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_data_processor_upsert.py -v`
Expected: 3 passed

- [ ] **Step 5: Confirm the write path still works end to end**

Run: `venv/bin/python -m pytest tests/test_data_processor_validation.py tests/test_data_processor_upsert.py tests/test_usgs_data_pull.py -v`
Expected: no new failures versus the baseline recorded in Task 0 of your session notes. If `tests/test_usgs_data_pull.py` was already failing, it may still fail — compare, don't assume.

- [ ] **Step 6: Commit**

```bash
git add src/acquisition/data_processor.py tests/test_data_processor_upsert.py
git commit -m "fix: upsert discharge observations so revised USGS values replace provisional ones"
```

---

### Task 4: Rolling re-fetch window in smart append

**Files:**
- Modify: `src/acquisition/smart_append.py` (`get_pull_start_date`)
- Test: `tests/test_smart_append_rolling_window.py`

**Interfaces:**
- Consumes: `settings.OBSERVATION_REFETCH_WINDOW_DAYS` from Task 1.
- Produces: `SmartAppendLogic.get_pull_start_date(config_id, station_number, config_start_date)` unchanged in signature, but a subsequent pull now returns `last_successful_pull_date - OBSERVATION_REFETCH_WINDOW_DAYS` days, never earlier than `config_start_date`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_smart_append_rolling_window.py`:

```python
"""Incremental pulls must rewind, so late-published values are picked up.

USGS fills in ice-affected and equipment-affected days afterwards as estimated
values ("A, e"). Starting every pull at last_successful_pull_date meant those
days were never fetched: the two largest missing days at 12200500 (2021-11-15
= 94,100 cfs and 2021-11-16 = 119,000 cfs) are both "A,e".
"""

from datetime import datetime, timedelta, timezone

import pytest
from django.conf import settings

from apps.streamflow.models import (
    PullConfiguration,
    PullStationProgress,
    Station,
)
from src.acquisition.smart_append import SmartAppendLogic


CONFIG_START = datetime(1900, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def config(db):
    # Field names and values verified against the model and real config 9
    # ("USGS Daily Mean Pull") on 2026-11-13. The source field is
    # `data_source`, NOT `agency` — `agency` lives on Station, not on
    # PullConfiguration. `data_strategy` and `schedule_type` are required.
    return PullConfiguration.objects.create(
        name="Test USGS Daily Mean Pull",
        data_source="USGS",
        data_type="daily_mean",
        data_strategy="append",
        schedule_type="custom",
        schedule_value="0 */12 * * *",
        pull_start_date=CONFIG_START,
    )


def test_first_pull_uses_config_start_date(config):
    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=CONFIG_START,
    )
    assert start == CONFIG_START


def test_subsequent_pull_rewinds_by_the_window(config):
    last = datetime(2026, 11, 10, tzinfo=timezone.utc)
    PullStationProgress.objects.create(
        configuration=config,
        station_number="12200500",
        last_successful_pull_date=last,
    )

    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=CONFIG_START,
    )

    expected = last - timedelta(days=settings.OBSERVATION_REFETCH_WINDOW_DAYS)
    assert start == expected


def test_rewind_never_predates_config_start_date(config):
    # A config that only wants 2026 onward must not be rewound into 2025.
    config_start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    PullStationProgress.objects.create(
        configuration=config,
        station_number="12200500",
        last_successful_pull_date=datetime(2026, 11, 10, tzinfo=timezone.utc),
    )

    start = SmartAppendLogic().get_pull_start_date(
        config_id=config.id,
        station_number="12200500",
        config_start_date=config_start,
    )

    assert start == config_start
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_smart_append_rolling_window.py -v`
Expected: `test_subsequent_pull_rewinds_by_the_window` FAILS — the returned start equals `last` with no rewind.

The fixture's fields were verified against the live model on 2026-11-13, so it should construct cleanly. If it still raises for a missing required field, inspect the model with
`venv/bin/python -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');django.setup();from apps.streamflow.models import PullConfiguration;print([f.name for f in PullConfiguration._meta.get_fields()])"`
and add only the fields the model actually requires. **Do not change the model.**

- [ ] **Step 3: Implement the rewind**

In `src/acquisition/smart_append.py`, add to the imports:

```python
from datetime import datetime, timedelta
from django.conf import settings
```

(The module already imports `datetime`; extend that import rather than duplicating it.)

Then in `get_pull_start_date`, replace the `else:` branch body — the three lines that log and `return last_date` — with:

```python
            else:
                # Rewind before re-fetching: USGS publishes late and revises
                # provisional values for months. Starting at the watermark meant
                # those days were never fetched again. Combined with the upsert
                # in DataProcessor, this re-reads and corrects the window.
                last_date = progress.last_successful_pull_date
                window = timedelta(
                    days=settings.OBSERVATION_REFETCH_WINDOW_DAYS
                )
                rewound = last_date - window
                if rewound < config_start_date:
                    rewound = config_start_date
                self.logger.info(
                    f"Subsequent pull for station {station_number} in config "
                    f"{config_id} - last pull {last_date}, re-fetching from "
                    f"{rewound} ({window.days}d window)"
                )
                return rewound
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_smart_append_rolling_window.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/acquisition/smart_append.py tests/test_smart_append_rolling_window.py
git commit -m "fix: rewind incremental observation pulls by a rolling window to catch late USGS values"
```

---

### Task 5: USGS Water Data OGC API client for daily means

**Files:**
- Create: `src/acquisition/usgs_waterdata_client.py`
- Test: `tests/test_usgs_waterdata_client.py`

**Interfaces:**
- Consumes: `settings.USGS_WATERDATA_BASE`, `settings.USGS_API_KEY` from Task 1.
- Produces:
  - `USGSWaterDataClient()` with `get_daily_mean(station_number: str, start_date: datetime | None, end_date: datetime | None = None) -> List[Dict]`. Each dict has keys `observed_at` (tz-aware midnight UTC `datetime`), `discharge` (`float`), `unit` (`"cfs"`), `type` (`"daily_mean"`), `quality_code` (`str`, ≤10 chars).
  - `USGSWaterDataError` (non-retryable), `USGSWaterDataTransientError` (retryable).
  - Module constants `DISCHARGE_PARAMETER_CODE = "00060"`, `DAILY_MEAN_STATISTIC_ID = "00003"`, `PAGE_LIMIT = 50000`, `APPROVAL_CODES`, `QUALIFIER_CODES`.
  - `build_quality_code(approval_status: str | None, qualifier: list | None) -> str`.

Measured API facts this task relies on (verified 2026-11-13):
- `GET {base}/collections/daily/items` with `monitoring_location_id=USGS-{id}&parameter_code=00060&statistic_id=00003&limit=50000` returned 12200500's full 31,453-day record in ~2.2 s.
- A `links` entry with `rel == "next"` is present only when the page was truncated.
- Feature `properties`: `time_series_id`, `monitoring_location_id`, `parameter_code`, `statistic_id`, `time` (`"2021-11-16"`), `value` (**string**, e.g. `"119000"`), `unit_of_measure` (`"ft^3/s"`), `approval_status` (`"Approved"` | `"Provisional"`), `qualifier` (**list or null**, e.g. `["EQUIP","ESTIMATED"]`), `last_modified`.
- `skipGeometry=true` removes the per-feature geometry and shrinks the payload.
- `limit` is capped at 50,000; above that the API returns HTTP 400 `InvalidParameterValue` "Limit of 50000 exceeded". The longest of the 285 audited records is 49,486 days, so every gage fits in one request — but only just, so the `next`-link pagination still has to work.
- With the configured `USGS_API_KEY` the response carries `X-Ratelimit-Limit: 1000` and `X-Ratelimit-Remaining`. Anonymous requests get HTTP 429 under load.
- Observed qualifier vocabulary across 7 gages: `ESTIMATED`, `REVISED`, `ICE`, `EQUIP`, `MAINT`, `BACKWATER`.
- Sampled gages each returned exactly one `time_series_id` for `00060`/`00003`, but the client must still not silently discard a second series.

- [ ] **Step 1: Write the failing test**

Create `tests/test_usgs_waterdata_client.py`:

```python
"""Tests for the USGS Water Data OGC API daily-mean client.

All HTTP is mocked. The live-API test is marked `integration` and skipped by
default, matching tests/test_usgs_client.py.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.acquisition.usgs_waterdata_client import (
    USGSWaterDataClient,
    USGSWaterDataError,
    USGSWaterDataTransientError,
    build_quality_code,
)


class _FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


def _feature(time, value, approval="Approved", qualifier=None):
    return {
        "properties": {
            "time_series_id": "abc",
            "monitoring_location_id": "USGS-12200500",
            "parameter_code": "00060",
            "statistic_id": "00003",
            "time": time,
            "value": value,
            "unit_of_measure": "ft^3/s",
            "approval_status": approval,
            "qualifier": qualifier,
            "last_modified": "2025-02-27T15:09:29.008013+00:00",
        }
    }


def _page(features, next_url=None):
    links = [{"rel": "self", "href": "x"}]
    if next_url:
        links.append({"rel": "next", "href": next_url})
    return {"type": "FeatureCollection", "features": features, "links": links}


# --- quality code mapping -------------------------------------------------

def test_quality_code_approved_no_qualifier():
    assert build_quality_code("Approved", None) == "A"


def test_quality_code_provisional():
    assert build_quality_code("Provisional", None) == "P"


def test_quality_code_approved_estimated_matches_legacy_format():
    # Legacy NWIS stored this as "A, e" and 654,593 such rows already exist.
    assert build_quality_code("Approved", ["ESTIMATED"]) == "A, e"


def test_quality_code_revised():
    assert build_quality_code("Approved", ["REVISED"]) == "A, R"


def test_quality_code_equip_and_estimated():
    assert build_quality_code("Approved", ["EQUIP", "ESTIMATED"]) == "A, q, e"


def test_quality_code_truncated_to_field_length():
    code = build_quality_code(
        "Approved", ["EQUIP", "ESTIMATED", "ICE", "MAINT", "BACKWATER", "REVISED"]
    )
    assert len(code) <= 10


def test_quality_code_unknown_qualifier_is_ignored_not_crashing():
    assert build_quality_code("Approved", ["SOMETHING_NEW"]) == "A"


# --- parsing --------------------------------------------------------------

def test_observed_at_is_midnight_utc():
    # All 25,311,950 existing USGS daily_mean rows are at 00:00:00 UTC. Any
    # other time-of-day would insert duplicates instead of updating.
    page = _page([_feature("2021-11-16", "119000")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert len(obs) == 1
    assert obs[0]["observed_at"] == datetime(2021, 11, 16, tzinfo=timezone.utc)
    assert obs[0]["observed_at"].tzinfo is not None


def test_string_value_is_converted_to_float():
    page = _page([_feature("2021-11-16", "119000")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert obs[0]["discharge"] == 119000.0
    assert isinstance(obs[0]["discharge"], float)


def test_obs_dict_shape_matches_legacy_client():
    page = _page([_feature("2021-11-16", "119000")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert set(obs[0]) == {
        "observed_at", "discharge", "unit", "type", "quality_code"
    }
    assert obs[0]["unit"] == "cfs"
    assert obs[0]["type"] == "daily_mean"


def test_the_skagit_crest_round_trips():
    crest = {
        "2021-11-13": ("65200", None),
        "2021-11-15": ("94100", ["EQUIP", "ESTIMATED"]),
        "2021-11-16": ("119000", ["EQUIP", "ESTIMATED"]),
        "2021-11-17": ("96200", None),
    }
    page = _page([
        _feature(t, v, qualifier=q) for t, (v, q) in crest.items()
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    by_date = {o["observed_at"].date().isoformat(): o for o in obs}
    assert by_date["2021-11-16"]["discharge"] == 119000.0
    assert by_date["2021-11-16"]["quality_code"] == "A, q, e"
    assert by_date["2021-11-13"]["quality_code"] == "A"


def test_null_and_unparseable_values_are_skipped_with_a_log(caplog):
    page = _page([
        _feature("2021-11-16", "119000"),
        _feature("2021-11-17", None),
        _feature("2021-11-18", "not-a-number"),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with caplog.at_level("WARNING"):
            obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert len(obs) == 1
    assert any("Unparseable" in r.message for r in caplog.records)


def test_empty_result_returns_empty_list():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))):
        assert USGSWaterDataClient().get_daily_mean("12200500", None) == []


# --- pagination -----------------------------------------------------------

def test_pagination_follows_next_link():
    page_1 = _page([_feature("2021-11-15", "94100")], next_url="http://next/page2")
    page_2 = _page([_feature("2021-11-16", "119000")])

    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               side_effect=[_FakeResponse(page_1), _FakeResponse(page_2)]) as g:
        obs = USGSWaterDataClient().get_daily_mean("12200500", None)

    assert len(obs) == 2
    assert g.call_count == 2


def test_pagination_stops_when_no_next_link():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               side_effect=[_FakeResponse(_page([_feature("2021-11-16", "1")]))]) as g:
        USGSWaterDataClient().get_daily_mean("12200500", None)
    assert g.call_count == 1


# --- errors ---------------------------------------------------------------

def test_429_raises_transient_error():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=429,
                                          headers={"Retry-After": "1"})):
        with pytest.raises(USGSWaterDataTransientError):
            USGSWaterDataClient().get_daily_mean("12200500", None, _retries=0)


def test_503_raises_transient_error():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=503)):
        with pytest.raises(USGSWaterDataTransientError):
            USGSWaterDataClient().get_daily_mean("12200500", None, _retries=0)


def test_404_raises_permanent_error():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=404)):
        with pytest.raises(USGSWaterDataError):
            USGSWaterDataClient().get_daily_mean("12200500", None, _retries=0)


# --- request construction -------------------------------------------------

def test_request_filters_on_parameter_and_statistic():
    # statistic_id=00003 is what replaces the legacy discharge_cols[0] guess.
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        USGSWaterDataClient().get_daily_mean("12200500", None)

    params = g.call_args.kwargs["params"]
    assert params["monitoring_location_id"] == "USGS-12200500"
    assert params["parameter_code"] == "00060"
    assert params["statistic_id"] == "00003"
    assert params["skipGeometry"] == "true"


def test_date_range_is_sent_as_a_datetime_interval():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        USGSWaterDataClient().get_daily_mean(
            "12200500",
            datetime(2026, 10, 1, tzinfo=timezone.utc),
            datetime(2026, 11, 12, tzinfo=timezone.utc),
        )

    assert g.call_args.kwargs["params"]["datetime"] == "2026-10-01/2026-11-12"


def test_no_dates_sends_no_datetime_param():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        USGSWaterDataClient().get_daily_mean("12200500", None)

    assert "datetime" not in g.call_args.kwargs["params"]


def test_api_key_sent_as_header_when_configured():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        client = USGSWaterDataClient(api_key="secret-key")
        client.get_daily_mean("12200500", None)

    assert g.call_args.kwargs["headers"]["X-Api-Key"] == "secret-key"


def test_no_api_key_header_when_unset():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        client = USGSWaterDataClient(api_key="")
        client.get_daily_mean("12200500", None)

    assert "X-Api-Key" not in g.call_args.kwargs["headers"]


def test_multiple_time_series_are_logged(caplog):
    page = _page([
        _feature("2021-11-16", "119000"),
        {"properties": {**_feature("2021-11-16", "42")["properties"],
                        "time_series_id": "second-series"}},
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with caplog.at_level("WARNING"):
            USGSWaterDataClient().get_daily_mean("12200500", None)

    assert any("multiple time series" in r.message.lower()
               for r in caplog.records)


@pytest.mark.integration
def test_live_api_returns_the_skagit_crest():
    obs = USGSWaterDataClient().get_daily_mean(
        "12200500",
        datetime(2021, 11, 10, tzinfo=timezone.utc),
        datetime(2021, 11, 22, tzinfo=timezone.utc),
    )
    by_date = {o["observed_at"].date().isoformat(): o["discharge"] for o in obs}
    assert by_date["2021-11-16"] == 119000.0
    assert by_date["2021-11-15"] == 94100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_usgs_waterdata_client.py -v -m "not integration"`
Expected: collection error — `ModuleNotFoundError: No module named 'src.acquisition.usgs_waterdata_client'`

- [ ] **Step 3: Implement the client**

Create `src/acquisition/usgs_waterdata_client.py`:

```python
"""USGS Water Data OGC API client for daily-mean discharge.

Replaces the legacy NWIS WaterServices path (``dataretrieval.nwis.get_dv``)
for daily means. USGS is retiring the legacy service, and at scale it returned
undecodable gzip bodies and empty responses — config 9 "USGS Daily Mean Pull"
logged 101 failed runs in August 2026 alone.

Two things this client does that the legacy path could not:

* filters on ``statistic_id="00003"`` so the daily-mean series is selected
  explicitly, instead of guessing with ``discharge_cols[0]`` and silently
  dropping any other series;
* surfaces ``approval_status`` and ``qualifier`` per value, so revised and
  estimated values are distinguishable.

Emitted observation dicts match the legacy client's shape exactly, so
``DataProcessor`` needs no changes.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DISCHARGE_PARAMETER_CODE = "00060"
DAILY_MEAN_STATISTIC_ID = "00003"

# 50,000 is the API's hard maximum ("Limit of 50000 exceeded" above it) and is
# deliberately used in full: the longest record among the 285 NWRFC-mapped
# gages is 49,486 days, so one request covers one gage. At limit=10000 the
# backfill would need 939 requests instead of 285, and backfill plus audit
# would blow the API key's 1,000 requests/hour budget.
PAGE_LIMIT = 50000

# Guard against a malformed `next` chain looping forever.
MAX_PAGES = 200

REQUEST_TIMEOUT_SECONDS = 180
DEFAULT_RETRIES = 3

# approval_status -> legacy NWIS base code, preserving the quality_code
# vocabulary already stored in discharge_observations ('A', 'P').
APPROVAL_CODES = {"Approved": "A", "Provisional": "P"}

# qualifier -> legacy NWIS suffix letter. 'e' (estimated) and 'R' (revised)
# reproduce the existing 'A, e' / 'A, R' codes. The rest had no legacy
# single-letter form; these are chosen to stay inside
# DischargeObservation.quality_code's max_length=10.
QUALIFIER_CODES = {
    "ESTIMATED": "e",
    "REVISED": "R",
    "ICE": "i",
    "EQUIP": "q",
    "MAINT": "m",
    "BACKWATER": "b",
}

QUALITY_CODE_MAX_LENGTH = 10


class USGSWaterDataError(Exception):
    """A non-retryable failure (4xx other than 429, malformed payload)."""


class USGSWaterDataTransientError(Exception):
    """A retryable failure (429, 5xx, network error)."""


def build_quality_code(
    approval_status: Optional[str], qualifier: Optional[list]
) -> str:
    """Render approval status and qualifiers as a legacy-style quality code.

    ``("Approved", ["EQUIP", "ESTIMATED"])`` -> ``"A, q, e"``. Unknown
    qualifiers are ignored rather than raising, so a new USGS vocabulary entry
    cannot break ingestion. The result is truncated to the model's
    ``max_length=10``.
    """
    base = APPROVAL_CODES.get(approval_status or "", "")
    parts = [base] if base else []

    for item in qualifier or []:
        code = QUALIFIER_CODES.get(str(item).upper())
        if code is None:
            logger.debug("Unmapped USGS qualifier %r ignored", item)
            continue
        if code not in parts:
            parts.append(code)

    return ", ".join(parts)[:QUALITY_CODE_MAX_LENGTH]


class USGSWaterDataClient:
    """Reads daily-mean discharge from the USGS Water Data OGC API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.base_url = (
            base_url
            if base_url is not None
            else getattr(
                settings,
                "USGS_WATERDATA_BASE",
                "https://api.waterdata.usgs.gov/ogcapi/v1",
            )
        ).rstrip("/")
        self.api_key = (
            api_key
            if api_key is not None
            else getattr(settings, "USGS_API_KEY", "")
        )
        self.logger = logging.getLogger(__name__)

    # -- public API -------------------------------------------------------

    def get_daily_mean(
        self,
        station_number: str,
        start_date: Optional[datetime],
        end_date: Optional[datetime] = None,
        _retries: int = DEFAULT_RETRIES,
    ) -> List[Dict]:
        """Return daily-mean discharge observations for one USGS station.

        Args:
            station_number: bare USGS site id, e.g. ``"12200500"``.
            start_date: inclusive start, or ``None`` for the full record.
            end_date: inclusive end. Ignored unless ``start_date`` is given.
            _retries: retry budget for transient failures; 0 disables retrying.

        Returns:
            Observation dicts with keys ``observed_at`` (midnight UTC),
            ``discharge`` (cfs, float), ``unit``, ``type``, ``quality_code``.
        """
        params = {
            "monitoring_location_id": f"USGS-{station_number}",
            "parameter_code": DISCHARGE_PARAMETER_CODE,
            "statistic_id": DAILY_MEAN_STATISTIC_ID,
            "limit": PAGE_LIMIT,
            "skipGeometry": "true",
        }
        if start_date is not None:
            stop = end_date or datetime.now(timezone.utc)
            params["datetime"] = (
                f"{self._as_date(start_date)}/{self._as_date(stop)}"
            )

        self.logger.info(
            "Fetching USGS daily mean for %s (%s)",
            station_number,
            params.get("datetime", "full record"),
        )

        features = self._fetch_all_pages(params, _retries)
        observations = self._parse(features, station_number)

        self.logger.info(
            "Retrieved %d daily mean records for %s",
            len(observations),
            station_number,
        )
        return observations

    # -- internals --------------------------------------------------------

    @staticmethod
    def _as_date(value) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value)[:10]

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/geo+json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    def _fetch_all_pages(self, params: Dict, retries: int) -> List[Dict]:
        url = f"{self.base_url}/collections/daily/items"
        features: List[Dict] = []
        pages = 0

        while url and pages < MAX_PAGES:
            payload = self._get(url, params, retries)
            features.extend(payload.get("features") or [])
            pages += 1

            url = next(
                (
                    link.get("href")
                    for link in payload.get("links") or []
                    if link.get("rel") == "next"
                ),
                None,
            )
            # `next` is absolute and already carries the query string.
            params = {}

        if pages >= MAX_PAGES and url:
            self.logger.warning(
                "Stopped paginating after %d pages; result may be truncated",
                MAX_PAGES,
            )

        return features

    def _get(self, url: str, params: Dict, retries: int) -> Dict:
        attempt = 0
        while True:
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=self._headers(),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                error: Exception = USGSWaterDataTransientError(str(exc))
            else:
                error = self._classify(response)
                if error is None:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise USGSWaterDataError(
                            f"Malformed JSON from {url}: {exc}"
                        ) from exc

            if isinstance(error, USGSWaterDataTransientError) and attempt < retries:
                delay = self._retry_delay(locals().get("response"), attempt)
                self.logger.warning(
                    "Transient USGS Water Data failure (%s); retry %d/%d in %.1fs",
                    error,
                    attempt + 1,
                    retries,
                    delay,
                )
                _time.sleep(delay)
                attempt += 1
                continue

            raise error

    @staticmethod
    def _classify(response) -> Optional[Exception]:
        status = response.status_code
        if status == 200:
            return None
        if status == 429 or status >= 500:
            return USGSWaterDataTransientError(f"HTTP {status}")
        return USGSWaterDataError(f"HTTP {status}")

    @staticmethod
    def _retry_delay(response, attempt: int) -> float:
        # Honour Retry-After when the API sends it; otherwise back off.
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(float(retry_after), 120.0)
                except (TypeError, ValueError):
                    pass
        return min(2.0 ** (attempt + 1), 60.0)

    def _parse(self, features: List[Dict], station_number: str) -> List[Dict]:
        observations: List[Dict] = []
        series_ids = set()

        for feature in features:
            props = feature.get("properties") or {}
            series_ids.add(props.get("time_series_id"))

            raw_value = props.get("value")
            raw_time = props.get("time")

            if raw_value is None or raw_time is None:
                self.logger.warning(
                    "Unparseable USGS record for %s at %s: value=%r",
                    station_number,
                    raw_time,
                    raw_value,
                )
                continue

            try:
                discharge = float(raw_value)
            except (TypeError, ValueError):
                self.logger.warning(
                    "Unparseable USGS discharge for %s at %s: %r",
                    station_number,
                    raw_time,
                    raw_value,
                )
                continue

            try:
                day = date.fromisoformat(str(raw_time)[:10])
            except ValueError:
                self.logger.warning(
                    "Unparseable USGS date for %s: %r", station_number, raw_time
                )
                continue

            observations.append(
                {
                    # Midnight UTC: matches all 25.3M existing USGS daily_mean
                    # rows, so upserts update instead of duplicating.
                    "observed_at": datetime(
                        day.year, day.month, day.day, tzinfo=timezone.utc
                    ),
                    "discharge": discharge,
                    "unit": "cfs",
                    "type": "daily_mean",
                    "quality_code": build_quality_code(
                        props.get("approval_status"), props.get("qualifier")
                    ),
                }
            )

        if len(series_ids) > 1:
            self.logger.warning(
                "Station %s returned multiple time series for %s/%s: %s. All "
                "values kept; the last one per date wins on upsert.",
                station_number,
                DISCHARGE_PARAMETER_CODE,
                DAILY_MEAN_STATISTIC_ID,
                sorted(s for s in series_ids if s),
            )

        observations.sort(key=lambda o: o["observed_at"])
        return observations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_usgs_waterdata_client.py -v -m "not integration"`
Expected: all non-integration tests pass.

- [ ] **Step 5: Verify against the live API**

Run: `venv/bin/python -m pytest tests/test_usgs_waterdata_client.py -v -m integration`
Expected: 1 passed — the live API returns 119,000 cfs for 2021-11-16 and 94,100 for 2021-11-15.

If `-m integration` reports "no tests ran" because the marker is unregistered (the existing suite shows `PytestUnknownMarkWarning`), run the test by name instead:
`venv/bin/python -m pytest tests/test_usgs_waterdata_client.py::test_live_api_returns_the_skagit_crest -v`

- [ ] **Step 6: Commit**

```bash
git add src/acquisition/usgs_waterdata_client.py tests/test_usgs_waterdata_client.py
git commit -m "feat: add USGS Water Data OGC API client for daily-mean discharge"
```

---

### Task 6: Route scheduled daily-mean pulls through the new client

**Files:**
- Modify: `src/acquisition/tasks.py` (the USGS branch that calls `USGSClient().get_daily_mean`)
- Test: `tests/test_usgs_daily_mean_routing.py`

**Interfaces:**
- Consumes: `USGSWaterDataClient` from Task 5.
- Produces: scheduled `daily_mean` USGS pulls use `USGSWaterDataClient`. `realtime_15min` pulls continue to use the legacy `USGSClient.get_instantaneous`.

**Scope note:** only daily means move to the new API. Instantaneous/realtime acquisition stays on the legacy client — it is a different OGC collection and a separate change. Flag this to the user as remaining legacy surface.

- [ ] **Step 1: Read the call site before changing it**

Run: `grep -n "USGSClient\|get_daily_mean\|get_instantaneous\|data_type" src/acquisition/tasks.py | head -40`

Identify the branch that selects `get_daily_mean` for USGS. Record the exact surrounding lines; the edit in Step 3 must match the real code, not this plan's paraphrase.

- [ ] **Step 2: Write the failing test**

Create `tests/test_usgs_daily_mean_routing.py`:

```python
"""Scheduled USGS daily-mean pulls must use the Water Data API client.

The legacy WaterServices path is being retired and was the source of the
gzip-decode and empty-body failures in config 9. These tests pin the routing
behaviour — which client is actually called for which data_type — not merely
that the import exists.

Model field names were verified on 2026-11-13: PullConfiguration uses
`data_source` (not `agency`), and requires `data_strategy` and
`schedule_type`. Station uses `agency`.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from apps.streamflow.models import (
    PullConfiguration,
    PullConfigurationStation,
    Station,
)
from src.acquisition.tasks import _process_single_station

NEW_CLIENT = "src.acquisition.tasks.USGSWaterDataClient.get_daily_mean"
LEGACY_DAILY = "src.acquisition.usgs_client.USGSClient.get_daily_mean"
LEGACY_INSTANT = "src.acquisition.usgs_client.USGSClient.get_instantaneous"


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500", name="Skagit", agency="USGS", is_active=True
    )


def _config(data_type):
    return PullConfiguration.objects.create(
        name=f"Test USGS {data_type} Pull",
        data_source="USGS",
        data_type=data_type,
        data_strategy="append",
        schedule_type="custom",
        schedule_value="0 */12 * * *",
        pull_start_date=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )


def _config_station(config, station):
    return PullConfigurationStation.objects.create(
        configuration=config,
        station_number=station.station_number,
        station_name=station.name,
    )


def test_daily_mean_routes_to_waterdata_client(station):
    config = _config("daily_mean")
    cs = _config_station(config, station)

    # Both clients return no observations, so the write path is not exercised;
    # this test is only about which client gets called.
    with patch(NEW_CLIENT, return_value=[]) as new_client, \
         patch(LEGACY_DAILY, return_value=[]) as legacy_daily:
        result = _process_single_station(cs, config.id, config)

    assert new_client.called, "daily_mean must go through USGSWaterDataClient"
    assert not legacy_daily.called, (
        "daily_mean must no longer use the legacy USGSClient.get_daily_mean"
    )
    assert result["success"] is True


def test_realtime_still_routes_to_legacy_client(station):
    # realtime_15min is deliberately left on the legacy client; migrating it
    # is separate work.
    config = _config("realtime_15min")
    cs = _config_station(config, station)

    with patch(NEW_CLIENT, return_value=[]) as new_client, \
         patch(LEGACY_INSTANT, return_value=[]) as legacy_instant:
        result = _process_single_station(cs, config.id, config)

    assert legacy_instant.called, "realtime_15min must use the legacy client"
    assert not new_client.called
    assert result["success"] is True


def test_daily_mean_passes_the_smart_append_start_date(station):
    # The rolling window from Task 4 must reach the new client, otherwise
    # late-published values are still never re-fetched.
    config = _config("daily_mean")
    cs = _config_station(config, station)

    with patch(NEW_CLIENT, return_value=[]) as new_client:
        _process_single_station(cs, config.id, config)

    kwargs = new_client.call_args.kwargs
    assert kwargs["station_number"] == "12200500"
    assert kwargs["start_date"] is not None
    assert kwargs["end_date"] is not None


def test_unknown_data_type_still_reports_failure(station):
    config = _config("daily_mean")
    # Keep this literal at most 20 characters: PullConfiguration.data_type is
    # CharField(max_length=20), and a longer value makes PostgreSQL raise
    # DataError during test setup, before the function under test is reached.
    config.data_type = "bogus_type"
    config.save(update_fields=["data_type"])
    cs = _config_station(config, station)

    result = _process_single_station(cs, config.id, config)

    assert result["success"] is False
    assert "bogus_type" in (result["error"] or "")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_usgs_daily_mean_routing.py -v`
Expected: `test_daily_mean_routes_to_waterdata_client` and `test_daily_mean_passes_the_smart_append_start_date` FAIL — patching `src.acquisition.tasks.USGSWaterDataClient` raises `AttributeError` because `tasks.py` does not import it yet. The legacy and unknown-type tests pass already.

- [ ] **Step 4: Wire in the new client**

In `src/acquisition/tasks.py`, add beside the existing `USGSClient` import (line 27):

```python
from src.acquisition.usgs_waterdata_client import USGSWaterDataClient
```

Then in `_process_single_station` (the USGS branch, around lines 135-148), the code currently reads:

```python
        if agency == "USGS":
            client = USGSClient()
            if config.data_type == "daily_mean":
                observations = client.get_daily_mean(
                    station_number=station_number,
                    start_date=start_date,
                    end_date=end_date,
                )
            elif config.data_type == "realtime_15min":
```

Change only the daily-mean call so it uses the new client, leaving the
`realtime_15min` branch and the trailing `else` error branch untouched:

```python
        if agency == "USGS":
            client = USGSClient()
            if config.data_type == "daily_mean":
                # Daily means come from the USGS Water Data OGC API; the legacy
                # WaterServices endpoint is being retired and was returning
                # undecodable gzip bodies and empty responses at scale.
                observations = USGSWaterDataClient().get_daily_mean(
                    station_number=station_number,
                    start_date=start_date,
                    end_date=end_date,
                )
            elif config.data_type == "realtime_15min":
```

Keep the keyword-argument call style — the tests assert on
`call_args.kwargs`. Do not restructure the branch, and do not remove the
`client = USGSClient()` line: the `realtime_15min` branch still uses it.

- [ ] **Step 5: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_usgs_daily_mean_routing.py -v`
Expected: 4 passed

- [ ] **Step 6: Confirm no regression in the pull machinery**

Run: `venv/bin/python -m pytest tests/test_usgs_data_pull.py tests/test_pull_pacing.py tests/test_pull_concurrency.py tests/test_pull_status_classification.py -q`
Expected: no new failures versus your recorded baseline.

- [ ] **Step 7: Commit**

```bash
git add src/acquisition/tasks.py tests/test_usgs_daily_mean_routing.py
git commit -m "feat: route scheduled USGS daily-mean pulls through the Water Data API client"
```

---

### Task 7: Backfill management command

**Files:**
- Create: `apps/streamflow/management/gage_lists.py`
- Create: `apps/streamflow/management/commands/backfill_usgs_observations.py`
- Test: `tests/test_gage_lists.py`
- Test: `tests/test_backfill_usgs_observations.py`

**Interfaces:**
- Consumes: `USGSWaterDataClient` (Task 5), `DataProcessor` (Tasks 2–3).
- Produces:
  - `apps.streamflow.management.gage_lists.resolve_gages(options: dict) -> List[str]` and
    `load_skip_file(path: str | None) -> set[str]`. **Task 8's audit command imports
    both** — do not duplicate this parsing in the command modules.
  - `python manage.py backfill_usgs_observations` with options
    `--gages`, `--gage-list-csv`, `--all-usgs`, `--start`, `--end`, `--dry-run`,
    `--sleep`, `--report`, `--skip-gages-file`.

**Why a shared module:** the identical gage-list parsing is needed by both this
command and Task 8's audit command. Duplicating it would violate the project's
DRY rule and give the parsing two test surfaces.

- [ ] **Step 1: Write the failing test for the shared gage-list helper**

Create `tests/test_gage_lists.py`:

```python
"""Tests for shared gage-list resolution used by the backfill and audit commands."""

import pytest
from django.core.management.base import CommandError

from apps.streamflow.management.gage_lists import load_skip_file, resolve_gages
from apps.streamflow.models import Station


def test_comma_separated_gages():
    assert resolve_gages({"gages": "12200500,13317000"}) == ["12200500", "13317000"]


def test_whitespace_and_blanks_are_stripped():
    assert resolve_gages({"gages": " 12200500 , ,13317000 "}) == [
        "12200500",
        "13317000",
    ]


def test_csv_with_usgs_id_column(tmp_path):
    csv_path = tmp_path / "gages.csv"
    csv_path.write_text("usgs_id,nwsli\n12200500,MVEW1\n13317000,WHBI1\n")

    assert resolve_gages({"gage_list_csv": str(csv_path)}) == [
        "12200500",
        "13317000",
    ]


def test_csv_duplicates_are_collapsed_preserving_order(tmp_path):
    csv_path = tmp_path / "gages.csv"
    csv_path.write_text("usgs_id\n12200500\n13317000\n12200500\n")

    assert resolve_gages({"gage_list_csv": str(csv_path)}) == [
        "12200500",
        "13317000",
    ]


def test_csv_missing_usgs_id_column_raises(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("site_no\n12200500\n")

    with pytest.raises(CommandError, match="usgs_id"):
        resolve_gages({"gage_list_csv": str(csv_path)})


def test_missing_csv_raises():
    with pytest.raises(CommandError, match="No such CSV"):
        resolve_gages({"gage_list_csv": "/nonexistent/path.csv"})


def test_all_usgs_reads_stations(db):
    Station.objects.create(station_number="13317000", name="B", agency="USGS")
    Station.objects.create(station_number="12200500", name="A", agency="USGS")
    Station.objects.create(station_number="08NL071", name="C", agency="EC")

    assert resolve_gages({"all_usgs": True}) == ["12200500", "13317000"]


def test_no_selection_raises():
    with pytest.raises(CommandError, match="--gages"):
        resolve_gages({})


def test_load_skip_file_returns_set(tmp_path):
    skip = tmp_path / "done.txt"
    skip.write_text("12200500\n13317000\n\n")

    assert load_skip_file(str(skip)) == {"12200500", "13317000"}


def test_load_skip_file_none_returns_empty_set():
    assert load_skip_file(None) == set()


def test_load_skip_file_missing_raises():
    with pytest.raises(CommandError, match="No such skip file"):
        load_skip_file("/nonexistent/skip.txt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_gage_lists.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'apps.streamflow.management.gage_lists'`

- [ ] **Step 3: Implement the shared helper**

Create `apps/streamflow/management/gage_lists.py`:

```python
"""Shared gage-list resolution for the observation backfill and audit commands.

Both commands accept the same three ways of naming gages, so the parsing lives
here rather than being duplicated per command.
"""

import csv
from pathlib import Path
from typing import Dict, List, Set

from django.core.management.base import CommandError

from apps.streamflow.models import Station


def resolve_gages(options: Dict) -> List[str]:
    """Return the USGS site ids selected by a command's options.

    Recognises, in priority order, ``gages`` (comma-separated), then
    ``gage_list_csv`` (a CSV with a ``usgs_id`` column), then ``all_usgs``.
    Duplicates are collapsed with first-seen order preserved.

    Raises:
        CommandError: if nothing is selected, or a CSV is missing or lacks
            a ``usgs_id`` column.
    """
    if options.get("gages"):
        return _dedupe(g.strip() for g in options["gages"].split(","))

    if options.get("gage_list_csv"):
        path = Path(options["gage_list_csv"])
        if not path.exists():
            raise CommandError(f"No such CSV: {path}")
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            if "usgs_id" not in (reader.fieldnames or []):
                raise CommandError(
                    f"{path} has no 'usgs_id' column "
                    f"(found: {reader.fieldnames})"
                )
            return _dedupe(
                (record.get("usgs_id") or "").strip() for record in reader
            )

    if options.get("all_usgs"):
        return list(
            Station.objects.filter(agency="USGS")
            .order_by("station_number")
            .values_list("station_number", flat=True)
        )

    raise CommandError(
        "Choose gages with --gages, --gage-list-csv or --all-usgs"
    )


def load_skip_file(path) -> Set[str]:
    """Return the gage ids listed one-per-line in ``path``, or an empty set."""
    if not path:
        return set()
    file_path = Path(path)
    if not file_path.exists():
        raise CommandError(f"No such skip file: {file_path}")
    return {
        line.strip()
        for line in file_path.read_text().splitlines()
        if line.strip()
    }


def _dedupe(values) -> List[str]:
    seen, out = set(), []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_gage_lists.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit the helper**

```bash
git add apps/streamflow/management/gage_lists.py tests/test_gage_lists.py
git commit -m "feat: add shared gage-list resolution for observation commands"
```

- [ ] **Step 6: Write the failing test for the backfill command**

Create `tests/test_backfill_usgs_observations.py`:

```python
"""Tests for the USGS observation backfill command."""

from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.streamflow.models import DischargeObservation, Station


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500",
        name="SKAGIT RIVER NEAR MOUNT VERNON, WA",
        agency="USGS",
        is_active=True,
    )


CREST = [
    {
        "observed_at": datetime(2021, 11, 16, tzinfo=timezone.utc),
        "discharge": 119000.0,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A, q, e",
    },
    {
        "observed_at": datetime(2021, 11, 15, tzinfo=timezone.utc),
        "discharge": 94100.0,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A, q, e",
    },
]


def test_backfill_inserts_missing_peak(station):
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            stdout=StringIO(),
        )

    row = DischargeObservation.objects.get(
        station=station, observed_at=datetime(2021, 11, 16, tzinfo=timezone.utc)
    )
    assert row.discharge == Decimal("119000.0000")


def test_backfill_overwrites_a_stale_value(station):
    DischargeObservation.objects.create(
        station=station,
        observed_at=datetime(2021, 11, 16, tzinfo=timezone.utc),
        discharge=Decimal("95000.0000"),
        unit="cfs",
        type="daily_mean",
        quality_code="P",
    )

    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            stdout=StringIO(),
        )

    rows = DischargeObservation.objects.filter(
        station=station, observed_at=datetime(2021, 11, 16, tzinfo=timezone.utc)
    )
    assert rows.count() == 1
    assert rows.get().discharge == Decimal("119000.0000")


def test_dry_run_writes_nothing(station):
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            "--dry-run",
            stdout=StringIO(),
        )

    assert DischargeObservation.objects.filter(station=station).count() == 0


def test_unknown_gage_is_reported_and_does_not_abort_the_run(station):
    out = StringIO()
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        return_value=CREST,
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "99999999,12200500",
            stdout=out,
        )

    assert "99999999" in out.getvalue()
    assert DischargeObservation.objects.filter(station=station).count() == 2


def test_fetch_failure_does_not_abort_remaining_gages(station):
    out = StringIO()
    with patch(
        "apps.streamflow.management.commands.backfill_usgs_observations."
        "USGSWaterDataClient.get_daily_mean",
        side_effect=RuntimeError("boom"),
    ):
        call_command(
            "backfill_usgs_observations",
            "--gages", "12200500",
            stdout=out,
        )

    assert "boom" in out.getvalue() or "failed" in out.getvalue().lower()


def test_requires_a_gage_selection(db):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("backfill_usgs_observations", stdout=StringIO())
```

- [ ] **Step 7: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_backfill_usgs_observations.py -v`
Expected: FAIL — `Unknown command: 'backfill_usgs_observations'`

- [ ] **Step 8: Implement the command**

Create `apps/streamflow/management/commands/backfill_usgs_observations.py`:

```python
"""Re-fetch and upsert USGS daily-mean discharge, restoring dropped peaks.

A 5-sigma batch filter in DataProcessor.validate_observations discarded real
flood peaks, and inserts used ignore_conflicts so provisional values were never
revised. Both are fixed, but existing rows stay wrong until re-fetched. This
command re-reads whole records from the USGS Water Data API and upserts them.

It is idempotent and safe to re-run. Runs can take a long time — use nohup:

    nohup venv/bin/python manage.py backfill_usgs_observations \\
        --gage-list-csv streamflow-dataops-observation-issues/gage_gaps.csv \\
        --report data/backfill_stage_a.csv \\
        > data/backfill_stage_a.log 2>&1 &
"""

import csv
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from apps.streamflow.management.gage_lists import load_skip_file, resolve_gages
from apps.streamflow.models import DischargeObservation, Station
from src.acquisition.data_processor import DataProcessor
from src.acquisition.usgs_waterdata_client import USGSWaterDataClient


class Command(BaseCommand):
    help = (
        "Re-fetch USGS daily-mean discharge from the Water Data API and upsert "
        "it, restoring peaks dropped by the old 5-sigma filter."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--gages",
            help="Comma-separated USGS site ids.",
        )
        parser.add_argument(
            "--gage-list-csv",
            help=(
                "CSV with a 'usgs_id' column, e.g. "
                "streamflow-dataops-observation-issues/gage_gaps.csv (285 "
                "NWRFC-mapped gages)."
            ),
        )
        parser.add_argument(
            "--all-usgs",
            action="store_true",
            help="Every Station with agency='USGS'.",
        )
        parser.add_argument(
            "--start",
            help="Inclusive start date YYYY-MM-DD. Omit for the full record.",
        )
        parser.add_argument("--end", help="Inclusive end date YYYY-MM-DD.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and report, write nothing.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=1.0,
            help=(
                "Seconds between gages. Without a USGS_API_KEY the API returns "
                "429 under load. Default 1.0."
            ),
        )
        parser.add_argument(
            "--report",
            help="Write a per-gage CSV report to this path.",
        )
        parser.add_argument(
            "--skip-gages-file",
            help=(
                "File with one already-completed USGS id per line; those gages "
                "are skipped. Use a previous run's report to resume."
            ),
        )

    def handle(self, *args, **options):
        gages = resolve_gages(options)
        skip = load_skip_file(options.get("skip_gages_file"))
        if skip:
            gages = [g for g in gages if g not in skip]
            self.stdout.write(f"Skipping {len(skip)} already-completed gages")

        start = self._parse_date(options.get("start"))
        end = self._parse_date(options.get("end"))
        dry_run = options["dry_run"]
        sleep_seconds = options["sleep"]

        client = USGSWaterDataClient()
        processor = DataProcessor()
        rows = []

        self.stdout.write(
            f"Backfilling {len(gages)} gages "
            f"({'dry run' if dry_run else 'writing'})"
        )

        for index, gage in enumerate(gages, start=1):
            station = Station.objects.filter(
                station_number=gage, agency="USGS"
            ).first()
            if station is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"[{index}/{len(gages)}] {gage}: not in stations table, "
                        f"skipped"
                    )
                )
                rows.append({"usgs_id": gage, "status": "not_in_db"})
                continue

            before = self._max_discharge(station)

            try:
                observations = client.get_daily_mean(gage, start, end)
            except Exception as exc:  # noqa: BLE001 - one bad gage must not stop the run
                self.stdout.write(
                    self.style.ERROR(
                        f"[{index}/{len(gages)}] {gage}: fetch failed: {exc}"
                    )
                )
                rows.append({"usgs_id": gage, "status": f"failed: {exc}"})
                continue

            written = 0
            if observations and not dry_run:
                written = processor.process_observations(
                    station_number=gage, observations=observations
                )

            after = self._max_discharge(station)
            rows.append(
                {
                    "usgs_id": gage,
                    "status": "dry_run" if dry_run else "ok",
                    "fetched": len(observations),
                    "written": written,
                    "db_max_before": before,
                    "db_max_after": after,
                }
            )
            self.stdout.write(
                f"[{index}/{len(gages)}] {gage}: fetched {len(observations)}, "
                f"wrote {written}, max {before} -> {after}"
            )

            if sleep_seconds and index < len(gages):
                time.sleep(sleep_seconds)

        if options.get("report"):
            self._write_report(options["report"], rows)

        failed = [r for r in rows if str(r.get("status", "")).startswith("failed")]
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {len(rows)} gages processed, {len(failed)} failed."
            )
        )

    # -- helpers ---------------------------------------------------------
    # Gage-list parsing lives in apps/streamflow/management/gage_lists.py,
    # shared with audit_usgs_observations.

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        from datetime import datetime, timezone

        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise CommandError(f"Bad date {value!r}, expected YYYY-MM-DD") from exc
        return parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _max_discharge(station):
        return DischargeObservation.objects.filter(
            station=station, type="daily_mean"
        ).aggregate(m=Max("discharge"))["m"]

    def _write_report(self, path, rows):
        fields = [
            "usgs_id",
            "status",
            "fetched",
            "written",
            "db_max_before",
            "db_max_after",
        ]
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fields})
        self.stdout.write(f"Report written to {target}")
```

- [ ] **Step 9: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_backfill_usgs_observations.py tests/test_gage_lists.py -v`
Expected: 6 passed for the command + 11 passed for the helper = 17 passed

- [ ] **Step 10: Smoke-test the real command on one gage, dry run**

**This is the only live command permitted in this task.** `--dry-run` writes
nothing; it reads the production database and the USGS API only. Do not run the
command without `--dry-run` — writing to live data happens in Task 9.

Run:
```bash
venv/bin/python manage.py backfill_usgs_observations \
  --gages 12200500 --start 2021-11-10 --end 2021-11-22 --dry-run
```
Expected: reports `fetched 13, wrote 0` and leaves `db_max_before == db_max_after`.

- [ ] **Step 11: Commit**

```bash
git add apps/streamflow/management/commands/backfill_usgs_observations.py tests/test_backfill_usgs_observations.py
git commit -m "feat: add backfill_usgs_observations command to re-fetch and upsert USGS daily means"
```

---

### Task 8: Audit command to verify the backfill

**Files:**
- Create: `apps/streamflow/management/commands/audit_usgs_observations.py`
- Test: `tests/test_audit_usgs_observations.py`

**Interfaces:**
- Consumes: `USGSWaterDataClient` (Task 5); `resolve_gages` from
  `apps.streamflow.management.gage_lists` (Task 7) — **import it, do not
  reimplement the CSV/comma-list parsing here.** This command does not accept
  `--all-usgs`, so `resolve_gages` will raise `CommandError` for a bare
  invocation, which is the wanted behaviour.
- Produces: `python manage.py audit_usgs_observations` with `--gages`, `--gage-list-csv`, `--report`, `--sleep`. Compares the DB against the API per gage and reports `n_missing`, `n_value_diff`, `db_max`, `api_max`.

This replaces re-running the external `audit_observation_gaps.py`, which needs `sqlalchemy`/`psycopg2` and a DSN. Same comparison, inside Django.

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_usgs_observations.py`:

```python
"""Tests for the observation audit command."""

from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.streamflow.models import DischargeObservation, Station

API_ROWS = [
    {
        "observed_at": datetime(2021, 11, 15, tzinfo=timezone.utc),
        "discharge": 94100.0,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A, q, e",
    },
    {
        "observed_at": datetime(2021, 11, 16, tzinfo=timezone.utc),
        "discharge": 119000.0,
        "unit": "cfs",
        "type": "daily_mean",
        "quality_code": "A, q, e",
    },
]

PATCH_TARGET = (
    "apps.streamflow.management.commands.audit_usgs_observations."
    "USGSWaterDataClient.get_daily_mean"
)


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500", name="Skagit", agency="USGS", is_active=True
    )


def _row(station, day, value, quality_code="A"):
    return DischargeObservation.objects.create(
        station=station,
        observed_at=datetime(2021, 11, day, tzinfo=timezone.utc),
        discharge=Decimal(str(value)),
        unit="cfs",
        type="daily_mean",
        quality_code=quality_code,
    )


def test_reports_missing_days(station):
    _row(station, 15, 94100.0)
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "missing=1" in out.getvalue()


def test_reports_value_differences(station):
    _row(station, 15, 94100.0)
    _row(station, 16, 95000.0)
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "missing=0" in out.getvalue()
    assert "diff=1" in out.getvalue()


def test_clean_gage_reports_no_problems(station):
    _row(station, 15, 94100.0)
    _row(station, 16, 119000.0)
    out = StringIO()
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command("audit_usgs_observations", "--gages", "12200500", stdout=out)

    assert "missing=0" in out.getvalue()
    assert "diff=0" in out.getvalue()


def test_report_csv_is_written(station, tmp_path):
    _row(station, 15, 94100.0)
    report = tmp_path / "audit.csv"
    with patch(PATCH_TARGET, return_value=API_ROWS):
        call_command(
            "audit_usgs_observations",
            "--gages", "12200500",
            "--report", str(report),
            stdout=StringIO(),
        )

    text = report.read_text()
    assert "usgs_id" in text
    assert "12200500" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_audit_usgs_observations.py -v`
Expected: FAIL — `Unknown command: 'audit_usgs_observations'`

- [ ] **Step 3: Implement the command**

Create `apps/streamflow/management/commands/audit_usgs_observations.py`:

```python
"""Compare stored USGS daily means against the USGS Water Data API.

Run after a backfill to confirm no missing days or stale values remain. This is
the in-Django equivalent of the external audit_observation_gaps.py, which needs
sqlalchemy/psycopg2 and a DSN.

    venv/bin/python manage.py audit_usgs_observations \\
        --gage-list-csv streamflow-dataops-observation-issues/gage_gaps.csv \\
        --report data/audit_after_backfill.csv
"""

import csv
import time
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.streamflow.management.gage_lists import resolve_gages
from apps.streamflow.models import DischargeObservation, Station
from src.acquisition.usgs_waterdata_client import USGSWaterDataClient

# A value counts as different if it is off by more than 0.5 cfs and 0.5%,
# matching the tolerance used by the original audit.
ABS_TOLERANCE_CFS = 0.5
REL_TOLERANCE = 0.005


class Command(BaseCommand):
    help = "Audit stored USGS daily means against the USGS Water Data API."

    def add_arguments(self, parser):
        parser.add_argument("--gages", help="Comma-separated USGS site ids.")
        parser.add_argument(
            "--gage-list-csv", help="CSV with a 'usgs_id' column."
        )
        parser.add_argument("--report", help="Write a per-gage CSV report here.")
        parser.add_argument(
            "--sleep", type=float, default=1.0,
            help="Seconds between gages. Default 1.0.",
        )

    def handle(self, *args, **options):
        gages = resolve_gages(options)
        client = USGSWaterDataClient()
        rows = []
        total_missing = total_diff = 0

        for index, gage in enumerate(gages, start=1):
            station = Station.objects.filter(
                station_number=gage, agency="USGS"
            ).first()
            if station is None:
                self.stdout.write(
                    self.style.WARNING(f"{gage}: not in stations table")
                )
                rows.append({"usgs_id": gage, "status": "not_in_db"})
                continue

            try:
                api_rows = client.get_daily_mean(gage, None)
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"{gage}: fetch failed: {exc}"))
                rows.append({"usgs_id": gage, "status": f"failed: {exc}"})
                continue

            api_by_date = {
                o["observed_at"].date(): float(o["discharge"]) for o in api_rows
            }
            db_by_date = {
                observed_at.date(): float(discharge)
                for observed_at, discharge in DischargeObservation.objects.filter(
                    station=station, type="daily_mean"
                ).values_list("observed_at", "discharge")
            }

            if not db_by_date or not api_by_date:
                rows.append({"usgs_id": gage, "status": "no_data"})
                continue

            # Only judge the span the DB claims to cover, as the original audit did.
            lo, hi = min(db_by_date), max(db_by_date)
            in_span = {d: v for d, v in api_by_date.items() if lo <= d <= hi}

            missing = sorted(d for d in in_span if d not in db_by_date)
            diffs = [
                d
                for d, api_value in in_span.items()
                if d in db_by_date
                and abs(api_value - db_by_date[d])
                > max(ABS_TOLERANCE_CFS, REL_TOLERANCE * api_value)
            ]

            total_missing += len(missing)
            total_diff += len(diffs)

            record = {
                "usgs_id": gage,
                "status": "ok",
                "n_db": len(db_by_date),
                "n_api_in_span": len(in_span),
                "n_missing": len(missing),
                "n_value_diff": len(diffs),
                "db_max": max(db_by_date.values()),
                "api_max": max(api_by_date.values()),
                "first_missing": missing[0].isoformat() if missing else "",
            }
            rows.append(record)
            self.stdout.write(
                f"[{index}/{len(gages)}] {gage}: missing={len(missing)} "
                f"diff={len(diffs)} db_max={record['db_max']:.0f} "
                f"api_max={record['api_max']:.0f}"
            )

            if options["sleep"] and index < len(gages):
                time.sleep(options["sleep"])

        if options.get("report"):
            self._write_report(options["report"], rows)

        self.stdout.write(
            self.style.SUCCESS(
                f"Audited {len(rows)} gages: {total_missing} missing days, "
                f"{total_diff} value differences."
            )
        )

    # Gage-list parsing is shared with backfill_usgs_observations; see
    # apps/streamflow/management/gage_lists.py.

    def _write_report(self, path, rows):
        fields = [
            "usgs_id", "status", "n_db", "n_api_in_span", "n_missing",
            "n_value_diff", "db_max", "api_max", "first_missing",
        ]
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fields})
        self.stdout.write(f"Report written to {target}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_audit_usgs_observations.py -v`
Expected: 4 passed

- [ ] **Step 5: Audit one real gage to capture the "before" state**

Run: `venv/bin/python manage.py audit_usgs_observations --gages 12200500`
Expected: roughly `missing=110 diff=106 db_max=73000 api_max=142000`. Record the exact output — Task 9 compares against it.

- [ ] **Step 6: Commit**

```bash
git add apps/streamflow/management/commands/audit_usgs_observations.py tests/test_audit_usgs_observations.py
git commit -m "feat: add audit_usgs_observations command to verify observations against USGS"
```

---

### Task 9: Deploy the code fixes, then run the staged backfill

**Files:**
- Modify: `CLAUDE.md` (document the new env vars, commands, and the corrected Django version)
- Create: `data/backfill_stage_a.csv`, `data/audit_after_stage_a.csv` (command output, gitignored)

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: corrected observations for the 285 NWRFC-mapped gages.

**Do not start this task until Tasks 1–8 are committed and reviewed.** The backfill is only correct once the 5σ drop is gone and inserts upsert.

- [ ] **Step 1: Confirm no regressions against the baseline**

Run the full suite and diff the failure set against clean `main`:
```bash
venv/bin/python -m pytest -q 2>&1 | tail -40
```
Expected: the ~311 pre-existing failures, plus the new tests passing, and **no newly failing test**. If anything new fails, stop and report it — do not change application code to make it pass.

- [ ] **Step 2: Document the changes in CLAUDE.md**

Add the three new env vars to the Settings & Environment list:

```
USGS_WATERDATA_BASE            # USGS Water Data OGC API base (default https://api.waterdata.usgs.gov/ogcapi/v1)
USGS_API_KEY                   # api.data.gov key; raises the rate limit to 1000 req/hr (anonymous gets 429s under load)
OBSERVATION_REFETCH_WINDOW_DAYS # Days each incremental observation pull rewinds before re-fetching (default 180)
```

Add to the Commands block:

```bash
# Re-fetch and upsert USGS daily means (restores peaks dropped by the old 5-sigma filter)
python manage.py backfill_usgs_observations --gage-list-csv streamflow-dataops-observation-issues/gage_gaps.csv --report data/backfill_stage_a.csv

# Verify stored observations against the USGS Water Data API
python manage.py audit_usgs_observations --gage-list-csv streamflow-dataops-observation-issues/gage_gaps.csv --report data/audit_after_stage_a.csv
```

Add a subsection under Data Acquisition Flow:

```markdown
#### Observation validation never drops records

`DataProcessor.validate_observations` rejects only impossible values (missing,
negative, > 1,000,000 cfs, unparseable timestamps). It does **not** drop
statistical outliers. A batch z-score filter (|z| > 5) used to, and because
streamflow is heavy-tailed that removed real flood peaks at 271 of 285 audited
gages — the whole November 2021 Skagit crest, including 119,000 cfs on
2021-11-16, was missing. High-z values are now logged
("High-z discharge retained") and kept. Never reintroduce a batch z-score drop
on streamflow.

#### Observation writes are upserts, and pulls rewind

`process_observations` upserts on `unique_observation_idx`
(`station`, `observed_at`, `type`), updating `discharge` and `quality_code`.
USGS revises provisional daily values for months, so a re-pulled day must
overwrite the stored value. To make that reachable, `SmartAppendLogic`
rewinds each incremental pull by `OBSERVATION_REFETCH_WINDOW_DAYS` (180)
before the station watermark, bounded below by the configuration's
`pull_start_date`.

`observed_at` for daily means is always midnight UTC. Emitting any other
time-of-day would insert duplicate rows instead of updating existing ones.

#### USGS daily means come from the Water Data OGC API

`src/acquisition/usgs_waterdata_client.py` reads
`api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items`, filtering on
`parameter_code=00060` **and** `statistic_id=00003` — which replaces the legacy
`discharge_cols[0]` guess that silently dropped any second series. The legacy
`dataretrieval.nwis.get_dv` path is being retired by USGS and was the source of
the "Expecting value: line 1 column 1" and gzip-decode failures. Instantaneous
(`realtime_15min`) acquisition is **still on the legacy client** — migrating it
is separate work.

`PAGE_LIMIT` is 50,000, the API's hard maximum — above it the API returns
HTTP 400 "Limit of 50000 exceeded". That is used in full on purpose: the
longest record among the 285 NWRFC-mapped gages is 49,486 days, so a
full-record backfill is one request per gage (285 total) against the API key's
1,000 requests/hour. Dropping the page size to 10,000 would cost 939 requests
and, with the audit's 285 on top, exceed the hourly budget.
```

Also correct the Project Overview line: the project runs **Django 6.0.2**, not Django 4.2.

- [ ] **Step 3: Commit and deploy**

```bash
git add CLAUDE.md
git commit -m "docs: record observation ingest fixes, Water Data API client, and new env vars"
git push
```

Then in the production tree:
```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps
git pull
sudo systemctl restart gunicorn celery-worker celery-beat
sudo systemctl status gunicorn celery-worker celery-beat --no-pager
```
Expected: all three active (running).

- [ ] **Step 4: Verify the live pull path works before backfilling**

Trigger one small real pull and confirm it writes without error:
```bash
venv/bin/python manage.py backfill_usgs_observations \
  --gages 12200500 --start 2021-11-10 --end 2021-11-22
```
Expected: `fetched 13, wrote 13`, and `db_max_before 73000 -> db_max_after 119000`.

Then confirm the crest is actually in the database:
```bash
venv/bin/python -c "
import os,django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from apps.streamflow.models import Station, DischargeObservation
s=Station.objects.get(station_number='12200500', agency='USGS')
for o in DischargeObservation.objects.filter(station=s,type='daily_mean',
        observed_at__date__gte='2021-11-12',observed_at__date__lte='2021-11-20').order_by('observed_at'):
    print(o.observed_at.date(), o.discharge, repr(o.quality_code))
"
```
Expected: nine consecutive days 11-12 → 11-20, with 119000.0000 on 11-16.

**If this step does not produce the crest, stop.** Do not launch the bulk backfill.

- [ ] **Step 5: Run Stage A — the 285 NWRFC-mapped gages**

This takes well over 5 minutes, so run it detached:
```bash
cd /home/streamflow/streamflow-dataOps/streamflow-dataOps
nohup venv/bin/python manage.py backfill_usgs_observations \
  --gage-list-csv streamflow-dataops-observation-issues/gage_gaps.csv \
  --sleep 1.0 \
  --report data/backfill_stage_a.csv \
  > data/backfill_stage_a.log 2>&1 &
echo "started pid $!"
```

Monitor with `tail -f data/backfill_stage_a.log`.

**Request budget.** With `PAGE_LIMIT = 50000` this is one request per gage — 285 requests against the key's 1,000/hour limit. The Stage A audit in Step 6 costs another 285, so run the two in sequence, not concurrently, and stay under the hourly cap. At `--sleep 1.0` the fetches alone span ~5 minutes of wall clock, so the cap is not at risk, but do not lower `--sleep` or parallelise: `SOURCE_PACING` limits USGS to 3 workers at 1.0 s precisely because USGS degrades silently under bursts.

If the log does fill with HTTP 429, stop the run and resume later with `--skip-gages-file` built from the completed gages in the report. The key is already configured, so a 429 means the hourly budget is exhausted, not that authentication is missing.

- [ ] **Step 6: Verify Stage A**

```bash
nohup venv/bin/python manage.py audit_usgs_observations \
  --gage-list-csv streamflow-dataops-observation-issues/gage_gaps.csv \
  --report data/audit_after_stage_a.csv \
  > data/audit_after_stage_a.log 2>&1 &
```

Then summarise:
```bash
venv/bin/python -c "
import pandas as pd
a=pd.read_csv('data/audit_after_stage_a.csv')
ok=a[a.status=='ok']
print('gages audited      :',len(ok))
print('total missing days :',int(ok.n_missing.sum()),'(was 46,701)')
print('total value diffs  :',int(ok.n_value_diff.sum()),'(was 49,523)')
print('gages still missing:',int((ok.n_missing>0).sum()),'(was 274)')
print()
worst=ok.sort_values('n_missing',ascending=False).head(10)
print(worst[['usgs_id','n_missing','n_value_diff','db_max','api_max']].to_string(index=False))
"
```
Expected: missing days and value differences near zero. Residual missing days are legitimate only where USGS has no value; investigate any gage still reporting a large `n_missing`, and report the numbers rather than assuming success.

- [ ] **Step 7: Commit the reports' provenance, not the data**

Confirm `data/` output is gitignored (`git check-ignore -v data/backfill_stage_a.csv`). If it is not, add `data/backfill_*.csv`, `data/audit_*.csv` and `data/*.log` to `.gitignore` and commit that.

```bash
git add .gitignore
git commit -m "chore: ignore observation backfill reports and logs"
```

- [ ] **Step 8: Report results and surface the remaining decisions**

Write a short summary for the user covering:
- before/after missing-day and value-difference counts from Step 6;
- the Skagit crest check from Step 4;
- that **Stage B** (the remaining USGS stations beyond the 285 audited) has not been run — it is `--all-usgs` with the same command;
- that **`DailyFlowPercentile` and any other derived product were computed on records without peaks** and still need recomputing (the user deferred this decision);
- that **instantaneous/`realtime_15min` acquisition is still on the legacy retiring NWIS endpoint**.

---

## Self-Review

**Spec coverage.** Report issue 1 (5σ drop) → Task 2. Issue 2 (never updates) → Task 3. Issue 3 (never re-fetches) → Task 4. Issue 4 (failing pulls / legacy endpoint / `discharge_cols[0]`) → Tasks 1, 5, 6. Suggested repair order items 1–2 → Tasks 2–6; item 3 (backfill) → Tasks 7 and 9; item 4 (re-run the audit) → Tasks 8 and 9 Step 6; item 5 (recompute derived products) → deliberately deferred by the user, surfaced again in Task 9 Step 8.

**Deliberately out of scope**, and called out to the user in Task 9 Step 8:
- Report item 5's pre-1955 blocks (12,854 days, mostly 13266000, 1921–1952). The full-record backfill in Task 7 will pick these up if USGS serves them; no separate work.
- Instantaneous/`realtime_15min` migration to the new API.
- Recomputing `DailyFlowPercentile`.
- Stage B (all USGS stations beyond the audited 285).

**Type consistency.** `get_daily_mean(station_number, start_date, end_date=None)` keeps the legacy signature, and the emitted dict keys (`observed_at`, `discharge`, `unit`, `type`, `quality_code`) match what `DataProcessor.process_observations` already consumes, so Tasks 2–3 and Task 5 compose without an adapter. `build_quality_code` is used by Task 5 only. `USGSWaterDataError` / `USGSWaterDataTransientError` are raised in Task 5 and caught broadly in Tasks 7–8. Settings names are identical in Tasks 1, 4 and 5.

**Risk notes.**
- The highest-risk detail is the midnight-UTC `observed_at` convention: get it wrong and the upsert inserts a parallel set of rows rather than correcting 25.3M existing ones. It is pinned by `test_observed_at_is_midnight_utc` and re-checked by hand in Task 9 Step 4.
- Task 9 Step 4 is a hard gate before the bulk run.
- `--sleep 1.0` matches the existing `SOURCE_PACING` entry for USGS (3 workers, 1.0 s), which was added because USGS degrades silently under bursts rather than returning 429s.
