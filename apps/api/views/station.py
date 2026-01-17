"""ViewSets for Station API."""

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Q, Max

from apps.streamflow.models import Station, DischargeObservation
from apps.api.serializers import (
    StationSerializer,
    StationListSerializer,
    StationCreateSerializer,
)


class StationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing stations.
    
    list: Get all stations with filtering and search
    retrieve: Get a single station by ID
    create: Create a new station
    update: Update a station
    partial_update: Partially update a station
    destroy: Delete a station
    """
    
    queryset = Station.objects.all()
    serializer_class = StationSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['agency', 'state', 'is_active', 'huc_code']
    search_fields = ['station_number', 'name', 'basin']
    ordering_fields = ['station_number', 'name', 'agency', 'last_updated']
    ordering = ['station_number']
    lookup_field = 'station_number'
    lookup_url_kwarg = 'station_number'
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'list':
            return StationListSerializer
        elif self.action == 'create':
            return StationCreateSerializer
        return StationSerializer
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, station_number=None):
        """
        Get statistics for a station.
        
        Returns observation counts, data availability, and date ranges.
        """
        station = self.get_object()
        
        # Get discharge observation stats
        discharge_stats = DischargeObservation.objects.filter(
            station_number=station.station_number
        ).aggregate(
            total_count=Count('id'),
            realtime_count=Count('id', filter=Q(data_type='realtime_15min')),
            daily_count=Count('id', filter=Q(data_type='daily_mean')),
            latest_timestamp=Max('timestamp')
        )
        
        data = {
            'station_number': station.station_number,
            'name': station.name,
            'agency': station.agency,
            'observation_counts': {
                'total': discharge_stats['total_count'],
                'realtime_15min': discharge_stats['realtime_count'],
                'daily_mean': discharge_stats['daily_count'],
            },
            'latest_observation': discharge_stats['latest_timestamp'],
            'record_period': {
                'start': station.record_start_date,
                'end': station.record_end_date,
                'years': float(station.years_of_record) if station.years_of_record else None,
            }
        }
        
        return Response(data)
    
    @action(detail=False, methods=['get'])
    def by_region(self, request):
        """
        Get stations grouped by region (state or HUC).
        
        Query params:
        - group_by: 'state' or 'huc'
        """
        group_by = request.query_params.get('group_by', 'state')
        
        if group_by == 'state':
            grouped = Station.objects.values('state').annotate(
                count=Count('id')
            ).order_by('-count')
        elif group_by == 'huc':
            grouped = Station.objects.values('huc_code').annotate(
                count=Count('id')
            ).order_by('-count')
        else:
            return Response(
                {'error': 'group_by must be "state" or "huc"'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response(grouped)
