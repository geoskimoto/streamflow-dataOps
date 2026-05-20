"""NOAA NWPS flood threshold fetcher. Calls /gauges/{lid} and upserts FloodThreshold rows."""

import logging

import requests

logger = logging.getLogger(__name__)

NWPS_BASE_URL = 'https://api.water.noaa.gov/nwps/v1'
REQUEST_TIMEOUT = 15


def _resolve_hads_lid(station):
    """Return the NOAA HADS LID for a station, or None if unavailable."""
    from apps.streamflow.models import MasterStation, StationMapping

    if station.agency == 'NOAA_RFC':
        return station.station_number

    # USGS: try MasterStation.noaa_lid
    try:
        master = MasterStation.objects.get(station_number=station.station_number, agency='USGS')
        if master.noaa_lid:
            return master.noaa_lid
    except MasterStation.DoesNotExist:
        pass

    # Any agency: try StationMapping for a NOAA_RFC target
    mapping = StationMapping.objects.filter(
        source_agency=station.agency,
        source_id=station.station_number,
        target_agency='NOAA_RFC',
    ).first()
    if mapping:
        return mapping.target_id

    return None


def _extract_threshold(stageflow, category, field):
    """Safely extract a numeric threshold value from the stageflow dict."""
    value = stageflow.get(category, {}).get(field)
    if value is None or value == '':
        return None
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def fetch_flood_thresholds_for_stations(station_ids):
    """Fetch NOAA NWPS flood thresholds and upsert FloodThreshold for given station PKs.

    NWPS API: GET /gauges/{lid}
    Response path: flood.stageflow.{action|flood|moderate|major|record}.{stage|flow}
    Note: NWPS uses 'flood' for what NWS calls minor flood stage. Stored as minor_* here.

    Returns:
        dict with keys: updated, skipped, errors
    """
    from apps.analytics.models import FloodThreshold
    from apps.streamflow.models import Station

    stations = Station.objects.filter(id__in=station_ids)
    updated = skipped = errors = 0

    for station in stations:
        lid = _resolve_hads_lid(station)
        if not lid:
            logger.debug('No HADS LID for %s, skipping', station.station_number)
            skipped += 1
            continue

        try:
            response = requests.get(
                f'{NWPS_BASE_URL}/gauges/{lid}',
                timeout=REQUEST_TIMEOUT,
                headers={'Accept': 'application/json'},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.error('NWPS API error for %s (lid=%s): %s', station.station_number, lid, exc)
            errors += 1
            continue

        flood = data.get('flood') or {}
        stageflow = flood.get('stageflow') or flood.get('categories') or {}

        FloodThreshold.objects.update_or_create(
            station=station,
            defaults={
                'noaa_lid': lid,
                'action_stage_ft': _extract_threshold(stageflow, 'action', 'stage'),
                'action_flow_cfs': _extract_threshold(stageflow, 'action', 'flow'),
                # NWPS 'flood' category = NWS minor flood stage
                'minor_stage_ft': _extract_threshold(stageflow, 'flood', 'stage'),
                'minor_flow_cfs': _extract_threshold(stageflow, 'flood', 'flow'),
                'moderate_stage_ft': _extract_threshold(stageflow, 'moderate', 'stage'),
                'moderate_flow_cfs': _extract_threshold(stageflow, 'moderate', 'flow'),
                'major_stage_ft': _extract_threshold(stageflow, 'major', 'stage'),
                'major_flow_cfs': _extract_threshold(stageflow, 'major', 'flow'),
                'record_stage_ft': _extract_threshold(stageflow, 'record', 'stage'),
                'record_flow_cfs': _extract_threshold(stageflow, 'record', 'flow'),
                'source': 'noaa_api',
            },
        )
        updated += 1
        logger.debug('Updated flood thresholds for %s (lid=%s)', station.station_number, lid)

    logger.info(
        'fetch_flood_thresholds: updated=%d, skipped=%d, errors=%d', updated, skipped, errors
    )
    return {'updated': updated, 'skipped': skipped, 'errors': errors}
