# Percentile Systems Comparison: Old vs. New Analytics

## Old System: Operational Percentile Ranking

### `DailyFlowPercentile` — `src/analytics/tasks.py` + `src/analytics/percentiles.py`

- **What it computes:** For each observed discharge value, computes that value's *rank* against the full period-of-record (0–100 percentile) and assigns it a categorical band (p0_4, p5_10, etc.)
- **Granularity:** One row per station per date — updated 3×/day
- **Purpose:** Real-time event classification — "today's flow at station X is at the 72nd percentile of historical record"
- **Schedule:** Beat-driven at 06:00, 12:00, 18:00 UTC daily
- **Minimum threshold:** 30 historical records required per station before computing

### `ForecastPercentile` — `src/analytics/tasks.py` + `src/analytics/percentiles.py`

- **What it computes:** For each NOAA RFC forecast value (1–8 days ahead), computes the forecast discharge's rank against the same full period-of-record baseline
- **Granularity:** One row per (station, target_date, source) — updated every 6h
- **Purpose:** Forecast context — "the forecast flow for Thursday is at the 85th percentile"
- **Translation:** Maps NOAA_RFC stations to USGS stations via `StationMapping` before computing
- **Schedule:** Beat-driven every 6h at 00:00, 06:00, 12:00, 18:00 UTC

---

## New System: Static Reference Statistics

### `StationMetadata` — `src/analytics/station_metadata.py`

- **What it computes:** The fixed *quantile values themselves* in cfs (Q10, Q25, Q50, Q75, Q90) using PostgreSQL `PERCENTILE_CONT` — aggregated once across the entire period of record
- **Granularity:** One row per station (1:1 with Station), refreshed annually by default
- **Purpose:** Reference metadata — "what is the median flow at this station?", years on record, record completeness, last observation date
- **Schedule:** Dispatcher-driven via `StatisticsConfiguration` (default: annual in October); can be monthly, weekly, or custom cron
- **Also stores:** `last_observation_date`, `record_start_date`, `record_end_date`, `years_on_record`, `record_completeness_pct`, `mean_annual_flow_cfs`

---

## Side-by-Side Comparison

| | DailyFlowPercentile | ForecastPercentile | StationMetadata |
|---|---|---|---|
| **What** | Rank of today's observed value | Rank of forecast value | Fixed quantile thresholds |
| **Output** | 0–100 percentile + band | 0–100 percentile + band | Q10/Q25/Q50/Q75/Q90 in cfs |
| **Frequency** | 3×/day | Every 6h | Annual (configurable) |
| **Rows** | Per station per date | Per station per forecast date | Per station (one row, ever) |
| **Use case** | Operational dashboard | Forecast context | Station summaries, API reference |
| **Baseline** | Full period-of-record daily_mean | Full period-of-record daily_mean | Full period-of-record daily_mean |

---

## Key Takeaways

**Same baseline, different questions:**
All three use the same source data — full period-of-record `daily_mean` discharge observations from `discharge_observations`. But they answer different questions:

- Old system: *"Where does today's (or tomorrow's forecast) flow sit in the historical distribution?"* → produces a rank/band per event
- New system: *"What are the characteristic flow thresholds at this station?"* → produces fixed reference values

**They supplement each other, not replace:**
- `DailyFlowPercentile` is operational — it runs continuously and classifies every new observation
- `StationMetadata` is reference — it is the lookup table that *defines* what Q10, Q50, Q90 actually are in cfs at each station

**No conflict or duplication:** Different tables, different structure, no mutual dependencies.

**The missing link — `percentile_backfill`:**
`StatisticsConfiguration` has a `computation_type='percentile_backfill'` option that is currently unimplemented (dispatcher logs a warning and skips it). This is where the two systems could eventually be connected — using `StationMetadata` Q-values to backfill or recalculate the band assignments in `DailyFlowPercentile` when the period-of-record changes significantly.
