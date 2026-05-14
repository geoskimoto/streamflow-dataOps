# NOAA NWPS API — Forecast Products Reference

**Investigated:** 2026-04-29  
**Swagger UI:** https://api.water.noaa.gov/nwps/v1/docs  
**Test station:** WTLO3 (S. Santiam River at Waterloo, OR) / USGS 14187500 / reach 23785687

---

## Summary of Findings

The NOAA National Water Prediction Service (NWPS) API exposes two distinct forecast families:

1. **Gauge-based** — NWRFC CHPS deterministic forecasts, keyed by NWS LID or USGS station ID
2. **Reach-based** — National Water Model (NWM) ensemble and deterministic forecasts, keyed by NWM reach ID

---

## Gauge-Based Endpoints (NWRFC CHPS Deterministic)

Base: `https://api.water.noaa.gov/nwps/v1/gauges/{identifier}`

`{identifier}` accepts either the NWS LID (e.g. `WTLO3`) or the USGS station ID (e.g. `14187500`).

| Endpoint | Description | Coverage |
|---|---|---|
| `GET /gauges/{id}` | Gauge metadata: lat/lon, reach ID, RFC/WFO, flood categories, SHEF pedts codes | — |
| `GET /gauges/{id}/stageflow` | Combined observed + forecast in one response | See below |
| `GET /gauges/{id}/stageflow/observed` | Recent observed stage/flow | ~30 days of obs (~8,500 pts) |
| `GET /gauges/{id}/stageflow/forecast` | NWRFC deterministic forecast | **~10 days, 6-hourly** (see note) |
| `GET /gauges/{id}/ratings` | Stage–flow rating curve | Up to 10,000 records |
| `GET /products/stageflow/{id}/{pedts}` | Specific SHEF product by pedts code | e.g. `HGIFZ` (fcst), `HGIRG` (obs) |

### Forecast units
- `primary` = stage in **ft**
- `secondary` = flow in **kcfs** (multiply × 1000 to get CFS)

### Actual forecast length observed
The NWPS public API returns ~10 days (40 points, 6-hourly) for the CHPS deterministic forecast. However, **StreamflowOps is currently storing only ~8 days** (31 points) per run in `forecast_runs`. The ingestion pipeline appears to be truncating the last ~2 days of the available product.

---

## Reach-Based Endpoints (National Water Model)

Base: `https://api.water.noaa.gov/nwps/v1/reaches/{reachId}`

`{reachId}` is the NWM reach ID — available from the gauge metadata endpoint above.

| `?series=` | NWM Product | Points | Temporal span | Resolution | Members |
|---|---|---|---|---|---|
| `analysis_assimilation` | Recent analysis | ~61 | ~2.5 days (recent past) | Hourly | 1 |
| `short_range` | Short-range forecast | ~18 | **~18 hours** | Hourly | 1 |
| `medium_range` | Medium-range ensemble | ~204–240 | **~8.5–10 days** | Hourly | 6 members + mean |
| `long_range` | Long-range ensemble | ~120 | **~30 days** | 6-hourly | 4 members + mean |
| `medium_range_blend` | Blended deterministic | ~240 | **10 days** | Hourly | 1 (blended) |

### NWM units
- Flow field is `flow` in **ft³/s (CFS)** — no unit conversion needed.

### Response structure (medium_range example)
```json
{
  "mediumRange": {
    "mean":    { "referenceTime": "...", "units": "ft³/s", "data": [{validTime, flow}, ...] },
    "member1": { ... },
    "member2": { ... },
    ...
  }
}
```

---

## Current Dashboard State vs. What's Available

| Product | Available from API | Currently used in dashboard |
|---|---|---|
| NWRFC CHPS deterministic (~10 days, 6-hr) | Yes | Yes — but StreamflowOps stores only ~8 days |
| NWM medium_range_blend (10 days, hourly) | Yes | No |
| NWM medium_range ensemble (10 days, 6 members) | Yes | No |
| NWM long_range ensemble (30 days, 4 members) | Yes | No |
| NWM short_range (18 hours) | Yes | No |

---

## ResidCast Model Horizon

ResidCast correction models (MuTHRE, XGBoost, LSTM) are trained and evaluated on **lead_day 0–5 only** (6 daily lead days), regardless of the underlying NWRFC forecast length. This is set in `resid-cast/config.py`:

```python
FORECAST_HORIZON: int = 6    # lead_day 0–5
```

Extending ResidCast to cover the full 10-day forecast horizon would require retraining all models.

---

## Reach ID Lookup

The NWM reach ID for a gauge is returned by the gauge metadata endpoint:

```bash
curl https://api.water.noaa.gov/nwps/v1/gauges/WTLO3
# → "reachId": "23785687"
```
