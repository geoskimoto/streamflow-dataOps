"""Django views for streamflow application."""

import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.db.models import Q, Count, Max, Min, Avg
from django.db import models
from django.utils import timezone
from datetime import timedelta
import csv
import json

logger = logging.getLogger(__name__)

from .models import (
    PullConfiguration,
    PullConfigurationStation,
    DataPullLog,
    PullStationProgress,
    Station,
    MasterStation,
    DischargeObservation,
    ForecastRun,
    StationMapping,
    RasterLayer,
    RasterDataset,
    RasterVariable,
    SpatialExtent,
    RasterPullConfiguration,
    RasterPullLog,
)
from .forms import StationForm, PullConfigurationForm, RasterPullConfigurationForm
from .import_forms import StationImportForm
from src.acquisition.tasks import execute_pull_configuration
from decimal import Decimal, InvalidOperation


class PullConfigurationListView(LoginRequiredMixin, ListView):
    """List all pull configurations."""
    
    model = PullConfiguration
    template_name = 'streamflow/configuration_list.html'
    context_object_name = 'configurations'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = PullConfiguration.objects.annotate(
            station_count=Count('configuration_stations', distinct=True),
            latest_log=Max('logs__start_time'),
            total_runs=Count('logs', distinct=True),
            successful_runs=Count('logs', filter=Q(logs__status='success'), distinct=True)
        )
        
        # Search functionality
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )
        
        # Filter by status
        status = self.request.GET.get('status')
        if status == 'enabled':
            queryset = queryset.filter(is_enabled=True)
        elif status == 'disabled':
            queryset = queryset.filter(is_enabled=False)
        
        # Filter by data type
        data_type = self.request.GET.get('data_type')
        if data_type:
            queryset = queryset.filter(data_type=data_type)
        
        # Calculate success rate
        for config in queryset:
            if config.total_runs > 0:
                config.success_rate = (config.successful_runs / config.total_runs) * 100
            else:
                config.success_rate = 0
        
        return queryset.order_by('-created_at')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add summary stats
        all_configs = PullConfiguration.objects.all()
        context['enabled_count'] = all_configs.filter(is_enabled=True).count()
        context['total_stations'] = PullConfigurationStation.objects.values('station_number').distinct().count()
        
        # Recent runs (last 24 hours)
        from_time = timezone.now() - timedelta(days=1)
        context['recent_runs'] = DataPullLog.objects.filter(start_time__gte=from_time).count()
        
        return context


class PullConfigurationDetailView(LoginRequiredMixin, DetailView):
    """Display details of a pull configuration."""
    
    model = PullConfiguration
    template_name = 'streamflow/configuration_detail.html'
    context_object_name = 'configuration'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = self.object
        
        # Get stations
        context['stations'] = config.configuration_stations.all()
        
        # Get recent logs (last 10)
        recent_logs = config.logs.order_by('-start_time')[:10]
        context['recent_logs'] = recent_logs
        
        # Get progress for each station
        context['progress'] = config.progress_records.select_related(
            'configuration'
        ).all()
        
        # Comprehensive stats
        all_logs = config.logs.all()
        total_logs = all_logs.count()
        successful_logs = all_logs.filter(status='success').count()
        failed_logs = all_logs.filter(status='failed').count()
        running_logs = all_logs.filter(status='running').count()
        
        # Calculate total records across all successful runs
        total_records = all_logs.filter(
            status='success'
        ).aggregate(
            total=models.Sum('records_processed')
        )['total'] or 0
        
        # Recent performance (last 7 days)
        from django.utils import timezone
        from datetime import timedelta
        seven_days_ago = timezone.now() - timedelta(days=7)
        recent_runs = all_logs.filter(start_time__gte=seven_days_ago)
        recent_success = recent_runs.filter(status='success').count()
        recent_total = recent_runs.count()
        
        context['stats'] = {
            'total_runs': total_logs,
            'successful_runs': successful_logs,
            'failed_runs': failed_logs,
            'running_runs': running_logs,
            'success_rate': (successful_logs / total_logs * 100) if total_logs > 0 else 0,
            'total_records': total_records,
            'recent_success_rate': (recent_success / recent_total * 100) if recent_total > 0 else 0,
            'recent_runs_count': recent_total,
        }
        
        # Last successful run info
        last_success = all_logs.filter(status='success').order_by('-start_time').first()
        if last_success:
            context['last_success'] = {
                'time': last_success.start_time,
                'records': last_success.records_processed,
            }
        
        return context


class PullConfigurationCreateView(LoginRequiredMixin, CreateView):
    """Create a new pull configuration."""
    
    model = PullConfiguration
    form_class = PullConfigurationForm
    template_name = 'streamflow/configuration_form.html'
    success_url = reverse_lazy('streamflow:configuration_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{form.instance.name}" created successfully!')
        return super().form_valid(form)


class PullConfigurationUpdateView(LoginRequiredMixin, UpdateView):
    """Update an existing pull configuration."""
    
    model = PullConfiguration
    form_class = PullConfigurationForm
    template_name = 'streamflow/configuration_form.html'
    success_url = reverse_lazy('streamflow:configuration_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{form.instance.name}" updated successfully!')
        return super().form_valid(form)


class PullConfigurationDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a pull configuration."""
    
    model = PullConfiguration
    template_name = 'streamflow/configuration_confirm_delete.html'
    success_url = reverse_lazy('streamflow:configuration_list')
    
    def form_valid(self, form):
        messages.success(self.request, 'Configuration deleted successfully!')
        return super().form_valid(form)


@login_required
def trigger_pull(request, pk):
    """Manually trigger a pull configuration."""
    
    config = get_object_or_404(PullConfiguration, pk=pk)
    
    if not config.is_enabled:
        messages.error(request, 'Cannot trigger disabled configuration.')
        return redirect('streamflow:configuration_detail', pk=pk)
    
    # Trigger Celery task
    task = execute_pull_configuration.delay(config.id)
    
    messages.success(
        request,
        f'Pull task triggered for "{config.name}". Task ID: {task.id}'
    )
    
    return redirect('streamflow:configuration_detail', pk=pk)


@login_required
def toggle_configuration(request, pk):
    """Toggle a configuration's enabled status."""
    
    config = get_object_or_404(PullConfiguration, pk=pk)
    config.is_enabled = not config.is_enabled
    config.save()
    
    status = 'enabled' if config.is_enabled else 'disabled'
    messages.success(request, f'Configuration "{config.name}" {status}.')
    
    return redirect('streamflow:configuration_detail', pk=pk)


class DataPullLogListView(LoginRequiredMixin, ListView):
    """List all data pull logs with filtering and search."""
    
    model = DataPullLog
    template_name = 'streamflow/log_list.html'
    context_object_name = 'logs'
    paginate_by = 50
    
    def get_queryset(self):
        from django.db.models import F, ExpressionWrapper, DurationField
        
        queryset = DataPullLog.objects.select_related('configuration').annotate(
            duration=ExpressionWrapper(
                F('end_time') - F('start_time'),
                output_field=DurationField()
            )
        )
        
        # Search by error message
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(error_message__icontains=search) |
                Q(configuration__name__icontains=search)
            )
        
        # Filter by configuration
        config_id = self.request.GET.get('configuration')
        if config_id:
            queryset = queryset.filter(configuration_id=config_id)
        
        # Filter by status
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        # Filter by date range
        days = self.request.GET.get('days', 7)
        try:
            days = int(days)
            cutoff = timezone.now() - timedelta(days=days)
            queryset = queryset.filter(start_time__gte=cutoff)
        except ValueError:
            pass
        
        return queryset.order_by('-start_time')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['configurations'] = PullConfiguration.objects.all()
        
        # Summary stats
        logs = self.get_queryset()
        context['total_logs'] = logs.count()
        context['success_count'] = logs.filter(status='success').count()
        context['failed_count'] = logs.filter(status='failed').count()
        context['running_count'] = logs.filter(status='running').count()
        
        return context


@login_required
def station_search(request):
    """Search for stations in master station list."""
    
    query = request.GET.get('q', '')
    
    if len(query) < 2:
        return JsonResponse({'stations': []})
    
    stations = MasterStation.objects.filter(
        Q(station_number__icontains=query) |
        Q(station_name__icontains=query) |
        Q(state_code__icontains=query)
    )[:20]
    
    data = {
        'stations': [
            {
                'station_number': s.station_number,
                'station_name': s.station_name,
                'state_code': s.state_code,
                'huc_code': s.huc_code,
                'agency': s.agency,
            }
            for s in stations
        ]
    }
    
    return JsonResponse(data)


@login_required
def add_station_to_config(request, pk):
    """Add a station to a pull configuration."""
    
    if request.method == 'POST':
        config = get_object_or_404(PullConfiguration, pk=pk)
        
        station_number = request.POST.get('station_number')
        name = request.POST.get('station_name', '')
        huc_code = request.POST.get('huc_code', '')
        state = request.POST.get('state', '')
        
        # Check if station already exists in config
        if config.configuration_stations.filter(station_number=station_number).exists():
            messages.warning(request, f'Station {station_number} is already in this configuration.')
        else:
            PullConfigurationStation.objects.create(
                configuration=config,
                station_number=station_number,
                station_name=name,
                huc_code=huc_code,
                state=state
            )
            messages.success(request, f'Station {station_number} added to configuration.')
    
    return redirect('streamflow:configuration_detail', pk=pk)


@login_required
def remove_station_from_config(request, pk, station_id):
    """Remove a station from a pull configuration."""
    
    config = get_object_or_404(PullConfiguration, pk=pk)
    station = get_object_or_404(PullConfigurationStation, pk=station_id, configuration=config)
    
    station_number = station.station_number
    station.delete()
    
    messages.success(request, f'Station {station_number} removed from configuration.')
    
    return redirect('streamflow:configuration_detail', pk=pk)


@login_required
def log_detail(request, pk):
    """Detailed view of a data pull log with full error information."""
    
    log = get_object_or_404(DataPullLog.objects.select_related('configuration'), pk=pk)
    
    # Calculate duration if ended
    duration = None
    if log.end_time:
        duration = log.end_time - log.start_time
    
    # Get related logs (same configuration, recent)
    related_logs = DataPullLog.objects.filter(
        configuration=log.configuration
    ).exclude(
        pk=log.pk
    ).order_by('-start_time')[:10]
    
    context = {
        'log': log,
        'duration': duration,
        'related_logs': related_logs,
    }
    
    return render(request, 'streamflow/log_detail.html', context)


@login_required
def dashboard(request):
    """Main dashboard view with comprehensive monitoring."""
    
    # Configuration statistics
    total_configs = PullConfiguration.objects.count()
    enabled_configs = PullConfiguration.objects.filter(is_enabled=True).count()
    disabled_configs = total_configs - enabled_configs
    
    # Station statistics
    total_stations = Station.objects.count()
    active_stations = Station.objects.filter(is_active=True).count()
    
    # Recent logs (last 24 hours)
    recent_cutoff = timezone.now() - timedelta(hours=24)
    recent_logs = DataPullLog.objects.filter(start_time__gte=recent_cutoff)
    
    recent_success = recent_logs.filter(status='success').count()
    recent_failed = recent_logs.filter(status='failed').count()
    recent_running = recent_logs.filter(status='running').count()
    total_recent = recent_logs.count()
    
    # Success rate
    success_rate = (recent_success / total_recent * 100) if total_recent > 0 else 0
    
    # Data statistics
    total_observations = DischargeObservation.objects.count()
    # Get today's date in UTC for querying observed_at timestamps
    today_utc = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    observations_today = DischargeObservation.objects.filter(
        observed_at__gte=today_utc
    ).count()
    
    total_forecasts = ForecastRun.objects.count()
    forecasts_today = ForecastRun.objects.filter(run_date__gte=today_utc).count()

    # Latest observations with station info
    latest_observations = DischargeObservation.objects.select_related(
        'station'
    ).order_by('-observed_at')[:15]
    
    # Latest forecasts with station info
    latest_forecasts = ForecastRun.objects.select_related(
        'station'
    ).order_by('-run_date')[:15]
    
    # Configurations needing attention (failed recently)
    failed_configs = PullConfiguration.objects.filter(
        logs__status='failed',
        logs__start_time__gte=recent_cutoff
    ).distinct().annotate(
        fail_count=Count('logs', filter=Q(logs__status='failed', logs__start_time__gte=recent_cutoff))
    ).order_by('-fail_count')[:5]
    
    # Active configurations (enabled with recent activity)
    active_configs = PullConfiguration.objects.filter(
        is_enabled=True
    ).annotate(
        last_run=Max('logs__start_time'),
        recent_runs=Count('logs', filter=Q(logs__start_time__gte=recent_cutoff))
    ).order_by('-last_run')[:5]
    
    # System health indicators
    stale_data_threshold = timezone.now() - timedelta(days=7)
    stale_stations = Station.objects.filter(
        is_active=True,
        discharge_observations__observed_at__lt=stale_data_threshold
    ).distinct().count()
    
    # Gridded data statistics
    from apps.streamflow.models import RasterLayer, RasterPullConfiguration
    total_raster_layers = RasterLayer.objects.count()
    raster_layers_today = RasterLayer.objects.filter(
        created_at__gte=timezone.now().replace(hour=0, minute=0, second=0)
    ).count()
    total_raster_configs = RasterPullConfiguration.objects.count()
    enabled_raster_configs = RasterPullConfiguration.objects.filter(schedule_enabled=True).count()
    
    context = {
        # Configuration stats
        'total_configs': total_configs,
        'enabled_configs': enabled_configs,
        'disabled_configs': disabled_configs,
        
        # Station stats
        'total_stations': total_stations,
        'active_stations': active_stations,
        
        # Recent activity
        'recent_success': recent_success,
        'recent_failed': recent_failed,
        'recent_running': recent_running,
        'total_recent': total_recent,
        'success_rate': success_rate,
        
        # Data stats
        'total_observations': total_observations,
        'observations_today': observations_today,
        'total_forecasts': total_forecasts,
        'forecasts_today': forecasts_today,
        
        # Recent data
        'latest_observations': latest_observations,
        'latest_forecasts': latest_forecasts,
        'recent_logs': DataPullLog.objects.select_related('configuration').order_by('-start_time')[:15],
        
        # Alerts
        'failed_configs': failed_configs,
        'active_configs': active_configs,
        'stale_stations': stale_stations,
        
        # Gridded data stats
        'total_raster_layers': total_raster_layers,
        'raster_layers_today': raster_layers_today,
        'total_raster_configs': total_raster_configs,
        'enabled_raster_configs': enabled_raster_configs,
    }
    
    return render(request, 'streamflow/dashboard.html', context)


@login_required
def station_filter_options_ajax(request):
    """Return available filter options (states, rfcs, visibility flags) for an agency."""
    agency = request.GET.get('agency', '').strip()

    qs = MasterStation.objects.all()
    if agency:
        qs = qs.filter(agency=agency)

    states = sorted(
        qs.exclude(state_code='').values_list('state_code', flat=True).distinct()
    )

    rfcs = sorted(
        qs.exclude(rfc_code='').values_list('rfc_code', flat=True).distinct()
    )

    show_rfc = agency in ('', 'NOAA_RFC')
    show_huc = agency in ('', 'USGS')

    return JsonResponse({
        'states': states,
        'rfcs': rfcs,
        'show_rfc': show_rfc,
        'show_huc': show_huc,
    })


@login_required
def station_search_ajax(request):
    """AJAX endpoint for searching master stations."""
    
    query = request.GET.get('q', '').strip()
    state = request.GET.get('state', '').strip()
    huc = request.GET.get('huc', '').strip()
    rfc = request.GET.get('rfc', '').strip()
    agency = request.GET.get('agency', '').strip()
    limit = int(request.GET.get('limit', 100))
    offset = int(request.GET.get('offset', 0))
    
    # Build query
    stations = MasterStation.objects.all()
    
    # Apply filters
    if query:
        stations = stations.filter(
            Q(station_number__icontains=query) |
            Q(station_name__icontains=query)
        )
    
    if state:
        stations = stations.filter(state_code=state)
    
    if huc:
        stations = stations.filter(huc_code__startswith=huc)
    
    if rfc:
        stations = stations.filter(rfc_code=rfc)
    
    if agency:
        stations = stations.filter(agency=agency)
    
    # Get total count before pagination
    total_count = stations.count()

    # If ids_only requested, return just IDs and station_numbers (no pagination)
    ids_only = request.GET.get('ids_only', '').strip()
    if ids_only:
        station_data = list(stations.order_by('station_number').values_list('id', 'station_number'))
        return JsonResponse({
            'ids': [{'id': sid, 'station_number': snum} for sid, snum in station_data],
            'total': total_count,
        })

    # Apply ordering and pagination
    stations = stations.order_by('station_number')[offset:offset + limit]

    # Convert to JSON
    results = [
        {
            'id': station.id,
            'station_number': station.station_number,
            'station_name': station.station_name,
            'state_code': station.state_code,
            'huc_code': station.huc_code,
            'rfc_code': station.rfc_code,
            'agency': station.agency,
            'latitude': str(station.latitude) if station.latitude else None,
            'longitude': str(station.longitude) if station.longitude else None,
        }
        for station in stations
    ]

    return JsonResponse({
        'stations': results,
        'total': total_count,
        'offset': offset,
        'limit': limit,
        'has_more': (offset + limit) < total_count
    })


@login_required
def add_stations_to_config(request, pk):
    """Add selected stations to a configuration."""
    
    config = get_object_or_404(PullConfiguration, pk=pk)
    
    if request.method == 'POST':
        # Station IDs are sent as a single JSON array to avoid exceeding
        # DATA_UPLOAD_MAX_NUMBER_FIELDS when selecting thousands of stations.
        station_ids_json = request.POST.get('station_ids_json', '[]')
        try:
            station_ids = json.loads(station_ids_json)
        except (json.JSONDecodeError, TypeError):
            station_ids = []

        if not station_ids:
            messages.warning(request, 'No stations selected.')
            return redirect('streamflow:configuration_detail', pk=pk)
        
        added_count = 0
        already_exists_count = 0
        
        for station_id in station_ids:
            try:
                master_station = MasterStation.objects.get(id=station_id)
                
                # Check if already exists
                exists = PullConfigurationStation.objects.filter(
                    configuration=config,
                    station_number=master_station.station_number
                ).exists()
                
                if exists:
                    already_exists_count += 1
                    continue
                
                # Create configuration station
                PullConfigurationStation.objects.create(
                    configuration=config,
                    station_number=master_station.station_number,
                    station_name=master_station.station_name,
                    huc_code=master_station.huc_code,
                    state=master_station.state_code,
                )
                added_count += 1
            
            except MasterStation.DoesNotExist:
                continue
        
        if added_count > 0:
            messages.success(
                request,
                f'Added {added_count} station(s) to configuration.'
            )
        
        if already_exists_count > 0:
            messages.info(
                request,
                f'{already_exists_count} station(s) already in configuration.'
            )
        
        return redirect('streamflow:configuration_detail', pk=pk)
    
    # GET request - show station selection interface
    # Get current stations in config
    current_station_numbers = list(
        config.configuration_stations.values_list('station_number', flat=True)
    )

    context = {
        'configuration': config,
        'current_station_numbers': current_station_numbers,
    }
    
    return render(request, 'streamflow/add_stations.html', context)


# ============================================================================
# Station Management Views
# ============================================================================

class StationListView(LoginRequiredMixin, ListView):
    """List all stations with search and filtering."""
    
    model = Station
    template_name = 'streamflow/station_list.html'
    context_object_name = 'stations'
    paginate_by = 50
    
    def get_queryset(self):
        queryset = Station.objects.all()
        
        # Search functionality
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(station_number__icontains=search) |
                Q(name__icontains=search)
            )
        
        # Filter by agency
        agency = self.request.GET.get('agency')
        if agency:
            queryset = queryset.filter(agency=agency)
        
        # Filter by state
        state = self.request.GET.get('state')
        if state:
            queryset = queryset.filter(state=state)
        
        # Filter by basin
        basin = self.request.GET.get('basin')
        if basin:
            queryset = queryset.filter(basin__icontains=basin)
        
        # Filter by HUC code
        huc = self.request.GET.get('huc')
        if huc:
            queryset = queryset.filter(huc_code__startswith=huc)
        
        # Filter by active status
        is_active = self.request.GET.get('is_active')
        if is_active == 'true':
            queryset = queryset.filter(is_active=True)
        elif is_active == 'false':
            queryset = queryset.filter(is_active=False)
        
        # NEW: Filter by "configured only" (stations in at least one configuration)
        configured_only = self.request.GET.get('configured_only')
        if configured_only == 'true':
            from .models import PullConfigurationStation
            # Get all station numbers that are in at least one configuration
            configured_station_numbers = PullConfigurationStation.objects.values_list(
                'station_number', flat=True
            ).distinct()
            queryset = queryset.filter(station_number__in=configured_station_numbers)
        
        # Filter by RFC (query MasterStation via StationMapping)
        rfc = self.request.GET.get('rfc')
        if rfc:
            from .models import StationMapping, MasterStation
            # Get MasterStation IDs with this RFC code
            master_ids = MasterStation.objects.filter(
                rfc_code=rfc
            ).values_list('station_number', flat=True)
            
            # Get Station IDs that map to these MasterStations
            station_numbers = StationMapping.objects.filter(
                source_agency="STATION",
                target_agency="MASTER",
                target_id__in=master_ids
            ).values_list('source_id', flat=True)
            
            queryset = queryset.filter(station_number__in=station_numbers)
        
        # Filter by Configuration
        configuration = self.request.GET.get('configuration')
        if configuration:
            from .models import PullConfigurationStation
            # Get station numbers in this configuration
            station_numbers = PullConfigurationStation.objects.filter(
                configuration_id=configuration
            ).values_list('station_number', flat=True).distinct()
            queryset = queryset.filter(station_number__in=station_numbers)
        
        # Annotate with observation count
        queryset = queryset.annotate(
            observation_count=Count('discharge_observations')
        )
        
        # Sort
        sort = self.request.GET.get('sort', 'station_number')
        queryset = queryset.order_by(sort)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get unique values for filters
        context['agencies'] = Station.AGENCY_CHOICES
        context['states'] = Station.objects.values_list(
            'state', flat=True
        ).distinct().order_by('state')
        context['basins'] = Station.objects.filter(
            basin__isnull=False
        ).values_list('basin', flat=True).distinct().order_by('basin')[:50]
        
        # NEW: Get distinct RFC codes from MasterStation
        from .models import MasterStation
        context['rfcs'] = MasterStation.objects.filter(
            rfc_code__isnull=False
        ).exclude(rfc_code='').values_list(
            'rfc_code', flat=True
        ).distinct().order_by('rfc_code')
        
        # NEW: Get active configurations
        from .models import PullConfiguration
        context['configurations'] = PullConfiguration.objects.filter(
            is_enabled=True
        ).order_by('name')
        
        # Pass filter values back to template
        context['current_filters'] = {
            'search': self.request.GET.get('search', ''),
            'agency': self.request.GET.get('agency', ''),
            'state': self.request.GET.get('state', ''),
            'basin': self.request.GET.get('basin', ''),
            'huc': self.request.GET.get('huc', ''),
            'is_active': self.request.GET.get('is_active', ''),
            'rfc': self.request.GET.get('rfc', ''),
            'configuration': self.request.GET.get('configuration', ''),
            'configured_only': self.request.GET.get('configured_only', ''),  # NEW
            'sort': self.request.GET.get('sort', 'station_number'),
        }
        
        # Summary statistics
        total_stations = Station.objects.count()
        active_stations = Station.objects.filter(is_active=True).count()
        context['stats'] = {
            'total': total_stations,
            'active': active_stations,
            'inactive': total_stations - active_stations,
        }
        
        return context


class MasterStationListView(LoginRequiredMixin, ListView):
    """List all master stations with search and filtering."""
    
    model = MasterStation
    template_name = 'streamflow/master_station_list.html'
    context_object_name = 'stations'
    paginate_by = 100
    
    def get_queryset(self):
        queryset = MasterStation.objects.all()
        
        # Search functionality
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(station_number__icontains=search) |
                Q(station_name__icontains=search)
            )
        
        # Filter by agency
        agency = self.request.GET.get('agency')
        if agency:
            queryset = queryset.filter(agency=agency)
        
        # Filter by state
        state = self.request.GET.get('state')
        if state:
            queryset = queryset.filter(state_code=state)
        
        # Filter by RFC
        rfc = self.request.GET.get('rfc')
        if rfc:
            queryset = queryset.filter(rfc_code=rfc)
        
        # Filter by HUC code
        huc = self.request.GET.get('huc')
        if huc:
            queryset = queryset.filter(huc_code__startswith=huc)
        
        # Sort
        sort = self.request.GET.get('sort', 'station_number')
        queryset = queryset.order_by(sort)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get unique values for filters
        context['agencies'] = MasterStation.AGENCY_CHOICES
        context['states'] = MasterStation.objects.exclude(
            state_code=''
        ).values_list('state_code', flat=True).distinct().order_by('state_code')
        context['rfcs'] = MasterStation.objects.exclude(
            rfc_code=''
        ).values_list('rfc_code', flat=True).distinct().order_by('rfc_code')
        
        # Pass filter values back to template
        context['current_filters'] = {
            'search': self.request.GET.get('search', ''),
            'agency': self.request.GET.get('agency', ''),
            'state': self.request.GET.get('state', ''),
            'rfc': self.request.GET.get('rfc', ''),
            'huc': self.request.GET.get('huc', ''),
            'sort': self.request.GET.get('sort', 'station_number'),
        }
        
        # Summary statistics
        total_stations = MasterStation.objects.count()
        context['stats'] = {
            'total': total_stations,
        }
        
        return context


class StationDetailView(LoginRequiredMixin, DetailView):
    """Display details of a specific station."""
    
    model = Station
    template_name = 'streamflow/station_detail.html'
    context_object_name = 'station'
    slug_field = 'station_number'
    slug_url_kwarg = 'station_number'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        station = self.object
        
        # Recent observations (last 100)
        context['recent_observations'] = station.discharge_observations.order_by(
            '-observed_at'
        )[:100]
        
        # Observation statistics
        obs_stats = station.discharge_observations.aggregate(
            total=Count('id'),
            earliest=models.Min('observed_at'),
            latest=models.Max('observed_at'),
            avg_discharge=models.Avg('discharge'),
            max_discharge=models.Max('discharge'),
            min_discharge=models.Min('discharge'),
        )
        context['observation_stats'] = obs_stats
        
        # Configurations using this station
        context['configurations'] = PullConfigurationStation.objects.filter(
            station_number=station.station_number
        ).select_related('configuration')
        
        # Recent pull progress
        context['recent_progress'] = PullStationProgress.objects.filter(
            station_number=station.station_number
        ).select_related('configuration').order_by('-updated_at')[:10]
        
        # Forecast runs
        context['recent_forecasts'] = station.forecast_runs.order_by(
            '-run_date'
        )[:10]
        
        return context


class StationCreateView(LoginRequiredMixin, CreateView):
    """Create a new station."""
    
    model = Station
    form_class = StationForm
    template_name = 'streamflow/station_form.html'
    success_url = reverse_lazy('streamflow:station_list')
    
    def form_valid(self, form):
        messages.success(
            self.request,
            f'Station "{form.instance.station_number}" created successfully!'
        )
        return super().form_valid(form)


class StationUpdateView(LoginRequiredMixin, UpdateView):
    """Update an existing station."""
    
    model = Station
    form_class = StationForm
    template_name = 'streamflow/station_form.html'
    slug_field = 'station_number'
    slug_url_kwarg = 'station_number'
    
    def get_success_url(self):
        return reverse_lazy(
            'streamflow:station_detail',
            kwargs={'station_number': self.object.station_number}
        )
    
    def form_valid(self, form):
        messages.success(
            self.request,
            f'Station "{form.instance.station_number}" updated successfully!'
        )
        return super().form_valid(form)


@login_required
def toggle_station_status(request, station_number):
    """Toggle a station's active status."""
    
    station = get_object_or_404(Station, station_number=station_number)
    station.is_active = not station.is_active
    station.save()
    
    status = 'activated' if station.is_active else 'deactivated'
    messages.success(request, f'Station "{station.station_number}" {status}.')
    
    return redirect('streamflow:station_detail', station_number=station_number)


@login_required
def station_export_csv(request):
    """Export filtered stations to CSV."""
    
    import csv
    from django.http import HttpResponse
    
    # Get queryset using same filtering as list view
    view = StationListView()
    view.request = request
    queryset = view.get_queryset()
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="stations_export.csv"'
    
    writer = csv.writer(response)
    
    # Write header
    writer.writerow([
        'Station Number', 'Name', 'Agency', 'State', 'Basin',
        'HUC Code', 'Latitude', 'Longitude', 'Catchment Area (sq km)',
        'Years of Record', 'Is Active', 'Last Updated'
    ])
    
    # Write data
    for station in queryset:
        writer.writerow([
            station.station_number,
            station.name,
            station.agency,
            station.state,
            station.basin,
            station.huc_code,
            station.latitude,
            station.longitude,
            station.catchment_area,
            station.years_of_record,
            'Yes' if station.is_active else 'No',
            station.last_updated.strftime('%Y-%m-%d %H:%M:%S') if station.last_updated else '',
        ])
    
    return response


@login_required
def station_import(request):
    """Import stations from CSV file."""
    
    if request.method == 'POST':
        form = StationImportForm(request.POST, request.FILES)
        
        if form.is_valid():
            csv_file = request.FILES['csv_file']
            skip_duplicates = form.cleaned_data['skip_duplicates']
            update_existing = form.cleaned_data['update_existing']
            
            # Parse CSV
            parsed_rows = form.parsed_rows
            
            # Process stations
            created_count = 0
            updated_count = 0
            skipped_count = 0
            errors = []
            
            for idx, row in enumerate(parsed_rows, start=2):  # Start at 2 (header is row 1)
                try:
                    station_number = row.get('station_number', '').strip()
                    if not station_number:
                        errors.append(f'Row {idx}: Missing station_number')
                        continue
                    
                    # Check if station exists
                    exists = Station.objects.filter(station_number=station_number).exists()
                    
                    if exists and skip_duplicates and not update_existing:
                        skipped_count += 1
                        continue
                    
                    # Prepare station data
                    station_data = {
                        'station_number': station_number,
                        'name': row.get('name', '').strip(),
                        'agency': row.get('agency', '').strip().upper(),
                    }
                    
                    # Optional fields
                    if row.get('latitude'):
                        try:
                            station_data['latitude'] = Decimal(row['latitude'])
                        except (InvalidOperation, ValueError):
                            errors.append(f'Row {idx}: Invalid latitude value')
                            continue
                    
                    if row.get('longitude'):
                        try:
                            station_data['longitude'] = Decimal(row['longitude'])
                        except (InvalidOperation, ValueError):
                            errors.append(f'Row {idx}: Invalid longitude value')
                            continue
                    
                    if row.get('state'):
                        station_data['state'] = row['state'].strip()
                    
                    if row.get('huc_code'):
                        station_data['huc_code'] = row['huc_code'].strip()
                    
                    if row.get('basin'):
                        station_data['basin'] = row['basin'].strip()
                    
                    if row.get('catchment_area'):
                        try:
                            station_data['catchment_area'] = Decimal(row['catchment_area'])
                        except (InvalidOperation, ValueError):
                            pass  # Optional field, skip on error
                    
                    if row.get('timezone'):
                        station_data['timezone'] = row['timezone'].strip()
                    
                    # Create or update station
                    if exists and update_existing:
                        Station.objects.filter(station_number=station_number).update(**station_data)
                        updated_count += 1
                    elif not exists:
                        Station.objects.create(**station_data)
                        created_count += 1
                    
                except Exception as e:
                    errors.append(f'Row {idx}: {str(e)}')
            
            # Show results
            if created_count > 0:
                messages.success(request, f'Successfully created {created_count} station(s).')
            if updated_count > 0:
                messages.success(request, f'Successfully updated {updated_count} station(s).')
            if skipped_count > 0:
                messages.info(request, f'Skipped {skipped_count} duplicate station(s).')
            if errors:
                for error in errors[:10]:  # Show first 10 errors
                    messages.error(request, error)
                if len(errors) > 10:
                    messages.error(request, f'...and {len(errors) - 10} more errors.')
            
            if created_count > 0 or updated_count > 0:
                return redirect('streamflow:station_list')
    
    else:
        form = StationImportForm()
    
    context = {
        'form': form,
        'sample_csv': '''station_number,name,agency,latitude,longitude,state,huc_code,basin,catchment_area,timezone
01013500,Fish River near Fort Kent ME,USGS,47.2476898,-68.5850645,ME,01010001,St. John,873.45,America/New_York
01018035,East Branch St. Croix River at Kellyland ME,USGS,45.58451,-67.76979,ME,01010005,St. Croix,45.67,America/New_York'''
    }
    
    return render(request, 'streamflow/station_import.html', context)


@login_required
def sync_master_stations(request):
    """Sync stations from MasterStation table."""
    
    if request.method == 'POST':
        agency_filter = request.POST.get('agency', '')
        state_filter = request.POST.get('state', '')
        huc_filter = request.POST.get('huc', '')
        
        # Get master stations
        master_stations = MasterStation.objects.all()
        
        if agency_filter:
            # Map agency to master station field
            master_stations = master_stations.filter(
                Q(station_number__startswith='0') if agency_filter == 'USGS' else Q()
            )
        
        if state_filter:
            master_stations = master_stations.filter(state_code=state_filter)
        
        if huc_filter:
            master_stations = master_stations.filter(huc_code__startswith=huc_filter)
        
        created_count = 0
        updated_count = 0
        skipped_count = 0
        errors = []
        
        for master in master_stations:
            try:
                # Determine agency from station number pattern
                if master.station_number and master.station_number.isdigit():
                    agency = 'USGS'
                else:
                    agency = 'EC'  # Assume Environment Canada for non-numeric
                
                # Check if station already exists
                station, created = Station.objects.get_or_create(
                    station_number=master.station_number,
                    defaults={
                        'name': master.station_name or 'Unknown',
                        'agency': agency,
                        'latitude': master.latitude,
                        'longitude': master.longitude,
                        'state': master.state_code or '',
                        'huc_code': master.huc_code or '',
                        'basin': '',  # MasterStation doesn't have basin field
                        'catchment_area': master.drainage_area_sqmi,
                        'is_active': True,
                    }
                )
                
                if created:
                    created_count += 1
                else:
                    # Update existing station
                    updated = False
                    if master.latitude and not station.latitude:
                        station.latitude = master.latitude
                        updated = True
                    if master.longitude and not station.longitude:
                        station.longitude = master.longitude
                        updated = True
                    if master.drainage_area_sqkm and not station.catchment_area:
                        station.catchment_area = master.drainage_area_sqkm
                        updated = True
                    
                    if updated:
                        station.save()
                        updated_count += 1
                    else:
                        skipped_count += 1
                
            except Exception as e:
                errors.append(f'Station {master.station_number}: {str(e)}')
        
        # Show results
        if created_count > 0:
            messages.success(request, f'Successfully created {created_count} station(s) from master list.')
        if updated_count > 0:
            messages.success(request, f'Successfully updated {updated_count} station(s).')
        if skipped_count > 0:
            messages.info(request, f'Skipped {skipped_count} station(s) (already up to date).')
        if errors:
            for error in errors[:10]:
                messages.error(request, error)
            if len(errors) > 10:
                messages.error(request, f'...and {len(errors) - 10} more errors.')
        
        return redirect('streamflow:station_list')
    
    # GET request - show sync form
    master_count = MasterStation.objects.count()
    station_count = Station.objects.count()
    
    # Get available filters
    states = MasterStation.objects.values_list('state_code', flat=True).distinct().order_by('state_code')
    hucs = MasterStation.objects.values_list('huc_code', flat=True).distinct().order_by('huc_code')
    
    context = {
        'master_count': master_count,
        'station_count': station_count,
        'states': [s for s in states if s],
        'hucs': [h for h in hucs if h][:20],  # Limit to first 20 HUCs
    }
    
    return render(request, 'streamflow/station_sync.html', context)


# ============================================================================
# Gridded Data Views (Raster/GEE)
# ============================================================================

@login_required
def gridded_data_list(request):
    """List all gridded/raster data layers with filtering."""
    from .models import RasterLayer, RasterDataset, RasterVariable, SpatialExtent
    
    # Get filter parameters
    dataset_filter = request.GET.get('dataset', '')
    variable_filter = request.GET.get('variable', '')
    extent_filter = request.GET.get('extent', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # Base queryset
    layers = RasterLayer.objects.select_related(
        'variable__dataset', 'extent'
    ).filter(is_valid=True).order_by('-timestamp')
    
    # Apply filters
    if dataset_filter:
        layers = layers.filter(variable__dataset__name=dataset_filter)
    if variable_filter:
        layers = layers.filter(variable__name=variable_filter)
    if extent_filter:
        layers = layers.filter(extent__name=extent_filter)
    if start_date:
        layers = layers.filter(date__gte=start_date)
    if end_date:
        layers = layers.filter(date__lte=end_date)
    
    # Get filter options
    datasets = RasterDataset.objects.filter(is_active=True)
    variables = RasterVariable.objects.select_related('dataset')
    extents = SpatialExtent.objects.all()
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(layers, 50)
    page = request.GET.get('page', 1)
    layers_page = paginator.get_page(page)
    
    context = {
        'layers': layers_page,
        'datasets': datasets,
        'variables': variables,
        'extents': extents,
        'filters': {
            'dataset': dataset_filter,
            'variable': variable_filter,
            'extent': extent_filter,
            'start_date': start_date,
            'end_date': end_date,
        },
        'total_count': layers.count(),
    }
    
    return render(request, 'streamflow/gridded_data_list.html', context)


@login_required
def gridded_data_detail(request, layer_id):
    """Detail view for a single raster layer with map viewer."""
    from .models import RasterLayer
    
    layer = get_object_or_404(
        RasterLayer.objects.select_related('variable__dataset', 'extent'),
        id=layer_id
    )
    
    # Get extent bbox for map
    bbox = layer.extent.bbox if layer.extent else None
    
    context = {
        'layer': layer,
        'bbox': bbox,
    }
    
    return render(request, 'streamflow/gridded_data_detail.html', context)


@login_required
def raster_config_list(request):
    """List all raster pull configurations."""
    from .models import RasterPullConfiguration
    
    configs = RasterPullConfiguration.objects.prefetch_related(
        'variables', 'extents', 'pull_logs'
    ).annotate(
        total_runs=Count('pull_logs', distinct=True),
        successful_runs=Count('pull_logs', filter=Q(pull_logs__status='success'), distinct=True),
        failed_runs=Count('pull_logs', filter=Q(pull_logs__status='failed'), distinct=True),
        last_run=Max('pull_logs__started_at')
    ).order_by('-schedule_enabled', 'name')
    
    context = {
        'configurations': configs,
    }
    
    return render(request, 'streamflow/raster_config_list.html', context)


@login_required
def raster_config_detail(request, config_id):
    """Detail view for raster configuration with logs."""
    from .models import RasterPullConfiguration, RasterPullLog
    
    config = get_object_or_404(
        RasterPullConfiguration.objects.prefetch_related('variables', 'extents'),
        id=config_id
    )
    
    # Get recent logs
    logs = config.pull_logs.order_by('-started_at')[:20]
    
    context = {
        'config': config,
        'logs': logs,
    }
    
    return render(request, 'streamflow/raster_config_detail.html', context)


@login_required
def raster_config_create(request):
    """Create new raster pull configuration."""
    from .forms import RasterPullConfigurationForm
    
    if request.method == 'POST':
        form = RasterPullConfigurationForm(request.POST)
        if form.is_valid():
            config = form.save(commit=False)
            # Dataset is auto-populated in form.clean() from selected variables
            config.dataset = form.cleaned_data['dataset']
            config.save()
            form.save_m2m()  # Save many-to-many relationships
            messages.success(request, f'Configuration "{config.name}" created successfully!')
            return redirect('streamflow:raster_config_detail', config_id=config.id)
    else:
        form = RasterPullConfigurationForm()
    
    context = {
        'form': form,
        'action': 'Create',
    }
    
    return render(request, 'streamflow/raster_config_form.html', context)


@login_required
def raster_config_edit(request, config_id):
    """Edit existing raster pull configuration."""
    from .models import RasterPullConfiguration
    from .forms import RasterPullConfigurationForm
    
    config = get_object_or_404(RasterPullConfiguration, id=config_id)
    
    if request.method == 'POST':
        form = RasterPullConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            config = form.save(commit=False)
            # Dataset is auto-populated in form.clean() from selected variables
            config.dataset = form.cleaned_data['dataset']
            config.save()
            form.save_m2m()  # Save many-to-many relationships
            messages.success(request, f'Configuration "{config.name}" updated successfully!')
            return redirect('streamflow:raster_config_detail', config_id=config.id)
    else:
        form = RasterPullConfigurationForm(instance=config)
    
    context = {
        'form': form,
        'config': config,
        'action': 'Edit',
    }
    
    return render(request, 'streamflow/raster_config_form.html', context)


@login_required
def raster_config_delete(request, config_id):
    """Delete raster pull configuration."""
    from .models import RasterPullConfiguration
    
    config = get_object_or_404(RasterPullConfiguration, id=config_id)
    
    if request.method == 'POST':
        config_name = config.name
        config.delete()
        messages.success(request, f'Configuration "{config_name}" deleted successfully!')
        return redirect('streamflow:raster_config_list')
    
    context = {
        'config': config,
    }
    
    return render(request, 'streamflow/raster_config_confirm_delete.html', context)


@login_required
def trigger_raster_pull(request, config_id):
    """Trigger manual raster data pull."""
    from .models import RasterPullConfiguration, RasterPullLog
    from src.acquisition.raster_tasks import pull_raster_data
    from django.utils import timezone
    import traceback
    
    config = get_object_or_404(RasterPullConfiguration, id=config_id)
    
    if request.method == 'POST':
        # Check if we should run sync or async
        run_sync = request.POST.get('sync', 'false').lower() == 'true'
        
        try:
            if run_sync:
                # Run synchronously (blocking)
                messages.info(
                    request,
                    f'Running synchronous pull for "{config.name}"... This may take a few moments.'
                )
                result = pull_raster_data(config.id)
                
                if 'error' in result:
                    messages.error(request, f'Pull failed: {result["error"]}')
                else:
                    messages.success(
                        request,
                        f'Pull completed! Layers: {result.get("successful", 0)} successful, '
                        f'{result.get("failed", 0)} failed, {result.get("skipped", 0)} skipped'
                    )
            else:
                # Create log entry BEFORE queuing task (so failures are tracked)
                pull_log = RasterPullLog.objects.create(
                    configuration=config,
                    status='pending',
                    started_at=timezone.now()
                )
                
                # Try async first (requires Celery worker)
                try:
                    task = pull_raster_data.delay(config.id, pull_log_id=pull_log.id)
                    pull_log.celery_task_id = task.id
                    pull_log.status = 'running'
                    pull_log.save()
                    
                    messages.success(
                        request,
                        f'Async pull triggered for "{config.name}". Task ID: {task.id}'
                    )
                except Exception as celery_error:
                    # Update log with error
                    pull_log.status = 'failed'
                    pull_log.completed_at = timezone.now()
                    pull_log.error_message = f'Failed to queue task: {str(celery_error)}'
                    pull_log.error_traceback = traceback.format_exc()
                    pull_log.calculate_duration()
                    pull_log.save()
                    
                    # Inform user of the failure
                    messages.error(
                        request,
                        f'Failed to queue async task: {str(celery_error)}. Check that Celery worker is running.'
                    )
        except Exception as e:
            logger.error(f"Failed to trigger pull: {e}\n{traceback.format_exc()}")
            messages.error(request, f'Failed to trigger pull: {str(e)}')
        
        return redirect('streamflow:raster_config_detail', config_id=config.id)
    
    return redirect('streamflow:raster_config_list')


@login_required
def toggle_raster_configuration(request, config_id):
    """Toggle a raster configuration's enabled status."""
    from .models import RasterPullConfiguration
    
    config = get_object_or_404(RasterPullConfiguration, id=config_id)
    config.schedule_enabled = not config.schedule_enabled
    config.save()
    
    status = 'enabled' if config.schedule_enabled else 'disabled'
    messages.success(request, f'Configuration "{config.name}" {status}.')
    
    return redirect('streamflow:raster_config_list')


class RasterPullLogListView(LoginRequiredMixin, ListView):
    """List all raster pull logs with filtering and search."""
    
    model = RasterPullLog
    template_name = 'streamflow/raster_log_list.html'
    context_object_name = 'logs'
    paginate_by = 50
    
    def get_queryset(self):
        from .models import RasterPullLog
        
        queryset = RasterPullLog.objects.select_related('configuration')
        
        # Search by error message
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(error_message__icontains=search) |
                Q(configuration__name__icontains=search)
            )
        
        # Filter by configuration
        config_id = self.request.GET.get('configuration')
        if config_id:
            queryset = queryset.filter(configuration_id=config_id)
        
        # Filter by status
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        # Filter by date range
        days = self.request.GET.get('days', 7)
        try:
            days = int(days)
            cutoff = timezone.now() - timedelta(days=days)
            queryset = queryset.filter(started_at__gte=cutoff)
        except ValueError:
            pass
        
        return queryset.order_by('-started_at')
    
    def get_context_data(self, **kwargs):
        from .models import RasterPullConfiguration
        
        context = super().get_context_data(**kwargs)
        context['configurations'] = RasterPullConfiguration.objects.all()
        
        # Summary stats
        logs = self.get_queryset()
        context['total_logs'] = logs.count()
        context['success_count'] = logs.filter(status='success').count()
        context['failed_count'] = logs.filter(status='failed').count()
        context['running_count'] = logs.filter(status='running').count()
        context['partial_count'] = logs.filter(status='partial').count()
        
        # Aggregate stats
        from django.db.models import Sum, Avg
        stats = logs.aggregate(
            total_layers=Sum('layers_successful'),
            total_failed=Sum('layers_failed'),
            total_skipped=Sum('layers_skipped'),
            avg_duration=Avg('duration_seconds')
        )
        context['total_layers_pulled'] = stats['total_layers'] or 0
        context['total_layers_failed'] = stats['total_failed'] or 0
        context['total_layers_skipped'] = stats['total_skipped'] or 0
        context['avg_duration'] = stats['avg_duration'] or 0
        
        return context


@login_required
def system_diagnostics(request):
    """Display system diagnostics and health checks."""
    from .diagnostics import SystemDiagnostics
    
    diagnostics = SystemDiagnostics()
    
    # Run all checks
    database_check = diagnostics.check_database()
    redis_check = diagnostics.check_redis()
    celery_worker_check = diagnostics.check_celery_worker()
    celery_beat_check = diagnostics.check_celery_beat()
    data_providers_check = diagnostics.check_data_providers()
    storage_check = diagnostics.check_storage()
    timeseries_storage_check = diagnostics.check_timeseries_storage()
    application_check = diagnostics.check_application()
    recent_activity = diagnostics.check_recent_activity()
    
    # Compile all checks
    all_checks = {
        'database': database_check,
        'redis': redis_check,
        'celery_worker': celery_worker_check,
        'celery_beat': celery_beat_check,
        'data_providers': data_providers_check.get('apis', []),
        'storage': storage_check,
        'timeseries_storage': timeseries_storage_check,
        'application': application_check,
        'recent_activity': recent_activity
    }
    
    # Determine overall status
    overall_status = diagnostics.get_overall_status(all_checks)
    
    context = {
        'overall_status': overall_status,
        'last_updated': timezone.now(),
        **all_checks
    }
    
    return render(request, 'streamflow/system_diagnostics.html', context)
