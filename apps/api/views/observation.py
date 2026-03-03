"""ViewSets for observation data API."""

import hashlib
from datetime import date, datetime, timedelta

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.http import HttpResponse
from django.db.models import Min, Max, Avg, Count
from django.utils import timezone
from django.utils.http import http_date
from drf_spectacular.utils import OpenApiParameter, extend_schema
from drf_spectacular.openapi import OpenApiTypes
import csv

from apps.streamflow.models import DischargeObservation, Station, DailyFlowPercentile
from apps.api.serializers import (
    DischargeObservationSerializer,
    ObservationStatisticsSerializer,
)
from apps.api.serializers.observation import (
    PercentileBandsResponseSerializer,
    PercentileDateRangeSerializer,
)
from apps.api.pagination import StandardResultsSetPagination


class DischargeObservationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for querying discharge observations.

    list: Get discharge observations with filtering
    retrieve: Get a single observation
    """

    queryset = DischargeObservation.objects.all()
    serializer_class = DischargeObservationSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['station', 'quality_code', 'type', 'unit']
    ordering_fields = ['observed_at', 'discharge']
    ordering = ['-observed_at']

    def get_queryset(self):
        """Filter observations by date range and station."""
        queryset = super().get_queryset()

        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            queryset = queryset.filter(observed_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(observed_at__lte=end_date)

        station_number = self.request.query_params.get('station_number')
        if station_number:
            queryset = queryset.filter(station__station_number=station_number)

        return queryset.select_related('station')

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        Get statistical summary of observations.

        Query params:
        - station_number: Optional filter
        - start_date: ISO format datetime
        - end_date: ISO format datetime
        - type: realtime_15min or daily_mean
        """
        station_number = request.query_params.get('station_number')

        observations = self.get_queryset()
        if station_number:
            observations = observations.filter(station__station_number=station_number)

        stats = observations.aggregate(
            count=Count('id'),
            min_value=Min('discharge'),
            max_value=Max('discharge'),
            mean_value=Avg('discharge'),
            start_date=Min('observed_at'),
            end_date=Max('observed_at'),
        )

        latest = observations.order_by('-observed_at').first()

        data = {
            'station_number': station_number,
            'start_date': stats['start_date'],
            'end_date': stats['end_date'],
            'count': stats['count'],
            'min_value': stats['min_value'],
            'max_value': stats['max_value'],
            'mean_value': round(stats['mean_value'], 2) if stats['mean_value'] else None,
            'latest_value': latest.discharge if latest else None,
            'latest_timestamp': latest.observed_at if latest else None,
        }

        serializer = ObservationStatisticsSerializer(data)
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # Percentile band endpoints
    # ------------------------------------------------------------------

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "date",
                OpenApiTypes.DATE,
                description=(
                    "Return bands for this date (YYYY-MM-DD). "
                    "Defaults to the latest date available in the database."
                ),
            ),
            OpenApiParameter(
                "station",
                OpenApiTypes.STR,
                description="Filter to a single station number.",
            ),
        ],
        responses={200: PercentileBandsResponseSerializer},
    )
    @action(detail=False, methods=["get"], url_path="percentile-bands")
    def percentile_bands(self, request):
        """
        Return precomputed exceedance percentile bands for all stations on a
        given date.

        Data is populated by the daily Celery task and the historical backfill
        command. Use ``?date=YYYY-MM-DD`` to drive a rangeslider. Omit the
        parameter to get the latest available date.

        Responses for past dates include long-lived Cache-Control and ETag
        headers (data never changes once computed). Today's date is uncached.
        """
        station_filter = request.query_params.get("station")

        # Resolve target date
        date_param = request.query_params.get("date")
        if date_param:
            try:
                target_date = date.fromisoformat(date_param)
            except ValueError:
                return Response(
                    {"detail": "Invalid date format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # Default to the latest date that has data
            latest = DailyFlowPercentile.objects.aggregate(d=Max("date"))["d"]
            target_date = latest or date.today()

        queryset = DailyFlowPercentile.objects.filter(
            date=target_date
        ).select_related("station")

        if station_filter:
            queryset = queryset.filter(station__station_number=station_filter)

        computed_at = queryset.aggregate(latest=Max("computed_at"))["latest"]

        results = [
            {
                "station_number":          obj.station.station_number,
                "discharge":               float(obj.discharge),
                "percentile_rank":         float(obj.percentile_rank),
                "band":                    obj.band,
                "historical_record_count": obj.historical_record_count,
            }
            for obj in queryset
        ]

        response = Response({
            "date":        target_date.isoformat(),
            "computed_at": computed_at.isoformat() if computed_at else None,
            "count":       len(results),
            "results":     results,
        })

        # Cache historical dates indefinitely (data never changes).
        # Don't cache today — the daily task may not have run yet.
        if computed_at and target_date < date.today():
            etag = hashlib.md5(
                f"{target_date.isoformat()}:{computed_at.isoformat()}".encode()
            ).hexdigest()
            response["Cache-Control"] = "public, max-age=86400"
            response["Last-Modified"] = http_date(computed_at.timestamp())
            response["ETag"] = f'"{etag}"'

        return response

    @extend_schema(responses={200: PercentileDateRangeSerializer})
    @action(detail=False, methods=["get"], url_path="percentile-date-range")
    def percentile_date_range(self, request):
        """
        Return the min and max dates available in daily_flow_percentiles.

        Use this to set the bounds of the rangeslider in the dashboard.
        Response is cached for 1 hour.
        """
        agg = DailyFlowPercentile.objects.aggregate(
            min_date=Min("date"),
            max_date=Max("date"),
        )

        response = Response({
            "min_date": agg["min_date"].isoformat() if agg["min_date"] else None,
            "max_date": agg["max_date"].isoformat() if agg["max_date"] else None,
        })
        response["Cache-Control"] = "public, max-age=3600"
        return response
