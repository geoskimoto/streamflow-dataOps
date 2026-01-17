"""Serializers for PullConfiguration model."""

from rest_framework import serializers
from apps.streamflow.models import PullConfiguration, PullConfigurationStation


class PullConfigurationSerializer(serializers.ModelSerializer):
    """Serializer for PullConfiguration model."""
    
    station_count = serializers.SerializerMethodField()
    
    class Meta:
        model = PullConfiguration
        fields = [
            'id',
            'name',
            'description',
            'data_type',
            'data_strategy',
            'pull_start_date',
            'is_enabled',
            'schedule_type',
            'schedule_value',
            'created_at',
            'updated_at',
            'station_count',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'station_count']
    
    def get_station_count(self, obj):
        """Get count of stations in configuration."""
        return PullConfigurationStation.objects.filter(configuration=obj).count()


class PullConfigurationDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer with station list."""
    
    station_count = serializers.SerializerMethodField()
    stations = serializers.SerializerMethodField()
    last_execution = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()
    
    class Meta:
        model = PullConfiguration
        fields = [
            'id',
            'name',
            'description',
            'data_type',
            'data_strategy',
            'pull_start_date',
            'is_enabled',
            'schedule_type',
            'schedule_value',
            'created_at',
            'updated_at',
            'station_count',
            'stations',
            'last_execution',
            'success_rate',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_station_count(self, obj):
        """Get count of stations."""
        return PullConfigurationStation.objects.filter(configuration=obj).count()
    
    def get_stations(self, obj):
        """Get list of station numbers."""
        return list(
            PullConfigurationStation.objects.filter(configuration=obj)
            .values_list('station_number', flat=True)
        )
    
    def get_last_execution(self, obj):
        """Get last execution info."""
        from apps.streamflow.models import DataPullLog
        last_log = DataPullLog.objects.filter(configuration=obj).order_by('-start_time').first()
        if last_log:
            return {
                'start_time': last_log.start_time,
                'status': last_log.status,
                'records_processed': last_log.records_processed,
            }
        return None
    
    def get_success_rate(self, obj):
        """Calculate success rate."""
        from apps.streamflow.models import DataPullLog
        from django.db.models import Count, Q
        
        stats = DataPullLog.objects.filter(configuration=obj).aggregate(
            total=Count('id'),
            successful=Count('id', filter=Q(status='success'))
        )
        
        if stats['total'] > 0:
            return round((stats['successful'] / stats['total']) * 100, 1)
        return None


class PullConfigurationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating configurations."""
    
    station_numbers = serializers.ListField(
        child=serializers.CharField(max_length=50),
        write_only=True,
        required=False,
        help_text="List of station numbers to include in this configuration"
    )
    
    class Meta:
        model = PullConfiguration
        fields = [
            'name',
            'description',
            'data_type',
            'data_strategy',
            'pull_start_date',
            'is_enabled',
            'schedule_type',
            'schedule_value',
            'station_numbers',
        ]
    
    def validate_name(self, value):
        """Validate name uniqueness."""
        if PullConfiguration.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError(
                f"Configuration with name '{value}' already exists."
            )
        return value
    
    def validate_schedule_value(self, value):
        """Validate cron expression for custom schedules."""
        schedule_type = self.initial_data.get('schedule_type')
        if schedule_type == 'custom' and value:
            parts = value.split()
            if len(parts) != 5:
                raise serializers.ValidationError(
                    "Invalid cron format. Expected 5 fields: minute hour day month weekday"
                )
        return value
    
    def create(self, validated_data):
        """Create configuration and associate stations."""
        station_numbers = validated_data.pop('station_numbers', [])
        config = PullConfiguration.objects.create(**validated_data)
        
        # Add stations
        for station_number in station_numbers:
            PullConfigurationStation.objects.create(
                configuration=config,
                station_number=station_number
            )
        
        return config
