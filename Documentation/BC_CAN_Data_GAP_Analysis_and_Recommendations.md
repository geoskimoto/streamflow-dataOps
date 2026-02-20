  1 # BC CAN Historical Backfill — Data Gap Analysis
   2
   3 **Date:** 2026-02-20
   4 **Configuration:** BC CAN Historical Backfill (One-Time) (ID: 4)
   5
   6 ## Issue
   7
   8 All BC Environment Canada stations show a last data point of 2024-12-31 in the database. An investigation was conducted to determine whe
     ther this was caused by a misconfiguration or an upstream data limitation.
   9
  10 ## Findings
  11
  12 ### Data Gap Confirmed
  13
  14 - **307 of 771** EC stations with data have their last observation on **2024-12-31**.
  15 - A handful of stations extend to 2025-01-01 or 2025-01-02, but the vast majority stop at year-end 2024.
  16 - Total EC records in the database: **11,629,855** (dating back to 1901).
  17
  18 ### Configuration Is Correct
  19
  20 The end date is **not** hardcoded to 12/31/2024. In `src/acquisition/tasks.py`, the end date is set dynamically:
  21
  22 ```python
  23 end_date = datetime.now(timezone.utc)
  24 ```
  25
  26 The `CanadaClient.get_daily_mean()` method also defaults to "now" when no end date is provided. The configuration's `pull_start_date` is
      `1900-01-01` (appropriate for a full historical backfill), and the backfill itself ran successfully on 2026-02-18, inserting 11.6M reco
     rds.
  27
  28 ### Root Cause: Environment Canada HYDAT Publication Lag
  29
  30 The `hydrometric-daily-mean` API collection is actually the **"Hydrometric Historical Data (HYDAT)"** dataset — Environment Canada's arc
     hival, quality-assured database. It is **not** a real-time feed.
  31
  32 Evidence from direct API queries on 2026-02-20:
  33
  34 | Station | Last Record With Discharge Data |
  35 |---|---|
  36 | 08MF005 (Fraser River) | 2024-12-31 |
  37 | 07FB001 (Pine River at East Pine) | 2024-12-31 |
  38 | 08EE008 (Goathorn Creek near Telkwa) | 2025-01-02 |
  39
  40 Records after these dates exist for some stations but contain `Discharge: None` (placeholder rows without validated data). HYDAT is publ
     ished on a **quarterly or semi-annual schedule**, and the current release only contains validated data through approximately year-end 20
     24.
  41
  42 ### Smart Append State
  43
  44 The `PullStationProgress` table correctly tracks the last successful pull date per station. When new HYDAT data becomes available, re-ru
     nning the backfill config will resume from where each station left off — no duplicate data will be pulled.
  45
  46 ## Recommendations
  47
  48 ### 1. Create a Recurring EC Realtime Pull Configuration
  49
  50 To bridge the gap between HYDAT releases, create a new `PullConfiguration` targeting the `hydrometric-realtime` collection:
  51
  52 - **Data source:** EC
  53 - **Data type:** `realtime_15min`
  54 - **Strategy:** append
  55 - **Schedule:** Every 4–6 hours
  56 - **Stations:** Active BC stations (or a prioritized subset)
  57
  58 The realtime endpoint provides near-real-time 15-minute discharge data with a rolling window (typically the last 30 days). This would ke
     ep the database current between HYDAT publications.
  59
  60 ### 2. Re-run the Historical Backfill After Next HYDAT Release
  61
  62 When Environment Canada publishes the next HYDAT update:
  63
  64 1. Re-enable configuration ID 4 (`is_enabled: True`).
  65 2. Trigger a manual run — Smart Append will pick up from each station's last successful date (2024-12-31 for most).
  66 3. Disable the config again after completion.
  67
  68 ### 3. Monitor HYDAT Release Schedule
  69
  70 Environment Canada publishes HYDAT updates at: https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/
  71
  72 Consider adding a periodic check (manual or automated) to detect when new HYDAT data becomes available so the backfill can be re-trigger
     ed promptly.
