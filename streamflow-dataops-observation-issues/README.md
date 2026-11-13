# StreamflowDataOps: USGS daily-mean observations are incomplete and stale

Found 2026-11-11 while auditing resid-cast's observations. Written for whoever mends
`streamflow-dataOps`. Everything below was measured read-only; nothing in streamflow-dataOps or
`streamflow_db` was changed.

**Short version.** USGS daily means in `streamflow_db` are missing flood peaks at almost every
gage, because the ingest discards any value more than 5 standard deviations from the mean of the
batch it is loading. Separately, once a row is written it is never updated, and the daily pull only
moves forward, so revised and late-published USGS values never arrive. The daily USGS pull has also
been mostly failing or half-failing since July 2026. The dashboard reads this database, so its
observed hydrographs are missing the same peaks.

---

## 1. Flood peaks are discarded by a 5σ outlier filter (the main problem)

**Code.** `src/acquisition/data_processor.py`, `DataProcessor.validate_observations`, lines ~170–186
(since commit `5099642`, 2026-01-17, "Phase 3 COMPLETE: Data Pipeline Integration"):

```python
mean = sum(discharges) / len(discharges)
std_dev = (sum((x - mean) ** 2 for x in discharges) / len(discharges)) ** 0.5
...
if z_score > 5:   # More than 5 standard deviations
    logger.warning(f"Statistical outlier detected: ...")
    continue      # ← the observation is dropped
```

`process_observations(..., validate=True)` is the default and is what the scheduled pulls call
(`src/acquisition/tasks.py:253`). The mean and standard deviation are those **of the batch being
loaded** (one pull's date range for one station).

**Why it drops floods.** Streamflow is heavy-tailed; the largest days of any long record sit well
beyond mean + 5σ. They are real, approved USGS values, not errors.

**Why it looks random.** The cutoff depends on the pull window:
- A long pull (a station's first pull from `pull_start_date`, the one-time "HUC 17 USGS Historical
  Backfill" configuration 8, or a long catch-up after downtime) drops everything above roughly the
  record's mean + 5σ.
- A short daily pull can't drop anything: with n ≤ 26 values no |z| can exceed 5. A flood that arrived
  through ordinary daily pulls is kept.
So at Skagit near Mt Vernon (12200500) 64,000 cfs is missing while 72,600 cfs is present.

**Evidence: the rule reproduces the gaps.** Applying |z| > 5 to each gage's full NWIS record:

| USGS gage | mean + 5σ (cfs) | flagged & missing in DB | missing, not flagged | flagged, present |
|---|---|---|---|---|
| 12200500 Skagit nr Mt Vernon | 63,441 | 110 | 0 | 1 |
| 12144500 Snoqualmie at Snoqualmie Falls | 16,543 | 162 | 0 | 2 |
| 12027500 Chehalis nr Grand Mound | 23,126 | 163 | 0 | 1 |
| 13317000 Salmon at White Bird | 79,885 | 148 | 4 | 1 |
| 12082500 | 3,883 | 184 | 6 | 5 |
| 12340500 Clark Fork above Missoula | 19,082 | 157 | 30 | 5 |

Examples of what's missing (NWIS daily means, approved): 12200500 2021-11-13 → 11-18 = 65,200 /
94,100 / 119,000 / 96,200 / 77,900 cfs; 12144500 2009-01-07/08 = 43,200 / 45,300. On 2009-01-08 only
30 of 97 WA gages in the database have a value, against ~85 on ordinary days.

**Scale (285 gages mapped to NWRFC forecast points, 2026-09-26 snapshot of `streamflow_db`):**
- 46,701 missing gage-days at 274 of 285 gages; 32,275 (69%) are explained by the 5σ rule, at 271 gages.
- At gages with drops, the largest flow in the database is a **median 0.44 of the true NWIS record
  maximum** (12200500: 72,600 vs 142,000 cfs).
- Missing share on each gage's top-1% flow days: median 0.258, vs 0.001 on other days; WA 0.33.
- Confirmed in the live database on 2026-11-12: 12200500 still lacks 2021-11-13 and 11-15 → 11-19.

**Fix.** Remove the z-score test for discharge (keep the existing checks: negative, > 1,000,000 cfs,
missing value). If a plausibility check is wanted, *flag* instead of drop (e.g. a column or a log),
and never use a batch z-score on streamflow.

## 2. Revised values never replace provisional ones

**Code.** Inserts use `bulk_create(..., ignore_conflicts=True)` (`data_processor.py` ~100–105 and
`historical_population.py` ~225–240) against the unique constraint (station, observed_at, type). An
existing row is never updated.

**Effect.** USGS publishes provisional ("P") daily values and revises them for months. The database
keeps the first provisional value forever: **49,523 gage-days at 237 gages differ from NWIS**, median
difference 3.7%, almost all 2025–26 (database code "P" on 48,740 of them). Live check, 2026-09-26 →
11-10: 2,763 of 11,325 recent gage-days already differ.

**Fix.** Upsert (`update_conflicts=True` with `update_fields=["discharge", "quality_code"]`, or
`ON CONFLICT … DO UPDATE`) and re-fetch a rolling window (see 3).

## 3. Values USGS publishes late are never fetched

**Code.** `src/acquisition/smart_append.py`: after the first pull, each pull starts at the station's
`last_successful_pull_date`. Nothing ever re-fetches earlier dates.

**Effect.** Days USGS fills in later (ice-affected or equipment days, published afterwards as
estimated "A, e" / "P, e") are never picked up: about 1,300 missing gage-days in 2025–26 at ordinary
flows (e.g. 12340500 has 30 such days, 2025-09-23 → 2026-03-13), plus blocks such as 14303600
(279 days, 2022) and 14233500 (131 days, 2022–23).

**Fix.** Each scheduled pull re-fetches a rolling window (resid-cast uses the last 180 days) and
upserts it. USGS revises provisional data on that timescale.

## 4. The USGS daily pull has been failing since July 2026

`data_pull_logs`, configuration 9 "USGS Daily Mean Pull" (every 12 h), runs per month
(success / partial / failed):

| | success | partial | failed |
|---|---|---|---|
| Feb–Jun 2026 | 490 | 0 | 23 |
| Jul | 53 | 0 | 71 |
| Aug | 7 | 9 | 101 |
| Sep | 1 | 58 | 1 |
| Oct | 11 | 51 | 0 |
| Nov 1–12 | 6 | 15 | 2 |

Recent errors are undecodable NWIS responses: "Expecting value: line 1 column 1 (char 0)" and
"Received response with content-encoding: gzip, but failed to decode it". Retries mostly catch up
(31 missing gage-days 2026-09-26 → 11-10 at 251 gages), but **34 of the 285 gages have no rows since
July**.

Likely related: `src/acquisition/usgs_client.py` uses `dataretrieval.nwis.get_dv`, i.e. the legacy
USGS WaterServices (`waterservices.usgs.gov`). USGS is moving users to the new Water Data APIs
(`https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items`) and retiring the legacy
services. The new API works well: one request returns a gage's full daily record (12200500: 31,453
days in ~2 s), with `approval_status`, `qualifier` and `last_modified`. Without an API key it answers
HTTP 429 when busy (with `Retry-After`); a free api.data.gov key (`X-Api-Key` header) raises the limit.
Also in `get_daily_mean`: it keeps only the first discharge column (`discharge_cols[0]`), so a gage
returning more than one daily discharge series silently loses the others. The new API's
`time-series-metadata` collection identifies the **primary** series explicitly.

## 5. Smaller items

- 12,854 missing days in long pre-1955 blocks at a few gages (mostly 13266000, 1921–1952).
- The deployed code under `/home/streamflow/streamflow-dataOps/` and the celery logs weren't readable
  from the account used for this audit, so the deployed commit and the "Statistical outlier detected"
  warnings are not confirmed. Grepping the worker logs for that string would confirm issue 1 directly.

## Suggested repair order

1. Remove the 5σ drop (issue 1) and switch inserts to upserts (issue 2).
2. Make the scheduled pull re-fetch a rolling window (issue 3), ideally from the new Water Data API (issue 4).
3. Backfill: re-fetch every gage's full record and upsert it. The lists below say exactly which days
   are missing or stale for the 285 NWRFC-mapped gages; other gages in the database are presumably
   affected the same way.
4. Re-run the audit (below) to confirm no missing days or value differences remain.
5. Anything derived from observations (percentile tables, dashboard statistics, flood-frequency
   products) should be recomputed after the backfill: they were computed on records without peaks.

## Files staged with this report

> **Note (2026-11-13, streamflow-dataOps side).** The two large per-row CSVs are
> **not in git** — they are point-in-time dumps of the 2026-09-26 snapshot and
> fall under this repo's "large data dumps never in git" rule (`.gitignore`:
> `data/backups/`). They live on disk at
> `data/backups/observation-audit-2026-09-26/{missing_days,value_diffs}.csv`.
> `gage_gaps.csv` **is** tracked: it is the per-gage summary of both, and the
> backfill and audit commands read it as their work list.
> Remediation plan:
> `docs/superpowers/plans/2026-11-13-usgs-observation-ingest-remediation.md`

- `gage_gaps.csv` — one row per gage: days in DB vs NWIS, missing, value differences, 5σ cutoff,
  missing explained by the rule, DB max vs NWIS max.
- `missing_days.csv` — one row per missing gage-day (46,701): date, NWIS value, qualifiers, z-score,
  whether the 5σ rule explains it, percentile rank.
- `value_diffs.csv` — one row per gage-day whose DB value differs from NWIS (49,523).
- `audit_observation_gaps.py` — the read-only audit (from resid-cast). Compares `streamflow_db` with NWIS
  for a list of gages: `python audit_observation_gaps.py --dsn "dbname=streamflow_db ..." --gages 12200500 ...`
  (it expects resid-cast's `data/station_crosswalk.parquet` when no `--gages` are given).

## What resid-cast did

resid-cast no longer reads observations from `streamflow_db`: it fetches them from the USGS Water
Data API (`data/usgs_waterdata.py` in resid-cast), keeps every value, and re-fetches the last 180 days
on each run with upserts. Forecasts still come from StreamflowDataOps, whose NWRFC forecast collection
has been reliable.
