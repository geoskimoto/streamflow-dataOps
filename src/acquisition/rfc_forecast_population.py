"""
RFC Historical Forecast Population Service.

This module provides functionality to scrape and populate historical forecast runs
from NOAA River Forecast Centers (RFCs). Each RFC maintains public web pages with
historical forecast data that can be retrieved for model training and analysis.

Note: The NOAA Water API only provides current forecasts, so historical data must
be obtained by scraping RFC websites directly.
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
import re
import time
from django.db import transaction
from django.db.models import Q

from apps.streamflow.models import Station, MasterStation, ForecastRun

logger = logging.getLogger(__name__)


class RFCForecastPopulationService:
    """Service for populating historical RFC forecast data."""

    # RFC base URLs
    RFC_URLS = {
        'NWRFC': 'https://www.nwrfc.noaa.gov',
        'CNRFC': 'https://www.cnrfc.noaa.gov',
        'CBRFC': 'https://www.cbrfc.noaa.gov',
        'MARFC': 'https://www.marfc.noaa.gov',
        'NERFC': 'https://www.nerfc.noaa.gov',
        'OHRFC': 'https://www.ohrfc.noaa.gov',
        'LMRFC': 'https://www.lmrfc.noaa.gov',
        'ABRFC': 'https://www.abrfc.noaa.gov',
        'WGRFC': 'https://www.wgrfc.noaa.gov',
        'SERFC': 'https://www.serfc.noaa.gov',
        'APRFC': 'https://www.aprfc.noaa.gov',
        'NCRFC': 'https://www.ncrfc.noaa.gov',
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'StreamflowDataOps/1.0 (Research/Education; contact@example.com)'
        })

    def discover_stations(
        self,
        rfc_codes: Optional[List[str]] = None,
        huc_codes: Optional[List[str]] = None,
        station_lids: Optional[List[str]] = None,
        limit: Optional[int] = None,
        include_inactive: bool = False
    ) -> List[Station]:
        """
        Discover RFC stations matching criteria.

        Args:
            rfc_codes: List of RFC codes (e.g., ['NWRFC', 'CNRFC'])
            huc_codes: List of HUC codes to filter by
            station_lids: Specific NOAA LIDs to fetch
            limit: Maximum number of stations to return
            include_inactive: Include inactive stations

        Returns:
            List of Station objects
        """
        query = Q(agency='NOAA_RFC')

        if not include_inactive:
            query &= Q(is_active=True)

        if rfc_codes:
            # Try to find stations by rfc_code in MasterStation
            master_query = Q(rfc_code__in=rfc_codes)
            if huc_codes:
                master_query &= Q(huc__in=huc_codes)
            
            master_stations = MasterStation.objects.filter(master_query)
            master_lids = list(master_stations.values_list('noaa_lid', flat=True))
            
            if master_lids:
                query &= Q(station_number__in=master_lids)

        if huc_codes:
            query &= Q(huc__in=huc_codes)

        if station_lids:
            query &= Q(station_number__in=station_lids)

        stations = Station.objects.filter(query)

        if limit:
            stations = stations[:limit]

        return list(stations)

    def check_station_status(
        self,
        station: Station,
        forecast_type: str = 'short'
    ) -> Dict:
        """
        Check if station already has historical forecast data populated.

        Args:
            station: Station object
            forecast_type: 'short' or 'medium'

        Returns:
            Dictionary with status information
        """
        forecast_runs = ForecastRun.objects.filter(
            station=station,
            source='NOAA_RFC',
            forecast_type=forecast_type
        )

        count = forecast_runs.count()
        
        if count == 0:
            return {
                'has_data': False,
                'forecast_count': 0,
                'min_run_date': None,
                'max_run_date': None,
                'is_complete': False
            }

        min_run = forecast_runs.order_by('run_date').first()
        max_run = forecast_runs.order_by('-run_date').first()

        return {
            'has_data': True,
            'forecast_count': count,
            'min_run_date': min_run.run_date if min_run else None,
            'max_run_date': max_run.run_date if max_run else None,
            'is_complete': False  # Can't determine completeness without API
        }

    def scrape_nwrfc_historical_forecasts(
        self,
        lid: str,
        forecast_type: str = 'short',
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Scrape historical forecasts from Northwest RFC website.

        The NWRFC provides historical forecast data through their web interface.
        This method attempts to retrieve forecast runs for a given station.

        Args:
            lid: NOAA Location ID (e.g., 'AAMC1')
            forecast_type: 'short' or 'medium'
            start_date: Start date for forecast retrieval
            end_date: End date for forecast retrieval

        Returns:
            List of forecast run dictionaries with structure:
            {
                'run_date': datetime,
                'forecast_data': [{'date': str, 'value': float}, ...],
                'forecast_type': str
            }
        """
        if forecast_type not in ['short', 'medium']:
            raise ValueError(f"Invalid forecast_type: {forecast_type}. Must be 'short' or 'medium'")

        # Default to last 90 days if not specified
        if not end_date:
            end_date = datetime.now()
        if not start_date:
            start_date = end_date - timedelta(days=90)

        self.logger.info(
            f"Attempting to scrape {forecast_type} forecasts for {lid} "
            f"from {start_date.date()} to {end_date.date()}"
        )

        # NWRFC forecast archive URLs
        # Format: https://www.nwrfc.noaa.gov/river/station/flowplot/flowplot.cgi?lid=AAMC1
        base_url = self.RFC_URLS['NWRFC']
        
        # Try multiple potential endpoints for forecast data
        potential_urls = [
            f"{base_url}/river/station/flowplot/flowplot.cgi?lid={lid}",
            f"{base_url}/data/rfc_fcst/{lid}.csv",
            f"{base_url}/river/station/{lid}/forecasts",
        ]

        forecast_runs = []
        
        for url in potential_urls:
            try:
                self.logger.info(f"Trying URL: {url}")
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 200:
                    # Attempt to parse the response
                    parsed_data = self._parse_nwrfc_response(
                        response.text,
                        response.headers.get('content-type', ''),
                        forecast_type,
                        start_date,
                        end_date
                    )
                    
                    if parsed_data:
                        forecast_runs.extend(parsed_data)
                        self.logger.info(f"Successfully parsed {len(parsed_data)} forecasts from {url}")
                        break  # Success, no need to try other URLs
                    else:
                        self.logger.warning(f"Could not parse data from {url}")
                else:
                    self.logger.warning(f"HTTP {response.status_code} for {url}")
                    
            except Exception as e:
                self.logger.warning(f"Error fetching {url}: {e}")
                continue

            # Be respectful with delays
            time.sleep(2)

        if not forecast_runs:
            self.logger.warning(
                f"Could not retrieve historical forecasts for {lid} from any source. "
                f"The station may not have public historical forecast archives available."
            )

        return forecast_runs

    def _parse_nwrfc_response(
        self,
        content: str,
        content_type: str,
        forecast_type: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """
        Parse NWRFC response content (HTML or CSV).

        Args:
            content: Response content
            content_type: HTTP content type
            forecast_type: 'short' or 'medium'
            start_date: Filter forecasts after this date
            end_date: Filter forecasts before this date

        Returns:
            List of parsed forecast runs
        """
        forecasts = []

        try:
            if 'text/csv' in content_type or content.startswith('Date,'):
                # CSV format
                forecasts = self._parse_csv_forecasts(content, forecast_type, start_date, end_date)
            elif 'text/html' in content_type or '<html' in content.lower():
                # HTML format
                forecasts = self._parse_html_forecasts(content, forecast_type, start_date, end_date)
            else:
                # Try both
                csv_result = self._parse_csv_forecasts(content, forecast_type, start_date, end_date)
                if csv_result:
                    forecasts = csv_result
                else:
                    forecasts = self._parse_html_forecasts(content, forecast_type, start_date, end_date)

        except Exception as e:
            self.logger.error(f"Error parsing NWRFC response: {e}")

        return forecasts

    def _parse_csv_forecasts(
        self,
        content: str,
        forecast_type: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """Parse CSV format forecast data."""
        forecasts = []
        
        lines = content.strip().split('\n')
        if not lines:
            return forecasts

        # Try to parse CSV
        # Common format: Date,IssueTime,ForecastValue
        # or: Date,Value with implicit issue time
        
        for line in lines[1:]:  # Skip header
            parts = line.split(',')
            if len(parts) >= 2:
                try:
                    # Parse date and value
                    date_str = parts[0].strip()
                    value = float(parts[1].strip())
                    
                    # Add to forecasts
                    # Note: This is simplified - real implementation would need
                    # to properly group by issue time
                    
                except (ValueError, IndexError):
                    continue

        return forecasts

    def _parse_html_forecasts(
        self,
        content: str,
        forecast_type: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """Parse HTML format forecast data."""
        forecasts = []
        
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # Look for tables with forecast data
            tables = soup.find_all('table')
            
            for table in tables:
                # Try to extract forecast data from table
                # This is highly dependent on RFC website structure
                pass
                
        except Exception as e:
            self.logger.error(f"Error parsing HTML: {e}")

        return forecasts

    def populate_station(
        self,
        station: Station,
        forecast_type: str = 'short',
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        force: bool = False,
        dry_run: bool = False
    ) -> Dict:
        """
        Populate historical forecasts for a single station.

        Args:
            station: Station object
            forecast_type: 'short' or 'medium'
            start_date: Start date for forecast retrieval (default: 90 days ago)
            end_date: End date for forecast retrieval (default: today)
            force: Re-populate even if data exists
            dry_run: Don't actually save data

        Returns:
            Dictionary with result statistics
        """
        lid = station.station_number
        
        # Get RFC code from MasterStation
        try:
            master_station = MasterStation.objects.filter(
                Q(noaa_lid=lid) | Q(station_number=lid)
            ).first()
            
            if not master_station or not master_station.rfc_code:
                return {
                    'status': 'failed',
                    'error': 'Station does not have RFC code in MasterStation',
                    'forecasts_retrieved': 0,
                    'forecasts_saved': 0
                }
            
            rfc_code = master_station.rfc_code
            
        except Exception as e:
            return {
                'status': 'failed',
                'error': f'Error getting MasterStation: {str(e)}',
                'forecasts_retrieved': 0,
                'forecasts_saved': 0
            }

        # Check if already populated
        if not force:
            status = self.check_station_status(station, forecast_type)
            if status['has_data']:
                return {
                    'status': 'skipped',
                    'reason': 'already_populated',
                    'existing_forecasts': status['forecast_count'],
                    'forecasts_retrieved': 0,
                    'forecasts_saved': 0
                }

        # Currently only NWRFC scraping is implemented
        if rfc_code != 'NWRFC':
            return {
                'status': 'not_supported',
                'error': f'Historical scraping not yet implemented for {rfc_code}',
                'forecasts_retrieved': 0,
                'forecasts_saved': 0
            }

        # Scrape historical forecasts
        try:
            forecast_runs = self.scrape_nwrfc_historical_forecasts(
                lid=lid,
                forecast_type=forecast_type,
                start_date=start_date,
                end_date=end_date
            )

            if not forecast_runs:
                return {
                    'status': 'no_data',
                    'error': 'No historical forecast data available from RFC website',
                    'forecasts_retrieved': 0,
                    'forecasts_saved': 0
                }

            if dry_run:
                return {
                    'status': 'dry_run',
                    'forecasts_retrieved': len(forecast_runs),
                    'forecasts_saved': 0,
                    'sample_run_dates': [
                        f['run_date'].isoformat() 
                        for f in forecast_runs[:5]
                    ]
                }

            # Save forecasts to database
            saved_count = 0
            duplicate_count = 0
            
            for forecast_data in forecast_runs:
                try:
                    ForecastRun.objects.update_or_create(
                        station=station,
                        source='NOAA_RFC',
                        run_date=forecast_data['run_date'],
                        forecast_type=forecast_type,
                        defaults={
                            'data': forecast_data['forecast_data'],
                            'rmse': forecast_data.get('rmse', None)
                        }
                    )
                    saved_count += 1
                except Exception as e:
                    self.logger.error(f"Error saving forecast run: {e}")
                    duplicate_count += 1

            return {
                'status': 'success',
                'forecasts_retrieved': len(forecast_runs),
                'forecasts_saved': saved_count,
                'duplicates_skipped': duplicate_count
            }

        except Exception as e:
            self.logger.error(f"Error populating forecasts for {lid}: {e}")
            return {
                'status': 'failed',
                'error': str(e),
                'forecasts_retrieved': 0,
                'forecasts_saved': 0
            }

    def populate_bulk(
        self,
        stations: List[Station],
        forecast_type: str = 'short',
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        force: bool = False,
        dry_run: bool = False,
        delay_seconds: float = 3.0
    ) -> Dict:
        """
        Populate historical forecasts for multiple stations.

        Args:
            stations: List of Station objects
            forecast_type: 'short' or 'medium'
            start_date: Start date for forecast retrieval
            end_date: End date for forecast retrieval
            force: Re-populate even if data exists
            dry_run: Don't actually save data
            delay_seconds: Delay between stations (respectful scraping)

        Returns:
            Dictionary with aggregate statistics
        """
        total = len(stations)
        results = {
            'total': total,
            'success': 0,
            'skipped': 0,
            'not_supported': 0,
            'no_data': 0,
            'failed': 0,
            'total_forecasts_saved': 0
        }

        for i, station in enumerate(stations, 1):
            self.logger.info(f"Processing station {i}/{total}: {station.station_number}")
            
            result = self.populate_station(
                station=station,
                forecast_type=forecast_type,
                start_date=start_date,
                end_date=end_date,
                force=force,
                dry_run=dry_run
            )

            status = result['status']
            if status in results:
                results[status] += 1
            
            results['total_forecasts_saved'] += result.get('forecasts_saved', 0)

            # Be respectful with delays between requests
            if i < total:
                time.sleep(delay_seconds)

        return results
