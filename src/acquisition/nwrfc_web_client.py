"""NWRFC website scraper for 10-day deterministic forecasts.

Scrapes textPlot.cgi, which returns an HTML table with observed (left columns)
and forecast (right columns) data side by side. Timestamps are in PDT/PST.
Values are in CFS.
"""

import logging
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.nwrfc.noaa.gov/station/flowplot/textPlot.cgi"
_TIMEOUT = 30  # seconds

# NWRFC pages report timestamps in Pacific time (PDT=UTC-7 in summer, PST=UTC-8).
# We apply a fixed UTC-7 offset; off by an hour in winter, acceptable for forecasts.
_PDT_OFFSET = timedelta(hours=-7)


def _parse_pdt(dt_str: str) -> datetime | None:
    """Parse 'YYYY-MM-DD HH:MM' as PDT → UTC-aware datetime. Returns None on failure."""
    try:
        naive = datetime.strptime(dt_str.strip(), "%Y-%m-%d %H:%M")
        return naive.replace(tzinfo=timezone(timedelta(hours=-7))).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


class NWRFCWebClient:
    """Scrapes NWRFC textPlot.cgi for 10-day flow forecasts."""

    def fetch(self, lid: str) -> str:
        """GET textPlot.cgi for the given LID. Raises on HTTP error with LID in message."""
        url = f"{_BASE_URL}?id={lid}&pe=QR"
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except requests.HTTPError as exc:
            raise requests.HTTPError(f"{lid}: {exc}") from exc

    def parse(self, html: str, lid: str = "") -> list[dict]:
        """Parse the HTML table response into a list of row dicts.

        The page has a 4-column table: [obs_time, obs_value, fc_time, fc_value].
        Observed and forecast rows are extracted from their respective columns.

        Returns: [{"date": "ISO-Z", "value": float_cfs, "is_forecast": bool}, ...]
        Missing or unparseable values are skipped and logged.
        """
        if "No data was found" in html:
            logger.debug("nwrfc_web_client: no data for %s", lid)
            return []

        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            logger.warning("nwrfc_web_client: no <table> found in response for %s", lid)
            return []

        rows = []
        for tr in table.find_all("tr")[2:]:  # skip header rows 0 and 1
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 2:
                continue

            # Observed column: cells[0] = datetime, cells[1] = value
            if len(cells) >= 2 and cells[0] and cells[1]:
                dt = _parse_pdt(cells[0])
                try:
                    val = float(cells[1].replace(",", ""))
                except (ValueError, AttributeError):
                    val = None
                if dt and val is not None:
                    rows.append({"date": dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": val, "is_forecast": False})
                elif cells[0]:
                    logger.debug("nwrfc_web_client: skipping observed row: %s %s", cells[0], cells[1])

            # Forecast column: cells[2] = datetime, cells[3] = value
            if len(cells) >= 4 and cells[2] and cells[3]:
                dt = _parse_pdt(cells[2])
                try:
                    val = float(cells[3].replace(",", ""))
                except (ValueError, AttributeError):
                    val = None
                if dt and val is not None:
                    rows.append({"date": dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "value": val, "is_forecast": True})
                elif cells[2]:
                    logger.debug("nwrfc_web_client: skipping forecast row: %s %s", cells[2], cells[3])

        return rows

    def fetch_and_parse(self, lid: str) -> list[dict]:
        """Convenience: fetch + parse for the given LID."""
        html = self.fetch(lid)
        return self.parse(html, lid=lid)
