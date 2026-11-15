# realtime_15min Migration to the Water Data OGC API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `realtime_15min` acquisition off the retiring legacy NWIS WaterServices endpoint (`dataretrieval.nwis.get_iv`) onto the Water Data OGC API's `continuous` collection, keeping the feature fully GUI-configurable and API-readable.

**Architecture:** Add `get_instantaneous` to the existing, already-hardened `USGSWaterDataClient` so it reuses that class's retry classification, pagination, provenance guard and quality-code mapping. Then point the `realtime_15min` branch of `_process_single_station` at it. The daily-mean path is untouched.

**Tech Stack:** Python 3.12, Django 6.0.2, PostgreSQL, `requests`, pytest + pytest-django.

## Background

`realtime_15min` currently holds **zero rows** and has **no pull configuration** — the table is 100% `daily_mean`. That is *not* because the feature is dead: this data existed until roughly March 2026 and was deleted to relieve storage pressure. It will be re-enabled for a few dozen stations once storage is sorted. So the path must stay a working, GUI-configurable, API-readable feature, not be retired.

Storage, for planning: a 15-minute series is **35,040 points per station-year**. Twenty-four stations is ~841k rows/year; forty is ~1.4M/year, ~14M over ten years, against an existing 37.8M-row table.

The 180-day rolling re-fetch window is already gated to `daily_mean` and `ec_realtime_daily` only (`src/acquisition/smart_append.py`, `REFETCH_WINDOW_DATA_TYPES`). **That gating is load-bearing here** — without it every realtime config would re-pull 180 days of 15-minute data on every 5-minute dispatch. Do not widen it.

### API facts, measured 2026-11-15

- Collection `continuous` ("Continuous values") is the instantaneous equivalent of `daily`.
- Discharge is `parameter_code="00060"` with `statistic_id="00011"` (**not** `00003`). A probe of 12200500 returned `00011` for all 35,016 points.
- `limit` is capped at 50,000, same as `daily` (HTTP 400 `InvalidParameterValue` above it).
- **With no `datetime` parameter the API silently returns only the most recent ~1 year** (35,016 points, 2025-11-15 → 2026-11-15, no `next` link). Explicit ranges reach much further back: `2024-01-01/2024-01-31` returned 2,881 points and `2023-06-01/2023-06-30` returned 2,785. **The client must therefore always send an explicit `datetime` range**, or a historical pull silently truncates to one year.
- One year of 15-minute data (~35,040 points) fits in a single 50,000-row request, so a multi-year pull must be split into time windows rather than relying on a single call.
- Feature `properties` match the `daily` shape — `time_series_id`, `monitoring_location_id`, `parameter_code`, `statistic_id`, `time`, `value` (**string**), `unit_of_measure` (`"ft^3/s"`), `approval_status`, `qualifier`, `last_modified` — plus `method_category`. `time` is a **full ISO timestamp with offset**, e.g. `2025-11-15T18:15:00+00:00`.

### What the legacy implementation did

`USGSClient.get_instantaneous` (`src/acquisition/usgs_client.py`) calls `nwis.get_iv(sites=..., parameterCd="00060", ...)`, takes `discharge_cols[0]` — the same silent multi-series guess that the daily migration removed — reads `observed_at` straight from the DataFrame index, sets `unit="cfs"`, `type="realtime_15min"`, takes `quality_code` from the matching `_cd` column, and skips rows whose discharge is null.

## Global Constraints

- **The production tree IS the deployment.** Develop in the worktree, push, `git pull` in `/home/streamflow/streamflow-dataOps/streamflow-dataOps`, restart services.
- Run Python as `venv/bin/python`. `source venv/bin/activate` does not work here.
- **Never modify application code to make a failing test pass.** Report and stop.
- **Do NOT use `git stash`** — the stash stack is shared across worktrees. Use `cp`.
- **Do NOT edit** `tests/test_backfill_usgs_observations.py`, `tests/test_audit_usgs_observations.py`, or `tests/test_usgs_waterdata_client.py`'s existing tests — the first two are pinned regression proofs and the third pins the daily-mean client behaviour. Add new tests; do not alter existing ones.
- `observed_at` for `realtime_15min` is a **full timezone-aware UTC timestamp**, not midnight. The midnight-UTC invariant applies only to `daily_mean`. Do not round, truncate, or localise it.
- `unit` is `"cfs"`; `type` is `"realtime_15min"`.
- `DischargeObservation.quality_code` is `CharField(max_length=10)`.
- The unique constraint is `(station, observed_at, type)`, so two points sharing a timestamp in one batch would break the upsert. Dedupe by exact timestamp.
- Do not change `USGSWaterDataClient.get_daily_mean` or any daily-mean behaviour.
- Do not widen `REFETCH_WINDOW_DATA_TYPES` in `smart_append.py`.
- `realtime_15min` must remain selectable in the GUI configuration form and filterable on the REST API (`filterset_fields` already includes `type`).

---

### Task 1: `get_instantaneous` on the Water Data client

**Files:**
- Modify: `src/acquisition/usgs_waterdata_client.py`
- Test: `tests/test_usgs_waterdata_instantaneous.py`

**Interfaces:**
- Consumes: the existing module internals — `_get`, `_fetch_all_pages`, `build_quality_code`, the provenance guard, and the error classes.
- Produces: `USGSWaterDataClient.get_instantaneous(station_number: str, start_date: datetime, end_date: datetime | None = None) -> List[Dict]`, emitting dicts with `observed_at` (tz-aware UTC timestamp), `discharge` (float), `unit` (`"cfs"`), `type` (`"realtime_15min"`), `quality_code` (str ≤10). Plus module constants `CONTINUOUS_STATISTIC_ID = "00011"` and `INSTANTANEOUS_WINDOW_DAYS = 180`.

- [ ] **Step 1: Read the existing daily-mean path first**

Read `src/acquisition/usgs_waterdata_client.py` in full before writing anything. `get_instantaneous` must reuse, not duplicate: the request/retry helper, the `next`-link pagination, `build_quality_code`, the per-feature provenance check, and `USGSWaterDataError` / `USGSWaterDataTransientError`. Note in your report which internals you reused and anything you had to generalise.

Where the daily path hardcodes `DAILY_MEAN_STATISTIC_ID` or the `daily` collection, parameterise rather than copy — but do not change the behaviour of `get_daily_mean`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_usgs_waterdata_instantaneous.py`:

```python
"""Tests for instantaneous (realtime_15min) fetches from the OGC `continuous` collection.

Measured 2026-11-15: discharge there is parameter_code 00060 with
statistic_id 00011 (not 00003); `limit` caps at 50,000; and with NO
`datetime` parameter the API silently returns only the most recent ~1 year,
so an explicit range is mandatory or a historical pull truncates in silence.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.acquisition.usgs_waterdata_client import (
    CONTINUOUS_STATISTIC_ID,
    USGSWaterDataClient,
    USGSWaterDataError,
    USGSWaterDataTransientError,
)

UTC = timezone.utc


class _FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload, self.status_code = payload, status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


def _feature(time, value, approval="Approved", qualifier=None, **over):
    props = {
        "time_series_id": "ts-1",
        "monitoring_location_id": "USGS-12200500",
        "parameter_code": "00060",
        "statistic_id": "00011",
        "time": time,
        "value": value,
        "unit_of_measure": "ft^3/s",
        "approval_status": approval,
        "qualifier": qualifier,
        "last_modified": "2026-05-05T17:41:15.094031+00:00",
        "method_category": None,
    }
    props.update(over)
    return {"properties": props}


def _page(features, next_url=None):
    links = [{"rel": "self", "href": "x"}]
    if next_url:
        links.append({"rel": "next", "href": next_url})
    return {"type": "FeatureCollection", "features": features, "links": links}


def _client():
    return USGSWaterDataClient(api_key="k")


# --- shape -------------------------------------------------------------

def test_emits_full_utc_timestamp_not_midnight():
    # realtime_15min keeps sub-daily resolution; the midnight-UTC rule is
    # daily_mean only.
    page = _page([_feature("2026-11-15T18:15:00+00:00", "47300")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert len(obs) == 1
    assert obs[0]["observed_at"] == datetime(2026, 11, 15, 18, 15, tzinfo=UTC)
    assert obs[0]["observed_at"].tzinfo is not None


def test_obs_dict_shape():
    page = _page([_feature("2026-11-15T18:15:00+00:00", "47300")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert set(obs[0]) == {
        "observed_at", "discharge", "unit", "type", "quality_code"}
    assert obs[0]["unit"] == "cfs"
    assert obs[0]["type"] == "realtime_15min"
    assert obs[0]["discharge"] == 47300.0
    assert isinstance(obs[0]["discharge"], float)


# --- the silent-truncation trap ---------------------------------------

def test_always_sends_an_explicit_datetime_range():
    # Omitting `datetime` makes the API return only the last ~1 year, which
    # would silently truncate a historical pull.
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC))

    assert "datetime" in g.call_args.kwargs["params"]


def test_requests_the_continuous_collection_and_statistic_00011():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2026, 11, 2, tzinfo=UTC))

    url = g.call_args.args[0] if g.call_args.args else g.call_args.kwargs["url"]
    params = g.call_args.kwargs["params"]
    assert "/continuous/items" in url
    assert params["parameter_code"] == "00060"
    assert params["statistic_id"] == CONTINUOUS_STATISTIC_ID == "00011"


def test_end_date_defaults_to_now_not_omitted():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous("12200500", datetime(2026, 11, 1, tzinfo=UTC))

    assert "datetime" in g.call_args.kwargs["params"]


# --- windowing ---------------------------------------------------------

def test_long_range_is_split_into_windows():
    # A year of 15-minute data is ~35,040 points; several years in one
    # request would exceed the 50,000 cap, so the range must be chunked.
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2023, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC))

    assert g.call_count > 1, "a 3-year range must be split into windows"
    sent = [c.kwargs["params"]["datetime"] for c in g.call_args_list]
    assert len(set(sent)) == len(sent), "windows must not repeat"


def test_short_range_is_a_single_request():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2026, 11, 1, tzinfo=UTC),
            datetime(2026, 11, 8, tzinfo=UTC))

    assert g.call_count == 1


def test_windows_cover_the_whole_range_without_gaps():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))) as g:
        _client().get_instantaneous(
            "12200500", datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 7, 1, tzinfo=UTC))

    spans = [c.kwargs["params"]["datetime"] for c in g.call_args_list]
    starts = [s.split("/")[0] for s in spans]
    ends = [s.split("/")[1] for s in spans]
    assert starts[0].startswith("2024-01-01")
    assert ends[-1].startswith("2025-07-01")
    for earlier_end, later_start in zip(ends, starts[1:]):
        assert later_start >= earlier_end, "windows must not leave a gap"


# --- dedupe ------------------------------------------------------------

def test_duplicate_timestamps_collapse_to_one():
    # Two rows sharing (station, observed_at, type) would break the upsert
    # with "ON CONFLICT DO UPDATE cannot affect row a second time".
    page = _page([
        _feature("2026-11-15T18:15:00+00:00", "47300"),
        _feature("2026-11-15T18:15:00+00:00", "47400", **{"time_series_id": "ts-2"}),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert len(obs) == 1
    stamps = [o["observed_at"] for o in obs]
    assert len(set(stamps)) == len(stamps)


def test_dedupe_is_deterministic_across_calls():
    page = _page([
        _feature("2026-11-15T18:15:00+00:00", "47300"),
        _feature("2026-11-15T18:15:00+00:00", "47400", **{"time_series_id": "ts-2"}),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        a = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))
        b = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert [o["discharge"] for o in a] == [o["discharge"] for o in b]


# --- provenance --------------------------------------------------------

@pytest.mark.parametrize("override", [
    {"monitoring_location_id": "USGS-99999999"},
    {"parameter_code": "00065"},
    {"statistic_id": "00003"},
    {"unit_of_measure": "m^3/s"},
])
def test_server_ignoring_a_filter_raises(override):
    # OGC servers commonly ignore unrecognised query params; without this
    # guard a renamed filter would write another series in as discharge.
    page = _page([_feature("2026-11-15T18:15:00+00:00", "47300", **override)])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        with pytest.raises(USGSWaterDataError):
            _client().get_instantaneous(
                "12200500", datetime(2026, 11, 15, tzinfo=UTC),
                datetime(2026, 11, 16, tzinfo=UTC))


# --- values and errors -------------------------------------------------

def test_null_and_unparseable_values_are_skipped():
    page = _page([
        _feature("2026-11-15T18:15:00+00:00", "47300"),
        _feature("2026-11-15T18:30:00+00:00", None),
        _feature("2026-11-15T18:45:00+00:00", "not-a-number"),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert len(obs) == 1


def test_negative_values_are_retained():
    # Negative instantaneous flow is real at tidal and canal sites; the
    # daily path already retains it.
    page = _page([_feature("2026-11-15T18:15:00+00:00", "-120.5")])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert obs[0]["discharge"] == -120.5


def test_quality_code_mapping_matches_the_daily_path():
    page = _page([_feature("2026-11-15T18:15:00+00:00", "47300",
                           approval="Provisional", qualifier=["ESTIMATED"])])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert obs[0]["quality_code"] == "P, e"
    assert len(obs[0]["quality_code"]) <= 10


def test_429_is_transient():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=429)):
        with pytest.raises(USGSWaterDataTransientError):
            _client().get_instantaneous(
                "12200500", datetime(2026, 11, 15, tzinfo=UTC),
                datetime(2026, 11, 16, tzinfo=UTC), _retries=0)


def test_404_is_permanent():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse({}, status_code=404)):
        with pytest.raises(USGSWaterDataError):
            _client().get_instantaneous(
                "12200500", datetime(2026, 11, 15, tzinfo=UTC),
                datetime(2026, 11, 16, tzinfo=UTC), _retries=0)


def test_empty_result_is_an_empty_list():
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(_page([]))):
        assert _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC)) == []


def test_results_are_sorted_by_timestamp():
    page = _page([
        _feature("2026-11-15T18:45:00+00:00", "3"),
        _feature("2026-11-15T18:15:00+00:00", "1"),
        _feature("2026-11-15T18:30:00+00:00", "2"),
    ])
    with patch("src.acquisition.usgs_waterdata_client.requests.get",
               return_value=_FakeResponse(page)):
        obs = _client().get_instantaneous(
            "12200500", datetime(2026, 11, 15, tzinfo=UTC),
            datetime(2026, 11, 16, tzinfo=UTC))

    assert [o["discharge"] for o in obs] == [1.0, 2.0, 3.0]


@pytest.mark.integration
def test_live_continuous_returns_recent_points():
    from datetime import datetime as _dt
    end = _dt.now(UTC)
    obs = USGSWaterDataClient().get_instantaneous(
        "12200500", end - timedelta(days=3), end)
    assert len(obs) > 100, f"expected ~288 points for 3 days, got {len(obs)}"
    assert all(o["type"] == "realtime_15min" for o in obs)
    assert all(o["unit"] == "cfs" for o in obs)
    stamps = [o["observed_at"] for o in obs]
    assert len(set(stamps)) == len(stamps), "live data must have unique stamps"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_usgs_waterdata_instantaneous.py -v -k "not live"`
Expected: `ImportError` on `CONTINUOUS_STATISTIC_ID`, or `AttributeError` for the missing method.

- [ ] **Step 4: Implement `get_instantaneous`**

Add to `src/acquisition/usgs_waterdata_client.py`:

```python
CONTINUOUS_STATISTIC_ID = "00011"

# A 15-minute series is ~35,040 points per year and `limit` caps at 50,000,
# so a multi-year request must be split. 180 days is ~17,280 points, which
# leaves generous headroom even where the series is denser than 15 minutes.
INSTANTANEOUS_WINDOW_DAYS = 180
```

Implement the method to:
1. Default `end_date` to `datetime.now(timezone.utc)` when `None`.
2. Split `start_date .. end_date` into consecutive windows of at most
   `INSTANTANEOUS_WINDOW_DAYS`, covering the range with no gap and no overlap,
   and issue one paginated fetch per window with an **explicit** `datetime`
   parameter formatted `"{start}/{end}"`.
3. Request collection `continuous` with `parameter_code=DISCHARGE_PARAMETER_CODE`,
   `statistic_id=CONTINUOUS_STATISTIC_ID`, `limit=PAGE_LIMIT`, `skipGeometry="true"`.
4. Apply the **same provenance check** the daily path uses, with the expected
   `statistic_id` being `00011` — skip-and-count mismatches and raise
   `USGSWaterDataError` if the count is nonzero.
5. Parse each feature into the five-key dict, with `observed_at` as a
   timezone-aware UTC `datetime` parsed from the full ISO `time` string
   (convert to UTC if the offset differs; never drop the time component),
   `discharge` as `float`, `unit="cfs"`, `type="realtime_15min"`, and
   `quality_code` from `build_quality_code`.
6. Skip features whose `value` is `None` or unparseable, logging a warning.
7. Dedupe by exact `observed_at`, deterministically — sort by
   `(observed_at, time_series_id)` and keep the first — logging a WARNING
   naming the station and the duplicate count, mirroring the daily path.
8. Return the list sorted by `observed_at`.

Use the ISO parser for the timestamp; `datetime.fromisoformat` handles the
`+00:00` offset the API emits. Do not use `strptime` with a hardcoded format.

Do not change `get_daily_mean`, and do not alter any existing test.

- [ ] **Step 5: Run the mocked tests**

Run: `venv/bin/python -m pytest tests/test_usgs_waterdata_instantaneous.py -v -k "not live"`
Expected: all pass.

- [ ] **Step 6: Run the daily-mean suite unchanged**

Run: `venv/bin/python -m pytest tests/test_usgs_waterdata_client.py -v`
Expected: all pass, file unmodified. If anything there fails, the shared internals were changed in a way that altered daily behaviour — stop and report.

- [ ] **Step 7: Verify against the live API**

Run: `venv/bin/python -m pytest tests/test_usgs_waterdata_instantaneous.py::test_live_continuous_returns_recent_points -v`
Expected: passes, roughly 288 points for three days. Never print the API key.

- [ ] **Step 8: Commit**

```bash
git add src/acquisition/usgs_waterdata_client.py tests/test_usgs_waterdata_instantaneous.py
git commit -m "feat: fetch instantaneous discharge from the Water Data continuous collection"
```

---

### Task 2: Route `realtime_15min` to the new client

**Files:**
- Modify: `src/acquisition/tasks.py`
- Test: `tests/test_usgs_realtime_routing.py`

**Interfaces:**
- Consumes: `USGSWaterDataClient.get_instantaneous` (Task 1).
- Produces: `_process_single_station` sends `realtime_15min` to the new client. `daily_mean` routing is unchanged.

After this the legacy `USGSClient` is no longer used for either observation
type in the scheduled path. It remains imported by
`src/acquisition/historical_population.py`, which is a separate concern — do
not touch it, but state in your report that it is still on the legacy client.

- [ ] **Step 1: Read the branch and the existing routing test**

Read the USGS branch of `_process_single_station` in `src/acquisition/tasks.py` and `tests/test_usgs_daily_mean_routing.py`. The existing test patches `src.acquisition.usgs_client.USGSClient.get_instantaneous` and asserts realtime goes there — **that assertion is about to become wrong**, so it must be updated. This is the one existing test you may change, and only for this reason. Record the before/after in your report.

- [ ] **Step 2: Write the failing test**

Create `tests/test_usgs_realtime_routing.py`:

```python
"""realtime_15min must come from the Water Data `continuous` collection.

The feature currently stores no rows — the data was removed under storage
pressure and will return for a few dozen stations — so this routing is
verified by behaviour, not by stored data.
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

NEW_INSTANT = "src.acquisition.tasks.USGSWaterDataClient.get_instantaneous"
NEW_DAILY = "src.acquisition.tasks.USGSWaterDataClient.get_daily_mean"
LEGACY_INSTANT = "src.acquisition.usgs_client.USGSClient.get_instantaneous"


@pytest.fixture
def station(db):
    return Station.objects.create(
        station_number="12200500", name="Skagit", agency="USGS", is_active=True
    )


def _config(data_type):
    return PullConfiguration.objects.create(
        name=f"Test {data_type}",
        data_source="USGS",
        data_type=data_type,
        data_strategy="append",
        schedule_type="custom",
        schedule_value="*/15 * * * *",
        pull_start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )


def _cs(config, station):
    return PullConfigurationStation.objects.create(
        configuration=config, station_number=station.station_number,
        station_name=station.name,
    )


def test_realtime_routes_to_the_new_client(station):
    config = _config("realtime_15min")
    cs = _cs(config, station)

    with patch(NEW_INSTANT, return_value=[]) as new, \
         patch(LEGACY_INSTANT, return_value=[]) as legacy:
        result = _process_single_station(cs, config.id, config)

    assert new.called, "realtime_15min must use USGSWaterDataClient"
    assert not legacy.called, "the legacy NWIS path must no longer be used"
    assert result["success"] is True


def test_daily_mean_still_routes_to_the_new_client(station):
    config = _config("daily_mean")
    cs = _cs(config, station)

    with patch(NEW_DAILY, return_value=[]) as daily, \
         patch(NEW_INSTANT, return_value=[]) as instant:
        result = _process_single_station(cs, config.id, config)

    assert daily.called
    assert not instant.called
    assert result["success"] is True


def test_realtime_receives_the_smart_append_window(station):
    config = _config("realtime_15min")
    cs = _cs(config, station)

    with patch(NEW_INSTANT, return_value=[]) as new:
        _process_single_station(cs, config.id, config)

    kwargs = new.call_args.kwargs
    assert kwargs["station_number"] == "12200500"
    assert kwargs["start_date"] is not None
    assert kwargs["end_date"] is not None


def test_realtime_is_not_given_the_180_day_rewind(station):
    # Gating the rewind to daily_mean/ec_realtime_daily is load-bearing:
    # otherwise every realtime config would re-pull 180 days of 15-minute
    # data on every 5-minute dispatch.
    from src.acquisition.smart_append import REFETCH_WINDOW_DATA_TYPES

    assert "realtime_15min" not in REFETCH_WINDOW_DATA_TYPES
```

- [ ] **Step 3: Run to verify failure**

Run: `venv/bin/python -m pytest tests/test_usgs_realtime_routing.py -v`
Expected: `test_realtime_routes_to_the_new_client` fails — the legacy client is still called.

- [ ] **Step 4: Route the branch**

In `src/acquisition/tasks.py`, change only the `realtime_15min` call so it uses
`USGSWaterDataClient().get_instantaneous(...)` with the same keyword-argument
style (`station_number=`, `start_date=`, `end_date=`). Leave the `daily_mean`
branch, the trailing unknown-`data_type` `else`, and every other agency branch
exactly as they are.

If the `client = USGSClient()` line becomes unused in that branch, leave the
import in place — `tests/test_usgs_daily_mean_routing.py` patches it by that
module's dotted path, and removing it would break a pinned patch target. Add a
`# noqa: F401`-style comment explaining that, matching the convention already
used in `backfill_usgs_observations.py`.

- [ ] **Step 5: Update the one stale assertion**

In `tests/test_usgs_daily_mean_routing.py`, the test asserting realtime uses the
legacy client is now wrong. Update it to assert realtime uses
`USGSWaterDataClient.get_instantaneous`, keeping every other assertion in that
file intact. Rename it if the name claims "legacy". Say exactly what you changed.

- [ ] **Step 6: Run the tests**

Run: `venv/bin/python -m pytest tests/test_usgs_realtime_routing.py tests/test_usgs_daily_mean_routing.py tests/test_usgs_waterdata_instantaneous.py -v -k "not live"`
Expected: all pass.

- [ ] **Step 7: Confirm GUI and API still expose the feature**

The feature must stay configurable and readable. Verify and record the evidence:

```bash
venv/bin/python -c "
import os,django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from apps.streamflow.models import PullConfiguration
print('data_type choices:', [c[0] for c in PullConfiguration._meta.get_field('data_type').choices])
"
grep -n "filterset_fields" apps/api/views/observation.py
```

Expected: `realtime_15min` is among the choices, and `type` is in
`filterset_fields` so `/api/v1/observations/?type=realtime_15min` works. Also
check the configuration form template or `apps/streamflow/forms.py` does not
filter the choice list down to `daily_mean`; report what you find. Change
nothing here unless you find the choice is actually unavailable — if so, stop
and report rather than fixing it.

- [ ] **Step 8: Commit**

```bash
git add src/acquisition/tasks.py tests/test_usgs_realtime_routing.py tests/test_usgs_daily_mean_routing.py
git commit -m "feat: route realtime_15min pulls through the Water Data continuous collection"
```

---

## Self-Review

**Coverage.** Task 1 provides the new fetch path; Task 2 routes to it. Together they remove the legacy NWIS dependency from both observation types in the scheduled pull.

**Deliberately out of scope**, to be surfaced to the user:
- `src/acquisition/historical_population.py` still calls the **legacy**
  `USGSClient.get_daily_mean` and is reachable via
  `manage.py populate_usgs_historical`. It also bulk-inserts while bypassing
  `validate_observations`. It looks largely superseded by
  `backfill_usgs_observations`. A decision on migrating versus retiring it is
  pending with the user.
- `apps/streamflow/management/commands/load_master_stations.py` uses
  `nwis.get_info` for **site metadata**, not observations — a different dataset
  and a separate migration.
- No backfill of historical 15-minute data is included. The table holds no
  `realtime_15min` rows today, and re-populating it is gated on the user's
  storage work. The new client supports historical windows when that happens.

**Risk notes.**
- The sharpest trap is the API's silent one-year truncation when `datetime` is
  omitted. `test_always_sends_an_explicit_datetime_range` and the windowing
  tests pin it.
- Second is duplicate timestamps breaking the upsert on
  `(station, observed_at, type)`; pinned by the dedupe tests.
- Third is accidentally applying the midnight-UTC rule, which belongs to
  `daily_mean` only; pinned by `test_emits_full_utc_timestamp_not_midnight`.
- Reusing the daily client's internals risks changing daily behaviour, so Task 1
  Step 6 runs the daily suite unmodified as the regression gate.
