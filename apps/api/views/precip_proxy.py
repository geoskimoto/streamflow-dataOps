"""Proxy view: fetches EA-LSTM precip-runoff forecasts from the ResidCast service."""
import logging

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.streamflow.models import StationMapping

logger = logging.getLogger(__name__)


class PrecipForecastProxyView(APIView):
    """GET /api/v1/precip-forecasts/<station_number>/

    Resolves the USGS station number to its NWRFC/HADS ID via StationMapping,
    then proxies the request to the ResidCast FastAPI service.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, station_number: str):
        try:
            mapping = StationMapping.objects.get(
                source_agency="USGS",
                source_id=station_number,
                target_agency="HADS",
            )
        except StationMapping.DoesNotExist:
            return Response(
                {"detail": f"No EA-LSTM forecast mapping for station {station_number}."},
                status=status.HTTP_404_NOT_FOUND,
            )

        url = (
            f"{settings.RESIDCAST_API_BASE}/api/v1/precip-forecasts"
            f"/{mapping.target_id}/"
        )
        headers = {"Authorization": f"Bearer {settings.RESIDCAST_API_TOKEN}"}

        try:
            resp = requests.get(url, headers=headers, timeout=10)
        except requests.RequestException as exc:
            logger.warning("ResidCast request failed for %s: %s", station_number, exc)
            return Response(
                {"detail": "Forecast service unavailable."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if resp.status_code == 404:
            return Response(
                {"detail": "No precip forecast available for this station."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not resp.ok:
            logger.warning(
                "ResidCast returned HTTP %s for %s", resp.status_code, station_number
            )
            return Response(
                {"detail": "Forecast service error."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(resp.json(), status=status.HTTP_200_OK)
