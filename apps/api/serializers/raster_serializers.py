"""Serializers for raster data models."""

from rest_framework import serializers
from apps.streamflow.models import (
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterLayer,
    RasterPullConfiguration,
    RasterPullLog
)


class RasterDatasetSerializer(serializers.ModelSerializer):
    """Serializer for RasterDataset model."""
    
    variable_count = serializers.SerializerMethodField()
    
    class Meta:
        model = RasterDataset
        fields = [
            'id', 'name', 'collection_id', 'description',
            'resolution_m', 'temporal_resolution', 'update_frequency',
            'is_active', 'variable_count', 'created_at', 'updated_at',
            'data_source', 'daac', 'file_format'
        ]
    
    def get_variable_count(self, obj):
        """Get count of variables for this dataset."""
        return obj.variables.count()


class RasterVariableSerializer(serializers.ModelSerializer):
    """Serializer for RasterVariable model."""
    
    dataset_name = serializers.CharField(source='dataset.name', read_only=True)
    layer_count = serializers.SerializerMethodField()
    
    class Meta:
        model = RasterVariable
        fields = [
            'id', 'dataset', 'dataset_name', 'name', 'gee_band_name',
            'unit', 'description', 'min_valid_value', 'max_valid_value',
            'layer_count'
        ]
    
    def get_layer_count(self, obj):
        """Get count of layers for this variable."""
        return obj.layers.count()


class SpatialExtentSerializer(serializers.ModelSerializer):
    """Serializer for SpatialExtent model."""
    
    bbox = serializers.SerializerMethodField()
    layer_count = serializers.SerializerMethodField()
    
    class Meta:
        model = SpatialExtent
        fields = [
            'id', 'name', 'description',
            'min_lon', 'min_lat', 'max_lon', 'max_lat',
            'bbox', 'layer_count'
        ]
    
    def get_bbox(self, obj):
        """Get bounding box as list."""
        return obj.bbox
    
    def get_layer_count(self, obj):
        """Get count of layers for this extent."""
        return obj.layers.count()


class RasterLayerSerializer(serializers.ModelSerializer):
    """Serializer for RasterLayer model."""
    
    variable_name = serializers.CharField(source='variable.name', read_only=True)
    dataset_name = serializers.CharField(source='variable.dataset.name', read_only=True)
    extent_name = serializers.CharField(source='extent.name', read_only=True)
    download_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    
    class Meta:
        model = RasterLayer
        fields = [
            'id', 'variable', 'variable_name', 'dataset_name',
            'extent', 'extent_name', 'timestamp', 'date',
            'file_path', 'file_size_bytes', 'format', 'compression',
            'resolution_m', 'width_pixels', 'height_pixels', 'crs',
            'min_value', 'max_value', 'mean_value', 'std_dev',
            'no_data_value', 'is_valid', 'validation_errors',
            'download_url', 'thumbnail_url', 'processing_time_seconds'
        ]
    
    def get_download_url(self, obj):
        """Get download URL for raster file."""
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(f'/api/raster-layers/{obj.id}/download/')
        return f'/api/raster-layers/{obj.id}/download/'
    
    def get_thumbnail_url(self, obj):
        """Get thumbnail URL if available."""
        if obj.thumbnail_path:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(f'/api/raster-layers/{obj.id}/thumbnail/')
            return f'/api/raster-layers/{obj.id}/thumbnail/'
        return None


class RasterLayerListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing raster layers."""
    
    variable_name = serializers.CharField(source='variable.name', read_only=True)
    extent_name = serializers.CharField(source='extent.name', read_only=True)
    
    class Meta:
        model = RasterLayer
        fields = [
            'id', 'variable_name', 'extent_name', 'timestamp', 'date',
            'file_size_bytes', 'resolution_m', 'is_valid'
        ]


class RasterPullConfigurationSerializer(serializers.ModelSerializer):
    """Serializer for RasterPullConfiguration model."""
    
    dataset_name = serializers.CharField(source='dataset.name', read_only=True)
    variable_names = serializers.SerializerMethodField()
    extent_names = serializers.SerializerMethodField()
    
    class Meta:
        model = RasterPullConfiguration
        fields = [
            'id', 'name', 'dataset', 'dataset_name',
            'variable_names', 'extent_names', 'description',
            'schedule_enabled', 'schedule_cron', 'pull_frequency_hours',
            'lookback_days', 'max_age_hours', 'resampling_method',
            'target_resolution_m', 'apply_compression',
            'generate_thumbnails', 'validate_on_pull', 'calculate_statistics',
            'is_active', 'last_successful_pull', 'last_pull_attempt',
            'created_at', 'updated_at'
        ]
    
    def get_variable_names(self, obj):
        """Get list of variable names."""
        return list(obj.variables.values_list('name', flat=True))
    
    def get_extent_names(self, obj):
        """Get list of extent names."""
        return list(obj.extents.values_list('name', flat=True))


class RasterPullLogSerializer(serializers.ModelSerializer):
    """Serializer for RasterPullLog model."""
    
    configuration_name = serializers.CharField(source='configuration.name', read_only=True)
    duration_formatted = serializers.SerializerMethodField()
    
    class Meta:
        model = RasterPullLog
        fields = [
            'id', 'configuration', 'configuration_name', 'status',
            'started_at', 'completed_at', 'duration_seconds', 'duration_formatted',
            'layers_attempted', 'layers_successful', 'layers_failed',
            'layers_skipped', 'error_message', 'warnings', 'celery_task_id'
        ]
    
    def get_duration_formatted(self, obj):
        """Get formatted duration string."""
        if obj.duration_seconds:
            minutes = int(obj.duration_seconds // 60)
            seconds = int(obj.duration_seconds % 60)
            return f"{minutes}m {seconds}s"
        return None
