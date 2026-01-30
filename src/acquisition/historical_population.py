"""Service for populating historical USGS discharge data."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.streamflow.models import Station, MasterStation, DischargeObservation
from src.acquisition.usgs_client import USGSClient

logger = logging.getLogger(__name__)


class HistoricalPopulationService:
    """Service for populating complete historical USGS discharge data."""

    def __init__(self, batch_size: int = 1000, delay: float = 1.0):
        """
        Initialize the service.

        Args:
            batch_size: Number of records per bulk insert
            delay: Seconds to wait between stations
        """
        self.usgs_client = USGSClient()
        self.batch_size = batch_size
        self.delay = delay
        self.logger = logging.getLogger(__name__)

    def check_station_status(self, station: Station) -> Dict[str, Any]:
        """
        Check existing data coverage for a station.

        Args:
            station: Station object

        Returns:
            Dictionary with coverage details:
            - has_data: bool
            - record_count: int
            - min_date: datetime or None
            - max_date: datetime or None
            - expected_start: datetime or None
            - expected_end: datetime or None
            - is_complete: bool
            - missing_days: int
        """
        # Query existing discharge observations
        observations = DischargeObservation.objects.filter(
            station=station,
            type='daily_mean'
        )

        if not observations.exists():
            return {
                'has_data': False,
                'record_count': 0,
                'min_date': None,
                'max_date': None,
                'expected_start': station.record_start_date,
                'expected_end': station.record_end_date or timezone.now(),
                'is_complete': False,
                'missing_days': None
            }

        # Get date range
        from django.db.models import Min, Max, Count
        stats = observations.aggregate(
            min_date=Min('observed_at'),
            max_date=Max('observed_at'),
            count=Count('id')
        )

        # Determine expected range
        expected_start = station.record_start_date or stats['min_date']
        expected_end = station.record_end_date or timezone.now()

        # Check if complete
        is_complete = False
        missing_days = None

        if expected_start and expected_end:
            # Calculate expected number of days
            expected_days = (expected_end.date() - expected_start.date()).days + 1
            actual_days = stats['count']
            missing_days = expected_days - actual_days

            # Consider complete if within 5% of expected
            is_complete = (missing_days / expected_days) < 0.05 if expected_days > 0 else False

        return {
            'has_data': True,
            'record_count': stats['count'],
            'min_date': stats['min_date'],
            'max_date': stats['max_date'],
            'expected_start': expected_start,
            'expected_end': expected_end,
            'is_complete': is_complete,
            'missing_days': missing_days
        }

    def populate_station(
        self,
        station: Station,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        force: bool = False,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Populate historical data for a single station.

        Args:
            station: Station object
            start_date: Override start date (None = use station.record_start_date)
            end_date: Override end date (None = use today)
            force: Re-fetch even if already populated
            dry_run: Don't actually insert data

        Returns:
            Dictionary with results:
            - station_number: str
            - status: 'success' | 'skipped' | 'failed' | 'dry_run'
            - records_fetched: int
            - records_inserted: int
            - existing_records: int
            - duration_seconds: float
            - error: str (if failed)
        """
        start_time = datetime.now()
        result = {
            'station_number': station.station_number,
            'status': 'failed',
            'records_fetched': 0,
            'records_inserted': 0,
            'existing_records': 0,
            'duration_seconds': 0.0,
            'error': None
        }

        try:
            # Check if already populated
            if not force and station.historical_data_populated_at:
                status = self.check_station_status(station)
                result['status'] = 'skipped'
                result['existing_records'] = status['record_count']
                result['duration_seconds'] = (datetime.now() - start_time).total_seconds()
                return result

            # Determine date range
            if not start_date:
                # Try to get from USGS if station metadata incomplete
                if not station.record_start_date:
                    # Default to 30 years ago
                    start_date = timezone.now() - timedelta(days=30*365)
                else:
                    start_date = station.record_start_date

            if not end_date:
                end_date = timezone.now()

            # Check for existing data to determine gaps
            status = self.check_station_status(station)
            result['existing_records'] = status['record_count']

            if status['has_data'] and not force:
                # Check if we need to fill gaps
                if status['is_complete']:
                    result['status'] = 'skipped'
                    result['duration_seconds'] = (datetime.now() - start_time).total_seconds()
                    return result

                # Fill gaps - fetch full range and let bulk_create with ignore_conflicts handle duplicates
                self.logger.info(
                    f"Station {station.station_number} has gaps "
                    f"({status['missing_days']} days missing), filling..."
                )

            if dry_run:
                result['status'] = 'dry_run'
                result['duration_seconds'] = (datetime.now() - start_time).total_seconds()
                return result

            # Fetch data from USGS
            self.logger.info(
                f"Fetching historical data for {station.station_number} "
                f"from {start_date.date()} to {end_date.date()}"
            )

            observations_data = self.usgs_client.get_daily_mean(
                station_number=station.station_number,
                start_date=start_date,
                end_date=end_date
            )

            result['records_fetched'] = len(observations_data)

            if not observations_data:
                result['status'] = 'failed'
                result['error'] = 'No data returned from USGS'
                result['duration_seconds'] = (datetime.now() - start_time).total_seconds()
                return result

            # Bulk insert with conflict handling
            with transaction.atomic():
                observations_to_create = []

                for obs_data in observations_data:
                    observation = DischargeObservation(
                        station=station,
                        observed_at=obs_data['observed_at'],
                        discharge=Decimal(str(obs_data['discharge'])),
                        unit=obs_data['unit'],
                        type=obs_data['type'],
                        quality_code=obs_data.get('quality_code', '')
                    )
                    observations_to_create.append(observation)

                    # Batch insert
                    if len(observations_to_create) >= self.batch_size:
                        created = DischargeObservation.objects.bulk_create(
                            observations_to_create,
                            ignore_conflicts=True
                        )
                        result['records_inserted'] += len(created)
                        observations_to_create = []

                # Insert remaining
                if observations_to_create:
                    created = DischargeObservation.objects.bulk_create(
                        observations_to_create,
                        ignore_conflicts=True
                    )
                    result['records_inserted'] += len(created)

                # Update station tracking
                station.historical_data_populated_at = timezone.now()
                station.historical_record_count = result['records_fetched']
                station.save(update_fields=[
                    'historical_data_populated_at',
                    'historical_record_count'
                ])

            result['status'] = 'success'
            self.logger.info(
                f"Successfully populated {result['records_inserted']} records "
                f"for station {station.station_number}"
            )

        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
            self.logger.error(
                f"Failed to populate station {station.station_number}: {e}",
                exc_info=True
            )

        result['duration_seconds'] = (datetime.now() - start_time).total_seconds()
        return result

    def discover_stations(
        self,
        huc_codes: Optional[List[str]] = None,
        state_codes: Optional[List[str]] = None,
        station_numbers: Optional[List[str]] = None,
        include_inactive: bool = False
    ) -> List[Station]:
        """
        Discover stations matching criteria, creating Station records from MasterStation if needed.

        Args:
            huc_codes: List of HUC codes (e.g., ['17'])
            state_codes: List of state codes (e.g., ['WA', 'OR'])
            station_numbers: Specific station numbers
            include_inactive: Include inactive stations

        Returns:
            List of Station objects
        """
        # If specific stations provided, use those
        if station_numbers:
            # Check Station table first
            stations = list(Station.objects.filter(
                station_number__in=station_numbers,
                agency='USGS'
            ))

            # Create missing from MasterStation
            existing_numbers = {s.station_number for s in stations}
            missing_numbers = set(station_numbers) - existing_numbers

            if missing_numbers:
                master_stations = MasterStation.objects.filter(
                    station_number__in=missing_numbers,
                    agency='USGS'
                )
                stations.extend(self._create_stations_from_master(master_stations))

            return stations

        # Build query
        query = {'agency': 'USGS'}

        if not include_inactive:
            query['is_active'] = True

        # Try Station table first
        station_query = Station.objects.filter(**query)

        if huc_codes:
            from django.db.models import Q
            huc_q = Q()
            for huc in huc_codes:
                huc_q |= Q(huc_code__startswith=huc)
            station_query = station_query.filter(huc_q)

        if state_codes:
            station_query = station_query.filter(state__in=state_codes)

        stations = list(station_query.order_by('station_number'))

        # If no stations found, try MasterStation
        if not stations:
            master_query = MasterStation.objects.filter(agency='USGS')  # MasterStation doesn't have is_active

            if huc_codes:
                huc_q = Q()
                for huc in huc_codes:
                    huc_q |= Q(huc_code__startswith=huc)
                master_query = master_query.filter(huc_q)

            if state_codes:
                master_query = master_query.filter(state_code__in=state_codes)  # MasterStation uses state_code

            master_stations = master_query.order_by('station_number')
            stations = self._create_stations_from_master(master_stations)

        return stations

    def _create_stations_from_master(self, master_stations) -> List[Station]:
        """Create Station records from MasterStation records."""
        stations = []

        for master in master_stations:
            station, created = Station.objects.get_or_create(
                station_number=master.station_number,
                defaults={
                    'name': master.station_name,  # Note: MasterStation uses station_name
                    'agency': master.agency,
                    'latitude': master.latitude,
                    'longitude': master.longitude,
                    'huc_code': master.huc_code,
                    'basin': '',  # MasterStation doesn't have basin
                    'state': master.state_code,  # Note: MasterStation uses state_code
                    'catchment_area': None,  # Calculate from drainage_area_sqmi if needed
                    'years_of_record': None,  # Will be determined from data
                    'record_start_date': None,  # Will query from USGS
                    'record_end_date': None,  # Will query from USGS
                    'is_active': True
                }
            )
            stations.append(station)

            if created:
                self.logger.info(f"Created Station record for {station.station_number}")

        return stations

    def populate_bulk(
        self,
        stations: List[Station],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        force: bool = False,
        dry_run: bool = False,
        delay: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Populate historical data for multiple stations.

        Args:
            stations: List of Station objects
            start_date: Override start date
            end_date: Override end date
            force: Re-fetch even if already populated
            dry_run: Don't actually insert data
            delay: Seconds between stations (overrides instance delay)

        Returns:
            Summary dictionary
        """
        import time

        if delay is None:
            delay = self.delay

        start_time = datetime.now()
        summary = {
            'total_stations': len(stations),
            'successful': 0,
            'skipped': 0,
            'failed': 0,
            'dry_run': 0,
            'total_records_fetched': 0,
            'total_records_inserted': 0,
            'duration_seconds': 0.0,
            'failed_stations': [],
            'results': []
        }

        for i, station in enumerate(stations, 1):
            self.logger.info(f"Processing station {i}/{len(stations)}: {station.station_number}")

            result = self.populate_station(
                station=station,
                start_date=start_date,
                end_date=end_date,
                force=force,
                dry_run=dry_run
            )

            summary['results'].append(result)

            if result['status'] == 'success':
                summary['successful'] += 1
                summary['total_records_fetched'] += result['records_fetched']
                summary['total_records_inserted'] += result['records_inserted']
            elif result['status'] == 'skipped':
                summary['skipped'] += 1
            elif result['status'] == 'dry_run':
                summary['dry_run'] += 1
            elif result['status'] == 'failed':
                summary['failed'] += 1
                summary['failed_stations'].append({
                    'station_number': result['station_number'],
                    'error': result['error']
                })

            # Delay between stations (except last one)
            if i < len(stations) and delay > 0:
                time.sleep(delay)

        summary['duration_seconds'] = (datetime.now() - start_time).total_seconds()
        return summary
