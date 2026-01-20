"""ViewSet for DataPullLog API."""

from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

from apps.streamflow.models import DataPullLog
from apps.api.serializers.log import DataPullLogSerializer, DataPullLogListSerializer
from apps.api.pagination import StandardResultsSetPagination


class DataPullLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for querying data pull execution logs.
    
    list: Get all data pull logs with filtering
    retrieve: Get a single log entry
    """
    
    queryset = DataPullLog.objects.all()
    serializer_class = DataPullLogSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['configuration', 'status']
    ordering_fields = ['start_time', 'end_time', 'records_processed']
    ordering = ['-start_time']
    
    def get_serializer_class(self):
        """Use lightweight serializer for list view."""
        if self.action == 'list':
            return DataPullLogListSerializer
        return DataPullLogSerializer
    
    def get_queryset(self):
        """Optimize queries with select_related."""
        return super().get_queryset().select_related('configuration')
