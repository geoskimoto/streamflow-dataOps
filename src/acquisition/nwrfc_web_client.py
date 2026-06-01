"""NWRFC website scraper for 10-day deterministic forecasts.

Scrapes textPlot.cgi, which returns a PRE block with date/time and
flow values at 6-hour intervals (observed past + 10-day forecast future).
"""

import logging
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.nwrfc.noaa.gov/station/flowplot/textPlot.cgi"
_TIMEOUT = 30  # seconds


class NWRFCWebClient:
    """Scrapes NWRFC textPlot.cgi for 10-day flow forecasts."""

    def fetch(self, lid: str) -> str:
        """GET textPlot.cgi for the given LID. Raises on HTTP error."""
        url = f"{_BASE_URL}?id={lid}&pe=QR"
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.HTTPError as exc:
            raise requests.HTTPError(f"{lid}: {exc}") from exc

    def parse(self, html: str, scrape_time: datetime) -> list[dict]:
        """Parse the HTML response into a list of row dicts.

        Each dict: {"date": "ISO-Z", "value": float_cfs, "is_forecast": bool}

        Rows with missing values ("---") are skipped and logged.
        The page reports flow in KCFS; values are converted to CFS.
        """
        soup = BeautifulSoup(html, "html.parser")
        pre = soup.find("pre")
        if not pre:
            logger.warning("nwrfc_web_client: no <pre> block found in response")
            return []

        rows = []
        # Pattern: MM/DD/YYYY HH:MM  <whitespace>  value_or_dashes
        pattern = re.compile(
            r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+([\d.]+|---)"
        )

        for line in pre.get_text().splitlines():
            m = pattern.search(line)
            if not m:
                continue

            date_str, time_str, val_str = m.group(1), m.group(2), m.group(3)

            if val_str == "---":
                logger.debug("nwrfc_web_client: skipping missing-value row: %s %s", date_str, time_str)
                continue

            try:
                # Page timestamps are UTC — confirmed by NWRFC docs.
                dt = datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %H:%M")
                dt = dt.replace(tzinfo=timezone.utc)
                value_cfs = float(val_str) * 1000.0  # KCFS → CFS
            except (ValueError, OverflowError) as exc:
                logger.warning("nwrfc_web_client: could not parse row '%s': %s", line.strip(), exc)
                continue

            rows.append({
                "date": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "value": value_cfs,
                "is_forecast": dt >= scrape_time,
            })

        return rows

    def fetch_and_parse(self, lid: str) -> list[dict]:
        """Convenience: fetch + parse with now() as the split boundary."""
        scrape_time = datetime.now(tz=timezone.utc)
        html = self.fetch(lid)
        return self.parse(html, scrape_time)
