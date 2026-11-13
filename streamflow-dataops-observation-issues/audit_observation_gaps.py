#!/usr/bin/env python
"""Audit streamflow_db daily means against USGS NWIS, per gage (read-only).

For every USGS gage mapped to an NWRFC station (data/station_crosswalk.parquet), compare
the daily-mean record in streamflow_db with the NWIS daily-value service and test whether
the missing days are explained by streamflow-dataOps' ingest filter
(src/acquisition/data_processor.py validate_observations: drop |z| > 5 against the mean and
std of the batch being loaded), applied to the gage's full NWIS record.

Reads: streamflow_db (SELECT only, default DSN "dbname=streamflow_db"), NWIS over HTTPS.
Writes: models_trained/_audit_obs/{gage_gaps.csv, missing_days.csv, value_diffs.csv}.

Usage: .venv/bin/python scripts/audit_observation_gaps.py [--workers 4] [--gages 12200500 ...]
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = os.path.join("models_trained", "_audit_obs")
NWIS = ("https://waterservices.usgs.gov/nwis/dv/?format=json&sites={g}&startDT=1850-01-01"
        "&endDT=2026-09-25&parameterCd=00060&statCd=00003")
logger = logging.getLogger("audit")


def nwis_record(gage: str) -> pd.DataFrame:
    """date, nwis_cfs, qualifiers for the gage's primary daily-mean discharge series."""
    req = urllib.request.Request(NWIS.format(g=gage), headers={"User-Agent": "resid-cast-audit"})
    for attempt in range(4):
        try:
            data = json.load(urllib.request.urlopen(req, timeout=180))
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))
    rows = []
    for k, ts in enumerate(data["value"]["timeSeries"]):
        for block in ts["values"]:
            for v in block["value"]:
                rows.append((v["dateTime"][:10], float(v["value"]), ",".join(v["qualifiers"]), k))
    df = pd.DataFrame(rows, columns=["date", "nwis_cfs", "qual", "series"])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["nwis_cfs"] >= 0]          # -999999 = no value
    return df.sort_values(["date", "series"]).drop_duplicates("date")


def db_record(conn, gage: str) -> pd.DataFrame:
    q = """SELECT (o.observed_at AT TIME ZONE 'UTC')::date AS date, o.discharge::float8 AS db_cfs, o.quality_code
           FROM discharge_observations o JOIN stations s ON s.id = o.station_id
           WHERE s.station_number = %s AND o.type = 'daily_mean' AND o.unit = 'cfs'"""
    df = pd.read_sql(q, conn, params=(gage,))
    df["date"] = pd.to_datetime(df["date"])
    return df.drop_duplicates("date")


def audit(gage: str, nwsli: str, dsn: str) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    with psycopg2.connect(dsn) as conn:
        conn.set_session(readonly=True)
        db = db_record(conn, gage)
        meta = pd.read_sql("SELECT record_start_date, historical_data_populated_at, historical_record_count "
                           "FROM stations WHERE station_number = %s", conn, params=(gage,))
    nw = nwis_record(gage)
    row = {"usgs_id": gage, "nwsli": nwsli, "n_db": len(db), "n_nwis": len(nw)}
    if meta.shape[0]:
        row.update({k: meta.iloc[0][k] for k in meta.columns})
    if nw.empty or db.empty:
        return row, pd.DataFrame(), pd.DataFrame()
    lo, hi = db["date"].min(), db["date"].max()
    m = nw.merge(db, on="date", how="left")
    span = m[(m["date"] >= lo) & (m["date"] <= hi)].copy()
    mu, sd = nw["nwis_cfs"].mean(), nw["nwis_cfs"].std(ddof=0)
    span["z_full"] = (span["nwis_cfs"] - mu) / sd if sd > 0 else 0.0
    span["flag5"] = span["z_full"].abs() > 5
    span["missing"] = span["db_cfs"].isna()
    span["pct_rank"] = span["nwis_cfs"].rank(pct=True)
    have = span[~span["missing"]]
    diff = have[(have["nwis_cfs"] - have["db_cfs"]).abs() > np.maximum(0.5, 0.005 * have["nwis_cfs"])]
    miss = span[span["missing"]]
    row.update({
        "db_first": lo.date(), "db_last": hi.date(), "n_nwis_in_span": len(span), "n_missing": len(miss),
        "n_value_diff": len(diff), "cutoff_5sd": mu + 5 * sd,
        "missing_flagged": int((miss["flag5"]).sum()), "missing_unflagged": int((~miss["flag5"]).sum()),
        "flagged_present": int((have["flag5"]).sum()),
        "missing_median_pct_rank": float(miss["pct_rank"].median()) if len(miss) else np.nan,
        "missing_in_top1pct": int((miss["pct_rank"] >= 0.99).sum()),
        "max_db": float(have["nwis_cfs"].max()) if len(have) else np.nan, "max_nwis": float(span["nwis_cfs"].max()),
        "missing_quals": json.dumps(miss["qual"].value_counts().to_dict()),
    })
    md = miss[["date", "nwis_cfs", "qual", "z_full", "flag5", "pct_rank"]].assign(usgs_id=gage, nwsli=nwsli)
    vd = diff[["date", "nwis_cfs", "db_cfs", "qual", "quality_code"]].assign(usgs_id=gage, nwsli=nwsli)
    return row, md, vd


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--dsn", default="dbname=streamflow_db")
    p.add_argument("--gages", nargs="*")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(OUT, exist_ok=True)
    cw = pd.read_parquet("data/station_crosswalk.parquet")[["nwsli", "usgs_id"]].dropna().drop_duplicates("usgs_id")
    if a.gages:
        cw = cw[cw["usgs_id"].isin(a.gages)]
    rows, mds, vds = [], [], []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(audit, r.usgs_id, r.nwsli, a.dsn): r.usgs_id for r in cw.itertuples()}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                row, md, vd = f.result()
                rows.append(row); mds.append(md); vds.append(vd)
            except Exception as exc:
                rows.append({"usgs_id": futs[f], "error": str(exc)[:200]})
                logger.warning("%s failed: %s", futs[f], exc)
            if i % 25 == 0:
                logger.info("%d/%d gages", i, len(futs))
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "gage_gaps.csv"), index=False)
    pd.concat([m for m in mds if len(m)], ignore_index=True).to_csv(os.path.join(OUT, "missing_days.csv"), index=False)
    pd.concat([v for v in vds if len(v)], ignore_index=True).to_csv(os.path.join(OUT, "value_diffs.csv"), index=False)
    logger.info("=== done: %d gages", len(rows))


if __name__ == "__main__":
    main()
