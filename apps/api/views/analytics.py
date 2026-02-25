"""API views for the analytics app."""

import logging

from drf_spectacular.utils import OpenApiParameter, extend_schema
from drf_spectacular.openapi import OpenApiTypes
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.analytics.models import ComputationLog, ScheduledComputation
from apps.api.pagination import StandardResultsSetPagination
from apps.api.serializers.analytics import (
    ComputationLogSerializer,
    ScheduledComputationListSerializer,
    ScheduledComputationSerializer,
)
from src.analytics.tasks import compute_flow_percentile_bands

logger = logging.getLogger(__name__)


class ScheduledComputationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of the analytics computation registry.
    Supports listing all computations, retrieving detail with recent logs,
    and triggering a manual run.
    """

    queryset = ScheduledComputation.objects.all()
    serializer_class = ScheduledComputationSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["name", "last_run_at", "last_run_status"]
    ordering = ["name"]

    def get_serializer_class(self):
        if self.action == "list":
            return ScheduledComputationListSerializer
        return ScheduledComputationSerializer

    @extend_schema(
        responses={202: {"type": "object", "properties": {
            "detail": {"type": "string"},
            "task_id": {"type": "string"},
        }}},
    )
    @action(detail=True, methods=["post"])
    def trigger(self, request, pk=None):
        """Manually trigger a computation run outside of its schedule."""
        computation = self.get_object()

        TASK_MAP = {
            "src.analytics.tasks.compute_flow_percentile_bands": compute_flow_percentile_bands,
        }

        task_fn = TASK_MAP.get(computation.task_path)
        if not task_fn:
            return Response(
                {"detail": f"No runnable task registered for '{computation.task_path}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task = task_fn.delay()
        logger.info(f"Manual trigger for '{computation.name}': task_id={task.id}")

        return Response(
            {"detail": f"'{computation.name}' triggered.", "task_id": task.id},
            status=status.HTTP_202_ACCEPTED,
        )


class ComputationLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only log history for analytics computation runs."""

    queryset = ComputationLog.objects.select_related("computation").all()
    serializer_class = ComputationLogSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["started_at", "status", "duration_seconds"]
    ordering = ["-started_at"]
