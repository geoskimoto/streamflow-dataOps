"""ViewSets for Station API."""

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Q, Max

from apps.streamflow.models import Station, DischargeObservation, MasterStation
from apps.api.serializers import (
    StationSerializer,
    StationListSerializer,
    StationCreateSerializer,
)
from apps.api.serializers.station import MasterStationSerializer


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

    serializer_class = StationSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['agency', 'state', 'is_active', 'huc_code']
    search_fields = ['station_number', 'name', 'basin']
    ordering_fields = ['station_number', 'name', 'agency', 'last_updated']
    ordering = ['station_number']
    lookup_field = 'station_number'
    lookup_url_kwarg = 'station_number'

    def get_queryset(self):
        """Return stations with metadata pre-fetched to avoid N+1 queries."""
        return Station.objects.select_related('metadata').all()

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
            station=station
        ).aggregate(
            total_count=Count('id'),
            realtime_count=Count('id', filter=Q(type='realtime_15min')),
            daily_count=Count('id', filter=Q(type='daily_mean')),
            latest_timestamp=Max('observed_at')
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

    @action(detail=False, methods=['get'], url_path='last-observation')
    def last_observation(self, request):
        """Return all stations with their last observation date in one response.

        Intended for downstream apps that need to determine active gages
        without querying each station individually.
        """
        stations = (
            Station.objects.select_related('metadata')
            .order_by('station_number')
        )
        serializer = StationListSerializer(stations, many=True)
        return Response(serializer.data)


class MasterStationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for MasterStation cross-reference table.

    list:   GET /api/master-stations/               — all records with optional filters
    retrieve: GET /api/master-stations/{id}/        — single record by pk
    lookup: GET /api/master-stations/lookup/?id=X   — search any ID field across all networks
    """

    queryset = MasterStation.objects.all()
    serializer_class = MasterStationSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['agency', 'state_code', 'huc_code', 'rfc_code']
    search_fields = ['station_number', 'noaa_lid', 'station_name']
    ordering_fields = ['station_number', 'state_code', 'rfc_code']
    ordering = ['station_number']

    @action(detail=False, methods=['get'])
    def lookup(self, request):
        """
        Resolve any station ID to all known network IDs.

        Query params:
          id — a station_number, noaa_lid, or rfc_code value (required)

        Returns the matching MasterStation record with all ID fields, or 404.
        """
        query_id = request.query_params.get('id', '').strip()
        if not query_id:
            return Response(
                {'error': 'id query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        station = MasterStation.objects.filter(
            Q(station_number__iexact=query_id) |
            Q(noaa_lid__iexact=query_id)
        ).first()

        if station is None:
            return Response(
                {'error': f'No station found matching id "{query_id}"'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(MasterStationSerializer(station).data)
