"""
Independent end-to-end validation of the committed iter_forecast_runs against
the real archive. Read-only; writes nothing to the database or the parquet.

Measured by streaming the implemented iter_forecast_runs over the whole file:
    forecast runs      3,577,182
    distinct LIDs            441
    types    medium    3,559,239
             short         2,021
             long         15,922
    single-point runs         12
    negative-horizon runs     27

Re-run before the import to confirm the archive still matches what the plan
assumes. A straddling bug in the carry-forward buffering would change the run
count, so this doubles as a regression check on iter_forecast_runs.
"""
import os
import sys
from collections import defaultdict

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DB_ENGINE", "sqlite")
sys.path.insert(0, os.getcwd())

import django  # noqa: E402

django.setup()

from src.acquisition.parquet_forecast_importer import iter_forecast_runs  # noqa: E402

PARQUET = "/home/geoskimoto/projects/resid-cast/all_nwrfc_forecasts_WY2006_2026.parquet"

EXPECTED = {
    "runs": 3_577_182,
    "lids": 441,
    "medium": 3_559_239,
    "short": 2_021,
    "long": 15_922,
    "single_point": 12,
    "negative_horizon": 27,
}

runs = 0
lids = set()
types = defaultdict(int)
single_point = 0
negative_horizon = 0
first = None

from datetime import datetime, timezone  # noqa: E402

for lid, issuance, data, ftype in iter_forecast_runs(PARQUET):
    runs += 1
    lids.add(lid)
    types[ftype] += 1
    if len(data) == 1:
        single_point += 1
    last = datetime.strptime(data[-1]["date"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    if last < issuance:
        negative_horizon += 1
    if first is None:
        first = (lid, issuance.isoformat(), ftype, len(data), data[0], data[-1])
    if runs % 500_000 == 0:
        print(f"  {runs:,} runs streamed…", flush=True)

actual = {
    "runs": runs,
    "lids": len(lids),
    "medium": types["medium"],
    "short": types["short"],
    "long": types["long"],
    "single_point": single_point,
    "negative_horizon": negative_horizon,
}

print("\nfirst run:", first)
print(f"\n{'metric':<18}{'expected':>12}{'actual':>12}   match")
ok = True
for k, exp in EXPECTED.items():
    got = actual[k]
    match = exp == got
    ok = ok and match
    print(f"{k:<18}{exp:>12,}{got:>12,}   {'OK' if match else 'MISMATCH'}")

print("\nRESULT:", "ALL MATCH" if ok else "MISMATCH — investigate before importing")
sys.exit(0 if ok else 1)
