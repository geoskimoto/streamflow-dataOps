# NOAA Forecast Products — Current State & Gap Analysis

**Date:** 2026-04-29

---

## What the System Currently Uses

The `NOAAClient` calls the **gauge-based** endpoint:

```
GET https://api.water.noaa.gov/nwps/v1/gauges/{hads_id}/stageflow?forecast={type}
```

This returns **NWRFC CHPS deterministic** forecasts, keyed by HADS/NWS LID. The `ForecastRun.forecast_type` field maps to three values:

| `forecast_type` | NOAA param | Product | Horizon | Resolution |
|---|---|---|---|---|
| `short` | `short` | NWRFC CHPS deterministic | ~18 hours | — |
| `medium` | `medium` | NWRFC CHPS deterministic | ~10 days | 6-hourly |
| `long` | `long` | NWRFC CHPS deterministic | ~30 days | — |

All three types use the same gauge-based endpoint and the same underlying model — NWRFC CHPS deterministic. There are no ensemble or NWM products currently ingested.

**Known truncation bug:** The API returns ~40 points (~10 days) for the medium product, but the current ingestion pipeline stores only ~31 points (~8 days). The last ~2 days of available forecast data are being dropped.

**Historical backfill limitation:** The `RFCForecastPopulationService` in `src/acquisition/rfc_forecast_population.py` explicitly raises a `ValueError` for `forecast_type='long'` — historical backfill of long-range forecasts is blocked at the code level.

---

## What Is NOT Yet Implemented

The NOAA NWPS API also exposes a **reach-based** endpoint for National Water Model (NWM) products:

```
GET https://api.water.noaa.gov/nwps/v1/reaches/{reachId}?series={product}
```

These are keyed by **NWM reach ID** (not HADS/gauge ID). The reach ID for any gauge is returned by:

```
GET https://api.water.noaa.gov/nwps/v1/gauges/{id}   →  "reachId": "23785687"
```

Available NWM products not currently ingested:

| `series=` | Product | Horizon | Resolution | Members |
|---|---|---|---|---|
| `short_range` | NWM short-range | ~18 hours | Hourly | 1 |
| `medium_range` | NWM medium-range ensemble | ~8.5–10 days | Hourly | 6 + mean |
| `medium_range_blend` | NWM blended deterministic | 10 days | Hourly | 1 (blended) |
| `long_range` | NWM long-range ensemble | ~30 days | 6-hourly | 4 + mean |
| `analysis_assimilation` | NWM recent analysis | ~2.5 days past | Hourly | 1 |

---

## `medium_range_blend` in Detail

The most likely candidate for near-term addition. Key characteristics:

- **Single blended deterministic member** — operationally clean, no ensemble handling needed
- **Hourly resolution** vs. 6-hourly for the current NWRFC CHPS medium product — meaningful upgrade for operational use
- **~240 points** over 10 days
- **Flow in CFS** directly — no unit conversion needed (current NWRFC product returns kcfs, requiring ×1000)
- Different station ID system: requires NWM reach ID, not HADS ID

---

## What Would Be Required to Add `medium_range_blend`

1. **Reach ID storage** — Add a `nwm_reach_id` field to `Station` or `MasterStation`, populated via the gauge metadata endpoint. Not all gauges will have a reach ID.

2. **New client method** in `NOAAClient` — A reach-based `get_reach_forecast(reach_id, series)` method separate from the existing gauge-based `get_forecast()`.

3. **Model change** — Either add a new `forecast_type` choice (e.g. `medium_blend`) or use the `source` field to distinguish NWM vs. NWRFC products. The current unique constraint is on `(station, source, run_date, forecast_type)`.

4. **PullConfiguration support** — A new data type option so the scheduler can trigger reach-based pulls alongside existing gauge pulls.

5. **Frontend/API** — The forecast chart and API filtering would need to surface the new type.

---

## Full Product Availability Matrix

| Product | Model | Type | Horizon | In system? |
|---|---|---|---|---|
| `short` (gauge) | NWRFC CHPS | Deterministic | ~18 hr | Yes |
| `medium` (gauge) | NWRFC CHPS | Deterministic | ~10 days | Yes (truncated ~8 days) |
| `long` (gauge) | NWRFC CHPS | Deterministic | ~30 days | Yes (no historical backfill) |
| NWM `short_range` | NWM | Deterministic | ~18 hr | No |
| NWM `medium_range_blend` | NWM | Deterministic blended | 10 days | No |
| NWM `medium_range` | NWM | Ensemble (6 members) | ~10 days | No |
| NWM `long_range` | NWM | Ensemble (4 members) | ~30 days | No |
| NWM `analysis_assimilation` | NWM | Analysis | ~2.5 days past | No |

---

## Outstanding Questions Before Deciding

- How many of the 309 active stations have NWM reach IDs? (Stations without a reach ID cannot use any NWM product.)
- Is the goal to replace the NWRFC CHPS medium/long products with NWM equivalents, supplement them, or run both in parallel?
- Should ensemble members from `medium_range` or `long_range` be stored, or only the blended/mean?
- Fix the existing ~8-day truncation bug on the medium product regardless of other decisions.
- Fix or remove the `ValueError` guard on `long` in `rfc_forecast_population.py` if historical long-range backfill is needed.
