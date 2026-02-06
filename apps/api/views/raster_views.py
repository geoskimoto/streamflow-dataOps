"""API views for raster data."""

import os
from pathlib import Path
from datetime import datetime

from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.db.models import Q, Count, Avg, Min, Max
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterLayer,
    RasterPullConfiguration,
    RasterPullLog
)
from apps.api.serializers.raster_serializers import (
    RasterDatasetSerializer,
    RasterVariableSerializer,
    SpatialExtentSerializer,
    RasterLayerSerializer,
    RasterLayerListSerializer,
    RasterPullConfigurationSerializer,
    RasterPullLogSerializer
)
from src.acquisition.raster_processor import RasterProcessor


class RasterDatasetViewSet(viewsets.ReadOnlyModelViewSet):
    """API viewset for raster datasets."""
    
    queryset = RasterDataset.objects.all()
    serializer_class = RasterDatasetSerializer
    
    def get_queryset(self):
        """Filter queryset by query parameters."""
        queryset = super().get_queryset()
        
        # Filter by active status
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def variables(self, request, pk=None):
        """Get variables for this dataset."""
        dataset = self.get_object()
        variables = dataset.rastervariable_set.all()
        serializer = RasterVariableSerializer(variables, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def coverage(self, request, pk=None):
        """Get temporal coverage for this dataset."""
        dataset = self.get_object()
        
        # Get date range for each variable
        coverage = []
        for variable in dataset.rastervariable_set.all():
            layers = variable.rasterlayer_set.filter(is_valid=True)
            
            if layers.exists():
                coverage.append({
                    'variable': variable.name,
                    'layer_count': layers.count(),
                    'first_date': layers.earliest('timestamp').timestamp,
                    'last_date': layers.latest('timestamp').timestamp,
                })
        
        return Response(coverage)


class RasterVariableViewSet(viewsets.ReadOnlyModelViewSet):
    """API viewset for raster variables."""
    
    queryset = RasterVariable.objects.select_related('dataset').all()
    serializer_class = RasterVariableSerializer
    
    def get_queryset(self):
        """Filter queryset by query parameters."""
        queryset = super().get_queryset()
        
        # Filter by dataset
        dataset = self.request.query_params.get('dataset')
        if dataset:
            queryset = queryset.filter(dataset__name=dataset)
        
        return queryset


class SpatialExtentViewSet(viewsets.ReadOnlyModelViewSet):
    """API viewset for spatial extents."""
    
    queryset = SpatialExtent.objects.all()
    serializer_class = SpatialExtentSerializer


class RasterLayerViewSet(viewsets.ReadOnlyModelViewSet):
    """API viewset for raster layers."""
    
    queryset = RasterLayer.objects.select_related(
        'variable', 'variable__dataset', 'extent'
    ).all()
    
    def get_serializer_class(self):
        """Use different serializer for list vs detail."""
        if self.action == 'list':
            return RasterLayerListSerializer
        return RasterLayerSerializer
    
    def get_queryset(self):
        """Filter queryset by query parameters."""
        queryset = super().get_queryset()
        
        # Filter by variable
        variable = self.request.query_params.get('variable')
        if variable:
            queryset = queryset.filter(variable__name=variable)
        
        # Filter by dataset
        dataset = self.request.query_params.get('dataset')
        if dataset:
            queryset = queryset.filter(variable__dataset__name=dataset)
        
        # Filter by extent
        extent = self.request.query_params.get('extent')
        if extent:
            queryset = queryset.filter(extent__name=extent)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                queryset = queryset.filter(timestamp__gte=start_dt)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                queryset = queryset.filter(timestamp__lte=end_dt)
            except ValueError:
                pass
        
        # Filter by valid status
        is_valid = self.request.query_params.get('is_valid')
        if is_valid is not None:
            queryset = queryset.filter(is_valid=is_valid.lower() == 'true')
        
        # Order by timestamp (newest first by default)
        order = self.request.query_params.get('order', '-timestamp')
        queryset = queryset.order_by(order)
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download raster file."""
        layer = self.get_object()
        
        file_path = Path(settings.RASTER_ROOT) / layer.file_path
        
        if not file_path.exists():
            return Response(
                {'error': 'File not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        response = FileResponse(
            open(file_path, 'rb'),
            as_attachment=True,
            filename=file_path.name
        )
        response['Content-Type'] = 'image/tiff'
        response['Content-Length'] = file_path.stat().st_size
        
        return response
    
    @action(detail=True, methods=['get'])
    def thumbnail(self, request, pk=None):
        """Get raster thumbnail."""
        layer = self.get_object()
        
        if not layer.thumbnail_path:
            return Response(
                {'error': 'Thumbnail not available'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        thumb_path = Path(settings.RASTER_ROOT) / layer.thumbnail_path
        
        if not thumb_path.exists():
            return Response(
                {'error': 'Thumbnail file not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        response = FileResponse(
            open(thumb_path, 'rb'),
            content_type='image/png'
        )
        response['Content-Length'] = thumb_path.stat().st_size
        
        return response
    
    @action(detail=False, methods=['post'])
    def extract_points(self, request):
        """Extract raster values at specific coordinates."""
        layer_id = request.data.get('layer_id')
        coordinates = request.data.get('coordinates', [])
        
        if not layer_id or not coordinates:
            return Response(
                {'error': 'layer_id and coordinates required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            layer = RasterLayer.objects.get(id=layer_id)
        except RasterLayer.DoesNotExist:
            return Response(
                {'error': 'Layer not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        file_path = Path(settings.RASTER_ROOT) / layer.file_path
        
        if not file_path.exists():
            return Response(
                {'error': 'File not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            processor = RasterProcessor()
            values = processor.extract_point_values(file_path, coordinates)
            
            results = []
            for coord, value in zip(coordinates, values):
                results.append({
                    'lon': coord[0],
                    'lat': coord[1],
                    'value': value
                })
            
            return Response({
                'layer_id': layer_id,
                'variable': layer.variable.name,
                'timestamp': layer.timestamp,
                'unit': layer.variable.unit,
                'results': results
            })
            
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def coverage(self, request):
        """Get temporal coverage summary."""
        variable = request.query_params.get('variable')
        extent = request.query_params.get('extent')
        
        queryset = RasterLayer.objects.filter(is_valid=True)
        
        if variable:
            queryset = queryset.filter(variable__name=variable)
        
        if extent:
            queryset = queryset.filter(extent__name=extent)
        
        if not queryset.exists():
            return Response({
                'layer_count': 0,
                'first_date': None,
                'last_date': None,
                'date_range_days': 0
            })
        
        first_layer = queryset.earliest('timestamp')
        last_layer = queryset.latest('timestamp')
        
        date_range = (last_layer.timestamp - first_layer.timestamp).days
        
        return Response({
            'layer_count': queryset.count(),
            'first_date': first_layer.timestamp,
            'last_date': last_layer.timestamp,
            'date_range_days': date_range
        })
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get aggregated statistics."""
        variable = request.query_params.get('variable')
        extent = request.query_params.get('extent')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        queryset = RasterLayer.objects.filter(is_valid=True)
        
        if variable:
            queryset = queryset.filter(variable__name=variable)
        
        if extent:
            queryset = queryset.filter(extent__name=extent)
        
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date)
                queryset = queryset.filter(timestamp__gte=start_dt)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date)
                queryset = queryset.filter(timestamp__lte=end_dt)
            except ValueError:
                pass
        
        stats = queryset.aggregate(
            count=Count('id'),
            min_value=Min('min_value'),
            max_value=Max('max_value'),
            avg_mean=Avg('mean_value'),
            avg_std_dev=Avg('std_dev')
        )
        
        return Response(stats)


class RasterPullConfigurationViewSet(viewsets.ReadOnlyModelViewSet):
    """API viewset for raster pull configurations."""
    
    queryset = RasterPullConfiguration.objects.select_related('dataset').all()
    serializer_class = RasterPullConfigurationSerializer
    
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """Get pull logs for this configuration."""
        config = self.get_object()
        logs = config.rasterpulllog_set.all().order_by('-started_at')[:50]
        serializer = RasterPullLogSerializer(logs, many=True)
        return Response(serializer.data)


class RasterPullLogViewSet(viewsets.ReadOnlyModelViewSet):
    """API viewset for raster pull logs."""
    
    queryset = RasterPullLog.objects.select_related('configuration').all()
    serializer_class = RasterPullLogSerializer
    
    def get_queryset(self):
        """Filter queryset by query parameters."""
        queryset = super().get_queryset().order_by('-started_at')
        
        # Filter by status
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)
        
        # Filter by configuration
        config = self.request.query_params.get('configuration')
        if config:
            queryset = queryset.filter(configuration__name=config)
        
        return queryset
