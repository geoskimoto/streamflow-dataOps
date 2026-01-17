"""ViewSets for PullConfiguration API."""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db.models import Count, Q, Avg
from django.utils import timezone

from apps.streamflow.models import PullConfiguration, DataPullLog
from apps.api.serializers import (
    PullConfigurationSerializer,
    PullConfigurationDetailSerializer,
    PullConfigurationCreateSerializer,
)


class PullConfigurationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing pull configurations.
    
    list: Get all configurations with filtering
    retrieve: Get a single configuration with details
    create: Create a new configuration
    update: Update a configuration
    partial_update: Partially update a configuration
    destroy: Delete a configuration
    """
    
    queryset = PullConfiguration.objects.all()
    serializer_class = PullConfigurationSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['data_type', 'data_strategy', 'is_enabled', 'schedule_type']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'retrieve':
            return PullConfigurationDetailSerializer
        elif self.action == 'create':
            return PullConfigurationCreateSerializer
        return PullConfigurationSerializer
    
    @action(detail=True, methods=['post'])
    def enable(self, request, pk=None):
        """Enable a configuration."""
        config = self.get_object()
        config.is_enabled = True
        config.save()
        serializer = self.get_serializer(config)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def disable(self, request, pk=None):
        """Disable a configuration."""
        config = self.get_object()
        config.is_enabled = False
        config.save()
        serializer = self.get_serializer(config)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def trigger(self, request, pk=None):
        """
        Trigger a manual execution of this configuration.
        
        Starts a Celery task to pull data for all stations in this configuration.
        """
        config = self.get_object()
        
        # Import here to avoid circular imports
        from src.acquisition.tasks import execute_pull_configuration
        
        # Start async task
        task = execute_pull_configuration.delay(config.id)
        
        return Response({
            'message': f'Pull configuration "{config.name}" triggered successfully',
            'task_id': task.id,
            'configuration_id': config.id,
        }, status=status.HTTP_202_ACCEPTED)
    
    @action(detail=True, methods=['get'])
    def execution_history(self, request, pk=None):
        """
        Get execution history for this configuration.
        
        Query params:
        - limit: Number of recent executions to return (default: 20)
        - status: Filter by status (success, failed, running)
        """
        config = self.get_object()
        limit = int(request.query_params.get('limit', 20))
        status_filter = request.query_params.get('status')
        
        logs = DataPullLog.objects.filter(configuration=config)
        
        if status_filter:
            logs = logs.filter(status=status_filter)
        
        logs = logs.order_by('-start_time')[:limit]
        
        data = [{
            'id': log.id,
            'start_time': log.start_time,
            'end_time': log.end_time,
            'status': log.status,
            'records_processed': log.records_processed,
            'stations_processed': log.stations_processed,
            'error_message': log.error_message,
            'duration_seconds': (log.end_time - log.start_time).total_seconds() if log.end_time else None,
        } for log in logs]
        
        return Response(data)
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """
        Get detailed statistics for this configuration.
        
        Includes success rates, performance metrics, and data quality info.
        """
        config = self.get_object()
        
        # Get execution stats
        logs = DataPullLog.objects.filter(configuration=config)
        
        stats = logs.aggregate(
            total_executions=Count('id'),
            successful=Count('id', filter=Q(status='success')),
            failed=Count('id', filter=Q(status='failed')),
            total_records=Count('records_processed'),
            avg_duration=Avg('end_time') - Avg('start_time'),
        )
        
        # Calculate success rate
        success_rate = 0
        if stats['total_executions'] > 0:
            success_rate = (stats['successful'] / stats['total_executions']) * 100
        
        # Get latest execution
        latest_log = logs.order_by('-start_time').first()
        
        data = {
            'configuration_id': config.id,
            'configuration_name': config.name,
            'execution_stats': {
                'total_executions': stats['total_executions'],
                'successful': stats['successful'],
                'failed': stats['failed'],
                'success_rate': round(success_rate, 1),
            },
            'data_stats': {
                'total_records_processed': stats['total_records'],
            },
            'latest_execution': {
                'start_time': latest_log.start_time if latest_log else None,
                'status': latest_log.status if latest_log else None,
                'records_processed': latest_log.records_processed if latest_log else None,
            } if latest_log else None,
        }
        
        return Response(data)
