"""API views for the analytics app."""

import logging

from rest_framework import filters, viewsets

from apps.analytics.models import StatisticsComputationLog, StatisticsConfiguration
from apps.api.pagination import StandardResultsSetPagination
from apps.api.serializers.analytics import (
    StatisticsComputationLogSerializer,
    StatisticsConfigurationSerializer,
)

logger = logging.getLogger(__name__)


class StatisticsConfigurationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of analytics statistics configurations.

    Manual trigger is available via the Django analytics web UI (analytics:trigger view).
    A REST API trigger action can be added here if needed for external automation.
    """

    queryset = StatisticsConfiguration.objects.all()
    serializer_class = StatisticsConfigurationSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["name", "last_run_at", "computation_type"]
    ordering = ["name"]


class StatisticsComputationLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only log history for statistics computation runs."""

    queryset = StatisticsComputationLog.objects.select_related("configuration").all()
    serializer_class = StatisticsComputationLogSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["started_at", "status", "duration_seconds"]
    ordering = ["-started_at"]
