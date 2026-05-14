"""API views for forecast data."""

from datetime import date, timedelta

from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Avg, Min, Max
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from apps.streamflow.models import ForecastRun, ForecastPercentile
from apps.api.serializers.forecast import (
    ForecastRunSerializer,
    ForecastRunListSerializer,
    ForecastStatisticsSerializer,
)
from apps.api.serializers.forecast_percentile import (
    ForecastPercentileBandsResponseSerializer,
    ForecastPercentileDateRangeSerializer,
)
from apps.api.pagination import StandardResultsSetPagination


class ForecastRunViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for forecast runs.
    
    Provides read-only access to forecast data from various sources (NOAA RFC, etc).
    """
    
    queryset = ForecastRun.objects.select_related('station').order_by('-run_date')
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['station', 'source', 'run_date']
    search_fields = ['station__station_number', 'station__name']
    ordering_fields = ['run_date', 'station__station_number']
    
    def get_serializer_class(self):
        """Use lightweight serializer for list view."""
        if self.action == 'list':
            return ForecastRunListSerializer
        return ForecastRunSerializer
    
    @extend_schema(
        parameters=[
            OpenApiParameter('station_number', OpenApiTypes.STR, description='Filter by station number'),
            OpenApiParameter('source', OpenApiTypes.STR, description='Filter by source (e.g., NOAA_RFC)'),
            OpenApiParameter('start_date', OpenApiTypes.DATETIME, description='Filter forecasts after this date'),
            OpenApiParameter('end_date', OpenApiTypes.DATETIME, description='Filter forecasts before this date'),
        ],
        responses={200: ForecastRunListSerializer(many=True)}
    )
    def list(self, request, *args, **kwargs):
        """List all forecast runs with optional filters."""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Additional filters
        station_number = request.query_params.get('station_number')
        if station_number:
            queryset = queryset.filter(station__station_number=station_number)
        
        start_date = request.query_params.get('start_date')
        if start_date:
            queryset = queryset.filter(run_date__gte=start_date)
        
        end_date = request.query_params.get('end_date')
        if end_date:
            queryset = queryset.filter(run_date__lte=end_date)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        responses={200: ForecastRunSerializer}
    )
    def retrieve(self, request, *args, **kwargs):
        """Retrieve a specific forecast run with full data."""
        return super().retrieve(request, *args, **kwargs)
    
    @extend_schema(
        parameters=[
            OpenApiParameter('source', OpenApiTypes.STR, description='Filter by source'),
            OpenApiParameter('start_date', OpenApiTypes.DATETIME, description='Start date for statistics'),
            OpenApiParameter('end_date', OpenApiTypes.DATETIME, description='End date for statistics'),
        ],
        responses={200: ForecastStatisticsSerializer}
    )
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        Get aggregate statistics for forecast runs.
        
        Returns counts, date ranges, and average RMSE.
        """
        queryset = self.filter_queryset(self.get_queryset())
        
        # Apply filters
        source = request.query_params.get('source')
        if source:
            queryset = queryset.filter(source=source)
        
        start_date = request.query_params.get('start_date')
        if start_date:
            queryset = queryset.filter(run_date__gte=start_date)
        
        end_date = request.query_params.get('end_date')
        if end_date:
            queryset = queryset.filter(run_date__lte=end_date)
        
        # Calculate statistics
        stats = queryset.aggregate(
            count=Count('id'),
            stations=Count('station', distinct=True),
            start_date=Min('run_date'),
            end_date=Max('run_date'),
            avg_rmse=Avg('rmse'),
        )
        
        # Calculate total forecast points
        total_points = sum(len(fr.data) if fr.data else 0 for fr in queryset)
        
        data = {
            'start_date': stats['start_date'],
            'end_date': stats['end_date'],
            'count': stats['count'] or 0,
            'stations': stats['stations'] or 0,
            'total_forecast_points': total_points,
            'avg_rmse': stats['avg_rmse'],
        }
        
        serializer = ForecastStatisticsSerializer(data)
        return Response(serializer.data)
    
    @extend_schema(
        parameters=[
            OpenApiParameter('station_number', OpenApiTypes.STR, required=True, description='Station number'),
        ],
        responses={200: ForecastRunSerializer(many=True)}
    )
    @action(detail=False, methods=['get'], url_path='by-station/(?P<station_number>[^/.]+)')
    def by_station(self, request, station_number=None):
        """
        Get all forecast runs for a specific station.
        
        Returns forecasts ordered by run date (most recent first).
        """
        queryset = self.get_queryset().filter(station__station_number=station_number)
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ForecastRunListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = ForecastRunListSerializer(queryset, many=True)
        return Response(serializer.data)
    
    @extend_schema(
        responses={200: ForecastRunSerializer}
    )
    @action(detail=False, methods=['get'], url_path='latest')
    def latest(self, request):
        """
        Get the most recent forecast run across all stations.
        """
        latest_forecast = self.get_queryset().first()
        if not latest_forecast:
            return Response(
                {'detail': 'No forecasts found'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.get_serializer(latest_forecast)
        return Response(serializer.data)

    @extend_schema(
        parameters=[
            OpenApiParameter('date', OpenApiTypes.DATE,
                             description='Forecast date (YYYY-MM-DD). Defaults to earliest available.'),
            OpenApiParameter('source', OpenApiTypes.STR,
                             description='Forecast source label (default: NWRFC).'),
            OpenApiParameter('station', OpenApiTypes.STR,
                             description='Filter to a single station number.'),
        ],
        responses={200: ForecastPercentileBandsResponseSerializer},
    )
    @action(detail=False, methods=['get'], url_path='discharge/percentile-bands')
    def percentile_bands(self, request):
        """
        Return precomputed exceedance percentile bands for all stations with
        NWRFC forecast data on a given date.

        Use ``?date=YYYY-MM-DD`` to drive the dashboard date picker in the
        forecast period. Omit the parameter to get the earliest available date.
        No caching — forecasts update intraday.
        """
        source         = request.query_params.get('source', 'NWRFC')
        station_filter = request.query_params.get('station')

        date_param = request.query_params.get('date')
        if date_param:
            try:
                target_date = date.fromisoformat(date_param)
            except ValueError:
                return Response(
                    {'detail': 'Invalid date format. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            earliest = ForecastPercentile.objects.filter(
                source=source
            ).aggregate(d=Min('target_date'))['d']
            target_date = earliest or (date.today() + timedelta(days=1))

        queryset = ForecastPercentile.objects.filter(
            target_date=target_date,
            source=source,
        ).select_related('station')

        if station_filter:
            queryset = queryset.filter(station__station_number=station_filter)

        agg = queryset.aggregate(
            computed_at=Max('computed_at'),
            forecast_run_date=Max('forecast_run_date'),
        )

        results = [
            {
                'station_number':          obj.station.station_number,
                'forecast_discharge':      float(obj.forecast_discharge),
                'percentile_rank':         float(obj.percentile_rank),
                'band':                    obj.band,
                'historical_record_count': obj.historical_record_count,
            }
            for obj in queryset
        ]

        return Response({
            'date':              target_date.isoformat(),
            'source':            source,
            'forecast_run_date': agg['forecast_run_date'].isoformat() if agg['forecast_run_date'] else None,
            'computed_at':       agg['computed_at'].isoformat() if agg['computed_at'] else None,
            'count':             len(results),
            'results':           results,
        })

    @extend_schema(
        parameters=[
            OpenApiParameter('source', OpenApiTypes.STR,
                             description='Forecast source label (default: NWRFC).'),
        ],
        responses={200: ForecastPercentileDateRangeSerializer},
    )
    @action(detail=False, methods=['get'], url_path='discharge/percentile-date-range')
    def percentile_date_range(self, request):
        """
        Return the min and max forecast dates available in forecast_percentiles.

        Use this to extend the dashboard rangeslider into the forecast period.
        Response is cached for 1 hour.
        """
        source = request.query_params.get('source', 'NWRFC')

        agg = ForecastPercentile.objects.filter(source=source).aggregate(
            min_date=Min('target_date'),
            max_date=Max('target_date'),
            forecast_run_date=Max('forecast_run_date'),
        )

        response = Response({
            'source':            source,
            'min_date':          agg['min_date'].isoformat() if agg['min_date'] else None,
            'max_date':          agg['max_date'].isoformat() if agg['max_date'] else None,
            'forecast_run_date': agg['forecast_run_date'].isoformat() if agg['forecast_run_date'] else None,
        })
        response['Cache-Control'] = 'public, max-age=3600'
        return response
