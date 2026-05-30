"""API view for basin-averaged NWM forcings."""
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.streamflow.models import BasinForcing, Station
from apps.api.serializers.forcing import BasinForcingSerializer


class BasinForcingView(APIView):
    """GET /api/v1/forcings/{usgs_id}/?days=365

    Returns daily basin-averaged forcings for the past N days (default 365),
    ordered oldest-first.
    """

    # This endpoint is intentionally unauthenticated — basin forcing data is public meteorological data.
    permission_classes = [AllowAny]

    def get(self, request, usgs_id: str):
        try:
            station = Station.objects.get(station_number=usgs_id, agency="USGS")
        except Station.DoesNotExist:
            return Response(
                {"detail": f"Station {usgs_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            days = int(request.query_params.get("days", 365))
        except (ValueError, TypeError):
            return Response(
                {"detail": "days must be a positive integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        forcings_qs = BasinForcing.objects.filter(station=station, source="nwm")
        if not forcings_qs.exists():
            forcings_qs = BasinForcing.objects.filter(station=station, source="daymet")
        forcings = forcings_qs.select_related("station").order_by("-date")[:days]
        forcings_list = list(reversed(list(forcings)))
        serializer = BasinForcingSerializer(forcings_list, many=True)
        return Response(serializer.data)
