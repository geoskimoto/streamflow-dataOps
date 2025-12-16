"""Django views for streamflow application."""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.db.models import Q, Count, Max
from django.utils import timezone
from datetime import timedelta

from .models import (
    PullConfiguration,
    PullConfigurationStation,
    DataPullLog,
    PullStationProgress,
    Station,
    MasterStation,
    DischargeObservation,
)
from src.acquisition.tasks import execute_pull_configuration


class PullConfigurationListView(ListView):
    """List all pull configurations."""
    
    model = PullConfiguration
    template_name = 'streamflow/configuration_list.html'
    context_object_name = 'configurations'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = PullConfiguration.objects.annotate(
            station_count=Count('configuration_stations'),
            latest_log=Max('logs__start_time')
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
        
        return queryset.order_by('-created_at')


class PullConfigurationDetailView(DetailView):
    """Display details of a pull configuration."""
    
    model = PullConfiguration
    template_name = 'streamflow/configuration_detail.html'
    context_object_name = 'configuration'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = self.object
        
        # Get stations
        context['stations'] = config.configuration_stations.all()
        
        # Get recent logs
        context['recent_logs'] = config.logs.order_by('-start_time')[:10]
        
        # Get progress for each station
        context['progress'] = config.progress_records.select_related(
            'configuration'
        ).all()
        
        # Stats
        total_logs = config.logs.count()
        successful_logs = config.logs.filter(status='success').count()
        context['stats'] = {
            'total_runs': total_logs,
            'success_rate': (successful_logs / total_logs * 100) if total_logs > 0 else 0,
            'total_records': config.logs.aggregate(
                total=Count('records_processed')
            )['total'] or 0,
        }
        
        return context


class PullConfigurationCreateView(CreateView):
    """Create a new pull configuration."""
    
    model = PullConfiguration
    template_name = 'streamflow/configuration_form.html'
    fields = [
        'name', 'description', 'data_type', 'data_strategy',
        'pull_start_date', 'is_enabled', 'schedule_type', 'schedule_value'
    ]
    success_url = reverse_lazy('streamflow:configuration_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{form.instance.name}" created successfully!')
        return super().form_valid(form)


class PullConfigurationUpdateView(UpdateView):
    """Update an existing pull configuration."""
    
    model = PullConfiguration
    template_name = 'streamflow/configuration_form.html'
    fields = [
        'name', 'description', 'data_type', 'data_strategy',
        'pull_start_date', 'is_enabled', 'schedule_type', 'schedule_value'
    ]
    success_url = reverse_lazy('streamflow:configuration_list')
    
    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{form.instance.name}" updated successfully!')
        return super().form_valid(form)


class PullConfigurationDeleteView(DeleteView):
    """Delete a pull configuration."""
    
    model = PullConfiguration
    template_name = 'streamflow/configuration_confirm_delete.html'
    success_url = reverse_lazy('streamflow:configuration_list')
    
    def form_valid(self, form):
        messages.success(self.request, 'Configuration deleted successfully!')
        return super().form_valid(form)


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


def toggle_configuration(request, pk):
    """Toggle a configuration's enabled status."""
    
    config = get_object_or_404(PullConfiguration, pk=pk)
    config.is_enabled = not config.is_enabled
    config.save()
    
    status = 'enabled' if config.is_enabled else 'disabled'
    messages.success(request, f'Configuration "{config.name}" {status}.')
    
    return redirect('streamflow:configuration_detail', pk=pk)


class DataPullLogListView(ListView):
    """List all data pull logs."""
    
    model = DataPullLog
    template_name = 'streamflow/log_list.html'
    context_object_name = 'logs'
    paginate_by = 50
    
    def get_queryset(self):
        queryset = DataPullLog.objects.select_related('configuration')
        
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
        return context


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


def add_station_to_config(request, pk):
    """Add a station to a pull configuration."""
    
    if request.method == 'POST':
        config = get_object_or_404(PullConfiguration, pk=pk)
        
        station_number = request.POST.get('station_number')
        station_name = request.POST.get('station_name', '')
        huc_code = request.POST.get('huc_code', '')
        state = request.POST.get('state', '')
        
        # Check if station already exists in config
        if config.configuration_stations.filter(station_number=station_number).exists():
            messages.warning(request, f'Station {station_number} is already in this configuration.')
        else:
            PullConfigurationStation.objects.create(
                configuration=config,
                station_number=station_number,
                station_name=station_name,
                huc_code=huc_code,
                state=state
            )
            messages.success(request, f'Station {station_number} added to configuration.')
    
    return redirect('streamflow:configuration_detail', pk=pk)


def remove_station_from_config(request, pk, station_id):
    """Remove a station from a pull configuration."""
    
    config = get_object_or_404(PullConfiguration, pk=pk)
    station = get_object_or_404(PullConfigurationStation, pk=station_id, configuration=config)
    
    station_number = station.station_number
    station.delete()
    
    messages.success(request, f'Station {station_number} removed from configuration.')
    
    return redirect('streamflow:configuration_detail', pk=pk)


def dashboard(request):
    """Main dashboard view."""
    
    # Get recent statistics
    total_configs = PullConfiguration.objects.count()
    enabled_configs = PullConfiguration.objects.filter(is_enabled=True).count()
    
    # Recent logs (last 24 hours)
    recent_cutoff = timezone.now() - timedelta(hours=24)
    recent_logs = DataPullLog.objects.filter(start_time__gte=recent_cutoff)
    
    recent_success = recent_logs.filter(status='success').count()
    recent_failed = recent_logs.filter(status='failed').count()
    recent_running = recent_logs.filter(status='running').count()
    
    # Latest observations
    latest_observations = DischargeObservation.objects.select_related(
        'station'
    ).order_by('-observed_at')[:10]
    
    # Configurations needing attention (failed recently)
    failed_configs = PullConfiguration.objects.filter(
        logs__status='failed',
        logs__start_time__gte=recent_cutoff
    ).distinct()
    
    context = {
        'total_configs': total_configs,
        'enabled_configs': enabled_configs,
        'recent_success': recent_success,
        'recent_failed': recent_failed,
        'recent_running': recent_running,
        'latest_observations': latest_observations,
        'failed_configs': failed_configs,
        'recent_logs': DataPullLog.objects.order_by('-start_time')[:10],
    }
    
    return render(request, 'streamflow/dashboard.html', context)
