"""Analytics section views: StatisticsConfiguration CRUD, dashboard, station metadata browser."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.analytics.forms import StatisticsConfigurationForm
from apps.analytics.models import (
    FloodThreshold,
    StatisticsComputationLog,
    StatisticsConfiguration,
    StationMetadata,
)


@login_required
def analytics_dashboard(request):
    configs = StatisticsConfiguration.objects.annotate(
        log_count=Count('logs'),
    ).order_by('name')

    recent_logs = StatisticsComputationLog.objects.select_related('configuration').order_by('-started_at')[:20]

    total_metadata = StationMetadata.objects.count()
    total_thresholds = FloodThreshold.objects.count()

    return render(request, 'analytics/dashboard.html', {
        'configs': configs,
        'recent_logs': recent_logs,
        'total_metadata': total_metadata,
        'total_thresholds': total_thresholds,
        'enabled_count': configs.filter(is_enabled=True).count(),
    })


class StatisticsConfigurationListView(LoginRequiredMixin, ListView):
    model = StatisticsConfiguration
    template_name = 'analytics/configuration_list.html'
    context_object_name = 'configs'
    ordering = ['name']

    def get_queryset(self):
        qs = super().get_queryset().annotate(log_count=Count('logs'))
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        ct = self.request.GET.get('type', '')
        if ct:
            qs = qs.filter(computation_type=ct)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['computation_types'] = StatisticsConfiguration.COMPUTATION_TYPE_CHOICES
        return ctx


class StatisticsConfigurationCreateView(LoginRequiredMixin, CreateView):
    model = StatisticsConfiguration
    form_class = StatisticsConfigurationForm
    template_name = 'analytics/configuration_form.html'

    def get_success_url(self):
        return reverse_lazy('analytics:configuration_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{form.instance.name}" created.')
        return super().form_valid(form)


class StatisticsConfigurationDetailView(LoginRequiredMixin, DetailView):
    model = StatisticsConfiguration
    template_name = 'analytics/configuration_detail.html'
    context_object_name = 'config'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['logs'] = self.object.logs.order_by('-started_at')[:25]
        ctx['station_count'] = self.object.get_station_queryset().count()
        ctx['explicit_stations'] = self.object.stations.select_related('station').order_by('station__station_number')[:50]
        return ctx


class StatisticsConfigurationUpdateView(LoginRequiredMixin, UpdateView):
    model = StatisticsConfiguration
    form_class = StatisticsConfigurationForm
    template_name = 'analytics/configuration_form.html'

    def get_success_url(self):
        return reverse_lazy('analytics:configuration_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{form.instance.name}" updated.')
        return super().form_valid(form)


class StatisticsConfigurationDeleteView(LoginRequiredMixin, DeleteView):
    model = StatisticsConfiguration
    template_name = 'analytics/configuration_confirm_delete.html'
    success_url = reverse_lazy('analytics:configuration_list')
    context_object_name = 'config'

    def form_valid(self, form):
        messages.success(self.request, f'Configuration "{self.object.name}" deleted.')
        return super().form_valid(form)


@login_required
def trigger_statistics_config(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    config = get_object_or_404(StatisticsConfiguration, pk=pk)
    if config.computation_type == 'station_metadata':
        from src.analytics.tasks import run_station_metadata_task
        run_station_metadata_task.delay(config.id)
    elif config.computation_type == 'flood_thresholds':
        from src.analytics.tasks import run_flood_thresholds_task
        run_flood_thresholds_task.delay(config.id)
    messages.success(request, f'Triggered "{config.name}" — check logs for status.')
    return redirect('analytics:configuration_detail', pk=pk)


@login_required
def toggle_statistics_config(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    config = get_object_or_404(StatisticsConfiguration, pk=pk)
    config.is_enabled = not config.is_enabled
    config.save(update_fields=['is_enabled'])
    state = 'enabled' if config.is_enabled else 'disabled'
    messages.success(request, f'Configuration "{config.name}" {state}.')
    return redirect('analytics:configuration_detail', pk=pk)


@login_required
def station_metadata_list(request):
    qs = StationMetadata.objects.select_related('station').order_by('station__station_number')

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(station__station_number__icontains=q) | qs.filter(station__name__icontains=q)

    agency = request.GET.get('agency', '')
    if agency:
        qs = qs.filter(station__agency=agency)

    return render(request, 'analytics/station_metadata_list.html', {
        'metadata_list': qs[:500],
        'total': StationMetadata.objects.count(),
        'query': q,
        'agency': agency,
    })
