"""Backfill BasinForcing table from CAMELS Daymet forcing files.

Reads CAMELS Daymet files for the 37 ealstm_available stations and bulk-inserts
into the BasinForcing table with source='daymet'. Skips rows that already exist.

Usage:
    cd /home/streamflow/streamflow-dataOps/streamflow-dataOps
    python backfill_basin_forcings.py
"""

import os
import sys
import glob
import django
import logging
import pandas as pd
from pathlib import Path
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, str(Path(__file__).resolve().parent))
django.setup()

from apps.streamflow.models import BasinForcing, Station  # noqa: E402

CAMELS_BASE = Path("/home/geoskimoto/projects/precip-runoff-models/data/raw/camels_us/basin_dataset_public_v1p2/basin_mean_forcing/daymet")
RESID_CAST_CONFIG = Path("/home/geoskimoto/projects/usgs-streamflow-dashboard/config/resid_cast_stations.json")
BATCH_SIZE = 5000


def load_ealstm_station_ids() -> list[str]:
    import json
    with open(RESID_CAST_CONFIG) as f:
        cfg = json.load(f)
    return sorted(k for k, v in cfg.items() if v.get("ealstm_available"))


def find_camels_file(usgs_id: str) -> Path | None:
    matches = glob.glob(str(CAMELS_BASE / "**" / f"{usgs_id}_lump_cida_forcing_leap.txt"), recursive=True)
    return Path(matches[0]) if matches else None


def read_camels_forcing(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=r"\s+", skiprows=3, header=0)
    df.columns = df.columns.str.strip()
    rename = {
        "dayl(s)": "dayl_s",
        "prcp(mm/day)": "prcp_mm_day",
        "srad(W/m2)": "srad_w_m2",
        "tmax(C)": "tmax_c",
        "tmin(C)": "tmin_c",
        "vp(Pa)": "vp_pa",
    }
    df = df.rename(columns=rename)
    df["date"] = pd.to_datetime(df[["Year", "Mnth", "Day"]].rename(columns={"Year": "year", "Mnth": "month", "Day": "day"}))
    return df[["date", "prcp_mm_day", "tmax_c", "tmin_c", "srad_w_m2", "vp_pa", "dayl_s"]].copy()


def backfill_station(usgs_id: str) -> dict:
    camels_path = find_camels_file(usgs_id)
    if camels_path is None:
        logger.warning("No CAMELS file for %s — skipping", usgs_id)
        return {"status": "skipped", "rows": 0}

    try:
        station = Station.objects.get(station_number=usgs_id, agency="USGS")
    except Station.DoesNotExist:
        logger.warning("Station %s not in StreamflowOps DB — skipping", usgs_id)
        return {"status": "skipped", "rows": 0}

    existing_dates = set(
        BasinForcing.objects.filter(station=station, source="daymet").values_list("date", flat=True)
    )

    df = read_camels_forcing(camels_path)
    df = df[~df["date"].dt.date.isin(existing_dates)]

    if df.empty:
        logger.info("%s: already fully backfilled (%d existing rows)", usgs_id, len(existing_dates))
        return {"status": "ok", "rows": 0}

    objs = [
        BasinForcing(
            station=station,
            date=row["date"].date(),
            prcp_mm_day=row["prcp_mm_day"],
            tmax_c=row["tmax_c"],
            tmin_c=row["tmin_c"],
            srad_w_m2=row["srad_w_m2"],
            vp_pa=row["vp_pa"],
            dayl_s=row["dayl_s"],
            source="daymet",
        )
        for _, row in df.iterrows()
    ]

    inserted = 0
    for i in range(0, len(objs), BATCH_SIZE):
        batch = objs[i:i + BATCH_SIZE]
        BasinForcing.objects.bulk_create(batch, ignore_conflicts=True)
        inserted += len(batch)

    logger.info("%s: inserted %d rows (had %d existing)", usgs_id, inserted, len(existing_dates))
    return {"status": "ok", "rows": inserted}


def main():
    station_ids = load_ealstm_station_ids()
    logger.info("Backfilling %d stations from CAMELS Daymet forcings", len(station_ids))

    total_inserted = 0
    skipped = 0

    for usgs_id in station_ids:
        result = backfill_station(usgs_id)
        if result["status"] == "skipped":
            skipped += 1
        else:
            total_inserted += result["rows"]

    logger.info("Done. Inserted %d total rows. Skipped %d stations.", total_inserted, skipped)


if __name__ == "__main__":
    main()
