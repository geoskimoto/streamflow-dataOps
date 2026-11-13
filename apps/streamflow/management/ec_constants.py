"""Constants shared by the Environment Canada observation commands.

``backfill_ec_observations`` and ``audit_ec_observations`` both need the
same full-record sentinel date, and the two must always agree: the audit
compares exactly the span the backfill wrote, so a sentinel that drifted
apart between them would make the audit judge a window the backfill never
filled. Defining it once here removes that failure mode - neither the
shared ``backfill_runner`` nor ``audit_runner`` is the right home, since
it is agency-specific, and ``gage_lists`` is about station selection.
"""

from datetime import datetime, timezone

# CanadaClient.get_daily_mean() requires a non-None start_date - unlike the
# USGS client, it has no "full record" shorthand - so both EC commands pass
# this sentinel instead of None when the caller wants the whole record.
EC_EARLIEST_START = datetime(1850, 1, 1, tzinfo=timezone.utc)
