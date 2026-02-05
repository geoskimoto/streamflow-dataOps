"""ViewSets for observation data API."""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.http import HttpResponse
from django.db.models import Min, Max, Avg, Count
import csv
from datetime import datetime

from apps.streamflow.models import DischargeObservation, Station
from apps.api.serializers import (
    DischargeObservationSerializer,
    ObservationStatisticsSerializer,
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
    # Only include actual model fields, not serializer properties
    filterset_fields = ['station', 'quality_code', 'type', 'unit']
    ordering_fields = ['observed_at', 'discharge']
    ordering = ['-observed_at']
    
    def get_queryset(self):
        """Filter observations by date range and station."""
        queryset = super().get_queryset()
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            queryset = queryset.filter(observed_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(observed_at__lte=end_date)
        
        # Filter by station number (via station relationship)
        station_number = self.request.query_params.get('station_number')
        if station_number:
            queryset = queryset.filter(station__station_number=station_number)
        
        return queryset.select_related('station')
    
    # CSV export disabled - not currently needed
    # @action(detail=False, methods=['get'])
    # def export_csv(self, request):
    #     """
    #     Export observations to CSV format.
    #     
    #     Query params:
    #     - station_number: Required
    #     - start_date: ISO format datetime
    #     - end_date: ISO format datetime
    #     - data_type: realtime_15min or daily_mean
    #     """
    #     station_number = request.query_params.get('station_number')
    #     if not station_number:
    #         return Response(
    #             {'error': 'station_number parameter is required'},
    #             status=status.HTTP_400_BAD_REQUEST
    #         )
    #     
    #     # Get observations
    #     observations = self.get_queryset().filter(station__station_number=station_number)
    #     
    #     # Create CSV response
    #     response = HttpResponse(content_type='text/csv')
    #     response['Content-Disposition'] = f'attachment; filename="discharge_{station_number}.csv"'
    #     
    #     writer = csv.writer(response)
    #     writer.writerow([
    #         'Station Number',
    #         'Observed At',
    #         'Discharge',
    #         'Unit',
    #         'Type',
    #         'Quality Code',
    #     ])
    #     
    #     for obs in observations:
    #         writer.writerow([
    #             obs.station.station_number,
    #             obs.observed_at.isoformat(),
    #             obs.discharge,
    #             obs.unit,
    #             obs.type,
    #             obs.quality_code,
    #         ])
    #     
    #     return response
    
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
        
        # Get latest observation
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
